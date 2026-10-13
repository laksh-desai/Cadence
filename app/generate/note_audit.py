"""Pre-send billing audit: what is missing that would stop Office Ally (or Medicare) paying.

Runs on a SAVED note, right before it is sent to Office Ally — from Cadence's Send button and from
the Chrome extension's panel, which both call `GET /api/patients/{pid}/notes/{nid}/audit`. ONE
implementation, so the two can never disagree about whether a note is ready.

Deterministic, reads only the note's own sections, never edits them. Each finding is
`{"level": "fix" | "check", "text": ...}`:
- "fix"   — this will not be paid as written (a timed code with no minutes, no total treatment
            time, no billable code at all). Fix it in Cadence before sending.
- "check" — the clinician should look (codes nobody confirmed yet, minutes that disagree between a
            treatment section and the Billing section, open gaps in the Billing section).
The audit never blocks by itself; the caller shows it before the copy and the clinician decides.
"""

from __future__ import annotations

import re

from app.generate import billing_section, compliance, cpt

_MINUTES_RE = re.compile(r"\bminutes?\s*:\s*(\d{1,3})\b", re.IGNORECASE)
_CHIP_RE = re.compile(r"\[\[CPT:\s*(\d{4}[0-9A-Z])\s+([^\]]*?)\]\]")
_LINE_MINUTES_RE = re.compile(r"\]\]\s*(\d{1,3})\s*min\b", re.IGNORECASE)
_TOTAL_TIME_RE = re.compile(r"total treatment time:\s*(\d{1,3})", re.IGNORECASE)
_TOTAL_TIMED_RE = re.compile(r"total timed minutes:\s*(\d{1,3})", re.IGNORECASE)
_NEEDS_RE = re.compile(r"\[\[NEEDS:\s*([^\]]*)\]\]")
_EVAL_CODE_RE = re.compile(r"\b9716[1-4]\b")


def audit(form_id: str, sections: list[dict]) -> dict:
    findings: list[dict] = []

    def fix(text): findings.append({"level": "fix", "text": text})
    def check(text): findings.append({"level": "check", "text": text})

    if form_id in cpt._NON_BILLING_FORMS:
        return {"ready": True, "findings": [], "codes": [], "total_timed_minutes": None,
                "total_treatment_minutes": None}

    billing_sec = next((s for s in sections if billing_section.is_billing_heading(s.get("heading"))), None)
    treatments = []
    for s in sections:
        if billing_section.is_billing_heading(s.get("heading")):
            continue
        hit = cpt.code_for_heading(s.get("heading", ""))
        if hit:
            m = _MINUTES_RE.search(s.get("body", ""))
            treatments.append({"heading": s["heading"].strip(), "code": hit[0], "label": hit[1],
                               "timed": cpt.is_timed(hit[0]),
                               "minutes": int(m.group(1)) if m else None})

    for s in sections:
        if (billing_section.UNDICTATED_FLAG in s.get("body", "")
                or "according to the dictation — remove this section" in s.get("body", "")):
            fix(f"{s['heading'].strip()} is in the note but was not in the dictation — remove it "
                "unless it was performed today (billing a service not provided is an overbill).")
    for t in treatments:
        if t["timed"] and not t["minutes"]:
            fix(f"{t['heading']} ({t['code']}) has no minutes — a timed code is not paid without "
                "its minutes.")

    codes, billing_minutes = [], {}
    body = (billing_sec or {}).get("body", "")
    for line in body.splitlines():
        for m in _CHIP_RE.finditer(line):
            code, rest = m.group(1), m.group(2)
            confirmed = not rest.rstrip().endswith("confirm")
            mins = _LINE_MINUTES_RE.search(line)
            codes.append({"code": code, "label": re.sub(r"\s*—\s*confirm$", "", rest).strip(),
                          "confirmed": confirmed,
                          "minutes": int(mins.group(1)) if mins else None})
            if mins:
                billing_minutes[code] = int(mins.group(1))
    # Codes confirmed in the treatment sections count too (a note saved before the Billing section
    # existed has only those).
    if not codes:
        for s in sections:
            for m in _CHIP_RE.finditer(s.get("body", "")):
                rest = m.group(2)
                codes.append({"code": m.group(1),
                              "label": re.sub(r"\s*—\s*confirm$", "", rest).strip(),
                              "confirmed": not rest.rstrip().endswith("confirm"), "minutes": None})

    total_time = _first_int(_TOTAL_TIME_RE, body)
    total_timed = _first_int(_TOTAL_TIMED_RE, body)
    is_eval = cpt.is_eval_form(form_id)

    if billing_sec is None and cpt.billing_enabled():
        check("This note has no Billing section (it was written before billing was switched on). "
              "Check the codes and minutes by hand before sending.")
    if not codes and not treatments and not is_eval:
        if form_id == "discharge":
            # A discharge summary written without a treatment that day is documentation only.
            check("No treatment code on this discharge — fine if no treatment was given today.")
        else:
            fix("No CPT code is documented for this visit — nothing would be billed.")
    unconfirmed = [c for c in codes if not c["confirmed"]]
    if unconfirmed:
        check(f"{len(unconfirmed)} code(s) not confirmed yet: "
              + ", ".join(c["code"] for c in unconfirmed) + ". Confirm or remove them in Cadence.")
    for t in treatments:
        bm = billing_minutes.get(t["code"])
        if t["minutes"] and bm and bm != t["minutes"]:
            check(f"{t['heading']}: the section says {t['minutes']} min but the Billing section "
                  f"says {bm} min — make them match.")
    has_timed = any(t["timed"] for t in treatments) or any(cpt.is_timed(c["code"]) for c in codes)
    if has_timed and total_time is None:
        fix("Total treatment time (minutes) is not documented — Medicare requires it.")
    if total_time is not None and total_timed is not None and total_timed > total_time:
        fix(f"Timed minutes ({total_timed}) are more than the total treatment time ({total_time}).")
    if is_eval and not _EVAL_CODE_RE.search(" ".join(s.get("body", "") for s in sections)):
        check("No evaluation code yet — choose 97161 (low), 97162 (moderate) or 97163 (high).")
    for gap in _NEEDS_RE.findall(body):
        g = gap.strip()
        if g.lower().startswith(("minutes for", "total treatment time")):
            continue  # already reported above as a "fix"
        check("Billing: " + g)

    # The Medicare documentation checklist (skilled care, response, goals, plan, ...) — the other
    # half of what a reviewer reads. Billing findings come first: they are the money.
    for f in compliance.check(form_id, sections):
        findings.append({"level": f["level"], "text": f["element"] + ": " + f["text"]})

    return {
        "ready": not any(f["level"] == "fix" for f in findings),
        "findings": findings,
        "codes": codes,
        "total_timed_minutes": total_timed,
        "total_treatment_minutes": total_time,
    }


def _first_int(rx: re.Pattern, text: str) -> int | None:
    m = rx.search(text or "")
    return int(m.group(1)) if m else None
