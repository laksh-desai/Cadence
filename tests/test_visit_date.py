"""The visit date a note documents.

It is the date the Office Ally extension matches against the encounter date
(docs/OfficeAlly_Integration_Rules.md, rule 3.2). Before it existed, a note's only date was when it
was SAVED, so a note written up the next morning could never match its visit's encounter.

    .venv/Scripts/python.exe -m unittest tests.test_visit_date -v
"""

import datetime
import shutil
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.storage import db, repository
from app.ui.schemas import SaveNoteRequest


class VisitDateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        self._orig = (db.ENC_PATH, db.KEYFILE)
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"
        db.init()
        self.pid = repository.create_patient(name="Test Patient", dob=None, mrn="155793457", condition=None)["id"]

    def tearDown(self):
        db.shutdown()
        db.ENC_PATH, db.KEYFILE = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _note(self, **kw):
        return repository.create_note(self.pid, "followup", "Follow-Up Visit",
                                      [{"heading": "Plan", "body": "Continue."}], [], "d", False, **kw)

    def test_a_chosen_visit_date_is_stored_and_returned(self):
        n = self._note(visit_date="2026-09-29")
        self.assertEqual(n["visit_date"], "2026-09-29")
        self.assertEqual(repository.get_note(self.pid, n["id"])["visit_date"], "2026-09-29")
        self.assertEqual(repository.list_notes(self.pid)[0]["visit_date"], "2026-09-29")

    def test_no_visit_date_means_today_on_this_computer(self):
        n = self._note()
        self.assertEqual(n["visit_date"], datetime.date.today().isoformat())

    def test_the_api_accepts_only_a_calendar_date_shape(self):
        base = dict(form_id="followup", form_name="F", sections=[], missing_info=[], dictation_raw="", used_prior=False)
        self.assertEqual(SaveNoteRequest(**base, visit_date="2026-09-29").visit_date, "2026-09-29")
        self.assertIsNone(SaveNoteRequest(**base).visit_date)
        for bad in ("09/29/2026", "2026-9-29", "tomorrow"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                SaveNoteRequest(**base, visit_date=bad)


if __name__ == "__main__":
    unittest.main()
