"""Tests for prompt assembly (app/generate/prompt.py).

Covers the two decisions the prompt builder makes that materially change model
behavior: which completeness rule (require vs omit) gets injected, and the closed
carry-forward-label list that a 4B model follows far better than an abstract rule.
render_prior_block's "no usable snapshot still instructs the model" behavior is the
carry-forward feature's front line. Pure functions -- no DB, no model.

    .venv/Scripts/python.exe -m unittest tests.test_prompt -v
"""

import unittest

from app.generate.forms import FORMS, FormSpec
from app.generate.prompt import (
    NO_PRIOR_MESSAGE,
    PatientContext,
    build_prompt,
    render_prior_block,
)
from app.generate.rules import MODE_RULE_OMIT, MODE_RULE_REQUIRE, OUTPUT_FORMAT

PATIENT = PatientContext(name="Jane Doe", sub="MRN 123 · DOB 01/01/1970 · L knee OA")

# The built-in set is now all require-mode; construct a throwaway omit, non-carry form to
# exercise the omit-mode / non-carry prompt paths without depending on a shipped omit template.
OMIT_FORM = FormSpec(id="_omit_test", name="Omit Test Note", mode="omit", carry=False, spec="Sections: A; B.")


class RenderPriorBlockTests(unittest.TestCase):
    def test_non_carry_form_returns_empty(self):
        self.assertEqual(render_prior_block(OMIT_FORM, None, True), "")

    def test_carry_form_no_snapshot_still_instructs(self):
        # A carry form with nothing to carry must still tell the model to flag the
        # sections, not silently drop the instruction.
        self.assertEqual(render_prior_block(FORMS["followup"], None, True), NO_PRIOR_MESSAGE)

    def test_use_prior_false_returns_no_prior_message(self):
        snap = {"functional_status": "Ambulates 150ft."}
        self.assertEqual(render_prior_block(FORMS["followup"], snap, False), NO_PRIOR_MESSAGE)

    def test_empty_snapshot_treated_as_no_prior(self):
        self.assertEqual(render_prior_block(FORMS["followup"], {}, True), NO_PRIOR_MESSAGE)

    def test_populated_snapshot_included(self):
        snap = {
            "precautions": "Weight-bearing as tolerated.",
            "functional_status": "Ambulates 150ft with walker.",
            "short_term_goals": "Independent 200ft in 2 weeks.",
            "long_term_goals": "Community ambulation.",
        }
        block = render_prior_block(FORMS["followup"], snap, True)
        self.assertTrue(block.startswith("PRIOR NOTE"))
        self.assertIn("Weight-bearing as tolerated.", block)
        self.assertIn("Ambulates 150ft with walker.", block)
        self.assertIn("Independent 200ft in 2 weeks.", block)
        self.assertIn("Community ambulation.", block)

    def test_absent_fields_are_omitted(self):
        block = render_prior_block(FORMS["followup"], {"functional_status": "Ambulates 150ft."}, True)
        self.assertIn("Ambulates 150ft.", block)
        self.assertNotIn("Precautions:", block)
        self.assertNotIn("Short-Term Goals", block)


class BuildPromptTests(unittest.TestCase):
    def test_require_mode_rule_injected(self):
        prompt = build_prompt(FORMS["followup"], PATIENT, "walked 200ft today", "")
        self.assertIn(MODE_RULE_REQUIRE, prompt)
        self.assertNotIn(MODE_RULE_OMIT, prompt)

    def test_omit_mode_rule_injected(self):
        prompt = build_prompt(OMIT_FORM, PATIENT, "reports less pain", "")
        self.assertIn(MODE_RULE_OMIT, prompt)
        self.assertNotIn(MODE_RULE_REQUIRE, prompt)

    def test_core_pieces_present(self):
        prompt = build_prompt(FORMS["followup"], PATIENT, "walked 200ft today", "")
        self.assertIn(FORMS["followup"].name, prompt)
        self.assertIn("Jane Doe", prompt)
        self.assertIn("MRN 123 · DOB 01/01/1970 · L knee OA", prompt)
        self.assertIn("walked 200ft today", prompt)
        self.assertIn(OUTPUT_FORMAT, prompt)

    def test_carry_form_gets_closed_label_list(self):
        prompt = build_prompt(FORMS["followup"], PATIENT, "walked 200ft", "")
        self.assertIn("The ONLY sections in this note that may ever be tagged", prompt)
        # The followup labels should be named in that closed list.
        self.assertIn("Functional Status", prompt)

    def test_non_carry_form_omits_label_list(self):
        prompt = build_prompt(OMIT_FORM, PATIENT, "reports less pain", "")
        self.assertNotIn("The ONLY sections in this note that may ever be tagged", prompt)

    def test_extra_info_block_present_when_provided(self):
        prompt = build_prompt(FORMS["followup"], PATIENT, "walked", "", extra_info="BP 128/78, HR 72")
        self.assertIn("ADDITIONAL DETAILS THE THERAPIST JUST PROVIDED", prompt)
        self.assertIn("BP 128/78, HR 72", prompt)

    def test_extra_info_absent_when_none(self):
        prompt = build_prompt(FORMS["followup"], PATIENT, "walked", "")
        self.assertNotIn("ADDITIONAL DETAILS THE THERAPIST JUST PROVIDED", prompt)

    def test_empty_prior_block_does_not_leave_dangling_separator(self):
        # prior_block="" must be filtered out of the joined prompt, not produce a
        # run of blank lines that could confuse the model's section parsing.
        prompt = build_prompt(OMIT_FORM, PATIENT, "reports less pain", "")
        self.assertNotIn("\n\n\n\n", prompt)


if __name__ == "__main__":
    unittest.main()
