"""Tests for the corpus loader (evals/dataset.py).

Pure/offline — synthetic JSONL written to a temp dir, no model, no DB, no real corpus needed.

    .venv/bin/python -m unittest tests.test_eval_dataset -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from evals import dataset

_BASE = {
    "id": 1,
    "patient_name": "Marcus Delgado",
    "diagnosis": "S/P Left ACL Reconstruction (autograft, hamstring)",
    "visit_type": "Follow-up, post-op week 6",
    "date": "2026-06-02",
    "transcript": "Okay this is Marcus Delgado, six weeks out from his ACL.",
}


def _write(dirpath: Path, name: str, records: list[dict]) -> Path:
    path = dirpath / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


class FormMappingTests(unittest.TestCase):
    def test_follow_up_variants_map_to_followup(self):
        for vt in ["Follow-up, post-op week 6", "follow up visit", "F/U week 3",
                   "Progress note", "Interim treatment visit"]:
            with self.subTest(visit_type=vt):
                self.assertEqual(dataset.form_id_for_visit_type(vt), "followup")

    def test_evaluation_variants_map_to_initial(self):
        for vt in ["Initial Evaluation", "initial eval", "New patient intake",
                   "Re-evaluation", "Physical therapy assessment"]:
            with self.subTest(visit_type=vt):
                self.assertEqual(dataset.form_id_for_visit_type(vt), "initial")

    def test_initial_wins_over_followup_when_both_appear(self):
        # "Initial evaluation, follow-up to referral" is an evaluation, not a follow-up visit.
        self.assertEqual(dataset.form_id_for_visit_type("Initial evaluation, follow-up to referral"),
                         "initial")

    def test_unrecognized_visit_type_is_flagged_not_defaulted(self):
        # A silent default would score the record against the wrong template and look like
        # a model defect, so an unmappable visit_type must be loud.
        self.assertEqual(dataset.form_id_for_visit_type("Telehealth check-in"), dataset.UNMAPPED)
        self.assertEqual(dataset.form_id_for_visit_type(""), dataset.UNMAPPED)


class LoaderTests(unittest.TestCase):
    def test_merges_files_with_inconsistent_schema(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d, "file1.jsonl", [{**_BASE, "id": 1}, {**_BASE, "id": 2}])
            _write(d, "file2.jsonl", [{
                **_BASE, "id": 3,
                "cpt_codes": [{"code": "97110", "description": "Therapeutic exercise"},
                              {"code": "97140", "description": "Manual therapy"}],
            }])
            records = dataset.load_corpus(d)
        self.assertEqual([r.id for r in records], [1, 2, 3])
        self.assertEqual(records[0].cpt_codes, ())          # missing -> empty, not None
        self.assertEqual(records[2].cpt_codes, ("97110", "97140"))
        self.assertEqual(records[2].cpt_descriptions["97110"], "Therapeutic exercise")

    def test_records_sorted_by_id_across_files(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d, "zzz.jsonl", [{**_BASE, "id": 1}])
            _write(d, "aaa.jsonl", [{**_BASE, "id": 9}])
            records = dataset.load_corpus(d)
        self.assertEqual([r.id for r in records], [1, 9])

    def test_blank_lines_tolerated(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "f.jsonl").write_text(json.dumps(_BASE) + "\n\n\n", encoding="utf-8")
            self.assertEqual(len(dataset.load_corpus(d)), 1)

    def test_bare_code_strings_tolerated(self):
        # The corpus schema is already known to be inconsistent; accept a plain code list too.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d, "f.jsonl", [{**_BASE, "cpt_codes": ["97110", "97530"]}])
            self.assertEqual(dataset.load_corpus(d)[0].cpt_codes, ("97110", "97530"))

    def test_duplicate_ids_across_files_raise(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d, "a.jsonl", [{**_BASE, "id": 5}])
            _write(d, "b.jsonl", [{**_BASE, "id": 5}])
            with self.assertRaises(dataset.DatasetError) as cm:
                dataset.load_corpus(d)
        self.assertIn("duplicate record id 5", str(cm.exception))

    def test_missing_required_field_raises_with_field_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            bad = {k: v for k, v in _BASE.items() if k != "transcript"}
            _write(d, "f.jsonl", [bad])
            with self.assertRaises(dataset.DatasetError) as cm:
                dataset.load_corpus(d)
        self.assertIn("transcript", str(cm.exception))

    def test_malformed_json_reports_line_number(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "f.jsonl").write_text(json.dumps(_BASE) + "\n{not json\n", encoding="utf-8")
            with self.assertRaises(dataset.DatasetError) as cm:
                dataset.load_corpus(d)
        self.assertIn(":2:", str(cm.exception))

    def test_empty_directory_raises_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(dataset.DatasetError) as cm:
                dataset.load_corpus(Path(td))
        self.assertIn("No .jsonl files", str(cm.exception))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            dataset.parse_record({**_BASE, "id": 1, "visit_type": "Initial Evaluation"}, "f"),
            dataset.parse_record({**_BASE, "id": 2, "visit_type": "Follow-up"}, "f"),
            dataset.parse_record({**_BASE, "id": 3, "visit_type": "Follow-up"}, "f"),
        ]

    def test_filter_by_form(self):
        self.assertEqual([r.id for r in dataset.select(self.records, form="followup")], [2, 3])

    def test_filter_by_ids(self):
        self.assertEqual([r.id for r in dataset.select(self.records, ids=[1, 3])], [1, 3])

    def test_limit_applies_after_filters(self):
        self.assertEqual([r.id for r in dataset.select(self.records, form="followup", limit=1)], [2])

    def test_word_count(self):
        self.assertEqual(self.records[0].word_count, len(_BASE["transcript"].split()))

    def test_summarize_mentions_forms_and_gold_codes(self):
        s = dataset.summarize(self.records)
        self.assertIn("3 records", s)
        self.assertIn("followup=2", s)
        self.assertIn("initial=1", s)


if __name__ == "__main__":
    unittest.main()
