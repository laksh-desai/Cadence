"""Which sections a change request touches, and what the scoped prompt must look like.

"Ask for changes" used to re-emit the WHOLE note to change one line. Measured on a real 14-section
note that meant: the change landed 3 times in 5, the note came back byte-identical twice, and one
"successful" revision DELETED four sections and reworded four more. Scoping the rewrite to the
section the clinician named took that to 4 in 5 applied, zero collateral, and ~20 seconds instead
of minutes.

Two halves are tested here, because they fail differently:

  * SELECTION is deterministic and must refuse to guess. Picking the wrong section is worse than
    not scoping at all — the clinician's change silently lands somewhere else.
  * The PROMPT's shape is load-bearing in ways that are not obvious, and every rule below is one
    the 4B actually broke. Those are regression tests for measured failures, not style checks.

    .venv/Scripts/python.exe -m unittest tests.test_revise_scoping -v
"""

import unittest

from app.generate.forms import FORMS
from app.generate.prompt import (
    build_scoped_revise_prompt,
    is_structural_instruction,
    select_revise_sections,
)

SECTIONS = [
    {"heading": "Summary of Daily Skilled Services", "body": "Worked on gait.", "carried_forward": False},
    {"heading": "Precautions", "body": "Weight-bearing as tolerated.", "carried_forward": False},
    {"heading": "Pain - At Rest", "body": "4", "carried_forward": False},
    {"heading": "Pain - With Movement", "body": "6", "carried_forward": False},
    {"heading": "Vitals", "body": "BP 120/80.", "carried_forward": False},
    {"heading": "Response to Treatment", "body": "Good", "carried_forward": False},
    {"heading": "Short-Term Goals", "body": "Walk 300 feet.", "carried_forward": False},
]


class SelectionTests(unittest.TestCase):
    def test_names_the_section_it_is_about(self):
        for instruction, want in [
            ("In Response to Treatment, say she tolerated the session well.", "Response to Treatment"),
            ("Delete the Vitals section, I did not take vitals today.", "Vitals"),
            ("Write the Precautions section as a bulleted list.", "Precautions"),
        ]:
            with self.subTest(instruction=instruction):
                self.assertEqual(select_revise_sections(SECTIONS, instruction), [want])

    def test_the_more_specific_of_two_similar_headings_wins(self):
        """"Pain at rest should be 3 out of 10" covers ALL of "Pain - At Rest" but only half of
        "Pain - With Movement". Scoring by how much of the HEADING the instruction contains — not
        the reverse — is what separates them."""
        self.assertEqual(
            select_revise_sections(SECTIONS, "Pain at rest should be 3 out of 10, I misspoke."),
            ["Pain - At Rest"])

    def test_a_partial_match_refuses_rather_than_guesses(self):
        """An empty list means "fall back to the whole-note rewrite", which is the safe direction.
        Editing the wrong section is worse than editing all of them: the change appears not to
        have happened, and something the clinician never mentioned quietly moved."""
        for vague in ("Shorten it.", "Make the whole note more concise.", "Fix the wording."):
            with self.subTest(instruction=vague):
                self.assertEqual(select_revise_sections(SECTIONS, vague), [])

    def test_structural_requests_are_not_scoped(self):
        """Merging, reordering or moving changes WHICH sections exist and in what order. A
        per-section splice cannot express that, so these must reach the whole-note path."""
        for instruction in ("There are two Neuromuscular sections. Merge them into one.",
                            "Move the medications list to the top.",
                            "Reorder the goals before the plan.",
                            "Combine the two pain sections."):
            with self.subTest(instruction=instruction):
                self.assertTrue(is_structural_instruction(instruction))

    def test_an_ordinary_edit_is_not_mistaken_for_a_structural_one(self):
        for instruction in ("In Response to Treatment, say she tolerated the session well.",
                            "Pain at rest should be 3 out of 10."):
            with self.subTest(instruction=instruction):
                self.assertFalse(is_structural_instruction(instruction))

    def test_an_empty_instruction_selects_nothing(self):
        self.assertEqual(select_revise_sections(SECTIONS, ""), [])
        self.assertEqual(select_revise_sections(SECTIONS, "   "), [])


class ScopedPromptTests(unittest.TestCase):
    """Every assertion here is a failure that was MEASURED on the real model, not a preference."""

    def _prompt(self, targets, instruction):
        return build_scoped_revise_prompt(FORMS["followup"], SECTIONS, targets, instruction)

    def test_only_the_targeted_section_body_is_included(self):
        """The other sections' bodies never enter the prompt — which is what makes collateral
        drift impossible rather than merely discouraged. The model cannot reword what it cannot
        see."""
        p = self._prompt(["Response to Treatment"], "Say she tolerated it well.")
        self.assertIn("Good", p)
        for absent in ("Weight-bearing as tolerated.", "BP 120/80.", "Walk 300 feet."):
            self.assertNotIn(absent, p)

    def test_the_other_section_names_are_not_listed(self):
        """A "context only, do not output" list of the other headings was echoed VERBATIM into the
        model's answer, so the revision contained the prompt. It was guarding a speculative
        problem and causing a measured one."""
        p = self._prompt(["Response to Treatment"], "Say she tolerated it well.")
        self.assertNotIn("Short-Term Goals", p)
        self.assertNotIn("context only", p.lower())

    def test_the_prompt_ends_on_an_output_cue_not_on_prose(self):
        """A prompt ending in prose gets CONTINUED like prose — the model replayed the input
        section and carried on down the page. Ending on "REVISED SECTION:" turns it from
        "continue this document" into "fill this in"."""
        p = self._prompt(["Vitals"], "Delete the Vitals section.")
        self.assertTrue(p.rstrip().endswith("REVISED SECTION:"), p[-120:])

    def test_the_instruction_comes_after_the_current_text(self):
        """Recency matters on a 4B. With the change stated first and the rules last, the model
        optimised for the formatting rules and echoed the section unchanged."""
        p = self._prompt(["Vitals"], "Delete the Vitals section.")
        self.assertGreater(p.index("CHANGE THE CLINICIAN ASKED FOR"), p.index("CURRENT SECTION"))

    def test_it_says_the_body_must_change(self):
        p = self._prompt(["Response to Treatment"], "Say she tolerated it well.")
        self.assertIn("MUST DIFFER", p)

    def test_it_offers_the_delete_convention(self):
        """A scoped prompt has no way to express "remove this section" except by convention —
        without it, "delete the Vitals section" can only ever echo."""
        self.assertIn("[[DELETE]]", self._prompt(["Vitals"], "Delete the Vitals section."))

    def test_the_value_ban_survives_into_the_scoped_path(self):
        """Rule 1 does not get weaker because the prompt got smaller."""
        p = self._prompt(["Vitals"], "Add her heart rate.")
        self.assertIn("NEVER invent a clinical value", p)
        self.assertIn("[[NEEDS:", p)

    def test_several_targets_are_all_included(self):
        p = self._prompt(["Pain - At Rest", "Pain - With Movement"], "Drop both pain scores by one.")
        self.assertIn("## Pain - At Rest", p)
        self.assertIn("## Pain - With Movement", p)
        self.assertIn("SECTIONS", p)


if __name__ == "__main__":
    unittest.main()
