"""The one code path that runs a corpus record through the real generation pipeline and scores it.

Both `scripts/eval_corpus.py` (CLI) and `app/ui/evals_api.py` (the Evals tab) call THESE functions
— there is no second implementation to drift.

**The isolation guarantee is structural, not a convention.** `run_record` takes an `EvalRecord`
and a `FormSpec`. There is no parameter through which a patient id could enter, and this module
imports nothing from `app.storage`. That is why a UI-triggered sweep cannot write synthetic
patients into the clinician's encrypted database, and it is why the eval path drives the pipeline
functions directly instead of POSTing to `/api/generate` (which requires a patient row).
`tests/test_eval_isolation.py` enforces both halves — a source-level import scan and a behavioural
sweep that asserts the patient table is untouched.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.generate import billing, chunked, cpt, ollama_client, postprocess, traceability
from app.generate.ollama_client import generate_note
from app.generate.parser import parse_plain
from app.generate.prompt import PatientContext, build_prompt, render_prior_block
from evals import dataset, score as scoring

# Mirrors app/ui/server.py:_finalize_note — kept in sync so the invariant check for "a condensed
# dictation always warns the clinician" tests the real contract.
CONDENSE_WARNING = "was long and was automatically condensed"
CONDENSE_WARNING_HARD = "had to be condensed to fit the model even after"


#: form_id recorded for a billing-only sweep. Not a real form — it marks a result whose note-side
#: blocks were never measured, so a reader cannot mistake empty invariants for passing ones.
BILLING_ONLY_FORM = "(billing-only)"


def build_missing(parsed_missing: list[str], code_flags: list[str],
                  was_condensed: bool, still_over: bool) -> list[str]:
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
    """One full pipeline pass, mirroring app/ui/server.py line for line.

    Returns (sections, missing, was_condensed, seconds, parsed_ok, draft, folded_raw).

    `folded_raw` counts headings the MODEL folded, measured on the raw parse BEFORE
    `postprocess.split_folded_headings` repairs them. Without it the "content in bodies, not
    headings" invariant goes permanently green once the repair lands, and a model regression
    becomes invisible — the repair would silently absorb a worsening model.
    """
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

    # The billing draft reads the RAW transcript, so it is computed regardless of whether the
    # model produced a parseable note — the same reason /api/generate computes it on its
    # parse-failure path.
    draft = billing.extract(record.transcript, body_part=record.body_part)

    parsed = parse_plain(text)
    if parsed is None:
        return [], [], was_condensed, seconds, False, draft, 0

    folded_raw = sum(1 for s in parsed["sections"] if postprocess.is_folded_heading(s))

    sections = postprocess.apply(form.id, parsed["sections"])
    # Verification anchors against the RAW transcript, not the condensed one, so a value the
    # condense pass introduced without basis is still caught (same as the app).
    sections = traceability.add_verification_flags(sections, record.transcript)
    sections, code_flags = cpt.suggest_codes(sections, form.id)
    draft = billing.reconcile(draft, sections)
    missing = build_missing(parsed["missing_info"], code_flags, was_condensed, still_over)
    return sections, missing, was_condensed, seconds, True, draft, folded_raw


def score_one(record, form, sections, missing, was_condensed, seconds, run, parsed_ok,
              draft=None, folded_raw=0) -> scoring.RecordResult:
    condense_flag = any(CONDENSE_WARNING in m or CONDENSE_WARNING_HARD in m for m in missing)
    present, expected, missing_labels = scoring.section_coverage(sections, form)
    has_gold = record.has_billing_gold and draft is not None
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
        icd=scoring.score_icd(draft, record.icd_codes) if has_gold and record.icd_codes else None,
        billing_detection=scoring.score_billing_detection(draft, record) if has_gold else None,
        minutes=scoring.score_minutes(draft, record) if has_gold else None,
        units=scoring.score_units(draft, record) if has_gold else None,
        agreement=scoring.score_cpt_agreement(sections, draft) if draft is not None else None,
        is_synthetic=record.is_synthetic,
        body_part=record.body_part,
        folded_headings_raw=folded_raw,
    )


def score_billing_only(record, draft, *, seconds: float = 0.0, run: int = 1
                       ) -> scoring.RecordResult:
    """Score ONLY the dictation-derived billing draft, with no model call.

    The billing extractor is deterministic and reads the DICTATION, never the note, so its accuracy
    can be measured without generating anything. That was true all along but had no recorded path:
    `eval_corpus.py` always generated, which at ~1.5 min per record means a 162-record billing
    sweep costs four hours of CPU to measure a component that answers in milliseconds. So billing
    sweeps got run as throwaway scripts and their numbers never reached `evals/results/` — which is
    what the Evals tab reads, so the most-iterated part of the system was the least recorded.

    Generation fields stay at their defaults rather than being faked: `checks` is empty because no
    invariant was evaluated, and an empty list is honestly "not measured" where a synthetic pass
    would be a lie. `evals/results.py` aggregates over whatever blocks are present.
    """
    has_gold = record.has_billing_gold
    return scoring.RecordResult(
        record_id=record.id,
        form_id=BILLING_ONLY_FORM,
        run=run,
        seconds=seconds,
        was_condensed=False,
        icd=scoring.score_icd(draft, record.icd_codes) if has_gold and record.icd_codes else None,
        billing_detection=scoring.score_billing_detection(draft, record) if has_gold else None,
        minutes=scoring.score_minutes(draft, record) if has_gold else None,
        units=scoring.score_units(draft, record) if has_gold else None,
        is_synthetic=record.is_synthetic,
        body_part=record.body_part,
    )


def load_result(path: Path) -> scoring.RecordResult:
    """Rehydrate a cached run for --resume.

    Every block `RecordResult.to_dict()` writes must be read back here. A key added on one side
    only would silently zero that metric for every cached record in a resumed sweep — the failure
    mode `tests/test_eval_score.py`'s round-trip test exists to catch.
    """
    d = json.loads(path.read_text(encoding="utf-8"))
    inv = d["invariants"]
    checks = [scoring.Check(name=f["name"], passed=False, detail=f["detail"]) for f in inv["failures"]]
    checks += [scoring.Check(name=f"passed{i}", passed=True) for i in range(inv["passed"])]
    cov = d["section_coverage"]
    c, o = d.get("cpt"), d.get("omissions") or {}
    icd, det, mins, un, agr = (d.get(k) for k in
                               ("icd", "billing_detection", "minutes", "units", "agreement"))
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
        is_synthetic=d.get("is_synthetic", False), body_part=d.get("body_part"),
        folded_headings_raw=d.get("folded_headings_raw", 0),
        icd=None if not icd else scoring.IcdScore(
            gold=tuple(icd["gold"]), suggested=tuple(icd["suggested"]), hits=tuple(icd["hits"]),
            missed=tuple(icd["missed"]), extra=tuple(icd["extra"]),
            laterality_errors=tuple(tuple(p) for p in icd["laterality_errors"]),
        ),
        billing_detection=None if not det else scoring.BillingDetectionScore(
            gold=tuple(det["gold"]), detected=tuple(det["detected"]), hits=tuple(det["hits"]),
            missed=tuple(det["missed"]), false_positives=tuple(det["false_positives"]),
            distractor_leaks=tuple(tuple(p) for p in det["distractor_leaks"]),
            surfaced=tuple(det.get("surfaced", ())),
        ),
        minutes=None if not mins else scoring.MinutesScore(
            cells=tuple(scoring.MinutesCell(code=x["code"], gold=x["gold"],
                                            extracted=x["extracted"], basis=x.get("basis", ""))
                        for x in mins["cells"]),
        ),
        units=None if not un else scoring.UnitsScore(
            gold_units=un["gold_units"], computed_units=un["computed_units"],
            gold_timed_minutes=un["gold_timed_minutes"],
            computed_timed_minutes=un["computed_timed_minutes"],
            gold_units_ama=un.get("gold_units_ama"),
            computed_units_ama=un.get("computed_units_ama"),
            untimed_leak=tuple(un.get("untimed_leak", ())),
            method_disagreement=un.get("method_disagreement", False),
            computed_units_if_confirmed=un.get("computed_units_if_confirmed"),
        ),
        agreement=None if not agr else scoring.AgreementScore(
            chip_only=tuple(agr["chip_only"]), dictation_only=tuple(agr["dictation_only"]),
            both=tuple(agr["both"]),
        ),
    )


#: A generation that reports longer than this did not take that long — the machine slept through
#: it. The slowest REAL note measured on any box here is ~10 minutes, so an hour is far above any
#: plausible generation and far below the multi-hour figures a suspend produces.
_MAX_PLAUSIBLE_SECONDS = 3600


def _timed(results):
    """Runs whose wall-clock is believable. See `mean_seconds` for why this is not paranoia."""
    return [r for r in results if 0 < r.seconds <= _MAX_PLAUSIBLE_SECONDS]


def aggregate(results: list[scoring.RecordResult]) -> dict:
    """Headline numbers for a set of results. Safety metrics first, deliberately."""
    if not results:
        return {}
    with_billing = [r for r in results if r.billing_detection]
    with_icd = [r for r in results if r.icd and r.icd.gold]
    with_units = [r for r in results if r.units and r.units.gold_units is not None]
    with_minutes = [r for r in results if r.minutes]

    def _ratio(num, den):
        return round(num / den, 4) if den else None

    cpt_hits = sum(len(r.billing_detection.hits) for r in with_billing)
    cpt_gold = sum(len(r.billing_detection.gold) for r in with_billing)
    cpt_det = sum(len(r.billing_detection.detected) for r in with_billing)
    icd_hits = sum(len(r.icd.hits) for r in with_icd)
    icd_gold = sum(len(r.icd.gold) for r in with_icd)
    cells = [c for r in with_minutes for c in r.minutes.cells]

    return {
        "records": len(results),
        # --- safety (a nonzero value here is a wrong claim, not an incomplete one) ---
        "distractor_leaks": sum(len(r.billing_detection.distractor_leaks) for r in with_billing),
        "untimed_leaks": sum(len(r.units.untimed_leak) for r in with_units),
        "laterality_errors": sum(len(r.icd.laterality_errors) for r in with_icd),
        "minutes_fabricated": sum(r.minutes.fabricated for r in with_minutes),
        # Over-counting units is the overbill; under-counting is a safe gap the clinician fills.
        # Reported apart from `units_exact`, which hides the direction of the error.
        "units_overstated": sum(1 for r in with_units if r.units.overstated),
        "units_understated": sum(1 for r in with_units if r.units.understated),
        # --- accuracy ---
        "cpt_detection_recall": _ratio(cpt_hits, cpt_gold),
        "cpt_detection_precision": _ratio(cpt_hits, cpt_det),
        # Billed outright vs at least raised for confirmation. The gap is clinician work, not error.
        "cpt_surfaced_recall": _ratio(
            sum(len([c for c in r.billing_detection.gold if c in r.billing_detection.surfaced])
                for r in with_billing), cpt_gold),
        "icd_recall": _ratio(icd_hits, icd_gold),
        "icd_precision": _ratio(icd_hits, sum(len(r.icd.suggested) for r in with_icd)),
        "minutes_exact": _ratio(sum(r.minutes.exact for r in with_minutes), len(cells)),
        "minutes_within_2": _ratio(sum(r.minutes.within_2 for r in with_minutes), len(cells)),
        "minutes_not_extracted": sum(r.minutes.not_extracted for r in with_minutes),
        "minutes_mae": (round(sum(abs(c.delta) for c in cells if c.delta is not None)
                              / max(1, sum(1 for c in cells if c.delta is not None)), 2)
                        if cells else None),
        "units_exact": _ratio(sum(1 for r in with_units if r.units.exact), len(with_units)),
        # Right after ONE confirmation click — the question the clinician actually has.
        "units_exact_if_confirmed": _ratio(
            sum(1 for r in with_units if r.units.exact_if_confirmed), len(with_units)),
        "timed_minutes_exact": _ratio(sum(1 for r in with_units if r.units.minutes_exact),
                                      len(with_units)),
        "method_disagreements": sum(1 for r in with_units if r.units.method_disagreement),
        # --- pipeline health (unchanged tiers) ---
        "invariants_passed": sum(r.invariants_passed for r in results),
        "invariants_total": sum(len(r.checks) for r in results),
        "flags_raised": sum(len(r.flags) for r in results),
        # How often the MODEL folded content into a heading, counted before the
        # deterministic repair. This is the number that shows the model regressing.
        "folded_headings_raw": sum(r.folded_headings_raw for r in results),
        # SUSPEND-INFLATED runs are excluded from the mean rather than averaged in. On Windows
        # both perf_counter and monotonic keep counting while the machine is ASLEEP, so a sweep
        # left running overnight reported a single generation as having taken 23 HOURS and a mean
        # of three. Those numbers are not slow generations, they are a closed laptop lid, and
        # averaging them in makes the one metric that should say "this is too slow for a clinic"
        # useless. Excluded and COUNTED, never silently dropped — see `timed_runs` below.
        "mean_seconds": (round(sum(r.seconds for r in _timed(results)) / len(_timed(results)), 1)
                         if _timed(results) else None),
        "max_seconds": (round(max(r.seconds for r in _timed(results)), 1)
                        if _timed(results) else None),
        "timed_runs": len(_timed(results)),
        "untimed_runs": len(results) - len(_timed(results)),
    }
