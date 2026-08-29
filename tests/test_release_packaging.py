"""What may and may not go into a release artifact.

A release zip is the one thing that leaves this machine on purpose. Everything else in Cadence is
built so PHI cannot escape by accident; packaging is where it could escape by CONSTRUCTION, because
the whole job is "copy the project folder somewhere else". A denylist that misses one entry ships a
patient database, and no other test in this suite would notice.

So the exclusions are asserted here rather than trusted to review, and the probe list is written
as the actual filenames the app creates at runtime — not as patterns, which is how you end up
matching `hf_config.example.yaml` (a safe template that SHOULD ship) while missing
`hf_config.yaml` (the token that must not).

    .venv/Scripts/python.exe -m unittest tests.test_release_packaging -v
"""

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import release  # noqa: E402

from app import __version__  # noqa: E402

#: The files Cadence actually creates that carry patient data, keys, or third-party credentials.
#: Real paths, because a fake one could pass a pattern test while the real one slips through.
MUST_NEVER_SHIP = (
    "app/storage/cadence.db.enc",
    "app/storage/.keyfile",
    "app/storage/.dblock",
    "app/integrations/.sheets_credentials.json",
    "app/integrations/sheets_config.yaml",
    "app/transcribe/hf_config.yaml",
)

#: Files that LOOK like the above to a careless pattern but are safe, shipped scaffolding. Their
#: presence is the point: a rule strict enough to drop these would ship a broken install.
MUST_SHIP = (
    "app/transcribe/hf_config.example.yaml",
    "app/integrations/sheets_config.example.yaml",
    "setup.ps1",
    "launcher.py",
    "requirements.txt",
)


class ExclusionTests(unittest.TestCase):
    def test_sensitive_paths_are_excluded(self):
        for rel in MUST_NEVER_SHIP:
            with self.subTest(path=rel):
                self.assertTrue(release.is_excluded(ROOT / rel),
                                f"{rel} would be packaged — this is how a patient database ships")

    def test_safe_scaffolding_is_not_excluded(self):
        for rel in MUST_SHIP:
            path = ROOT / rel
            if not path.exists():
                continue
            with self.subTest(path=rel):
                self.assertFalse(release.is_excluded(path), f"{rel} must ship or the install breaks")

    def test_the_collected_file_list_contains_nothing_sensitive(self):
        """The end-to-end version of the above: whatever `collect()` decides to walk, none of it
        may be a runtime secret."""
        collected = {p.relative_to(ROOT).as_posix() for p in release.collect()}
        for rel in MUST_NEVER_SHIP:
            self.assertNotIn(rel, collected)
        # No stray database or key by extension, wherever it happens to live.
        for path in collected:
            self.assertFalse(path.endswith((".enc", ".keyfile", ".pem", ".key")), path)
            self.assertNotIn("/.venv/", "/" + path)
            self.assertFalse(path.startswith("evals/"), f"eval corpora are not part of the product: {path}")

    def test_the_app_itself_is_packaged(self):
        """The inverse failure — an exclusion so broad the release contains no application."""
        collected = {p.relative_to(ROOT).as_posix() for p in release.collect()}
        for required in ("app/ui/server.py", "app/ui/static/app.js", "app/generate/prompt.py",
                         "templates/followup.md"):
            self.assertIn(required, collected)


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_the_note_table_records_the_version(self):
        """`app_version` on a saved note is the reason the stamp exists: Cadence's rules change
        what notes SAY, so "which build wrote this?" is a clinical question."""
        schema = (ROOT / "app" / "storage" / "schema.sql").read_text(encoding="utf-8")
        self.assertIn("app_version", schema)
        migrate = (ROOT / "app" / "storage" / "db.py").read_text(encoding="utf-8")
        self.assertIn('("app_version", "TEXT")', migrate,
                      "an existing database must gain the column too, not just a fresh one")


class InstallLayoutTests(unittest.TestCase):
    """The data root must be derivable from the LAYOUT, not from a setting.

    If it depended on an environment variable a setup script had to remember, then a hand-made
    shortcut, a `python launcher.py` from a terminal, or a script run directly would each get a
    different empty database — and it would present as "all my patients disappeared", not as a
    missing variable.
    """

    def setUp(self):
        from app import paths
        self.paths = paths
        self._orig_install = paths.INSTALL_DIR
        self._orig_env = os.environ.pop("CADENCE_DATA_DIR", None)

    def tearDown(self):
        self.paths.INSTALL_DIR = self._orig_install
        if self._orig_env is not None:
            os.environ["CADENCE_DATA_DIR"] = self._orig_env
        else:
            os.environ.pop("CADENCE_DATA_DIR", None)

    def test_a_checkout_has_no_separate_data_root(self):
        """Unset and not installed, every path stays exactly where it always was — which is why
        the rest of this suite is unaffected by the split."""
        self.paths.INSTALL_DIR = Path("C:/dev/Cadence")
        self.assertIsNone(self.paths.data_dir())

    def test_an_installed_layout_derives_its_own_data_root(self):
        self.paths.INSTALL_DIR = Path("C:/Cadence/versions/1.2.3")
        self.assertEqual(self.paths.data_dir(), Path("C:/Cadence/data").resolve())

    def test_an_explicit_setting_still_wins(self):
        self.paths.INSTALL_DIR = Path("C:/Cadence/versions/1.2.3")
        os.environ["CADENCE_DATA_DIR"] = str(Path("D:/Elsewhere"))
        self.assertEqual(self.paths.data_dir(), Path("D:/Elsewhere").resolve())

    def test_the_schema_travels_with_the_code_not_the_data(self):
        """A version's migrations are part of that version. If schema.sql resolved against the
        data root, a new build would run the OLD schema."""
        from app.storage import db
        self.assertIn("app", db.SCHEMA_PATH.parts)
        self.assertEqual(db.SCHEMA_PATH.name, "schema.sql")


if __name__ == "__main__":
    unittest.main()
