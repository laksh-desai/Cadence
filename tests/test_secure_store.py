"""Windows DPAPI wrapper (app/secure_store.py)."""

import os
import sys
import unittest

from app import secure_store


@unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
class DpapiTests(unittest.TestCase):
    def test_roundtrip_many_times(self):
        # Hundreds of rounds: the first version freed its buffer early and failed intermittently.
        for _ in range(300):
            key = os.urandom(44)
            sealed = secure_store.protect(key)
            self.assertTrue(secure_store.is_protected(sealed))
            self.assertNotIn(key, sealed)
            self.assertEqual(secure_store.unprotect(sealed), key)

    def test_unprotected_legacy_value_still_reads(self):
        self.assertEqual(secure_store.unprotect(b"plain-old-key"), b"plain-old-key")


if __name__ == "__main__":
    unittest.main()
