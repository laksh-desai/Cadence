"""Multi-tenant data isolation — the SaaS fork's highest-severity safeguard (SRA risk T2).

The local app has NO tenant model: all patients are one global pool (`repository.list_patients()`
is an unfiltered SELECT). In the SaaS every practice is a tenant and no request may ever read or
write another practice's PHI. This module makes that invariant structural: every store method takes
the authenticated `Principal` and filters by `principal.practice_id`, so there is simply no code
path that returns or mutates cross-tenant data.

Backed by SQLite here so the isolation invariant is testable *now*, before Postgres is provisioned.
The production target swaps the driver for Aptible-managed PostgreSQL and adds Row-Level Security as
a defense-in-depth backstop — but the `WHERE practice_id = ?` scoping below is identical and fully
portable. Nothing here touches the live local app (`app/`).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          TEXT PRIMARY KEY,
    practice_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    dob         TEXT,
    mrn         TEXT,
    condition   TEXT
);
CREATE INDEX IF NOT EXISTS idx_patients_practice ON patients(practice_id);
"""

_EDITABLE = ("name", "dob", "mrn", "condition")


@dataclass(frozen=True)
class Principal:
    """The authenticated actor for a request: a user belonging to exactly one practice (tenant).
    Produced by the auth boundary (saas/auth.py) and threaded into every data-access call."""

    user_id: str
    practice_id: str
    role: str = "clinician"


class TenantScopedPatientStore:
    """A patients store where every operation is scoped to the caller's practice. There is no
    unscoped read/write/delete method by design, so cross-tenant access is structurally impossible
    rather than merely discouraged."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def create_patient(self, principal: Principal, *, name: str, dob=None, mrn=None, condition=None) -> dict:
        pid = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO patients (id, practice_id, name, dob, mrn, condition) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, principal.practice_id, name, dob, mrn, condition),
        )
        self._conn.commit()
        created = self.get_patient(principal, pid)
        assert created is not None  # just inserted under this principal's practice
        return created

    def get_patient(self, principal: Principal, patient_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM patients WHERE id = ? AND practice_id = ?",
            (patient_id, principal.practice_id),
        ).fetchone()
        return dict(row) if row else None

    def list_patients(self, principal: Principal) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM patients WHERE practice_id = ? ORDER BY name",
            (principal.practice_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_patient(self, principal: Principal, patient_id: str, **fields) -> dict | None:
        sets = {k: v for k, v in fields.items() if k in _EDITABLE}
        if not sets:
            return self.get_patient(principal, patient_id)
        assignments = ", ".join(f"{k} = ?" for k in sets)  # keys are a fixed whitelist, not user input
        params = [*sets.values(), patient_id, principal.practice_id]
        cur = self._conn.execute(
            f"UPDATE patients SET {assignments} WHERE id = ? AND practice_id = ?", params
        )
        self._conn.commit()
        return self.get_patient(principal, patient_id) if cur.rowcount else None

    def delete_patient(self, principal: Principal, patient_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM patients WHERE id = ? AND practice_id = ?",
            (patient_id, principal.practice_id),
        )
        self._conn.commit()
        return cur.rowcount > 0
