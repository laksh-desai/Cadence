"""Append-only audit log — SRA risk T4 (HIPAA audit controls, §164.312(b)).

The local app has no record of who accessed or changed which patient/note. A hosted service handling
many practices' PHI must keep an audit trail that is (a) tenant-scoped like everything else, (b)
append-only (entries are never updated or deleted from application code), and (c) queryable for
review/incident-response.

SQLite-backed so it's testable now; the Postgres target keeps the identical shape (append-only is
additionally enforceable there via a REVOKE UPDATE/DELETE grant + RLS). Records reference PHI
*subjects* (patient ids) but hold no clinical values themselves, so the log is lower-sensitivity than
the data plane while still being protected.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass

from saas.tenancy import Principal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    ts           REAL NOT NULL,
    practice_id  TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    action       TEXT NOT NULL,          -- e.g. "patient.read", "note.create", "patient.delete"
    resource_type TEXT NOT NULL,         -- e.g. "patient", "note"
    resource_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_practice_ts ON audit_log(practice_id, ts);
"""


@dataclass(frozen=True)
class AuditEntry:
    id: str
    ts: float
    practice_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str | None


class AuditLog:
    """Append-only, tenant-scoped audit trail. `record()` only ever inserts; there is no update or
    delete method by design. Reads are scoped to the caller's practice, same as the data plane."""

    def __init__(self, conn: sqlite3.Connection, *, clock=time.time):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._clock = clock

    def record(self, principal: Principal, action: str, resource_type: str, resource_id: str | None = None) -> AuditEntry:
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            ts=self._clock(),
            practice_id=principal.practice_id,
            user_id=principal.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        self._conn.execute(
            "INSERT INTO audit_log (id, ts, practice_id, user_id, action, resource_type, resource_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry.id, entry.ts, entry.practice_id, entry.user_id, entry.action, entry.resource_type, entry.resource_id),
        )
        self._conn.commit()
        return entry

    def entries_for_practice(self, principal: Principal, *, limit: int = 100) -> list[AuditEntry]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE practice_id = ? ORDER BY ts DESC LIMIT ?",
            (principal.practice_id, limit),
        ).fetchall()
        return [AuditEntry(**dict(r)) for r in rows]

    def entries_for_resource(self, principal: Principal, resource_type: str, resource_id: str) -> list[AuditEntry]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE practice_id = ? AND resource_type = ? AND resource_id = ? ORDER BY ts DESC",
            (principal.practice_id, resource_type, resource_id),
        ).fetchall()
        return [AuditEntry(**dict(r)) for r in rows]
