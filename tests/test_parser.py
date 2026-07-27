"""Tests for the model-output parser (app/generate/parser.py).

parse_plain is the contract boundary between the raw model text and everything
downstream (postprocess, storage, the UI). Getting the ## heading / [[CARRIED
FORWARD]] / ---MISSING--- splitting right is what lets the deterministic safeguards
and the amber-gap rendering work at all. Pure function -- no DB, no model.

    .venv/Scripts/python.exe -m unittest tests.test_parser -v
"""

import unittest

from app.generate.parser import parse_plain


class ParsePlainTests(unittest.TestCase):
    def test_no_heading_returns_none(self):
        # Callers fall back to rendering the raw text when the model ignores the
        # `## heading` contract -- signalled by None.
        self.assertIsNone(parse_plain("Just some prose with no headings."))

    def test_empty_input_returns_none(self):
        self.assertIsNone(parse_plain(""))

    def test_basic_single_section(self):
        result = parse_plain("## Assessment\nPatient tolerated session well.")
        self.assertEqual(len(result["sections"]), 1)
        s = result["sections"][0]
        self.assertEqual(s["heading"], "Assessment")
        self.assertEqual(s["body"], "Patient tolerated session well.")
        self.assertFalse(s["carried_forward"])
        self.assertEqual(result["missing_info"], [])

    def test_carried_forward_tag_detected_and_stripped(self):
        result = parse_plain("## Functional Status [[CARRIED FORWARD]]\nAmbulates 200ft.")
        s = result["sections"][0]
        self.assertEqual(s["heading"], "Functional Status")
        self.assertTrue(s["carried_forward"])

    def test_multiple_sections_and_multiline_body(self):
        text = "## Subjective\nReports less pain.\nSleeping better.\n\n## Objective\nROM improved."
        result = parse_plain(text)
        self.assertEqual([s["heading"] for s in result["sections"]], ["Subjective", "Objective"])
        self.assertEqual(result["sections"][0]["body"], "Reports less pain.\nSleeping better.")

    def test_missing_list_parsed(self):
        text = "## Vitals\nBP taken.\n---MISSING---\n- Heart rate\n- Pain rating"
        result = parse_plain(text)
        self.assertEqual(result["missing_info"], ["Heart rate", "Pain rating"])
        # The MISSING block must not be parsed as a section.
        self.assertEqual([s["heading"] for s in result["sections"]], ["Vitals"])

    def test_missing_none_yields_empty_list(self):
        result = parse_plain("## Plan\nContinue POC.\n---MISSING---\n- none")
        self.assertEqual(result["missing_info"], [])

    def test_headings_after_missing_marker_are_ignored(self):
        # Anything after ---MISSING--- is the missing list, never more sections.
        text = "## Plan\nContinue.\n---MISSING---\n- BP\n## Not A Real Section\nignore me"
        result = parse_plain(text)
        self.assertEqual([s["heading"] for s in result["sections"]], ["Plan"])

    def test_empty_trailing_heading_is_skipped(self):
        # A bare "## " marker with no title (here, trailing) captures an empty
        # heading and is dropped -- only the real section survives.
        result = parse_plain("## Assessment\nTolerating well.\n## ")
        self.assertEqual([s["heading"] for s in result["sections"]], ["Assessment"])

    def test_heading_whitespace_trimmed(self):
        result = parse_plain("##   Precautions  \nWeight-bearing as tolerated.")
        self.assertEqual(result["sections"][0]["heading"], "Precautions")

    def test_single_hash_heading_salvaged(self):
        # A 4B model sometimes emits "# Heading" — must not discard the note to raw fallback.
        result = parse_plain("# Assessment\nTolerating well.")
        self.assertEqual(result["sections"][0]["heading"], "Assessment")

    def test_triple_hash_heading_salvaged(self):
        result = parse_plain("### Plan\nContinue POC.")
        self.assertEqual(result["sections"][0]["heading"], "Plan")

    def test_mixed_heading_levels(self):
        result = parse_plain("# Subjective\nLess pain.\n### Objective\nROM improved.")
        self.assertEqual([s["heading"] for s in result["sections"]], ["Subjective", "Objective"])

    def test_hashless_prose_still_none(self):
        self.assertIsNone(parse_plain("Subjective: less pain. Objective: ROM improved."))


if __name__ == "__main__":
    unittest.main()
