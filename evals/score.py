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

# A section heading is a LABEL ("Functional Mobility / Gait" is 26 chars; the longest in any
# built-in template is well under this). Anything longer means the model wrote the section's
# CONTENT on the "## " line instead of in the body below it.
#
# This is not cosmetic. Observed on a real Follow-Up generation: 6 of 13 headings ran past 80
# chars (longest 434), leaving every body empty — and because traceability.add_verification_flags
# inspects `body` only, the ENTIRE verification layer silently no-opped. An invented assistive
# device and invented vitals passed through completely unflagged, while the note still scored
# clean on every other invariant. Catching this is the difference between "no fabrications found"
# and "the fabrication detector never ran."
MAX_HEADING_CHARS = 80


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
    prose_headings = [s.get("heading", "") for s in sections if len(s.get("heading", "")) > MAX_HEADING_CHARS]
    checks.append(Check(
        "content in bodies, not headings", not prose_headings,
        f"{len(prose_headings)}/{len(sections)} headings over {MAX_HEADING_CHARS} chars "
        f"(longest {max((len(h) for h in prose_headings), default=0)}) — "
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
        }
