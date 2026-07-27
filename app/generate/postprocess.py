"""Deterministic safety-net corrections applied after parsing the model's output.

MedGemma 4B reliably (not occasionally) violates two prompt rules no amount of
rewording fixed across repeated testing: it tags every section [[CARRIED FORWARD]]
even when told only specific sections qualify, and it invents empty placeholder
sections ("Minutes: 0 / no X performed today") for treatments never mentioned. Since
these are systemic model behaviors rather than one-off mistakes, CLAUDE.md's standing
instruction to fix the underlying logic — not just the prompt — applies: enforce both
rules in code so the contract holds regardless of model compliance.
"""

import re

from app.generate.forms import CARRY_SECTION_LABELS

_ZERO_MINUTES_RE = re.compile(r"^\s*Minutes:\s*0\b", re.IGNORECASE)
_CODE_HEADING_RE = re.compile(r"\b(CPT|ICD)\b", re.IGNORECASE)
# A carry-forward form's spec labels its carried sections "<Section> [carry forward]"; the model
# routinely copies that bracketed instruction into the emitted heading ("## Precautions [carry
# forward]"). Strip it so the heading is clean — it never affects the carry logic (which matches the
# label substring either way), only the displayed heading. NOTE: this is the single-bracket spec
# INSTRUCTION, not the double-bracket "[[CARRIED FORWARD]]" OUTPUT tag (that's parsed separately).
_CARRY_INSTRUCTION_RE = re.compile(r"\s*\[\[?\s*carry\s*forward[^\]]*\]\]?", re.IGNORECASE)

# --- Manual muscle test notation ---------------------------------------------
# PTs write strength grades as shorthand ("3+/5", a range as "3+/5 to 4-/5"), but the
# model frequently echoes the spoken long form ("three plus to four minus out of
# five") straight from the dictation. The prompt asks for shorthand; this enforces it
# deterministically since the transform is bounded and unambiguous. Restricted to a
# denominator of five so it can NEVER touch a pain rating ("4 out of 10") or any other
# "out of N" phrase — grades are 0-5 with an optional +/- only.
_GRADE_WORD = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
_MOD = {"plus": "+", "minus": "-", "+": "+", "-": "-"}
_GRADE = r"(zero|one|two|three|four|five|[0-5])(?:\s*(plus|minus|\+|-))?"
_OUT_OF_FIVE = r"out\s+of\s+(?:five|5)"
_MMT_RANGE_RE = re.compile(rf"\b{_GRADE}\s+to\s+{_GRADE}\s+{_OUT_OF_FIVE}\b", re.IGNORECASE)
_MMT_SINGLE_RE = re.compile(rf"\b{_GRADE}\s+{_OUT_OF_FIVE}\b", re.IGNORECASE)


def _grade_token(num: str, mod: str | None) -> str:
    n = _GRADE_WORD.get(num.lower(), num)
    m = _MOD.get(mod.lower(), "") if mod else ""
    return f"{n}{m}/5"


# --- Dictated checklist affirmations -----------------------------------------
# The therapist sometimes reads a form aloud as "<fact>, yes". The prompt (rule 17)
# asks the model to convert these to declarative prose, but the 4B model frequently
# echoes the trailing ", yes" verbatim — observed repeated across a whole Fall Risk
# section and duplicated into the Objective Summary on a real generation run. The
# affirmation is safe to drop deterministically ONLY at end-of-statement position:
# "<fact>, yes" means the fact holds, so "<fact>" alone is the clean clinical form.
# The negation half ("<fact>, no") is deliberately NOT handled here — dropping ", no"
# would silently INVERT clinical meaning — so it stays a prompt-only mitigation plus
# clinician review (CLAUDE.md rule 17). Matching only a statement-final ", yes" (before
# a period/newline/end of body) also avoids touching a mid-clause "..., yes, and ...".
_CHECKLIST_YES_RE = re.compile(r",[ \t]*yes[ \t]*(?=[.\n]|$)", re.IGNORECASE)


def strip_checklist_affirmations(sections: list[dict]) -> list[dict]:
    """Drop a statement-final ", yes" the model echoed from a dictated checklist answer
    ("Patient reports fear of falling, yes." -> "Patient reports fear of falling.").
    Bounded to end-of-statement position so it never touches a mid-clause ", yes," and
    never the meaning-inverting ", no".
    """
    out = []
    for s in sections:
        body = _CHECKLIST_YES_RE.sub("", s["body"])
        out.append(s if body == s["body"] else {**s, "body": body})
    return out


def _is_carry_forward_label(form_id: str, heading: str) -> bool:
    """Bidirectional substring match: the model sometimes writes the full verbose
    label as a heading (e.g. "Short-Term Goals [carry forward] each marked..."), but
    for forms whose spec lists Short-Term/Long-Term Goals under one combined "Goals"
    line (soappt), it sometimes collapses them into a single generic "Goals" heading
    instead. A one-directional check misses that collapsed case, so check both ways.
    """
    labels = CARRY_SECTION_LABELS.get(form_id, [])
    heading_lower = heading.lower()
    return any(label.lower() in heading_lower or heading_lower in label.lower() for label in labels)


def enforce_carry_tags(form_id: str, sections: list[dict]) -> list[dict]:
    """Strip a [[CARRIED FORWARD]] flag from any section whose heading isn't one of
    this form's actual carry-forward labels (app.generate.forms.CARRY_SECTION_LABELS).
    """
    out = []
    for s in sections:
        allowed = _is_carry_forward_label(form_id, s["heading"])
        out.append({**s, "carried_forward": bool(s["carried_forward"]) and allowed})
    return out


def drop_unperformed_treatment_sections(sections: list[dict]) -> list[dict]:
    """Drop any section whose body opens with "Minutes: 0" — a reliable signal the
    model invented a placeholder for a treatment that was never performed, rather
    than the (clinically nonsensical) idea that a treatment took zero minutes.
    """
    return [s for s in sections if not _ZERO_MINUTES_RE.match(s["body"])]


def flag_code_sections(sections: list[dict]) -> list[dict]:
    """CPT/ICD-10 code assignment is a billing/coding judgment call, not a
    transcription task — observed the model confidently fabricate both a CPT code
    and an ICD-10 code that didn't match the stated condition, for a dictation that
    never mentioned any code. Replace any CPT/ICD-headed section's body with an
    explicit gap marker rather than ever pass through a model-guessed code.
    """
    out = []
    for s in sections:
        if _CODE_HEADING_RE.search(s["heading"]):
            out.append({**s, "body": "[[NEEDS: code not stated by therapist — clinician to assign]]"})
        else:
            out.append(s)
    return out


# Block-format templates put codes as body FIELD lines ("Medical Diagnosis (ICD-10): M54.5",
# "Treatment Procedures (CPT): 97110") rather than their own heading, so flag_code_sections (which
# matches on the section HEADING) misses a model-authored code there. Observed: the block Initial Eval
# fabricated ICD-10 "M54.5" (low back pain) for a shoulder note and it passed through unflagged. Any
# field line whose LABEL names CPT or ICD gets its value replaced with the same gap marker — the model
# never authors a billing code (rule 12); the clinician assigns it.
_CODE_FIELD_LINE_RE = re.compile(r"(?im)^([^\n:]*\b(?:CPT|ICD(?:-?10)?)\b[^\n:]*:)[^\n]*$")


def flag_code_field_lines(sections: list[dict]) -> list[dict]:
    """Replace the value on any 'CPT'/'ICD'-labelled body field line with the code gap marker (the
    body-line analogue of flag_code_sections, for block-format notes that keep codes as fields)."""
    out = []
    for s in sections:
        body = _CODE_FIELD_LINE_RE.sub(
            lambda m: m.group(1) + " [[NEEDS: code not stated by therapist — clinician to assign]]",
            s["body"],
        )
        out.append(s if body == s["body"] else {**s, "body": body})
    return out


def normalize_strength_grades(sections: list[dict]) -> list[dict]:
    """Rewrite spelled-out manual muscle test grades into clinical shorthand
    ("three plus to four minus out of five" -> "3+/5 to 4-/5"). The range form is
    substituted first so its single trailing "out of five" (which applies to both
    sides) isn't consumed by the single-grade pass.
    """
    out = []
    for s in sections:
        body = _MMT_RANGE_RE.sub(
            lambda m: f"{_grade_token(m.group(1), m.group(2))} to {_grade_token(m.group(3), m.group(4))}",
            s["body"],
        )
        body = _MMT_SINGLE_RE.sub(lambda m: _grade_token(m.group(1), m.group(2)), body)
        out.append(s if body == s["body"] else {**s, "body": body})
    return out


def strip_carry_instruction_headings(sections: list[dict]) -> list[dict]:
    """Remove an echoed "[carry forward]" spec instruction from a section heading
    ("## Precautions [carry forward]" -> "## Precautions"). Cosmetic only — runs before
    enforce_carry_tags, which matches the section label either way."""
    out = []
    for s in sections:
        heading = _CARRY_INSTRUCTION_RE.sub("", s["heading"]).strip()
        out.append(s if heading == s["heading"] else {**s, "heading": heading})
    return out


def apply(form_id: str, sections: list[dict]) -> list[dict]:
    sections = drop_unperformed_treatment_sections(sections)
    sections = strip_carry_instruction_headings(sections)
    sections = enforce_carry_tags(form_id, sections)
    sections = flag_code_sections(sections)
    sections = flag_code_field_lines(sections)
    sections = normalize_strength_grades(sections)
    sections = strip_checklist_affirmations(sections)
    return sections
