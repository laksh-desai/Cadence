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
        "subacromial", "labrum", "labral", "deltoid",
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
        "gluteus medius", "gluteal", "iliopsoas", "hip flexor", "tha", "greater trochanter",
        "iliotibial", "it band",
    ),
    "ankle": (
        "ankle", "foot", "achilles", "plantar", "calcaneus", "calcaneal", "talus", "talar",
        "peroneal", "tibialis posterior", "metatarsal", "midfoot", "subtalar", "heel",
        "atfl", "gastroc",
    ),
}


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
    CueRule("stretching", "97110", "Therapeutic Exercise", "weak"),
    CueRule("stretches", "97110", "Therapeutic Exercise", "weak"),
    CueRule("range of motion exercises", "97110", "Therapeutic Exercise", "weak"),
    CueRule("rom exercises", "97110", "Therapeutic Exercise", "weak"),
    CueRule("pulleys", "97110", "Therapeutic Exercise", "weak"),
    CueRule("theraband", "97110", "Therapeutic Exercise", "weak"),
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
                  "supraspinatus tendinopathy", "supraspinatus tendinitis"),
            label="Rotator cuff tear or rupture, unspecified, not traumatic",
            right="M75.101", left="M75.102", unspecified="M75.100",
        ),
        IcdRule(
            cues=("adhesive capsulitis", "frozen shoulder"),
            label="Adhesive capsulitis of shoulder",
            right="M75.01", left="M75.02", unspecified="M75.00",
        ),
        IcdRule(
            cues=("impingement syndrome", "shoulder impingement", "subacromial impingement",
                  "impingement of the shoulder"),
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
                  "biceps tendinopathy", "long head of biceps tendinitis"),
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
                  "glenoid labrum tear"),
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
            right="M25.611", left="M25.612", unspecified="M25.619",
        ),
        IcdRule(
            cues=("shoulder pain", "pain in the shoulder", "painful shoulder", "shoulder pain syndrome"),
            label="Pain in shoulder",
            right="M25.511", left="M25.512", unspecified="M25.519",
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
    # "N weeks post <procedure>" is how a post-surgical visit is actually opened. Bounded to a
    # time-unit prefix so the bare word "post" can't fire on "posterior capsule".
    "weeks post", "months post", "years post", "days post", "week post", "month post",
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


def body_part_for(text: str) -> str | None:
    """Best-effort body region for a transcript, or None if it is absent or ambiguous.

    Returns None on a tie rather than picking the higher-scoring region: a wrong table yields a
    confidently-wrong ICD chip, which is worse than no chip at all.
    """
    scores: dict[str, int] = {}
    lowered = (text or "").lower()
    for part, cues in BODY_PART_CUES.items():
        n = sum(len(_phrase_re(c).findall(lowered)) for c in cues)
        if n:
            scores[part] = n
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]
