"""Deterministic billing draft from the DICTATION: interventions, ICD-10, minutes, and units.

Where `cpt.suggest_codes` maps the generated NOTE's section headings to codes, this module works
from the therapist's own words, before the model touches them. That buys three things the
heading-based path can't give: a diagnosis (headings never carry one), per-intervention minutes as
SPOKEN rather than as the model rewrote them, and a second opinion that `reconcile()` checks the
note against — a code in one and not the other is either a rule-15 omission or a rule-14
fabrication, and both are worth the clinician's eye.

**Why scanning the dictation is allowed where scanning the note is not.** CLAUDE.md rule 12 warns
against body-scanning the note's prose for interventions, because a passing mention in an
unrelated section misfires. The dictation carries the same shape of risk through different failure
modes — negation, prior visits, plans, home program, self-correction — so it is guarded in four
layers, every one of them testable:

  1. CLAUSE SCOPING. Matching, negation and temporal scoping all happen inside a single clause.
     There is no whole-transcript substring test anywhere in this file.
  2. CUE STRENGTH TIERS. Only a "strong" cue — the service's own name — reaches `performed` on its
     own. A "weak" cue (a technique that could legitimately bill elsewhere) becomes `uncertain`.
  3. A STATUS ENUM, NEVER A BOOLEAN. Excluded hits stay in the output WITH their reason, so a
     wrong exclusion is visible to the clinician instead of silently missing — the same
     "flag, never delete" philosophy as postprocess.py.
  4. `confirm_required=True`, hard-coded. No caller can flip it; a test asserts it on every path.

The policy behind the tuning, stated so it isn't quietly reversed later: a MISSED intervention is
a safe failure — the clinician adds it. A LEAKED negated or prior-visit intervention is an
OVERBILL. Tune toward precision, and measure the leak rate (`evals/score.py:distractor_leaks`).

Nothing here decides anything. Every line is a draft the clinician confirms, edits, or deletes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.generate import coding_tables as tables
from app.generate.cpt import is_timed
from app.generate.traceability import normalize_for_matching

# --- intervention status ----------------------------------------------------------
PERFORMED = "performed"
NEGATED = "negated"
PRIOR_VISIT = "prior_visit"
PLANNED = "planned"
HOME_PROGRAM = "home_program"
UNCERTAIN = "uncertain"

#: Only this status contributes minutes to the billable total. Everything else is retained in the
#: draft with its reason so the clinician can see what was excluded and why.
BILLABLE_STATUS = PERFORMED

#: Statuses that both assert the treatment HAPPENED TODAY — it is only the code that is in doubt
#: for `uncertain`. Minutes may be carried between these two; they must never be carried from
#: `planned`, `prior_visit`, `negated`, or `home_program`, which assert the opposite.
TODAY_STATUSES = frozenset({PERFORMED, UNCERTAIN})

# --- how minutes were arrived at --------------------------------------------------
EXPLICIT = "explicit"                      # "twenty minutes of ther ex"
FRACTION = "fraction"                      # "a third of the session", with a stated session total
BARE_NUMBER = "bare_number_inferred"       # "manual therapy fifteen" — weakest, see the guard below
NOT_STATED = "not_stated"
FRACTION_UNRESOLVED = "fraction_unresolved"  # a fraction with no session total to apply it to

# --- unit-allocation methods ------------------------------------------------------
CMS_SUBSTITUTION = "cms_substitution"
AMA_RULE_OF_EIGHTS = "ama_rule_of_eights"


# ==================================================================================
# The 8-minute rule
# ==================================================================================

#: The literal Medicare table. `units_for_minutes` is a closed form of exactly this; the test
#: suite walks 0..200 against the table so the arithmetic can never silently drift from the rule.
UNIT_TABLE: tuple[tuple[int, int, int], ...] = (
    (0, 7, 0), (8, 22, 1), (23, 37, 2), (38, 52, 3), (53, 67, 4), (68, 82, 5),
)


def units_for_minutes(minutes: int) -> int:
    """Billable units for a total of timed treatment minutes (Medicare 8-minute rule).

    0-7 -> 0, 8-22 -> 1, 23-37 -> 2, 38-52 -> 3, 53-67 -> 4, 68-82 -> 5, and one more unit per
    additional 15 minutes beyond that. Every band is 15 minutes wide and opens 7 minutes before
    its multiple of 15, which is what `(minutes + 7) // 15` encodes; the leading guard is needed
    only because the first band is truncated at zero rather than opening at -7.
    """
    if minutes is None or minutes < 8:
        return 0
    return (minutes + 7) // 15


@dataclass(frozen=True)
class UnitAllocation:
    """Units under ONE named method, with the arithmetic that produced them."""
    method: str
    total_timed_minutes: int
    total_units: int
    per_code: tuple[tuple[str, int], ...]
    ambiguous: bool = False
    note: str = ""


def allocate_units(per_code_minutes: dict[str, int], *, method: str) -> UnitAllocation:
    """Distribute units across codes under `method`.

    Two real, incompatible rules exist and payers do not agree on which applies, so this function
    never gets called once — `extract()` runs it under both and shows the disagreement:

      * CMS SUBSTITUTION sums every timed minute, converts the TOTAL to units, then splits them.
      * The AMA RULE OF EIGHTS gives each code its own independent 8-minute threshold.

    They diverge on exactly the sessions a therapist actually has: 97110 for 8 minutes plus 97140
    for 8 minutes is 1 unit under CMS and 2 under the AMA. Emitting a single number would be
    picking the biller's side of a payer-specific question rule 12 explicitly leaves to them.
    """
    minutes = {c: int(m) for c, m in (per_code_minutes or {}).items() if m}
    total = sum(minutes.values())

    if method == AMA_RULE_OF_EIGHTS:
        per = tuple(sorted((c, units_for_minutes(m)) for c, m in minutes.items()))
        return UnitAllocation(
            method=method,
            total_timed_minutes=total,
            total_units=sum(u for _, u in per),
            per_code=per,
            note="Each code billed against its own 8-minute threshold (AMA rule of eights).",
        )

    total_units = units_for_minutes(total)
    base = {c: m // 15 for c, m in minutes.items()}
    leftover = total_units - sum(base.values())

    # Leftover units go to the largest remainders. Ties are broken by code ascending purely so the
    # output is deterministic — that is a presentation choice, not a billing judgment, so a tie is
    # also reported as `ambiguous` rather than silently resolved.
    remainders = sorted(
        ((m % 15, c) for c, m in minutes.items()), key=lambda rc: (-rc[0], rc[1])
    )
    ambiguous = False
    if leftover > 0 and remainders:
        contested = remainders[:leftover]
        cutoff = contested[-1][0]
        tied = [c for r, c in remainders if r == cutoff]
        if len(tied) > len([c for r, c in contested if r == cutoff]):
            ambiguous = True
        for _, code in contested:
            base[code] = base.get(code, 0) + 1

    note = "Total timed minutes converted to units, then split by largest remainder (CMS)."
    if ambiguous:
        note += (
            " Two or more codes tie for the last unit — the split shown is one valid reading; "
            "the biller decides which code carries it."
        )
    return UnitAllocation(
        method=CMS_SUBSTITUTION,
        total_timed_minutes=total,
        total_units=total_units,
        per_code=tuple(sorted(base.items())),
        ambiguous=ambiguous,
        note=note,
    )


# ==================================================================================
# Clause scoping
# ==================================================================================

# Sentence punctuation, plus the connectives that reset scope in spoken dictation. Without the
# connectives, "we did not do gait training and then manual therapy for fifteen" would put a
# negation and a performed treatment in one clause and suppress the wrong one.
#
# "next" is deliberately NOT a splitter, even though it reads like one. Splitting on it consumes
# the "next visit" / "next time" prefix of TEMPORAL_FUTURE_CUES, so a planned treatment loses its
# marker and gets billed as performed — the exact overbill this module exists to prevent. A
# missed clause break is a cosmetic loss; a destroyed future marker is a claim.
_CLAUSE_SPLIT_RE = re.compile(
    r"[.!?;\n]+"
    r"|,?\s+(?:and then|then|after that|afterwards|afterward|also|"
    r"but|however|followed by|whereas|meanwhile)\b",
    re.IGNORECASE,
)

#: How many words may sit between a negation trigger and the cue it negates. Kept tight (NegEx
#: uses a similar span) because "no" and "not" are extremely common in clinical speech.
_NEGATION_WINDOW_WORDS = 6


def split_clauses(text: str) -> list[str]:
    """Split raw dictation into scope-bounded clauses.

    Deliberately operates on the RAW text, before `normalize_for_matching`, which lowercases and
    collapses all whitespace (traceability.py) and would destroy the newlines that separate
    dictated list items.
    """
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(text or "") if c and c.strip()]


def _find_any(clause: str, phrases) -> re.Match | None:
    """First whole-word match of any phrase in `phrases`, or None."""
    best: re.Match | None = None
    for p in phrases:
        m = tables._phrase_re(p).search(clause)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


def _scoped_marker(clause: str, cue_start: int, cue_end: int, phrases) -> bool:
    """True if a prior/future/home marker governs the cue at `cue_start`.

    Looks before the cue, and also just after it, because a therapist says both "last visit,
    manual therapy" and "manual therapy last visit". A `SCOPE_RESET_CUES` word between the marker
    and the cue cancels it — that is what keeps "last visit we did manual therapy, today ther ex"
    from attributing the ther ex to the prior visit too.
    """
    for phrase in phrases:
        rx = tables._phrase_re(phrase)
        for m in rx.finditer(clause[:cue_start]):
            if not _find_any(clause[m.end():cue_start], tables.SCOPE_RESET_CUES):
                return True
        tail = clause[cue_end:cue_end + 25]
        m = rx.search(tail)
        if m and not _find_any(tail[:m.start()], tables.SCOPE_RESET_CUES):
            return True
    return False


def _negated_before(clause: str, cue_start: int) -> bool:
    """True if a negation trigger governs the cue at `cue_start`.

    Two guards keep the very common bare "no"/"not" from over-firing: the trigger must be within
    `_NEGATION_WINDOW_WORDS` words of the cue, and no comma may intervene. A comma ends the
    negation's scope in speech — "no pain today, we did ther ex" negates the pain, not the ther ex.
    """
    for phrase in tables.NEGATION_CUES:
        for m in tables._phrase_re(phrase).finditer(clause[:cue_start]):
            between = clause[m.end():cue_start]
            if "," in between:
                continue
            if len(between.split()) <= _NEGATION_WINDOW_WORDS:
                return True
    return False


# ==================================================================================
# Minutes
# ==================================================================================

_MINUTES_RE = re.compile(r"\b(\d{1,3})\s*(?:minutes?|mins?|min)\b", re.IGNORECASE)

# Matched on the RAW clause, not the normalized one: normalize_for_matching turns "one third" into
# "1 third", so a fraction pattern written against spoken words would miss half its cases.
_FRACTION_RE = re.compile(
    r"\b(two thirds|three quarters|a third|one third|a quarter|one quarter|a half|one half|half)"
    r"\s+of\s+(?:the\s+)?(?:session|visit|treatment)\b",
    re.IGNORECASE,
)
_FRACTION_VALUES = {
    "a third": 1 / 3, "one third": 1 / 3, "two thirds": 2 / 3,
    "a quarter": 1 / 4, "one quarter": 1 / 4, "three quarters": 3 / 4,
    "a half": 1 / 2, "one half": 1 / 2, "half": 1 / 2,
}

# The whole session's length, for resolving a fraction. Searched across the transcript because a
# therapist states it once ("this was a forty-five minute session") and then speaks in fractions.
_SESSION_TOTAL_RES = (
    re.compile(r"\b(\d{2,3})\s*(?:minute|min)\s*(?:session|visit|treatment)\b", re.IGNORECASE),
    re.compile(r"\bsession\s+(?:was|lasted|ran|is)\s*(?:about\s+)?(\d{2,3})\s*(?:minutes?|mins?)\b",
               re.IGNORECASE),
    re.compile(r"\btotal\s+(?:treatment\s+)?time\s*(?:was|of|is)?\s*(\d{2,3})\s*(?:minutes?|mins?)\b",
               re.IGNORECASE),
)

# A bare number sitting next to any of these is a measurement, a dosage, or a rep scheme — not a
# duration. This guard is what makes `bare_number_inferred` survivable at all; see the note on
# _NUM_RUN_RE below.
_BARE_TRAILING_UNIT_RE = re.compile(
    r"^\s*(?:degrees?|reps?|repetitions?|sets?|times|x\b|lbs?|pounds?|kilograms?|kgs?|"
    r"feet|foot|ft|yards?|meters?|metres?|weeks?|days?|months?|years?|%|percent|"
    r"mg|milligrams?|ml|mcg|grams?|/\s*\d)",
    re.IGNORECASE,
)
_BARE_LEADING_UNIT_RE = re.compile(
    r"(?:\bx|\bsets? of|\breps? of|\bby|\bgrade|\blevel|\bstep|\bweek|\bvisit|#)\s*$",
    re.IGNORECASE,
)
_BARE_MIN, _BARE_MAX = 3, 90

# A standalone integer: not part of a fraction, range, decimal, or grade. Borrowed from
# `traceability._contains_number`, and load-bearing for the same reason — without the lookaround,
# a normalized pain rating "4/10" offers up "10" and an MMT grade "3+/5" offers up "3", either of
# which would become fabricated treatment minutes.
_BARE_NUMBER_RE = re.compile(r"(?<![\d./+-])(\d{1,3})(?![\d./+-])")


def session_total_minutes(transcript: str) -> int | None:
    """The stated whole-session length, or None. Never inferred — a fraction with no stated total
    stays unresolved and is reported as a gap rather than multiplied against a guess."""
    norm = normalize_for_matching(transcript)
    for rx in _SESSION_TOTAL_RES:
        m = rx.search(norm)
        if m:
            return int(m.group(1))
    return None


def _bare_number_candidates(norm_clause: str, consumed: list[tuple[int, int]]) -> list[re.Match]:
    """Bare integers in a clause that could plausibly be a duration.

    The dangerous interaction to know about: `normalize_for_matching`'s `_NUM_RUN_RE` converts
    EVERY spoken number word, so "one of the exercises" arrives here as "1 of the exercises" and
    "she has three kids" as "3 kids". The 3-90 range, the leading/trailing unit guards, and the
    caller's single-cue-per-clause requirement are jointly what keep this from inventing minutes.
    """
    out = []
    for m in _BARE_NUMBER_RE.finditer(norm_clause):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        value = int(m.group(1))
        if not (_BARE_MIN <= value <= _BARE_MAX):
            continue
        if _BARE_TRAILING_UNIT_RE.match(norm_clause[m.end():]):
            continue
        if _BARE_LEADING_UNIT_RE.search(norm_clause[:m.start()]):
            continue
        out.append(m)
    return out


# ==================================================================================
# Records
# ==================================================================================

@dataclass(frozen=True)
class InterventionHit:
    """One billable-intervention mention, kept whether or not it is billable.

    `clause` is the evidence the clinician reads to adjudicate the line — it is the whole point of
    retaining excluded hits rather than dropping them.
    """
    code: str
    label: str
    timed: bool
    cue: str
    cue_strength: str
    clause: str
    status: str
    minutes: int | None = None
    minutes_basis: str = NOT_STATED

    @property
    def billable(self) -> bool:
        return self.status == BILLABLE_STATUS


@dataclass(frozen=True)
class IcdCandidate:
    """A diagnosis candidate. Candidates are never ranked or auto-picked — the clinician selects."""
    code: str
    label: str
    cue: str
    clause: str
    laterality: str | None = None
    laterality_stated: bool = False
    caution: str = ""
    #: False when ICD-10-CM gives this condition one code regardless of side (most lumbar and
    #: cervical codes, plantar fasciitis, …). Asking the clinician to confirm a side the code set
    #: doesn't distinguish is noise, so the laterality gap is suppressed for these.
    lateralized: bool = True
    #: True for a SYMPTOM code (pain, stiffness) rather than a definitive diagnosis. Suppressed by
    #: detect_icd when a specific diagnosis was also found for the region.
    symptom_only: bool = False


@dataclass(frozen=True)
class Conflict:
    """A disagreement between what the dictation said and what the note ended up containing."""
    kind: str       # "dictation_only" | "note_only" | "minutes_mismatch"
    severity: str   # "high" (code-level) | "low" (minutes, read out of model-written prose)
    code: str
    detail: str


@dataclass(frozen=True)
class BillingDraft:
    body_part: str | None = None
    interventions: tuple[InterventionHit, ...] = ()
    icd_candidates: tuple[IcdCandidate, ...] = ()
    total_timed_minutes: int = 0
    untimed_codes: tuple[str, ...] = ()
    units: UnitAllocation | None = None
    units_alt: UnitAllocation | None = None
    #: Units if the clinician confirmed every `uncertain` timed line as well. Computed HERE rather
    #: than in the browser so the 8-minute rule lives in exactly one place — the same reason the
    #: timed-code set was moved out of app.js. It answers the question the clinician actually has
    #: ("what do I get if I accept these?") without either side reimplementing the arithmetic.
    units_if_confirmed: UnitAllocation | None = None
    missing: tuple[str, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    #: Hard-coded, never a constructor argument any caller varies, and asserted by the test suite.
    #: Cadence drafts billing; the clinician bills. This field is the machine-readable form of
    #: that boundary.
    confirm_required: bool = True

    @property
    def billable(self) -> tuple[InterventionHit, ...]:
        return tuple(h for h in self.interventions if h.billable)

    @property
    def method_disagreement(self) -> bool:
        return bool(self.units and self.units_alt
                    and self.units.total_units != self.units_alt.total_units)


# ==================================================================================
# Detection
# ==================================================================================

def _status_for(clause: str, cue_start: int, cue_end: int, strength: str) -> str:
    """Decide a cue's status from its clause. Order is precedence, most-disqualifying first."""
    if _negated_before(clause, cue_start):
        return NEGATED
    if _scoped_marker(clause, cue_start, cue_end, tables.TEMPORAL_PRIOR_CUES):
        return PRIOR_VISIT
    if _scoped_marker(clause, cue_start, cue_end, tables.TEMPORAL_FUTURE_CUES):
        return PLANNED
    if _scoped_marker(clause, cue_start, cue_end, tables.HOME_PROGRAM_CUES):
        return HOME_PROGRAM
    # A weak cue names a technique, not a service — it never bills on its own authority.
    if strength != "strong":
        return UNCERTAIN
    return PERFORMED


def _cue_matches(clause: str) -> list[tuple[re.Match, tables.CueRule]]:
    """Every intervention cue in a clause, with overlapping matches suppressed.

    Suppression is what makes specific-beats-generic work without an explicit precedence pass:
    "manual stretching" and "stretching" both match the same text, so the longer, earlier span
    wins and the generic one is dropped — the same outcome as `cpt._CPT_RULES` ordering, but
    robust to a clause containing several distinct interventions.
    """
    found: list[tuple[re.Match, tables.CueRule]] = []
    for rule in tables.INTERVENTION_CUES:
        for m in rule.pattern.finditer(clause):
            found.append((m, rule))
    found.sort(key=lambda mr: (mr[0].start(), -(mr[0].end() - mr[0].start())))
    kept: list[tuple[re.Match, tables.CueRule]] = []
    for m, rule in found:
        if any(m.start() < km.end() and km.start() < m.end() for km, _ in kept):
            continue
        kept.append((m, rule))
    return kept


def detect_interventions(clauses: list[str], *, session_total: int | None = None
                         ) -> list[InterventionHit]:
    """Find every billable-intervention mention across clauses, with status and minutes.

    Returns one hit per MENTION, not per code — `_dedupe` collapses repeats later, so a caller
    that wants the raw evidence (the eval harness, a test) can still see every occurrence.
    """
    hits: list[InterventionHit] = []
    for clause in clauses:
        matches = _cue_matches(clause)
        if not matches:
            continue

        # A spoken self-correction supersedes what came before it (rule 8). The superseded cue is
        # marked `uncertain` rather than deleted — silently dropping half of "gait training,
        # sorry, therapeutic activities" would hide the therapist's own ambiguity.
        #
        # This deliberately does NOT require a second recognized cue in the clause. Requiring one
        # was a real leak, found by the eval harness on synthetic record 1021: in "joint
        # mobilization, I mean strength work" the corrected-TO phrase is not in the cue table, so
        # only one cue matched, the correction check was skipped, and the RETRACTED treatment got
        # billed. Whether we recognize the replacement is irrelevant — the therapist withdrew what
        # came before the marker, so it must not bill. The cost is a false negative when
        # "sorry" appears for an unrelated reason, which is the safe direction.
        correction = _find_any(clause, tables.CORRECTION_CUES)
        correction_at = correction.start() if correction else None

        minutes_by_index = _minutes_for_clause(clause, matches, session_total)
        for i, (m, rule) in enumerate(matches):
            status = (UNCERTAIN if correction_at is not None and m.start() < correction_at
                      else _status_for(clause, m.start(), m.end(), rule.strength))
            mins, basis = minutes_by_index.get(i, (None, NOT_STATED))
            hits.append(InterventionHit(
                code=rule.code, label=rule.label, timed=is_timed(rule.code),
                cue=m.group(0), cue_strength=rule.strength, clause=clause,
                status=status, minutes=mins, minutes_basis=basis,
            ))
    return hits


def _minutes_for_clause(clause: str, matches: list[tuple[re.Match, tables.CueRule]],
                        session_total: int | None = None) -> dict[int, tuple[int | None, str]]:
    """Assign a duration to each cue in one clause.

    Assignment is greedy by proximity and one-to-one: a "20 minutes" is claimed by the nearest
    unclaimed cue, so "manual therapy 15 minutes and ther ex 20 minutes" splits correctly instead
    of giving both cues the same number.
    """
    norm = normalize_for_matching(clause)
    out: dict[int, tuple[int | None, str]] = {}

    # Cue positions in the NORMALIZED clause. Cue phrases contain no number words, so the
    # normalizer cannot alter them; a cue that still fails to re-locate is simply left unassigned.
    positions: dict[int, tuple[int, int]] = {}
    for i, (_, rule) in enumerate(matches):
        nm = rule.pattern.search(norm)
        if nm:
            positions[i] = (nm.start(), nm.end())

    minute_matches = list(_MINUTES_RE.finditer(norm))
    pairs = []
    for mi, mm in enumerate(minute_matches):
        for i, (cs, ce) in positions.items():
            gap = mm.start() - ce if mm.start() >= ce else cs - mm.end()
            if 0 <= gap <= 45:
                pairs.append((gap, mi, i))
    pairs.sort()
    used_min: set[int] = set()
    for gap, mi, i in pairs:
        if mi in used_min or i in out:
            continue
        used_min.add(mi)
        out[i] = (int(minute_matches[mi].group(1)), EXPLICIT)

    # A fraction of the session, applied only when the session length was actually stated.
    frac = _FRACTION_RE.search(clause)
    if frac and len(matches) == 1 and 0 not in out:
        share = _FRACTION_VALUES.get(frac.group(1).lower())
        if share and session_total:
            out[0] = (int(round(session_total * share)), FRACTION)
        else:
            out[0] = (None, FRACTION_UNRESOLVED)

    # Last resort: a bare number, and only in a clause naming exactly ONE intervention, so there
    # is no question which cue it would attach to.
    if len(matches) == 1 and 0 not in out:
        consumed = [(m.start(), m.end()) for m in minute_matches]
        consumed += [positions[i] for i in positions]
        bare = _bare_number_candidates(norm, consumed)
        if len(bare) == 1:
            out[0] = (int(bare[0].group(1)), BARE_NUMBER)

    return out


def _laterality_in(text: str) -> tuple[str | None, bool]:
    """Laterality stated in `text`, if any. Returns (side, stated)."""
    best: tuple[int, str] | None = None
    for phrase, side in tables.LATERALITY_CUES:
        m = tables._phrase_re(phrase).search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), side)
    return (best[1], True) if best else (None, False)


def detect_icd(clauses: list[str], body_part: str | None, *, transcript: str = ""
               ) -> list[IcdCandidate]:
    """Diagnosis candidates from clauses that FRAME something as the diagnosis.

    The context requirement is the whole safety story here. Without it, "she's worried about a
    rotator cuff tear" and "her sister had a frozen shoulder" both yield a billable diagnosis —
    the open-ended inference rule 12 forbids. A clause must name a diagnosis context and must not
    hedge it.
    """
    rules = tables.ICD_BY_BODY_PART.get(body_part or "", ())
    if not rules:
        return []

    # A side stated once anywhere in the transcript, used only when the diagnosis clause itself
    # doesn't state one AND the transcript is unambiguous about which side it is.
    #
    # "bilateral" is deliberately EXCLUDED from this fallback. `_phrase_re` matches "bilaterally",
    # which is ubiquitous as a FINDINGS qualifier ("grip five out of five bilaterally", "Spurling
    # negative bilaterally") and almost never describes the diagnosis. Reading it as the
    # diagnosis's side was doubly wrong: most families have no bilateral code, so `code_for`
    # returned BOTH sides and emitted two false codes for a condition the therapist never
    # lateralised. A genuinely bilateral diagnosis is stated in the diagnosis clause itself
    # ("bilateral adhesive capsulitis"), which `_laterality_in` still picks up.
    sides = {side for phrase, side in tables.LATERALITY_CUES
             if side != "bilateral" and tables._phrase_re(phrase).search(transcript or "")}
    fallback_side = next(iter(sides)) if len(sides) == 1 else None

    out: list[IcdCandidate] = []
    seen: set[str] = set()
    for clause in clauses:
        if not _find_any(clause, tables.ICD_CONTEXT_CUES):
            continue
        if _find_any(clause, tables.ICD_HEDGE_CUES):
            continue
        for rule in rules:
            hit = _find_any(clause, rule.cues)
            if not hit:
                continue
            side, stated = _laterality_in(clause)
            if not stated and fallback_side:
                side, stated = fallback_side, True
            for code in rule.code_for(side):
                if code in seen:
                    continue
                seen.add(code)
                out.append(IcdCandidate(
                    code=code, label=rule.label, cue=hit.group(0), clause=clause,
                    laterality=side, laterality_stated=stated, caution=rule.caution,
                    lateralized=rule.lateralized, symptom_only=rule.symptom_only,
                ))
            break  # one diagnosis per clause; specific rules are ordered before generic ones

    # ICD-10-CM: code the established diagnosis, not its symptoms. A long-form dictation names the
    # symptom repeatedly ("Chief complaint, ... knee pain", "Assessment summary, patient presents
    # with knee pain and decreased range of motion") while the DIAGNOSIS is stated once, so without
    # this a generic pain code rode along on nearly every eval — 152 false positives across a
    # 288-case sweep, ICD precision 64%. The symptom code is kept only when it is all the therapist
    # gave, because then it is the one honest code available.
    if any(not c.symptom_only for c in out):
        out = [c for c in out if not c.symptom_only]
    return out


# ==================================================================================
# Assembly
# ==================================================================================

def extract(transcript: str, *, body_part: str | None = None) -> BillingDraft:
    """Build the full billing draft from a raw dictation. Never fabricates a value."""
    text = transcript or ""
    part = body_part or tables.body_part_for(text)
    clauses = split_clauses(text)
    session_total = session_total_minutes(text)

    hits = _dedupe(detect_interventions(clauses, session_total=session_total))
    icd = detect_icd(clauses, part, transcript=text)

    billable = [h for h in hits if h.billable]
    per_code: dict[str, int] = {}
    for h in billable:
        if h.timed and h.minutes:
            per_code[h.code] = per_code.get(h.code, 0) + h.minutes
    total = sum(per_code.values())
    untimed = tuple(sorted({h.code for h in billable if not h.timed}))

    # What the total becomes if the clinician also accepts the `uncertain` lines — the ones where
    # a duration WAS found but the phrase wasn't definite enough to bill a code on its own
    # authority. Measured separately by `evals/score.py:exact_if_confirmed`, because judging the
    # unit math against gold that assumes every intervention bills would otherwise penalize the
    # weak-cue policy rather than the arithmetic.
    pending = dict(per_code)
    for h in hits:
        if h.status == UNCERTAIN and h.timed and h.minutes:
            pending[h.code] = pending.get(h.code, 0) + h.minutes

    return BillingDraft(
        body_part=part,
        interventions=tuple(hits),
        icd_candidates=tuple(icd),
        total_timed_minutes=total,
        untimed_codes=untimed,
        units=allocate_units(per_code, method=CMS_SUBSTITUTION),
        units_alt=allocate_units(per_code, method=AMA_RULE_OF_EIGHTS),
        units_if_confirmed=(allocate_units(pending, method=CMS_SUBSTITUTION)
                            if pending != per_code else None),
        missing=_missing_for(part, hits, icd, session_total),
    )


def _dedupe(hits: list[InterventionHit]) -> list[InterventionHit]:
    """Collapse repeat mentions of one code, keeping the most billable one.

    A therapist naming the same treatment twice ("ther ex twenty minutes ... more ther ex at the
    end") must not double-bill, and a `performed` mention must not be shadowed by a later
    `planned` one. Minutes are summed only across mentions that each stated their own duration.
    """
    order = {PERFORMED: 0, UNCERTAIN: 1, HOME_PROGRAM: 2, PLANNED: 3, PRIOR_VISIT: 4, NEGATED: 5}
    by_code: dict[str, InterventionHit] = {}
    for h in hits:
        cur = by_code.get(h.code)
        if cur is None:
            by_code[h.code] = h
        elif order[h.status] < order[cur.status]:
            # A better status wins. Minutes carry across ONLY between statuses that both assert
            # the treatment happened today, and only to FILL a blank — never to add. Borrowing a
            # planned or prior-visit duration would invent a billable value out of a non-billable
            # one; filling a blank from an `uncertain` mention of the same code cannot over-count,
            # because nothing is summed.
            #
            # Found by the all-region eval on synthetic record 2021: "strength work, eight
            # minutes" (weak cue -> uncertain) followed by "electrical stimulation, I mean ther ex"
            # (strong cue -> performed, no minutes) silently dropped the 8 minutes on the floor.
            carry = (h.minutes is None and cur.minutes is not None
                     and h.status in TODAY_STATUSES and cur.status in TODAY_STATUSES)
            by_code[h.code] = (replace(h, minutes=cur.minutes, minutes_basis=cur.minutes_basis)
                               if carry else h)
        elif h.status == cur.status and h.minutes:
            # Same status, both stated: the therapist split one treatment across the session
            # ("ther ex twenty minutes ... more ther ex, ten minutes at the end").
            by_code[h.code] = (replace(cur, minutes=cur.minutes + h.minutes) if cur.minutes
                               else replace(cur, minutes=h.minutes, minutes_basis=h.minutes_basis))
    return list(by_code.values())


def _missing_for(part, hits, icd, session_total) -> tuple[str, ...]:
    """Gaps the clinician must fill. Every one of these is a value we refused to invent."""
    missing: list[str] = []
    if part is None:
        missing.append("Body region not identified in the dictation — no ICD-10 suggested.")
    elif not icd:
        missing.append(
            "No diagnosis stated as a diagnosis — ICD-10 not suggested; clinician to assign."
        )
    for c in icd:
        if c.lateralized and not c.laterality_stated:
            missing.append(
                f"Laterality not stated for {c.label} — {c.code} is the unspecified-side code; "
                "confirm right or left."
            )
        if c.caution:
            missing.append(f"{c.code}: {c.caution}.")
    for h in hits:
        if not h.billable or not h.timed:
            continue
        if h.minutes is None:
            if h.minutes_basis == FRACTION_UNRESOLVED:
                missing.append(
                    f"{h.code} {h.label} was given as a fraction of the session but no session "
                    "length was stated — minutes not calculated."
                )
            else:
                missing.append(f"Minutes not stated for {h.code} {h.label} — required for units.")
        elif h.minutes_basis == BARE_NUMBER:
            missing.append(
                f"Minutes for {h.code} {h.label} were read from a bare number "
                f"(\"{h.minutes}\") — verify this is a duration."
            )
    uncertain = [h for h in hits if h.status == UNCERTAIN]
    if uncertain:
        missing.append(
            "Possible interventions named without a billable service name: "
            + ", ".join(sorted({f"{h.cue} (→ {h.code}?)" for h in uncertain}))
            + " — confirm or discard."
        )
    return tuple(missing)


# ==================================================================================
# Reconcile against the generated note
# ==================================================================================

_CPT_MARKER_RE = re.compile(r"\[\[CPT:\s*([0-9A-Z]{5})\b")
_SECTION_MINUTES_RE = re.compile(r"\bMinutes:\s*(\d{1,3})\b", re.IGNORECASE)


def reconcile(draft: BillingDraft, sections: list[dict]) -> BillingDraft:
    """Cross-check the dictation-derived draft against the note's own `[[CPT: ...]]` chips.

    Returns a NEW draft; `sections` is read and never modified, so the per-section chips and every
    test that locks them stay exactly as they are.

    The two directions carry different meanings, and both are worth surfacing:
      * in the dictation but not the note -> the model dropped a stated treatment (rule 15)
      * in the note but not the dictation -> a fabricated or heading-artifact code (rule 14)
    Minutes disagreements are rated `low` because the note's side of that comparison is prose the
    MODEL wrote, so a mismatch is as likely to be a rewording as a real error.
    """
    chip_codes: dict[str, int | None] = {}
    for s in sections or ():
        body = s.get("body", "") or ""
        for m in _CPT_MARKER_RE.finditer(body):
            mm = _SECTION_MINUTES_RE.search(body)
            chip_codes[m.group(1)] = int(mm.group(1)) if mm else None

    dictation_codes = {h.code: h for h in draft.billable}
    # Starts EMPTY, not from `draft.conflicts`: the conflict set is a pure function of (draft,
    # sections), so recomputing it makes reconcile idempotent. Appending instead would double
    # every finding in the review card the second time it ran.
    conflicts: list[Conflict] = []

    for code, hit in sorted(dictation_codes.items()):
        if code not in chip_codes:
            conflicts.append(Conflict(
                kind="dictation_only", severity="high", code=code,
                detail=f"\"{hit.cue}\" was dictated but the note has no {hit.label} section — "
                       "the treatment may have been dropped from the note (rule 15).",
            ))
    for code in sorted(chip_codes):
        if code not in dictation_codes:
            conflicts.append(Conflict(
                kind="note_only", severity="high", code=code,
                detail=f"The note suggests {code} but the dictation never named that treatment as "
                       "performed today — verify before billing (rule 14).",
            ))
    for code, hit in sorted(dictation_codes.items()):
        note_min = chip_codes.get(code)
        if note_min is not None and hit.minutes is not None and note_min != hit.minutes:
            conflicts.append(Conflict(
                kind="minutes_mismatch", severity="low", code=code,
                detail=f"Dictation gave {hit.minutes} min for {code}; the note says {note_min} min.",
            ))

    return replace(draft, conflicts=tuple(conflicts))
