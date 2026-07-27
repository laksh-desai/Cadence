"""Tests for the SaaS append-only audit log (SRA risk T4).

Guarantees locked here: records are tenant-scoped (a practice only ever sees its own audit trail),
the log is append-only (no update/delete API), and per-resource history is queryable.

    .venv/Scripts/python.exe -m unittest tests.test_saas_audit -v
"""

import sqlite3
import unittest

from saas.audit import AuditLog
from saas.tenancy import Principal

A = Principal(user_id="user-a", practice_id="practice-a")
B = Principal(user_id="user-b", practice_id="practice-b")


class _FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 1.0
        return self.t


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.log = AuditLog(sqlite3.connect(":memory:"), clock=_FakeClock())

    def test_record_captures_fields(self):
        e = self.log.record(A, "patient.read", "patient", "pt-1")
        self.assertEqual((e.practice_id, e.user_id, e.action, e.resource_type, e.resource_id),
                         ("practice-a", "user-a", "patient.read", "patient", "pt-1"))

    def test_practice_scoped_reads(self):
        self.log.record(A, "patient.create", "patient", "pt-a")
        self.log.record(B, "patient.create", "patient", "pt-b")
        a_actions = [e.resource_id for e in self.log.entries_for_practice(A)]
        self.assertEqual(a_actions, ["pt-a"])  # A never sees B's audit entries

    def test_entries_ordered_newest_first(self):
        self.log.record(A, "patient.read", "patient", "pt-1")
        self.log.record(A, "patient.update", "patient", "pt-1")
        actions = [e.action for e in self.log.entries_for_practice(A)]
        self.assertEqual(actions, ["patient.update", "patient.read"])

    def test_entries_for_resource_is_scoped(self):
        self.log.record(A, "note.create", "note", "note-1")
        self.log.record(A, "note.read", "note", "note-1")
        self.log.record(A, "note.read", "note", "note-2")
        hist = self.log.entries_for_resource(A, "note", "note-1")
        self.assertEqual({e.action for e in hist}, {"note.create", "note.read"})
        self.assertTrue(all(e.resource_id == "note-1" for e in hist))

    def test_resource_history_does_not_leak_across_tenants(self):
        self.log.record(A, "note.read", "note", "shared-id")
        self.log.record(B, "note.read", "note", "shared-id")
        # Even with a colliding resource id, B's query only returns B's entry.
        self.assertEqual(len(self.log.entries_for_resource(B, "note", "shared-id")), 1)

    def test_log_is_append_only_no_mutation_api(self):
        # Structural guarantee: there is no way to update or delete an audit entry from app code.
        for forbidden in ("update", "delete", "remove", "clear"):
            self.assertFalse(hasattr(self.log, forbidden), f"audit log must not expose {forbidden}()")


if __name__ == "__main__":
    unittest.main()
