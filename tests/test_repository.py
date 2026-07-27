"""Behaviour tests for the repository CRUD contract the API layer depends on.

Complements test_storage_delete (which covers deletion + carry rebuild) by locking the pieces
those tests don't exercise: update_patient's partial-update semantics (omitted field unchanged vs
explicit None clears — a bug here would make PATCH clobber fields), and list_notes' snippet
(NEEDS-marker stripping + truncation) and missing_count. Same temp-DB isolation as the delete
tests, so the real cadence.db.enc is never touched.

    .venv/Scripts/python.exe -m unittest tests.test_repository -v
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from app.storage import db, repository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        self._orig = (db.ENC_PATH, db.KEYFILE)
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"
        db.init()

    def tearDown(self):
        db.shutdown()
        db.ENC_PATH, db.KEYFILE = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _patient(self):
        return repository.create_patient(
            name="Robert Handy", dob="1949-03-02", mrn="MRN1", condition="R knee OA",
        )["id"]

    # -- update_patient partial semantics --------------------------------------
    def test_update_changes_only_the_provided_field(self):
        pid = self._patient()
        repository.update_patient(pid, name="Bob Handy")
        p = repository.get_patient(pid)
        self.assertEqual(p["name"], "Bob Handy")
        self.assertEqual(p["dob"], "1949-03-02")   # untouched
        self.assertEqual(p["mrn"], "MRN1")          # untouched
        self.assertEqual(p["condition"], "R knee OA")

    def test_omitted_field_is_left_unchanged(self):
        pid = self._patient()
        repository.update_patient(pid, condition="L knee OA")  # mrn omitted
        self.assertEqual(repository.get_patient(pid)["mrn"], "MRN1")

    def test_explicit_none_clears_the_field(self):
        pid = self._patient()
        repository.update_patient(pid, mrn=None)  # explicit clear
        self.assertIsNone(repository.get_patient(pid)["mrn"])

    def test_update_missing_patient_returns_none(self):
        self.assertIsNone(repository.update_patient("p-nope", name="x"))

    # -- list_notes snippet / missing_count ------------------------------------
    def test_snippet_strips_needs_markers(self):
        pid = self._patient()
        repository.create_note(
            pid, "followup", "Follow-Up",
            [{"heading": "Objective", "body": "Ambulates 200 ft. [[NEEDS: assist level — verify]]", "carried_forward": False}],
            missing_info=[], dictation_raw="raw", used_prior=False,
        )
        snippet = repository.list_notes(pid)[0]["snippet"]
        self.assertNotIn("[[NEEDS", snippet)
        self.assertIn("Ambulates 200 ft.", snippet)

    def test_snippet_strips_cpt_and_skips_marker_only_first_section(self):
        pid = self._patient()
        repository.create_note(
            pid, "followup", "Follow-Up",
            [{"heading": "Precautions", "body": "[[NEEDS: prior value required]]", "carried_forward": False},
             {"heading": "Gait Training", "body": "Ambulated 100 ft. [[CPT: 97116 Gait Training — confirm]]", "carried_forward": False}],
            missing_info=[], dictation_raw="raw", used_prior=False,
        )
        snip = repository.list_notes(pid)[0]["snippet"]
        self.assertNotIn("[[", snip)                 # neither NEEDS nor CPT markers leak
        self.assertIn("Ambulated 100 ft.", snip)     # skipped the marker-only first section

    def test_missing_count_reflects_missing_info(self):
        pid = self._patient()
        repository.create_note(
            pid, "initial", "Initial Evaluation",
            [{"heading": "Vitals", "body": "BP recorded.", "carried_forward": False}],
            missing_info=["Heart rate", "Pain rating"], dictation_raw="raw", used_prior=False,
        )
        self.assertEqual(repository.list_notes(pid)[0]["missing_count"], 2)

    def test_get_note_round_trips_sections_including_carry_flag(self):
        pid = self._patient()
        sections = [{"heading": "Functional Status", "body": "Ambulates 200 ft.", "carried_forward": True}]
        nid = repository.create_note(pid, "followup", "Follow-Up", sections, [], "raw", True)["id"]
        got = repository.get_note(pid, nid)
        self.assertEqual(got["sections"], sections)

    # -- patient list metadata -------------------------------------------------
    def test_note_count_and_has_prior_reflect_state(self):
        pid = self._patient()
        self.assertEqual(repository.get_patient(pid)["note_count"], 0)
        self.assertFalse(repository.get_patient(pid)["has_prior"])
        repository.create_note(pid, "soap", "SOAP", [{"heading": "A", "body": "x", "carried_forward": False}], [], "raw", False)
        self.assertEqual(repository.get_patient(pid)["note_count"], 1)


if __name__ == "__main__":
    unittest.main()
