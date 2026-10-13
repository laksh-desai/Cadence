"""Intake from outside the app — emailed dictation and the Google Form (2026-10).

Pure parsing is tested directly; the queue flow is tested with a fake mailbox, in a throwaway
database, so no real mail account or patient data is ever touched.
"""

import asyncio
import email
import email.policy
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.integrations import email_intake as ei
from app.integrations import form_intake as fi


def _msg(raw: str):
    return email.message_from_string(raw, policy=email.policy.default)


class SenderTests(unittest.TestCase):
    def test_practice_domain_only(self):
        self.assertTrue(ei.sender_allowed("PT <pt@sdmobilept.com>", ["sdmobilept.com"]))
        self.assertFalse(ei.sender_allowed("someone@gmail.com", ["sdmobilept.com"]))

    def test_lookalike_domain_is_rejected(self):
        self.assertFalse(ei.sender_allowed("x@sdmobilept.com.evil.net", ["sdmobilept.com"]))
        self.assertFalse(ei.sender_allowed("x@evilsdmobilept.com", ["sdmobilept.com"]))

    def test_exact_address_allowlist(self):
        self.assertTrue(ei.sender_allowed("a@x.org", ["a@x.org"]))
        self.assertFalse(ei.sender_allowed("b@x.org", ["a@x.org"]))


class VisitDateTests(unittest.TestCase):
    def test_subject_date(self):
        d, where = ei.parse_visit_date("Cadence 10/12/2026 daily", "", date(2026, 10, 13))
        self.assertEqual(d, date(2026, 10, 12))

    def test_labelled_body_date_wins_over_other_dates(self):
        body = "Patient seen today.\nVisit date: May 8, 2026\nFirst injection 05/05/2026."
        d, where = ei.parse_visit_date("Cadence note", body, date(2026, 5, 9))
        self.assertEqual(d, date(2026, 5, 8))
        self.assertIn("labelled", where)

    def test_iso_and_written_forms(self):
        self.assertEqual(ei.parse_visit_date("Cadence 2026-10-01", "")[0], date(2026, 10, 1))
        self.assertEqual(ei.parse_visit_date("Cadence", "seen 3 Oct 2026", date(2026, 10, 5))[0],
                         date(2026, 10, 3))

    def test_future_date_is_rejected_and_email_date_used(self):
        d, where = ei.parse_visit_date("Cadence 12/31/2030", "", date(2026, 10, 12))
        self.assertEqual((d, where), (date(2026, 10, 12), "email date"))


class FormTypeTests(unittest.TestCase):
    def test_subject_keywords(self):
        self.assertEqual(ei.form_for_subject("Cadence daily 10/12"), "followup")
        self.assertEqual(ei.form_for_subject("Cadence re-eval visit 10"), "reeval")
        self.assertEqual(ei.form_for_subject("Cadence Initial Eval"), "initial")
        self.assertEqual(ei.form_for_subject("Cadence discharge"), "discharge")

    def test_form_choices(self):
        self.assertEqual(fi.form_for_choice("Daily Visit"), "followup")
        self.assertEqual(fi.form_for_choice("Re-evaluation / Progress Report"), "reeval")
        self.assertEqual(fi.form_for_choice("Initial Evaluation"), "initial")
        self.assertEqual(fi.form_for_choice("Discharge Summary"), "discharge")


class BodyTests(unittest.TestCase):
    def test_reply_chain_and_signature_removed(self):
        m = _msg("Subject: Cadence\nContent-Type: text/plain\n\nGait training 15 minutes.\n\n--\nDr PT\n"
                 "On Mon, Oct 12, 2026 at 9:00 AM Someone wrote:\n> old text\n")
        self.assertEqual(ei.body_text(m), "Gait training 15 minutes.")

    def test_html_only_email(self):
        m = _msg("Subject: Cadence\nContent-Type: text/html\n\n<p>Gait training<br>15 minutes</p>")
        self.assertEqual(ei.body_text(m), "Gait training\n15 minutes")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cadence_intake_"))
        self.p = patch("app.integrations.email_intake._dir", lambda: self.tmp)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_mailbox_and_password_never_returned(self):
        self.assertEqual(ei.public_settings()["mailboxes"][0]["address"], ei.DEFAULT_MAILBOX)
        out = ei.save_settings({"enabled": True, "mailboxes": [
            {"address": "info@sdmobilept.com", "password": "abcd efgh ijkl mnop"}]})
        self.assertTrue(out["mailboxes"][0]["has_password"])
        self.assertNotIn("abcd", str(out))
        raw = (self.tmp / ei.SETTINGS_FILENAME).read_text()
        self.assertNotIn("abcdefgh", raw, "password must be stored encrypted")
        self.assertEqual(ei.mailboxes()[0].password, "abcdefghijklmnop")

    def test_blank_password_keeps_the_saved_one_and_mailboxes_can_be_added(self):
        ei.save_settings({"mailboxes": [{"address": "info@sdmobilept.com", "password": "pw1"}]})
        ei.save_settings({"mailboxes": [{"address": "info@sdmobilept.com", "password": ""},
                                        {"address": "pt2@sdmobilept.com", "password": "pw2"}]})
        boxes = {m.address: m.password for m in ei.mailboxes()}
        self.assertEqual(boxes, {"info@sdmobilept.com": "pw1", "pt2@sdmobilept.com": "pw2"})

    def test_bad_address_rejected(self):
        with self.assertRaises(ei.SettingsError):
            ei.save_settings({"mailboxes": [{"address": "not-an-email"}]})


class QueueFlowTests(unittest.TestCase):
    """End to end with a FAKE mailbox: one email -> one Unknown patient (visit date as DOB) -> one
    queued Daily Visit; a second check does not queue it again."""

    def setUp(self):
        from app.storage import db
        from app.ui import server
        self.db, self.server = db, server
        self.tmp = Path(tempfile.mkdtemp(prefix="cadence_intake_flow_"))
        self._orig = (db.ENC_PATH, db.KEYFILE)
        db.ENC_PATH, db.KEYFILE = self.tmp / "cadence.db.enc", self.tmp / ".keyfile"
        db.init()
        self.patches = [patch("app.integrations.email_intake._dir", lambda: self.tmp)]
        for p in self.patches:
            p.start()
        ei.save_settings({"enabled": True, "mailboxes": [
            {"address": "info@sdmobilept.com", "password": "pw"}]})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.db.shutdown()
        self.db.ENC_PATH, self.db.KEYFILE = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_email_one_unknown_patient_one_job(self):
        from app.storage import repository
        mail = ei.IncomingEmail("info@sdmobilept.com", "<m1@x>", "Cadence daily 10/12/2026",
                                "pt@sdmobilept.com", date(2026, 10, 12),
                                "Gait training fifteen minutes with walker.", b"7")
        submitted = []

        def fake_fetch(mb, known_ids, resend_ids):
            return ([mail] if "<m1@x>" not in known_ids else []), []

        def fake_submit(**kw):
            submitted.append(kw)
            return type("J", (), {"id": f"job{len(submitted)}"})()

        async def run():
            with patch.object(ei, "fetch_new", fake_fetch), patch.object(ei, "mark_seen", lambda *a: None), \
                 patch.object(self.server._job_queue, "submit", fake_submit), \
                 patch.object(self.server, "_intake_job_alive", lambda j: True):
                first = await self.server._email_check_once()
                second = await self.server._email_check_once()
            return first, second

        first, second = asyncio.run(run())
        self.assertEqual((first["queued"], second["queued"]), (1, 0))
        self.assertEqual(len(submitted), 1)
        payload = submitted[0]["payload"]
        self.assertEqual((payload["form_id"], payload["visit_date"], payload["use_prior"]),
                         ("followup", "2026-10-12", False))
        p = repository.get_patient(payload["patient_id"])
        self.assertEqual((p["name"], p["dob"]), ("Unknown patient", "10/12/2026"))


if __name__ == "__main__":
    unittest.main()
