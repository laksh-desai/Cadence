"""Validate the rule-16 condensing path on a genuinely long dictation, end to end, on the real model.

CLAUDE.md rule 16 built `chunked.fit_dictation` and then said, honestly, that it had never been
validated on a real long transcript -- only unit-tested on its deterministic scaffolding. This is
that validation, and it is deliberately built as an A/B rather than a single pass, because the
claim being tested is comparative: *condensing is better than the silent truncation it replaces.*
A one-armed run could only tell you the condensed note is imperfect, which was never in dispute.

    arm RAW        the pre-rule-16 behaviour: feed the whole over-budget dictation and let Ollama
                   silently drop whatever does not fit. This is the CONTROL.
    arm CONDENSED  the rule-16 path: condense at sentence boundaries, then generate.

Both are scored against a HAND-AUTHORED fact ledger (evals/data/longform_intake_ledger.json) whose
facts carry a ZONE -- head / mid / tail. The zone is the whole point: truncation is not random
data loss, it eats one END of the transcript, so an aggregate recall number would average away the
exact signal. Rule 24's lesson is applied to the ruler itself -- surface forms are compared after
`traceability.normalize_for_matching`, so a note writing "3+/5" still matches a dictation saying
"three plus out of five"; measuring notation and reporting it as lost facts is how the note audit
first read 15 dropped medications when the true answer was 0.

The condensed INTERMEDIATE is scored too, separately from the note. Those two numbers answer
different questions -- "did the condense pass drop the fact?" versus "did the writer drop it?" --
and only the first is this feature's responsibility.

Usage:
    python scripts/validate_longform.py                    # both arms, real model, ~30-60 min
    python scripts/validate_longform.py --arm condensed    # skip the control
    python scripts/validate_longform.py --condense-only    # tune the condense prompt for ~half the
                                                           # cost: runs the condense pass, scores
                                                           # the intermediate, skips the note
    python scripts/validate_longform.py --dry-run          # budget math + ledger check, no model

The dry run is worth running on its own after ANY template or rules edit: it prints the real
per-form dictation budget, which is what moves when the prompt scaffolding changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.generate import billing, chunked, cpt, postprocess, traceability  # noqa: E402
from app.generate.forms import FORMS  # noqa: E402
from app.generate.ollama_client import (  # noqa: E402
    NUM_CTX, NUM_PREDICT, OllamaUnavailableError, generate_note, model_for,
)
from app.generate.parser import parse_plain  # noqa: E402
from app.generate.prompt import PatientContext, build_prompt  # noqa: E402

DATA_DIR = ROOT / "evals" / "data"
OUT_DIR = ROOT / "evals" / "results" / "longform"
ZONES = ("head", "mid", "tail")


@dataclass
class ArmResult:
    name: str
    seconds: float = 0.0
    was_condensed: bool = False
    still_over: bool = False
    condensed_tokens: int | None = None
    note_text: str = ""
    sections: list = field(default_factory=list)
    missing_info: list = field(default_factory=list)
    parse_failed: bool = False
    found: dict = field(default_factory=dict)      # fact id -> bool, scored against the NOTE
    condense_found: dict = field(default_factory=dict)  # fact id -> bool, scored against the CONDENSED text
    error: str | None = None


def _norm(text: str) -> str:
    return traceability.normalize_for_matching(text or "")


def score_facts(facts: list[dict], text: str) -> dict[str, bool]:
    """A fact is present if ANY of its accepted surface forms appears in the normalized text."""
    hay = _norm(text)
    return {f["id"]: any(_norm(v) in hay for v in f["any_of"]) for f in facts}


def zone_table(facts: list[dict], found: dict[str, bool]) -> dict:
    by_zone = {z: {"total": 0, "found": 0, "missed": []} for z in ZONES}
    for f in facts:
        z = by_zone[f["zone"]]
        z["total"] += 1
        if found.get(f["id"]):
            z["found"] += 1
        else:
            z["missed"].append(f["id"])
    for z in by_zone.values():
        z["recall"] = round(z["found"] / z["total"], 3) if z["total"] else None
    return by_zone


def note_to_text(sections: list[dict], raw_text: str) -> str:
    if not sections:
        return raw_text or ""
    return "\n".join(f"{s.get('heading','')}\n{s.get('body','')}" for s in sections)


async def run_arm(name: str, *, form, patient_ctx, dictation: str, overhead: int,
                  condense: bool, facts: list[dict], model: str,
                  condense_only: bool = False) -> ArmResult:
    arm = ArmResult(name=name)
    t0 = time.monotonic()
    try:
        if condense:
            summary, was_condensed, still_over = await chunked.fit_dictation(
                dictation, overhead, generate_note
            )
            arm.was_condensed, arm.still_over = was_condensed, still_over
            arm.condensed_tokens = chunked.estimate_tokens(summary)
            arm.condense_found = score_facts(facts, summary)
            (OUT_DIR / f"{name}_condensed.txt").write_text(summary, encoding="utf-8")
        else:
            # The control: hand Ollama the whole thing and let it truncate, exactly as it did
            # before rule 16 existed.
            summary = dictation
        if condense_only:
            # The condense-pass scores are already recorded above; skip the ~20-minute note.
            return arm
        prompt = build_prompt(form, patient_ctx, summary, "", None)
        arm.note_text = await generate_note(prompt, model=model)
    except OllamaUnavailableError as e:
        arm.error = str(e)
        return arm
    finally:
        arm.seconds = round(time.monotonic() - t0, 1)

    parsed = parse_plain(arm.note_text)
    if parsed is None:
        arm.parse_failed = True
    else:
        sections = postprocess.apply(form.id, parsed["sections"])
        # Verification flags anchor against the RAW dictation on purpose, even in the condensed
        # arm: a value the condense pass introduced with no basis in what the therapist actually
        # said must still be flagged (CLAUDE.md rule 16's own caveat).
        sections = traceability.add_verification_flags(sections, dictation)
        sections, code_flags = cpt.suggest_codes(sections, form.id)
        arm.sections = sections
        arm.missing_info = list(parsed["missing_info"]) + code_flags
    arm.found = score_facts(facts, note_to_text(arm.sections, arm.note_text))
    (OUT_DIR / f"{name}_note.md").write_text(arm.note_text, encoding="utf-8")
    return arm


def check_billing(dictation: str, ledger: dict) -> dict:
    """Billing is derived from the DICTATION, so it should be untouched by any of this -- which is
    exactly why it is worth asserting here. If condensing ever starts feeding billing, this breaks."""
    draft = billing.extract(dictation)
    billed = {h.code: h.minutes for h in draft.interventions if h.status == "performed"}
    expected = {k: v for k, v in ledger["expected_billed"].items()}
    leaks = sorted(set(billed) & set(ledger["must_not_bill"]))
    return {
        "billed": {k: billed[k] for k in sorted(billed)},
        "expected": expected,
        "missing_codes": sorted(set(expected) - set(billed)),
        "false_codes": sorted(set(billed) - set(expected)),
        "minutes_wrong": {c: [billed[c], expected[c]] for c in sorted(set(billed) & set(expected))
                          if billed[c] != expected[c]},
        "leaks": leaks,
        "excluded_with_reason": [
            {"code": h.code, "status": h.status, "clause": h.clause[:90]}
            for h in draft.interventions if h.status != "performed"
        ],
    }


def fabrication_flags(sections: list[dict]) -> int:
    """How many rule-20 verification markers the note carries. Reported, not judged: on a condensed
    run some are EXPECTED (the condense pass rewords, so a value can drift out of anchor range),
    and that visibility is the feature working, not failing."""
    return sum(s.get("body", "").count("[[NEEDS:") for s in sections)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=["both", "raw", "condensed"], default="both")
    ap.add_argument("--condense-only", action="store_true",
                    help="run ONLY the condense pass and score the intermediate — skips the note "
                         "generation, so iterating on the condense prompt costs one pass instead "
                         "of two (~15 min rather than ~45 on the target hardware)")
    ap.add_argument("--form", default=None, help="override the form id in the ledger")
    ap.add_argument("--fast", action="store_true", help="use the fast-draft tier (a smoke test, not a result)")
    ap.add_argument("--dry-run", action="store_true", help="budget math and ledger sanity only")
    args = ap.parse_args()

    ledger = json.loads((DATA_DIR / "longform_intake_ledger.json").read_text(encoding="utf-8"))
    dictation = (DATA_DIR / ledger["transcript"]).read_text(encoding="utf-8").strip()
    facts = ledger["facts"]
    form = FORMS[args.form or ledger["form_id"]]
    patient_ctx = PatientContext(name="Longform Control", sub="MRN L-701 · synthetic · incomplete cervical SCI")
    overhead = chunked.estimate_tokens(build_prompt(form, patient_ctx, "", "", None))
    tokens = chunked.estimate_tokens(dictation)
    budget = NUM_CTX - NUM_PREDICT - overhead

    print(f"transcript : {len(dictation.split())} words, {len(dictation)} chars, ~{tokens} tokens")
    print(f"form       : {form.id} ({form.name})")
    print(f"budget     : num_ctx {NUM_CTX} - num_predict {NUM_PREDICT} - overhead {overhead} = {budget} tokens")
    print(f"overflow   : {tokens - budget:+d} tokens ({tokens / budget:.2f}x budget) -> "
          f"{'CONDENSES' if tokens > budget else 'fits, would NOT condense'}")
    print(f"chunks     : {len(chunked.split_into_chunks(dictation))}")

    # Sanity-check the ledger against its own transcript before trusting any note score. A fact
    # that is not in the SOURCE is a ledger bug, and scoring notes against it would manufacture
    # findings -- the exact rule-24 failure.
    self_check = score_facts(facts, dictation)
    bad = [k for k, v in self_check.items() if not v]
    print(f"ledger     : {len(facts)} facts; self-check against the transcript: "
          f"{len(facts) - len(bad)}/{len(facts)}")
    if bad:
        print(f"  !! LEDGER BUG - these facts are not findable in the source transcript: {bad}")
        return 2

    bill = check_billing(dictation, ledger)
    print(f"billing    : billed {bill['billed']} | leaks {bill['leaks'] or 'none'} | "
          f"missing {bill['missing_codes'] or 'none'} | false {bill['false_codes'] or 'none'}")

    if args.dry_run:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = model_for(args.fast)
    arms: list[ArmResult] = []
    plan = {"both": ["raw", "condensed"], "raw": ["raw"], "condensed": ["condensed"]}[args.arm]
    if args.condense_only:
        plan = ["condensed"]     # the raw arm has nothing to condense
    for name in plan:
        print(f"\n--- arm {name} ({model}) ... this takes minutes on CPU", flush=True)
        arm = await run_arm(name, form=form, patient_ctx=patient_ctx, dictation=dictation,
                            overhead=overhead, condense=(name == "condensed"),
                            facts=facts, model=model, condense_only=args.condense_only)
        arms.append(arm)
        if arm.error:
            print(f"    ERROR: {arm.error}")
            continue
        z = zone_table(facts, arm.found)
        overall = sum(1 for v in arm.found.values() if v)
        print(f"    {arm.seconds/60:.1f} min | sections {len(arm.sections)}"
              f"{' | PARSE FAILED' if arm.parse_failed else ''}"
              f" | verification flags {fabrication_flags(arm.sections)}")
        if arm.condensed_tokens is not None:
            cz = zone_table(facts, arm.condense_found)
            budget_tokens = NUM_CTX - NUM_PREDICT - overhead
            print(f"    condensed {tokens} -> ~{arm.condensed_tokens} tokens "
                  f"({1 - arm.condensed_tokens / tokens:.0%} smaller; budget {budget_tokens}, "
                  f"still_over={arm.still_over}); condense-pass fact recall "
                  + " ".join(f"{k}={cz[k]['found']}/{cz[k]['total']}" for k in ZONES))
            kept = sum(1 for v in arm.condense_found.values() if v)
            print(f"    condense-pass TOTAL {kept}/{len(facts)} = {kept/len(facts):.0%}")
        if args.condense_only:
            continue
        print(f"    NOTE fact recall {overall}/{len(facts)} = {overall/len(facts):.0%}  "
              + " ".join(f"{k}={z[k]['found']}/{z[k]['total']}" for k in ZONES))
        for k in ZONES:
            if z[k]["missed"]:
                print(f"      missed[{k}]: {', '.join(z[k]['missed'])}")

    if len(arms) == 2 and not any(a.error for a in arms):
        raw, cond = arms[0], arms[1]
        rz, cz = zone_table(facts, raw.found), zone_table(facts, cond.found)
        print("\n=== A/B: does condensing beat silent truncation? ===")
        for k in ZONES:
            d = cz[k]["found"] - rz[k]["found"]
            print(f"  {k:5s} raw {rz[k]['found']:2d}/{rz[k]['total']:2d}  "
                  f"condensed {cz[k]['found']:2d}/{cz[k]['total']:2d}   {d:+d}")
        rt = sum(raw.found.values())
        ct = sum(cond.found.values())
        print(f"  TOTAL raw {rt}/{len(facts)}  condensed {ct}/{len(facts)}   {ct - rt:+d}")
        print(f"  time  raw {raw.seconds/60:.1f} min  condensed {cond.seconds/60:.1f} min "
              f"({cond.seconds - raw.seconds:+.0f}s for the condense pass)")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}_longform.json"
    out.write_text(json.dumps({
        "run_id": stamp,
        "ledger_id": ledger["id"],
        "form_id": form.id,
        "model": model,
        "transcript": {"words": len(dictation.split()), "chars": len(dictation), "tokens": tokens},
        "budget": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "overhead": overhead,
                   "budget_tokens": budget, "overflow_ratio": round(tokens / budget, 3)},
        "billing": bill,
        "arms": [{
            "name": a.name, "seconds": a.seconds, "error": a.error,
            "was_condensed": a.was_condensed, "still_over": a.still_over,
            "condensed_tokens": a.condensed_tokens, "parse_failed": a.parse_failed,
            "sections": len(a.sections), "verification_flags": fabrication_flags(a.sections),
            "missing_info": a.missing_info,
            "note_recall": {"found": sum(1 for v in a.found.values() if v), "total": len(facts)},
            "note_by_zone": zone_table(facts, a.found),
            "condense_by_zone": zone_table(facts, a.condense_found) if a.condense_found else None,
        } for a in arms],
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
