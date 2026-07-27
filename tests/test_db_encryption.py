"""Encryption-lifecycle tests for app/storage/db.py.

This is the security-critical core of the local store: patient data must survive a
decrypt -> write -> re-encrypt -> shutdown -> re-decrypt round trip, the on-disk file must
actually be ciphertext (PHI never readable at rest), and a wrong/lost keyfile must fail loudly
rather than silently. Runs entirely against a temp dir (module paths are redirected in setUp) so
the real cadence.db.enc / .keyfile are never touched.

    .venv/Scripts/python.exe -m unittest tests.test_db_encryption -v
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from app.storage import db


class EncryptionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        self._orig = (db.KEYFILE, db.ENC_PATH, db._runtime_dir, db._runtime_db_path)
        db.KEYFILE = self.tmp / ".keyfile"
        db.ENC_PATH = self.tmp / "cadence.db.enc"
        db._runtime_dir = None
        db._runtime_db_path = None

    def tearDown(self):
        try:
            db.shutdown()
        except Exception:
            pass
        db.KEYFILE, db.ENC_PATH, db._runtime_dir, db._runtime_db_path = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _insert_patient(self, name):
        conn = db.get_connection()
        try:
            conn.execute(
                "INSERT INTO patients (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("p1", name, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()

    def _names(self):
        conn = db.get_connection()
        try:
            return [r["name"] for r in conn.execute("SELECT name FROM patients")]
        finally:
            conn.close()

    def test_data_round_trips_through_encryption(self):
        db.init()
        self._insert_patient("Alice Aardvark")
        db.persist()
        db.shutdown()                          # removes the plaintext working copy
        self.assertTrue(db.ENC_PATH.exists())  # ciphertext remains on disk
        db.init()                              # new "session" decrypts it
        self.assertEqual(self._names(), ["Alice Aardvark"])

    def test_file_on_disk_is_ciphertext_not_plaintext(self):
        db.init()
        self._insert_patient("Zebediah Confidential")
        db.persist()
        blob = db.ENC_PATH.read_bytes()
        self.assertNotIn(b"Zebediah Confidential", blob)  # PHI must not be readable at rest

    def test_keyfile_is_created_and_stable(self):
        db.init()
        self._insert_patient("Kay")
        db.persist()                           # the first encrypt lazily creates the keyfile
        key1 = db.KEYFILE.read_bytes()
        self.assertTrue(key1)
        db.shutdown()
        db.init()                              # must reuse the same key, not regenerate
        self.assertEqual(db.KEYFILE.read_bytes(), key1)

    def test_wrong_key_fails_loudly(self):
        db.init()
        self._insert_patient("Bob")
        db.persist()
        db.shutdown()
        db.KEYFILE.write_bytes(Fernet.generate_key())  # simulate a lost/replaced keyfile
        with self.assertRaises(RuntimeError):
            db.init()


if __name__ == "__main__":
    unittest.main()
