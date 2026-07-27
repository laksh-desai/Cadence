"""Consistency invariants for the form configuration.

Carry-forward and completeness-mode behaviour is configured in four places that MUST agree:
each template's `carry:`/`mode:` frontmatter, `forms.CARRY_FORWARD_FORM_IDS`,
`forms.CARRY_SECTION_LABELS`, and `carry_forward.CARRY_FIELD_HEADING_MAP`. Editing one without the
others would silently break carry-forward or flip a form's completeness mode — these tests catch
that drift. Pure config, no DB/model.

    .venv/Scripts/python.exe -m unittest tests.test_forms_config -v
"""

import unittest

from app.generate.forms import (
    CARRY_FORWARD_FORM_IDS,
    CARRY_SECTION_LABELS,
    FORM_ORDER,
    FORMS,
)
from app.storage.carry_forward import CARRY_FIELD_HEADING_MAP

# The practice trimmed the built-in set to its two evaluations + the follow-up (the rest were
# removed; users rebuild what they need via the Templates tab). Both Initial Evaluations are
# require mode; "initial_updated" is the block-structured variant. No built-in omit forms remain.
REQUIRE_FORMS = {"initial", "initial_updated", "followup"}
OMIT_FORMS = set()


class FormConfigConsistencyTests(unittest.TestCase):
    def test_all_forms_present(self):
        self.assertEqual(len(FORM_ORDER), 3)
        self.assertEqual(set(FORMS), set(FORM_ORDER))

    def test_modes_match_claude_md(self):
        self.assertEqual({fid for fid, f in FORMS.items() if f.mode == "require"}, REQUIRE_FORMS)
        self.assertEqual({fid for fid, f in FORMS.items() if f.mode == "omit"}, OMIT_FORMS)

    def test_every_mode_is_valid(self):
        for fid, f in FORMS.items():
            self.assertIn(f.mode, ("require", "omit"), fid)

    def test_carry_flag_matches_carry_forward_ids(self):
        self.assertEqual({fid for fid, f in FORMS.items() if f.carry}, CARRY_FORWARD_FORM_IDS)

    def test_carry_section_labels_keys_match_carry_forms(self):
        self.assertEqual(set(CARRY_SECTION_LABELS), CARRY_FORWARD_FORM_IDS)

    def test_carry_field_heading_map_keys_match_carry_forms(self):
        self.assertEqual(set(CARRY_FIELD_HEADING_MAP), CARRY_FORWARD_FORM_IDS)

    def test_initial_eval_never_carries_forward(self):
        # CLAUDE.md: the Initial Evaluation is the first visit and never carries forward.
        self.assertFalse(FORMS["initial"].carry)

    def test_every_form_has_a_nonempty_spec(self):
        for fid, f in FORMS.items():
            with self.subTest(form=fid):
                self.assertTrue(f.spec.strip(), f"{fid} has an empty spec body")
                self.assertTrue(f.name.strip(), f"{fid} has no name")


if __name__ == "__main__":
    unittest.main()
