"""Tests for the deterministic CPT suggestion (app/generate/cpt.py, CLAUDE.md rule 12).

The point: the code comes from a fixed table keyed on the stated intervention (the section heading),
never from a model inference — and the judgment-heavy cases (eval complexity, units) are surfaced,
not auto-assigned.

    .venv/Scripts/python.exe -m unittest tests.test_cpt -v
"""

import unittest

from app.generate.cpt import code_for_heading, suggest_codes


def _sec(heading, body="Minutes: 15. Performed as tolerated."):
    return {"heading": heading, "body": body, "carried_forward": False}


class CodeForHeadingTests(unittest.TestCase):
    def test_common_interventions_map(self):
        self.assertEqual(code_for_heading("Therapeutic Exercise"), ("97110", "Therapeutic Exercise"))
        self.assertEqual(code_for_heading("Gait Training"), ("97116", "Gait Training"))
        self.assertEqual(code_for_heading("Manual Therapy"), ("97140", "Manual Therapy"))

    def test_specific_beats_generic(self):
        # "Neuromuscular Re-education" must NOT be taken as a plain exercise (97110).
        self.assertEqual(code_for_heading("Neuromuscular Re-education"), ("97112", "Neuromuscular Re-education"))
        self.assertEqual(code_for_heading("Therapeutic Activities"), ("97530", "Therapeutic Activities"))

    def test_modalities_map(self):
        self.assertEqual(code_for_heading("Ultrasound"), ("97035", "Ultrasound"))
        self.assertEqual(code_for_heading("Iontophoresis"), ("97033", "Iontophoresis"))
        self.assertEqual(code_for_heading("Paraffin Bath"), ("97018", "Paraffin Bath"))
        self.assertEqual(code_for_heading("Whirlpool")[0], "97022")

    def test_non_intervention_heading_is_none(self):
        self.assertIsNone(code_for_heading("Chief Complaint"))
        self.assertIsNone(code_for_heading("Assessment Summary"))
        self.assertIsNone(code_for_heading("Plan of Treatment"))


class SuggestCodesTests(unittest.TestCase):
    def test_treatment_section_gets_confirmable_marker(self):
        out, _ = suggest_codes([_sec("Therapeutic Exercise")], "followup")
        self.assertIn("[[CPT: 97110 Therapeutic Exercise — confirm]]", out[0]["body"])

    def test_non_treatment_section_untouched(self):
        out, _ = suggest_codes([_sec("Chief Complaint", "Right knee pain.")], "followup")
        self.assertEqual(out[0]["body"], "Right knee pain.")

    def test_model_is_not_authoring_the_code(self):
        # The code is appended deterministically even though the body never mentioned a number.
        out, _ = suggest_codes([_sec("Manual Therapy", "To the right shoulder, 10 minutes.")], "followup")
        self.assertIn("97140", out[0]["body"])

    def test_strips_model_written_code_from_heading(self):
        # Real-run finding: the spec asks for "cpt", so the model put 97110 in the heading itself.
        out, _ = suggest_codes([_sec("Therapeutic Exercise 97110", "Quad sets performed.")], "followup")
        self.assertEqual(out[0]["heading"], "Therapeutic Exercise")
        self.assertIn("[[CPT: 97110 Therapeutic Exercise — confirm]]", out[0]["body"])

    def test_replaces_a_wrong_model_written_code(self):
        # Model wrote the WRONG code (97530) in the body; it must be removed, not trusted, and the
        # deterministic 97110 substituted.
        out, _ = suggest_codes([_sec("Therapeutic Exercise", "Strengthening. CPT 97530.")], "followup")
        self.assertNotIn("97530", out[0]["body"])
        self.assertIn("97110", out[0]["body"])

    def test_idempotent_when_marker_present(self):
        pre = _sec("Gait Training", "Minutes: 12. [[CPT: 97116 Gait Training — confirm]]")
        out, _ = suggest_codes([pre], "followup")
        self.assertEqual(out[0]["body"].count("[[CPT:"), 1)

    def test_eval_form_surfaces_complexity_choice_not_a_guess(self):
        _, extra = suggest_codes([_sec("Objective Summary", "…")], "initial")
        self.assertEqual(len(extra), 1)
        self.assertIn("97161", extra[0])
        self.assertIn("97163", extra[0])

    def test_non_eval_form_has_no_eval_flag(self):
        _, extra = suggest_codes([_sec("Therapeutic Exercise")], "followup")
        self.assertEqual(extra, [])

    def test_patient_facing_form_gets_no_codes(self):
        # An After-Visit Letter is not a billing document — no CPT even if it names an intervention.
        out, extra = suggest_codes([_sec("Therapeutic Exercise")], "avletter")
        self.assertNotIn("[[CPT:", out[0]["body"])
        self.assertEqual(extra, [])

    def test_referral_letter_gets_no_codes(self):
        out, _ = suggest_codes([_sec("Gait Training")], "referral")
        self.assertNotIn("[[CPT:", out[0]["body"])


if __name__ == "__main__":
    unittest.main()
