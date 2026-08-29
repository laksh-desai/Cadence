"""Tests for scripts/backup.py — the encrypted-store backup/restore helper.

The store is a matched pair (Fernet keyfile + encrypted DB); one is useless without the
other, and a mismatched pair is unrecoverable. These lock in that the tool: backs both up
together, verifies the copy actually decrypts, restores it, refuses a mismatched pair, and
refuses to clobber existing data without --force (saving the current files aside first).
No real app storage is touched — everything runs in temp dirs.

    .venv/Scripts/python.exe -m unittest tests.test_backup -v
"""

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet

from scripts import backup


def _make_store(with_db=True):
    """A temp storage dir with a real Fernet key and (optionally) an encrypted DB blob."""
    sd = Path(mkdtemp(prefix="cad_store_"))
    key = Fernet.generate_key()
    (sd / backup.KEYFILE_NAME).write_bytes(key)
    if with_db:
        blob = Fernet(key).encrypt(b"SQLite format 3\x00 ... fake db bytes ...")
        (sd / backup.ENC_NAME).write_bytes(blob)
    return sd


class BackupRestoreTests(unittest.TestCase):
    def test_backup_verifies_and_restores_roundtrip(self):
        src = _make_store()
        dest = Path(mkdtemp(prefix="cad_dest_"))
        out = backup.do_backup(dest, storage_dir=src)
        self.assertTrue((out / backup.KEYFILE_NAME).exists())
        self.assertTrue((out / backup.ENC_NAME).exists())
        self.assertTrue((out / "manifest.json").exists())

        # Restore into a fresh, empty storage dir and confirm bytes match the source.
        target = Path(mkdtemp(prefix="cad_target_"))  # empty -> no --force needed
        backup.do_restore(out, storage_dir=target, force=False)
        self.assertEqual((target / backup.KEYFILE_NAME).read_bytes(), (src / backup.KEYFILE_NAME).read_bytes())
        self.assertEqual((target / backup.ENC_NAME).read_bytes(), (src / backup.ENC_NAME).read_bytes())
        ok, _ = backup.verify_pair(target / backup.KEYFILE_NAME, target / backup.ENC_NAME)
        self.assertTrue(ok)

    def test_verify_pair_detects_mismatch(self):
        sd = _make_store()
        # Overwrite the keyfile with a DIFFERENT key -> pair no longer decrypts.
        (sd / backup.KEYFILE_NAME).write_bytes(Fernet.generate_key())
        ok, msg = backup.verify_pair(sd / backup.KEYFILE_NAME, sd / backup.ENC_NAME)
        self.assertFalse(ok)
        self.assertIn("mismatch", msg.lower())

    def test_backup_refuses_mismatched_source(self):
        sd = _make_store()
        (sd / backup.KEYFILE_NAME).write_bytes(Fernet.generate_key())
        with self.assertRaises(SystemExit):
            backup.do_backup(Path(mkdtemp(prefix="cad_dest_")), storage_dir=sd)

    def test_restore_refuses_overwrite_without_force(self):
        src = _make_store()
        out = backup.do_backup(Path(mkdtemp(prefix="cad_dest_")), storage_dir=src)
        occupied = _make_store()  # already has data
        with self.assertRaises(SystemExit):
            backup.do_restore(out, storage_dir=occupied, force=False)

    def test_dry_run_writes_nothing_and_needs_no_force(self):
        """A backup nobody has ever restored is not a backup. Rehearsing must be possible WITHOUT
        the live patient database being overwritten to find out — which was the only option before
        --dry-run, so the safe advice was "never test your backups"."""
        src = _make_store()
        out = backup.do_backup(Path(mkdtemp(prefix="cad_dest_")), storage_dir=src)
        occupied = _make_store()
        before = ((occupied / backup.KEYFILE_NAME).read_bytes(),
                  (occupied / backup.ENC_NAME).read_bytes())

        backup.do_restore(out, storage_dir=occupied, force=False, dry_run=True)  # no SystemExit

        self.assertEqual(((occupied / backup.KEYFILE_NAME).read_bytes(),
                          (occupied / backup.ENC_NAME).read_bytes()), before)
        self.assertEqual(list(occupied.glob("*.pre-restore-*")), [],
                         "a rehearsal must not leave safety copies behind either")

    def test_dry_run_still_refuses_a_broken_backup(self):
        """The rehearsal's whole value is catching a bad pair before the real restore does."""
        src = _make_store()
        out = backup.do_backup(Path(mkdtemp(prefix="cad_dest_")), storage_dir=src)
        (out / backup.KEYFILE_NAME).write_bytes(Fernet.generate_key())  # mismatched keyfile
        with self.assertRaises(SystemExit):
            backup.do_restore(out, storage_dir=_make_store(), dry_run=True)

    def test_restore_force_saves_current_files_aside(self):
        src = _make_store()
        out = backup.do_backup(Path(mkdtemp(prefix="cad_dest_")), storage_dir=src)
        occupied = _make_store()
        before = (occupied / backup.ENC_NAME).read_bytes()
        backup.do_restore(out, storage_dir=occupied, force=True)
        # a *.pre-restore copy of the old DB must exist, holding the old bytes
        aside = list(occupied.glob(backup.ENC_NAME + ".pre-restore-*"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_bytes(), before)
        # and the live DB is now the restored one
        self.assertEqual((occupied / backup.ENC_NAME).read_bytes(), (src / backup.ENC_NAME).read_bytes())

    def test_keyfile_only_store_is_valid(self):
        src = _make_store(with_db=False)
        out = backup.do_backup(Path(mkdtemp(prefix="cad_dest_")), storage_dir=src)
        self.assertTrue((out / backup.KEYFILE_NAME).exists())
        self.assertFalse((out / backup.ENC_NAME).exists())


if __name__ == "__main__":
    unittest.main()
