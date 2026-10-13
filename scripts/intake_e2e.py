"""End-to-end check of dictation intake (email + Google Form) with FAKE inputs — no mailbox, no
Google account, no patient data. Runs the real intake code, the real queue and the real model into a
THROWAWAY database, and prints only the note's STRUCTURE (headings + lengths).

    python scripts/intake_e2e.py            # email -> one real note; form -> queued only
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.integrations import email_intake as ei  # noqa: E402
from app.integrations import form_intake as fi  # noqa: E402
from app.storage import db, repository  # noqa: E402
from app.ui import server  # noqa: E402

FAKE_DICTATION = (
    "Daily visit. Patient reports right knee pain three out of ten, no falls since last visit. "
    "Gait training fifteen minutes, two hundred feet with a single point cane, standby assist, "
    "verbal cues for step length. Neuromuscular re-education ten minutes, tandem stance three times "
    "twenty seconds with contact guard. Therapeutic exercise fifteen minutes, sit to stand three "
    "times ten and step ups two times ten. Total treatment time forty minutes. Tolerated well with "
    "mild fatigue, balance improving, still needs cues on turns. Plan continue two times a week.")


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cadence_intake_e2e_"))
    db.ENC_PATH, db.KEYFILE = tmp / "cadence.db.enc", tmp / ".keyfile"
    db.init()
    patches = [patch.object(ei, "_dir", lambda: tmp), patch.object(fi, "_dir", lambda: tmp)]
    for p in patches:
        p.start()
    try:
        ei.save_settings({"enabled": True, "mailboxes": [{"address": "info@sdmobilept.com",
                                                          "password": "fake-not-used"}]})
        fake_mail = ei.IncomingEmail("info@sdmobilept.com", "<e2e-1@test>",
                                     "Cadence visit 10/13/2026", "pt@sdmobilept.com",
                                     date(2026, 10, 13), FAKE_DICTATION, b"1")
        stranger = ei.IncomingEmail("info@sdmobilept.com", "<e2e-2@test>", "Cadence 10/13/2026",
                                    "someone@gmail.com", date(2026, 10, 13), FAKE_DICTATION, b"2")

        def fake_fetch(mb, known_ids, resend_ids):
            # The real filter runs here too: the gmail.com sender must be skipped.
            out, skipped = [], []
            for m in (fake_mail, stranger):
                if m.message_id in known_ids and m.message_id not in resend_ids:
                    continue
                (out if ei.sender_allowed(m.sender, mb.allowed_senders) else skipped).append(m)
            return out, [s.sender for s in skipped]

        with patch.object(ei, "fetch_new", fake_fetch), patch.object(ei, "mark_seen", lambda *a: None):
            r1 = await server._email_check_once()
            r2 = await server._email_check_once()
        print("email check 1:", r1["result"], "| check 2:", r2["result"])
        assert r1["queued"] == 1 and r2["queued"] == 0, "exactly one note, never twice"
        assert any("gmail.com" in s for s in r1["skipped"]), "personal-account sender must be skipped"

        fi.save_settings({"enabled": True, "spreadsheet_id": "x" * 30})
        row = fi.FormRow(2, "row2:10/13/2026 09:00:00", date(2026, 10, 13), "pt@sdmobilept.com",
                         "10/12/2026", "Re-evaluation / Progress Report", FAKE_DICTATION, "")
        marks = {}
        with patch.object(fi, "fetch_rows", lambda: [row]), \
             patch.object(fi, "write_status", lambda m: marks.update(m)):
            f1 = await server._form_check_once()
        print("form check:", f1["result"], "| status written:", marks)
        assert f1["queued"] == 1 and "Queued in Cadence" in marks[2]

        jobs = server._job_queue.list()
        print("queued jobs:", [(j["patient_name"], j["form_name"], j["status"]) for j in jobs])
        form_job = next(j for j in jobs if j["form_id"] == "reeval")
        server._job_queue.cancel(form_job["id"])          # one real generation only (laptop heat)

        email_job = next(j for j in jobs if j["form_id"] == "followup")
        t0 = time.time()
        while True:
            job = server._job_queue.get(email_job["id"])
            if job.finished:
                break
            await asyncio.sleep(5)
        res = job.result or {}
        print(f"email note finished in {time.time() - t0:.0f}s, status {job.status}, "
              f"visit_date {res.get('visit_date')}")
        for s in res.get("sections", []):
            print(f"   {s['heading'][:44]!r}: {len(s['body'])} chars")
        pts = repository.list_patients()
        print("patients created:", [(p["name"], p["dob"]) for p in pts])
        incomplete = [m for m in res.get("missing_info", []) if m.startswith("INCOMPLETE")]
        print("incomplete-note warning:", bool(incomplete))
        await server._job_queue.stop()
        return 0 if job.status == "done" and res.get("sections") and not incomplete else 1
    finally:
        for p in patches:
            p.stop()
        db.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
