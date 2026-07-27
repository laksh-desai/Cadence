"""Tests for the note-fidelity fixes: the Ollama context/output ceiling, the expanded
Initial Evaluation template, and the generation rules added to close the omission /
checklist / ASR / conflict / mapping failures found in real testing.

These are all pure/offline: they inspect the request payload, the loaded FormSpec,
and the assembled prompt string -- no Ollama, no DB, no server lifespan.

    .venv/Scripts/python.exe -m unittest tests.test_generation_fidelity -v
"""

import unittest

from app.generate.forms import FormSpec, load_forms
from app.generate.ollama_client import NUM_CTX, NUM_PREDICT, _build_payload
from app.generate.prompt import PatientContext, build_prompt, render_prior_block


FORMS = load_forms()

# The built-in set is now all require-mode; a throwaway omit form exercises the omit-mode path.
_OMIT_FORM = FormSpec(id="_omit", name="Omit Note", mode="omit", carry=False, spec="Sections: A; B.")


def _prompt_for(fid):
    form = FORMS[fid]
    prior = render_prior_block(form, None, False)
    ctx = PatientContext(name="Test Patient", sub="condition")
    return build_prompt(form, ctx, "did some therapy today", prior, None)


def _prompt_omit():
    prior = render_prior_block(_OMIT_FORM, None, False)
    ctx = PatientContext(name="Test Patient", sub="condition")
    return build_prompt(_OMIT_FORM, ctx, "did some therapy today", prior, None)


class OllamaContextCeilingTests(unittest.TestCase):
    """The 4096 ceiling silently dropped the transcript tail and truncated the note."""

    def test_num_ctx_raised_above_old_ceiling(self):
        self.assertGreaterEqual(NUM_CTX, 8192)

    def test_num_predict_is_set_and_leaves_room_in_context(self):
        self.assertGreater(NUM_PREDICT, 0)
        # Output cap must leave room for the prompt inside the context window.
        self.assertLess(NUM_PREDICT, NUM_CTX)

    def test_payload_carries_both_options(self):
        opts = _build_payload("hello")["options"]
        self.assertEqual(opts["num_ctx"], NUM_CTX)
        self.assertEqual(opts["num_predict"], NUM_PREDICT)

    def test_payload_keeps_model_warm(self):
        # keep_alive keeps MedGemma resident between notes so only the first pays the cold-load cost.
        self.assertIn("keep_alive", _build_payload("hello"))


class InitialTemplateHasTheMissingSectionsTests(unittest.TestCase):
    """Omissions #1/#4/#5/#6/#14/#15 were template gaps, not model failures."""

    def setUp(self):
        self.spec = FORMS["initial"].spec

    def test_spec_now_names_the_previously_missing_sections(self):
        for needed in [
            "Medications",
            "Allergies",
            "Social History",
            "Living Environment",
            "prior therapy",
            "gait deviations",
            "community mobility",
            "complexity",
            "discharge",
            "participation",
            "certification period",
        ]:
            with self.subTest(section=needed):
                self.assertIn(needed.lower(), self.spec.lower())

    def test_guided_walkthrough_covers_meds_allergies_and_social(self):
        labels = " ".join(s.label.lower() for s in FORMS["initial"].steps)
        self.assertIn("medication", labels)
        self.assertIn("allergies", labels)
        self.assertIn("social history", labels)

    def test_still_does_not_prompt_for_a_cpt_code(self):
        # Rule #12: never invite the model to author a billing code.
        self.assertNotIn("cpt", self.spec.lower())


class NewWritingRulesReachThePromptTests(unittest.TestCase):
    """The rules the user asked for must actually be in the assembled prompt."""

    def setUp(self):
        self.require_prompt = _prompt_for("initial")  # require mode
        self.omit_prompt = _prompt_omit()             # omit mode

    def test_checklist_to_narrative_rule_present(self):
        self.assertIn("checklist answers into declarative", self.require_prompt)

    def test_asr_repair_and_unclear_marker_present(self):
        self.assertIn("unclear dictation", self.require_prompt)

    def test_conflict_normalization_rule_present(self):
        self.assertIn("dictation also stated", self.require_prompt)

    def test_pot_field_mapping_rule_present(self):
        self.assertIn("visits per week", self.require_prompt)
        self.assertIn("minutes per session", self.require_prompt)

    def test_mmt_notation_rule_present(self):
        self.assertIn("standard notation", self.require_prompt)

    def test_no_cross_section_copying_rule_present(self):
        self.assertIn("more than one section", self.require_prompt)

    def test_no_mid_section_truncation_rule_present(self):
        self.assertIn("mid-sentence", self.require_prompt)

    def test_writing_rules_apply_to_both_modes(self):
        # WRITING_RULES_LEAD is shared, so these must appear regardless of mode.
        self.assertIn("standard notation", self.omit_prompt)
        self.assertIn("checklist answers into declarative", self.omit_prompt)


class CompleteExtractionIsRequireModeOnlyTests(unittest.TestCase):
    """The strong 'never drop a stated fact' rule belongs to require mode, so it
    doesn't push the patient-facing After-Visit Letter (omit mode) to dump everything.
    """

    def test_present_in_require_mode(self):
        self.assertIn("Dropping a stated fact", _prompt_for("initial"))
        self.assertIn("every medication with its dose", _prompt_for("initial"))

    def test_absent_in_omit_mode(self):
        self.assertNotIn("Dropping a stated fact", _prompt_omit())


if __name__ == "__main__":
    unittest.main()
