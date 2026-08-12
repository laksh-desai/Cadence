"""Corpus sweep: run the synthetic transcript corpus through the REAL generation pipeline
and score every note (SYNTHETIC DATA ONLY — fictional patients, no PHI).

This is `scripts/validate_quality.py` generalized from one hardcoded dictation to a corpus.
It drives the SAME pipeline the app runs — build_prompt -> fit_dictation -> generate ->
postprocess -> verification -> CPT — by calling those functions directly, deliberately NOT
through /api/generate, because that endpoint requires a patient row and would write synthetic
patients into the clinician's encrypted database.

Budget: a sweep is roughly 1-2 min per note on CPU, so 26 records x 3 runs is 1.5-2.5 hours.
Use --limit / --only / --ids while iterating, and --resume to continue an interrupted sweep.

    .venv/bin/python scripts/eval_corpus.py --limit 3 --runs 1
    .venv/bin/python scripts/eval_corpus.py --runs 3 --resume
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate import forms as forms_store, ollama_client
from app.generate.forms import FORMS
from app.generate.ollama_client import OllamaUnavailableError
from evals import dataset, results as results_store, runner, score as scoring

# The pipeline drive + scoring live in evals/runner.py so the Evals tab in the browser UI runs
# the IDENTICAL code path — see that module's docstring for why the isolation guarantee is
# structural rather than a convention.
generate_one = runner.generate_one
score_one = runner.score_one

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "evals" / "runs"


def _pct(v) -> str:
    return "  n/a" if v is None else f"{v:.0%}"


def report(results: list[scoring.RecordResult]) -> None:
    if not results:
        print("\nNo results.")
        return
    print("\n" + "=" * 78)
    print("CORPUS EVAL SUMMARY")
    print("=" * 78)

    # Tier B — invariants.
    total_checks = sum(len(r.checks) for r in results)
    passed_checks = sum(r.invariants_passed for r in results)
    print(f"\n[B] Pipeline invariants: {passed_checks}/{total_checks} checks passed")
    failures: dict[str, int] = {}
    for r in results:
        for c in r.checks:
            if not c.passed:
                failures[c.name] = failures.get(c.name, 0) + 1
    if failures:
        for name, n in sorted(failures.items(), key=lambda kv: -kv[1]):
            print(f"      FAIL x{n:<3} {name}")
    else:
        print("      all invariants held on every run")

    # Tier A — CPT.
    with_gold = [r for r in results if r.cpt and r.cpt.gold]
    if with_gold:
        hits = sum(len(r.cpt.hits) for r in with_gold)
        gold = sum(len(r.cpt.gold) for r in with_gold)
        sugg = sum(len(r.cpt.suggested) for r in with_gold)
        gaps = sorted({c for r in with_gold for c in r.cpt.table_gap})
        missed = sorted({c for r in with_gold for c in r.cpt.missed_section})
        print(f"\n[A] CPT vs gold labels ({len(with_gold)} runs with gold codes)")
        print(f"      recall    {hits}/{gold}" + (f"  ({hits / gold:.0%})" if gold else ""))
        print(f"      precision {hits}/{sugg}" + (f"  ({hits / sugg:.0%})" if sugg else ""))
        if gaps:
            print(f"      TABLE GAP (cadence can never suggest these): {gaps}")
        if missed:
            print(f"      missed although mappable (model omitted the section): {missed}")
    else:
        print("\n[A] CPT: no records with gold codes in this selection")

    # Tier C — omissions.
    stated = sum(len(r.omissions.stated) for r in results if r.omissions)
    present = sum(len(r.omissions.present) for r in results if r.omissions)
    print(f"\n[C] Stated-value capture (rule 15): {present}/{stated}" +
          (f"  ({present / stated:.0%} of transcript values reached the note)" if stated else ""))
    worst = sorted((r for r in results if r.omissions and r.omissions.dropped),
                   key=lambda r: -len(r.omissions.dropped))[:5]
    for r in worst:
        print(f"      record {r.record_id} run {r.run}: dropped {list(r.omissions.dropped)}")

    # Section coverage.
    sp = sum(r.sections_present for r in results)
    se = sum(r.sections_expected for r in results)
    if se:
        print(f"\n[B] Template section coverage: {sp}/{se} ({sp / se:.0%}) of outline labels emitted")

    # Billing gold labels (ICD / dictation-side CPT / minutes / units). Safety metrics first:
    # a leak is a wrong claim, where a miss is only an incomplete one.
    billing_scoped = [r for r in results if r.billing_detection]
    if billing_scoped:
        agg = results_store.split_aggregate(results)
        print(f"\n[A2] Billing extraction ({len(billing_scoped)} runs with billing gold)")
        for scope in ("synthetic", "handwritten"):
            a = agg[scope]
            if not a:
                continue
            print(f"      {scope:<12} n={a['records']}  "
                  f"CPT billed {_pct(a['cpt_detection_recall'])} / surfaced "
                  f"{_pct(a['cpt_surfaced_recall'])} / prec {_pct(a['cpt_detection_precision'])}  "
                  f"ICD r{_pct(a['icd_recall'])}/p{_pct(a['icd_precision'])}  "
                  f"min {_pct(a['minutes_exact'])}  units {_pct(a['units_exact'])}")
        a = agg["all"]
        # Every counter here is a WRONG CLAIM, not an incomplete draft. Reported first, and apart
        # from accuracy, because they are the only numbers that carry billing risk.
        unsafe = (a["distractor_leaks"], a["untimed_leaks"], a["laterality_errors"],
                  a["minutes_fabricated"], a["units_overstated"])
        print(f"      WRONG CLAIMS: {a['distractor_leaks']} distractor leak(s), "
              f"{a['untimed_leaks']} untimed leak(s), {a['laterality_errors']} laterality error(s), "
              f"{a['minutes_fabricated']} fabricated minute(s), "
              f"{a['units_overstated']} OVER-counted unit(s)"
              + ("" if any(unsafe) else "  — none"))
        print(f"      safe gaps: {a['units_understated']} under-counted unit(s), "
              f"{a['minutes_not_extracted']} minute value(s) left for the clinician"
              f"   ·   CMS/AMA disagreed on {a['method_disagreements']} record(s)")
        for r in billing_scoped:
            for code, reason in r.billing_detection.distractor_leaks:
                print(f"      LEAK record {r.record_id} run {r.run}: billed {code} ({reason})")

        # Per-body-part, so a weak region is visible instead of averaged away.
        by_part: dict[str, list] = {}
        for r in billing_scoped:
            by_part.setdefault(getattr(r, "body_part", None) or "—", []).append(r)
        if len(by_part) > 1:
            print("      by body part:")
            for part, rows in sorted(by_part.items()):
                p = runner.aggregate(rows)
                print(f"        {part:<10} n={p['records']:<3} "
                      f"CPT {_pct(p['cpt_detection_recall'])}/{_pct(p['cpt_surfaced_recall'])}  "
                      f"ICD {_pct(p['icd_recall'])}  units {_pct(p['units_exact'])}"
                      f"  ({p['units_overstated']} over)")

    # Tier D — triage.
    nflags = sum(len(r.flags) for r in results)
    print(f"\n[D] Verification flags raised: {nflags} (human adjudication — see run JSON)")
    kinds: dict[str, int] = {}
    for r in results:
        for f in r.flags:
            key = f.text.split("—")[0].strip()[:52]
            kinds[key] = kinds.get(key, 0) + 1
    for key, n in sorted(kinds.items(), key=lambda kv: -kv[1])[:10]:
        print(f"      x{n:<3} {key}")

    # Stability across runs.
    by_record: dict[int, list[scoring.RecordResult]] = {}
    for r in results:
        by_record.setdefault(r.record_id, []).append(r)
    multi = {k: v for k, v in by_record.items() if len(v) > 1}
    if multi:
        unstable = [
            k for k, v in multi.items()
            if len({r.invariants_passed for r in v}) > 1 or len({len(r.flags) for r in v}) > 1
        ]
        print(f"\n[*] Run-to-run stability: {len(multi) - len(unstable)}/{len(multi)} records identical "
              f"across runs; unstable: {sorted(unstable)}")

    condensed = [r.record_id for r in results if r.was_condensed]
    if condensed:
        print(f"\n[*] Condense path (rule 16) exercised on records: {sorted(set(condensed))}")

    secs = [r.seconds for r in results]
    print(f"\n[*] Generation time: mean {sum(secs) / len(secs):.0f}s, max {max(secs):.0f}s "
          f"(this machine — does NOT transfer to the target i5-8365U)")
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=1, help="passes per record (>=3 to see nondeterminism)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N records")
    ap.add_argument("--ids", type=int, nargs="+", default=None, help="only these record ids")
    ap.add_argument("--only", default=None, help="filter to records whose derived form is this")
    ap.add_argument("--form", default=None, help="OVERRIDE: generate every record against this form")
    ap.add_argument("--fast", action="store_true", help="use the fast-draft model instead of MedGemma")
    ap.add_argument("--no-generate", action="store_true",
                    help="score ONLY the billing extraction (no model call, seconds not minutes). "
                         "The extractor reads the dictation, never the note, so its accuracy needs "
                         "no generation - and the result still lands in evals/results/ and the "
                         "Evals tab like any other sweep.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for per-run JSON")
    ap.add_argument("--resume", action="store_true", help="skip runs whose JSON already exists")
    ap.add_argument("--data", type=Path, default=None, help="corpus directory (default evals/data)")
    ap.add_argument("--body-part", default=None,
                    help="label the sweep's results file with this body part (does not filter)")
    args = ap.parse_args()

    try:
        corpus = dataset.load_corpus(args.data)
    except dataset.DatasetError as e:
        print(f"ERROR: {e}")
        return 2

    print(f"Corpus: {dataset.summarize(corpus)}")
    unmapped = [r.id for r in corpus if r.form_id == dataset.UNMAPPED]
    if unmapped and not args.form:
        print(f"ERROR: records {unmapped} have a visit_type that maps to no form. "
              f"Extend evals/dataset._FORM_PATTERNS, or pass --form to override.")
        return 2

    records = dataset.select(corpus, form=args.only, ids=args.ids, limit=args.limit)
    if not records:
        print("No records matched the selection.")
        return 2

    if args.form and args.form not in FORMS:
        print(f"ERROR: unknown form {args.form!r}. Known: {forms_store.ordered_form_ids()}")
        return 2

    if not args.no_generate and not asyncio.run(ollama_client.is_reachable()):
        print("ERROR: Ollama isn't reachable on localhost:11434. Start it and pull MedGemma 4B.")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    total = len(records) * args.runs
    print(f"Running {len(records)} records x {args.runs} run(s) = {total} generations "
          f"(~{total * 1.5:.0f} min at 1.5 min each)\n")

    if args.no_generate:
        from app.generate import billing as billing_mod

        t0 = time.perf_counter()
        billing_results = [
            runner.score_billing_only(r, billing_mod.extract(r.transcript))
            for r in records
        ]
        print(f"Scored {len(billing_results)} records' billing extraction in "
              f"{time.perf_counter() - t0:.1f}s (no model calls).\n")
        report(billing_results)
        cfg = {"mode": "billing-only", "records": len(records), "runs": 1,
               "corpus_dir": str(args.data or "evals/data"),
               "body_part": args.body_part or "corpus", "note_type": "all"}
        path = results_store.write_run(billing_results, config=cfg, started_at=started_at)
        print(f"\nSaved -> {path}")
        return 0

    results: list[scoring.RecordResult] = []
    done = 0
    for record in records:
        form = FORMS[args.form or record.form_id]
        for run in range(1, args.runs + 1):
            done += 1
            out_path = args.out / f"record{record.id:03d}_{form.id}_run{run}.json"
            if args.resume and out_path.exists():
                results.append(runner.load_result(out_path))
                print(f"[{done}/{total}] record {record.id} run {run} — cached")
                continue
            print(f"[{done}/{total}] record {record.id} ({record.word_count}w) "
                  f"-> {form.name}, run {run}… ", end="", flush=True)
            try:
                sections, missing, was_condensed, seconds, parsed_ok, draft, folded_raw = asyncio.run(
                    generate_one(record, form, args.fast)
                )
            except OllamaUnavailableError as e:
                print(f"\n  ABORT — {e}")
                break
            result = score_one(record, form, sections, missing, was_condensed, seconds, run,
                               parsed_ok, draft, folded_raw)
            results.append(result)
            out_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
            # The note itself, for clinician review / SFT bootstrapping later.
            out_path.with_suffix(".note.md").write_text(
                "\n\n".join(f"## {s['heading']}\n{s['body']}" for s in sections), encoding="utf-8"
            )
            flag_note = f" {len(result.flags)} flags" if result.flags else ""
            cond = " CONDENSED" if was_condensed else ""
            print(f"{seconds:.0f}s  {result.invariants_passed}/{len(result.checks)} invariants{flag_note}{cond}")

    report(results)
    print(f"\nPer-run JSON + notes written to {args.out}")

    if results:
        path = results_store.write_run(results, config={
            "body_part": args.body_part or "corpus",
            "note_type": args.only or args.form or "all",
            "form_override": args.form,
            "sample_count": len(records),
            "runs_per_record": args.runs,
            "model": ollama_client.model_for(args.fast),
            "fast": args.fast,
            "corpus_files": sorted({r.source_file for r in records}),
            "record_ids": [r.id for r in records],
        }, started_at=started_at)
        print(f"Sweep results (config + aggregate + per-record) written to {path}")
        print(f"Compare with:  .venv/Scripts/python.exe scripts/eval_compare.py <older>.json {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
