"""Scoring for a generated note, in four tiers of decreasing objectivity.

  A. GOLD-LABEL  CPT precision/recall against the corpus's `cpt_codes`. Real ground truth.
  B. INVARIANT   Contract violations the pipeline promises never to emit. Objective —
                 a failure here is a bug, not a judgment call.
  C. OMISSION    Clinical values stated in the transcript that never reached the note
                 (CLAUDE.md rule 15). Objective, and previously unmeasured.
  D. TRIAGE      Every [[NEEDS: ...]] flag raised, with context. NOT scored — a human
                 adjudicates these.

Tier D deliberately reports no false-positive rate. A flag exists BECAUSE the strict matcher
in traceability.py failed to anchor a value; re-running that same matcher to "verify" the flag
is circular and would report 0% by construction. Real false positives come from phrasings the
normalizer doesn't cover, which only a human can identify. This tier surfaces the evidence for
that judgment rather than pretending to make it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.generate import cpt as cpt_module
from app.generate import traceability
from app.generate.forms import CARRY_SECTION_LABELS
# MAX_HEADING_CHARS comes from the PRODUCTION module, not redefined here:
# `postprocess.split_folded_headings` repairs a folded heading at this same threshold, so the
# eval and the repair must agree by construction. Two copies of the number would let the eval
# quietly stop measuring what the pipeline actually does.
from app.generate.postprocess import MAX_HEADING_CHARS
from evals.soap import SOAP_ORDER, coverage as soap_coverage

# Every CPT code Cadence's deterministic table is capable of producing. A gold code absent from
# this set can NEVER be suggested no matter how good the model is — that's a table gap, a
# different (and cheaper to fix) problem than the model omitting a treatment section.
SUGGESTABLE_CODES = frozenset(code for _, code, _ in cpt_module._CPT_RULES)

_CPT_MARKER_RE = re.compile(r"\[\[CPT:\s*([0-9A-Z]{5})\b")
_NEEDS_MARKER_RE = re.compile(r"\[\[NEEDS:\s*([^\]]*)\]\]")
_ANY_MARKER_RE = re.compile(r"\[\[(?:NEEDS|CPT):[^\]]*\]\]")
# A bare PT CPT / G code sitting in the prose, i.e. one the model authored that the pipeline
# failed to strip (rule 12). Checked only AFTER [[CPT: ...]] markers are removed.
_BARE_CODE_RE = re.compile(r"\b(?:97\d{3}|G0283)\b")
# Conservative ICD-10: a letter, two digits, optional decimal tail. Checked only after NEEDS
# markers are stripped, since the pipeline replaces code sections with a NEEDS marker.
_ICD10_RE = re.compile(r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b")
_ZERO_MINUTES_RE = re.compile(r"^\s*Minutes:\s*0\b", re.IGNORECASE)


def note_text(sections: list[dict]) -> str:
    return "\n".join(f"{s.get('heading', '')}\n{s.get('body', '')}" for s in sections)


def strip_markers(text: str) -> str:
    return _ANY_MARKER_RE.sub("", text)


# --- Tier A: CPT against gold labels -----------------------------------------

@dataclass
class CptScore:
    gold: tuple[str, ...]
    suggested: tuple[str, ...]
    hits: tuple[str, ...] = ()
    missed_section: tuple[str, ...] = ()   # table CAN produce it; no section heading triggered it
    table_gap: tuple[str, ...] = ()        # table cannot produce it at all — a mapping gap
    extra: tuple[str, ...] = ()            # suggested but not in gold

    @property
    def precision(self) -> float | None:
        return len(self.hits) / len(self.suggested) if self.suggested else None

    @property
    def recall(self) -> float | None:
        return len(self.hits) / len(self.gold) if self.gold else None

    @property
    def attainable_recall(self) -> float | None:
        """Recall counting only codes the table could ever produce — isolates model
        performance from table coverage."""
        attainable = [c for c in self.gold if c in SUGGESTABLE_CODES]
        return len(self.hits) / len(attainable) if attainable else None


def score_cpt(sections: list[dict], gold_codes: tuple[str, ...]) -> CptScore:
    suggested: list[str] = []
    for s in sections:
        for m in _CPT_MARKER_RE.finditer(s.get("body", "")):
            if m.group(1) not in suggested:
                suggested.append(m.group(1))
    gold = tuple(gold_codes)
    hits = tuple(c for c in gold if c in suggested)
    misses = [c for c in gold if c not in suggested]
    return CptScore(
        gold=gold,
        suggested=tuple(suggested),
        hits=hits,
        missed_section=tuple(c for c in misses if c in SUGGESTABLE_CODES),
        table_gap=tuple(c for c in misses if c not in SUGGESTABLE_CODES),
        extra=tuple(c for c in suggested if c not in gold),
    )


# --- Tier B: pipeline invariants ---------------------------------------------

@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


def _expected_section_labels(spec: str) -> list[str]:
    """Best-effort section names from a template's outline: field-per-section specs write one
    line per section as "Label — description". Heuristic by design, so coverage is reported as
    a ratio rather than a pass/fail and an imprecise extraction can't manufacture a failure."""
    labels: list[str] = []
    for line in (spec or "").splitlines():
        m = re.match(r"^([A-Z][^—\n]{2,60}?)\s*[—–]", line.strip())
        if m:
            label = re.sub(r"\[carry forward\]", "", m.group(1), flags=re.I).strip(" .-")
            if label and label not in labels:
                labels.append(label)
    return labels


def score_invariants(
    sections: list[dict],
    form,
    *,
    parsed_ok: bool,
    was_condensed: bool,
    condense_flag_present: bool,
) -> list[Check]:
    checks: list[Check] = []
    text = note_text(sections)
    body_only = "\n".join(s.get("body", "") for s in sections)

    checks.append(Check("parsed into sections", parsed_ok, "model ignored the ## heading contract"))
    checks.append(Check("not collapsed (>=4 sections)", len(sections) >= 4, f"{len(sections)} sections"))

    # Content must live in the BODY, or the whole verification layer no-ops (see MAX_HEADING_CHARS).
    # NOTE: `postprocess.split_folded_headings` now repairs this at the same threshold, so a
    # failure here no longer means "the model folded the heading" — it means THE REPAIR DECLINED TO
    # SPLIT, which is a much narrower and more interesting event. To see how often the model folds
    # in the first place (i.e. whether it is getting worse), read `folded_headings_raw`, which is
    # counted on the RAW parse before postprocess runs.
    prose_headings = [s.get("heading", "") for s in sections if len(s.get("heading", "")) > MAX_HEADING_CHARS]
    checks.append(Check(
        "content in bodies, not headings", not prose_headings,
        f"{len(prose_headings)}/{len(sections)} headings still over {MAX_HEADING_CHARS} chars "
        f"(longest {max((len(h) for h in prose_headings), default=0)}) after the fold repair — "
        f"verification flags cannot fire on an empty body",
    ))
    empty_bodies = [
        s.get("heading", "") for s in sections if not strip_markers(s.get("body", "")).strip()
    ]
    checks.append(Check(
        "every section has a non-empty body", not empty_bodies,
        f"{len(empty_bodies)}/{len(sections)} empty: {empty_bodies[:4]}",
    ))

    # Rule 12 — the model must never author a billing code. [[CPT: ...]] markers are the
    # pipeline's own trusted suggestions and are stripped before checking for bare codes.
    stripped = strip_markers(text)
    bare = sorted(set(_BARE_CODE_RE.findall(stripped)))
    checks.append(Check("no model-authored CPT code survived", not bare, f"found {bare}"))
    icd = sorted(set(_ICD10_RE.findall(stripped)))
    checks.append(Check("no ICD-10 code survived", not icd, f"found {icd}"))

    # Rule 11 — zero-minute placeholder sections are dropped by postprocess.
    zero = [s["heading"] for s in sections if _ZERO_MINUTES_RE.match(s.get("body", ""))]
    checks.append(Check("no 'Minutes: 0' placeholder section", not zero, f"found {zero}"))

    # Rule 11 — carry tags only on this form's real carry-forward labels.
    legal = [lbl.lower() for lbl in CARRY_SECTION_LABELS.get(form.id, [])]
    illegal = [
        s["heading"] for s in sections
        if s.get("carried_forward")
        and not any(lbl in s["heading"].lower() or s["heading"].lower() in lbl for lbl in legal)
    ]
    checks.append(Check("no illegal [[CARRIED FORWARD]] tag", not illegal, f"found {illegal}"))

    # Rule 18(d) — a section must not stop mid-sentence (the old num_ctx truncation signature).
    tail = strip_markers(body_only).rstrip()
    truncated = bool(tail) and not re.search(r"[.!?:)\]\d%]$", tail)
    checks.append(Check("note does not end mid-sentence", not truncated, f"ends: ...{tail[-60:]!r}"))

    # Rule 16 — a condensed dictation must always surface its warning to the clinician.
    if was_condensed:
        checks.append(Check("condense warning surfaced", condense_flag_present, "condensed but no warning"))

    # SOAP coverage — an empty block is a field the clinician fills by hand in the EHR.
    cov = soap_coverage(sections)
    empty = [k for k in SOAP_ORDER if cov[k] == 0]
    checks.append(Check("all four SOAP blocks populated", not empty, f"empty: {empty}"))

    return checks


def section_coverage(sections: list[dict], form) -> tuple[int, int, list[str]]:
    """How many of the template's own section labels appear as headings. Returns
    (present, expected, missing)."""
    expected = _expected_section_labels(form.spec)
    heads = " | ".join(s.get("heading", "").lower() for s in sections)
    missing = [lbl for lbl in expected if lbl.lower() not in heads]
    return len(expected) - len(missing), len(expected), missing


# --- Tier C: omission (transcript -> note) -----------------------------------

@dataclass
class OmissionScore:
    stated: tuple[str, ...] = ()
    present: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def rate(self) -> float | None:
        return len(self.present) / len(self.stated) if self.stated else None


def score_omissions(sections: list[dict], transcript: str) -> OmissionScore:
    """Every clinical value the therapist STATED must appear somewhere in the note (rule 15).

    This is `traceability.anchor_note_to_transcript` run with its arguments swapped: that
    function asks "is each value in A also in B", so passing (transcript, note) inverts the
    fabrication check into an omission check. Reusing it verbatim guarantees both directions
    share the same value patterns and the same spoken/written normalization.
    """
    anchors = traceability.anchor_note_to_transcript(transcript, note_text(sections))
    return OmissionScore(
        stated=tuple(a.value for a in anchors),
        present=tuple(a.value for a in anchors if a.anchored),
        dropped=tuple(a.value for a in anchors if not a.anchored),
    )


# --- Tier A2: billing gold labels (ICD / CPT-from-dictation / minutes / units) ------------
#
# These score `app/generate/billing.py`, which reads the DICTATION, so unlike Tier A they do not
# depend on the model at all — a failure here is a bug in the extractor, not a bad generation.
# Three of the metrics below deliberately measure UNSAFETY rather than incompleteness, and those
# are the ones to read first:
#
#   distractor_leaks   a negated / prior-visit / planned / home-program treatment got billed
#   untimed_leak       a service-based modality's minutes inflated the timed total
#   laterality_errors  the right diagnosis family on the WRONG side
#
# A miss is a safe failure the clinician corrects. Each of these three is a wrong claim.

def _same_icd_family(a: str, b: str) -> bool:
    """True if two ICD-10 codes differ only in their final character — i.e. same condition,
    different laterality (M75.101 right vs M75.102 left)."""
    return a != b and len(a) == len(b) and len(a) > 1 and a[:-1] == b[:-1]


@dataclass
class IcdScore:
    gold: tuple[str, ...] = ()
    suggested: tuple[str, ...] = ()
    hits: tuple[str, ...] = ()
    missed: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    #: Right condition, WRONG side. Counted separately from a plain miss because it is the more
    #: dangerous error: a missing code is a blank to fill, a wrong-side code reads as confident.
    laterality_errors: tuple[tuple[str, str], ...] = ()

    @property
    def precision(self) -> float | None:
        return len(self.hits) / len(self.suggested) if self.suggested else None

    @property
    def recall(self) -> float | None:
        return len(self.hits) / len(self.gold) if self.gold else None


def score_icd(draft, gold_codes: tuple[str, ...]) -> IcdScore:
    suggested = tuple(dict.fromkeys(c.code for c in draft.icd_candidates))
    gold = tuple(gold_codes)
    hits = tuple(c for c in gold if c in suggested)
    missed = tuple(c for c in gold if c not in suggested)
    extra = tuple(c for c in suggested if c not in gold)
    laterality = tuple(
        (g, s) for g in missed for s in extra if _same_icd_family(g, s)
    )
    return IcdScore(gold=gold, suggested=suggested, hits=hits, missed=missed, extra=extra,
                    laterality_errors=laterality)


@dataclass
class BillingDetectionScore:
    """CPT detection from the DICTATION (not from note headings — that's Tier A)."""
    gold: tuple[str, ...] = ()
    detected: tuple[str, ...] = ()
    hits: tuple[str, ...] = ()
    missed: tuple[str, ...] = ()
    false_positives: tuple[str, ...] = ()
    #: A code the transcript explicitly marked as NOT billable today, that got billed anyway,
    #: paired with the reason it should have been excluded. The headline safety metric.
    distractor_leaks: tuple[tuple[str, str], ...] = ()
    #: Codes AUTO-BILLED or merely SURFACED as an unconfirmed candidate (a weak cue). A surfaced
    #: code is one click for the clinician; a missed one they must notice is absent. Tracking both
    #: keeps "we got it wrong" separate from "we asked instead of assuming".
    surfaced: tuple[str, ...] = ()

    @property
    def precision(self) -> float | None:
        return len(self.hits) / len(self.detected) if self.detected else None

    @property
    def recall(self) -> float | None:
        """Auto-billed recall — gold codes Cadence billed without asking."""
        return len(self.hits) / len(self.gold) if self.gold else None

    @property
    def surfaced_recall(self) -> float | None:
        """Gold codes Cadence either billed OR raised for confirmation. The gap between this and
        `recall` is work handed to the clinician; the gap between this and 1.0 is a true miss."""
        if not self.gold:
            return None
        return len([c for c in self.gold if c in self.surfaced]) / len(self.gold)


def score_billing_detection(draft, record) -> BillingDetectionScore:
    from app.generate.billing import PERFORMED, UNCERTAIN
    detected = tuple(dict.fromkeys(h.code for h in draft.billable))
    surfaced = tuple(dict.fromkeys(h.code for h in draft.interventions
                                   if h.status in (PERFORMED, UNCERTAIN)))
    gold = tuple(dict.fromkeys(i.code for i in record.interventions if i.billable))
    hits = tuple(c for c in gold if c in detected)
    leaks = tuple((d.code, d.reason) for d in record.distractors if d.code in detected)
    return BillingDetectionScore(
        gold=gold, detected=detected, hits=hits,
        missed=tuple(c for c in gold if c not in detected),
        false_positives=tuple(c for c in detected if c not in gold),
        distractor_leaks=leaks,
        surfaced=surfaced,
    )


@dataclass
class MinutesCell:
    code: str
    gold: int | None
    extracted: int | None
    basis: str = ""

    @property
    def delta(self) -> int | None:
        return None if self.gold is None or self.extracted is None else self.extracted - self.gold


@dataclass
class MinutesScore:
    cells: tuple[MinutesCell, ...] = ()

    @property
    def exact(self) -> int:
        return sum(1 for c in self.cells if c.delta == 0)

    @property
    def within_2(self) -> int:
        return sum(1 for c in self.cells if c.delta is not None and abs(c.delta) <= 2)

    @property
    def not_extracted(self) -> int:
        """Gold had a duration, the extractor found none. A SAFE failure — it becomes a visible
        "minutes not stated" gap the clinician fills, never a fabricated number."""
        return sum(1 for c in self.cells if c.gold is not None and c.extracted is None)

    @property
    def fabricated(self) -> int:
        """The extractor produced minutes where the transcript stated none. Distinct from
        `not_extracted` because this one is an invented billable value, i.e. unsafe."""
        return sum(1 for c in self.cells if c.gold is None and c.extracted is not None)

    @property
    def mae(self) -> float | None:
        deltas = [abs(c.delta) for c in self.cells if c.delta is not None]
        return sum(deltas) / len(deltas) if deltas else None


def score_minutes(draft, record) -> MinutesScore:
    extracted = {h.code: h for h in draft.billable}
    gold = {i.code: i for i in record.interventions}
    cells = []
    for code in sorted(set(gold) | set(extracted)):
        g = gold.get(code)
        e = extracted.get(code)
        cells.append(MinutesCell(
            code=code,
            gold=g.minutes if g else None,
            extracted=e.minutes if e else None,
            basis=e.minutes_basis if e else "",
        ))
    return MinutesScore(cells=tuple(cells))


@dataclass
class UnitsScore:
    gold_units: int | None = None
    computed_units: int | None = None
    gold_timed_minutes: int | None = None
    computed_timed_minutes: int | None = None
    gold_units_ama: int | None = None
    computed_units_ama: int | None = None
    #: An untimed, service-based code whose minutes reached the timed total — an inflated unit
    #: count, i.e. an overbill.
    untimed_leak: tuple[str, ...] = ()
    #: CMS substitution and the AMA rule of eights disagree on this record. Not an error: it means
    #: the record exercises the case where Cadence must show both numbers.
    method_disagreement: bool = False
    #: Units if the clinician accepts the `uncertain` timed lines too. Gold assumes every stated
    #: intervention bills, so plain `exact` scores the WEAK-CUE POLICY rather than the arithmetic:
    #: a record where the code was found, the minutes were right, and the only thing missing was a
    #: confirmation click still counts as wrong. This is the units analogue of `surfaced_recall`.
    computed_units_if_confirmed: int | None = None

    @property
    def exact(self) -> bool:
        return self.gold_units is not None and self.gold_units == self.computed_units

    @property
    def overstated(self) -> bool:
        """Computed MORE units than the session earned — the only unsafe direction for this
        metric, and the one that matters for billing risk. Under-counting is a safe failure:
        Cadence surfaces the missing minutes as a gap and the clinician adds them back. A bare
        "units exact 58%" reads alarming while hiding which way the errors ran, so the two are
        reported separately."""
        return (self.gold_units is not None and self.computed_units is not None
                and self.computed_units > self.gold_units)

    @property
    def understated(self) -> bool:
        return (self.gold_units is not None and self.computed_units is not None
                and self.computed_units < self.gold_units)

    @property
    def exact_if_confirmed(self) -> bool:
        """Would the units be right after the clinician accepts the surfaced lines? That is the
        question that matters in the room; `exact` answers the narrower "right with no input"."""
        if self.gold_units is None:
            return False
        return self.gold_units in (self.computed_units, self.computed_units_if_confirmed)

    @property
    def minutes_exact(self) -> bool:
        return (self.gold_timed_minutes is not None
                and self.gold_timed_minutes == self.computed_timed_minutes)


def score_units(draft, record) -> UnitsScore:
    from app.generate.cpt import is_timed

    # Recompute the timed total INDEPENDENTLY of how the draft arrived at it, then compare. An
    # earlier version asked whether a code was "untimed but marked timed", which is tautologically
    # false because the draft sets that flag FROM `is_timed` — a metric that can never fire is
    # worse than no metric, because it reads as a clean bill of health.
    expected_timed = sum(h.minutes for h in draft.billable if is_timed(h.code) and h.minutes)
    untimed_with_minutes = sorted({h.code for h in draft.billable
                                   if not is_timed(h.code) and h.minutes})
    leaks = tuple(untimed_with_minutes) if draft.total_timed_minutes != expected_timed else ()
    return UnitsScore(
        gold_units=record.expected_units,
        computed_units=draft.units.total_units if draft.units else None,
        gold_timed_minutes=record.total_timed_minutes,
        computed_timed_minutes=draft.total_timed_minutes,
        gold_units_ama=record.expected_units_ama,
        computed_units_ama=draft.units_alt.total_units if draft.units_alt else None,
        untimed_leak=leaks,
        method_disagreement=draft.method_disagreement,
        computed_units_if_confirmed=(draft.units_if_confirmed.total_units
                                     if draft.units_if_confirmed else None),
    )


@dataclass
class AgreementScore:
    """Do the two independent code sources agree? `cpt.suggest_codes` reads the NOTE's headings;
    `billing.extract` reads the DICTATION. Disagreement localizes the failure: a code only the
    dictation has means the model dropped a treatment (rule 15); only the note, a fabrication
    (rule 14)."""
    chip_only: tuple[str, ...] = ()
    dictation_only: tuple[str, ...] = ()
    both: tuple[str, ...] = ()

    @property
    def agreement(self) -> float | None:
        total = len(self.chip_only) + len(self.dictation_only) + len(self.both)
        return len(self.both) / total if total else None


def score_cpt_agreement(sections: list[dict], draft) -> AgreementScore:
    chips = {m.group(1) for s in sections for m in _CPT_MARKER_RE.finditer(s.get("body", ""))}
    dictated = {h.code for h in draft.billable}
    return AgreementScore(
        chip_only=tuple(sorted(chips - dictated)),
        dictation_only=tuple(sorted(dictated - chips)),
        both=tuple(sorted(chips & dictated)),
    )


# --- Tier D: flag triage (human-adjudicated) ---------------------------------

@dataclass
class Flag:
    section: str
    text: str
    context: str = ""


def _transcript_window(transcript: str, flag_text: str, width: int = 120) -> str:
    """Best-effort excerpt to adjudicate a flag against. Anchors on the quoted value if the
    flag has one, else on the first distinctive word, so the reviewer sees what the therapist
    actually said near the value in question."""
    quoted = re.search(r'"([^"]+)"', flag_text)
    needle = quoted.group(1) if quoted else ""
    digits = re.search(r"\d+", needle or "")
    key = digits.group(0) if digits else (needle.split()[0] if needle else "")
    if not key:
        return ""
    idx = transcript.lower().find(key.lower())
    if idx == -1:
        return ""
    start = max(0, idx - width // 2)
    return ("…" if start else "") + transcript[start:idx + width // 2].replace("\n", " ") + "…"


def collect_flags(sections: list[dict], transcript: str) -> list[Flag]:
    flags: list[Flag] = []
    for s in sections:
        for m in _NEEDS_MARKER_RE.finditer(s.get("body", "")):
            text = m.group(1).strip()
            flags.append(Flag(section=s.get("heading", ""), text=text,
                              context=_transcript_window(transcript, text)))
    return flags


# --- aggregate ---------------------------------------------------------------

@dataclass
class RecordResult:
    record_id: int
    form_id: str
    run: int
    seconds: float
    was_condensed: bool
    checks: list[Check] = field(default_factory=list)
    cpt: CptScore | None = None
    omissions: OmissionScore | None = None
    flags: list[Flag] = field(default_factory=list)
    sections_present: int = 0
    sections_expected: int = 0
    sections_missing: list[str] = field(default_factory=list)
    note_chars: int = 0
    # Billing blocks — None on a record with no billing gold (the hand-written eight).
    icd: IcdScore | None = None
    billing_detection: BillingDetectionScore | None = None
    minutes: MinutesScore | None = None
    units: UnitsScore | None = None
    agreement: AgreementScore | None = None
    is_synthetic: bool = False
    #: Carried so a sweep can break results down per region — a weak body part must be visible,
    #: not averaged away against five strong ones.
    body_part: str | None = None
    #: Headings the MODEL folded, counted on the raw parse BEFORE
    #: postprocess.split_folded_headings repaired them. Preserves visibility of model
    #: behaviour once the repair makes the downstream invariant permanently green.
    folded_headings_raw: int = 0

    @property
    def invariants_passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "form_id": self.form_id,
            "run": self.run,
            "seconds": round(self.seconds, 1),
            "was_condensed": self.was_condensed,
            "note_chars": self.note_chars,
            "invariants": {
                "passed": self.invariants_passed,
                "total": len(self.checks),
                "failures": [{"name": c.name, "detail": c.detail} for c in self.checks if not c.passed],
            },
            "section_coverage": {
                "present": self.sections_present,
                "expected": self.sections_expected,
                "missing": self.sections_missing,
            },
            "cpt": None if self.cpt is None else {
                "gold": list(self.cpt.gold),
                "suggested": list(self.cpt.suggested),
                "hits": list(self.cpt.hits),
                "missed_section": list(self.cpt.missed_section),
                "table_gap": list(self.cpt.table_gap),
                "extra": list(self.cpt.extra),
                "precision": self.cpt.precision,
                "recall": self.cpt.recall,
                "attainable_recall": self.cpt.attainable_recall,
            },
            "omissions": None if self.omissions is None else {
                "stated": len(self.omissions.stated),
                "present": len(self.omissions.present),
                "dropped": list(self.omissions.dropped),
                "rate": self.omissions.rate,
            },
            "flags": [{"section": f.section, "text": f.text, "context": f.context} for f in self.flags],
            "is_synthetic": self.is_synthetic,
            "body_part": self.body_part,
            "folded_headings_raw": self.folded_headings_raw,
            # Every key written here MUST be read back by scripts/eval_corpus.py:_load_result.
            # A --resume run rehydrates from this dict, so a key added on one side only would
            # silently zero the metric on every cached record. tests/test_eval_score.py locks
            # the round trip.
            "icd": None if self.icd is None else {
                "gold": list(self.icd.gold), "suggested": list(self.icd.suggested),
                "hits": list(self.icd.hits), "missed": list(self.icd.missed),
                "extra": list(self.icd.extra),
                "laterality_errors": [list(p) for p in self.icd.laterality_errors],
                "precision": self.icd.precision, "recall": self.icd.recall,
            },
            "billing_detection": None if self.billing_detection is None else {
                "gold": list(self.billing_detection.gold),
                "detected": list(self.billing_detection.detected),
                "hits": list(self.billing_detection.hits),
                "missed": list(self.billing_detection.missed),
                "false_positives": list(self.billing_detection.false_positives),
                "distractor_leaks": [list(p) for p in self.billing_detection.distractor_leaks],
                "surfaced": list(self.billing_detection.surfaced),
                "precision": self.billing_detection.precision,
                "recall": self.billing_detection.recall,
                "surfaced_recall": self.billing_detection.surfaced_recall,
            },
            "minutes": None if self.minutes is None else {
                "cells": [{"code": c.code, "gold": c.gold, "extracted": c.extracted,
                           "basis": c.basis, "delta": c.delta} for c in self.minutes.cells],
                "exact": self.minutes.exact, "within_2": self.minutes.within_2,
                "not_extracted": self.minutes.not_extracted,
                "fabricated": self.minutes.fabricated, "mae": self.minutes.mae,
            },
            "units": None if self.units is None else {
                "gold_units": self.units.gold_units,
                "computed_units": self.units.computed_units,
                "gold_timed_minutes": self.units.gold_timed_minutes,
                "computed_timed_minutes": self.units.computed_timed_minutes,
                "gold_units_ama": self.units.gold_units_ama,
                "computed_units_ama": self.units.computed_units_ama,
                "untimed_leak": list(self.units.untimed_leak),
                "method_disagreement": self.units.method_disagreement,
                "computed_units_if_confirmed": self.units.computed_units_if_confirmed,
                "exact": self.units.exact, "minutes_exact": self.units.minutes_exact,
                "exact_if_confirmed": self.units.exact_if_confirmed,
                "overstated": self.units.overstated,
            },
            "agreement": None if self.agreement is None else {
                "chip_only": list(self.agreement.chip_only),
                "dictation_only": list(self.agreement.dictation_only),
                "both": list(self.agreement.both),
                "agreement": self.agreement.agreement,
            },
        }
