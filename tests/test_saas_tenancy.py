"""Tests for the SaaS tenant-isolation invariant (SRA risks T1/T2).

The load-bearing guarantee: a Principal from practice A can never read, list, update, or delete a
patient owned by practice B. These run against in-memory SQLite; the same scoping carries to the
Postgres target (plus RLS as a backstop).

    .venv/Scripts/python.exe -m unittest tests.test_saas_tenancy -v
"""

import sqlite3
import unittest

from saas.auth import (
    CLINICIAN,
    PRACTICE_ADMIN,
    AuthError,
    PermissionDenied,
    StubAuthenticator,
    require_authenticated,
    require_role,
)
from saas.tenancy import Principal, TenantScopedPatientStore

A = Principal(user_id="user-a", practice_id="practice-a", role=CLINICIAN)
B = Principal(user_id="user-b", practice_id="practice-b", role=CLINICIAN)


def _store():
    return TenantScopedPatientStore(sqlite3.connect(":memory:"))


class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.s = _store()
        self.a_pt = self.s.create_patient(A, name="Alice Aardvark", mrn="A1")
        self.b_pt = self.s.create_patient(B, name="Bob Booth", mrn="B1")

    def test_get_is_tenant_scoped(self):
        self.assertIsNone(self.s.get_patient(A, self.b_pt["id"]))  # A cannot read B's patient
        self.assertIsNotNone(self.s.get_patient(B, self.b_pt["id"]))  # B can

    def test_list_returns_only_own_tenant(self):
        self.assertEqual([p["name"] for p in self.s.list_patients(A)], ["Alice Aardvark"])
        self.assertEqual([p["name"] for p in self.s.list_patients(B)], ["Bob Booth"])

    def test_delete_cannot_cross_tenant(self):
        self.assertFalse(self.s.delete_patient(A, self.b_pt["id"]))
        self.assertIsNotNone(self.s.get_patient(B, self.b_pt["id"]))  # B's patient survives

    def test_delete_within_tenant_works(self):
        self.assertTrue(self.s.delete_patient(A, self.a_pt["id"]))
        self.assertIsNone(self.s.get_patient(A, self.a_pt["id"]))

    def test_update_cannot_cross_tenant(self):
        self.assertIsNone(self.s.update_patient(A, self.b_pt["id"], name="hijacked"))
        self.assertEqual(self.s.get_patient(B, self.b_pt["id"])["name"], "Bob Booth")

    def test_update_within_tenant_works(self):
        updated = self.s.update_patient(A, self.a_pt["id"], condition="ACL rehab")
        self.assertEqual(updated["condition"], "ACL rehab")

    def test_created_patient_carries_its_practice(self):
        self.assertEqual(self.s.get_patient(A, self.a_pt["id"])["practice_id"], "practice-a")


class AuthBoundaryTests(unittest.TestCase):
    def test_valid_token_resolves_principal(self):
        auth = StubAuthenticator({"tok-a": A})
        self.assertEqual(require_authenticated(auth, "tok-a"), A)

    def test_missing_token_raises(self):
        with self.assertRaises(AuthError):
            require_authenticated(StubAuthenticator(), None)

    def test_unknown_token_raises(self):
        with self.assertRaises(AuthError):
            require_authenticated(StubAuthenticator({"tok-a": A}), "bogus")

    def test_require_role_allows_permitted(self):
        require_role(Principal("u", "p", PRACTICE_ADMIN), PRACTICE_ADMIN)  # must not raise

    def test_require_role_denies_others(self):
        with self.assertRaises(PermissionDenied):
            require_role(A, PRACTICE_ADMIN)

    def test_stub_authenticator_satisfies_protocol(self):
        from saas.auth import Authenticator

        self.assertIsInstance(StubAuthenticator(), Authenticator)


if __name__ == "__main__":
    unittest.main()
