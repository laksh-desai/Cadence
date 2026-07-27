"""Locks the block-structured "Initial Evaluation — Updated Version" form (templates/initial_updated.md).

This form was added with an EXACT 4-block outline the clinician supplied; the point of these tests
is that a later edit can't silently reorder, drop, or reword a block/field without failing. It also
confirms the form behaves like the other Initial Evaluation: require mode, carry-forward OFF, and it
surfaces the evaluation-complexity review flag (an eval visit bills a per-visit evaluation CPT the
clinician selects — see app/generate/cpt.py). Pure config + pure functions; no DB/model/server.

    .venv/Scripts/python.exe -m unittest tests.test_initial_updated_form -v
"""

import unittest

from app.generate import cpt
from app.generate.forms import CARRY_SECTION_LABELS, FORM_ORDER, FORMS

FORM_ID = "initial_updated"


class InitialUpdatedFormTests(unittest.TestCase):
    def setUp(self):
        self.form = FORMS[FORM_ID]

    def test_registered_and_ordered_after_initial(self):
        self.assertIn(FORM_ID, FORM_ORDER)
        self.assertEqual(FORM_ORDER.index(FORM_ID), FORM_ORDER.index("initial") + 1)

    def test_metadata(self):
        self.assertEqual(self.form.name, "Initial Evaluation — Updated Version (experimental)")
        self.assertEqual(self.form.mode, "require")
        # Like the original Initial Evaluation, this is the first visit and never carries forward.
        self.assertFalse(self.form.carry)
        self.assertNotIn(FORM_ID, CARRY_SECTION_LABELS)

    def test_four_blocks_present_and_in_order(self):
        # The block variant emits four "## " SOAP sections (the ═══-divider form collapsed to one
        # section on the 4B model — see CLAUDE.md; explicit ## headings map to the app's parser).
        spec = self.form.spec
        blocks = ["## Subjective", "## Objective", "## Assessment", "## Plan"]
        positions = [spec.find(b) for b in blocks]
        for b, pos in zip(blocks, positions):
            self.assertNotEqual(pos, -1, f"block header missing from spec: {b!r}")
        self.assertEqual(positions, sorted(positions), "blocks are out of order in the spec")

    def test_exact_field_labels_preserved(self):
        # A representative field from each block — enough that a reorder/rename/drop trips a test.
        spec = self.form.spec
        for label in [
            # Subjective
            "Chief Complaint:", "History of Present Illness:", "Date of Onset:",
            "Mechanism / Cause:", "Course Since Onset:", "Current Medications:",
            "Prior Level of Function:", "Living Situation:", "Patient Goals:", "Pain:",
            # Objective
            "Outcome Measurement Tools:", "Handedness:", "Range of Motion:",
            "Neuromuscular:", "Functional Mobility / Gait:", "Special Tests:",
            # Assessment
            "Diagnosis:", "Clinical Presentation:", "Justification for Skilled Care:",
            "Rehab Potential:", "Short-Term Goals:", "Long-Term Goals:",
            # Plan
            "Frequency:", "Duration:", "Medicare Certification Dates:",
            "Treatment Procedures (CPT):", "Medical Diagnosis (ICD-10):", "Treatment Diagnosis:",
        ]:
            with self.subTest(label=label):
                self.assertIn(label, spec)

    def test_surfaces_evaluation_complexity_flag(self):
        # An eval visit bills a per-visit evaluation CPT whose complexity the clinician picks; it is
        # surfaced as a review flag, never auto-assigned (cpt._EVAL_FORMS).
        _sections, extra = cpt.suggest_codes([], FORM_ID)
        self.assertTrue(any("97161" in e for e in extra), "missing evaluation-complexity review flag")


if __name__ == "__main__":
    unittest.main()
