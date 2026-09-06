"""Body-part-scoped coding tables: the closed data `billing.py` matches the dictation against.

CLAUDE.md rule 12 originally banned ICD-10 outright — "open-ended, no safe deterministic map."
That reasoning holds for ICD-10-CM as a whole (~70k codes), but NOT for a single body region's
outpatient-PT differential, which is a closed set of roughly a dozen codes the therapist names
aloud as the referring or working diagnosis. This module is exactly that narrowing and no wider:
one table per body part, matched only inside a diagnosis-context clause, laterality resolved only
from what was actually said, every candidate returned and none auto-picked.

**This file is deliberately NOT runtime-editable.** Templates are (a clinician can rewrite an
outline in the Templates tab), but a user-editable billing-code table is a liability surface rule
12 doesn't permit — a code table changes what gets submitted to a payer, so it changes only
through a reviewed commit.

**Adding a body part is a data-only change**: one `ICD_BY_BODY_PART` entry, one `BODY_PART_CUES`
entry, one generator phrase bank. Nothing in `billing.py`, `evals/score.py`, `app/ui/server.py`,
or `app.js` changes — the UI picker reads `BODY_PARTS` over the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- provenance -------------------------------------------------------------------
# A stale or unverified ICD code rendered as a confident chip is WORSE than no chip — that is
# precisely the failure rule 12 was written about (the model confidently emitting M25.51, "pain in
# joint, pelvic region and thigh", for an ankle sprain). These tables were assembled from the
# ICD-10-CM tabular list and are the author's best reading, which is NOT a coder's sign-off.
# `tests/test_billing_extract.py` fails while any region is unverified, so it cannot be forgotten.
ICD10CM_YEAR = "2026"


@dataclass(frozen=True)
class TableProvenance:
    """Who verified one body part's ICD table, and when.

    Per body part rather than global so the clinician can sign off the regions the practice
    actually sees first, and unverified regions stay visibly unverified instead of being carried
    by a single global tick.
    """
    icd10cm_year: str = ICD10CM_YEAR
    verified_by: str = ""   # clinician / certified coder initials — REQUIRED before real use
    verified_on: str = ""   # ISO date of that review

    @property
    def verified(self) -> bool:
        return bool(self.verified_by and self.verified_on)


# Body parts this module can code for. Adding one is a data-only change: an entry here, in
# BODY_PART_CUES, in ICD_BY_BODY_PART, and a phrase bank in evals/synth/banks.py. No logic
# anywhere else changes.
BODY_PARTS: tuple[str, ...] = ("shoulder", "knee", "lumbar", "cervical", "hip", "ankle")

TABLE_PROVENANCE: dict[str, TableProvenance] = {part: TableProvenance() for part in BODY_PARTS}


def is_verified(body_part: str) -> bool:
    """True once a clinician or coder has signed off this region's ICD table."""
    prov = TABLE_PROVENANCE.get(body_part)
    return bool(prov and prov.verified)


def unverified_body_parts() -> list[str]:
    return [p for p in BODY_PARTS if not is_verified(p)]

# Words that identify which body region a dictation is about. Used only to SELECT a table — if
# none of these hit (or two body parts tie), billing.py emits no ICD candidates at all rather
# than guessing, per rule 1 "never invent clinical values".
BODY_PART_CUES: dict[str, tuple[str, ...]] = {
    "shoulder": (
        "shoulder", "rotator cuff", "glenohumeral", "gleno-humeral", "scapula", "scapular",
        "supraspinatus", "infraspinatus", "subscapularis", "teres minor", "acromio",
        "subacromial", "deltoid",
        # SLAP = Superior Labrum Anterior-to-Posterior. Unambiguously shoulder, and it carries the
        # region on its own - which is what lets "labral"/"labrum" be shared with hip below.
        "slap repair", "slap lesion", "slap tear",
        # SHARED with hip (see SHARED_BODY_PART_CUES): a labral tear happens at both joints, so the
        # word alone does not name one. Listed under shoulder ONLY, it made every hip labral tear
        # vote shoulder, which routed real hip records to the shoulder table.
        "labrum", "labral",
    ),
    "knee": (
        "knee", "patella", "patellar", "patellofemoral", "meniscus", "meniscal", "acl", "mcl",
        "pcl", "lcl", "quadriceps", "quad", "hamstring", "tibiofemoral", "tka",
        "cruciate", "collateral ligament", "chondromalacia",
    ),
    "lumbar": (
        "lumbar", "low back", "lower back", "lumbosacral", "l4", "l5", "s1", "sacroiliac",
        "si joint", "sciatica", "sciatic", "paraspinal", "erector spinae", "spondylolisthesis",
        "lumbar spine",
    ),
    "cervical": (
        "cervical", "neck", "c5", "c6", "c7", "cervicalgia", "whiplash", "upper trap",
        "cervical spine", "suboccipital", "levator scapulae", "cervicogenic",
    ),
    "hip": (
        "hip", "acetabul", "femoroacetabular", "fai", "trochanter", "trochanteric",
        "labrum", "labral",   # shared with shoulder - see SHARED_BODY_PART_CUES
        "gluteus medius", "gluteal", "iliopsoas", "hip flexor", "tha", "greater trochanter",
        "iliotibial", "it band",
    ),
    "ankle": (
        "ankle", "foot", "achilles", "plantar", "calcaneus", "calcaneal", "talus", "talar",
        "peroneal", "tibialis posterior", "metatarsal", "midfoot", "subtalar", "heel",
        "atfl", "gastroc",
    ),
}


#: Cues that legitimately belong to more than one region, so the uniqueness invariant in
#: `tests/test_billing_extract.py` must not fail them. Keep this set TINY and justified: every
#: entry is a cue that stops discriminating, and the value of the invariant is that an ACCIDENTAL
#: collision (a typo, a copy-paste between regions) still fails loudly.
#:
#: "labral"/"labrum" — a labral tear occurs at the shoulder (SLAP, M75.x/S43.43x) and at the hip
#: (M24.15x). The word names a structure both joints have, so on its own it cannot name a joint.
#: The disambiguating cues are the surrounding anatomy, plus "SLAP" for shoulder specifically.
SHARED_BODY_PART_CUES: frozenset[str] = frozenset({"labrum", "labral"})


def _phrase_re(phrase: str) -> re.Pattern:
    """Compile a cue phrase to a word-boundary regex tolerant of spacing, hyphenation, and plurals.

    Word boundaries are load-bearing, not cosmetic: a naive substring test for the very common
    abbreviation "ther ex" matches inside "oTHER EXercise", which would bill 97110 off a sentence
    that never named therapeutic exercise. `\\b` on both ends rejects that.

    The optional trailing "s" is equally load-bearing in the other direction: without it the body
    part cue "shoulder" fails to match "bilateral shoulderS", which silently disables the entire
    ICD table for any dictation that happens to use the plural.
    """
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", phrase.strip()) if p]
    return re.compile(r"\b" + r"[\s\-]+".join(parts) + r"s?\b", re.IGNORECASE)


@dataclass(frozen=True)
class CueRule:
    """One dictation phrase that names a billable intervention.

    `strength` is the safety dial. "strong" means the phrase IS the service's own name, so a
    clause containing it (unnegated, present-tense) is billable on its own. "weak" means the
    phrase names a TECHNIQUE that usually maps to this code but could legitimately bill under
    another one — surfaced as a candidate for the clinician, never auto-billed. Per the
    precision-over-recall policy: a missed intervention is a safe failure the clinician corrects,
    a wrongly-billed one is an overbill.
    """
    phrase: str
    code: str
    label: str
    strength: str  # "strong" | "weak"

    @property
    def pattern(self) -> re.Pattern:
        return _phrase_re(self.phrase)


# Order matters and mirrors `cpt._CPT_RULES`: specific phrases before generic ones, because a
# clause is attributed to the FIRST rule that hits, so "neuromuscular re-education" must be
# checked before anything that would read it as plain "exercise".
INTERVENTION_CUES: tuple[CueRule, ...] = (
    # --- strong: the service's own name, as a therapist actually says it -------------------
    CueRule("neuromuscular re-education", "97112", "Neuromuscular Re-education", "strong"),
    CueRule("neuromuscular reeducation", "97112", "Neuromuscular Re-education", "strong"),
    CueRule("neuromuscular re-ed", "97112", "Neuromuscular Re-education", "strong"),
    CueRule("neuro re-education", "97112", "Neuromuscular Re-education", "strong"),
    CueRule("neuro re-ed", "97112", "Neuromuscular Re-education", "strong"),
    CueRule("neuro reed", "97112", "Neuromuscular Re-education", "strong"),
    CueRule("nmre", "97112", "Neuromuscular Re-education", "strong"),

    CueRule("gait training", "97116", "Gait Training", "strong"),
    CueRule("gait train", "97116", "Gait Training", "strong"),

    CueRule("therapeutic activities", "97530", "Therapeutic Activities", "strong"),
    CueRule("therapeutic activity", "97530", "Therapeutic Activities", "strong"),
    CueRule("ther act", "97530", "Therapeutic Activities", "strong"),
    CueRule("theraact", "97530", "Therapeutic Activities", "strong"),

    CueRule("therapeutic exercise", "97110", "Therapeutic Exercise", "strong"),
    CueRule("therapeutic exercises", "97110", "Therapeutic Exercise", "strong"),
    CueRule("ther ex", "97110", "Therapeutic Exercise", "strong"),
    CueRule("therex", "97110", "Therapeutic Exercise", "strong"),
    CueRule("theraex", "97110", "Therapeutic Exercise", "strong"),

    # Manual-therapy techniques. Promoted to "strong" deliberately: unlike "stretching" these name
    # a hands-on skilled technique that has no other outpatient-PT code to bill under.
    CueRule("manual therapy", "97140", "Manual Therapy", "strong"),
    CueRule("joint mobilization", "97140", "Manual Therapy", "strong"),
    CueRule("joint mobilizations", "97140", "Manual Therapy", "strong"),
    CueRule("soft tissue mobilization", "97140", "Manual Therapy", "strong"),
    CueRule("myofascial release", "97140", "Manual Therapy", "strong"),
    CueRule("manual stretching", "97140", "Manual Therapy", "strong"),

    CueRule("aquatic therapy", "97113", "Aquatic Therapy", "strong"),
    CueRule("pool therapy", "97113", "Aquatic Therapy", "strong"),

    CueRule("self-care training", "97535", "Self-Care/Home Management Training", "strong"),
    CueRule("self-care", "97535", "Self-Care/Home Management Training", "strong"),
    CueRule("home management training", "97535", "Self-Care/Home Management Training", "strong"),
    CueRule("adl training", "97535", "Self-Care/Home Management Training", "strong"),

    CueRule("wheelchair management", "97542", "Wheelchair Management", "strong"),
    CueRule("orthotic training", "97760", "Orthotic Management/Training", "strong"),
    CueRule("orthotic management", "97760", "Orthotic Management/Training", "strong"),
    CueRule("group therapy", "97150", "Group Therapeutic Procedure", "strong"),

    CueRule("iontophoresis", "97033", "Iontophoresis", "strong"),
    CueRule("ultrasound", "97035", "Ultrasound", "strong"),
    CueRule("massage", "97124", "Massage Therapy", "strong"),

    CueRule("mechanical traction", "97012", "Mechanical Traction", "strong"),
    # MANUAL traction is a hands-on technique billed under manual therapy, not the mechanical
    # traction table. Listed before the bare "traction" weak cue below so the longer, earlier span
    # wins overlap suppression — otherwise "manual traction" would bill 97012, which is wrong.
    CueRule("manual traction", "97140", "Manual Therapy", "strong"),
    CueRule("electrical stimulation", "97014", "Electrical Stimulation", "strong"),
    CueRule("e-stim", "97014", "Electrical Stimulation", "strong"),
    CueRule("estim", "97014", "Electrical Stimulation", "strong"),
    CueRule("nmes", "97014", "Electrical Stimulation", "strong"),
    CueRule("tens unit", "97014", "Electrical Stimulation", "strong"),
    CueRule("vasopneumatic", "97016", "Vasopneumatic Device", "strong"),
    CueRule("paraffin", "97018", "Paraffin Bath", "strong"),
    CueRule("whirlpool", "97022", "Whirlpool", "strong"),
    CueRule("diathermy", "97024", "Diathermy", "strong"),
    CueRule("hot pack", "97010", "Hot/Cold Packs", "strong"),
    CueRule("hot packs", "97010", "Hot/Cold Packs", "strong"),
    CueRule("cold pack", "97010", "Hot/Cold Packs", "strong"),
    CueRule("cold packs", "97010", "Hot/Cold Packs", "strong"),
    CueRule("ice pack", "97010", "Hot/Cold Packs", "strong"),
    CueRule("moist heat", "97010", "Hot/Cold Packs", "strong"),

    # --- weak: a technique that USUALLY maps here but could bill elsewhere ------------------
    # Surfaced as a candidate only. "stretching" may be ther ex (patient-performed) or manual
    # therapy (therapist-performed); "balance work" may be neuro re-ed or therapeutic activities.
    # Auto-billing either would be a coin flip on a claim.
    CueRule("balance training", "97112", "Neuromuscular Re-education", "weak"),
    CueRule("balance work", "97112", "Neuromuscular Re-education", "weak"),
    CueRule("balance exercises", "97112", "Neuromuscular Re-education", "weak"),
    CueRule("proprioceptive training", "97112", "Neuromuscular Re-education", "weak"),
    CueRule("proprioception", "97112", "Neuromuscular Re-education", "weak"),
    CueRule("postural training", "97112", "Neuromuscular Re-education", "weak"),
    CueRule("scapular stabilization", "97110", "Therapeutic Exercise", "weak"),
    CueRule("strengthening", "97110", "Therapeutic Exercise", "weak"),
    # Loose phrasings a therapist genuinely uses for a service, admitted at WEAK strength after
    # the all-body-part eval showed they were the single largest source of missed interventions
    # (and therefore of under-counted units). Weak, not strong, is the deliberate answer to
    # CLAUDE.md rule 21(a): "hands-on work" usually means manual therapy but can describe manual
    # cueing during exercise, and "functional activities" straddles 97530 and 97110. Surfacing
    # them as a candidate the clinician confirms is strictly better than silence; auto-billing
    # them would be a coin flip on a claim.
    CueRule("strength work", "97110", "Therapeutic Exercise", "weak"),
    CueRule("strengthening work", "97110", "Therapeutic Exercise", "weak"),
    CueRule("hands-on work", "97140", "Manual Therapy", "weak"),
    CueRule("hands on work", "97140", "Manual Therapy", "weak"),
    CueRule("manual work", "97140", "Manual Therapy", "weak"),
    CueRule("functional activities", "97530", "Therapeutic Activities", "weak"),
    CueRule("functional training", "97530", "Therapeutic Activities", "weak"),
    CueRule("functional work", "97530", "Therapeutic Activities", "weak"),
    CueRule("stretching", "97110", "Therapeutic Exercise", "weak"),
    CueRule("stretches", "97110", "Therapeutic Exercise", "weak"),
    CueRule("range of motion exercises", "97110", "Therapeutic Exercise", "weak"),
    CueRule("rom exercises", "97110", "Therapeutic Exercise", "weak"),
    CueRule("pulleys", "97110", "Therapeutic Exercise", "weak"),
    CueRule("theraband", "97110", "Therapeutic Exercise", "weak"),
    # Bare "traction" is how a spine dictation usually says it, but it is genuinely ambiguous
    # between MECHANICAL traction (97012, a service-based modality) and MANUAL traction (97140, a
    # timed hands-on technique) — and those two bill completely differently, so guessing would be
    # a coin flip on the unit count as well as the code. Weak, and disambiguated by the explicit
    # "manual traction" / "mechanical traction" rules above when the therapist says which.
    CueRule("traction", "97012", "Mechanical Traction", "weak"),
)


# --- status scoping ---------------------------------------------------------------
# These are what stop the dictation scan from becoming rule 12's misfire. Each list answers a
# different "the therapist said the words but did not bill it today" case. Matched WITHIN one
# clause only; see billing.split_clauses.

# Negation trigger appearing BEFORE the cue in the same clause ("we did not do gait training").
NEGATION_CUES: tuple[str, ...] = (
    "no", "not", "didn't", "did not", "does not", "doesn't", "without", "deferred",
    "declined", "unable to", "wasn't able", "was not able", "couldn't", "could not",
    "held", "held off", "skipped", "omitted", "avoided", "contraindicated", "no longer",
    "wasn't", "was not", "instead of", "rather than", "canceled", "cancelled",
)

# The service happened, but at a PRIOR visit — billing it today is an overbill.
TEMPORAL_PRIOR_CUES: tuple[str, ...] = (
    "last visit", "last session", "last time", "previous visit", "previous session",
    "prior visit", "prior session", "previously", "at the last", "on the last",
    "had been doing", "we had done", "in the past", "last week we", "earlier visits",
    "up until now", "so far we", "historically",
)

# The service is PLANNED, not performed.
#
# The bare "planned" / "plan includes" forms were added after the hand-written control set caught
# a four-code overbill on record 108: "Interventions planned include therapeutic exercise,
# neuromuscular re-education, manual therapy, and therapeutic activities" billed all four as
# performed, because every future cue here was a VERB form ("plan to", "will add") and the note
# used a NOUN form. The synthetic corpus could not have found this — its generator only ever
# rendered the verb frames it was given.
TEMPORAL_FUTURE_CUES: tuple[str, ...] = (
    "next visit", "next session", "next time", "will add", "we'll add", "will begin",
    "we'll begin", "will start", "we'll start", "plan to", "plan is to", "planning to",
    "going to add", "going to start", "intend to", "upcoming", "at the next",
    "future sessions", "moving forward we", "eventually", "would like to add",
    "planned", "interventions planned", "plan includes", "plan of care includes",
    "will include", "anticipated", "we recommend", "recommend starting",
    # The PLAN-OF-TREATMENT family, found by the long-form initial-eval corpus: "Plan of treatment,
    # treatment approaches include therapeutic exercise, neuromuscular re-education, manual
    # therapy..." billed FOUR codes on an evaluation where nothing was performed. Same class as
    # record 108's "Interventions planned include", different wording.
    #
    # Expanding THIS list is the safe direction. A future cue can only move a treatment OUT of the
    # billable set, so a false positive here under-bills (the clinician adds it back from a visible
    # flag) while a false negative over-bills. Precision on the billable set is what matters.
    "plan of treatment", "treatment approaches", "approaches include", "treatment will include",
    "interventions include", "plan of care", "treatment plan includes", "proposed treatment",
    "anticipate", "goals include",
    # The DELIBERATION family, found by the hand-written long-form control (evals/data/
    # longform_intake.txt): "I considered functional electrical stimulation for the left
    # dorsiflexors but I want to check with the surgeon first" billed 97014 as performed. The
    # therapist had ALSO said "I did not do any electrical stimulation" one sentence earlier —
    # the negation was detected and then discarded, because `_dedupe` keeps the most billable
    # mention of a code. Contemplating a treatment is not performing it, and every phrase here
    # says "not today" in the plainest possible terms.
    "considered", "considering", "thinking about", "thought about", "may add", "might add",
    "could add", "would consider", "pending", "awaiting", "on hold", "once cleared",
    "if cleared", "when cleared", "discussed adding", "talked about adding",
)

# The patient does it at home — unsupervised, so not a billable treatment minute.
HOME_PROGRAM_CUES: tuple[str, ...] = (
    "home program", "home exercise program", "home exercise", "hep", "at home",
    "for home", "given for home", "home routine", "independently at home",
)

# Words that pull the scope back to the present visit, cancelling a prior/future/home marker
# earlier in the same clause. Without these, "last visit we did manual therapy, today ther ex
# twenty minutes" attributes BOTH treatments to the prior visit and silently bills nothing.
# Deliberately NOT clause splitters: splitting on "today" would orphan the duration in
# "gait training today for fifteen minutes".
SCOPE_RESET_CUES: tuple[str, ...] = (
    "today", "this visit", "this session", "this time", "now", "currently",
    "at this visit", "in today's session", "current visit",
)

# A spoken self-correction: the value AFTER the cue supersedes the one before it (rule 8).
CORRECTION_CUES: tuple[str, ...] = (
    "sorry", "i mean", "i meant", "correction", "scratch that", "strike that",
    "let me correct", "no wait", "wait no", "rather", "make that", "excuse me",
)


# --- evaluation complexity (97161/97162/97163) --------------------------------------
#
# CAPTURE ONLY, never inference. Rule 12 keeps complexity out of the auto-assigned set because
# choosing a level is a clinician judgment -- and that stays true. What was wrong is that Cadence
# asked for the level on EVERY evaluation even when the therapist had already said it out loud
# ("clinical decision making is moderate complexity"), which is not caution, it is discarding a
# stated fact and then demanding it back. Rule 12(b) already settled the principle for CPT:
# scanning the DICTATION for a stated billing fact is permitted where scanning the NOTE is not.
# Recording the clinician's own judgment is not making one for them.
#
# Every phrase requires the noun "complexity" or a literal code. "complex" alone is deliberately
# absent -- it appears inside "complex regional pain syndrome", and matching that would attach an
# evaluation code to a diagnosis.
EVAL_COMPLEXITY_CUES: tuple[tuple[str, str, str], ...] = (
    # A code the therapist dictated is the most explicit form there is; capturing it is required
    # (the model still never authors one).
    ("97161", "97161", "PT evaluation, low complexity"),
    ("97162", "97162", "PT evaluation, moderate complexity"),
    ("97163", "97163", "PT evaluation, high complexity"),
    ("low complexity", "97161", "PT evaluation, low complexity"),
    ("complexity is low", "97161", "PT evaluation, low complexity"),
    ("moderate complexity", "97162", "PT evaluation, moderate complexity"),
    ("complexity is moderate", "97162", "PT evaluation, moderate complexity"),
    ("high complexity", "97163", "PT evaluation, high complexity"),
    ("complexity is high", "97163", "PT evaluation, high complexity"),
    ("highly complex evaluation", "97163", "PT evaluation, high complexity"),
)

#: The evaluation codes, so callers can recognise one without hard-coding the numbers.
EVAL_CPT_CODES: frozenset[str] = frozenset({"97161", "97162", "97163"})


# --- ICD-10 ------------------------------------------------------------------------

@dataclass(frozen=True)
class IcdRule:
    """One diagnosis in a body part's closed differential, with its laterality variants.

    `bilateral` is `None` for most M75/M25 families because ICD-10-CM provides no bilateral code
    for them — the correct coding is BOTH sides, which `billing.detect_icd` emits as two separate
    candidates rather than silently picking one.

    `caution` carries a coding judgment the table cannot make (a 7th-character encounter type, a
    companion code) straight through to the clinician's confirm step.
    """
    cues: tuple[str, ...]
    label: str            # human label without laterality, for the chip
    right: str
    left: str
    unspecified: str
    bilateral: str | None = None
    caution: str = ""
    #: Rules sharing a non-empty family are MUTUALLY EXCLUSIVE variants of one condition — they
    #: describe the same thing at different specificity, so at most one can be true and billing
    #: two is a duplicate claim line. `billing.detect_icd` keeps only the first match within a
    #: family, and rules are ordered specific-before-generic, so the more specific one wins.
    #:
    #: The per-clause `break` alone does not cover this: a long dictation states the diagnosis
    #: more than once at different precision ("lumbar spinal stenosis with neurogenic
    #: claudication" in the referral, plain "spinal stenosis" in the assessment), which is two
    #: clauses and so two codes — here M48.062 AND M48.061, "with" and "without" claudication
    #: simultaneously.
    family: str = ""
    #: True for a rule that codes a SYMPTOM (pain, stiffness) rather than a definitive diagnosis.
    #: ICD-10-CM guidance is to code the established diagnosis and NOT its symptoms; billing
    #: "M25.511 pain in right shoulder" alongside "M75.41 impingement" is a duplicate claim line.
    #: `billing.detect_icd` therefore suppresses these whenever a specific diagnosis was also
    #: found for the same region — but keeps them when the symptom is all the therapist said,
    #: because then it is the only honest code available.
    symptom_only: bool = False

    @property
    def lateralized(self) -> bool:
        """False when ICD-10-CM gives this condition ONE code regardless of side.

        Whole regions work this way — most lumbar and cervical codes are region-based (M54.5 low
        back pain, M54.2 cervicalgia), as are some peripheral ones (M72.2 plantar fasciitis). For
        those, asking the clinician to "confirm right or left" is noise about a distinction the
        code set does not make, so `billing._missing_for` suppresses the laterality gap.
        """
        return not (self.right == self.left == self.unspecified)

    def code_for(self, laterality: str | None) -> tuple[str, ...]:
        """Codes for a stated laterality. Bilateral with no bilateral code -> both sides."""
        if not self.lateralized:
            return (self.unspecified,)
        if laterality == "right":
            return (self.right,)
        if laterality == "left":
            return (self.left,)
        if laterality == "bilateral":
            return (self.bilateral,) if self.bilateral else (self.right, self.left)
        return (self.unspecified,)


# Shoulder differential seen in outpatient PT. Ordered specific-before-generic: a complete tear
# must be checked before the generic "rotator cuff tear" family, and both before plain
# "shoulder pain", which is the fallback anyone's dictation could trip.
ICD_BY_BODY_PART: dict[str, tuple[IcdRule, ...]] = {
    "shoulder": (
        IcdRule(
            cues=("complete rotator cuff tear", "full thickness tear", "full-thickness tear",
                  "complete tear of the rotator cuff"),
            label="Complete rotator cuff tear or rupture, not traumatic",
            right="M75.121", left="M75.122", unspecified="M75.120",
        ),
        IcdRule(
            cues=("incomplete rotator cuff tear", "partial thickness tear", "partial-thickness tear",
                  "partial tear of the rotator cuff", "partial rotator cuff tear"),
            label="Incomplete rotator cuff tear or rupture, not traumatic",
            right="M75.111", left="M75.112", unspecified="M75.110",
        ),
        IcdRule(
            cues=("rotator cuff tendinopathy", "rotator cuff tendinitis", "rotator cuff tendonitis",
                  "rotator cuff syndrome", "rotator cuff tear", "rotator cuff strain",
                  "supraspinatus tendinopathy", "supraspinatus tendinitis",
                  "torn rotator cuff", "cuff tear", "rct"),
            label="Rotator cuff tear or rupture, unspecified, not traumatic",
            right="M75.101", left="M75.102", unspecified="M75.100",
        ),
        IcdRule(
            cues=("adhesive capsulitis", "frozen shoulder",
                  "capsulitis"),
            label="Adhesive capsulitis of shoulder",
            right="M75.01", left="M75.02", unspecified="M75.00",
        ),
        IcdRule(
            cues=("impingement syndrome", "shoulder impingement", "subacromial impingement",
                  "impingement of the shoulder",
                  "impingement", "subacromial pain syndrome"),
            label="Impingement syndrome of shoulder",
            right="M75.41", left="M75.42", unspecified="M75.40",
        ),
        IcdRule(
            cues=("calcific tendinitis", "calcific tendinopathy", "calcific tendonitis"),
            label="Calcific tendinitis of shoulder",
            right="M75.31", left="M75.32", unspecified="M75.30",
        ),
        IcdRule(
            cues=("bicipital tendinitis", "biceps tendinitis", "bicipital tendinopathy",
                  "biceps tendinopathy", "long head of biceps tendinitis",
                  "long head biceps tendinopathy", "biceps tendonosis"),
            label="Bicipital tendinitis",
            right="M75.21", left="M75.22", unspecified="M75.20",
        ),
        IcdRule(
            cues=("subacromial bursitis", "shoulder bursitis", "bursitis of the shoulder", "bursitis"),
            label="Bursitis of shoulder",
            right="M75.51", left="M75.52", unspecified="M75.50",
        ),
        IcdRule(
            cues=("slap tear", "slap lesion", "labral tear", "superior labral tear",
                  "glenoid labrum tear",
                  "superior labrum tear", "labral pathology"),
            label="Superior glenoid labrum lesion",
            right="S43.431", left="S43.432", unspecified="S43.439",
            caution="needs a 7th character (A initial / D subsequent / S sequela) — confirm the "
                    "encounter type",
        ),
        IcdRule(
            cues=("rotator cuff capsule sprain", "shoulder sprain", "sprain of the shoulder",
                  "glenohumeral sprain"),
            label="Sprain of rotator cuff capsule",
            right="S43.421", left="S43.422", unspecified="S43.429",
            caution="needs a 7th character (A initial / D subsequent / S sequela) — a PT follow-up "
                    "is usually 'D'; confirm the encounter type",
        ),
        IcdRule(
            cues=("primary osteoarthritis of the shoulder", "shoulder osteoarthritis",
                  "glenohumeral osteoarthritis", "shoulder arthritis", "shoulder oa"),
            label="Primary osteoarthritis, shoulder",
            right="M19.011", left="M19.012", unspecified="M19.019",
        ),
        IcdRule(
            cues=("total shoulder arthroplasty", "reverse total shoulder", "shoulder replacement",
                  "shoulder arthroplasty", "tsa", "rtsa"),
            label="Aftercare following joint replacement surgery",
            right="Z47.1", left="Z47.1", unspecified="Z47.1",
            bilateral="Z47.1",
            caution="also code the joint prosthesis (Z96.611 right / Z96.612 left) — confirm both",
        ),
        IcdRule(
            cues=("shoulder stiffness", "stiffness of the shoulder", "loss of shoulder motion"),
            label="Stiffness of shoulder, not elsewhere classified",
            right="M25.611", left="M25.612", unspecified="M25.619", symptom_only=True,
        ),
        IcdRule(
            cues=("shoulder pain", "pain in the shoulder", "painful shoulder", "shoulder pain syndrome"),
            label="Pain in shoulder",
            right="M25.511", left="M25.512", unspecified="M25.519", symptom_only=True,
        ),
    ),

    # --- knee ------------------------------------------------------------------------
    "knee": (
        IcdRule(
            cues=("anterior cruciate ligament tear", "acl tear", "acl rupture", "acl sprain",
                  "torn acl", "cruciate ligament tear",
                  "blown acl", "anterior cruciate rupture", "acl deficiency"),
            label="Sprain of anterior cruciate ligament of knee",
            right="S83.511", left="S83.512", unspecified="S83.519",
            caution="needs a 7th character (A initial / D subsequent / S sequela) — a PT follow-up "
                    "is usually 'D'; confirm the encounter type",
        ),
        IcdRule(
            cues=("medial collateral ligament sprain", "mcl sprain", "mcl tear", "torn mcl"),
            label="Sprain of medial collateral ligament of knee",
            right="S83.411", left="S83.412", unspecified="S83.419",
            caution="needs a 7th character (A / D / S) — confirm the encounter type",
        ),
        IcdRule(
            cues=("medial meniscus tear", "meniscal tear", "meniscus tear", "torn meniscus",
                  "lateral meniscus tear",
                  "meniscal injury"),
            label="Derangement of meniscus due to old tear or injury",
            right="M23.221", left="M23.222", unspecified="M23.209",
            caution="M23.2- is for an OLD tear; a current acute injury is S83.2- with a 7th "
                    "character, and the specific horn/meniscus changes the code — confirm",
        ),
        IcdRule(
            cues=("total knee arthroplasty", "total knee replacement", "knee replacement", "tka",
                  "knee arthroplasty"),
            label="Aftercare following joint replacement surgery",
            right="Z47.1", left="Z47.1", unspecified="Z47.1", bilateral="Z47.1",
            caution="also code the joint prosthesis (Z96.651 right / Z96.652 left) — confirm both",
        ),
        IcdRule(
            cues=("chondromalacia patellae", "chondromalacia"),
            label="Chondromalacia patellae",
            right="M22.41", left="M22.42", unspecified="M22.40",
        ),
        IcdRule(
            cues=("patellofemoral pain syndrome", "patellofemoral pain", "patellofemoral syndrome",
                  "patellofemoral disorder", "runner's knee",
                  "pfps"),
            label="Patellofemoral disorders",
            right="M22.2X1", left="M22.2X2", unspecified="M22.2X9",
        ),
        IcdRule(
            cues=("patellar tendinitis", "patellar tendinopathy", "patellar tendonitis",
                  "jumper's knee",
                  "patellar tendinosis"),
            label="Patellar tendinitis",
            right="M76.51", left="M76.52", unspecified="M76.50",
        ),
        IcdRule(
            cues=("primary osteoarthritis of the knee", "knee osteoarthritis", "knee oa",
                  "osteoarthritis of the knee", "degenerative joint disease of the knee",
                  "knee arthritis",
                  "degenerative knee", "wear and tear in the knee",
                  "tricompartmental oa"),
            label="Unilateral primary osteoarthritis, knee",
            right="M17.11", left="M17.12", unspecified="M17.10", bilateral="M17.0",
        ),
        IcdRule(
            cues=("knee effusion", "effusion of the knee"),
            label="Effusion, knee",
            right="M25.461", left="M25.462", unspecified="M25.469",
        ),
        IcdRule(
            cues=("knee stiffness", "stiffness of the knee", "loss of knee motion",
                  "arthrofibrosis of the knee"),
            label="Stiffness of knee, not elsewhere classified",
            right="M25.661", left="M25.662", unspecified="M25.669", symptom_only=True,
        ),
        IcdRule(
            cues=("knee pain", "pain in the knee", "painful knee"),
            label="Pain in knee",
            right="M25.561", left="M25.562", unspecified="M25.569", symptom_only=True,
        ),
    ),

    # --- lumbar spine ----------------------------------------------------------------
    # Most lumbar codes are REGION-based, not side-based: `lateralized` is False for those (right
    # == left == unspecified), so no laterality gap is raised for a distinction ICD-10-CM doesn't
    # make. Sciatica and lumbago-with-sciatica are the exceptions and do carry a side.
    "lumbar": (
        IcdRule(
            cues=("lumbar spinal stenosis with neurogenic claudication",
                  "stenosis with neurogenic claudication"),
            label="Spinal stenosis, lumbar region, with neurogenic claudication",
            right="M48.062", left="M48.062", unspecified="M48.062", family="lumbar_stenosis",
        ),
        IcdRule(
            cues=("lumbar spinal stenosis", "spinal stenosis", "lumbar stenosis",
                  "canal stenosis", "central stenosis", "narrowing of the canal"),
            label="Spinal stenosis, lumbar region, without neurogenic claudication",
            right="M48.061", left="M48.061", unspecified="M48.061", family="lumbar_stenosis",
        ),
        IcdRule(
            cues=("lumbar radiculopathy", "disc disorder with radiculopathy",
                  "herniated disc with radiculopathy", "radiculopathy"),
            label="Intervertebral disc disorders with radiculopathy, lumbar region",
            right="M51.16", left="M51.16", unspecified="M51.16",
        ),
        IcdRule(
            cues=("lumbago with sciatica", "low back pain with sciatica",
                  "back pain with sciatica"),
            label="Lumbago with sciatica",
            right="M54.41", left="M54.42", unspecified="M54.40", family="sciatica",
        ),
        IcdRule(
            cues=("sciatica",
                  "sciatic pain"),
            label="Sciatica",
            right="M54.31", left="M54.32", unspecified="M54.30", family="sciatica",
        ),
        IcdRule(
            cues=("herniated disc", "disc herniation", "disc displacement",
                  "herniated nucleus pulposus", "bulging disc",
                  "slipped disc", "disc bulge", "hnp"),
            label="Other intervertebral disc displacement, lumbar region",
            right="M51.26", left="M51.26", unspecified="M51.26",
        ),
        IcdRule(
            cues=("degenerative disc disease", "disc degeneration", "ddd",
                  "degenerative discs", "disc disease", "worn discs"),
            label="Other intervertebral disc degeneration, lumbar region",
            right="M51.36", left="M51.36", unspecified="M51.36",
        ),
        IcdRule(
            cues=("spondylolisthesis",),
            label="Spondylolisthesis, lumbar region",
            right="M43.16", left="M43.16", unspecified="M43.16",
        ),
        IcdRule(
            cues=("lumbar sprain", "lumbar strain", "low back strain", "lumbosacral sprain",
                  "back strain"),
            label="Sprain of ligaments of lumbar spine",
            right="S33.5XX", left="S33.5XX", unspecified="S33.5XX",
            caution="needs a 7th character (A / D / S) — confirm the encounter type",
        ),
        IcdRule(
            cues=("segmental dysfunction", "somatic dysfunction"),
            label="Segmental and somatic dysfunction of lumbar region",
            right="M99.03", left="M99.03", unspecified="M99.03",
        ),
        IcdRule(
            cues=("low back pain", "lower back pain", "lumbago", "lumbar pain",
                  "pain in the low back",
                  "lbp", "back pain", "mechanical back pain"),
            label="Low back pain, unspecified",
            right="M54.50", left="M54.50", unspecified="M54.50", symptom_only=True,
            caution="M54.51 (vertebrogenic) and M54.59 (other) are more specific if the "
                    "presentation supports them — confirm",
        ),
    ),

    # --- cervical spine --------------------------------------------------------------
    "cervical": (
        IcdRule(
            cues=("cervical radiculopathy", "disc disorder with radiculopathy",
                  "radiculopathy",
                  "pinched nerve in the neck", "nerve root irritation"),
            label="Cervical disc disorder with radiculopathy, unspecified cervical region",
            right="M50.10", left="M50.10", unspecified="M50.10",
            caution="the specific cervical level changes the code (M50.11-/M50.12-/M50.13-) — confirm",
        ),
        IcdRule(
            cues=("cervical spinal stenosis", "cervical stenosis", "spinal stenosis"),
            label="Spinal stenosis, cervical region",
            right="M48.02", left="M48.02", unspecified="M48.02",
        ),
        IcdRule(
            cues=("cervical disc degeneration", "degenerative disc disease", "disc degeneration"),
            label="Other cervical disc degeneration, unspecified cervical region",
            right="M50.30", left="M50.30", unspecified="M50.30",
        ),
        IcdRule(
            cues=("cervical disc herniation", "herniated disc", "disc displacement",
                  "disc herniation",
                  "slipped disc in the neck", "disc bulge in the neck"),
            label="Other cervical disc displacement, unspecified cervical region",
            right="M50.20", left="M50.20", unspecified="M50.20",
        ),
        IcdRule(
            cues=("whiplash", "cervical sprain", "neck sprain", "cervical strain", "neck strain",
                  "wad", "flexion extension injury"),
            label="Sprain of ligaments of cervical spine",
            right="S13.4XX", left="S13.4XX", unspecified="S13.4XX",
            caution="needs a 7th character (A / D / S) — confirm the encounter type",
        ),
        IcdRule(
            cues=("cervicobrachial syndrome",),
            label="Cervicobrachial syndrome",
            right="M53.1", left="M53.1", unspecified="M53.1",
        ),
        IcdRule(
            cues=("cervicogenic headache",
                  "headaches coming from the neck", "neck related headache"),
            label="Cervicogenic headache",
            right="G44.86", left="G44.86", unspecified="G44.86",
        ),
        IcdRule(
            cues=("segmental dysfunction", "somatic dysfunction"),
            label="Segmental and somatic dysfunction of cervical region",
            right="M99.01", left="M99.01", unspecified="M99.01",
        ),
        IcdRule(
            cues=("cervicalgia", "neck pain", "pain in the neck",
                  "neck ache"),
            label="Cervicalgia",
            right="M54.2", left="M54.2", unspecified="M54.2", symptom_only=True,
        ),
    ),

    # --- hip ---------------------------------------------------------------------------
    "hip": (
        IcdRule(
            cues=("total hip arthroplasty", "total hip replacement", "hip replacement", "tha",
                  "hip arthroplasty"),
            label="Aftercare following joint replacement surgery",
            right="Z47.1", left="Z47.1", unspecified="Z47.1", bilateral="Z47.1",
            caution="also code the joint prosthesis (Z96.641 right / Z96.642 left) — confirm both",
        ),
        IcdRule(
            cues=("trochanteric bursitis", "greater trochanteric pain syndrome", "hip bursitis",
                  "gtps"),
            label="Trochanteric bursitis",
            right="M70.61", left="M70.62", unspecified="M70.60",
        ),
        IcdRule(
            cues=("iliotibial band syndrome", "it band syndrome", "itb syndrome",
                  "itb friction syndrome"),
            label="Iliotibial band syndrome",
            right="M76.31", left="M76.32", unspecified="M76.30",
        ),
        IcdRule(
            cues=("hip labral tear", "acetabular labral tear", "labral tear",
                  "torn labrum in the hip", "acetabular labrum injury"),
            label="Other articular cartilage disorders, hip",
            right="M24.151", left="M24.152", unspecified="M24.159",
        ),
        IcdRule(
            cues=("femoroacetabular impingement", "fai", "hip impingement",
                  "cam impingement", "pincer impingement"),
            label="Other specified joint derangements, hip",
            right="M24.851", left="M24.852", unspecified="M24.859",
        ),
        IcdRule(
            cues=("primary osteoarthritis of the hip", "hip osteoarthritis", "hip oa",
                  "osteoarthritis of the hip", "hip arthritis",
                  "degenerative hip", "arthritic hip", "worn hip"),
            label="Unilateral primary osteoarthritis, hip",
            right="M16.11", left="M16.12", unspecified="M16.10", bilateral="M16.0",
        ),
        IcdRule(
            cues=("hip stiffness", "stiffness of the hip"),
            label="Stiffness of hip, not elsewhere classified",
            right="M25.651", left="M25.652", unspecified="M25.659", symptom_only=True,
        ),
        IcdRule(
            cues=("hip pain", "pain in the hip", "painful hip"),
            label="Pain in hip",
            right="M25.551", left="M25.552", unspecified="M25.559", symptom_only=True,
        ),
    ),

    # --- ankle / foot ------------------------------------------------------------------
    "ankle": (
        IcdRule(
            cues=("achilles tendinitis", "achilles tendinopathy", "achilles tendonitis",
                  "achilles tendinosis", "tendinopathy of the achilles"),
            label="Achilles tendinitis",
            right="M76.61", left="M76.62", unspecified="M76.60",
        ),
        IcdRule(
            cues=("achilles rupture", "achilles tendon rupture", "ruptured achilles"),
            label="Strain of Achilles tendon",
            right="S86.011", left="S86.012", unspecified="S86.019",
            caution="needs a 7th character (A / D / S) — confirm the encounter type",
        ),
        IcdRule(
            # Plantar fasciitis has ONE code regardless of side — lateralized is False here.
            cues=("plantar fasciitis", "plantar fasciopathy", "plantar fascial fibromatosis"),
            label="Plantar fascial fibromatosis",
            right="M72.2", left="M72.2", unspecified="M72.2",
        ),
        IcdRule(
            cues=("lateral ankle sprain", "calcaneofibular ligament sprain", "atfl sprain"),
            label="Sprain of calcaneofibular ligament of ankle",
            right="S93.421", left="S93.422", unspecified="S93.429",
            caution="needs a 7th character (A / D / S) — confirm the encounter type",
        ),
        IcdRule(
            cues=("ankle sprain", "sprained ankle", "sprain of the ankle",
                  "rolled ankle", "inversion injury"),
            label="Sprain of unspecified ligament of ankle",
            right="S93.401", left="S93.402", unspecified="S93.409",
            caution="needs a 7th character (A / D / S) — confirm the encounter type; a named "
                    "ligament is more specific (S93.41-/S93.42-/S93.43-)",
        ),
        IcdRule(
            cues=("posterior tibial tendon dysfunction", "tibialis posterior tendinopathy",
                  "posterior tibialis tendinitis",
                  "pttd", "post tib dysfunction"),
            label="Other synovitis and tenosynovitis, ankle and foot",
            right="M65.871", left="M65.872", unspecified="M65.879",
        ),
        IcdRule(
            cues=("osteoarthritis of the ankle", "ankle osteoarthritis", "ankle oa",
                  "ankle arthritis",
                  "degenerative ankle", "arthritic ankle"),
            label="Primary osteoarthritis, ankle and foot",
            right="M19.071", left="M19.072", unspecified="M19.079",
        ),
        IcdRule(
            cues=("ankle stiffness", "stiffness of the ankle", "loss of ankle motion"),
            label="Stiffness of ankle, not elsewhere classified",
            right="M25.671", left="M25.672", unspecified="M25.679", symptom_only=True,
        ),
        IcdRule(
            cues=("ankle pain", "pain in the ankle", "foot pain", "painful ankle"),
            label="Pain in ankle and joints of foot",
            right="M25.571", left="M25.572", unspecified="M25.579", symptom_only=True,
        ),
    ),
}

# An ICD candidate is only taken from a clause that FRAMES something as the diagnosis. Without
# this, "she's worried about a rotator cuff tear" and "her sister had a frozen shoulder" both
# yield a billable diagnosis, which is the open-ended inference rule 12 forbids.
ICD_CONTEXT_CUES: tuple[str, ...] = (
    "diagnosis", "diagnoses", "diagnosed", "dx", "referred", "referral", "referring",
    "assessment", "impression", "consistent with", "presents with", "presenting with",
    "evaluation for", "eval for", "status post", "s/p", "post-op", "post op", "postoperative",
    "working diagnosis", "known", "medical diagnosis", "pt diagnosis", "treating",
    # "N weeks post <procedure>" / "N weeks out from <procedure>" is how a post-surgical visit is
    # actually opened. Bounded to a time-unit prefix so the bare words "post" and "out" can't fire
    # on "posterior capsule" or "walked out". The "out from" family was added after the knee
    # control record (201) showed "she's four weeks out from a right total knee replacement"
    # yielding no diagnosis at all.
    "weeks post", "months post", "years post", "days post", "week post", "month post",
    "weeks out", "months out", "days out", "week out", "month out",
)

# ...and never from a clause that hedges it as a worry, a rule-out, someone else's problem, or a
# condition from the PAST rather than the one being treated today.
#
# "history of" moved here from ICD_CONTEXT_CUES after the hand-written control caught a false
# positive on record 108: the run-on clause "History of present illness, he had increasing left
# shoulder pain for about four years, was diagnosed with rotator cuff arthropathy, ..." yielded
# M25.512 (pain in left shoulder) for a four-year-old symptom that is not the billable diagnosis
# for this visit. A history clause naming a past condition must never produce a billing code.
ICD_HEDGE_CUES: tuple[str, ...] = (
    "worried about", "worries about", "worried she", "concerned about", "concern for",
    "afraid of", "anxious about", "ruling out", "rule out", "r/o", "question of",
    "wondering if", "wonders if", "family history", "her sister", "her mother", "his brother",
    "his father", "denies", "no evidence of", "negative for", "does not have",
    "history of", "history of present illness", "past medical history", "medical history",
    "surgical history", "years ago", "previously diagnosed",
)

# Laterality, taken only from what was said. An unstated side yields the "unspecified" variant
# PLUS a gap flag — never a guessed side, because a right/left error is a claim denial at best.
LATERALITY_CUES: tuple[tuple[str, str], ...] = (
    ("bilateral", "bilateral"),
    ("bilaterally", "bilateral"),
    ("both shoulders", "bilateral"),
    ("right", "right"),
    ("left", "left"),
)


def _score_parts(text: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    lowered = (text or "").lower()
    for part, cues in BODY_PART_CUES.items():
        n = sum(len(_phrase_re(c).findall(lowered)) for c in cues)
        if n:
            scores[part] = n
    return scores


def _winner(scores: dict[str, int]) -> str | None:
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def body_part_for(text: str, diagnosis_text: str = "") -> str | None:
    """Best-effort body region for a transcript, or None if it is absent or ambiguous.

    Returns None on a tie rather than picking the higher-scoring region: a wrong table yields a
    confidently-wrong ICD chip, which is worse than no chip at all. That safety rule is unchanged;
    what changed is WHERE the vote is counted.

    Counting every mention in the whole transcript lets incidental anatomy outvote the diagnosis.
    A lumbar patient's note names "hip flexor stretch" and "hamstring" in the exercise list and
    "knee" in an exam finding, none of which say anything about which region is being DIAGNOSED —
    and those mentions tied the real region often enough to return None and suppress the ICD table
    entirely. Measured on the corpus: three lumbar records with a perfectly good cue in a
    diagnosis-framing clause ("Assessment is mechanical back pain", "Treating diagnosis is
    sciatica", "referred with a diagnosis of lumbar stenosis") extracted NOTHING, because
    hip 2 / lumbar 2 is a tie.

    So the diagnosis clauses break the TIE, and never overrule a clear transcript-wide result.
    That ordering is load-bearing, and the first version had it backwards. Letting the diagnosis
    clause decide outright routed three hip records to the SHOULDER table: "labral tear" is a cue
    for both regions, and read alone it is genuinely ambiguous, where the full transcript said hip
    unmistakably. It traded 3 confidently-wrong ICD claims for the recall — the exact trade this
    function's None-on-tie rule exists to refuse.

    As a tiebreaker it is strictly additive: every case that already resolved still resolves the
    same way, and the only behaviour that changes is a tie, which previously yielded nothing at all.
    """
    return _winner(_score_parts(text)) or _winner(_score_parts(diagnosis_text))
