"""Repetition-loop guard (app/generate/loopguard.py). Made-up note text only."""

import unittest

from app.generate import loopguard, postprocess

LOOP = ("Patient ambulates 150 feet with a rolling walker and contact guard. " * 6).strip()


class LoopGuardTests(unittest.TestCase):
    def test_a_sentence_written_over_and_over_is_a_loop(self):
        self.assertTrue(loopguard.is_looping("## Objective Summary\n" + LOOP))

    def test_a_normal_note_is_not_a_loop(self):
        note = ("## Objective Summary\nPatient ambulates 150 feet with a rolling walker and contact guard.\n"
                "## Functional Mobility\nSit to stand with minimal assist from a standard chair.\n"
                "## Plan\nContinue skilled PT twice weekly for four weeks.")
        self.assertFalse(loopguard.is_looping(note))

    def test_short_phrases_may_repeat(self):
        self.assertFalse(loopguard.is_looping("Tolerated well. " * 10))

    def test_repeated_sentences_collapse_to_the_first_copy(self):
        out = loopguard.collapse_repeats([{"heading": "Objective Summary", "body": LOOP + " Knee AROM 5 to 90 degrees today."}])
        body = out[0]["body"]
        self.assertEqual(body.count("Patient ambulates 150 feet"), 1)
        self.assertIn("Knee AROM 5 to 90 degrees today.", body)  # new content is kept

    def test_repeated_lines_collapse(self):
        body = "\n".join(["- Left knee flexion 90 degrees, extension lacking 5 degrees."] * 5 + ["- Quadriceps 3+/5."])
        out = loopguard.collapse_repeats([{"heading": "Musculoskeletal Assessment", "body": body}])
        self.assertEqual(out[0]["body"].count("Left knee flexion"), 1)
        self.assertIn("Quadriceps 3+/5.", out[0]["body"])

    def test_an_identical_repeated_section_is_dropped_but_a_different_one_kept(self):
        s = {"heading": "Objective Summary", "body": "Patient ambulates 150 feet with a rolling walker today."}
        other = {"heading": "Objective Summary", "body": "Balance improved on single-leg stance testing today, 8 seconds."}
        out = loopguard.collapse_repeats([s, dict(s), other])
        self.assertEqual(len(out), 2)

    def test_postprocess_removes_the_loop(self):
        out = postprocess.apply("followup", [{"heading": "Objective Summary", "body": LOOP}])
        self.assertEqual(out[0]["body"].count("Patient ambulates 150 feet"), 1)


class LegitimateRepeatsAreNotLoops(unittest.TestCase):
    """The first loop guard counted repeats over the WHOLE note and cut off real notes."""

    def test_repeated_flags_across_sections_are_not_a_loop(self):
        note = "\n".join(
            f"## Section {i}\nFinding number {i} about the left knee today.\n"
            "[[NEEDS: not stated in the dictation — clinician to confirm]]" for i in range(8))
        self.assertFalse(loopguard.is_looping(note))

    def test_a_sentence_restated_far_apart_is_not_a_loop(self):
        rep = "Patient tolerated the exercise without any increase in pain."
        filler = [f"Distinct finding number {i} with enough words in it." for i in range(13)]
        self.assertFalse(loopguard.is_looping("\n".join([rep] + filler + [rep] + filler + [rep])))

    def test_back_to_back_repetition_is_a_loop(self):
        loop = "Walked 100 feet with the walker and cues. Balance at the counter with min assist. " * 3
        self.assertTrue(loopguard.is_looping(loop))


if __name__ == "__main__":
    unittest.main()
