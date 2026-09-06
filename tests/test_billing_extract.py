"""Dictation -> interventions / ICD-10 / minutes, and the four guards that make it safe.

CLAUDE.md rule 12 forbids body-scanning the generated NOTE for interventions. Scanning the
DICTATION is permitted instead, but only because of the guards this suite exists to lock:

  1. clause scoping        — a negation in one clause must not reach a cue in the next
  2. cue strength tiers    — a technique name never bills on its own authority
  3. a status enum         — an excluded hit is RETAINED with its reason, never silently dropped
  4. confirm_required      — hard-coded True on every path

The negatives matter more than the positives here. A missed intervention is a safe failure the
clinician corrects; a negated, prior-visit, planned, or home-program treatment that leaks into the
billable set is an OVERBILL. Every "must not bill" test below is one of those.

No model, no network, no DB — pure functions over strings.

    .venv/Scripts/python.exe -m unittest tests.test_billing_extract -v
"""

import unittest

from app.generate import billing, coding_tables
from app.generate.billing import (
    BARE_NUMBER,
    EXPLICIT,
    FRACTION,
    FRACTION_UNRESOLVED,
    HOME_PROGRAM,
    NEGATED,
    NOT_STATED,
    PERFORMED,
    PLANNED,
    PRIOR_VISIT,
    UNCERTAIN,
)


def _status(draft, code):
    """Status of `code` in a draft, or None if the code was never detected at all."""
    for h in draft.interventions:
        if h.code == code:
            return h.status
    return None


def _hit(draft, code):
    for h in draft.interventions:
        if h.code == code:
            return h
    raise AssertionError(f"{code} not detected in: {[h.code for h in draft.interventions]}")


class ClauseScopingTests(unittest.TestCase):
    def test_negation_does_not_cross_a_sentence_boundary(self):
        draft = billing.extract(
            "She reports no shoulder pain at rest. We did therapeutic exercise for twenty minutes."
        )
        self.assertEqual(_status(draft, "97110"), PERFORMED)

    def test_negation_does_not_cross_a_comma(self):
        """"no pain today, we did ther ex" negates the pain, not the treatment. A comma ends a
        negation's scope in speech, which is what keeps the very common bare "no" from
        suppressing everything downstream of it."""
        draft = billing.extract("Shoulder follow-up, no pain today, we did ther ex twenty minutes.")
        self.assertEqual(_status(draft, "97110"), PERFORMED)

    def test_negation_does_reach_its_own_cue(self):
        draft = billing.extract("Shoulder visit. We did not do gait training today.")
        self.assertEqual(_status(draft, "97116"), NEGATED)
        self.assertNotIn("97116", {h.code for h in draft.billable})

    def test_a_connective_resets_scope(self):
        draft = billing.extract(
            "Shoulder. We did not do manual therapy, but then therapeutic exercise for twenty minutes."
        )
        self.assertEqual(_status(draft, "97140"), NEGATED)
        self.assertEqual(_status(draft, "97110"), PERFORMED)


class StatusTests(unittest.TestCase):
    def test_prior_visit_treatment_is_not_billable_today(self):
        draft = billing.extract("Shoulder. Last visit we did manual therapy.")
        self.assertEqual(_status(draft, "97140"), PRIOR_VISIT)
        self.assertEqual(draft.billable, ())

    def test_a_scope_reset_rescues_todays_treatment_from_a_prior_marker(self):
        """The failure this guard was written for: without SCOPE_RESET_CUES, "today" is just more
        text and BOTH treatments get attributed to the prior visit, billing nothing."""
        draft = billing.extract(
            "Shoulder. Last visit we did manual therapy, today ther ex for twenty minutes."
        )
        self.assertEqual(_status(draft, "97140"), PRIOR_VISIT)
        self.assertEqual(_status(draft, "97110"), PERFORMED)

    def test_marker_after_the_cue_still_scopes_it(self):
        draft = billing.extract("Shoulder. We did manual therapy last visit.")
        self.assertEqual(_status(draft, "97140"), PRIOR_VISIT)

    def test_planned_treatment_is_not_billable(self):
        draft = billing.extract("Shoulder. Next visit we will add gait training.")
        self.assertEqual(_status(draft, "97116"), PLANNED)
        self.assertEqual(draft.billable, ())

    def test_the_noun_form_of_a_plan_is_also_not_billable(self):
        """Regression from the hand-written control (record 108) — a FOUR-code overbill.

        "Interventions planned include therapeutic exercise, neuromuscular re-education, manual
        therapy, and therapeutic activities" billed all four as performed, because every future
        cue was a VERB form ("plan to", "will add") and a real evaluation note used the NOUN form.
        The synthetic corpus structurally could not have caught this: its generator only renders
        the frames it was given, so it never spoke this sentence.
        """
        draft = billing.extract(
            "Left shoulder evaluation. Interventions planned include therapeutic exercise, "
            "neuromuscular re-education for deltoid retraining, manual therapy for the elbow "
            "and scapula, and therapeutic activities for functional reintegration."
        )
        self.assertEqual(draft.billable, ())
        for code in ("97110", "97112", "97140", "97530"):
            with self.subTest(code=code):
                self.assertEqual(_status(draft, code), PLANNED)

    def test_home_program_is_not_billable(self):
        draft = billing.extract("Shoulder. Her home program includes stretching and pulleys.")
        self.assertEqual(_status(draft, "97110"), HOME_PROGRAM)
        self.assertEqual(draft.billable, ())

    def test_excluded_hits_are_retained_with_their_reason(self):
        """Retention is the whole design: a wrong exclusion must be VISIBLE to the clinician
        rather than showing up as a silently absent code."""
        draft = billing.extract("Shoulder. We did not do gait training today.")
        self.assertEqual(len(draft.interventions), 1)
        self.assertEqual(draft.interventions[0].status, NEGATED)
        self.assertIn("gait training", draft.interventions[0].clause.lower())


class CueStrengthTests(unittest.TestCase):
    def test_a_weak_technique_name_does_not_bill_on_its_own(self):
        """"stretching" may be ther ex (patient-performed) or manual therapy (therapist-performed).
        Auto-billing either is a coin flip on a claim, so it surfaces as a candidate instead."""
        draft = billing.extract("Shoulder. We worked on stretching for fifteen minutes.")
        self.assertEqual(_status(draft, "97110"), UNCERTAIN)
        self.assertEqual(draft.billable, ())

    def test_the_service_name_does_bill(self):
        draft = billing.extract("Shoulder. Therapeutic exercise for fifteen minutes.")
        self.assertEqual(_status(draft, "97110"), PERFORMED)

    def test_uncertain_cues_are_surfaced_as_a_gap(self):
        draft = billing.extract("Shoulder. We worked on balance work for ten minutes.")
        self.assertTrue(any("confirm or discard" in m for m in draft.missing))

    def test_specific_cue_beats_the_generic_one_it_contains(self):
        """"manual stretching" is manual therapy, not therapeutic exercise. The overlapping
        generic cue must be suppressed — the same specific-before-generic contract
        tests/test_cpt.py locks for the heading table."""
        draft = billing.extract("Shoulder. Manual stretching for fifteen minutes.")
        self.assertEqual(_status(draft, "97140"), PERFORMED)
        self.assertIsNone(_status(draft, "97110"))

    def test_traction_is_disambiguated_by_what_the_therapist_said(self):
        """MECHANICAL traction (97012) is a service-based modality; MANUAL traction (97140) is a
        timed hands-on technique. They bill completely differently, so bare "traction" — how a
        spine dictation usually says it — must surface for confirmation rather than guess.

        Found by the all-region eval: bare "traction" was the ONLY code in the whole corpus that
        was never even surfaced, because the table knew "mechanical traction" and nothing else.
        """
        self.assertEqual(_status(billing.extract("Low back. Mechanical traction fifteen minutes."),
                                 "97012"), PERFORMED)
        self.assertEqual(_status(billing.extract("Neck. Manual traction for ten minutes."),
                                 "97140"), PERFORMED)
        bare = billing.extract("Low back. We also did traction in supine.")
        self.assertEqual(_status(bare, "97012"), UNCERTAIN)
        self.assertEqual(bare.billable, ())

    def test_ther_ex_abbreviation_does_not_match_inside_other_exercise(self):
        """Word boundaries are load-bearing: a naive substring test for "ther ex" fires inside
        "oTHER EXercise", billing 97110 off a sentence that never named the service."""
        draft = billing.extract("Shoulder. She tolerated the other exercises well.")
        self.assertIsNone(_status(draft, "97110"))


class MinutesTests(unittest.TestCase):
    def test_explicit_minutes_before_the_cue(self):
        draft = billing.extract("Shoulder. Twenty minutes of therapeutic exercise.")
        hit = _hit(draft, "97110")
        self.assertEqual((hit.minutes, hit.minutes_basis), (20, EXPLICIT))

    def test_explicit_minutes_after_the_cue(self):
        draft = billing.extract("Shoulder. Manual therapy for fifteen minutes.")
        hit = _hit(draft, "97140")
        self.assertEqual((hit.minutes, hit.minutes_basis), (15, EXPLICIT))

    def test_two_treatments_in_one_clause_get_their_own_minutes(self):
        """Assignment is one-to-one by proximity, so the same duration can't be claimed twice."""
        draft = billing.extract(
            "Shoulder. Manual therapy fifteen minutes and therapeutic exercise twenty minutes."
        )
        self.assertEqual(_hit(draft, "97140").minutes, 15)
        self.assertEqual(_hit(draft, "97110").minutes, 20)
        self.assertEqual(draft.total_timed_minutes, 35)

    def test_a_fraction_resolves_against_a_stated_session_length(self):
        draft = billing.extract(
            "Shoulder. This was a forty-five minute session. "
            "Therapeutic exercise for a third of the session."
        )
        hit = _hit(draft, "97110")
        self.assertEqual((hit.minutes, hit.minutes_basis), (15, FRACTION))

    def test_a_fraction_with_no_stated_session_length_is_a_gap_not_a_guess(self):
        draft = billing.extract("Shoulder. Therapeutic exercise for a third of the session.")
        hit = _hit(draft, "97110")
        self.assertIsNone(hit.minutes)
        self.assertEqual(hit.minutes_basis, FRACTION_UNRESOLVED)
        self.assertTrue(any("no session length was stated" in m for m in draft.missing))

    def test_a_bare_number_is_read_as_minutes_only_in_an_unambiguous_clause(self):
        draft = billing.extract("Shoulder. Manual therapy fifteen.")
        hit = _hit(draft, "97140")
        self.assertEqual((hit.minutes, hit.minutes_basis), (15, BARE_NUMBER))
        self.assertTrue(any("bare number" in m for m in draft.missing),
                        "a bare-number reading must be flagged for verification")

    def test_a_bare_number_next_to_a_unit_is_not_minutes(self):
        for clause, label in [
            ("Therapeutic exercise, flexion to ninety degrees.", "degrees"),
            ("Therapeutic exercise, pain four out of ten.", "pain rating"),
            ("Therapeutic exercise, strength four out of five.", "MMT grade"),
            ("Therapeutic exercise, three sets of twelve reps.", "reps"),
            ("Therapeutic exercise, ambulated fifty feet.", "distance"),
        ]:
            with self.subTest(unit=label):
                draft = billing.extract("Shoulder. " + clause)
                self.assertIsNone(_hit(draft, "97110").minutes, f"{label} was read as minutes")

    def test_unstated_minutes_are_flagged_not_invented(self):
        draft = billing.extract("Shoulder. We did therapeutic exercise and gait training.")
        self.assertIsNone(_hit(draft, "97110").minutes)
        self.assertEqual(_hit(draft, "97110").minutes_basis, NOT_STATED)
        self.assertEqual(draft.total_timed_minutes, 0)
        self.assertTrue(any("Minutes not stated" in m for m in draft.missing))


class SelfCorrectionTests(unittest.TestCase):
    def test_the_corrected_value_is_performed_and_neither_is_dropped(self):
        """Rule 8: keep only the corrected value on a self-correction. The superseded cue becomes
        `uncertain` rather than vanishing — dropping half of what the therapist said would hide
        their own ambiguity from the person signing the note."""
        draft = billing.extract(
            "Shoulder. We did gait training, sorry, therapeutic activities for twenty minutes."
        )
        self.assertEqual(_status(draft, "97530"), PERFORMED)
        self.assertEqual(_status(draft, "97116"), UNCERTAIN)
        self.assertEqual({h.code for h in draft.billable}, {"97530"})

    def test_the_retracted_treatment_is_dropped_even_when_the_replacement_is_unrecognized(self):
        """Regression, found by the eval harness on synthetic record 1021.

        "joint mobilization, I mean strength work" — the corrected-TO phrase is not in the cue
        table, so only ONE cue matched. An earlier version required two recognized cues before
        applying the self-correction rule, so the check was skipped and the RETRACTED treatment
        was billed. Whether we recognize the replacement is irrelevant: the therapist withdrew
        what came before the marker.
        """
        draft = billing.extract(
            "Follow-up, right shoulder. Then joint mobilization, I mean strength work."
        )
        self.assertEqual(_status(draft, "97140"), UNCERTAIN)
        self.assertEqual(draft.billable, ())

    def test_a_correction_after_the_only_cue_does_not_bill_it(self):
        draft = billing.extract("Shoulder. We did gait training, sorry, that was last week.")
        self.assertNotIn("97116", {h.code for h in draft.billable})


class IcdTests(unittest.TestCase):
    def test_a_stated_diagnosis_with_laterality(self):
        draft = billing.extract(
            "Initial evaluation, right shoulder. Referring diagnosis is right rotator cuff "
            "tendinopathy."
        )
        codes = {c.code for c in draft.icd_candidates}
        self.assertIn("M75.101", codes)
        self.assertTrue(all(c.laterality_stated for c in draft.icd_candidates))

    def test_left_selects_the_left_variant(self):
        draft = billing.extract("Left shoulder. Diagnosis is left adhesive capsulitis.")
        self.assertIn("M75.02", {c.code for c in draft.icd_candidates})

    def test_bilateral_with_no_bilateral_code_emits_both_sides(self):
        draft = billing.extract(
            "Bilateral shoulders. Diagnosis is bilateral adhesive capsulitis."
        )
        codes = {c.code for c in draft.icd_candidates}
        self.assertEqual({"M75.01", "M75.02"}, codes)

    def test_unstated_laterality_uses_the_unspecified_code_and_flags_it(self):
        """A guessed side is a claim denial at best. The unspecified variant plus a visible gap is
        the honest output."""
        draft = billing.extract("Shoulder evaluation. Diagnosis is adhesive capsulitis.")
        self.assertIn("M75.00", {c.code for c in draft.icd_candidates})
        self.assertTrue(any("Laterality not stated" in m for m in draft.missing))

    def test_a_hedged_mention_is_not_a_diagnosis(self):
        """The single most important ICD negative: a worry is not a billable diagnosis."""
        draft = billing.extract(
            "Right shoulder. She is worried about a rotator cuff tear after her sister's surgery."
        )
        self.assertEqual(draft.icd_candidates, ())

    def test_a_mention_with_no_diagnosis_context_is_not_a_diagnosis(self):
        draft = billing.extract("Right shoulder. We talked about rotator cuff tendinopathy.")
        self.assertEqual(draft.icd_candidates, ())

    def test_specific_diagnosis_beats_the_generic_family(self):
        draft = billing.extract(
            "Right shoulder. Diagnosis is a complete rotator cuff tear on the right."
        )
        codes = {c.code for c in draft.icd_candidates}
        self.assertIn("M75.121", codes)
        self.assertNotIn("M75.101", codes)

    def test_a_seventh_character_caution_reaches_the_clinician(self):
        draft = billing.extract("Right shoulder. Diagnosis is a right shoulder sprain.")
        self.assertIn("S43.421", {c.code for c in draft.icd_candidates})
        self.assertTrue(any("7th character" in m for m in draft.missing))

    def test_a_past_condition_in_a_history_clause_is_not_the_billable_diagnosis(self):
        """Regression from the hand-written control (record 108).

        "History of present illness, he had increasing left shoulder pain for about four years,
        was diagnosed with rotator cuff arthropathy, ..." yielded M25.512 for a FOUR-YEAR-OLD
        symptom, because "history of" was a diagnosis-CONTEXT cue and "diagnosed" sat in the same
        run-on clause. A history clause must never produce a billing code — it is not what is
        being treated today.
        """
        draft = billing.extract(
            "Left shoulder. History of present illness, he had increasing left shoulder pain for "
            "about four years, was diagnosed with rotator cuff arthropathy."
        )
        self.assertEqual(draft.icd_candidates, ())

    def test_a_post_surgical_header_frames_the_diagnosis(self):
        """Regressions from the hand-written control set. Both are how a post-op visit actually
        opens, and neither carried a recognized diagnosis context:
          * record 107 — "ten weeks post left SLAP repair, type two labral tear"
          * record 201 — "she's four weeks out from a right total knee replacement"
        """
        draft = billing.extract(
            "This is a follow-up, ten weeks post left SLAP repair, type two labral tear."
        )
        self.assertIn("S43.432", {c.code for c in draft.icd_candidates})

        draft = billing.extract(
            "Follow up, right knee, she's four weeks out from a right total knee replacement."
        )
        self.assertIn("Z47.1", {c.code for c in draft.icd_candidates})

    def test_admitted_paraphrases_reach_their_diagnosis(self):
        """The ICD eval used to be perfectly circular: the generator picked the spoken diagnosis
        with `rng.choice(rule.cues)` — the extractor's OWN cue list — so recall read 100% while
        measuring nothing. Adding real paraphrases dropped it to 79% (9% on paraphrased samples).
        These are the ones judged unambiguous enough to code on and admitted (rule 21a)."""
        for text, want in [
            ("Right shoulder. Diagnosis is a torn rotator cuff on the right.", "M75.101"),
            ("Left shoulder. Referring diagnosis is left subacromial pain syndrome.", "M75.42"),
            ("Right knee. Assessment is a blown ACL on the right.", "S83.511"),
            ("Left knee. Diagnosis is degenerative knee.", "M17.12"),
            ("Low back. Working diagnosis is a slipped disc.", "M51.26"),
            ("Low back. Diagnosis is canal stenosis.", "M48.061"),
            ("Neck. Diagnosis is a pinched nerve in the neck.", "M50.10"),
            ("Right hip. Referring diagnosis is right cam impingement.", "M24.851"),
            ("Left ankle. Diagnosis is a rolled ankle on the left.", "S93.402"),
        ]:
            with self.subTest(text=text[:46]):
                draft = billing.extract(text)
                self.assertIn(want, {c.code for c in draft.icd_candidates})

    def test_ambiguous_phrasings_are_deliberately_not_coded(self):
        """The other half of rule 21(a): a low recall number must NOT be "fixed" by admitting a
        phrase that doesn't specifically name one diagnosis. Each of these is a SYMPTOM with
        several causes, and guessing a code for it would be a wrong claim.

        "PF" is the sharpest case — it means plantar fascia to a foot therapist and patellofemoral
        to a knee therapist, so it can never be safely expanded.
        """
        for text, why in [
            ("Left foot. Diagnosis is heel pain.", "fat pad, calcaneal stress fracture, Sever's"),
            ("Right knee. Diagnosis is anterior knee pain.", "PFPS, fat pad, patellar tendinopathy"),
            ("Right hip. Diagnosis is lateral hip pain.", "bursitis vs gluteal tendinopathy"),
            ("Left shoulder. Diagnosis is a stiff shoulder.", "stiffness M25.61 vs capsulitis M75.0"),
        ]:
            with self.subTest(why=why):
                codes = {c.code for c in billing.extract(text).icd_candidates}
                # A generic pain/stiffness code is fine; the SPECIFIC pathology must not be guessed.
                for specific in ("M72.2", "M22.2X1", "M22.2X2", "M70.61", "M70.62",
                                 "M75.01", "M75.02"):
                    self.assertNotIn(specific, codes, f"guessed {specific} from a symptom ({why})")

    def test_no_body_part_means_no_icd_at_all(self):
        draft = billing.extract("Patient did therapeutic exercise for twenty minutes.")
        self.assertIsNone(draft.body_part)
        self.assertEqual(draft.icd_candidates, ())
        self.assertTrue(any("Body region not identified" in m for m in draft.missing))

    def test_a_body_part_with_no_stated_diagnosis_is_flagged(self):
        draft = billing.extract("Shoulder follow-up. Therapeutic exercise for twenty minutes.")
        self.assertEqual(draft.body_part, "shoulder")
        self.assertEqual(draft.icd_candidates, ())
        self.assertTrue(any("No diagnosis stated" in m for m in draft.missing))


class DedupeTests(unittest.TestCase):
    def test_one_treatment_split_across_the_session_sums_its_minutes(self):
        draft = billing.extract(
            "Shoulder. Therapeutic exercise for twenty minutes. "
            "Then more therapeutic exercise, ten minutes at the end."
        )
        self.assertEqual(_hit(draft, "97110").minutes, 30)

    def test_a_performed_mention_is_not_shadowed_by_a_planned_one(self):
        draft = billing.extract(
            "Shoulder. Manual therapy for fifteen minutes. "
            "Next visit we will do more manual therapy."
        )
        self.assertEqual(_status(draft, "97140"), PERFORMED)
        self.assertEqual(_hit(draft, "97140").minutes, 15)

    def test_minutes_are_never_borrowed_from_a_not_today_status(self):
        """A planned treatment's duration must not become today's billable minutes."""
        for text, why in [
            ("Shoulder. We did gait training. Next visit we will do gait training for thirty minutes.",
             "planned"),
            ("Shoulder. We did gait training. Last visit we did gait training for thirty minutes.",
             "prior_visit"),
            ("Shoulder. We did gait training. Her home program has gait training for thirty minutes.",
             "home_program"),
        ]:
            with self.subTest(source=why):
                draft = billing.extract(text)
                self.assertEqual(_status(draft, "97116"), PERFORMED)
                self.assertIsNone(_hit(draft, "97116").minutes)
                self.assertEqual(draft.total_timed_minutes, 0)

    def test_minutes_do_carry_between_two_today_mentions_of_one_code(self):
        """Regression from the all-region eval (synthetic record 2021).

        "strength work, eight minutes" is a WEAK cue, so it lands as `uncertain`; a later strong
        cue for the same code ("...I mean ther ex") lands as `performed` with no minutes. Both
        assert today's session — only the CODE was ever in doubt — so the 8 minutes belongs to the
        performed line. An earlier version let the better status win outright and dropped it.
        """
        draft = billing.extract(
            "Left knee. Then strength work, eight minutes. "
            "Then electrical stimulation, I mean ther ex."
        )
        self.assertEqual(_status(draft, "97110"), PERFORMED)
        self.assertEqual(_hit(draft, "97110").minutes, 8)
        self.assertEqual(draft.total_timed_minutes, 8)

    def test_carrying_minutes_fills_a_blank_and_never_sums(self):
        """The carry can only ever fill a None. If it added, two mentions of one treatment block
        would double-count it — the overbill direction."""
        draft = billing.extract(
            "Left knee. Then strength work, eight minutes. Then ther ex for twenty minutes."
        )
        self.assertEqual(_hit(draft, "97110").minutes, 20)

    def test_an_explicit_negation_is_not_erased_by_a_later_performed_mention(self):
        """Found by the hand-written long-form control (evals/data/longform_intake.txt).

        "most billable wins" quietly threw away a detected negation: the therapist said "I did not
        do any electrical stimulation" and then, a sentence later, "I considered functional
        electrical stimulation" — and 97014 was BILLED. Two mentions that contradict each other
        cannot be resolved automatically, so the code drops to `uncertain` and carries both
        clauses. Per rule 12(b) a confirmation click is clinician work; a leaked negation is a
        claim.
        """
        draft = billing.extract(
            "Left knee. We did not do any manual therapy today. "
            "The manual therapy table was free so we used it for fifteen minutes."
        )
        self.assertEqual(_status(draft, "97140"), UNCERTAIN)
        self.assertNotIn("97140", {h.code for h in draft.billable})
        self.assertIn("did not do any manual therapy", _hit(draft, "97140").clause)

    def test_a_negation_alone_still_reads_as_negated(self):
        draft = billing.extract("Left knee. We did not do any manual therapy today.")
        self.assertEqual(_status(draft, "97140"), NEGATED)

    def test_an_uncontradicted_treatment_is_untouched_by_the_contradiction_check(self):
        draft = billing.extract("Left knee. Manual therapy for fifteen minutes.")
        self.assertEqual(_status(draft, "97140"), PERFORMED)
        self.assertNotIn("the dictation also said", _hit(draft, "97140").clause)


class DeliberationCueTests(unittest.TestCase):
    """Contemplating a treatment is not performing it. Found by the hand-written long-form
    control: "I considered functional electrical stimulation for the left dorsiflexors but I want
    to check with the surgeon first" billed 97014. The "planned for a future visit" that followed
    sat in a later clause, so clause scoping — correctly — never saw it; the fix belongs on the
    verb, not on a wider scope."""

    def test_considered_is_not_performed(self):
        draft = billing.extract(
            "Left ankle. I considered electrical stimulation for the dorsiflexors."
        )
        self.assertEqual(_status(draft, "97014"), PLANNED)
        self.assertNotIn("97014", {h.code for h in draft.billable})

    def test_pending_clearance_is_not_performed(self):
        draft = billing.extract("Left knee. Manual therapy pending surgeon clearance.")
        self.assertEqual(_status(draft, "97140"), PLANNED)

    def test_thinking_about_is_not_performed(self):
        draft = billing.extract("Right hip. Thinking about adding gait training.")
        self.assertEqual(_status(draft, "97116"), PLANNED)

    def test_a_deliberation_cue_does_not_suppress_a_treatment_in_the_next_clause(self):
        draft = billing.extract(
            "Right hip. I considered electrical stimulation. "
            "We did therapeutic exercise for twenty minutes."
        )
        self.assertEqual(_status(draft, "97110"), PERFORMED)
        self.assertEqual(_hit(draft, "97110").minutes, 20)


class EvalComplexityCaptureTests(unittest.TestCase):
    """97161/2/3 is CAPTURED when the therapist states it, never inferred.

    Rule 12 keeps complexity out of the auto-assigned set because choosing a level is a clinical
    judgment — and it still is. What changed is that Cadence used to ask for the level on EVERY
    evaluation even when the therapist had just dictated it, which is not caution: it discards a
    stated fact and demands it back, and a gap list that always contains the same question is a
    gap list the clinician stops reading.
    """

    def _codes(self, text, **kw):
        draft = billing.extract(text, eval_form=kw.pop("eval_form", True), **kw)
        return [h.code for h in draft.interventions if h.code in coding_tables.EVAL_CPT_CODES]

    def test_spoken_level_is_captured(self):
        for phrase, want in [("clinical decision making is low complexity", "97161"),
                             ("this is a moderate complexity evaluation", "97162"),
                             ("high complexity given the comorbidities", "97163")]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self._codes(f"Initial evaluation, left knee OA. {phrase}."), [want])

    def test_a_dictated_code_is_captured(self):
        self.assertEqual(self._codes("Initial evaluation, left knee OA. Bill 97163 for today."),
                         ["97163"])

    def test_nothing_stated_captures_nothing(self):
        self.assertEqual(self._codes("Initial evaluation, left knee OA. Ther ex twenty minutes."), [])

    def test_complex_regional_pain_syndrome_is_not_a_complexity_level(self):
        """The reason every cue requires the noun "complexity" or a literal code: "complex" alone
        appears inside a diagnosis, and matching it would staple an evaluation code to it."""
        self.assertEqual(
            self._codes("Initial evaluation, left ankle. Diagnosis is complex regional pain syndrome."),
            [])

    def test_two_different_levels_capture_nothing(self):
        """An ambiguous dictation must still reach the clinician as a question — the same refusal
        `body_part_for` makes on a tie."""
        self.assertEqual(
            self._codes("Initial eval. This is low complexity. Actually it is high complexity."), [])

    def test_a_negated_level_is_not_captured(self):
        self.assertEqual(self._codes("Initial eval, knee OA. This is not a high complexity evaluation."),
                         [])

    def test_a_follow_up_never_grows_an_evaluation_code(self):
        """`eval_form` is the caller's answer, not something inferred from the words: a follow-up
        that happens to say "high complexity" must not bill an evaluation."""
        self.assertEqual(
            self._codes("Follow up visit, knee. That was a high complexity session.", eval_form=False),
            [])

    def test_an_eval_code_never_enters_the_timed_unit_math(self):
        draft = billing.extract(
            "Initial evaluation, left knee OA. High complexity. Ther ex for twenty minutes.",
            eval_form=True)
        self.assertEqual(draft.total_timed_minutes, 20)
        self.assertEqual(draft.units.total_units, 1)

    def test_a_captured_eval_code_is_not_reported_as_dropped_from_the_note(self):
        """`reconcile` compares dictation codes against the note's chips. An evaluation code is a
        per-visit code and never a treatment section, so leaving it in that comparison made every
        captured level report itself as a rule-15 omission."""
        draft = billing.extract(
            "Initial evaluation, left knee OA. High complexity. Ther ex for twenty minutes.",
            eval_form=True)
        reconciled = billing.reconcile(draft, [
            {"heading": "Therapeutic Exercise", "body": "Minutes: 20 [[CPT: 97110 Therapeutic Exercise — confirm]]",
             "carried_forward": False},
        ])
        self.assertEqual([c.code for c in reconciled.conflicts], [])


class FullDraftTests(unittest.TestCase):
    TRANSCRIPT = (
        "Okay, follow-up visit, right shoulder. Referring diagnosis is right rotator cuff "
        "tendinopathy. Um, today we did therapeutic exercise for twenty-five minutes, "
        "scapular retraction and external rotation with theraband. Then manual therapy, "
        "twenty minutes, to the right glenohumeral joint. Then neuromuscular re-education for "
        "fifteen minutes working on scapular control. We did not do gait training. "
        "Her home program includes pulleys. Next visit we will add therapeutic activities."
    )

    def setUp(self):
        self.draft = billing.extract(self.TRANSCRIPT)

    def test_a_realistic_session_produces_four_units(self):
        self.assertEqual(self.draft.total_timed_minutes, 60)
        self.assertEqual(self.draft.units.total_units, 4)

    def test_only_the_performed_treatments_are_billable(self):
        self.assertEqual({h.code for h in self.draft.billable}, {"97110", "97140", "97112"})

    def test_every_distractor_is_excluded_with_its_reason(self):
        self.assertEqual(_status(self.draft, "97116"), NEGATED)
        self.assertEqual(_status(self.draft, "97530"), PLANNED)

    def test_the_diagnosis_is_detected(self):
        self.assertIn("M75.101", {c.code for c in self.draft.icd_candidates})

    def test_both_unit_methods_are_reported(self):
        self.assertIsNotNone(self.draft.units)
        self.assertIsNotNone(self.draft.units_alt)
        self.assertEqual(self.draft.units.method, billing.CMS_SUBSTITUTION)
        self.assertEqual(self.draft.units_alt.method, billing.AMA_RULE_OF_EIGHTS)

    def test_confirm_required_is_true(self):
        self.assertTrue(self.draft.confirm_required)


class ConfirmRequiredTests(unittest.TestCase):
    def test_confirm_required_on_every_path(self):
        """Cadence drafts billing; the clinician bills. This flag is the machine-readable form of
        that boundary, so it is asserted on every shape of input rather than once."""
        for text in [
            "",
            "Shoulder. Therapeutic exercise twenty minutes.",
            "We did not do anything.",
            "Right shoulder. Diagnosis is right adhesive capsulitis.",
            "Patient tolerated treatment well.",
        ]:
            with self.subTest(text=text[:40]):
                self.assertTrue(billing.extract(text).confirm_required)


class TableIntegrityTests(unittest.TestCase):
    def test_the_billing_tables_and_gold_labels_are_signed_off(self):
        """THE SIGN-OFF GATE. This test is EXPECTED TO FAIL until a clinician or certified coder
        reviews the billing data, and that failure is the point — a wrong code rendered as a
        confident chip is worse than no chip, which is exactly the failure rule 12 was written
        about. It deliberately reports EVERY outstanding item at once rather than existing as
        several separate red tests, so there is one gate with one complete list.

        See docs/go-live-checklist.md section 4b.
        """
        import json
        from pathlib import Path

        outstanding = []
        self.assertTrue(coding_tables.ICD10CM_YEAR)
        unverified = coding_tables.unverified_body_parts()
        if unverified:
            outstanding.append(
                "  * app/generate/coding_tables.py: TABLE_PROVENANCE has no verified_by/_on for "
                f"{unverified} — each region's ICD-10 table needs review against ICD-10-CM "
                f"{coding_tables.ICD10CM_YEAR}. Sign off the regions the practice actually sees "
                "first; they are independent."
            )

        # The hand-written control set is what every accuracy number is measured against. Its
        # billing gold was hand-READ from the transcripts (never produced by the extractor, which
        # would be circular), but hand-read is not the same as clinician-verified. Scans EVERY
        # corpus file rather than one named one, so a control set added for a new region is
        # covered automatically instead of quietly escaping the gate.
        data_dir = Path(__file__).resolve().parent.parent / "evals" / "data"
        for path in sorted(data_dir.glob("*.jsonl")):
            unverified = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                prov = rec.get("gold_provenance")
                if prov is not None and not prov.get("verified_by"):
                    unverified.append(rec["id"])
            if unverified:
                outstanding.append(
                    f"  * evals/data/{path.name}: records {unverified} have a blank "
                    "gold_provenance.verified_by — the non-circular control's billing labels are "
                    "hand-read, not clinician-verified (CLAUDE.md rule 21b)."
                )

        self.assertEqual(
            outstanding, [],
            "Billing data still needs clinical sign-off before any code reaches a claim:\n"
            + "\n".join(outstanding),
        )

    def test_every_body_part_has_cues_and_an_icd_table(self):
        for part in coding_tables.BODY_PARTS:
            with self.subTest(part=part):
                self.assertIn(part, coding_tables.BODY_PART_CUES)
                self.assertTrue(coding_tables.ICD_BY_BODY_PART.get(part))
                self.assertIn(part, coding_tables.TABLE_PROVENANCE)

    def test_every_body_part_is_identifiable_from_its_own_cues(self):
        """A region whose cues don't select its own table silently disables ICD for every note in
        it — the failure mode that hid for a whole session when "shoulder" didn't match
        "shoulderS"."""
        for part, cues in coding_tables.BODY_PART_CUES.items():
            for cue in cues:
                if cue in coding_tables.SHARED_BODY_PART_CUES:
                    # A shared cue MUST NOT identify a region on its own - that is the whole point
                    # of sharing it. Assert the safe outcome instead: ambiguous, so no table.
                    with self.subTest(part=part, cue=cue, shared=True):
                        self.assertIsNone(
                            coding_tables.body_part_for(f"Patient with {cue} pain."),
                            f"{cue!r} is shared, so alone it must resolve to no region, not one")
                    continue
                with self.subTest(part=part, cue=cue):
                    self.assertEqual(coding_tables.body_part_for(f"Patient with {cue} pain."), part)

    def test_body_part_cues_do_not_collide_across_regions(self):
        """Two regions claiming the same cue makes `body_part_for` tie and return None, which
        disables ICD for both.

        `SHARED_BODY_PART_CUES` is the deliberate exception: a handful of words name a structure
        that more than one joint HAS, so the word genuinely cannot name a joint and must not be
        allowed to decide one. Everything else must stay unique, which is what catches the
        accidental collision - a typo, or a cue copy-pasted between regions.
        """
        seen: dict[str, str] = {}
        for part, cues in coding_tables.BODY_PART_CUES.items():
            for cue in cues:
                if cue in coding_tables.SHARED_BODY_PART_CUES:
                    continue
                with self.subTest(cue=cue):
                    self.assertNotIn(cue, seen,
                                     f"{cue!r} is claimed by both {seen.get(cue)} and {part}")
                    seen[cue] = part

    def test_every_shared_cue_is_actually_claimed_by_more_than_one_region(self):
        """Keeps the exception list honest. A cue listed as shared but present in only one region
        is a stale entry that silently disables the collision check for a word that no longer
        needs it."""
        for cue in coding_tables.SHARED_BODY_PART_CUES:
            owners = [p for p, cues in coding_tables.BODY_PART_CUES.items() if cue in cues]
            with self.subTest(cue=cue):
                self.assertGreater(len(owners), 1,
                                   f"{cue!r} is marked shared but only {owners} claims it")

    def test_every_icd_rule_is_reachable_from_its_own_cues(self):
        """A rule ordered after a more generic one that swallows its cue can never fire. Catches
        the ordering mistake at the point it is made rather than as a silent recall loss."""
        for part, rules in coding_tables.ICD_BY_BODY_PART.items():
            for rule in rules:
                for cue in rule.cues:
                    with self.subTest(part=part, cue=cue):
                        draft = billing.extract(
                            f"Visit for the {part}. Referring diagnosis is {cue}.",
                            body_part=part)
                        self.assertTrue(
                            set(draft.icd_candidates and
                                {c.code for c in draft.icd_candidates}) & set(rule.code_for(None)),
                            f"{part}/{cue!r} did not reach {rule.code_for(None)} — a more generic "
                            "rule ordered before it is swallowing the phrase",
                        )

    def test_non_lateralized_rules_do_not_ask_for_a_side(self):
        """Most lumbar and cervical codes are region-based. Asking the clinician to confirm a side
        ICD-10-CM does not distinguish is noise that trains them to ignore the gap list."""
        draft = billing.extract("Neck visit. Referring diagnosis is cervicalgia.")
        self.assertIn("M54.2", {c.code for c in draft.icd_candidates})
        self.assertFalse(any("Laterality not stated" in m for m in draft.missing))

    def test_lateralized_rules_still_ask_for_a_side(self):
        draft = billing.extract("Knee visit. Referring diagnosis is knee osteoarthritis.")
        self.assertTrue(any("Laterality not stated" in m for m in draft.missing))

    def test_every_intervention_cue_maps_to_a_known_cpt_code(self):
        from app.generate.cpt import _CPT_RULES
        known = {code for _, code, _ in _CPT_RULES}
        for rule in coding_tables.INTERVENTION_CUES:
            with self.subTest(cue=rule.phrase):
                self.assertIn(rule.code, known)
                self.assertIn(rule.strength, ("strong", "weak"))


if __name__ == "__main__":
    unittest.main()


class LongFormSweepRegressionTests(unittest.TestCase):
    """Four defects found by a 288-case sweep (6 regions x 2 note types x 3 complexities x 8),
    once the synthetic dictations became realistic long-form evaluations. None was reachable with
    the short dictations the corpus used before — they only appear in prose a real PT would speak.
    """

    def test_plan_of_treatment_does_not_bill_its_listed_approaches(self):
        """A FOUR-CODE overbill on an evaluation. Same class as record 108's "Interventions
        planned include", different wording, and it fired on every long-form eval."""
        draft = billing.extract(
            "Right shoulder initial evaluation. Referring diagnosis right impingement syndrome. "
            "Plan of treatment, treatment approaches include therapeutic exercise, neuromuscular "
            "re-education, manual therapy for range of motion, and therapeutic activities."
        )
        self.assertEqual(draft.billable, ())
        for code in ("97110", "97112", "97140", "97530"):
            with self.subTest(code=code):
                self.assertEqual(_status(draft, code), PLANNED)

    def test_a_symptom_code_is_suppressed_when_a_real_diagnosis_is_present(self):
        """ICD-10-CM: code the established diagnosis, not its symptoms. A long-form dictation
        names the symptom repeatedly ("Chief complaint, ... shoulder pain", "Assessment summary,
        patient presents with shoulder pain") while the diagnosis is stated once — 152 false
        positives across the sweep, ICD precision 64%."""
        draft = billing.extract(
            "Left shoulder. Referring diagnosis is left adhesive capsulitis. Assessment summary, "
            "patient presents with left shoulder pain and decreased range of motion."
        )
        codes = {c.code for c in draft.icd_candidates}
        self.assertIn("M75.02", codes)
        self.assertNotIn("M25.512", codes, "a duplicate claim line for the symptom")

    def test_a_symptom_code_survives_when_it_is_all_that_was_said(self):
        """The other direction: suppressing it unconditionally would throw away the only honest
        code available when the therapist named no definitive diagnosis."""
        draft = billing.extract("Left shoulder. Referring diagnosis is left shoulder pain.")
        self.assertIn("M25.512", {c.code for c in draft.icd_candidates})

    def test_bilaterally_as_a_findings_qualifier_is_not_the_diagnosis_laterality(self):
        """"grip five out of five bilaterally" was read as the DIAGNOSIS's side. Doubly wrong:
        most families have no bilateral code, so `code_for` returned BOTH sides and emitted two
        false codes for a condition the therapist never lateralised."""
        draft = billing.extract(
            "Low back. Referring diagnosis is sciatic pain. Strength, hip abduction four out of "
            "five bilaterally, Spurling test negative bilaterally."
        )
        codes = {c.code for c in draft.icd_candidates}
        self.assertEqual(codes, {"M54.30"}, "one unspecified-side code, not right AND left")

    def test_a_genuinely_bilateral_diagnosis_still_yields_both_sides(self):
        draft = billing.extract("Shoulder. Referring diagnosis is bilateral adhesive capsulitis.")
        self.assertEqual({c.code for c in draft.icd_candidates}, {"M75.01", "M75.02"})


class GeneratorIntegrityTests(unittest.TestCase):
    def test_every_paraphrase_bank_entry_is_a_tuple_not_a_string(self):
        """A single-element entry written `("capsulitis")` is a STRING, and `rng.choice` on a
        string picks one CHARACTER — the spoken diagnosis became "s" and the gold label became
        "Bilateral s". Six entries were corrupted this way when paraphrases were purged."""
        from evals.synth import banks
        for key, value in banks.DIAGNOSIS_PARAPHRASES.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, tuple, f"{key} lost its trailing comma")
                for phrase in value:
                    self.assertGreater(len(phrase), 2, f"{key} contains a single character")
        for code, value in banks.INTERVENTION_SPOKEN.items():
            with self.subTest(code=code):
                self.assertIsInstance(value, tuple)


class MutualExclusivityAndLateralityScopeTests(unittest.TestCase):
    """Three defects found by re-running the sweep on a freshly re-seeded corpus (a
    GENERATOR_VERSION bump redraws every sample), so they were not artifacts of the seeds the
    earlier fixes had been tuned against.

    All three are WRONG-CLAIM defects — a code on the draft that a coder would have to remove —
    which is the class rule 12 exists to prevent.
    """

    def test_one_condition_stated_twice_at_two_precisions_yields_one_code(self):
        """M48.062 ("with neurogenic claudication") and M48.061 ("without") are mutually
        exclusive: a patient cannot have both, so billing both is a duplicate claim line.

        The per-clause `break` does not cover this. A long dictation states the diagnosis more
        than once at different precision — the full phrase in the referral, the bare phrase in
        the assessment — which is two clauses and so two codes.
        """
        draft = billing.extract(
            "Referring diagnosis lumbar spinal stenosis with neurogenic claudication. "
            "Assessment summary, findings are consistent with spinal stenosis."
        )
        codes = [c.code for c in draft.icd_candidates]
        self.assertEqual(codes, ["M48.062"], "the more specific variant must win, alone")

    def test_lumbago_with_sciatica_supersedes_bare_sciatica(self):
        """Same family mechanism on the other lumbar pair, where the generic cue ("sciatica") is
        a literal substring of the specific one ("lumbago with sciatica")."""
        draft = billing.extract(
            "Referring diagnosis lumbago with sciatica. Assessment, sciatica is the primary driver."
        )
        codes = [c.code for c in draft.icd_candidates]
        self.assertEqual(len(codes), 1, f"expected one sciatica-family code, got {codes}")
        self.assertTrue(codes[0].startswith("M54.4"),
                        f"the specific 'lumbago with sciatica' code must win, got {codes[0]}")

    def test_a_side_far_from_the_diagnosis_does_not_lateralise_it(self):
        """The laterality fallback used to scan the WHOLE transcript. That was defensible at
        35-120 words, where a lone side mention almost certainly was the diagnosis. In a
        ~1,000-word intake a side is stated constantly in places that say nothing about which
        side the DIAGNOSIS is, and the fallback promoted the first one — turning an unspecified
        sciatica (M54.30) into a confident right-sided claim (M54.31).

        Rule 12: an unstated side yields the unspecified code plus a gap flag, never a guess.
        """
        draft = billing.extract(
            "Referring diagnosis sciatica with lumbar involvement. "
            "On examination the right straight leg raise was negative, right grip was intact, "
            "and right ankle dorsiflexion strength was five out of five."
        )
        codes = [c.code for c in draft.icd_candidates if c.code.startswith("M54.3")]
        self.assertEqual(codes, ["M54.30"], "unspecified, not the side mentioned in the exam")

    def test_a_side_stated_beside_the_diagnosis_still_lateralises_it(self):
        """The other half, and the reason the fix is a WINDOW rather than diagnosis-clauses-only.
        A side is very often a bare fragment next to the diagnosis, carrying no diagnosis context
        of its own; scoping to diagnosis clauses alone silently dropped it."""
        draft = billing.extract("Left knee. Diagnosis is degenerative knee.")
        self.assertTrue(draft.icd_candidates, "a diagnosis should still be found")
        self.assertEqual(draft.icd_candidates[0].laterality, "left")


class IntakeGeneratorFidelityTests(unittest.TestCase):
    """The generator must not assert a diagnosis the gold label does not carry.

    `intake.py` hardcoded "patient presents with {part} pain" in the assessment summary — a
    diagnosis-FRAMING clause. For a patient whose diagnosis was stiffness, that put a pain
    diagnosis in the transcript, so the extractor read it correctly and was scored as a false
    positive for doing the right thing. Ten of the corpus's remaining ICD false positives were
    this one generator bug across three regions.

    Rule 21: when the score looks wrong, check the labels before the cue table.
    """

    def test_a_stiffness_diagnosis_never_speaks_a_pain_diagnosis(self):
        from evals.synth import generate as synth

        checked = 0
        for part in ("knee", "hip", "ankle", "shoulder"):
            for cx in ("low", "medium", "high"):
                for s in synth.generate_corpus(body_part=part, note_type="initial",
                                               count=8, complexity=cx, seed=7777):
                    if "stiff" not in s.diagnosis.lower() and "motion" not in s.diagnosis.lower():
                        continue
                    checked += 1
                    got = {c.code for c in billing.extract(s.transcript).icd_candidates}
                    with self.subTest(part=part, said=s.diagnosis):
                        self.assertFalse(got - set(s.icd_codes),
                                         f"extra code(s) {sorted(got - set(s.icd_codes))} "
                                         f"for a stiffness diagnosis")
        self.assertGreater(checked, 0, "no stiffness samples drawn — the guard is not exercising")
