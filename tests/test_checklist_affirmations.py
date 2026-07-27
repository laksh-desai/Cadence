"""Tests for the deterministic checklist-affirmation stripper in postprocess.

The therapist reads intake forms aloud as "<fact>, yes"/"<fact>, no". The prompt asks
the model to convert these to declarative prose, but MedGemma 4B echoes the trailing
", yes" verbatim (observed six times across one real Initial Eval run, duplicated into
two sections). `strip_checklist_affirmations` drops a *statement-final* ", yes" only.

The load-bearing cases are the negatives: ", no" must NEVER be stripped (that would
invert clinical meaning), and a mid-clause ", yes," must be left alone. Those stay
prompt-only mitigations plus clinician review — see CLAUDE.md rule 17.

    .venv/Scripts/python.exe -m unittest tests.test_checklist_affirmations -v
"""

import unittest

from app.generate.postprocess import strip_checklist_affirmations


def _body(text):
    return strip_checklist_affirmations([{"heading": "Fall Risk", "body": text, "carried_forward": False}])[0]["body"]


class StripsTrailingYesTests(unittest.TestCase):
    def test_yes_before_period(self):
        self.assertEqual(_body("Patient reports fear of falling, yes."), "Patient reports fear of falling.")

    def test_yes_at_end_of_body(self):
        self.assertEqual(_body("Patient worries about falling, yes"), "Patient worries about falling")

    def test_yes_before_newline(self):
        self.assertEqual(_body("Unsteady on uneven ground, yes\nTUG not performed."), "Unsteady on uneven ground\nTUG not performed.")

    def test_capitalized_yes(self):
        self.assertEqual(_body("Fear of falling, Yes."), "Fear of falling.")

    def test_multiple_in_one_body(self):
        # The exact Fall Risk section from the real run.
        text = (
            "Patient reports fear of falling, yes. Patient worries about falling, yes. "
            "Patient feels unsteady on uneven ground, yes."
        )
        self.assertEqual(
            _body(text),
            "Patient reports fear of falling. Patient worries about falling. "
            "Patient feels unsteady on uneven ground.",
        )

    def test_no_double_space_when_space_before_period(self):
        self.assertEqual(_body("Fear of falling , yes ."), "Fear of falling .")


class DoesNotInvertOrCorruptTests(unittest.TestCase):
    """The dangerous failure mode: silently changing clinical meaning."""

    def test_no_is_never_stripped(self):
        self.assertEqual(_body("Fear of falling, no."), "Fear of falling, no.")

    def test_no_at_end_is_never_stripped(self):
        self.assertEqual(_body("History of falls, no"), "History of falls, no")

    def test_midclause_yes_is_left_alone(self):
        # ", yes," continues the sentence — not a checklist answer, don't touch it.
        self.assertEqual(_body("Fear of falling, yes, and difficulty on stairs."), "Fear of falling, yes, and difficulty on stairs.")

    def test_yes_as_a_word_without_comma_untouched(self):
        self.assertEqual(_body("The patient answered questions appropriately."), "The patient answered questions appropriately.")

    def test_unrelated_prose_untouched(self):
        text = "Walks 100 ft with a rolling walker, contact guard, forward head posture."
        self.assertEqual(_body(text), text)


class IntegratesWithApplyTests(unittest.TestCase):
    def test_apply_runs_the_stripper(self):
        from app.generate import postprocess

        sections = [{"heading": "Fall Risk", "body": "Reports fear of falling, yes.", "carried_forward": False}]
        out = postprocess.apply("initial", sections)
        self.assertEqual(out[0]["body"], "Reports fear of falling.")


if __name__ == "__main__":
    unittest.main()
