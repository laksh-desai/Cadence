"""Medicare documentation checklist — the reviewer's questions, asked of every note before it leaves.

Outpatient therapy claims are denied on DOCUMENTATION far more than on coding: medical necessity
not shown, skilled care not described, minutes that don't support the units, goals that can't be
measured, a progress report with nothing to compare. This module asks, per note type, the questions
a Medicare Administrative Contractor's medical reviewer asks (the MAC outpatient-therapy checklist
and Medicare Benefit Policy Manual ch. 15 §220.3 — daily treatment note, evaluation / plan of care,
progress report, discharge note), and answers each from the note's own sections.

What it is and is not:
- Deterministic and explainable: every finding names the element and the section to fix. No model.
- A floor, not an approval. It cannot judge whether care was reasonable and necessary, and it
  cannot see what lives outside the note (the certified plan of care signature, the KX threshold,
  payer edits). A note that passes is one a reviewer can follow; it is not a promise of payment.
- It never edits the note. "fix" = a reviewer would likely deny or down-code as written;
  "check" = a weakness worth a look.

Billing elements (minutes per timed code, total treatment time, codes) are in `note_audit`, which
calls this module, so the Send button and the extension show one combined list.
"""

from __future__ import annotations

import re

from app.generate import billing_section, cpt

# --- vocabulary --------------------------------------------------------------------------

# Words that show the THERAPIST'S skill was needed — what makes a service "skilled" to a reviewer.
_SKILLED = re.compile(
    r"\b(cue[sd]?|cueing|facilitat\w*|guard\w*|contact guard|cga|min(imal|imum)? assist\w*|"
    r"mod(erate)? assist\w*|max(imal|imum)? assist\w*|stand-?by|sba|supervis\w*|tactile|verbal|"
    r"demonstrat\w*|instruct\w*|educat\w*|progress\w*|modif\w*|adjust\w*|monitor\w*|assess\w*|"
    r"analy[sz]\w*|correct\w*|feedback|graded|upgrad\w*|challeng\w*|safety)\b", re.I)
# A parameter a reviewer can check: distance, reps, time, load, angle, steps, a score.
_PARAMETER = re.compile(
    r"\b\d+(\.\d+)?\s*(ft|feet|foot|m|meters?|reps?|x|times|sets?|sec(onds?)?|s|min(utes)?|"
    r"lbs?|pounds?|kg|deg(rees)?|°|steps?|stairs?|laps?|/\s*\d+)\b|\b\d+\s*x\s*\d+\b", re.I)
_RESPONSE = re.compile(
    r"\b(toleran\w*|tolerat\w*|respon\w*|fatigu\w*|improv\w*|progress\w*|declin\w*|pain|"
    r"able to|unable|demonstrat\w*|required|needed|increas\w*|decreas\w*|better|worse)\b", re.I)
_GOAL_STATUS = re.compile(r"\b(met|not met|progressing|partially|discontinued|achiev\w*|goal)\b", re.I)
_COMPARISON = re.compile(r"\b(from|previous(ly)?|prior|baseline|initial(ly)?|up|down|improv\w*|"
                         r"declin\w*|compared|was|increas\w*|decreas\w*|start of care)\b", re.I)
_TIMEFRAME = re.compile(r"\b(\d+|one|two|three|four|five|six|seven|eight|ten|twelve)\s*"
                        r"(days?|weeks?|wks?|months?|visits?)\b|\bby (discharge|the end)\b", re.I)
_NUMBER = re.compile(r"\d")
_FREQUENCY = re.compile(r"\b(\d+|one|two|three|four|five)\s*(x|times)\s*(a|per|/)?\s*(week|wk)|"
                        r"\b(\d+|one|two|three|four|five)\s*/\s*(week|wk)|\bweekly\b|"
                        r"\b(once|twice) (a|per) week\b", re.I)
_DURATION = re.compile(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s*"
                       r"(weeks?|wks?|months?|visits?)\b", re.I)
_REHAB_POTENTIAL = re.compile(r"\b(rehab(ilitation)? potential|prognosis)\b", re.I)
_PLOF = re.compile(r"\b(prior level|plof|previously|before (the|her|his)|was (walking|independent|"
                   r"living))\b", re.I)
# Phrases a reviewer reads as UNSKILLED when they are all a section says.
_GENERIC = re.compile(r"^\W*(pt\.?|patient)?\s*(tolerated (treatment |session |it )?(well|good)|"
                      r"did well|continue (with )?(poc|plan( of care)?|current plan|same)|"
                      r"progressing( well)?|no (changes|complaints))\W*$", re.I)


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+", text or ""))


def _find(sections: list[dict], *labels: str) -> dict | None:
    """The section a label names: a heading that STARTS with it first ("Assessment Summary" for
    "assessment"), and only then one that merely contains it ("Musculoskeletal Assessment")."""
    for test in (lambda h, l: h.startswith(l), lambda h, l: l in h):
        for s in sections:
            h = (s.get("heading") or "").lower()
            if any(test(h, l.lower()) for l in labels):
                return s
    return None


def _body(sec: dict | None) -> str:
    return (sec or {}).get("body", "") if sec else ""


def _clean(text: str) -> str:
    """The text a reviewer reads: Cadence's own markers removed."""
    return re.sub(r"\[\[(NEEDS|CPT):[^\]]*\]\]", "", text or "").strip()


# --- the checks --------------------------------------------------------------------------

def check(form_id: str, sections: list[dict]) -> list[dict]:
    """Findings for this note: [{"level": "fix"|"check", "element": ..., "text": ...}]."""
    if form_id in cpt._NON_BILLING_FORMS:
        return []
    findings: list[dict] = []

    def add(level, element, text):
        findings.append({"level": level, "element": element, "text": text})

    clinical = [s for s in sections if not billing_section.is_billing_heading(s.get("heading"))]
    for s in clinical:
        body = _clean(s.get("body"))
        if body and _GENERIC.match(body):
            add("fix", "Skilled language",
                f"{s['heading']}: \"{body}\" on its own reads as unskilled care to a reviewer — say "
                "what you did, what you measured, and how the patient responded.")

    if form_id == "followup":
        _daily(clinical, add)
    elif form_id in ("initial", "initial_updated"):
        _evaluation(clinical, add, block=(form_id == "initial_updated"))
    elif form_id == "reeval":
        _reassessment(clinical, add)
    elif form_id == "discharge":
        _discharge(clinical, add)
    return findings


def _treatments(sections):
    return [s for s in sections if cpt.code_for_heading(s.get("heading", ""))]


def _daily(sections, add):
    treatments = _treatments(sections)
    if not treatments:
        add("fix", "Interventions", "No treatment section — a daily note must document each "
            "intervention provided.")
    for t in treatments:
        body = _clean(t.get("body"))
        if not _SKILLED.search(body):
            add("fix", "Skilled care",
                f"{t['heading']}: describe the skilled input (cues, facilitation, guarding, assist "
                "level, progression) — without it the service reads as one the patient could do alone.")
        if not _PARAMETER.search(re.sub(r"(?i)minutes?\s*:\s*\d+", "", body)):
            add("check", "Treatment parameters",
                f"{t['heading']}: no measurable parameter (distance, sets x reps, time, load).")
    assessment = _clean(_body(_find(sections, "assessment", "response to treatment")))
    if not assessment:
        add("fix", "Patient response", "No Assessment — document the patient's response to "
            "today's treatment and why skilled PT is still needed.")
    else:
        if not _RESPONSE.search(assessment):
            add("check", "Patient response", "Assessment does not state how the patient responded.")
        if not (_GOAL_STATUS.search(assessment) or _GOAL_STATUS.search(
                _body(_find(sections, "short-term goals")) + _body(_find(sections, "long-term goals")))):
            add("check", "Progress toward goals", "Nothing links today's session to the goals — "
                "note progress toward at least one goal.")
        if not re.search(r"\b(skill\w*|continue\w*|requires?|needs?|necess\w*|risk|deficit\w*|"
                         r"limit\w*|impair\w*)\b", assessment, re.I):
            add("check", "Medical necessity", "Assessment does not say why skilled PT is still "
                "required (remaining deficits, fall risk, safety).")
    if not _clean(_body(_find(sections, "plan"))):
        add("fix", "Plan", "No Plan — state the focus of the next visit.")


def _goals(sections, add, *, measurable_required=True):
    for label in ("Short-Term Goals", "Long-Term Goals"):
        body = _clean(_body(_find(sections, label.lower())))
        if not body:
            add("fix", "Goals", f"No {label} — the plan of care must have measurable goals.")
            continue
        if measurable_required and not _NUMBER.search(body) and not re.search(
                r"\b(independent\w*|modified independent|supervision|stand-?by|min|mod|max)\b", body, re.I):
            add("fix", "Measurable goals", f"{label}: no measurable target (distance, score, "
                "assist level) — a reviewer cannot tell when it is met.")
        if measurable_required and not _TIMEFRAME.search(body):
            add("check", "Goal timeframe", f"{label}: no timeframe (\"in 3 weeks\").")


def _evaluation(sections, add, *, block=False):
    text = "\n".join(_clean(s.get("body")) for s in sections)
    if block:
        # The 4-block evaluation keeps everything inside Subjective/Objective/Assessment/Plan.
        if not re.search(r"short[- ]term", text, re.I) or not re.search(r"long[- ]term", text, re.I):
            add("fix", "Goals", "Short- and long-term goals not found in the Plan block.")
    else:
        _goals(sections, add)
    if not _find(sections, "diagnos") and "diagnos" not in text.lower():
        add("fix", "Diagnosis", "No diagnosis documented.")
    if not _PLOF.search(text):
        add("check", "Prior level of function", "Prior level of function is not stated — it is "
            "what the long-term goals are measured against.")
    # The baseline must come from the EXAM, not from a goal or the plan ("walk 150 ft in 3 weeks").
    exam = "\n".join(_clean(s.get("body")) for s in sections
                     if not re.search(r"goal|plan", s.get("heading", ""), re.I))
    if block:
        exam = _clean(_body(_find(sections, "objective"))) or text
    if not re.search(r"\b\d+\s*/\s*\d+|\b\d+\s*(sec|seconds|ft|feet|degrees|°)", exam, re.I):
        add("fix", "Objective tests and measures", "No objective measurement (ROM, strength, a "
            "balance or gait test, distance) — the evaluation needs a measurable baseline.")
    if not _REHAB_POTENTIAL.search(text):
        add("check", "Rehab potential", "Rehab potential / prognosis is not stated.")
    plan = _clean(_body(_find(sections, "plan of treatment", "plan"))) or text
    if not _FREQUENCY.search(plan):
        add("fix", "Plan of care: frequency", "Visit frequency (e.g. 2x/week) is not in the plan.")
    if not _DURATION.search(plan):
        add("fix", "Plan of care: duration", "Plan duration (e.g. 8 weeks) is not in the plan.")
    if not re.search(r"\b(gait|neuromuscular|balance|therapeutic|exercise|strength|transfer|"
                     r"training|activities|manual|home (exercise )?program)\b", plan, re.I):
        add("check", "Plan of care: interventions", "The plan does not name the planned interventions.")
    if not re.search(r"\b(skill\w*|necess\w*|requires?|needs?|deficit\w*|impair\w*|limit\w*|risk)\b",
                     _clean(_body(_find(sections, "assessment"))) or text, re.I):
        add("check", "Medical necessity", "Assessment does not state why skilled PT is needed.")


def _reassessment(sections, add):
    if not _clean(_body(_find(sections, "reporting period"))):
        add("fix", "Reporting period", "Reporting period (dates / visit number) is missing — "
            "required on every progress report.")
    measures = _clean(_body(_find(sections, "objective measures", "functional mobility")))
    if not measures or not _NUMBER.search(measures):
        add("fix", "Objective measures", "No objective measure today — a progress report must "
            "show measured change.")
    elif not _COMPARISON.search(measures):
        add("check", "Comparison", "Objective measures are not compared with earlier values.")
    status = _clean(_body(_find(sections, "goal status")))
    if not status or not _GOAL_STATUS.search(status):
        add("fix", "Goal status", "Each previous goal needs a status (MET / PROGRESSING / NOT MET).")
    assess = _clean(_body(_find(sections, "assessment")))
    if not re.search(r"\b(skill\w*|necess\w*|requires?|needs?|continue\w*|deficit\w*|risk)\b", assess, re.I):
        add("fix", "Justification", "Assessment does not justify continued skilled therapy.")
    _goals(sections, add)
    if not _clean(_body(_find(sections, "plan"))):
        add("fix", "Plan", "No updated plan of treatment.")


def _discharge(sections, add):
    if not _clean(_body(_find(sections, "reason for discharge"))):
        add("fix", "Reason for discharge", "Reason for discharge is missing.")
    for label in ("Short-Term Goals", "Long-Term Goals"):
        body = _clean(_body(_find(sections, label.lower())))
        if not body:
            add("fix", "Final goal status", f"{label}: final status of each goal is missing.")
        elif not _GOAL_STATUS.search(body):
            add("check", "Final goal status", f"{label}: mark each goal MET / NOT MET / DISCONTINUED.")
    status = _clean(_body(_find(sections, "functional status", "objective measures")))
    if not status:
        add("fix", "Status at discharge", "Functional status at discharge is missing.")
    elif not _COMPARISON.search(status) and not _clean(_body(_find(sections, "initial status"))):
        add("check", "Comparison", "Discharge status is not compared with the start of care.")
    if not _clean(_body(_find(sections, "home exercise"))):
        add("check", "Home program", "No home exercise program or education documented.")
    if not _clean(_body(_find(sections, "recommendation", "equipment"))):
        add("check", "Recommendations", "No discharge recommendations or follow-up.")
