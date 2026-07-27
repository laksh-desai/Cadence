"""Traceability / verification spike: anchor note values back to the dictation transcript.

The PT market's highest-value unmet feature (docs/saas-migration/product-strategy.md, item 13):
every clinical VALUE in a generated note — pain, MMT grade, ROM degrees, treatment minutes —
must trace back to something the clinician actually said, because a hallucinated *number* is a
billing-fraud risk, not merely a quality issue.

This module implements the model- and ASR-agnostic half of that feature. Given the note text and
the raw dictation transcript, it decides, for each clinical value it finds in the note, whether
the transcript actually contains that value:

    ANCHORED   -> the value appears in the transcript (spoken "four out of five" or written "4/5")
    UNANCHORED -> the value is NOT in the transcript  => probable fabrication, surface for review

The hard part is that the note is normalized ("3+/5", "4/10", "15 minutes") while the transcript
is spoken ("three plus out of five", "four out of ten", "fifteen minutes"). We bridge that by
normalizing BOTH sides to a canonical digit form before matching.

Deferred to a later phase (needs real ASR word-timestamps): turning an ANCHORED value into an
audio timestamp for "click the note sentence to hear the source." All three candidate ASR
backends expose per-word timing (CTC forced alignment on the current MedASR, Whisper
`word_timestamps`, AWS Transcribe Medical), so that step is a join: char offset -> word index ->
timestamp. See docs/saas-migration/traceability-spike.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- spoken-number -> digit normalization (0-999: covers pain 0-10, MMT 0-5, treatment
# minutes, and ROM degrees which routinely exceed 100 and so MUST parse spoken hundreds,
# otherwise a real "one hundred twenty degrees" would be wrongly flagged as fabricated) ---
_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUM_WORDS = sorted([*_ONES, *_TENS, "hundred"], key=len, reverse=True)  # longest-first: "fourteen" before "four"
# A maximal run of number-words joined by spaces/hyphens/"and" (e.g. "one hundred and twenty").
_NUM_RUN_RE = re.compile(
    r"\b(?:" + "|".join(_NUM_WORDS) + r")(?:[ -]+(?:and[ -]+)?(?:" + "|".join(_NUM_WORDS) + r"))*\b",
    re.IGNORECASE,
)


def _parse_number_run(run: str) -> int | None:
    """Parse a spoken number run to an int: 'one hundred twenty' -> 120, 'forty five' -> 45.
    Returns None if the run holds no actual number word (so a bare 'and' is left untouched)."""
    total, current, saw = 0, 0, False
    for w in re.split(r"[ -]+", run.lower()):
        if w in ("", "and"):
            continue
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        else:
            return None
        saw = True
    return (total + current) if saw else None


def normalize_for_matching(text: str) -> str:
    """Canonicalize spoken/written clinical values to a comparable digit form:
    'three plus out of five' -> '3+/5', 'four out of ten' -> '4/10', 'fifteen minutes' ->
    '15 minutes', 'one hundred twenty degrees' -> '120 degrees'. Applied to BOTH the note and
    the transcript so they can be compared.
    """
    def _sub(m: re.Match) -> str:
        n = _parse_number_run(m.group(0))
        return str(n) if n is not None else m.group(0)

    s = (text or "").lower().replace("a hundred", "one hundred")
    s = _NUM_RUN_RE.sub(_sub, s)
    # grade modifiers spoken as words, adjacent to a digit: "3 plus" -> "3+"
    s = re.sub(r"\b(\d)\s+plus\b", r"\1+", s)
    s = re.sub(r"\b(\d)\s+minus\b", r"\1-", s)
    # MMT range "X to Y out of Z" -> "X/Z to Y/Z": the spoken denominator applies to BOTH grades,
    # matching how postprocess.normalize_strength_grades renders the note. Must run before the
    # single "out of" rule below, else a dictated range ("three plus to four minus out of five")
    # normalizes to "3+ to 4-/5" and the note's "3+/5" false-flags as unanchored.
    s = re.sub(r"\b(\d+[+-]?)\s+to\s+(\d+[+-]?)\s+out of\s+(\d+)\b", r"\1/\3 to \2/\3", s)
    # "X out of Y" -> "X/Y" (keeps an optional +/- grade modifier on X)
    s = re.sub(r"\b(\d+[+-]?)\s*out of\s*(\d+)\b", r"\1/\2", s)
    # "X over Y" -> "X/Y" — some clinicians say pain "four over ten". Only affects values that then
    # match a pattern (N/10, N/5); "4 over 6 weeks" -> "4/6 weeks" matches nothing, so it's harmless.
    s = re.sub(r"\b(\d+)\s+over\s+(\d+)\b", r"\1/\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --- clinical values worth verifying (the fraud-risk set) ---------------------
# Each pattern runs against the NORMALIZED note text; the matched string is what we then
# look for in the normalized transcript.
_VALUE_PATTERNS = {
    "mmt": re.compile(r"\b\d[+-]?/5\b"),
    "pain": re.compile(r"\b\d{1,2}/10\b"),
    "minutes": re.compile(r"\b\d{1,3} minutes?\b"),
    "degrees": re.compile(r"\b\d{1,3} degrees?\b"),
    # Ambulation distance — a classic carry-forward / billing value; units always spoken, so
    # low false-positive risk. Bare "m" for metres is deliberately excluded (collides with the
    # letter, per CLAUDE.md's mm/er caution); "metres/meters/yards/feet/foot/ft" are safe.
    "distance": re.compile(r"\b\d{1,4} (?:feet|foot|ft|yards?|metres?|meters?)\b"),
}


@dataclass(frozen=True)
class Anchor:
    kind: str          # "mmt" | "pain" | "minutes" | "degrees"
    value: str         # normalized value, e.g. "3+/5"
    anchored: bool     # True if found in the transcript
    transcript_hit: str | None  # the normalized-transcript substring it matched, or None


def extract_values(note_text: str) -> list[Anchor]:
    """Pull the fraud-risk clinical values out of a note (pre-anchoring)."""
    norm = normalize_for_matching(note_text)
    found: list[Anchor] = []
    seen: set[tuple[str, str]] = set()
    for kind, pat in _VALUE_PATTERNS.items():
        for m in pat.finditer(norm):
            key = (kind, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            found.append(Anchor(kind=kind, value=m.group(0), anchored=False, transcript_hit=None))
    return found


def anchor_note_to_transcript(note_text: str, transcript: str) -> list[Anchor]:
    """For every fraud-risk value in the note, decide whether the transcript contains it.
    UNANCHORED values are the probable fabrications a clinician should verify.
    """
    norm_transcript = normalize_for_matching(transcript)
    results: list[Anchor] = []
    for v in extract_values(note_text):
        hit = v.value if _contains_value(norm_transcript, v.value) else None
        results.append(Anchor(kind=v.kind, value=v.value, anchored=hit is not None, transcript_hit=hit))
    return results


def unanchored_values(note_text: str, transcript: str) -> list[Anchor]:
    """Just the probable fabrications — the note values with no basis in the transcript."""
    return [a for a in anchor_note_to_transcript(note_text, transcript) if not a.anchored]


def _contains_value(norm_transcript: str, value: str) -> bool:
    # Word-boundary-ish match so "4/5" doesn't spuriously match inside "14/5" etc. The value
    # already carries its own delimiters (/ , space+unit), so a direct search is safe here.
    return re.search(rf"(?<![\d/]){re.escape(value)}", norm_transcript) is not None


_EXISTING_MARKER_RE = re.compile(r"\[\[NEEDS:[^\]]*\]\]")


def flag_unanchored_in_sections(sections: list[dict], transcript: str) -> list[dict]:
    """Append an amber [[NEEDS: ...]] marker to any section that states a clinical value the
    dictation never contained — the fraud-risk fabrication guard, applied after postprocess.

    Deterministic and model-independent, so it works identically on any generation backend.
    The marker text is deliberately hedged ("verify or remove") because the matcher can't be
    perfect: a value the clinician stated in a phrasing the normalizer doesn't cover would be a
    false positive, and "verify" is the safe framing for a draft the clinician signs anyway.
    Values already inside an existing [[NEEDS: ...]] marker are ignored, never double-flagged.
    Reuses [[NEEDS: ...]] because it is the only form the UI renders in amber (app.js).
    """
    out = []
    for s in sections:
        body_wo_markers = _EXISTING_MARKER_RE.sub("", s["body"])
        unfound = [a.value for a in anchor_note_to_transcript(body_wo_markers, transcript) if not a.anchored]
        if unfound:
            marker = " " + " ".join(
                f'[[NEEDS: "{v}" not found in dictation — verify or remove]]' for v in unfound
            )
            out.append({**s, "body": s["body"].rstrip() + marker})
        else:
            out.append(s)
    return out


# --- fabricated pain-rating fields --------------------------------------------
# A rigid pain template ("Worst: /10  Best: /10  Current: /10") pressures the 4B model to FILL the
# slots even when the clinician gave no numeric rating — observed a real note invent "Worst: 10,
# Best: 10, Current: 10" for a dictation that named pain locations but no scores. `flag_unanchored_in_sections`
# above only catches the written "N/10" form; the bare field form ("Worst: 10") slips past it, so we
# catch it here: a Worst/Best/Current value (0-10) whose "N/10" equivalent is not in the dictation is
# a probable fabrication. The negative lookahead skips a value that already has "/10" (left to the
# pattern above) and skips doses/units ("Current 10 mg"). Flags, never deletes — same hedge as the rest.
_PAIN_FIELD_RE = re.compile(
    r"\b(?:worst|best|current)\b\s*[:\-]?\s*(10|[0-9])\b"
    r"(?!\s*(?:/\s*10|mg|ml|milligram|gram|degree|second|minute|feet|foot|ft|%|week|day|/5))",
    re.IGNORECASE,
)


def flag_unanchored_pain_fields(sections: list[dict], transcript: str) -> list[dict]:
    """Flag a Worst/Best/Current pain-slot value the dictation never stated — the fabrication a rigid
    "/10" pain template invites. Complements flag_unanchored_in_sections (which only sees "N/10")."""
    norm_t = normalize_for_matching(transcript)
    out = []
    for s in sections:
        body_wo = _EXISTING_MARKER_RE.sub("", s["body"])
        bad: list[str] = []
        for m in _PAIN_FIELD_RE.finditer(body_wo):
            val = m.group(1) + "/10"
            if not _contains_value(norm_t, val) and val not in bad:
                bad.append(val)
        if bad:
            marker = " " + " ".join(
                f'[[NEEDS: pain rating "{v}" not stated in the dictation — verify or remove]]' for v in bad
            )
            out.append({**s, "body": s["body"].rstrip() + marker})
        else:
            out.append(s)
    return out


# --- unsupported "normal" exam findings (CLAUDE.md rule 19) -------------------
# The 4B model fills exam sections it was told nothing about with invented normals
# ("Skin intact", "Sensation intact", "No edema", "O2 normal"). Each normal assertion is ABOUT a
# body system; if the dictation never mentions that system, the normal finding has no basis and is
# flagged for verification. Meaning-safe: we FLAG, never delete — a genuinely dictated normal is
# indistinguishable in text (rule 19), so this is a hedged review aid, exactly like the value
# anchoring above. Each rule is (assertion-in-note, transcript keyword stems that would support it,
# human label). Keyword sets are kept broad so a normal the clinician phrased differently
# ("no swelling" for edema, "neuro screen clean" for neuro) still anchors and isn't false-flagged.
_NORMAL_RULES = [
    (re.compile(r"\b(?:skin|integument\w*)\b[^.]*\b(?:intact|unremarkable|normal|clean|dry)\b", re.I),
     ("skin", "integument", "incision", "wound"), "skin/integumentary"),
    (re.compile(r"\bneuro\w*\b[^.]*\b(?:intact|unremarkable|normal|nonfocal|non-focal)\b", re.I),
     ("neuro",), "neurological exam"),
    (re.compile(r"\bsensation\b[^.]*\b(?:intact|unremarkable|normal|wnl|within normal limits)\b", re.I),
     ("sensa", "sensor"), "sensation"),
    (re.compile(r"\bcoordination\b[^.]*\b(?:intact|unremarkable|normal|wnl|within normal limits)\b", re.I),
     ("coordinat",), "coordination"),
    (re.compile(r"\bno edema\b", re.I),
     ("edema", "swell"), "edema"),
    (re.compile(r"\bcogniti\w*\b[^.]*\b(?:intact|unremarkable|normal)\b", re.I),
     ("cogniti", "orient", "memory", "alert"), "cognition"),
    (re.compile(r"\b(?:o2|oxygen|spo2|sao2)\b[^.]*\bnormal\b", re.I),
     ("o2", "oxygen", "spo2", "sao2", "sat"), "oxygen saturation"),
]


# --- assistive devices (CLAUDE.md rule 14) and vitals ------------------------
# Device: the head noun (cane/walker/…) must appear in the transcript, else the device was invented
# (observed: "ambulates with a cane" for a dictation that named no device). Negated mentions
# ("without a cane") are skipped so a correct no-device statement isn't flagged.
_DEVICE_RULES = [
    (re.compile(r"\bcane\b", re.I), "cane", 'assistive device "cane"'),
    (re.compile(r"\bwalker\b", re.I), "walker", 'assistive device "walker"'),
    (re.compile(r"\bcrutch\w*\b", re.I), "crutch", 'assistive device "crutches"'),
    (re.compile(r"\bwheelchair\b", re.I), "wheelchair", 'assistive device "wheelchair"'),
    (re.compile(r"\brollator\b", re.I), "rollator", 'assistive device "rollator"'),
]
_NEG_BEFORE = re.compile(r"\b(?:no|without|denies|denied)\b[\s\w]{0,12}$", re.I)


def _negated_before(text: str, idx: int) -> bool:
    """True if the device mention starting at idx is preceded by a nearby negation ("without a cane")."""
    return _NEG_BEFORE.search(text[:idx]) is not None


# Vitals: flag a value whose TYPE the dictation never mentions. Type-mention (not value-matching)
# because spoken BP/HR idioms ("one thirty over eighty") don't normalize cleanly to "130/80", so
# value-matching would false-flag real vitals. The BP pattern requires 2-3 digits each side, so it
# never fires on an MMT grade ("3+/5") or a pain rating ("4/10").
_VITAL_RULES = [
    # BP: 2-3 digits each side, NOT part of a longer number or date (the lookbehind/lookahead reject
    # "12/08/2026" so a note date isn't misread as a blood pressure).
    (re.compile(r"(?<![\d/])\d{2,3}\s*/\s*\d{2,3}(?!\s*[\d/])"), ("blood pressure", "bp", "pressure"), "blood pressure"),
    # HR / O2 must be followed by an actual value in the same clause, so an honest "HR: Not stated" —
    # the model correctly declining to fabricate — is never flagged (a real-generation regression).
    (re.compile(r"\b(?:hr|heart rate|pulse)\b[^.\n]{0,12}\d", re.I), ("heart rate", "pulse", "bpm"), "heart rate"),
    (re.compile(r"\b(?:o2|oxygen|spo2|sao2)\b[^.\n]{0,12}\d", re.I), ("o2", "oxygen", "spo2", "sao2", "sat"), "oxygen saturation"),
]


def _flag_by_mention_rules(sections, transcript, rules, template):
    """Shared engine: for each (regex, keyword-stems, label) rule, if the section body matches the
    regex but NONE of the keyword stems appear in the transcript, the thing is unsupported → append
    `template` formatted with the label. Flags, never rewrites."""
    t = transcript.lower()
    out = []
    for s in sections:
        body_wo_markers = _EXISTING_MARKER_RE.sub("", s["body"])
        flags: list[str] = []
        for rx, keywords, label in rules:
            if rx.search(body_wo_markers) and not any(k in t for k in keywords):
                if label not in flags:
                    flags.append(label)
        if flags:
            marker = " " + " ".join(template.format(label=lbl) for lbl in flags)
            out.append({**s, "body": s["body"].rstrip() + marker})
        else:
            out.append(s)
    return out


def flag_unsupported_normals(sections: list[dict], transcript: str) -> list[dict]:
    """Flag a NORMAL exam finding about a body system the dictation never mentioned — the
    invented-normal class the 4B model produces when it treats an empty exam section as "must be
    filled" (CLAUDE.md rule 19). Flags, never rewrites (a real dictated normal is indistinguishable)."""
    return _flag_by_mention_rules(
        sections, transcript, _NORMAL_RULES,
        "[[NEEDS: {label} stated as normal but not mentioned in dictation — verify]]",
    )


def flag_unsupported_vitals(sections: list[dict], transcript: str) -> list[dict]:
    """Flag a vital-sign value in the note whose vital TYPE the dictation never mentions (rule 14
    invented-vitals class)."""
    return _flag_by_mention_rules(
        sections, transcript, _VITAL_RULES,
        "[[NEEDS: {label} value stated but not mentioned in dictation — verify]]",
    )


def flag_unsupported_devices(sections: list[dict], transcript: str) -> list[dict]:
    """Flag an assistive device named in the note whose head noun the dictation never mentions —
    the invented-device fabrication (CLAUDE.md rule 14). Skips negated mentions ("without a cane")."""
    t = transcript.lower()
    out = []
    for s in sections:
        body = _EXISTING_MARKER_RE.sub("", s["body"])
        flags: list[str] = []
        for rx, stem, label in _DEVICE_RULES:
            positive = any(not _negated_before(body, m.start()) for m in rx.finditer(body))
            if positive and stem not in t and label not in flags:
                flags.append(label)
        if flags:
            marker = " " + " ".join(f"[[NEEDS: {lbl} not mentioned in dictation — verify]]" for lbl in flags)
            out.append({**s, "body": s["body"].rstrip() + marker})
        else:
            out.append(s)
    return out


def _norm_sentence(s: str) -> str:
    """Lowercased, punctuation-stripped, whitespace-collapsed form for comparing sentences."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def flag_cross_section_duplication(sections: list[dict], min_words: int = 8) -> list[dict]:
    """Flag a substantial sentence repeated near-verbatim across 2+ sections (CLAUDE.md rule 18c) —
    the paste-duplication that makes a note read as templated. Only EXACT long sentences
    (>= min_words) are flagged; brief summary overlap is by design (Objective Summary vs the detailed
    sections). Flags, never rewrites — rule 19 notes cross-section paraphrase has no safe mechanical
    rewrite, but surfacing an exact duplicate for the clinician to condense is safe."""
    per_section: list[list[str]] = []
    counts: dict[str, set[int]] = {}
    for i, s in enumerate(sections):
        body = _EXISTING_MARKER_RE.sub("", s["body"])
        sents = [_norm_sentence(x) for x in re.split(r"(?<=[.!?])\s+", body)]
        per_section.append(sents)
        for snt in sents:
            if len(snt.split()) >= min_words:
                counts.setdefault(snt, set()).add(i)
    dup = {snt for snt, idxs in counts.items() if len(idxs) >= 2}
    if not dup:
        return sections
    out = []
    for i, s in enumerate(sections):
        if any(snt in dup for snt in per_section[i]):
            marker = " [[NEEDS: text duplicated across sections — condense so each section is in its own words]]"
            out.append({**s, "body": s["body"].rstrip() + marker})
        else:
            out.append(s)
    return out


def add_verification_flags(sections: list[dict], transcript: str) -> list[dict]:
    """The full local verification pass run in /api/generate after postprocess. Deterministic,
    model-independent, hedged because the clinician signs every note: fabricated clinical values,
    then unsupported normal findings, then unsupported vitals, then invented devices, then
    cross-section paste-duplication."""
    sections = flag_unanchored_in_sections(sections, transcript)
    sections = flag_unanchored_pain_fields(sections, transcript)
    sections = flag_unsupported_normals(sections, transcript)
    sections = flag_unsupported_vitals(sections, transcript)
    sections = flag_unsupported_devices(sections, transcript)
    sections = flag_cross_section_duplication(sections)
    return sections
