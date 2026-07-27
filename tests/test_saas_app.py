"""End-to-end tests of the SaaS HTTP skeleton (saas/app.py) via FastAPI's in-process TestClient.

Proves the whole authz stack over real HTTP with no infrastructure: unauthenticated -> 401,
cross-tenant id -> 404, role-gated action -> 403, and audit entries recorded on access.

    .venv/Scripts/python.exe -m unittest tests.test_saas_app -v
"""

import sqlite3
import unittest

from fastapi.testclient import TestClient

from saas.app import create_app
from saas.audit import AuditLog
from saas.auth import StubAuthenticator
from saas.tenancy import Principal, TenantScopedPatientStore

A_CLIN = Principal("ua", "practice-a", "clinician")
A_ADMIN = Principal("uaa", "practice-a", "practice_admin")
B_ADMIN = Principal("ub", "practice-b", "practice_admin")

TOKENS = {"a-clin": A_CLIN, "a-admin": A_ADMIN, "b-admin": B_ADMIN}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class SaasAppTests(unittest.TestCase):
    def setUp(self):
        # check_same_thread=False: TestClient runs sync endpoints in a worker thread, so the one
        # shared skeleton connection is touched from a different thread than it was created in.
        # (Production uses a per-request Postgres connection/pool, where this doesn't arise.)
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.store = TenantScopedPatientStore(conn)
        self.audit = AuditLog(conn)
        app = create_app(authenticator=StubAuthenticator(TOKENS), store=self.store, audit=self.audit)
        self.client = TestClient(app)

    def _create(self, token, name):
        r = self.client.post("/patients", json={"name": name}, headers=_auth(token))
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    # --- authentication (T1) ---
    def test_no_token_is_401(self):
        self.assertEqual(self.client.get("/patients").status_code, 401)

    def test_bad_token_is_401(self):
        self.assertEqual(self.client.get("/patients", headers=_auth("nope")).status_code, 401)

    # --- tenant isolation over HTTP (T2) ---
    def test_cross_tenant_get_is_404(self):
        b_id = self._create("b-admin", "Bob")
        r = self.client.get(f"/patients/{b_id}", headers=_auth("a-clin"))
        self.assertEqual(r.status_code, 404)

    def test_list_is_tenant_scoped(self):
        self._create("a-clin", "Alice")
        self._create("b-admin", "Bob")
        names = [p["name"] for p in self.client.get("/patients", headers=_auth("a-clin")).json()]
        self.assertEqual(names, ["Alice"])

    def test_own_tenant_get_ok(self):
        a_id = self._create("a-clin", "Alice")
        r = self.client.get(f"/patients/{a_id}", headers=_auth("a-clin"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "Alice")

    # --- role gating (T1 authz) ---
    def test_clinician_cannot_delete(self):
        a_id = self._create("a-clin", "Alice")
        self.assertEqual(self.client.delete(f"/patients/{a_id}", headers=_auth("a-clin")).status_code, 403)

    def test_admin_can_delete_own(self):
        a_id = self._create("a-clin", "Alice")
        self.assertEqual(self.client.delete(f"/patients/{a_id}", headers=_auth("a-admin")).status_code, 204)

    def test_admin_cannot_delete_across_tenant(self):
        b_id = self._create("b-admin", "Bob")
        self.assertEqual(self.client.delete(f"/patients/{b_id}", headers=_auth("a-admin")).status_code, 404)
        # Bob still exists for practice B
        self.assertEqual(self.client.get(f"/patients/{b_id}", headers=_auth("b-admin")).status_code, 200)

    # --- audit trail (T4) ---
    def test_access_is_audited(self):
        a_id = self._create("a-clin", "Alice")
        self.client.get(f"/patients/{a_id}", headers=_auth("a-clin"))
        actions = {e.action for e in self.audit.entries_for_practice(A_CLIN)}
        self.assertIn("patient.create", actions)
        self.assertIn("patient.read", actions)


if __name__ == "__main__":
    unittest.main()
