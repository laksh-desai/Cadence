"""The note's "Billing — CPT & Minutes" section, written by CODE from the billing draft.

Why a section, and why code:
- Office Ally pays only what the note documents, and Medicare's daily-note checklist needs every
  timed code's minutes, the total timed minutes and the total treatment time. The billing draft
  (`billing.extract`) already computes all of that from the DICTATION, but it was response
  metadata and vanished on Save. As a section it is saved with the note, is editable in review,
  and reaches Office Ally like any other section.
- The model never writes it (CLAUDE.md rule 12): every value comes from the dictation-side
  extractor, and anything missing is an amber `[[NEEDS: ...]]` gap, never a guess.

Codes are `[[CPT: ... — confirm]]` chips, so the review card's Confirm / Remove buttons rewrite
them here exactly as they do in the treatment sections, and the pre-send audit
(`note_audit.audit`) can tell a confirmed code from one nobody looked at.
"""

from __future__ import annotations

from app.generate import billing, cpt
from app.generate.prompt import clean_dictation as _clean

HEADING = "Billing — CPT & Minutes"

_REEVAL_LINE = (
    "[[NEEDS: Re-evaluation 97164 — bill ONLY if a significant change is documented (new findings, "
    "unexpected change, or no response to the plan); a routine Progress Report is not billable]]"
)


def is_billing_heading(heading: str) -> bool:
    h = (heading or "").lower()
    return h.startswith("billing") or "cpt & minutes" in h


def build(draft: billing.BillingDraft, transcript: str, form_id: str) -> dict:
    """One section summarising what to bill for this visit. Always returned for a billable form,
    so a visit with nothing billable says so instead of silently omitting the section."""
    lines: list[str] = []
    performed = [h for h in draft.interventions if h.status == billing.BILLABLE_STATUS]
    uncertain = [h for h in draft.interventions if h.status == "uncertain"]

    for h in performed:
        lines.append(_code_line(h))
    for h in uncertain:
        lines.append(f"[[NEEDS: confirm {h.code} {h.label} was performed today — the dictation is "
                     f"unclear (\"{_short(h.clause)}\")]]")
    if form_id in cpt._REEVAL_FORMS:
        lines.append(_REEVAL_LINE)
    if not performed and not uncertain:
        lines.append("[[NEEDS: no billable treatment was found in the dictation — add each "
                     "treatment with its minutes, or confirm none was billed today]]")

    timed = [h for h in performed if h.timed]
    if timed and draft.total_timed_minutes:
        lines.append(f"Total timed minutes: {draft.total_timed_minutes}")
    session, corrected_from = billing.session_total_detail(_clean(transcript))
    if session is not None:
        lines.append(f"Total treatment time: {session} min")
        if corrected_from is not None:
            lines.append(f"[[NEEDS: the dictation said {corrected_from} then {session} minutes for "
                         f"the total — confirm {session}]]")
        if timed and draft.total_timed_minutes > session:
            lines.append(f"[[NEEDS: timed minutes ({draft.total_timed_minutes}) exceed the total "
                         f"treatment time ({session}) — correct one of them]]")
    elif performed:
        lines.append("[[NEEDS: total treatment time in minutes — Medicare requires it on every "
                     "daily note]]")
    if draft.units and draft.units.total_units:
        per = ", ".join(f"{code} x{n}" for code, n in draft.units.per_code if n)
        lines.append(f"Units (8-minute rule): {draft.units.total_units} ({per})")
        if draft.method_disagreement and draft.units_alt:
            lines.append(f"Note: the AMA rule-of-eights count is {draft.units_alt.total_units} "
                         "units — the biller decides which method applies.")

    for c in draft.icd_candidates:
        side = "" if c.laterality_stated or not c.lateralized else " (side not stated — confirm)"
        lines.append(f"ICD-10 (confirm): {c.code} {c.label}{side}")

    return {"heading": HEADING, "body": "\n".join(lines), "carried_forward": False}


UNDICTATED_FLAG = ("[[NEEDS: this treatment was not found in the dictation — remove this section "
                   "unless it was performed today]]")


def flag_undictated_treatments(sections: list[dict], draft: billing.BillingDraft) -> list[dict]:
    """Flag a treatment section the MODEL wrote that the dictation never mentions.

    Measured (field test, 2026-10): on a 40-word Daily Visit dictation naming gait training and
    neuro re-ed, the model added a Therapeutic Exercise section with "Minutes: 35" — the two real
    durations added together — and it earned a CPT chip. A treatment in the note that is not in the
    dictation is the overbilling case, so it is flagged in the section itself, where the clinician
    is reading. Codes the dictation mentions in ANY status (performed, uncertain, planned, ...) are
    left alone: those have their own handling in the Billing section.
    """
    # Billable or still-to-confirm mentions keep their section; everything else (declined /
    # negated, a prior visit, planned, home program) means the dictation says it was NOT done today.
    # Field test 2026-10: "patient declined soft-tissue mobilization" became a Manual Therapy section
    # with a CPT chip, unflagged, because the code had been "mentioned".
    kept = {h.code for h in draft.interventions if h.status in (billing.BILLABLE_STATUS, "uncertain")}
    excluded = {h.code: h.status for h in draft.interventions if h.code not in kept}
    out = []
    for s in sections:
        hit = cpt.code_for_heading(s.get("heading", ""))
        body = s.get("body", "")
        if hit and hit[0] not in kept and "[[NEEDS: this treatment" not in body:
            flag = (NOT_TODAY_FLAG.format(why=_WHY.get(excluded[hit[0]], "not performed today"))
                    if hit[0] in excluded else UNDICTATED_FLAG)
            s = {**s, "body": (body.rstrip() + " " + flag).strip()}
        out.append(s)
    return out


NOT_TODAY_FLAG = ("[[NEEDS: this treatment was {why} according to the dictation — remove this "
                  "section unless it was performed today]]")
_WHY = {"negated": "declined or not done", "prior_visit": "from a previous visit",
        "planned": "only planned", "home_program": "a home program item"}


def _code_line(h: billing.InterventionHit) -> str:
    chip = f"[[CPT: {h.code} {h.label} — confirm]]"
    if not h.timed:
        return f"{chip} untimed (1 unit)"
    if h.minutes:
        return f"{chip} {h.minutes} min"
    return (f"{chip} [[NEEDS: minutes for {h.label} — a timed code is not paid without its "
            "minutes]]")


def _short(text: str, n: int = 80) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"
