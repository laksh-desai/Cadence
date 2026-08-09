"""The billing scorers, and the to_dict -> load_result round trip that --resume depends on.

The round trip is the load-bearing test here. `RecordResult.to_dict()` writes a run to
evals/runs/, and `runner.load_result()` reads it back when `--resume` skips a cached generation.
A key added on one side only does not error — it silently rehydrates as None, so every cached
record reports zero for that metric and a resumed sweep quietly under-reports. That class of bug
has no symptom until someone trusts the number.

The scorers themselves are checked mostly through their NEGATIVES: `distractor_leaks`,
`untimed_leak` and `laterality_errors` each measure a wrong claim, and a scorer that fails to
notice one is worse than no scorer at all.

    .venv/Scripts/python.exe -m unittest tests.test_eval_billing_score -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.generate import billing
from evals import dataset, runner
from evals import score as scoring
from evals.synth import generate as synth


def _record(**over):
    base = {
        "id": 9001, "patient_name": "Test", "diagnosis": "Right rotator cuff tendinopathy",
        "visit_type": "Follow-up, week 3", "date": "2026-03-02",
        "transcript": ("Follow-up, right shoulder. Referring diagnosis is right rotator cuff "
                       "tendinopathy. Therapeutic exercise for twenty minutes. Manual therapy "
                       "for fifteen minutes. We did not do gait training today."),
        "body_part": "shoulder",
        "icd_codes": [{"code": "M75.101", "description": "Rotator cuff tear, right"}],
        "interventions": [
            {"code": "97110", "label": "Therapeutic Exercise", "minutes": 20, "timed": True},
            {"code": "97140", "label": "Manual Therapy", "minutes": 15, "timed": True},
        ],
        "distractors": [{"code": "97116", "reason": "negated"}],
        "total_timed_minutes": 35, "expected_units": 2, "expected_units_ama": 2,
        "synth": {"generator_version": 1},
    }
    base.update(over)
    return dataset.parse_record(base, "test")


class IcdScoreTests(unittest.TestCase):
    def test_a_correct_code_is_a_hit(self):
        rec = _record()
        s = scoring.score_icd(billing.extract(rec.transcript), rec.icd_codes)
        self.assertEqual(s.hits, ("M75.101",))
        self.assertEqual(s.recall, 1.0)
        self.assertEqual(s.laterality_errors, ())

    def test_the_wrong_side_is_not_a_hit_and_is_reported_separately(self):
        """A missing code is a blank the clinician fills; a wrong-side code reads as confident and
        goes on a claim. They must never be collapsed into one 'miss' number."""
        rec = _record(transcript="Follow-up, left shoulder. Referring diagnosis is left rotator "
                                 "cuff tendinopathy.")
        s = scoring.score_icd(billing.extract(rec.transcript), ("M75.101",))
        self.assertEqual(s.hits, ())
        self.assertEqual(s.laterality_errors, (("M75.101", "M75.102"),))

    def test_a_different_condition_is_not_a_laterality_error(self):
        s = scoring.score_icd(billing.extract("Shoulder. Diagnosis is right adhesive capsulitis."),
                              ("M75.101",))
        self.assertEqual(s.laterality_errors, ())


class BillingDetectionScoreTests(unittest.TestCase):
    def test_clean_detection(self):
        rec = _record()
        s = scoring.score_billing_detection(billing.extract(rec.transcript), rec)
        self.assertEqual(set(s.hits), {"97110", "97140"})
        self.assertEqual(s.recall, 1.0)
        self.assertEqual(s.distractor_leaks, ())

    def test_a_billed_distractor_is_reported_with_its_reason(self):
        """The headline safety metric. The reason makes the failure attributable to a specific
        guard in billing.py rather than just 'precision dropped'."""
        rec = _record(transcript="Follow-up, right shoulder. Therapeutic exercise twenty minutes. "
                                 "Gait training for ten minutes.",
                      distractors=[{"code": "97116", "reason": "negated"}])
        s = scoring.score_billing_detection(billing.extract(rec.transcript), rec)
        self.assertEqual(s.distractor_leaks, (("97116", "negated"),))

    def test_a_missed_treatment_is_a_recall_loss_not_a_leak(self):
        rec = _record(transcript="Follow-up, right shoulder. Therapeutic exercise twenty minutes.")
        s = scoring.score_billing_detection(billing.extract(rec.transcript), rec)
        self.assertIn("97140", s.missed)
        self.assertEqual(s.distractor_leaks, ())


class MinutesScoreTests(unittest.TestCase):
    def test_exact_minutes(self):
        rec = _record()
        s = scoring.score_minutes(billing.extract(rec.transcript), rec)
        self.assertEqual(s.exact, 2)
        self.assertEqual(s.fabricated, 0)
        self.assertEqual(s.mae, 0.0)

    def test_not_extracted_and_fabricated_are_distinct(self):
        """One is a safe gap the clinician fills; the other is an invented billable value.
        Averaging them into a single 'minutes accuracy' would hide the dangerous one."""
        rec = _record(transcript="Follow-up, right shoulder. We did therapeutic exercise and "
                                 "manual therapy.")
        s = scoring.score_minutes(billing.extract(rec.transcript), rec)
        self.assertEqual(s.not_extracted, 2)
        self.assertEqual(s.fabricated, 0)


class UnitsScoreTests(unittest.TestCase):
    def test_units_and_minutes_match_the_gold(self):
        rec = _record()
        s = scoring.score_units(billing.extract(rec.transcript), rec)
        self.assertTrue(s.exact)
        self.assertTrue(s.minutes_exact)
        self.assertEqual(s.computed_units, 2)
        self.assertEqual(s.untimed_leak, ())

    def test_an_untimed_modality_does_not_reach_the_timed_total(self):
        rec = _record(
            transcript="Follow-up, right shoulder. Therapeutic exercise for twenty minutes. "
                       "Manual therapy for fifteen minutes. Hot packs for ten minutes.",
        )
        s = scoring.score_units(billing.extract(rec.transcript), rec)
        self.assertEqual(s.computed_timed_minutes, 35)
        self.assertEqual(s.untimed_leak, ())


class RoundTripTests(unittest.TestCase):
    """to_dict() -> load_result() must preserve every block, or --resume silently zeroes it."""

    def _result(self):
        from app.generate.forms import FORMS
        rec = _record()
        draft = billing.extract(rec.transcript, body_part=rec.body_part)
        sections = [{"heading": "Therapeutic Exercise",
                     "body": "Minutes: 20 [[CPT: 97110 Therapeutic Exercise — confirm]]",
                     "carried_forward": False}]
        draft = billing.reconcile(draft, sections)
        return runner.score_one(rec, FORMS["followup"], sections, [], False, 12.3, 1, True, draft)

    def test_every_billing_block_survives_the_round_trip(self):
        original = self._result()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(original.to_dict(), indent=2), encoding="utf-8")
            back = runner.load_result(path)

        for block in ("icd", "billing_detection", "minutes", "units", "agreement"):
            with self.subTest(block=block):
                self.assertIsNotNone(getattr(back, block),
                                     f"{block} was dropped by the round trip — a --resume sweep "
                                     "would report zero for it")
        self.assertEqual(back.icd.hits, original.icd.hits)
        self.assertEqual(back.icd.laterality_errors, original.icd.laterality_errors)
        self.assertEqual(back.billing_detection.distractor_leaks,
                         original.billing_detection.distractor_leaks)
        self.assertEqual(back.minutes.exact, original.minutes.exact)
        self.assertEqual(back.minutes.fabricated, original.minutes.fabricated)
        self.assertEqual(back.units.computed_units, original.units.computed_units)
        self.assertEqual(back.units.untimed_leak, original.units.untimed_leak)
        self.assertEqual(back.units.overstated, original.units.overstated)
        self.assertEqual(back.billing_detection.surfaced, original.billing_detection.surfaced)
        self.assertEqual(back.billing_detection.surfaced_recall,
                         original.billing_detection.surfaced_recall)
        self.assertEqual(back.agreement.both, original.agreement.both)
        self.assertEqual(back.is_synthetic, original.is_synthetic)
        self.assertEqual(back.body_part, original.body_part)

    def test_to_dict_keys_are_all_read_back(self):
        """Guards the pairing directly: a block added to to_dict() without a matching branch in
        load_result() fails here rather than in a sweep three weeks later."""
        d = self._result().to_dict()
        for block in ("icd", "billing_detection", "minutes", "units", "agreement"):
            self.assertIn(block, d)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(d), encoding="utf-8")
            back = runner.load_result(path).to_dict()
        for block in ("icd", "billing_detection", "units", "agreement"):
            with self.subTest(block=block):
                self.assertEqual(back[block], d[block])


class AggregateTests(unittest.TestCase):
    def test_aggregate_reports_the_safety_metrics(self):
        from app.generate.forms import FORMS
        rec = _record()
        draft = billing.reconcile(billing.extract(rec.transcript, body_part=rec.body_part), [])
        result = runner.score_one(rec, FORMS["followup"], [], [], False, 1.0, 1, True, draft)
        agg = runner.aggregate([result])
        for key in ("distractor_leaks", "untimed_leaks", "laterality_errors",
                    "minutes_fabricated", "units_overstated"):
            self.assertIn(key, agg)
            self.assertEqual(agg[key], 0)
        # Surfaced recall must be reported alongside billed recall: the gap between them is
        # clinician work, not error, and collapsing them hides which one moved.
        self.assertIn("cpt_surfaced_recall", agg)
        self.assertGreaterEqual(agg["cpt_surfaced_recall"], agg["cpt_detection_recall"])

    def test_results_split_synthetic_from_handwritten(self):
        """The non-circular control must stay separable — a synthetic-only score can look good
        while both generator and extractor are wrong about real dictation."""
        from app.generate.forms import FORMS
        from evals import results as results_store
        syn = _record()
        hand = _record(id=9002, synth={})
        out = []
        for rec in (syn, hand):
            draft = billing.extract(rec.transcript, body_part=rec.body_part)
            out.append(runner.score_one(rec, FORMS["followup"], [], [], False, 1.0, 1, True, draft))
        agg = results_store.split_aggregate(out)
        self.assertEqual(agg["synthetic"]["records"], 1)
        self.assertEqual(agg["handwritten"]["records"], 1)
        self.assertEqual(agg["all"]["records"], 2)


class CompareTests(unittest.TestCase):
    def test_comparing_across_generator_versions_is_refused(self):
        from evals import results as results_store
        older = {"run_id": "a", "config": {"generator_version": 1}, "aggregate": {"all": {}}}
        newer = {"run_id": "b", "config": {"generator_version": 2}, "aggregate": {"all": {}}}
        with self.assertRaises(ValueError):
            results_store.compare(older, newer)
        self.assertIsNotNone(results_store.compare(older, newer, force=True))

    def test_direction_accounts_for_metrics_where_lower_is_better(self):
        from evals import results as results_store
        older = {"run_id": "a", "config": {"generator_version": 1},
                 "aggregate": {"all": {"distractor_leaks": 0, "units_exact": 0.8}}}
        newer = {"run_id": "b", "config": {"generator_version": 1},
                 "aggregate": {"all": {"distractor_leaks": 3, "units_exact": 0.9}}}
        m = results_store.compare(older, newer)["metrics"]
        self.assertEqual(m["distractor_leaks"]["direction"], "worse")
        self.assertEqual(m["units_exact"]["direction"], "better")


if __name__ == "__main__":
    unittest.main()
