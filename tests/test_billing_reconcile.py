"""Cross-checking the dictation-derived billing draft against the note's own [[CPT: ...]] chips.

Cadence now derives billing codes twice, from two independent sources: `cpt.suggest_codes` maps
the generated note's section HEADINGS, and `billing.extract` reads the raw DICTATION. When they
disagree, one of them is wrong in a way that is worth the clinician's attention:

  * in the dictation, absent from the note -> the model dropped a stated treatment (rule 15)
  * in the note, absent from the dictation -> a fabricated code or a heading artifact (rule 14)

The severity split is the honest part. A code-level disagreement is `high`, because both sides are
deterministic. A minutes disagreement is `low`, because the note's side of that comparison is
prose the MODEL wrote, so a mismatch is as likely to be a rewording as a real error.

Also locks the non-negotiable: `reconcile` must NOT touch `sections`. The per-section chips and
every test in tests/test_cpt.py depend on them being left exactly as `suggest_codes` wrote them.

    .venv/Scripts/python.exe -m unittest tests.test_billing_reconcile -v
"""

import copy
import unittest

from app.generate import billing


def _sec(heading, body, carried=False):
    return {"heading": heading, "body": body, "carried_forward": carried}


def _kinds(draft):
    return {c.kind for c in draft.conflicts}


def _by_code(draft, code):
    return [c for c in draft.conflicts if c.code == code]


DICTATION = (
    "Follow-up, right shoulder. Therapeutic exercise for twenty minutes. "
    "Manual therapy for fifteen minutes."
)


class AgreementTests(unittest.TestCase):
    def test_a_matching_note_raises_no_conflicts(self):
        draft = billing.extract(DICTATION)
        sections = [
            _sec("Therapeutic Exercise", "Minutes: 20 [[CPT: 97110 Therapeutic Exercise — confirm]]"),
            _sec("Manual Therapy", "Minutes: 15 [[CPT: 97140 Manual Therapy — confirm]]"),
        ]
        self.assertEqual(billing.reconcile(draft, sections).conflicts, ())


class ConflictKindTests(unittest.TestCase):
    def test_dictated_treatment_missing_from_the_note_is_high_severity(self):
        """The rule-15 omission: the therapist said it, the model didn't write it."""
        draft = billing.extract(DICTATION)
        sections = [
            _sec("Therapeutic Exercise", "Minutes: 20 [[CPT: 97110 Therapeutic Exercise — confirm]]"),
        ]
        out = billing.reconcile(draft, sections)
        self.assertIn("dictation_only", _kinds(out))
        conflict = _by_code(out, "97140")[0]
        self.assertEqual(conflict.severity, "high")
        self.assertIn("rule 15", conflict.detail)

    def test_note_code_with_no_dictation_basis_is_high_severity(self):
        """The rule-14 fabrication: a chip on a section the dictation never justified."""
        draft = billing.extract(DICTATION)
        sections = [
            _sec("Therapeutic Exercise", "Minutes: 20 [[CPT: 97110 Therapeutic Exercise — confirm]]"),
            _sec("Manual Therapy", "Minutes: 15 [[CPT: 97140 Manual Therapy — confirm]]"),
            _sec("Gait Training", "Minutes: 10 [[CPT: 97116 Gait Training — confirm]]"),
        ]
        out = billing.reconcile(draft, sections)
        self.assertIn("note_only", _kinds(out))
        conflict = _by_code(out, "97116")[0]
        self.assertEqual(conflict.severity, "high")
        self.assertIn("rule 14", conflict.detail)

    def test_minutes_disagreement_is_low_severity(self):
        """Rated low on purpose: the note's minutes are model-written prose, so a mismatch is as
        likely to be a rewording as a real error. Rating it `high` would train the clinician to
        ignore the high-severity code conflicts that actually matter."""
        draft = billing.extract(DICTATION)
        sections = [
            _sec("Therapeutic Exercise", "Minutes: 25 [[CPT: 97110 Therapeutic Exercise — confirm]]"),
            _sec("Manual Therapy", "Minutes: 15 [[CPT: 97140 Manual Therapy — confirm]]"),
        ]
        out = billing.reconcile(draft, sections)
        conflict = _by_code(out, "97110")[0]
        self.assertEqual(conflict.kind, "minutes_mismatch")
        self.assertEqual(conflict.severity, "low")
        self.assertIn("20", conflict.detail)
        self.assertIn("25", conflict.detail)

    def test_a_negated_treatment_written_into_the_note_is_flagged(self):
        """The overbill this whole module guards against, caught from the other direction: the
        therapist said they did NOT do it, and the model wrote a billable section anyway."""
        draft = billing.extract(
            "Follow-up, right shoulder. Therapeutic exercise for twenty minutes. "
            "We did not do gait training today."
        )
        sections = [
            _sec("Therapeutic Exercise", "Minutes: 20 [[CPT: 97110 Therapeutic Exercise — confirm]]"),
            _sec("Gait Training", "Minutes: 10 [[CPT: 97116 Gait Training — confirm]]"),
        ]
        out = billing.reconcile(draft, sections)
        self.assertEqual(_by_code(out, "97116")[0].kind, "note_only")


class PurityTests(unittest.TestCase):
    def test_sections_are_never_modified(self):
        """`suggest_codes` owns the per-section chips. If reconcile touched them, the review UI
        and tests/test_cpt.py would start disagreeing about what the note says."""
        draft = billing.extract(DICTATION)
        sections = [
            _sec("Therapeutic Exercise", "Minutes: 25 [[CPT: 97110 Therapeutic Exercise — confirm]]"),
            _sec("Gait Training", "Minutes: 10 [[CPT: 97116 Gait Training — confirm]]"),
        ]
        before = copy.deepcopy(sections)
        billing.reconcile(draft, sections)
        self.assertEqual(sections, before)

    def test_the_original_draft_is_not_mutated(self):
        draft = billing.extract(DICTATION)
        billing.reconcile(draft, [_sec("Gait Training", "[[CPT: 97116 Gait Training — confirm]]")])
        self.assertEqual(draft.conflicts, ())

    def test_reconcile_preserves_the_rest_of_the_draft(self):
        draft = billing.extract(DICTATION)
        out = billing.reconcile(draft, [])
        self.assertEqual(out.total_timed_minutes, draft.total_timed_minutes)
        self.assertEqual(out.units.total_units, draft.units.total_units)
        self.assertEqual(out.interventions, draft.interventions)
        self.assertTrue(out.confirm_required)

    def test_an_empty_note_flags_every_dictated_treatment(self):
        draft = billing.extract(DICTATION)
        out = billing.reconcile(draft, [])
        self.assertEqual(_kinds(out), {"dictation_only"})
        self.assertEqual(len(out.conflicts), 2)

    def test_reconcile_is_idempotent(self):
        """The conflict set is a pure function of (draft, sections), so re-running must recompute
        it rather than append. Regression: seeding the list from `draft.conflicts` showed every
        finding twice in the review card on the second pass."""
        draft = billing.extract(DICTATION)
        once = billing.reconcile(draft, [])
        twice = billing.reconcile(once, [])
        self.assertEqual(once.conflicts, twice.conflicts)


if __name__ == "__main__":
    unittest.main()
