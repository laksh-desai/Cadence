"""The synthetic generator: determinism, label correctness, and corpus compatibility.

Two properties make this corpus worth committing:

  1. DETERMINISM. Same arguments -> byte-identical file, and raising --count leaves the earlier
     records untouched. That is what makes a committed corpus diff readable and a re-run
     idempotent, and it comes from seeding each sample off a string containing its own index
     rather than drawing sequentially from one shared stream.
  2. LABELS THAT AGREE WITH THEMSELVES. `expected_units` must equal
     `units_for_minutes(total_timed_minutes)`, and untimed codes must never reach that total. A
     generator whose own arithmetic drifts would report the extractor as broken when it is right.

Offline and instant — no model, no network, no DB.

    .venv/Scripts/python.exe -m unittest tests.test_synth_generator -v
"""

import json
import unittest

from app.generate.billing import units_for_minutes
from app.generate.cpt import is_timed
from evals import dataset
from evals.synth import generate as synth

KW = dict(body_part="shoulder", note_type="followup", complexity="medium", seed=1234)


class DeterminismTests(unittest.TestCase):
    def test_same_arguments_produce_identical_samples(self):
        a = synth.generate_corpus(count=6, **KW)
        b = synth.generate_corpus(count=6, **KW)
        self.assertEqual([s.to_record() for s in a], [s.to_record() for s in b])

    def test_growing_the_corpus_leaves_earlier_records_untouched(self):
        """Per-sample seeding off the index, not a shared stream. Without this, bumping --count
        rewrites every record and the corpus diff becomes unreadable."""
        small = synth.generate_corpus(count=5, **KW)
        large = synth.generate_corpus(count=12, **KW)
        self.assertEqual([s.to_record() for s in small],
                         [s.to_record() for s in large[:5]])

    def test_a_different_seed_produces_different_text(self):
        a = synth.generate_corpus(count=4, **{**KW, "seed": 1})
        b = synth.generate_corpus(count=4, **{**KW, "seed": 2})
        self.assertNotEqual([s.transcript for s in a], [s.transcript for s in b])

    def test_complexity_changes_the_sample(self):
        low = synth.generate_corpus(count=6, **{**KW, "complexity": "low"})
        high = synth.generate_corpus(count=6, **{**KW, "complexity": "high"})
        self.assertEqual(sum(len(s.distractors) for s in low), 0)
        self.assertGreater(sum(len(s.distractors) for s in high), 0)


class LabelConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.samples = [
            s for c in synth.COMPLEXITIES
            for s in synth.generate_corpus(count=8, **{**KW, "complexity": c})
        ]

    def test_expected_units_match_the_stated_total(self):
        for s in self.samples:
            with self.subTest(id=s.id):
                self.assertEqual(s.expected_units, units_for_minutes(s.total_timed_minutes))

    def test_the_timed_total_is_the_sum_of_timed_minutes_only(self):
        """The trap the corpus exists to test: an untimed modality's duration must not inflate
        the total. If the GENERATOR got this wrong, every extractor score would be nonsense."""
        for s in self.samples:
            with self.subTest(id=s.id):
                expected = sum(i.minutes for i in s.interventions if i.timed and i.minutes)
                self.assertEqual(s.total_timed_minutes, expected)

    def test_every_intervention_agrees_with_the_cpt_timed_table(self):
        for s in self.samples:
            for i in s.interventions:
                with self.subTest(id=s.id, code=i.code):
                    self.assertEqual(i.timed, is_timed(i.code))

    def test_untimed_interventions_carry_no_minutes(self):
        for s in self.samples:
            for i in s.interventions:
                if not i.timed:
                    self.assertIsNone(i.minutes)

    def test_cpt_codes_are_derived_from_the_interventions(self):
        """`cpt_codes` is what the existing Tier A scorer reads, so it must never be drawn
        separately from the richer intervention list."""
        for s in self.samples:
            self.assertEqual(set(s.cpt_codes),
                             {i.code for i in s.interventions if i.billable})

    def test_every_distractor_has_a_reason_and_is_not_also_billable(self):
        for s in self.samples:
            billable = {i.code for i in s.interventions if i.billable}
            for d in s.distractors:
                with self.subTest(id=s.id, code=d.code):
                    self.assertTrue(d.reason)
                    self.assertNotIn(d.code, billable,
                                     "a code cannot be both billable and a distractor")

    def test_distractor_codes_are_actually_named_in_the_transcript(self):
        """A distractor the dictation never mentions tests nothing — the extractor would 'pass'
        it by never seeing it."""
        from evals.synth import banks
        for s in self.samples:
            for d in s.distractors:
                spoken = banks.INTERVENTION_SPOKEN[d.code]
                with self.subTest(id=s.id, code=d.code):
                    self.assertTrue(any(p.lower() in s.transcript.lower() for p in spoken),
                                    f"no spoken form of {d.code} appears in the transcript")

    def test_high_complexity_produces_method_disagreements(self):
        """The corpus must contain cases where CMS and the AMA rule of eights differ, or the
        two-number requirement is never actually exercised."""
        samples = synth.generate_corpus(count=24, **{**KW, "complexity": "high"})
        differing = [s for s in samples if s.expected_units != s.expected_units_ama]
        self.assertTrue(differing, "no CMS/AMA divergence in 24 high-complexity samples")


class CorpusCompatibilityTests(unittest.TestCase):
    def test_records_round_trip_through_the_dataset_loader(self):
        for s in synth.generate_corpus(count=5, **KW):
            record = dataset.parse_record(json.loads(json.dumps(s.to_record())), "test")
            with self.subTest(id=s.id):
                self.assertEqual(record.id, s.id)
                self.assertEqual(record.total_timed_minutes, s.total_timed_minutes)
                self.assertEqual(record.expected_units, s.expected_units)
                self.assertEqual(set(record.icd_codes), set(s.icd_codes))
                self.assertEqual(len(record.interventions), len(s.interventions))
                self.assertTrue(record.has_billing_gold)
                self.assertTrue(record.is_synthetic)

    def test_ids_cannot_collide_with_the_hand_written_records(self):
        """Hand-written shoulder records are 101-108; synthetic shoulder starts at 1001. The
        loader rejects duplicate ids across files, so a collision would break the whole corpus."""
        ids = {s.id for s in synth.generate_corpus(count=50, **KW)}
        self.assertTrue(all(i >= 1001 for i in ids))
        self.assertFalse(ids & set(range(101, 109)))

    def test_body_parts_get_disjoint_id_blocks(self):
        blocks = sorted(synth.ID_BLOCKS.values())
        self.assertEqual(len(blocks), len(set(blocks)))
        for a, b in zip(blocks, blocks[1:]):
            self.assertGreaterEqual(b - a, 1000)

    def test_unknown_arguments_are_rejected_loudly(self):
        for bad in ({"body_part": "elbow"}, {"note_type": "soap"}, {"complexity": "extreme"}):
            with self.subTest(**bad):
                with self.assertRaises(ValueError):
                    synth.generate_corpus(count=1, **{**KW, **bad})


class SpokenNumberTests(unittest.TestCase):
    def test_numbers_render_as_speech(self):
        """Dictation is speech. Writing "20" would skip the spoken-to-digit normalization the
        extractor actually has to perform on a real transcript."""
        for n, expected in [(5, "five"), (15, "fifteen"), (20, "twenty"), (23, "twenty-three"),
                            (45, "forty-five"), (60, "sixty"), (67, "sixty-seven")]:
            self.assertEqual(synth.spoken_number(n), expected)

    def test_durations_are_never_written_as_digits(self):
        """Scoped to DURATIONS, not to every digit: "Follow-up, week 3" is genuinely how a
        therapist speaks and appears in real transcripts. What must stay spoken is the minutes,
        because those are what the extractor has to normalize."""
        for s in synth.generate_corpus(count=10, **{**KW, "complexity": "high"}):
            with self.subTest(id=s.id):
                self.assertNotRegex(
                    s.transcript, r"\d+\s*(?:minutes?|mins?)\b",
                    "durations must be spoken words so the extractor's spoken-to-digit "
                    "normalization is actually exercised")


if __name__ == "__main__":
    unittest.main()
