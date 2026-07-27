"""DB-backed tests for the patient/note deletion paths and the carry-forward
snapshot rebuild that deletion triggers. Run with:
    .venv/Scripts/python.exe -m unittest tests.test_storage_delete -v

These are the highest-risk pieces of the storage layer: notes are referenced by
carry_snapshots.source_note_id (a real foreign key, enforced because get_connection
sets PRAGMA foreign_keys = ON), and deleting the note a snapshot was built from must
neither raise nor silently leave a snapshot pointing at a row that no longer exists.

Isolation: each test points db.ENC_PATH / db.KEYFILE at a fresh temp directory before
db.init(), so nothing here ever decrypts, reads, or (on persist) overwrites the real
cadence.db.enc. The real store is never touched.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from app.storage import carry_forward, db, repository

FOLLOWUP_SECTIONS = [
    {"heading": "Functional Status", "body": "Ambulates 150ft with rolling walker.", "carried_forward": False},
    {"heading": "Short-Term Goals", "body": "Independent 200ft in 2 weeks.", "carried_forward": False},
]


def _followup_sections(distance: str) -> list[dict]:
    return [
        {"heading": "Functional Status", "body": f"Ambulates {distance}.", "carried_forward": False},
        {"heading": "Short-Term Goals", "body": "Progress ambulation.", "carried_forward": False},
    ]


class StorageDeleteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        self._orig_enc, self._orig_key = db.ENC_PATH, db.KEYFILE
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"
        db.init()

    def tearDown(self):
        db.shutdown()
        db.ENC_PATH, db.KEYFILE = self._orig_enc, self._orig_key
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------------
    def _new_patient(self, name="Test Patient"):
        return repository.create_patient(name=name, dob=None, mrn=None, condition=None)["id"]

    def _save_note(self, patient_id, form_id, sections, created_at=None):
        note = repository.create_note(
            patient_id=patient_id, form_id=form_id, form_name=form_id,
            sections=sections, missing_info=[], dictation_raw="raw", used_prior=False,
        )
        if created_at is not None:
            self._set_created_at(note["id"], created_at)
        return note["id"]

    def _set_created_at(self, note_id, ts):
        # create_note stamps created_at to the current second; two notes saved in the
        # same test would tie, making "newest remaining" ambiguous. Force distinct,
        # ordered timestamps so rebuild's newest-first selection is deterministic.
        conn = db.get_connection()
        try:
            conn.execute("UPDATE notes SET created_at = ? WHERE id = ?", (ts, note_id))
            conn.commit()
        finally:
            conn.close()

    def _snapshot_source(self, patient_id):
        conn = db.get_connection()
        try:
            r = conn.execute(
                "SELECT source_note_id FROM carry_snapshots WHERE patient_id = ?",
                (patient_id,),
            ).fetchone()
        finally:
            conn.close()
        return r["source_note_id"] if r else None

    # -- delete_patient --------------------------------------------------------
    def test_delete_patient_cascades_notes_and_snapshot(self):
        pid = self._new_patient()
        nid = self._save_note(pid, "followup", FOLLOWUP_SECTIONS)
        carry_forward.update_snapshot_after_save(pid, nid, "followup", FOLLOWUP_SECTIONS)

        before = repository.get_patient(pid)
        self.assertEqual(before["note_count"], 1)
        self.assertTrue(before["has_prior"])

        self.assertTrue(repository.delete_patient(pid))
        self.assertIsNone(repository.get_patient(pid))
        self.assertEqual(repository.list_notes(pid), [])
        self.assertIsNone(repository.get_carry_snapshot(pid))

    def test_delete_patient_missing_returns_false(self):
        self.assertFalse(repository.delete_patient("does-not-exist"))

    # -- delete_note -----------------------------------------------------------
    def test_delete_note_missing_returns_false(self):
        pid = self._new_patient()
        self.assertFalse(repository.delete_note(pid, "no-such-note"))

    def test_delete_non_source_note_keeps_snapshot(self):
        # Two carry notes; snapshot built from the newer (B). Deleting the OLDER note
        # (A) must not disturb the snapshot -- it still points at B.
        pid = self._new_patient()
        a = self._save_note(pid, "followup", _followup_sections("150ft"), created_at="2026-01-01T10:00:00+00:00")
        b = self._save_note(pid, "followup", _followup_sections("300ft"), created_at="2026-01-02T10:00:00+00:00")
        carry_forward.update_snapshot_after_save(pid, b, "followup", _followup_sections("300ft"))

        self.assertTrue(repository.delete_note(pid, a))
        carry_forward.rebuild_snapshot_after_delete(pid)

        self.assertEqual(self._snapshot_source(pid), b)
        self.assertIn("300ft", repository.get_carry_snapshot(pid)["functional_status"])
        self.assertEqual(repository.get_patient(pid)["note_count"], 1)

    def test_delete_source_note_rebuilds_from_previous(self):
        # Snapshot built from the newer note (B). Deleting B (the source) must not
        # raise a foreign-key error, and the snapshot must be rebuilt from A.
        pid = self._new_patient()
        a = self._save_note(pid, "followup", _followup_sections("150ft"), created_at="2026-01-01T10:00:00+00:00")
        b = self._save_note(pid, "followup", _followup_sections("300ft"), created_at="2026-01-02T10:00:00+00:00")
        carry_forward.update_snapshot_after_save(pid, b, "followup", _followup_sections("300ft"))
        self.assertEqual(self._snapshot_source(pid), b)

        self.assertTrue(repository.delete_note(pid, b))  # would raise on FK if not guarded
        carry_forward.rebuild_snapshot_after_delete(pid)

        self.assertEqual(self._snapshot_source(pid), a)
        self.assertIn("150ft", repository.get_carry_snapshot(pid)["functional_status"])
        self.assertTrue(repository.get_patient(pid)["has_prior"])

    def test_delete_last_carry_note_clears_snapshot(self):
        pid = self._new_patient()
        a = self._save_note(pid, "followup", FOLLOWUP_SECTIONS)
        carry_forward.update_snapshot_after_save(pid, a, "followup", FOLLOWUP_SECTIONS)

        self.assertTrue(repository.delete_note(pid, a))
        carry_forward.rebuild_snapshot_after_delete(pid)

        self.assertIsNone(repository.get_carry_snapshot(pid))
        self.assertFalse(repository.get_patient(pid)["has_prior"])

    def test_rebuild_never_picks_a_non_carry_note_as_source(self):
        # A carry note (A, followup) then a later non-carry note (B, soap). The
        # snapshot's source is A (soap saves don't update the snapshot). Deleting A
        # must clear the snapshot -- rebuild must NOT promote the non-carry SOAP note
        # to snapshot source just because it's the newest note that remains.
        pid = self._new_patient()
        a = self._save_note(pid, "followup", FOLLOWUP_SECTIONS, created_at="2026-01-01T10:00:00+00:00")
        b = self._save_note(pid, "soap", [{"heading": "Assessment", "body": "Tolerating well.", "carried_forward": False}], created_at="2026-01-02T10:00:00+00:00")
        carry_forward.update_snapshot_after_save(pid, a, "followup", FOLLOWUP_SECTIONS)
        self.assertEqual(self._snapshot_source(pid), a)

        self.assertTrue(repository.delete_note(pid, a))
        carry_forward.rebuild_snapshot_after_delete(pid)

        self.assertIsNone(repository.get_carry_snapshot(pid))
        self.assertFalse(repository.get_patient(pid)["has_prior"])
        # The SOAP note itself is untouched -- only the carry snapshot was affected.
        self.assertEqual(repository.get_patient(pid)["note_count"], 1)
        self.assertIsNotNone(repository.get_note(pid, b))


if __name__ == "__main__":
    unittest.main()
