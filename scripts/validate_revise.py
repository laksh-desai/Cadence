"""Measure whether "Ask for changes" actually applies the change the clinician asked for.

The reported problem: the clinician types a change, waits several minutes, and gets a note back
that is materially the same — and the UI still says "Changes applied". Two separate failures are
tangled together there and they need separating before anything is fixed:

    DID IT CHANGE AT ALL?      the model re-emitted the note verbatim
    DID IT CHANGE THE RIGHT    something moved, but not the thing that was asked for
    THING?
    DID IT BREAK ANYTHING      the change landed, and four untouched sections drifted with it
    ELSE?

The third is the quiet one. `build_revise_prompt` asks the 4B model to re-emit the COMPLETE note —
every section — to change one line. Most of its output budget goes on copying, which is both why
the edit gets lost and why untouched sections come back subtly reworded. Collateral drift in a
clinical note is worse than a missed edit: the clinician asked to reword the assessment and the
medication list quietly changed.

So each case below declares a TARGET section and a deterministic check, and the harness reports
all three numbers plus wall-clock. No LLM judge (circular, per CLAUDE.md rule 21) — every check is
a substring or a count over the parsed sections.

    python scripts/validate_revise.py                    # all cases, current strategy
    python scripts/validate_revise.py --case 1 --case 3  # just these
    python scripts/validate_revise.py --strategy scoped  # the section-scoped rewrite
    python scripts/validate_revise.py --dry-run          # show the cases, call no model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.generate import postprocess  # noqa: E402
from app.generate.forms import FORMS  # noqa: E402
from app.generate.ollama_client import OllamaUnavailableError, generate_note, model_for  # noqa: E402
from app.generate.parser import parse_plain  # noqa: E402
from app.generate.prompt import build_revise_prompt  # noqa: E402

FIXTURE = ROOT / "evals" / "runs" / "record1001_followup_run1.note.md"
OUT_DIR = ROOT / "evals" / "results" / "revise"


def _sec(sections: list[dict], name: str) -> dict | None:
    for s in sections:
        if name.lower() in (s.get("heading") or "").lower():
            return s
    return None


def _headings(sections: list[dict]) -> list[str]:
    return [(s.get("heading") or "").strip() for s in sections]


# Each case: the instruction a clinician would actually type, the section it targets, and a
# deterministic check over the REVISED sections. `target` is used for the collateral count, so it
# must name the section the instruction is about (None = the change is note-wide).
CASES = [
    {
        "id": 1,
        "instruction": "In Response to Treatment, say she tolerated the session well with no "
                       "increase in pain.",
        "target": "Response to Treatment",
        "check": lambda after: "tolerated" in (_sec(after, "Response to Treatment") or {}).get("body", "").lower(),
        "why": "the commonest kind of request — expand one short section",
    },
    {
        "id": 2,
        "instruction": "Pain at rest should be 3 out of 10, I misspoke.",
        "target": "Pain - At Rest",
        "check": lambda after: "3" in (_sec(after, "Pain - At Rest") or {}).get("body", ""),
        "why": "correcting a value the clinician got wrong — must actually change the number",
    },
    {
        "id": 3,
        "instruction": "Delete the Vitals section, I did not take vitals today.",
        "target": "Vitals",
        "check": lambda after: _sec(after, "Vitals") is None,
        "why": "a deletion — the model tends to re-emit what it was told to remove",
    },
    {
        "id": 4,
        "instruction": "Write the Precautions section as a bulleted list.",
        "target": "Precautions",
        "check": lambda after: any(
            ln.strip().startswith(("-", "*", "•"))
            for ln in (_sec(after, "Precautions") or {}).get("body", "").splitlines()),
        "why": "formatting only — no clinical content should move",
    },
    {
        "id": 5,
        "instruction": "There are two Neuromuscular Reeducation sections. Merge them into one.",
        "target": None,
        "check": lambda after: sum(1 for h in _headings(after) if "neuromuscular" in h.lower()) == 1,
        "why": "a structural fix the clinician can see is needed at a glance",
    },
]


def compare(before: list[dict], after: list[dict], target: str | None) -> dict:
    """What actually moved. `collateral` is the count of NON-target sections whose body changed —
    the number that says whether a one-line request quietly rewrote the rest of the note."""
    before_by = {(s.get("heading") or "").strip().lower(): s.get("body", "") for s in before}
    after_by = {(s.get("heading") or "").strip().lower(): s.get("body", "") for s in after}
    tgt = (target or "").strip().lower()

    changed, collateral = [], []
    for head, body in after_by.items():
        was = before_by.get(head)
        if was is None or was.strip() != body.strip():
            changed.append(head)
            if not tgt or tgt not in head:
                collateral.append(head)
    dropped = [h for h in before_by if h not in after_by]
    # A deletion request makes the dropped section the POINT, not collateral.
    if tgt:
        collateral = [h for h in collateral if tgt not in h]
        dropped_collateral = [h for h in dropped if tgt not in h]
    else:
        dropped_collateral = []
    return {
        "identical": before_by == after_by,
        "changed_sections": sorted(changed),
        "dropped_sections": sorted(dropped),
        "collateral": sorted(set(collateral) | set(dropped_collateral)),
    }


async def run_case(case: dict, note_text: str, before: list[dict], form, model: str,
                   strategy: str) -> dict:
    t0 = time.monotonic()
    try:
        if strategy == "scoped":
            from app.generate.prompt import (
                build_scoped_revise_prompt, is_structural_instruction, select_revise_sections)
            # Mirror the SERVER's routing exactly. An earlier version of this harness skipped the
            # structural check, so a "merge these two sections" request was handed a scoped prompt
            # containing no sections at all — the harness measuring something the app never does.
            picked = ([] if is_structural_instruction(case["instruction"])
                      else select_revise_sections(before, case["instruction"]))
            if picked:
                prompt = build_scoped_revise_prompt(form, before, picked, case["instruction"])
                out = await generate_note(prompt, model=model)
                revised = apply_scoped(before, out)
            else:
                prompt = build_revise_prompt(form, note_text, case["instruction"])
                out = await generate_note(prompt, model=model)
                parsed = parse_plain(out)
                revised = postprocess.apply(form.id, parsed["sections"]) if parsed else []
            raw = out
        else:
            prompt = build_revise_prompt(form, note_text, case["instruction"])
            raw = await generate_note(prompt, model=model)
            parsed = parse_plain(raw)
            revised = postprocess.apply(form.id, parsed["sections"]) if parsed else []
    except OllamaUnavailableError as e:
        return {**{k: case[k] for k in ("id", "instruction", "target")}, "error": str(e)}
    seconds = round(time.monotonic() - t0, 1)

    if not revised:
        return {**{k: case[k] for k in ("id", "instruction", "target")},
                "seconds": seconds, "parse_failed": True, "applied": False,
                "identical": False, "collateral": [], "raw_chars": len(raw)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"case{case['id']}_{strategy}_raw.md").write_text(raw, encoding="utf-8")
    delta = compare(before, revised, case["target"])
    try:
        applied = bool(case["check"](revised))
    except Exception:  # noqa: BLE001 - a broken check must not look like a failed revision
        applied = False
    return {
        "id": case["id"], "instruction": case["instruction"], "target": case["target"],
        "seconds": seconds, "parse_failed": False,
        "applied": applied, "identical": delta["identical"],
        "changed_sections": delta["changed_sections"],
        "collateral": delta["collateral"],
        "sections_before": len(before), "sections_after": len(revised),
        "raw_chars": len(raw),
    }


def apply_scoped(before: list[dict], model_output: str) -> list[dict]:
    """Splice the model's re-written section(s) back into the full note.

    The scoped strategy only asks for the sections being changed, so the rest of the note is
    carried over BYTE-IDENTICAL rather than re-emitted — which is what makes collateral drift
    structurally impossible instead of merely discouraged.
    """
    parsed = parse_plain(model_output)
    if parsed is None:
        return []
    new_by = {(s.get("heading") or "").strip().lower(): s for s in parsed["sections"]}
    out, seen = [], set()
    for s in before:
        head = (s.get("heading") or "").strip().lower()
        replacement = new_by.get(head)
        if replacement is not None:
            seen.add(head)
            if replacement.get("body", "").strip().upper() in ("[[DELETE]]", "DELETE"):
                continue                       # an explicit deletion request
            out.append({**s, "body": replacement["body"]})
        else:
            out.append(s)
    for head, s in new_by.items():             # a section the model added
        if head not in seen and head not in {(b.get("heading") or "").strip().lower() for b in before}:
            out.append(s)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", choices=["whole", "scoped"], default="whole")
    ap.add_argument("--case", type=int, action="append", help="run only these case ids (repeatable)")
    ap.add_argument("--fast", action="store_true", help="fast-draft tier (a smoke test, not a result)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    note_text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_plain(note_text)
    before = postprocess.apply("followup", parsed["sections"])
    form = FORMS["followup"]
    cases = [c for c in CASES if not args.case or c["id"] in args.case]

    print(f"fixture : {FIXTURE.name} — {len(before)} sections, {len(note_text.split())} words")
    print(f"strategy: {args.strategy}")
    print(f"cases   : {len(cases)}\n")
    for c in cases:
        print(f"  [{c['id']}] {c['instruction']}")
        print(f"      target={c['target']!r}  ({c['why']})")
    if args.dry_run:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = model_for(args.fast)
    results = []
    print(f"\nrunning against {model} — minutes per case on CPU\n", flush=True)
    for c in cases:
        r = await run_case(c, note_text, before, form, model, args.strategy)
        results.append(r)
        if r.get("error"):
            print(f"[{r['id']}] ERROR {r['error']}")
            continue
        verdict = "APPLIED " if r["applied"] else "NOT APPLIED"
        note = " (note returned IDENTICAL)" if r["identical"] else ""
        # On Windows time.monotonic() counts time the machine spent SUSPENDED, so a run left
        # overnight reports a case as having taken 23 hours. The structural results are unaffected
        # — only the clock is — so say that rather than print a number that is plainly fiction.
        mins = r["seconds"] / 60
        clock = "clock unusable (machine slept)" if mins > 120 else f"{mins:.1f} min"
        print(f"[{r['id']}] {verdict}{note}  {clock}  "
              f"sections {r['sections_before']}->{r['sections_after']}  "
              f"collateral {len(r['collateral'])}", flush=True)
        if r["collateral"]:
            print(f"      untouched sections that changed anyway: {', '.join(r['collateral'][:6])}")

    ok = [r for r in results if not r.get("error")]
    if ok:
        applied = sum(1 for r in ok if r["applied"])
        identical = sum(1 for r in ok if r["identical"])
        collateral = sum(len(r["collateral"]) for r in ok)
        timed = [r for r in ok if r["seconds"] / 60 <= 120]   # exclude suspend-inflated cases
        total_min = sum(r["seconds"] for r in timed) / 60
        print(f"\n=== {args.strategy} ===")
        print(f"  APPLIED          {applied}/{len(ok)}")
        print(f"  returned identical {identical}/{len(ok)}   <- the 'wasted my time' case")
        print(f"  collateral edits {collateral} section(s) across {len(ok)} revisions")
        if timed:
            print(f"  time             {total_min:.1f} min over {len(timed)} timed case(s), "
                  f"{total_min/len(timed):.1f} min per revision")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}_revise_{args.strategy}.json"
    out.write_text(json.dumps({"strategy": args.strategy, "model": model,
                               "fixture": FIXTURE.name, "results": results}, indent=2),
                   encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
