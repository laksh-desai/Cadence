"""Unit tests for app.integrations.sheets_sync.reconcile_one -- pure logic, no
credentials, no network, no database. Run with:
    .venv/Scripts/python.exe -m unittest tests.test_sheets_sync -v
"""

import unittest

from app.integrations.sheets_sync import reconcile_one

T0 = "2026-06-29T10:00:00+00:00"
T1 = "2026-06-29T11:00:00+00:00"  # later than T0
T2 = "2026-06-29T12:00:00+00:00"  # later than T1


def local(updated_at, sheet_synced_at):
    return {"updated_at": updated_at, "sheet_synced_at": sheet_synced_at}


def sheet(last_edited):
    return {"last_edited": last_edited}


class ReconcileOneTests(unittest.TestCase):
    def test_sheet_changed_only_pulls(self):
        # synced at T0, local untouched since, sheet edited at T1.
        action = reconcile_one(local(T0, T0), sheet(T1))
        self.assertEqual(action.kind, "pull")
        self.assertEqual(action.timestamp, T1)
        self.assertFalse(action.is_conflict)

    def test_local_changed_only_pushes(self):
        # synced at T0, local edited at T1, sheet untouched since (blank).
        action = reconcile_one(local(T1, T0), sheet(None))
        self.assertEqual(action.kind, "push")
        self.assertEqual(action.timestamp, T1)
        self.assertFalse(action.is_conflict)

    def test_neither_changed_is_noop(self):
        action = reconcile_one(local(T0, T0), sheet(T0))
        self.assertEqual(action.kind, "noop")

    def test_both_changed_sheet_later_pulls_and_flags_conflict(self):
        # synced at T0, local edited at T1, sheet edited at T2 (later) -- sheet wins.
        action = reconcile_one(local(T1, T0), sheet(T2))
        self.assertEqual(action.kind, "pull")
        self.assertEqual(action.timestamp, T2)
        self.assertTrue(action.is_conflict)

    def test_both_changed_local_later_pushes_and_flags_conflict(self):
        # synced at T0, sheet edited at T1, local edited at T2 (later) -- local wins.
        action = reconcile_one(local(T2, T0), sheet(T1))
        self.assertEqual(action.kind, "push")
        self.assertEqual(action.timestamp, T2)
        self.assertTrue(action.is_conflict)

    def test_never_synced_new_local_patient_with_no_sheet_row_appends(self):
        # A brand-new local patient, never synced, with no matching sheet row at
        # all yet (sheet=None) -- must push/append, never anything resembling a
        # delete (there's no delete path to even accidentally hit here).
        action = reconcile_one(local(T0, None), None)
        self.assertEqual(action.kind, "append")
        self.assertEqual(action.timestamp, T0)

    def test_first_push_not_yet_human_edited_is_not_a_false_pull(self):
        # The easiest correctness bug to introduce: a row we just appended
        # ourselves has a blank last_edited (the Apps Script onEdit trigger never
        # fired for an API-driven write). sheet_synced_at is still None (hasn't
        # been marked synced yet). A blank last_edited must NOT be misread as a
        # sheet-side change just because it differs from "unset."
        action = reconcile_one(local(T0, None), sheet(None))
        self.assertEqual(action.kind, "push")
        self.assertFalse(action.is_conflict)

    def test_first_push_after_mark_synced_is_noop(self):
        # Same row, but sheet_synced_at has now been set to T0 after the push
        # succeeded (mark_synced was called). Still blank last_edited. Must settle
        # to no-op, not loop forever re-pushing or falsely pulling.
        action = reconcile_one(local(T0, T0), sheet(None))
        self.assertEqual(action.kind, "noop")

    def test_unparseable_timestamp_treated_as_unset_not_a_crash(self):
        # Malformed data should degrade gracefully (treated as no signal), not
        # raise -- a single corrupted cell must never break the whole sync cycle.
        action = reconcile_one(local(T0, T0), sheet("not-a-real-timestamp"))
        self.assertIn(action.kind, ("noop", "push"))  # sheet_ts parses to None -> sheet_changed=False


if __name__ == "__main__":
    unittest.main()
