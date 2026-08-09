"""Tests for the deterministic post-parse safety net (app/generate/postprocess.py).

These lock in CLAUDE.md generation rules #11 and #12 — the corrections that must
hold *regardless of model compliance*, because MedGemma 4B reliably violates the
prompt no matter how it's worded:
  - drops invented "Minutes: 0" not-performed placeholder sections,
  - strips [[CARRIED FORWARD]] from any heading that isn't one of the form's real
    carry-forward labels,
  - never lets a model-authored CPT/ICD code through (replaces it with a gap marker).

Pure functions — no DB, no model. Run with:
    .venv/Scripts/python.exe -m unittest tests.test_postprocess -v
"""

import unittest

from app.generate import postprocess

CODE_MARKER = "[[NEEDS: code not stated by therapist — clinician to assign]]"


def _sec(heading, body, carried=False):
    return {"heading": heading, "body": body, "carried_forward": carried}


class DropUnperformedTests(unittest.TestCase):
    def test_body_opening_with_minutes_zero_is_dropped(self):
        secs = [_sec("Ultrasound", "Minutes: 0 — not performed today.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), [])

    def test_case_insensitive_and_leading_whitespace(self):
        secs = [
            _sec("A", "minutes: 0 nothing"),
            _sec("B", "   Minutes: 0\nno treatment"),
        ]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), [])

    def test_real_treatment_with_nonzero_minutes_is_kept(self):
        secs = [_sec("Therapeutic Exercise", "Minutes: 20\nPerformed knee extensions.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), secs)

    def test_zero_not_a_word_boundary_is_kept(self):
        # "Minutes: 05" is a nonzero (if oddly written) duration -- the \b in the
        # pattern means only a bare 0 counts, so this must survive.
        secs = [_sec("Manual Therapy", "Minutes: 05 of soft tissue work.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), secs)

    def test_minutes_zero_not_at_body_start_is_kept(self):
        # Only a body that OPENS with the placeholder is a not-performed marker.
        secs = [_sec("Note", "Total treatment time excluding rest: Minutes: 0 rest breaks.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), secs)


class EnforceCarryTagsTests(unittest.TestCase):
    def test_real_carry_label_keeps_flag(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Functional Status", "x", True)])
        self.assertTrue(out[0]["carried_forward"])

    def test_non_carry_heading_is_stripped(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Therapeutic Exercise", "x", True)])
        self.assertFalse(out[0]["carried_forward"])

    def test_collapsed_goals_heading_matches_bidirectionally(self):
        # A collapsed single "Goals" heading must still be treated as a carry label even
        # though followup's label list says "Short-Term Goals" / "Long-Term Goals".
        out = postprocess.enforce_carry_tags("followup", [_sec("Goals", "x", True)])
        self.assertTrue(out[0]["carried_forward"])

    def test_form_with_no_carry_labels_strips_everything(self):
        out = postprocess.enforce_carry_tags("initial", [_sec("Assessment", "x", True)])
        self.assertFalse(out[0]["carried_forward"])

    def test_literal_body_tag_stripped_on_non_carry_form(self):
        # Real-run #3: a non-carry Initial Eval had "[[CARRIED FORWARD]]" written into every body.
        out = postprocess.enforce_carry_tags(
            "initial", [_sec("Chief Complaint", "Status post right THA. [[CARRIED FORWARD]]", False)])
        self.assertNotIn("CARRIED FORWARD", out[0]["body"])
        self.assertFalse(out[0]["carried_forward"])

    def test_literal_body_tag_marks_carry_on_allowed_section(self):
        # On a real carry section, a tag in the BODY (not heading) must still mark it carried.
        out = postprocess.enforce_carry_tags(
            "followup", [_sec("Functional Status", "Ambulates 200 ft. [[CARRIED FORWARD]]", False)])
        self.assertTrue(out[0]["carried_forward"])
        self.assertNotIn("CARRIED FORWARD", out[0]["body"])


class TemplateEchoTests(unittest.TestCase):
    """Real-run #15: the model output the template's field INSTRUCTIONS as the values. Flag those;
    never touch a real value that merely shares a couple of words."""

    def test_echoed_functional_status_instruction_flagged(self):
        body = "ambulation distance, assistive device, assist level, and stairs, updated to reflect today."
        out = postprocess.flag_template_echo("followup", [_sec("Functional Status", body)])
        self.assertIn("[[NEEDS:", out[0]["body"])
        self.assertNotIn("assist level", out[0]["body"])

    def test_echoed_goal_instruction_flagged(self):
        out = postprocess.flag_template_echo(
            "followup", [_sec("Short-Term Goals", "mark MET if today's data shows it achieved.")])
        self.assertIn("[[NEEDS:", out[0]["body"])

    def test_echoed_plan_instruction_flagged(self):
        out = postprocess.flag_template_echo(
            "followup", [_sec("Plan", "plan for the next visit: frequency, progression, and any change to the assist level.")])
        self.assertIn("[[NEEDS:", out[0]["body"])

    def test_real_functional_status_value_not_flagged(self):
        body = "Ambulates 200 feet with a single point cane at contact guard; managed six steps with the rail."
        out = postprocess.flag_template_echo("followup", [_sec("Functional Status", body)])
        self.assertEqual(out[0]["body"], body)

    def test_real_goal_value_not_flagged(self):
        out = postprocess.flag_template_echo("followup", [_sec("Short-Term Goals", "MET")])
        self.assertEqual(out[0]["body"], "MET")

    def test_strips_echoed_carry_forward_instruction_from_heading(self):
        # The model copies the spec's "[carry forward]" instruction into the heading; drop it.
        out = postprocess.strip_carry_instruction_headings([_sec("Precautions [carry forward]", "x", False)])
        self.assertEqual(out[0]["heading"], "Precautions")

    def test_strips_carry_instruction_with_trailing_note(self):
        out = postprocess.strip_carry_instruction_headings(
            [_sec("Short-Term Goals [carry forward — mark MET]", "x", False)]
        )
        self.assertEqual(out[0]["heading"], "Short-Term Goals")

    def test_clean_heading_left_untouched(self):
        out = postprocess.strip_carry_instruction_headings([_sec("Functional Status", "x", False)])
        self.assertEqual(out[0]["heading"], "Functional Status")

    def test_code_field_lines_are_flagged(self):
        # Block-format codes live as body field lines, not headings — flag the model-authored value.
        body = "Frequency: 2x/week\nMedical Diagnosis (ICD-10): M54.5\nTreatment Procedures (CPT): 97110"
        out = postprocess.flag_code_field_lines([_sec("Plan", body, False)])[0]["body"]
        self.assertIn("Medical Diagnosis (ICD-10): [[NEEDS:", out)
        self.assertIn("Treatment Procedures (CPT): [[NEEDS:", out)
        self.assertNotIn("M54.5", out)          # fabricated ICD code removed
        self.assertNotIn("97110", out)
        self.assertIn("Frequency: 2x/week", out)  # non-code field untouched

    def test_treatment_diagnosis_in_words_not_flagged(self):
        out = postprocess.flag_code_field_lines([_sec("Plan", "Treatment Diagnosis: Rotator cuff tendinopathy", False)])[0]["body"]
        self.assertIn("Rotator cuff tendinopathy", out)
        self.assertNotIn("[[NEEDS:", out)

    def test_false_stays_false(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Functional Status", "x", False)])
        self.assertFalse(out[0]["carried_forward"])

    def test_body_and_heading_are_preserved(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Precautions", "weight bearing", True)])
        self.assertEqual(out[0]["heading"], "Precautions")
        self.assertEqual(out[0]["body"], "weight bearing")


class FlagCodeSectionsTests(unittest.TestCase):
    def test_cpt_heading_body_replaced(self):
        out = postprocess.flag_code_sections([_sec("CPT Codes", "97110, 97140")])
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_icd_heading_body_replaced(self):
        out = postprocess.flag_code_sections([_sec("ICD-10 Diagnosis", "M25.51")])
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_case_insensitive(self):
        out = postprocess.flag_code_sections([_sec("Billing cpt", "anything")])
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_non_code_heading_untouched(self):
        out = postprocess.flag_code_sections([_sec("Assessment", "Tolerating well.")])
        self.assertEqual(out[0]["body"], "Tolerating well.")

    def test_word_boundary_avoids_false_positive(self):
        # A heading that merely contains the letters (e.g. "Indication") must not trip.
        out = postprocess.flag_code_sections([_sec("Indications for Continued Care", "x")])
        self.assertEqual(out[0]["body"], "x")


class ApplyIntegrationTests(unittest.TestCase):
    def test_all_three_corrections_compose(self):
        sections = [
            _sec("Ultrasound", "Minutes: 0 not performed"),          # dropped
            _sec("Functional Status", "Ambulates 200ft.", True),     # carry kept
            _sec("Gait Training", "Walked 200ft.", True),            # carry stripped
            _sec("CPT Code", "97110"),                               # body flagged
        ]
        out = postprocess.apply("followup", sections)
        headings = [s["heading"] for s in out]
        self.assertNotIn("Ultrasound", headings)  # dropped entirely
        by_heading = {s["heading"]: s for s in out}
        self.assertTrue(by_heading["Functional Status"]["carried_forward"])
        self.assertFalse(by_heading["Gait Training"]["carried_forward"])
        self.assertEqual(by_heading["CPT Code"]["body"], CODE_MARKER)


if __name__ == "__main__":
    unittest.main()
