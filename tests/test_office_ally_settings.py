"""Manage Office → Office Ally layout settings.

The layout a note type goes into is enforced by the extension as a HARD block
(docs/OfficeAlly_Integration_Rules.md, rule 2.1), so a malformed id or a silently-lost settings
file would either block every fill or, worse, let a note into the wrong layout. These tests pin
the validation and the fallback.

    .venv/Scripts/python.exe -m unittest tests.test_office_ally_settings -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from app.integrations import office_ally  # noqa: E402

KNOWN = {"initial", "initial_updated", "followup"}


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "office_ally.json"
        self.patch = mock.patch.object(office_ally, "settings_path", return_value=self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_no_layouts_are_built_in_every_practice_enters_its_own(self):
        # SoapLayoutIDs belong to one Office Ally account; a built-in default would send another
        # practice's notes to the wrong layout.
        self.assertEqual(office_ally.load_layouts(), {})
        self.assertEqual(office_ally.DEFAULT_LAYOUTS, {})

    def test_saved_layouts_round_trip(self):
        clean = office_ally.validate_layouts(
            {"initial": {"id": " 374261 ", "name": "Cadence  Init Eval"}, "followup": {"id": "999", "name": "Daily"}}, KNOWN)
        office_ally.save_layouts(clean)
        self.assertEqual(office_ally.load_layouts(),
                         {"initial": {"id": "374261", "name": "Cadence Init Eval"}, "followup": {"id": "999", "name": "Daily"}})

    def test_an_empty_id_removes_that_note_types_rule(self):
        clean = office_ally.validate_layouts({"followup": {"id": "", "name": "Progress Notes"}}, KNOWN)
        self.assertEqual(clean, {})

    def test_bad_input_is_refused_with_a_reason(self):
        for bad, why in [
            ({"initial": {"id": "37-4261", "name": "X"}}, "digits"),
            ({"initial": {"id": "374261", "name": ""}}, "name"),
            ({"not_a_form": {"id": "1", "name": "X"}}, "unknown"),
            ("nope", "object"),
        ]:
            with self.subTest(why=why):
                with self.assertRaises(office_ally.SettingsError):
                    office_ally.validate_layouts(bad, KNOWN)

    def test_an_unreadable_file_means_no_layouts_rather_than_a_crash(self):
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(office_ally.load_layouts(), {})


class PackagingTests(unittest.TestCase):
    def test_the_practices_settings_file_is_not_shipped(self):
        import release
        self.assertTrue(release.is_excluded(ROOT / "app" / "integrations" / "office_ally.json"))


if __name__ == "__main__":
    unittest.main()
