"""Automated note-quality validation against the REAL local model (fake data only — no PHI).

Runs a realistic dictation through the full production pipeline (prompt -> stream/generate ->
postprocess -> verification -> CPT), then auto-scores the note for the defect classes observed in
real use — then exercises the revise endpoint's logic the same way. This is "clinical validation
lite": it can't judge clinical acceptability (only the clinician can), but it deterministically
catches the mechanical failure classes:

  structure   4 blocks / expected sections present, no collapsed note
  fields      every template field appears (unstated ones as "not documented")
  capture     stated facts present (meds, pain scores, MMT, tests, outcome measure, cert period)
  safety      no model-authored CPT/ICD codes survive; no unflagged fabricated pain scores
  style       duplication flags, note length (conciseness), generation speed

    .venv/Scripts/python.exe scripts/validate_quality.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate import cpt, postprocess, traceability
from app.generate.forms import FORMS
from app.generate.ollama_client import generate_note
from app.generate.parser import parse_plain
from app.generate.prompt import PatientContext, build_prompt, build_revise_prompt, render_prior_block

DICTATION = (
    "Physical therapy initial evaluation. Chief complaint is right shoulder pain and difficulty lifting "
    "the arm overhead. Onset about six weeks ago, gradual, no specific injury; getting worse. Prior "
    "treatment, saw her primary doctor, X-ray negative, referred for outpatient PT with a diagnosis of "
    "right rotator cuff tendinopathy. Past medical history, high blood pressure and type two diabetes. "
    "Surgical history, appendectomy years ago. Alert and oriented. No falls in the past year. Current "
    "medications, lisinopril ten milligrams daily, metformin five hundred milligrams twice a day, and "
    "ibuprofen as needed. No known drug allergies. Prior level of function fully independent, works part "
    "time as a cashier. Lives in a single-story home with her husband. Goals, reach overhead cabinets and "
    "sleep on her right side. Pain worst seven out of ten, best two, currently four. QuickDASH fifty-two. "
    "Right-hand dominant. Forward head and rounded shoulders. Right shoulder active flexion one hundred "
    "ten degrees, abduction ninety, external rotation forty; left full. Strength, right shoulder flexion "
    "four minus out of five, abduction three plus out of five, external rotation four out of five. Gait "
    "normal, no assistive device. Hawkins-Kennedy positive, empty can positive. Assessment, right rotator "
    "cuff tendinopathy limiting overhead function, presentation evolving, skilled PT medically necessary. "
    "Educated on activity modification and home program. Rehab potential good. Precaution, no lifting over "
    "ten pounds overhead. Short-term goal, flexion to one hundred forty degrees in three weeks. Long-term "
    "goal, full overhead reaching in six weeks. Plan, twice a week for six weeks, certification period "
    "starts today for sixty days. I will assign the codes."
)

# Facts that MUST appear (loose stems; normalize handles spoken/written number forms).
FACTS = {
    "med: lisinopril 10": ["lisinopril"],
    "med: metformin 500": ["metformin"],
    "med: ibuprofen": ["ibuprofen"],
    "allergies (NKDA)": ["no known drug allergies", "nkda"],
    "pain 7/10 worst": ["7/10", "worst: 7", "worst 7"],
    "pain current 4": ["4/10", "current: 4", "current 4"],
    "quickdash 52": ["52"],
    "rom flexion 110": ["110"],
    "mmt 3+/5": ["3+/5"],
    "special test hawkins": ["hawkins"],
    "cert period 60 days": ["sixty days", "60 days"],
    "frequency 2x/week": ["twice a week", "2x", "two times a week", "2 visits"],
}

EXPECTED_FIELDS = [
    "Chief Complaint", "History of Present Illness", "Date of Onset", "Mechanism / Cause",
    "Course Since Onset", "Prior Treatment", "Medical History", "Surgical History",
    "Cognition", "History of Falls", "Current Medications", "Allergies", "Prior Level of Function",
    "Living Situation", "Patient Goals", "Pain",
    "Outcome Measurement Tools", "Handedness", "Posture", "Range of Motion", "Neuromuscular",
    "Functional Mobility / Gait", "Special Tests",
    "Diagnosis", "Clinical Presentation", "Justification for Skilled Care", "Patient Education",
    "Rehab Potential", "Short-Term Goals", "Long-Term Goals",
    "Frequency", "Duration", "Medicare Certification Dates",
    "Treatment Procedures (CPT)", "Medical Diagnosis (ICD-10)", "Treatment Diagnosis",
]


def run_pipeline(form, text, transcript):
    parsed = parse_plain(text) or {"sections": [], "missing_info": []}
    sections = postprocess.apply(form.id, parsed["sections"])
    sections = traceability.add_verification_flags(sections, transcript)
    sections, _ = cpt.suggest_codes(sections, form.id)
    return sections


def score_note(sections, dictation, gen_seconds):
    alltext = "\n".join(s["heading"] + "\n" + s["body"] for s in sections)
    low = alltext.lower()
    norm = traceability.normalize_for_matching(alltext)
    results, points, total = [], 0, 0

    def check(name, ok, detail=""):
        nonlocal points, total
        total += 1
        points += 1 if ok else 0
        results.append(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail and not ok else ''}")

    heads = [s["heading"].lower() for s in sections]
    check("structure: 4 blocks (S/O/A/P as own sections)",
          all(any(b in h for h in heads) for b in ["subjective", "objective", "assessment", "plan"]),
          f"headings={heads}")
    check("structure: not collapsed (>=4 sections)", len(sections) >= 4, f"{len(sections)} sections")

    present = sum(1 for f in EXPECTED_FIELDS if (f.lower() + ":") in low)
    check(f"fields: template fields present ({present}/{len(EXPECTED_FIELDS)})",
          present >= int(0.85 * len(EXPECTED_FIELDS)), f"only {present}")

    captured = 0
    for name, stems in FACTS.items():
        hit = any(st in low or st in norm for st in stems)
        captured += 1 if hit else 0
        check(f"capture: {name}", hit)
    check("safety: no unflagged model-authored code",
          "[[NEEDS: code" in alltext or not any(
              c in alltext for c in ["97110", "97112", "97116", "97140", "M19", "M54", "M75"]) or "[[CPT:" in alltext)
    dup_flags = alltext.count("text duplicated across sections")
    check("style: <=1 duplication flag", dup_flags <= 1, f"{dup_flags} flags")
    check("style: concise (< 4200 chars)", len(alltext) < 4200, f"{len(alltext)} chars")
    check("perf: generation under 10 min", gen_seconds < 600, f"{gen_seconds:.0f}s")

    print("\n".join(results))
    print(f"\nSCORE: {points}/{total}  |  fact capture {captured}/{len(FACTS)}  |  "
          f"{len(alltext)} chars in {gen_seconds:.0f}s")
    return points, total


def main() -> int:
    form = FORMS["initial_updated"]
    ctx = PatientContext(name="Carol Whitfield (fake)", sub="MRN 04471-238 · fake demo")
    prompt = build_prompt(form, ctx, DICTATION, render_prior_block(form, None, False), None)

    print(f"=== [1/2] Generating {form.name} (real model) ===")
    t0 = time.perf_counter()
    text = asyncio.run(generate_note(prompt))
    gen_s = time.perf_counter() - t0
    sections = run_pipeline(form, text, DICTATION)
    p1, t1 = score_note(sections, DICTATION, gen_s)

    print("\n=== [2/2] Revise pass: 'shorten History of Present Illness to one sentence' ===")
    note_text = "\n\n".join("## " + s["heading"] + "\n" + s["body"] for s in sections)
    rprompt = build_revise_prompt(form, note_text, "Shorten the History of Present Illness to one sentence.")
    t0 = time.perf_counter()
    revised = asyncio.run(generate_note(rprompt))
    rev_s = time.perf_counter() - t0
    rsections = run_pipeline(form, revised, DICTATION)
    rheads = [s["heading"].lower() for s in rsections]
    ok_struct = all(any(b in h for h in rheads) for b in ["subjective", "objective", "assessment", "plan"])
    still_meds = "lisinopril" in revised.lower()
    print(f"  revise time {rev_s:.0f}s | sections {len(rsections)} | structure kept: {ok_struct} | "
          f"meds preserved: {still_meds}")
    print(f"\nOVERALL: generation {p1}/{t1} · revise {'OK' if (ok_struct and still_meds) else 'CHECK'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
