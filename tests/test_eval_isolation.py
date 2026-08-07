"""The eval path must never write a synthetic patient into the clinician's encrypted database.

This is the one invariant the Evals tab could plausibly break. `scripts/eval_corpus.py` has always
driven the pipeline functions directly rather than POSTing to `/api/generate`, precisely because
that endpoint requires a patient row — but that was a convention held in one script. Exposing
sweeps over HTTP means the guarantee has to be structural and enforced.

Two independent checks, because either alone is bypassable:

  1. SOURCE-LEVEL — nothing under evals/ imports app.storage. Catches the mistake at the moment
     someone adds the import, before any runtime path exercises it.
  2. BEHAVIOURAL — run a real sweep against a temp DB with a mocked model and assert the patient
     table is untouched. Catches a route that reaches storage some way the import scan can't see.

    .venv/Scripts/python.exe -m unittest tests.test_eval_isolation -v
"""

import ast
import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage import db, repository

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = REPO_ROOT / "evals"

# Importing any of these from evals/ would put the clinician's real record store one call away
# from a synthetic sweep.
FORBIDDEN_ROOTS = ("app.storage",)
FORBIDDEN_NAMES = ("repository", "carry_forward")

CANNED_NOTE = """## Therapeutic Exercise
Minutes: 20
Scapular retraction and external rotation performed.

## Manual Therapy
Minutes: 15
Graded glenohumeral mobilizations.
---MISSING---
- none
"""


async def _fake_generate(prompt, timeout_s=600.0, model=None):
    return CANNED_NOTE


class SourceLevelIsolationTests(unittest.TestCase):
    def _imports(self, path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield node.module
                for alias in node.names:
                    yield f"{node.module}.{alias.name}"

    def test_evals_package_never_imports_storage(self):
        checked = 0
        for path in sorted(EVALS_DIR.rglob("*.py")):
            checked += 1
            for name in self._imports(path):
                with self.subTest(file=path.relative_to(REPO_ROOT), imported=name):
                    for root in FORBIDDEN_ROOTS:
                        self.assertFalse(
                            name == root or name.startswith(root + "."),
                            f"{path.relative_to(REPO_ROOT)} imports {name} — the eval path must "
                            "not be able to reach the encrypted patient store.",
                        )
                    leaf = name.rsplit(".", 1)[-1]
                    self.assertNotIn(
                        leaf, FORBIDDEN_NAMES,
                        f"{path.relative_to(REPO_ROOT)} imports {name}",
                    )
        self.assertGreater(checked, 3, "the import scan found almost no files — is the path right?")

    def test_runner_takes_no_patient_identifier(self):
        """The structural half of the guarantee: there is no parameter a patient could enter
        through, so the isolation does not depend on callers behaving."""
        import inspect

        from evals import runner
        for fn in (runner.generate_one, runner.score_one):
            params = set(inspect.signature(fn).parameters)
            with self.subTest(fn=fn.__name__):
                self.assertFalse(params & {"patient_id", "patient", "pid"})


class BehaviouralIsolationTests(unittest.TestCase):
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

    def test_a_full_sweep_writes_no_patients(self):
        from app.generate.forms import FORMS
        from evals import dataset, runner
        from evals.synth import generate as synth

        repository.create_patient(name="Real Patient", dob=None, mrn=None, condition="shoulder")
        before = [p["name"] for p in repository.list_patients()]

        samples = synth.generate_corpus(body_part="shoulder", note_type="followup", count=3,
                                        complexity="medium", seed=99)
        records = [dataset.parse_record(s.to_record(), "test") for s in samples]

        with patch("app.generate.ollama_client.generate_note", _fake_generate), \
             patch("evals.runner.generate_note", _fake_generate):
            for record in records:
                sections, missing, cond, secs, ok, draft = asyncio.run(
                    runner.generate_one(record, FORMS["followup"], False))
                runner.score_one(record, FORMS["followup"], sections, missing, cond, secs, 1, ok,
                                 draft)

        after = [p["name"] for p in repository.list_patients()]
        self.assertEqual(before, after,
                         "a sweep added rows to the patient table — synthetic records must never "
                         "reach the clinician's encrypted store")
        self.assertEqual(len(after), 1)

    def test_the_sweep_actually_ran(self):
        """Guards the test above from passing vacuously — an isolation test that silently did
        nothing would look identical to one that worked."""
        from app.generate.forms import FORMS
        from evals import dataset, runner
        from evals.synth import generate as synth

        record = dataset.parse_record(
            synth.generate_sample(1, body_part="shoulder", note_type="followup",
                                  complexity="medium", seed=99).to_record(), "test")
        with patch("evals.runner.generate_note", _fake_generate):
            sections, _, _, _, ok, draft = asyncio.run(
                runner.generate_one(record, FORMS["followup"], False))
        self.assertTrue(ok)
        self.assertTrue(sections)
        self.assertIsNotNone(draft)


if __name__ == "__main__":
    unittest.main()
