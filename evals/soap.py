"""Python port of the UI's SOAP bucketing (app/ui/static/app.js `SOAP_RULES` / `soapBlockFor`).

Cadence GENERATES field-per-section notes; S/O/A/P is a grouping applied afterward, for the
"Copy for Office Ally" control. That classifier lives in JavaScript, so scoring it offline
needs a port.

A rule list duplicated across two languages drifts. `tests/test_soap_parity.py` guards against
that by parsing the array back out of app.js and asserting the two are identical, which keeps
the JS as the single source of truth without restructuring the frontend. If that test fails,
the fix is to update THIS file to match app.js — not the other way round.
"""

from __future__ import annotations

SOAP_LABELS = {"S": "Subjective", "O": "Objective", "A": "Assessment", "P": "Plan"}
SOAP_ORDER = ("S", "O", "A", "P")

# Order matters: first substring hit wins, so specific phrases precede generic ones.
# Mirrors app.js exactly, including ordering and the disambiguator block.
SOAP_RULES: list[tuple[str, str]] = [
    # Subjective — history / patient-reported / visit context.
    ("chief complaint", "S"), ("history of present", "S"), ("summary of daily", "S"),
    ("social history", "S"), ("living environment", "S"), ("referral", "S"), ("precaution", "S"),
    ("medication", "S"), ("allerg", "S"), ("patient goal", "S"), ("subjective", "S"), ("complaint", "S"),
    # Plan — targets + next steps (checked before the objective/assessment generics).
    ("short-term goal", "P"), ("long-term goal", "P"), ("plan", "P"), ("recommendation", "P"),
    ("home program", "P"), ("hep", "P"), ("goal", "P"),
    # Disambiguators — headings containing a generic word that belong elsewhere.
    ("response to treatment", "A"), ("functional status", "A"),
    ("functional mobility", "O"), ("objective summary", "O"), ("musculoskeletal", "O"),
    # Objective — exam findings + treatments / modalities.
    ("range of motion", "O"), ("strength", "O"), ("mmt", "O"), ("gait", "O"), ("mobility", "O"),
    ("vitals", "O"), ("cardiopulmonary", "O"), ("pain", "O"), ("fall risk", "O"), ("other systems", "O"),
    ("coordination", "O"), ("sensation", "O"), ("edema", "O"), ("observation", "O"), ("posture", "O"),
    ("special test", "O"), ("outcome", "O"),
    ("therapeutic exercise", "O"), ("gait training", "O"), ("manual therapy", "O"), ("neuromuscular", "O"),
    ("therapeutic activit", "O"), ("ultrasound", "O"), ("e-stim", "O"), ("electrical stim", "O"),
    ("massage", "O"), ("traction", "O"), ("modalit", "O"), ("minutes", "O"), ("treatment", "O"),
    # Assessment — clinical judgment (generic, last, so the specifics above win).
    ("assessment", "A"), ("diagnos", "A"), ("impression", "A"), ("rehab potential", "A"),
    ("prognosis", "A"), ("justification", "A"), ("skilled service", "A"), ("clinical complexity", "A"),
]


def soap_block_for(heading: str) -> str:
    """Bucket a section heading into S/O/A/P. Unmatched clinical content defaults to
    Objective, exactly as app.js does."""
    h = (heading or "").lower()
    for keyword, block in SOAP_RULES:
        if keyword in h:
            return block
    return "O"


def soap_groups(sections: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {k: [] for k in SOAP_ORDER}
    for s in sections or ():
        groups[soap_block_for(s.get("heading", ""))].append(s)
    return groups


def coverage(sections: list[dict]) -> dict[str, int]:
    """Section count per SOAP block — a note leaving a block empty is one the clinician
    would have to fill by hand when copying into the EHR."""
    return {k: len(v) for k, v in soap_groups(sections).items()}
