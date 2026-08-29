"""Server-side generation queue, so a note that takes minutes never holds the clinician still.

CLAUDE.md budgets ~1-2 minutes per note. Measured across 21 real generations on the DEV box the
median was 7.0 minutes and 21 of 21 exceeded the budget, with the floor set by a 91-WORD follow-up
-- so the cost is driven by output length and template size, not by how much the therapist said.
Two of the three fixes CLAUDE.md floats do not survive contact with that measurement:

  * "cut num_predict" -- 3072 is a CEILING, not a target. A note is ~1200-2500 tokens, so the
    ceiling is not binding and lowering it would truncate long notes before it saved a second.
  * "generate per-section" -- the same total tokens through more prompts. On a 4B model each
    section would also lose the whole-note context that internal consistency (rule 4) depends on.

What is actually left is the third option, and it is a product change rather than a speed one:
STOP MAKING THE WAIT BLOCKING. A therapist between patients cannot stand at the screen for seven
minutes, but they can start a note, walk to the next patient, dictate that one too, and review
both at the end of the block. So generation moves off the request:

  POST /api/generate/jobs        enqueue, get an id back immediately
  GET  /api/generate/jobs        the tray -- everything queued, running, or waiting for review
  GET  /api/generate/jobs/{id}   status + the text written since `cursor` (live tail, reattachable)

Design decisions worth keeping:

* ONE worker, strictly serialized. Two 4B generations on a 4-core CPU-only box do not run twice as
  fast, they run twice as slowly each and double the memory pressure that
  docs/performance-tuning.md identifies as the real bottleneck. This mirrors the single serialized
  MedASR worker already used by live capture, for the same reason.
* The buffer is append-only and clients read it by CURSOR, so closing the tab, navigating to
  another patient, or reloading the page all reattach to a running note instead of killing it.
  That is the entire point -- the old /api/generate/stream tied the note's life to one HTTP
  connection.
* Jobs live in memory and are LOST on a server restart, deliberately: a generated note is a draft
  the clinician has not reviewed, and persisting unreviewed drafts into the encrypted store would
  put un-signed model output in the same place as signed records. The queue survives the browser,
  which is the case that actually happens; it does not survive quitting the app.
* Nothing here saves anything. A finished job holds a result the clinician still has to review and
  Save, exactly as before.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

#: Finished jobs stay in the tray so the clinician can come back to them, but not forever -- this
#: is unreviewed patient content held in memory. Swept when it is this old, or when the tray grows
#: past _MAX_FINISHED.
FINISHED_TTL_SECONDS = 6 * 60 * 60
_MAX_FINISHED = 40


@dataclass
class Job:
    id: str
    patient_id: str
    patient_name: str
    form_id: str
    form_name: str
    fast: bool
    #: Everything needed to run the generation, opaque to this module. Holding the dictation here
    #: is why a job is never written to disk.
    payload: dict = field(repr=False, default_factory=dict)
    status: str = QUEUED
    detail: str = ""            # a human-readable stage ("Condensing a very long dictation…")
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    buffer: str = field(repr=False, default="")
    result: dict | None = field(repr=False, default=None)
    error: str | None = None
    _task: asyncio.Task | None = field(repr=False, default=None, compare=False)

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    @property
    def finished(self) -> bool:
        return self.status in (DONE, ERROR, CANCELLED)

    def summary(self, position: int | None = None) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_name": self.patient_name,
            "form_id": self.form_id,
            "form_name": self.form_name,
            "fast": self.fast,
            "status": self.status,
            "detail": self.detail,
            "created_at": self.created_at,
            "elapsed_seconds": round(self.elapsed, 1),
            "chars_written": len(self.buffer),
            "queue_position": position,
            "error": self.error,
        }


#: The generation callable, injected so this module never imports the server or the model client.
#: It is handed the job and an `emit(text)` callback for streaming, and returns the finished
#: result dict. Set once at startup by app/ui/server.py.
Runner = Callable[[Job, Callable[[str], None]], Awaitable[dict]]


class JobQueue:
    def __init__(self, runner: Runner):
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []           # submission order, for a stable tray
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._running_id: str | None = None
        #: Ids the clinician cancelled. Cancelling the running job and shutting the whole worker
        #: down both surface as a CancelledError at the same await, so the worker needs to know
        #: which one happened: swallowing a shutdown would leave the worker alive after stop(),
        #: and re-raising a per-job cancel would kill the queue over one dismissed note.
        self._cancelled_ids: set[str] = set()

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_forever(), name="cadence-generation-worker")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    # -- submission ----------------------------------------------------------
    def submit(self, *, patient_id: str, patient_name: str, form_id: str, form_name: str,
               fast: bool, payload: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], patient_id=patient_id, patient_name=patient_name,
                  form_id=form_id, form_name=form_name, fast=fast, payload=payload)
        self._jobs[job.id] = job
        self._order.append(job.id)
        self._pending.put_nowait(job.id)
        self._sweep()
        self.start()
        return job

    # -- reads ---------------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def position(self, job_id: str) -> int | None:
        """1-based place in the wait line, or None if it is running or finished. What the tray
        shows instead of an ETA -- an honest "2nd in line" beats a fabricated minutes estimate on
        hardware whose throughput swings with whatever else is open."""
        if job_id == self._running_id:
            return None
        waiting = [j for j in self._order
                   if self._jobs[j].status == QUEUED and j != self._running_id]
        return waiting.index(job_id) + 1 if job_id in waiting else None

    def list(self) -> list[dict]:
        return [self._jobs[j].summary(self.position(j)) for j in self._order if j in self._jobs]

    def tail(self, job_id: str, cursor: int) -> dict | None:
        """Status plus whatever has been written since `cursor`. The cursor is a character offset
        into an append-only buffer, which is what makes a reload reattach rather than restart."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        cursor = max(0, min(cursor, len(job.buffer)))
        return {
            **job.summary(self.position(job_id)),
            "cursor": len(job.buffer),
            "text": job.buffer[cursor:],
            "result": job.result,
            "summary": job.payload.get("summary", ""),
            "extra_info": job.payload.get("extra_info"),
        }

    # -- cancellation --------------------------------------------------------
    def cancel(self, job_id: str) -> bool:
        """Cancel a queued or running job, or dismiss a finished one from the tray."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.finished:
            self._forget(job_id)
            return True
        self._cancelled_ids.add(job_id)
        if job._task is not None:
            job._task.cancel()
        job.status = CANCELLED
        job.detail = "Cancelled"
        job.finished_at = time.time()
        return True

    def _forget(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._cancelled_ids.discard(job_id)
        if job_id in self._order:
            self._order.remove(job_id)

    def _sweep(self) -> None:
        now = time.time()
        stale = [j for j in self._order
                 if self._jobs[j].finished
                 and now - (self._jobs[j].finished_at or now) > FINISHED_TTL_SECONDS]
        finished = [j for j in self._order if self._jobs[j].finished]
        for j in stale + finished[:max(0, len(finished) - _MAX_FINISHED)]:
            self._forget(j)

    # -- the worker ----------------------------------------------------------
    async def _run_forever(self) -> None:
        while True:
            job_id = await self._pending.get()
            job = self._jobs.get(job_id)
            if job is None or job.status != QUEUED:
                continue                                   # cancelled while it waited
            self._running_id = job_id
            job.status = RUNNING
            job.started_at = time.time()
            job.detail = "Writing the note…"

            def emit(text: str, _job: Job = job) -> None:
                _job.buffer += text

            job._task = asyncio.create_task(self._runner(job, emit))
            try:
                job.result = await job._task
                job.status = DONE
                job.detail = "Ready for review"
            except asyncio.CancelledError:
                job.status = CANCELLED
                job.detail = "Cancelled"
                if job.id not in self._cancelled_ids:
                    raise                                   # the WORKER is shutting down
            except Exception as e:                          # noqa: BLE001
                # A failed note must never take the worker down with it, or one bad dictation
                # silently stops every later note in the queue.
                logger.exception("generation job %s failed", job.id)
                job.status = ERROR
                job.error = str(e) or "Generation failed unexpectedly — please try again."
                job.detail = "Failed"
            finally:
                job.finished_at = time.time()
                job._task = None
                self._running_id = None
