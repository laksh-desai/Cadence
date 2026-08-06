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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate import chunked, cpt, forms as forms_store, ollama_client, postprocess, traceability
from app.generate.forms import FORMS
from app.generate.ollama_client import OllamaUnavailableError, generate_note
from app.generate.parser import parse_plain
from app.generate.prompt import PatientContext, build_prompt, render_prior_block
from evals import dataset, score as scoring

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "evals" / "runs"

# Mirrors app/ui/server.py:_finalize_note — kept in sync so the invariant check for
# "a condensed dictation always warns the clinician" tests the real contract.
CONDENSE_WARNING = "was long and was automatically condensed"
CONDENSE_WARNING_HARD = "had to be condensed to fit the model even after"


def build_missing(parsed_missing: list[str], code_flags: list[str], was_condensed: bool, still_over: bool) -> list[str]:
    missing = list(parsed_missing) + list(code_flags)
    if was_condensed:
        missing.append(
            "This dictation was very long and had to be condensed to fit the model even after "
            "cleanup — verify the note captured the whole session."
            if still_over else
            "This dictation was long and was automatically condensed to fit the model — verify the "
            "note captured the whole session."
        )
    return missing


async def generate_one(record: dataset.EvalRecord, form, fast: bool):
    """One full pipeline pass. Returns (sections, missing, was_condensed, seconds, parsed_ok)."""
    sub = " · ".join(filter(None, [record.diagnosis, record.visit_type])) or "—"
    ctx = PatientContext(name=record.patient_name, sub=sub)
    prior_block = render_prior_block(form, None, False)

    overhead = chunked.estimate_tokens(build_prompt(form, ctx, "", prior_block, None))
    summary, was_condensed, still_over = await chunked.fit_dictation(
        record.transcript, overhead, generate_note
    )
    prompt = build_prompt(form, ctx, summary, prior_block, None)

    t0 = time.perf_counter()
    text = await generate_note(prompt, model=ollama_client.model_for(fast))
    seconds = time.perf_counter() - t0

    parsed = parse_plain(text)
    if parsed is None:
        return [], [], was_condensed, seconds, False

    sections = postprocess.apply(form.id, parsed["sections"])
    # Verification anchors against the RAW transcript, not the condensed one, so a value the
    # condense pass introduced without basis is still caught (same as the app).
    sections = traceability.add_verification_flags(sections, record.transcript)
    sections, code_flags = cpt.suggest_codes(sections, form.id)
    missing = build_missing(parsed["missing_info"], code_flags, was_condensed, still_over)
    return sections, missing, was_condensed, seconds, True


def score_one(record, form, sections, missing, was_condensed, seconds, run, parsed_ok) -> scoring.RecordResult:
    condense_flag = any(
        CONDENSE_WARNING in m or CONDENSE_WARNING_HARD in m for m in missing
    )
    present, expected, missing_labels = scoring.section_coverage(sections, form)
    return scoring.RecordResult(
        record_id=record.id,
        form_id=form.id,
        run=run,
        seconds=seconds,
        was_condensed=was_condensed,
        checks=scoring.score_invariants(
            sections, form,
            parsed_ok=parsed_ok, was_condensed=was_condensed, condense_flag_present=condense_flag,
        ),
        cpt=scoring.score_cpt(sections, record.cpt_codes) if record.cpt_codes else None,
        omissions=scoring.score_omissions(sections, record.transcript),
        flags=scoring.collect_flags(sections, record.transcript),
        sections_present=present,
        sections_expected=expected,
        sections_missing=missing_labels,
        note_chars=len(scoring.note_text(sections)),
    )


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
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for per-run JSON")
    ap.add_argument("--resume", action="store_true", help="skip runs whose JSON already exists")
    ap.add_argument("--data", type=Path, default=None, help="corpus directory (default evals/data)")
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

    if not asyncio.run(ollama_client.is_reachable()):
        print("ERROR: Ollama isn't reachable on localhost:11434. Start it and pull MedGemma 4B.")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    total = len(records) * args.runs
    print(f"Running {len(records)} records x {args.runs} run(s) = {total} generations "
          f"(~{total * 1.5:.0f} min at 1.5 min each)\n")

    results: list[scoring.RecordResult] = []
    done = 0
    for record in records:
        form = FORMS[args.form or record.form_id]
        for run in range(1, args.runs + 1):
            done += 1
            out_path = args.out / f"record{record.id:03d}_{form.id}_run{run}.json"
            if args.resume and out_path.exists():
                results.append(_load_result(out_path))
                print(f"[{done}/{total}] record {record.id} run {run} — cached")
                continue
            print(f"[{done}/{total}] record {record.id} ({record.word_count}w) "
                  f"-> {form.name}, run {run}… ", end="", flush=True)
            try:
                sections, missing, was_condensed, seconds, parsed_ok = asyncio.run(
                    generate_one(record, form, args.fast)
                )
            except OllamaUnavailableError as e:
                print(f"\n  ABORT — {e}")
                break
            result = score_one(record, form, sections, missing, was_condensed, seconds, run, parsed_ok)
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
    return 0


def _load_result(path: Path) -> scoring.RecordResult:
    """Rehydrate just enough of a cached run for the aggregate report."""
    d = json.loads(path.read_text(encoding="utf-8"))
    inv = d["invariants"]
    checks = [scoring.Check(name=f["name"], passed=False, detail=f["detail"]) for f in inv["failures"]]
    checks += [scoring.Check(name=f"passed{i}", passed=True) for i in range(inv["passed"])]
    cov = d["section_coverage"]
    c = d.get("cpt")
    o = d.get("omissions") or {}
    return scoring.RecordResult(
        record_id=d["record_id"], form_id=d["form_id"], run=d["run"], seconds=d["seconds"],
        was_condensed=d["was_condensed"], checks=checks,
        cpt=None if not c else scoring.CptScore(
            gold=tuple(c["gold"]), suggested=tuple(c["suggested"]), hits=tuple(c["hits"]),
            missed_section=tuple(c["missed_section"]), table_gap=tuple(c["table_gap"]),
            extra=tuple(c["extra"]),
        ),
        omissions=scoring.OmissionScore(
            stated=tuple(range(o.get("stated", 0))), present=tuple(range(o.get("present", 0))),
            dropped=tuple(o.get("dropped", ())),
        ),
        flags=[scoring.Flag(section=f["section"], text=f["text"], context=f.get("context", ""))
               for f in d.get("flags", [])],
        sections_present=cov["present"], sections_expected=cov["expected"],
        sections_missing=cov["missing"], note_chars=d.get("note_chars", 0),
    )


if __name__ == "__main__":
    raise SystemExit(main())
