"""Deterministic CPT suggestion from the stated intervention (CLAUDE.md rule 12).

The MODEL never authors codes — rule 12, after it was caught fabricating a wrong ICD-10. But
outpatient PT CPT codes are a small, closed set that maps 1:1 from the intervention the therapist
explicitly named (the note's own treatment-section headings), so the code is a deterministic LOOKUP
from a stated fact, NOT an inference. Each matched section gets a confirmable ``[[CPT: ...]]``
suggestion the clinician reviews, edits, or removes before signing.

The judgment-heavy cases are deliberately NOT auto-assigned, per the liability boundary:
  * Evaluation complexity (97161/97162/97163) is surfaced as a review flag for the clinician to pick.
  * Units / the 8-minute rule / modifiers are left to the biller — payer-specific and high-liability.

Matching is on the section HEADING (the intervention's own section), never prose, so a passing
mention of an intervention in some other section can't misfire.
"""

import re

# A PT CPT/G code the MODEL may have written (the followup/progress specs literally ask for "cpt",
# so the 4B model sometimes emits one — in the heading or body — and sometimes the WRONG one). We
# strip it from a matched treatment section and substitute the table's trusted code, so per rule 12
# the only code ever shown is the deterministic one, never the model's guess.
_MODEL_CODE_RE = re.compile(r"\s*\b(?:97\d{3}|G0283)\b")

# (heading substring, CPT code, human label). Order matters: specific phrases come before generic
# ones because matching stops at the first hit (so "neuromuscular re-education" is never taken as a
# plain "exercise").
_CPT_RULES: list[tuple[str, str, str]] = [
    ("neuromuscular re", "97112", "Neuromuscular Re-education"),
    ("gait train", "97116", "Gait Training"),
    ("manual therapy", "97140", "Manual Therapy"),
    ("therapeutic activit", "97530", "Therapeutic Activities"),
    ("therapeutic exercise", "97110", "Therapeutic Exercise"),
    ("aquatic", "97113", "Aquatic Therapy"),
    ("self-care", "97535", "Self-Care/Home Management Training"),
    ("home management", "97535", "Self-Care/Home Management Training"),
    ("ultrasound", "97035", "Ultrasound"),
    ("iontophoresis", "97033", "Iontophoresis"),
    ("paraffin", "97018", "Paraffin Bath"),
    ("whirlpool", "97022", "Whirlpool"),
    ("diathermy", "97024", "Diathermy"),
    ("vasopneumatic", "97016", "Vasopneumatic Device"),
    ("mechanical traction", "97012", "Mechanical Traction"),
    ("electrical stim", "97014", "Electrical Stimulation"),
    ("e-stim", "97014", "Electrical Stimulation"),
    ("hot/cold", "97010", "Hot/Cold Packs"),
    ("hot pack", "97010", "Hot/Cold Packs"),
    ("cold pack", "97010", "Hot/Cold Packs"),
    ("massage", "97124", "Massage Therapy"),
    ("wheelchair management", "97542", "Wheelchair Management"),
    ("orthotic", "97760", "Orthotic Management/Training"),
    ("group therap", "97150", "Group Therapeutic Procedure"),
]

# Timed ("constant attendance") outpatient-PT codes: billed in 15-minute units, so the Medicare
# 8-minute rule applies to them and ONLY to them. Keyed by CODE rather than by a _CPT_RULES row
# because several rows map to the same code (97010 x3, 97014 x2, 97535 x2) — "timed" is a property
# of the code, not of the heading->code mapping, and a per-row flag could disagree with itself.
#
# Everything else in the table is SERVICE-BASED (one unit per session regardless of duration) and
# must be EXCLUDED from the timed-minutes total: 97010 hot/cold, 97012 mechanical traction, 97014
# unattended e-stim, 97016 vasopneumatic, 97018 paraffin, 97022 whirlpool, 97024 diathermy, and
# 97150 group therapy. The 97161/97162/97163 evaluations are likewise one unit each and never enter
# the total (they aren't in _CPT_RULES at all — see _EVAL_FORMS below).
TIMED_CODES: frozenset[str] = frozenset({
    "97032", "97033", "97034", "97035", "97036",
    "97110", "97112", "97113", "97116", "97124", "97140",
    "97530", "97535", "97542", "97760",
})


def is_timed(code: str) -> bool:
    """True if `code` is billed in 15-minute units (so the 8-minute rule applies to its minutes)."""
    return code in TIMED_CODES


# Evaluation forms bill a per-visit evaluation CPT whose complexity level is a clinician judgment
# (not a treatment-section lookup), so it is surfaced for selection rather than auto-assigned.
_EVAL_FORMS = {"initial", "initial_updated"}

# Patient-facing and auxiliary notes are NOT billing documents — a treatment CPT code must never
# land on a patient's plain-language After-Visit Letter, a Referral Letter to another provider, or
# an internal SMART-goal / issues list.
_NON_BILLING_FORMS = {"avletter", "referral", "smart", "issues"}


def code_for_heading(heading: str) -> tuple[str, str] | None:
    """Return (code, label) for a treatment-section heading, or None if the heading doesn't name a
    mappable intervention."""
    h = (heading or "").lower()
    for sub, code, label in _CPT_RULES:
        if sub in h:
            return code, label
    return None


def suggest_codes(sections: list[dict], form_id: str) -> tuple[list[dict], list[str]]:
    """Attach a confirmable ``[[CPT: ...]]`` suggestion to each treatment section whose heading names
    a mappable intervention, and return the codes that require clinician JUDGMENT (the evaluation
    complexity level) as review flags. Never auto-assigns eval complexity, units, or modifiers.
    Idempotent per section (a section already carrying a ``[[CPT:`` marker is left alone).
    """
    if form_id in _NON_BILLING_FORMS:
        return list(sections), []  # patient-facing / auxiliary note — never a billing document
    out: list[dict] = []
    for s in sections:
        hit = code_for_heading(s["heading"])
        if not hit or "[[CPT:" in s["body"]:
            out.append(s)  # not a treatment section, or already suggested (idempotent)
            continue
        code, label = hit
        # Strip any code the MODEL wrote (rule 12 — could be wrong), then append the trusted one.
        heading = _MODEL_CODE_RE.sub("", s["heading"]).strip()
        body = _MODEL_CODE_RE.sub("", s["body"]).rstrip()
        out.append({**s, "heading": heading, "body": f"{body} [[CPT: {code} {label} — confirm]]"})
    extra: list[str] = []
    if form_id in _EVAL_FORMS:
        extra.append(
            "Assign the PT evaluation CPT — 97161 (low), 97162 (moderate), or 97163 (high) "
            "complexity — select the level for this visit."
        )
    return out, extra
