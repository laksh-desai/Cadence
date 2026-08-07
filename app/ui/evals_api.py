"""HTTP surface for the Evals tab: generate synthetic samples, run a scored sweep, read results.

Three design decisions worth knowing before changing anything here.

**1. `import evals.*` happens INSIDE the handlers, never at module import.** The `evals` package
is developer tooling; a broken or absent one must never stop the clinical app from starting. This
mirrors how `server.py`'s lifespan treats MedASR — an optional subsystem that degrades to a clear
error instead of taking the app down.

**2. A sweep cannot write a synthetic patient into the encrypted database.** Not by policy — by
construction. Every path here goes through `evals.runner`, whose functions take an `EvalRecord`
and a `FormSpec` and have no parameter a patient id could enter through, and which imports nothing
from `app.storage`. `tests/test_eval_isolation.py` enforces that with a source-level import scan
AND a behavioural sweep that asserts the patient table is untouched.

**3. Poll, don't stream.** `/api/generate/stream` uses ndjson because token latency is the point
there. A sweep runs for tens of minutes and needs to survive a page reload, so it exposes a job id
and a small status object. Polling is resumable for free and needs no event buffer or replay.

One sweep at a time (`_eval_lock`): there is one CPU and one Ollama, and a sweep already starves
the clinician's live generation — running two would be strictly worse for no benefit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("cadence.evals")
router = APIRouter(prefix="/api/evals", tags=["evals"])

#: Only one sweep at a time — one CPU, one Ollama.
_eval_lock = asyncio.Lock()

#: run_id -> EvalJob. In memory: a server restart loses the job, but NOT the work, because the
#: loop writes each record's JSON to evals/runs/ as it finishes and `--resume` picks those up.
_JOBS: dict[str, "EvalJob"] = {}

#: Rough seconds per generation on a dev box, used only for a first ETA before any record has
#: finished. Replaced by the measured mean as soon as one completes.
_ETA_SEED_SECONDS = 90.0


@dataclass
class EvalJob:
    run_id: str
    total: int
    config: dict
    status: str = "running"          # running | done | cancelled | error
    done: int = 0
    current: str = ""
    error: str = ""
    started: float = field(default_factory=time.perf_counter)
    started_at: str = ""
    cancel: bool = False
    results_file: str = ""
    aggregate: dict = field(default_factory=dict)

    def snapshot(self) -> dict:
        elapsed = time.perf_counter() - self.started
        per = (elapsed / self.done) if self.done else _ETA_SEED_SECONDS
        return {
            "run_id": self.run_id,
            "status": self.status,
            "done": self.done,
            "total": self.total,
            "current_record": self.current,
            "seconds_elapsed": round(elapsed, 1),
            "eta_seconds": round(max(0, self.total - self.done) * per, 1)
                           if self.status == "running" else 0,
            "error": self.error,
            "results_file": self.results_file,
            "partial_aggregate": self.aggregate,
            "config": self.config,
        }


class SampleRequest(BaseModel):
    body_part: str = "shoulder"
    note_type: str = "followup"
    count: int = 10
    complexity: str = "medium"
    seed: int = 1234
    target_units: int = 4
    write: bool = False   # persist to evals/data/<body_part>_synth.jsonl


class RunRequest(BaseModel):
    body_part: str = "shoulder"
    note_type: str = "followup"
    count: int = 10
    complexity: str = "medium"
    seed: int = 1234
    target_units: int = 4
    runs: int = 1
    fast: bool = False
    #: Include the hand-written records for this body part. They are the NON-CIRCULAR control —
    #: the generator and the extractor share an author, so a synthetic-only score can look good
    #: while both are wrong about real dictation.
    include_handwritten: bool = True


@router.get("/options")
async def options():
    """Everything the pickers need. Driven by the data tables, so adding a body part needs no
    JS change at all."""
    from app.generate import coding_tables
    from evals.synth import banks, generate as synth
    return {
        "body_parts": [b for b in coding_tables.BODY_PARTS if b in banks.TREATMENTS_BY_BODY_PART],
        "note_types": list(synth.NOTE_TYPES),
        "complexities": list(synth.COMPLEXITIES),
        "generator_version": synth.GENERATOR_VERSION,
        "icd_table_verified": bool(coding_tables.ICD_TABLE_VERIFIED_BY
                                   and coding_tables.ICD_TABLE_VERIFIED_ON),
        "icd10cm_year": coding_tables.ICD10CM_YEAR,
    }


def _sample_payload(s) -> dict:
    return {
        "id": s.id,
        "visit_type": s.visit_type,
        "diagnosis": s.diagnosis,
        "transcript": s.transcript,
        "icd_codes": list(s.icd_codes),
        "interventions": [
            {"code": i.code, "label": i.label, "minutes": i.minutes, "timed": i.timed}
            for i in s.interventions
        ],
        "distractors": [{"code": d.code, "reason": d.reason} for d in s.distractors],
        "total_timed_minutes": s.total_timed_minutes,
        "expected_units": s.expected_units,
        "expected_units_ama": s.expected_units_ama,
    }


@router.post("/samples")
async def make_samples(body: SampleRequest):
    """Generate samples and return them WITH their gold labels. Instant — no model involved.

    This is the first half of the deliberate two-step flow: look at what the generator produced
    before committing 40 minutes of CPU to sweeping it.
    """
    from evals.synth import generate as synth
    try:
        samples = synth.generate_corpus(
            body_part=body.body_part, note_type=body.note_type, count=body.count,
            complexity=body.complexity, seed=body.seed, target_units=body.target_units,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    written = ""
    if body.write:
        import json
        from evals.dataset import DATA_DIR
        path = DATA_DIR / f"{body.body_part}_synth.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(s.to_record(), ensure_ascii=False) for s in samples) + "\n",
            encoding="utf-8")
        written = str(path)

    return {
        "count": len(samples),
        "written_to": written,
        "samples": [_sample_payload(s) for s in samples],
    }


async def _run_sweep(job: EvalJob, body: RunRequest):
    """The sweep itself. Every generation goes through evals.runner — the same functions
    scripts/eval_corpus.py calls, and the reason no patient row can be involved."""
    from app.generate.forms import FORMS
    from app.generate.ollama_client import OllamaUnavailableError
    from evals import dataset, results as results_store, runner
    from evals.synth import generate as synth

    try:
        samples = synth.generate_corpus(
            body_part=body.body_part, note_type=body.note_type, count=body.count,
            complexity=body.complexity, seed=body.seed, target_units=body.target_units,
        )
        records = [dataset.parse_record(s.to_record(), "ui-generated") for s in samples]

        if body.include_handwritten:
            try:
                corpus = dataset.load_corpus()
                records += [r for r in corpus
                            if not r.is_synthetic and r.body_part in (None, body.body_part)]
            except dataset.DatasetError as e:
                log.warning("could not load the hand-written control set: %s", e)

        job.total = len(records) * body.runs
        results = []
        for record in records:
            if job.cancel:
                job.status = "cancelled"
                break
            form = FORMS.get(record.form_id) or FORMS["followup"]
            for run in range(1, body.runs + 1):
                if job.cancel:
                    job.status = "cancelled"
                    break
                job.current = f"record {record.id} ({record.word_count}w) run {run}"
                sections, missing, condensed, seconds, ok, draft = await runner.generate_one(
                    record, form, body.fast)
                results.append(runner.score_one(record, form, sections, missing, condensed,
                                                seconds, run, ok, draft))
                job.done += 1
                job.aggregate = runner.aggregate(results)

        if results:
            path = results_store.write_run(results, config={
                "body_part": body.body_part, "note_type": body.note_type,
                "sample_count": len(records), "complexity": body.complexity, "seed": body.seed,
                "target_units": body.target_units, "runs_per_record": body.runs,
                "fast": body.fast, "include_handwritten": body.include_handwritten,
                "source": "ui", "cancelled": job.status == "cancelled",
            }, run_id=job.run_id, started_at=job.started_at)
            job.results_file = path.name
            job.aggregate = results_store.split_aggregate(results)["all"]
        if job.status == "running":
            job.status = "done"
    except OllamaUnavailableError as e:
        job.status, job.error = "error", str(e)
    except Exception as e:                      # noqa: BLE001 — a sweep must never kill the app
        log.exception("eval sweep failed")
        job.status, job.error = "error", f"{type(e).__name__}: {e}"


@router.post("/runs", status_code=202)
async def start_run(body: RunRequest):
    from datetime import datetime, timezone

    from evals import results as results_store

    if _eval_lock.locked():
        raise HTTPException(409, "An eval sweep is already running — one at a time (single CPU).")
    await _eval_lock.acquire()

    job = EvalJob(run_id=results_store.new_run_id(), total=body.count * body.runs,
                  config=body.model_dump(),
                  started_at=datetime.now(timezone.utc).isoformat())
    _JOBS[job.run_id] = job

    async def _guarded():
        try:
            await _run_sweep(job, body)
        finally:
            _eval_lock.release()

    asyncio.create_task(_guarded())
    return job.snapshot()


@router.get("/runs")
async def list_runs(limit: int = 25):
    from evals import results as results_store
    return {
        "active": [j.snapshot() for j in _JOBS.values() if j.status == "running"],
        "past": results_store.list_runs(limit=limit),
    }


@router.get("/runs/{run_id}")
async def run_status(run_id: str):
    job = _JOBS.get(run_id)
    if job is None:
        raise HTTPException(404, "unknown run id")
    return job.snapshot()


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancellation is checked between records, so it takes effect within one generation
    (up to ~2 minutes on CPU) rather than instantly."""
    job = _JOBS.get(run_id)
    if job is None:
        raise HTTPException(404, "unknown run id")
    job.cancel = True
    return job.snapshot()


@router.get("/runs/{run_id}/result")
async def run_result(run_id: str):
    from evals import results as results_store
    job = _JOBS.get(run_id)
    name = job.results_file if job and job.results_file else None
    if not name:
        for row in results_store.list_runs():
            if row.get("run_id") == run_id:
                name = row["file"]
                break
    if not name:
        raise HTTPException(404, "no results file for that run yet")
    return results_store.load_run(results_store.RESULTS_DIR / name)
