"""Tests for carry-forward field extraction (app/generate/... carry_forward
extract_snapshot_fields).

This is the heading-match logic that turns a saved note's own sections into the
per-patient carry-forward snapshot -- no second LLM call, just fixed per-form
heading matching. The deliberate "leave a field None when the form has no matching
heading" behavior (discharge/soappt precautions, etc.) is asserted here so a future
edit to CARRY_FIELD_HEADING_MAP can't silently start conflating sections. Pure
function -- no DB.

    .venv/Scripts/python.exe -m unittest tests.test_carry_extract -v
"""

import unittest

from app.storage.carry_forward import extract_snapshot_fields


def _sec(heading, body):
    return {"heading": heading, "body": body}


class ExtractSnapshotFieldsTests(unittest.TestCase):
    def test_followup_extracts_all_four_fields(self):
        sections = [
            _sec("Precautions", "Weight-bearing as tolerated."),
            _sec("Functional Status", "Ambulates 150ft with walker."),
            _sec("Short-Term Goals", "Independent 200ft."),
            _sec("Long-Term Goals", "Community ambulation."),
        ]
        fields = extract_snapshot_fields("followup", sections)
        self.assertEqual(fields["precautions"], "Weight-bearing as tolerated.")
        self.assertEqual(fields["functional_status"], "Ambulates 150ft with walker.")
        self.assertEqual(fields["short_term_goals"], "Independent 200ft.")
        self.assertEqual(fields["long_term_goals"], "Community ambulation.")

    def test_heading_match_is_case_insensitive(self):
        fields = extract_snapshot_fields("followup", [_sec("FUNCTIONAL STATUS", "x")])
        self.assertEqual(fields["functional_status"], "x")

    def test_unmapped_form_returns_empty(self):
        # A form that never carries forward (e.g. the Initial Evaluation) has no field map at all.
        self.assertEqual(extract_snapshot_fields("initial", [_sec("Assessment", "x")]), {})

    def test_first_matching_section_wins(self):
        sections = [
            _sec("Short-Term Goals", "first"),
            _sec("Short-Term Goals", "second"),
        ]
        fields = extract_snapshot_fields("followup", sections)
        self.assertEqual(fields["short_term_goals"], "first")

    def test_missing_headings_leave_fields_none(self):
        fields = extract_snapshot_fields("followup", [_sec("Objective", "unrelated")])
        self.assertIsNone(fields["precautions"])
        self.assertIsNone(fields["functional_status"])
        self.assertIsNone(fields["short_term_goals"])
        self.assertIsNone(fields["long_term_goals"])

    def test_inline_needs_marker_stripped_from_carried_body(self):
        # A verification/gap flag must not be baked into the carried-forward context (it would be
        # rendered into the next visit's prior-note block and could be echoed).
        fields = extract_snapshot_fields(
            "followup",
            [_sec("Functional Status", 'Ambulates 200 ft with a walker. [[NEEDS: assist level — verify]]')],
        )
        self.assertEqual(fields["functional_status"], "Ambulates 200 ft with a walker.")

    def test_inline_cpt_marker_stripped_from_carried_body(self):
        fields = extract_snapshot_fields(
            "followup",
            [_sec("Functional Status", "Ambulates 200 ft. [[CPT: 97116 Gait Training — confirm]]")],
        )
        self.assertEqual(fields["functional_status"], "Ambulates 200 ft.")

    def test_section_that_is_only_a_marker_becomes_none(self):
        # The model sometimes punts a carried section with just a gap marker -> carry nothing,
        # so render_prior_block omits the line rather than carrying "[[NEEDS: ...]]" forward.
        fields = extract_snapshot_fields(
            "followup",
            [_sec("Functional Status", "[[NEEDS: ambulation distance, assistive device]]")],
        )
        self.assertIsNone(fields["functional_status"])

    def test_block_format_single_section_body_is_scanned(self):
        # Real block-format Follow-Up generations routinely parse as ONE "## FOLLOW-UP VISIT"
        # section whose body holds "Label: value" lines (not a section per field). Carry fields
        # must still be recovered from those body lines — this reproduces a captured real note.
        body = (
            "Summary of Daily Skilled Services:\n"
            "Patient tolerated twenty minutes of exercise. Short term goal to walk 100 ft is met.\n"
            "Precautions: Weight-bearing as tolerated. Contact guard assist.\n"
            "═══ BLOCK 3 — ASSESSMENT ═══\n"
            "Functional Status: Ambulation distance 200 ft with a cane. Stairs eight steps with rail.\n"
            "Short-Term Goals: Walk 100 ft (MET)\n"
            "Long-Term Goals: Independent community walking (IN PROGRESS)\n"
        )
        fields = extract_snapshot_fields("followup", [_sec("FOLLOW-UP VISIT", body)])
        self.assertEqual(fields["precautions"], "Weight-bearing as tolerated. Contact guard assist.")
        self.assertTrue(fields["functional_status"].startswith("Ambulation distance 200 ft"))
        self.assertEqual(fields["short_term_goals"], "Walk 100 ft (MET)")
        self.assertEqual(fields["long_term_goals"], "Independent community walking (IN PROGRESS)")

    def test_block_scan_ignores_prose_mention_not_a_field_line(self):
        # A prose "Short term goal to walk..." is NOT a "Short-Term Goals:" field line -> no capture.
        body = "Summary: Short term goal to walk one hundred feet is met.\n"
        fields = extract_snapshot_fields("followup", [_sec("FOLLOW-UP VISIT", body)])
        self.assertIsNone(fields["short_term_goals"])

    def test_block_scan_strips_echoed_carry_forward_marker(self):
        # If the model echoes the template's "[carry forward]" instruction into the value, drop it.
        fields = extract_snapshot_fields(
            "followup",
            [_sec("FOLLOW-UP VISIT", "Functional Status: [carry forward] Ambulates 150 ft with walker.")],
        )
        self.assertEqual(fields["functional_status"], "Ambulates 150 ft with walker.")


if __name__ == "__main__":
    unittest.main()
