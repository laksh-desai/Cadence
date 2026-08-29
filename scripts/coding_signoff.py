"""Produce the ICD-10 / CPT sign-off worksheet, and record a completed sign-off.

CLAUDE.md names the unverified coding tables as one of the three things blocking Cadence, and
correctly says it is "not a code task — it needs a certified coder or the clinician with the
ICD-10-CM tabular list." True, and also incomplete: nobody can sign off on a table they cannot
see. The tables live inside a Python module as nested dataclasses, so "please review the codes"
currently means "please read app/generate/coding_tables.py", which is not a request you can make
of a coder. That is a tooling gap, and this closes it.

    python scripts/coding_signoff.py                       # worksheet for every region -> stdout
    python scripts/coding_signoff.py --region shoulder     # one region
    python scripts/coding_signoff.py --out signoff.md      # write it to a file to print/email
    python scripts/coding_signoff.py --status              # what is signed off and what is not

    python scripts/coding_signoff.py --sign shoulder --by "J. Rivera, CPC" --on 2026-09-02

`--sign` edits `TABLE_PROVENANCE` in `app/generate/coding_tables.py` in place. Signing is per
REGION on purpose (see TableProvenance): the practice can verify shoulder and knee, start billing
those, and leave the regions it rarely sees visibly unverified rather than carrying all six on one
global tick. `tests/test_billing_extract.py` keeps failing until every region is signed, so a
partial sign-off is visible rather than quietly complete.

The worksheet deliberately shows the CUES as well as the codes. A wrong code is the obvious
failure, but a code attached to the wrong TRIGGER PHRASE is the one that actually bills: "PF" was
rejected from the tables precisely because it means plantar fascia to a foot therapist and
patellofemoral to a knee therapist (CLAUDE.md rule 21), and only a coder reading the phrases can
catch the next one of those.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.generate import coding_tables as tables  # noqa: E402
from app.generate.cpt import TIMED_CODES, _CPT_RULES  # noqa: E402

TABLES_PATH = ROOT / "app" / "generate" / "coding_tables.py"


def _laterality_cell(rule: tables.IcdRule) -> str:
    if not rule.lateralized:
        return f"`{rule.unspecified}` (one code, no side)"
    parts = [f"R `{rule.right}`", f"L `{rule.left}`", f"unspec `{rule.unspecified}`"]
    if rule.bilateral:
        parts.append(f"bilat `{rule.bilateral}`")
    return " · ".join(parts)


def icd_section(region: str) -> list[str]:
    prov = tables.TABLE_PROVENANCE[region]
    rules = tables.ICD_BY_BODY_PART[region]
    out = [
        f"### {region.upper()} — {len(rules)} diagnoses",
        "",
        f"*ICD-10-CM {prov.icd10cm_year}. Status: "
        + (f"signed off by {prov.verified_by} on {prov.verified_on}."
           if prov.verified else "**NOT YET VERIFIED.**")
        + "*",
        "",
        "| Checked | Label Cadence shows | Codes | Trigger phrases in the dictation | Notes |",
        "|---|---|---|---|---|",
    ]
    for rule in rules:
        notes = []
        if rule.symptom_only:
            notes.append("symptom code — suppressed when a definitive diagnosis is also found")
        if rule.family:
            notes.append(f"exclusive with other `{rule.family}` variants")
        if rule.caution:
            notes.append(rule.caution)
        cues = ", ".join(f'"{c}"' for c in rule.cues)
        out.append(f"| [ ] | {rule.label} | {_laterality_cell(rule)} | {cues} | "
                   f"{'; '.join(notes) or '—'} |")
    out += [
        "",
        f"**{region} sign-off.** Three questions per row, in the order they cause harm:",
        "",
        "1. Do the CODES match the label in the ICD-10-CM tabular list for "
        f"{prov.icd10cm_year}? (A wrong code is a wrong claim.)",
        "2. Would every TRIGGER PHRASE, said by this practice's therapists, mean this diagnosis "
        "and no other? (A phrase that is ambiguous between two diagnoses must be struck — a "
        "missed code is a gap the clinician fills; a wrong one is a claim.)",
        "3. Is anything this practice actually sees MISSING from the list? Write it in.",
        "",
        f"When the region is correct: `python scripts/coding_signoff.py --sign {region} "
        '--by "<your name and credential>" --on <YYYY-MM-DD>`',
        "",
    ]
    return out


def cpt_section() -> list[str]:
    out = [
        "### CPT — outpatient PT service codes",
        "",
        "These map a named intervention to its code. Cadence never lets the model author a code; "
        "every one comes from this table and is marked *confirm* in the review step.",
        "",
        "| Checked | Code | Label | Timed? | Section headings that map to it |",
        "|---|---|---|---|---|",
    ]
    # Several headings map to one code (97010 x3, 97014 x2, 97535 x2), so group by code — the row
    # a coder checks is the CODE, and seeing all of its triggers together is the point.
    by_code: dict[str, tuple[str, list[str]]] = {}
    for heading, code, label in _CPT_RULES:
        by_code.setdefault(code, (label, []))[1].append(heading)
    for code, (label, headings) in by_code.items():
        cues = ", ".join(f'"{h}…"' for h in headings)
        out.append(f"| [ ] | `{code}` | {label} | "
                   f"{'timed (8-min rule)' if code in TIMED_CODES else 'service-based'} | "
                   f"{cues} |")
    # Cross-check: every timed code should exist in the table above, or the 8-minute rule is
    # counting minutes for a code nothing can ever produce.
    orphans = sorted(TIMED_CODES - set(by_code))
    if orphans:
        out += ["", f"> Timed codes with no heading mapping: {', '.join(orphans)}"]
    out += [
        "",
        "**CPT sign-off.** The timed/service-based column is the one with money attached: only "
        "TIMED codes feed the 8-minute rule, and counting a service-based modality's minutes "
        "inflates the unit total. Evaluation complexity (97161/2/3) is deliberately NOT in this "
        "table — Cadence raises it as a flag for the clinician to choose, because complexity is a "
        "judgment call.",
        "",
    ]
    return out


def worksheet(regions: list[str]) -> str:
    today = dt.date.today().isoformat()
    lines = [
        "# Cadence coding sign-off worksheet",
        "",
        f"*Generated {today} from `app/generate/coding_tables.py` and `app/generate/cpt.py`.*",
        "",
        "## Why this needs a human",
        "",
        "Cadence never lets the language model choose a billing code. Every code it suggests comes "
        "from one of the fixed tables below, and the clinician confirms or removes each one before "
        "signing. That design only holds if the TABLES are right — a confidently-wrong code shown "
        "as a tidy chip is worse than no code at all, because it invites a click.",
        "",
        "These tables were assembled from the ICD-10-CM tabular list by the developer. That is a "
        "careful reading, not a coder's sign-off, and Cadence's own test suite fails on purpose "
        "until this worksheet is completed. **Until then, treat every code as a draft to check "
        "against your own reference, not as a suggestion you can accept on trust.**",
        "",
        "Work region by region. Sign off the ones this practice actually sees first — they are "
        "independent, and an unsigned region stays visibly unsigned rather than being carried "
        "along by the others.",
        "",
        "## Regions",
        "",
    ]
    for region in regions:
        lines += icd_section(region)
    lines += cpt_section()
    lines += [
        "## What is NOT in these tables, and why",
        "",
        "- **Units, the 8-minute rule, and modifiers.** Cadence computes units two ways (CMS "
        "substitution and the AMA rule of eights) and shows both WITH the disagreement when they "
        "differ, rather than picking one. The biller decides.",
        "- **Evaluation complexity (97161/97162/97163).** Surfaced as a flag, never auto-assigned.",
        "- **Any diagnosis outside the six regions above.** If the dictation is about a body "
        "region with no table, Cadence suggests no ICD code at all rather than guessing.",
        "- **Ambiguous abbreviations.** \"PF\" is excluded deliberately: it means plantar fascia to "
        "a foot therapist and patellofemoral to a knee therapist. If you spot another, strike it.",
        "",
    ]
    return "\n".join(lines) + "\n"


def status() -> str:
    rows = []
    for region in tables.BODY_PARTS:
        prov = tables.TABLE_PROVENANCE[region]
        n = len(tables.ICD_BY_BODY_PART[region])
        rows.append(f"  {region:10s} {n:2d} diagnoses  "
                    + (f"signed off by {prov.verified_by} on {prov.verified_on}"
                       if prov.verified else "NOT VERIFIED"))
    unsigned = tables.unverified_body_parts()
    head = (f"ICD-10-CM {tables.ICD10CM_YEAR} tables — "
            f"{len(tables.BODY_PARTS) - len(unsigned)}/{len(tables.BODY_PARTS)} regions signed off")
    tail = ("\nAll regions signed off. tests/test_billing_extract.py's sign-off gate should now pass."
            if not unsigned else
            f"\nStill unverified: {', '.join(unsigned)}"
            "\nRun without --status to print the worksheet a coder fills in.")
    return "\n".join([head, *rows]) + "\n" + tail


def sign(region: str, by: str, on: str) -> int:
    """Record a completed sign-off by making TABLE_PROVENANCE explicit for this region.

    The dict is a comprehension over BODY_PARTS, so the first signature has to expand it into
    literal entries. Done here rather than by hand because getting it wrong silently un-verifies a
    region that a human already checked.
    """
    if region not in tables.BODY_PARTS:
        print(f"unknown region {region!r}; expected one of {', '.join(tables.BODY_PARTS)}")
        return 2
    try:
        dt.date.fromisoformat(on)
    except ValueError:
        print(f"--on must be an ISO date (YYYY-MM-DD), got {on!r}")
        return 2
    if not by.strip():
        print("--by must name the person who reviewed the table")
        return 2

    src = TABLES_PATH.read_text(encoding="utf-8")
    comprehension = ("TABLE_PROVENANCE: dict[str, TableProvenance] = "
                     "{part: TableProvenance() for part in BODY_PARTS}")
    if comprehension in src:
        expanded = ["TABLE_PROVENANCE: dict[str, TableProvenance] = {"]
        for part in tables.BODY_PARTS:
            expanded.append(f'    "{part}": TableProvenance(),')
        expanded.append("}")
        src = src.replace(comprehension, "\n".join(expanded), 1)

    pattern = re.compile(rf'^(\s*)"{re.escape(region)}":\s*TableProvenance\([^)]*\),\s*$', re.M)
    if not pattern.search(src):
        print(f"could not find the {region} entry in {TABLES_PATH} — sign it by hand:")
        print(f'    "{region}": TableProvenance(verified_by="{by}", verified_on="{on}"),')
        return 1
    escaped_by = by.replace('"', r"\"")
    src = pattern.sub(
        lambda m: f'{m.group(1)}"{region}": TableProvenance('
                  f'verified_by="{escaped_by}", verified_on="{on}"),',
        src, count=1)
    TABLES_PATH.write_text(src, encoding="utf-8")
    print(f"recorded: {region} ICD-10-CM {tables.ICD10CM_YEAR} table verified by {by} on {on}")
    remaining = [p for p in tables.BODY_PARTS if p != region and not tables.is_verified(p)]
    print("still unverified: " + (", ".join(remaining) if remaining else "none — all regions signed"))
    print("\nRe-run the suite to confirm the gate moved:"
          "\n    .venv/Scripts/python.exe -m unittest tests.test_billing_extract")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", action="append", choices=list(tables.BODY_PARTS),
                    help="limit the worksheet to this region (repeatable)")
    ap.add_argument("--out", type=Path, help="write the worksheet here instead of stdout")
    ap.add_argument("--status", action="store_true", help="what is signed off and what is not")
    ap.add_argument("--sign", metavar="REGION", help="record a completed sign-off for one region")
    ap.add_argument("--by", default="", help="who reviewed it (name + credential)")
    ap.add_argument("--on", default=dt.date.today().isoformat(), help="ISO date of the review")
    args = ap.parse_args()

    # The Windows console defaults to cp1252, which cannot encode the em dashes and typographic
    # quotes in the worksheet copy. Writing to a FILE is already UTF-8; this makes stdout match so
    # `python scripts/coding_signoff.py | more` does not die on a dash.
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.status:
        print(status())
        return 0
    if args.sign:
        return sign(args.sign, args.by, args.on)

    text = worksheet(args.region or list(tables.BODY_PARTS))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
