"""Tests for the deterministic dictation cleaner.

The dictation is now a raw MedASR speech-to-text transcript, so it arrives with
spoken hesitation sounds (um, uh, hmm...) that the model would otherwise echo into
the finished note. `clean_dictation` strips those unambiguous fillers BEFORE the text
reaches the model — the model-independent half of the fix (the WRITING RULES prompt
is the other half). Two things must stay true and are easy to break:

  1. It removes the fillers (and tidies the whitespace/punctuation they leave behind).
  2. It NEVER removes a real clinical word — especially tokens that look like filler
     but carry meaning: "mm" (millimeters), "er"/"ER" (external rotation; ER), and
     any word that merely CONTAINS a filler substring ("summer", "number", "her").

`build_prompt` is the single dictation chokepoint, so the last group of tests locks
in that the cleaning actually happens there (and therefore for guided mode too).

    .venv/Scripts/python.exe -m unittest tests.test_clean_dictation -v
"""

import unittest

from app.generate.forms import load_forms
from app.generate.prompt import PatientContext, build_prompt, clean_dictation, render_prior_block


FORMS = load_forms()


class FillerRemovalTests(unittest.TestCase):
    def test_removes_standalone_fillers(self):
        self.assertEqual(clean_dictation("um the knee looks better"), "the knee looks better")
        self.assertEqual(clean_dictation("we did uh some gait training"), "we did some gait training")
        self.assertEqual(clean_dictation("hmm let me think"), "let me think")

    def test_removes_fillers_case_insensitively(self):
        self.assertEqual(clean_dictation("Um, we started"), "we started")
        self.assertEqual(clean_dictation("UH the patient"), "the patient")

    def test_removes_multiple_and_repeated_fillers(self):
        self.assertEqual(
            clean_dictation("um, so today, uh, we did ther ex"),
            "so today, we did ther ex",
        )

    def test_removes_filler_at_end(self):
        self.assertEqual(clean_dictation("we finished with stretching um"), "we finished with stretching")

    def test_handles_comma_after_filler(self):
        self.assertEqual(clean_dictation("uh, patient reports less pain"), "patient reports less pain")

    def test_collapses_leftover_whitespace(self):
        self.assertNotIn("  ", clean_dictation("we did um some exercises"))

    def test_empty_and_none_pass_through(self):
        self.assertEqual(clean_dictation(""), "")
        self.assertIsNone(clean_dictation(None))
        self.assertEqual(clean_dictation("   "), "")


class DoesNotEatClinicalContentTests(unittest.TestCase):
    """The dangerous failure mode: silently deleting a real value."""

    def test_keeps_words_that_merely_contain_a_filler(self):
        for phrase in ["summer", "number of reps", "her knee", "humerus", "maximum assist"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(clean_dictation(phrase), phrase)

    def test_keeps_millimeters(self):
        # "mm" is a real unit and is intentionally NOT in the filler set.
        self.assertEqual(clean_dictation("effusion measured 20 mm"), "effusion measured 20 mm")

    def test_keeps_external_rotation_and_ER_abbreviations(self):
        # "er"/"ER" collide with external rotation / emergency room -- never stripped.
        self.assertEqual(clean_dictation("shoulder ER to 45 degrees"), "shoulder ER to 45 degrees")
        self.assertEqual(clean_dictation("seen in the ER last week"), "seen in the ER last week")

    def test_keeps_meaning_bearing_discourse_words(self):
        # "so"/"like" can carry meaning; left for the prompt, not stripped here.
        text = "so the patient walked like a normal gait pattern"
        self.assertEqual(clean_dictation(text), text)

    def test_preserves_numbers_and_measurements(self):
        text = "40 minutes of therapeutic exercise, pain 3 out of 10"
        self.assertEqual(clean_dictation(text), text)


class TranscriptArtifactTests(unittest.TestCase):
    """Pasted-transcript junk (timestamps, speaker labels, [inaudible]-type annotations) is
    stripped, but never a real clinical value."""

    def test_strips_bracketed_and_paren_timestamps(self):
        self.assertEqual(clean_dictation("[00:12:34] patient walked 200 feet"), "patient walked 200 feet")
        self.assertEqual(clean_dictation("gait training (1:05) went well"), "gait training went well")

    def test_strips_bare_hhmmss_timestamp(self):
        self.assertEqual(clean_dictation("00:03:22 started with stretching"), "started with stretching")

    def test_strips_leading_line_timestamp_only(self):
        self.assertEqual(clean_dictation("00:15 so today we worked on balance"), "so today we worked on balance")

    def test_keeps_midsentence_clock_and_dosing_times(self):
        # A one-colon time mid-sentence (dosing/appointment) must survive.
        self.assertEqual(clean_dictation("takes lisinopril at 8:00 each morning"),
                         "takes lisinopril at 8:00 each morning")

    def test_keeps_blood_pressure_and_ratios(self):
        # BP uses a slash, ratios are one-digit minutes -> neither looks like a timestamp.
        self.assertEqual(clean_dictation("BP 128/76, inspiratory ratio 2:1"), "BP 128/76, inspiratory ratio 2:1")

    def test_strips_asr_annotations(self):
        self.assertEqual(clean_dictation("patient reports [inaudible] pain in the knee"),
                         "patient reports pain in the knee")
        self.assertEqual(clean_dictation("(background noise) resumed gait training"), "resumed gait training")

    def test_strips_speaker_labels_from_pasted_transcript(self):
        pasted = "Therapist: how is the knee today\nPatient: much better, less pain"
        cleaned = clean_dictation(pasted)
        self.assertNotIn("Therapist:", cleaned)
        self.assertNotIn("Patient:", cleaned)
        self.assertIn("how is the knee today", cleaned)
        self.assertIn("much better, less pain", cleaned)

    def test_strips_numbered_speaker_labels(self):
        self.assertEqual(clean_dictation("Speaker 1: we did ther ex"), "we did ther ex")
        self.assertEqual(clean_dictation("SPEAKER_02 - patient tolerated well"), "patient tolerated well")

    def test_does_not_touch_clinical_field_labels(self):
        # "Assessment:" / a plan "PT:" line are NOT diarization labels.
        text = "Assessment: rotator cuff tendinopathy\nPlan: PT twice a week"
        self.assertIn("Assessment: rotator cuff tendinopathy", clean_dictation(text))
        self.assertIn("PT twice a week", clean_dictation(text))

    def test_does_not_touch_our_own_output_markers(self):
        # [[NEEDS: ...]] / [[CPT: ...]] must never be caught by annotation stripping.
        text = "[[NEEDS: minutes]] and [[CPT: 97110 — confirm]]"
        self.assertEqual(clean_dictation(text), text)


class CleaningHappensInBuildPromptTests(unittest.TestCase):
    """Locks in that cleaning is wired at the single dictation chokepoint."""

    def _prompt(self, summary, extra=None):
        form = FORMS["followup"]
        prior = render_prior_block(form, None, False)
        ctx = PatientContext(name="Test Patient", sub="condition")
        return build_prompt(form, ctx, summary, prior, extra)

    def test_summary_filler_absent_from_prompt(self):
        prompt = self._prompt("um we did uh some gait training today")
        # The dictation block should carry the cleaned text, not the raw fillers.
        self.assertIn("we did some gait training today", prompt)
        self.assertNotIn("um we did", prompt)

    def test_extra_info_is_also_cleaned(self):
        prompt = self._prompt("gait training", "uh minutes were 20")
        self.assertIn("minutes were 20", prompt)
        self.assertNotIn("uh minutes", prompt)

    def test_clinical_content_survives_the_prompt(self):
        prompt = self._prompt("effusion 20 mm, shoulder ER 45 degrees")
        self.assertIn("20 mm", prompt)
        self.assertIn("ER 45 degrees", prompt)


if __name__ == "__main__":
    unittest.main()
