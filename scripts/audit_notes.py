"""Measure GENERATED notes against the dictations that produced them.

The billing extractor has a scored eval harness; the note WRITER has never had one. Every
generation-side rule in CLAUDE.md (15 completeness, 19 invented normals, 20 verification) has been
checked by reading individual notes by eye, which does not scale and does not produce a number that
can be compared across a prompt or model change.

This measures the two failures that matter most and are deterministically checkable, WITHOUT an
LLM judge (which would be circular - rule 21):

  DROPPED   a fact the dictation stated that the note does not carry   (rule 15)
  INVENTED  a fact the note asserts that the dictation never stated    (rules 14/19)

Medications are the probe. They are the ideal fact class for this: a closed, explicitly-stated
list; each item is a proper noun that either appears in the source or does not, with no paraphrase
question; the failure is documented and was observed for real (a note reading "Ibuprofen 400mg,
twice daily" for a dictation naming no drug at all); and rule 15 records that a dictated
11-medication list was silently dropped. What is true of medications is not automatically true of
narrative prose - this is a probe, not a proof, and clinician review remains the backstop (rule 14).

Structural and fabrication counts come from the SAME functions the production pipeline runs
(postprocess.is_folded_heading, traceability.*), so the audit cannot drift from the app's behaviour.

    .venv/Scripts/python.exe scripts/audit_notes.py
    .venv/Scripts/python.exe scripts/audit_notes.py --all        # include real patients
    .venv/Scripts/python.exe scripts/audit_notes.py --verbose    # per-note detail
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate import postprocess, traceability
from app.storage import db

_DOSE = (r"\d|as\b|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
         r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand")

#: A drug named in a note: a capitalised word followed by a dose, in EITHER notation. Requiring a
#: digit was the first version, and it read three notes that had carried every medication perfectly
#: - "Levothyroxine eighty-eight micrograms daily" - as having dropped all of them. The metric was
#: measuring dose FORMAT and reporting it as lost facts, which is the worst way for an audit to be
#: wrong: it manufactures alarming findings about the thing it exists to reassure you about.
#:
#: Still deliberately narrow - a dose is required, so sentence-initial prose ("Patient reports...")
#: does not match, and the stem must be long enough to skip "Left 5" style fragments.
_DRUG_RE = re.compile(rf"\b([A-Z][a-z]{{4,}})\s+(?:{_DOSE})")

#: Words that pass the shape test but are not drugs. Kept explicit rather than clever: this list is
#: auditable, and a false "invented medication" is the metric's own fabrication.
_NOT_DRUGS = {
    "Patient", "Vitamin", "Right", "Left", "Bilateral", "Grade", "Level", "Score", "Total",
    "Session", "Visit", "Therapy", "Exercise", "Minutes", "Degrees", "Range", "Strength",
    "Assessment", "Denies", "Reports", "Continue", "Increase", "Adverse", "Allergies",
    "Flexion", "Extension", "Rotation", "Abduction", "Shoulder", "Ambulates", "Gait",
    # Dose vocabulary. "hundred milligrams three times a day" matches the drug-shaped pattern
    # (word followed by a number word), so without these the audit reports the unit as a dropped
    # medication - the metric fabricating the very failure it exists to detect.
    "Milligrams", "Milligram", "Micrograms", "Units", "About", "Daily", "Twice", "Three",
    "Times", "Needed", "Bedtime", "Grams", "Tablet", "Tablets",
}


def _added_flags(sections: list[dict], flagger, transcript: str) -> int:
    """How many [[NEEDS:]] markers a verification pass ADDS.

    The flag_* functions return the full section list with markers appended, not a list of
    findings, so len() of the result is the section count - which made every fabrication column
    read exactly the number of sections. Counting the delta is what the caller actually wants.
    """
    import copy
    before = sum(s.get("body", "").count("[[NEEDS:") for s in sections)
    after_sections = flagger(copy.deepcopy(sections), transcript)
    after = sum(s.get("body", "").count("[[NEEDS:") for s in after_sections)
    return max(0, after - before)


def _note_medications(sections: list[dict]) -> set[str]:
    for s in sections:
        if "medic" in s.get("heading", "").lower():
            body = re.sub(r"\[\[.*?\]\]", " ", s.get("body", ""))
            # Case-insensitively, normalised to one casing. Inside a Medications section the
            # capitalisation carries no meaning - the model writes the first drug capitalised and
            # the rest lowercase mid-list ("...daily, gabapentin three hundred milligrams..."), so
            # requiring a capital initial reported four plainly-present medications as dropped.
            return {m.group(1).capitalize()
                    for m in re.finditer(_DRUG_RE.pattern, body, re.IGNORECASE)} - _NOT_DRUGS
    return set()


def _dictated_medications(transcript: str, named_in_note: set[str]) -> set[str]:
    """Which of the note's drugs the dictation actually states.

    Asymmetric on purpose. Pulling a gold list out of free speech would need its own drug
    dictionary - and any name missing from that dictionary would score as INVENTED, so the metric
    would manufacture the exact failure it is meant to detect. Checking presence instead is exact:
    a proper noun is in the source text or it is not.
    """
    low = transcript.lower()
    return {d for d in named_in_note if d.lower() in low}


def _dropped_medications(transcript: str, carried: set[str]) -> set[str]:
    """Drugs the DICTATION names that the note omits - the rule-15 direction.

    Only the medication clause is scanned, and only tokens immediately followed by a dose, so this
    stays a lower bound rather than a guess at the whole pharmacopoeia.
    """
    m = re.search(r"medications?[,:]?\s*(?:patient takes|she takes|he takes|takes)?(.{0,400})",
                  transcript, re.IGNORECASE)
    if not m:
        return set()
    spoken = m.group(1)
    numbers = (r"\d|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|"
               r"sixty|seventy|eighty|ninety|hundred|thousand")
    cand = {w.capitalize()
            for w in re.findall(rf"\b([a-z]{{5,}})\s+(?:{numbers})\b", spoken)}
    return {c for c in cand - _NOT_DRUGS if c not in carried}


def audit_note(row) -> dict:
    sections = json.loads(row["sections_json"])
    transcript = row["dictation_raw"] or ""

    named = _note_medications(sections)
    carried = _dictated_medications(transcript, named)
    invented = named - carried
    dropped = _dropped_medications(transcript, carried)

    return {
        "id": row["id"][:8],
        "form": row["form_id"],
        "sections": len(sections),
        "folded": sum(1 for s in sections if postprocess.is_folded_heading(s)),
        "empty": sum(1 for s in sections if not s.get("body", "").strip()),
        "long_head": sum(1 for s in sections
                         if len(s.get("heading", "")) > postprocess.MAX_HEADING_CHARS),
        "meds_in_note": len(named),
        "meds_ok": len(carried),
        "meds_invented": sorted(invented),
        "meds_dropped": sorted(dropped),
        "unanchored": _added_flags(sections, traceability.flag_unanchored_in_sections, transcript),
        "normals": _added_flags(sections, traceability.flag_unsupported_normals, transcript),
        "devices": _added_flags(sections, traceability.flag_unsupported_devices, transcript),
        "vitals": _added_flags(sections, traceability.flag_unsupported_vitals, transcript),
        "flags": sum(s.get("body", "").count("[[NEEDS:") for s in sections),
        "dict_words": len(transcript.split()),
        "note_words": sum(len(s.get("body", "").split()) for s in sections),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true",
                    help="audit real patients too (default: synthetic demo notes only)")
    ap.add_argument("--verbose", action="store_true", help="per-note detail")
    args = ap.parse_args()

    db.init()
    try:
        conn = db.get_connection()
        where = "" if args.all else "WHERE n.synthetic=1"
        rows = conn.execute(
            f"SELECT n.id, n.form_id, n.sections_json, n.dictation_raw "
            f"FROM notes n {where} ORDER BY n.form_id, n.id").fetchall()
        conn.close()
    finally:
        db.shutdown()

    if not rows:
        print("No notes to audit. Seed some with scripts/seed_demo_data.py.")
        return 0

    results = [audit_note(r) for r in rows]

    header = (f"{'note':<10}{'form':<10}{'sec':>4}{'fold':>5}{'empty':>6}{'>80':>4}"
              f"{'meds':>6}{'inv':>4}{'drop':>5}{'unanch':>7}{'norm':>5}{'dev':>4}"
              f"{'flags':>6}{'dict':>6}{'note':>6}")
    print(header)
    for r in results:
        print(f"{r['id']:<10}{r['form']:<10}{r['sections']:>4}{r['folded']:>5}{r['empty']:>6}"
              f"{r['long_head']:>4}{r['meds_ok']:>6}{len(r['meds_invented']):>4}"
              f"{len(r['meds_dropped']):>5}{r['unanchored']:>7}{r['normals']:>5}"
              f"{r['devices']:>4}{r['flags']:>6}{r['dict_words']:>6}{r['note_words']:>6}")

    def tot(key: str) -> int:
        return sum(r[key] if isinstance(r[key], int) else len(r[key]) for r in results)

    print(f"\n=== {len(results)} notes ===")
    print(f"STRUCTURE   folded {tot('folded')}   empty bodies {tot('empty')}   "
          f"headings over {postprocess.MAX_HEADING_CHARS} chars {tot('long_head')}")
    print(f"MEDICATIONS {tot('meds_in_note')} named in notes, {tot('meds_ok')} traceable to the "
          f"dictation, {tot('meds_invented')} INVENTED, {tot('meds_dropped')} dropped")
    print(f"FABRICATION unanchored values {tot('unanchored')}   unsupported normals "
          f"{tot('normals')}   invented devices {tot('devices')}   vitals {tot('vitals')}")
    print(f"FLAGS       {tot('flags')} [[NEEDS:]] markers raised for the clinician")

    if args.verbose:
        for r in results:
            if r["meds_invented"] or r["meds_dropped"]:
                print(f"\n{r['id']} ({r['form']})")
                if r["meds_invented"]:
                    print(f"   INVENTED: {', '.join(r['meds_invented'])}")
                if r["meds_dropped"]:
                    print(f"   DROPPED : {', '.join(r['meds_dropped'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
