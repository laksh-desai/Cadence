"""Clinician corrections must be recorded, and must never leave the device.

Until this landed, every correction was destroyed: `app.js` wrote edits into the section body in
place, so the model's original text was gone, and the "Ask for changes" instruction was never
persisted at all. The `notes` table had no original-output column and no edit signal, so a
blindly-accepted note and a heavily-rewritten one were byte-identical in shape. That loss is
unrecoverable — a corpus you didn't capture in March cannot be reconstructed in September.

Two invariants are locked here, and the second is the load-bearing one:

  1. NULL means "not captured", 0 means "accepted as generated". If a migration ever defaulted
     `edited_section_count` to 0, every pre-capture note would look blindly-accepted and the exact
     signal this feature exists to build would be destroyed.
  2. This is real patient content. It stays in the encrypted `notes` row and never becomes an
     export — enforced structurally by a source scan, not by a comment.

    .venv/Scripts/python.exe -m unittest tests.test_correction_capture -v
"""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.storage import db, repository
from app.ui import server

REPO_ROOT = Path(__file__).resolve().parent.parent

# The pre-capture `notes` DDL, verbatim, so the migration is tested against a REAL old database
# rather than against the current schema with columns removed.
LEGACY_NOTES_DDL = """
CREATE TABLE patients (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, dob TEXT, mrn TEXT, condition TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE notes (
  id            TEXT PRIMARY KEY,
  patient_id    TEXT NOT NULL,
  form_id       TEXT NOT NULL,
  form_name     TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  sections_json TEXT NOT NULL,
  missing_json  TEXT NOT NULL,
  dictation_raw TEXT NOT NULL,
  used_prior    INTEGER NOT NULL DEFAULT 0
);
"""

NEW_COLUMNS = ("original_sections_json", "revise_instructions_json", "edited_section_count",
               "model_id", "fast_tier", "template_spec_sha", "template_customized", "synthetic")


def _sec(heading, body, carried=False):
    return {"heading": heading, "body": body, "carried_forward": carried}


class EditCountTests(unittest.TestCase):
    """Pure — no DB. `count_edited_sections` is the denormalized index over the stored original."""

    def test_identical_is_zero_not_none(self):
        secs = [_sec("A", "one"), _sec("B", "two")]
        self.assertEqual(repository.count_edited_sections(secs, secs), 0)

    def test_no_original_is_none_not_zero(self):
        """The distinction the whole feature rests on."""
        self.assertIsNone(repository.count_edited_sections([], [_sec("A", "one")]))

    def test_whitespace_only_change_is_not_an_edit(self):
        """A <textarea> routinely returns a trailing newline; that is not a correction."""
        before = [_sec("A", "one two three")]
        after = [_sec("A", "  one   two three\n")]
        self.assertEqual(repository.count_edited_sections(before, after), 0)

    def test_one_changed_body(self):
        before = [_sec("A", "one"), _sec("B", "two")]
        after = [_sec("A", "one"), _sec("B", "REWRITTEN")]
        self.assertEqual(repository.count_edited_sections(before, after), 1)

    def test_a_changed_heading_counts(self):
        self.assertEqual(
            repository.count_edited_sections([_sec("A", "one")], [_sec("Renamed", "one")]), 1)

    def test_a_removed_section_counts(self):
        before = [_sec("A", "one"), _sec("B", "two")]
        self.assertEqual(repository.count_edited_sections(before, before[:1]), 1)


class _TempDbTest(unittest.TestCase):
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

    def _row(self, note_id):
        conn = db.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            return dict(conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())
        finally:
            conn.close()


class MigrationTests(unittest.TestCase):
    def test_migration_adds_columns_to_a_preexisting_db_and_the_old_row_survives(self):
        """Against the real legacy DDL. `CREATE TABLE IF NOT EXISTS` is a no-op on an existing
        table, so `_migrate` is the only thing that can add these columns to a clinician's DB."""
        tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        try:
            path = tmp / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript(LEGACY_NOTES_DDL)
            conn.execute(
                "INSERT INTO notes VALUES ('n1','p1','followup','Follow-Up','2026-01-01',"
                "'[]','[]','old dictation',0)")
            conn.commit()

            db._migrate(conn)
            conn.commit()

            cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)")}
            for column in NEW_COLUMNS:
                self.assertIn(column, cols)

            conn.row_factory = sqlite3.Row
            row = dict(conn.execute("SELECT * FROM notes WHERE id='n1'").fetchone())
            self.assertEqual(row["dictation_raw"], "old dictation")
            self.assertIsNone(row["edited_section_count"],
                              "a pre-capture note must read as NOT CAPTURED, never as unedited")
            self.assertIsNone(row["original_sections_json"])
            self.assertEqual(row["synthetic"], 0, "unknown must never read as safe to export")
            conn.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_migration_is_idempotent(self):
        tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        try:
            conn = sqlite3.connect(tmp / "legacy.db")
            conn.executescript(LEGACY_NOTES_DDL)
            db._migrate(conn)
            db._migrate(conn)   # must not raise "duplicate column name"
            conn.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CapturePersistenceTests(_TempDbTest):
    def setUp(self):
        super().setUp()
        self.pid = repository.create_patient(
            name="Test PT", dob=None, mrn=None, condition="knee")["id"]
        self.client = TestClient(server.app)

    def _save(self, **extra):
        body = {
            "form_id": "followup", "form_name": "Follow-Up Visit",
            "sections": [_sec("Therapeutic Exercise", "Minutes: 20. Quad sets.")],
            "missing_info": [], "dictation_raw": "did quad sets", "used_prior": False,
        }
        body.update(extra)
        r = self.client.post(f"/api/patients/{self.pid}/notes", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def test_save_without_the_new_fields_still_works(self):
        """The exact legacy payload shape, as tests/test_endpoints.py sends it."""
        row = self._row(self._save())
        self.assertIsNone(row["edited_section_count"])
        self.assertIsNone(row["original_sections_json"])

    def test_identical_original_records_zero_edits(self):
        secs = [_sec("Therapeutic Exercise", "Minutes: 20. Quad sets.")]
        row = self._row(self._save(sections=secs, original_sections=secs))
        self.assertEqual(row["edited_section_count"], 0)
        self.assertEqual(json.loads(row["original_sections_json"])[0]["body"],
                         "Minutes: 20. Quad sets.")

    def test_an_edited_section_records_one_and_keeps_both_versions(self):
        original = [_sec("Therapeutic Exercise", "Minutes: 20. MODEL WROTE THIS.")]
        final = [_sec("Therapeutic Exercise", "Minutes: 20. Clinician rewrote this.")]
        row = self._row(self._save(sections=final, original_sections=original))
        self.assertEqual(row["edited_section_count"], 1)
        self.assertIn("MODEL WROTE THIS", row["original_sections_json"])
        self.assertIn("Clinician rewrote this", row["sections_json"])

    def test_revise_instructions_round_trip(self):
        row = self._row(self._save(revise_instructions=[
            {"text": "make the assessment more concise", "applied": True, "at": "2026-08-08T00:00:00Z"},
            {"text": "add the stair count", "applied": False, "at": "2026-08-08T00:01:00Z"},
        ]))
        stored = json.loads(row["revise_instructions_json"])
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["text"], "make the assessment more concise")
        self.assertFalse(stored[1]["applied"], "a failed revision is still signal")

    def test_provenance_is_stored(self):
        row = self._row(self._save(model_id="medgemma-4b", fast=False,
                                   template_spec_sha="abc123", template_customized=True))
        self.assertEqual(row["model_id"], "medgemma-4b")
        self.assertEqual(row["fast_tier"], 0)
        self.assertEqual(row["template_spec_sha"], "abc123")
        self.assertEqual(row["template_customized"], 1)

    def test_carry_snapshot_is_built_from_the_final_not_the_original(self):
        """If carry-forward were fed the originals, a follow-up would carry the model's
        UNCORRECTED values into the next visit — the correction would be silently undone."""
        original = [_sec("Functional Status", "Ambulates 150 feet with a walker.")]
        final = [_sec("Functional Status", "Ambulates 200 feet with a cane.")]
        self._save(sections=final, original_sections=original)
        snapshot = repository.get_carry_snapshot(self.pid)
        self.assertIsNotNone(snapshot)
        self.assertIn("200 feet", snapshot["functional_status"])
        self.assertNotIn("150 feet", snapshot["functional_status"])

    def test_capture_is_not_on_the_http_read_surface(self):
        """Write-only in v1: keeping it off the wire keeps the PHI surface exactly where it was."""
        note_id = self._save(original_sections=[_sec("A", "MODEL ORIGINAL")])
        got = self.client.get(f"/api/patients/{self.pid}/notes/{note_id}").json()
        self.assertNotIn("original_sections", got)
        self.assertNotIn("MODEL ORIGINAL", json.dumps(got))


class PhiBoundaryTests(unittest.TestCase):
    def test_no_export_path_exists(self):
        """Structural, not a comment. The captured corrections are real patient content; training
        needs a GPU and therefore off-device compute, so this data can NEVER be training data (see
        docs/finetune-when-viable.md). If an export is ever built it must filter
        `WHERE synthetic = 1` at the SQL level — which is why that column exists.

        Same spirit as tests/test_eval_isolation.py's import scan.
        """
        allowed = {
            REPO_ROOT / "app" / "storage" / "schema.sql",
            REPO_ROOT / "app" / "storage" / "db.py",
            REPO_ROOT / "app" / "storage" / "repository.py",
            Path(__file__),
        }
        offenders = []
        for path in list(REPO_ROOT.glob("app/**/*.py")) + list(REPO_ROOT.glob("scripts/**/*.py")) \
                + list(REPO_ROOT.glob("evals/**/*.py")) + list(REPO_ROOT.glob("app/**/*.sql")) \
                + list(REPO_ROOT.glob("tests/**/*.py")):
            if path in allowed:
                continue
            if "original_sections_json" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(
            offenders, [],
            "captured clinician corrections are real patient content and must stay in the "
            f"encrypted notes row; {offenders} reads the raw column outside app/storage/",
        )

    def test_sheets_sync_never_touches_notes(self):
        """The Google Workspace BAA carve-out covers the roster only. It must not creep to note
        content just because a new column looks interesting."""
        src = (REPO_ROOT / "app" / "integrations" / "sheets_sync.py").read_text(encoding="utf-8")
        # NB: the bare word "notes" appears legitimately as `scheduling_notes`, which is a
        # PATIENTS column and part of the roster the BAA carve-out does cover. What must never
        # appear is any route to the notes TABLE or the note repository functions.
        for forbidden in ("create_note", "list_notes", "get_note", "sections_json",
                          "original_sections", "FROM notes", "INTO notes"):
            self.assertNotIn(forbidden, src, f"sheets_sync references {forbidden!r}")


if __name__ == "__main__":
    unittest.main()
