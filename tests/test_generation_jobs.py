"""Tests for the background generation queue (app/generate/jobs.py + its endpoints).

The feature exists because a note takes 5-9 minutes on the target hardware and the clinician
cannot stand still for that. So the behaviours that matter are the ones that let them walk away:

  * the POST returns immediately, before any model work happens
  * closing the tab does NOT kill the note — the buffer lives on the server and is read by cursor
  * a second note QUEUES rather than competing for the same 4 cores
  * one failing note does not stop the queue behind it

No model, no network. The runner is a stub, which is the whole reason the queue takes one.

    .venv/Scripts/python.exe -m unittest tests.test_generation_jobs -v
"""

import asyncio
import unittest

from app.generate import jobs


def _run(coro):
    return asyncio.run(coro)


async def _settle(queue, *, until, timeout=5.0):
    """Pump the loop until `until()` or the timeout — the worker is a real asyncio task, so tests
    have to let it run rather than assuming synchronous completion."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if until():
            return True
        await asyncio.sleep(0.01)
    return False


def _submit(queue, name="Test Patient", **kw):
    return queue.submit(patient_id="p1", patient_name=name, form_id="followup",
                        form_name="Follow-Up Visit", fast=False, payload={"summary": "x"}, **kw)


class SubmissionTests(unittest.TestCase):
    def test_submit_returns_immediately_with_a_queued_job(self):
        async def main():
            started = asyncio.Event()

            async def runner(job, emit):
                started.set()
                await asyncio.sleep(10)
                return {}

            q = jobs.JobQueue(runner)
            job = _submit(q)
            # The critical assertion: submit() did not await the runner.
            self.assertEqual(job.status, jobs.QUEUED)
            self.assertFalse(started.is_set())
            await q.stop()

        _run(main())

    def test_a_job_runs_and_finishes_with_its_result(self):
        async def main():
            async def runner(job, emit):
                emit("## Subjective\n")
                emit("Patient reports improvement.")
                return {"sections": [], "form_id": "followup"}

            q = jobs.JobQueue(runner)
            job = _submit(q)
            self.assertTrue(await _settle(q, until=lambda: job.status == jobs.DONE))
            self.assertEqual(job.buffer, "## Subjective\nPatient reports improvement.")
            self.assertEqual(job.result, {"sections": [], "form_id": "followup"})
            self.assertEqual(job.detail, "Ready for review")
            await q.stop()

        _run(main())


class SerializationTests(unittest.TestCase):
    def test_only_one_job_runs_at_a_time(self):
        """Two 4B generations on a 4-core CPU-only box do not run twice as fast; they run twice as
        slowly each and double the memory pressure that is the real bottleneck."""
        async def main():
            concurrent = 0
            peak = 0
            release = asyncio.Event()

            async def runner(job, emit):
                nonlocal concurrent, peak
                concurrent += 1
                peak = max(peak, concurrent)
                await release.wait()
                concurrent -= 1
                return {}

            q = jobs.JobQueue(runner)
            a, b, c = _submit(q, "A"), _submit(q, "B"), _submit(q, "C")
            self.assertTrue(await _settle(q, until=lambda: a.status == jobs.RUNNING))
            self.assertEqual(b.status, jobs.QUEUED)
            self.assertEqual(c.status, jobs.QUEUED)
            release.set()
            self.assertTrue(await _settle(q, until=lambda: c.status == jobs.DONE))
            self.assertEqual(peak, 1)
            await q.stop()

        _run(main())

    def test_queue_position_is_reported_for_waiting_jobs_only(self):
        async def main():
            release = asyncio.Event()

            async def runner(job, emit):
                await release.wait()
                return {}

            q = jobs.JobQueue(runner)
            a, b, c = _submit(q, "A"), _submit(q, "B"), _submit(q, "C")
            self.assertTrue(await _settle(q, until=lambda: a.status == jobs.RUNNING))
            self.assertIsNone(q.position(a.id))     # running, not waiting
            self.assertEqual(q.position(b.id), 1)
            self.assertEqual(q.position(c.id), 2)
            release.set()
            self.assertTrue(await _settle(q, until=lambda: c.status == jobs.DONE))
            self.assertIsNone(q.position(c.id))
            await q.stop()

        _run(main())


class ReattachTests(unittest.TestCase):
    def test_tail_returns_only_text_since_the_cursor(self):
        """This is what makes closing the tab safe: the buffer is append-only and owned by the
        server, so a reload resumes from an offset instead of restarting the note."""
        async def main():
            gate = asyncio.Event()

            async def runner(job, emit):
                emit("first ")
                await gate.wait()
                emit("second")
                return {"ok": True}

            q = jobs.JobQueue(runner)
            job = _submit(q)
            self.assertTrue(await _settle(q, until=lambda: job.buffer.startswith("first")))

            t1 = q.tail(job.id, 0)
            self.assertEqual(t1["text"], "first ")
            self.assertEqual(t1["cursor"], 6)
            self.assertEqual(t1["status"], jobs.RUNNING)
            self.assertIsNone(t1["result"])

            gate.set()
            self.assertTrue(await _settle(q, until=lambda: job.status == jobs.DONE))

            t2 = q.tail(job.id, t1["cursor"])
            self.assertEqual(t2["text"], "second")     # not the whole note again
            self.assertEqual(t2["result"], {"ok": True})
            await q.stop()

        _run(main())

    def test_tail_of_an_unknown_job_is_none(self):
        async def main():
            q = jobs.JobQueue(lambda job, emit: asyncio.sleep(0))
            self.assertIsNone(q.tail("nope", 0))

        _run(main())

    def test_an_out_of_range_cursor_is_clamped(self):
        async def main():
            async def runner(job, emit):
                emit("abc")
                return {}

            q = jobs.JobQueue(runner)
            job = _submit(q)
            self.assertTrue(await _settle(q, until=lambda: job.status == jobs.DONE))
            self.assertEqual(q.tail(job.id, 9999)["text"], "")
            self.assertEqual(q.tail(job.id, -5)["text"], "abc")
            await q.stop()

        _run(main())


class FailureIsolationTests(unittest.TestCase):
    def test_one_failing_job_does_not_stop_the_queue(self):
        """Otherwise a single bad dictation silently stalls every note behind it."""
        async def main():
            async def runner(job, emit):
                if job.patient_name == "Boom":
                    raise RuntimeError("model exploded")
                return {"ok": job.patient_name}

            q = jobs.JobQueue(runner)
            bad, good = _submit(q, "Boom"), _submit(q, "Fine")
            self.assertTrue(await _settle(q, until=lambda: good.status == jobs.DONE))
            self.assertEqual(bad.status, jobs.ERROR)
            self.assertIn("model exploded", bad.error)
            self.assertEqual(good.result, {"ok": "Fine"})
            await q.stop()

        _run(main())


class CancellationTests(unittest.TestCase):
    def test_cancelling_a_running_job_leaves_the_worker_alive(self):
        async def main():
            async def runner(job, emit):
                if job.patient_name == "Slow":
                    await asyncio.sleep(30)
                return {"ok": job.patient_name}

            q = jobs.JobQueue(runner)
            slow, after = _submit(q, "Slow"), _submit(q, "After")
            self.assertTrue(await _settle(q, until=lambda: slow.status == jobs.RUNNING))
            self.assertTrue(q.cancel(slow.id))
            self.assertEqual(slow.status, jobs.CANCELLED)
            # The queue must keep going — a cancelled note is not a crashed worker.
            self.assertTrue(await _settle(q, until=lambda: after.status == jobs.DONE))
            await q.stop()

        _run(main())

    def test_cancelling_a_queued_job_stops_it_ever_running(self):
        async def main():
            ran = []
            release = asyncio.Event()

            async def runner(job, emit):
                ran.append(job.patient_name)
                if job.patient_name == "A":
                    await release.wait()
                return {}

            q = jobs.JobQueue(runner)
            a, b = _submit(q, "A"), _submit(q, "B")
            self.assertTrue(await _settle(q, until=lambda: a.status == jobs.RUNNING))
            q.cancel(b.id)
            release.set()
            self.assertTrue(await _settle(q, until=lambda: a.status == jobs.DONE))
            await asyncio.sleep(0.05)
            self.assertEqual(ran, ["A"])
            await q.stop()

        _run(main())

    def test_cancelling_a_finished_job_dismisses_it_from_the_tray(self):
        async def main():
            q = jobs.JobQueue(lambda job, emit: _done())

            async def _done():
                return {}

            job = _submit(q)
            self.assertTrue(await _settle(q, until=lambda: job.status == jobs.DONE))
            self.assertTrue(q.cancel(job.id))
            self.assertEqual(q.list(), [])
            self.assertIsNone(q.get(job.id))
            await q.stop()

        _run(main())

    def test_cancelling_an_unknown_job_is_false(self):
        async def main():
            q = jobs.JobQueue(lambda job, emit: asyncio.sleep(0))
            self.assertFalse(q.cancel("nope"))

        _run(main())


class TrayTests(unittest.TestCase):
    def test_list_preserves_submission_order_and_carries_no_note_text(self):
        async def main():
            release = asyncio.Event()

            async def runner(job, emit):
                emit("some note text")
                await release.wait()
                return {}

            q = jobs.JobQueue(runner)
            _submit(q, "A"), _submit(q, "B")
            self.assertTrue(await _settle(q, until=lambda: q.list()[0]["status"] == jobs.RUNNING))
            rows = q.list()
            self.assertEqual([r["patient_name"] for r in rows], ["A", "B"])
            for r in rows:
                self.assertNotIn("text", r)
                self.assertNotIn("result", r)
            self.assertEqual(rows[0]["chars_written"], len("some note text"))
            release.set()
            await q.stop()

        _run(main())

    def test_finished_jobs_are_swept_once_the_tray_grows_past_its_cap(self):
        async def main():
            async def runner(job, emit):
                return {}

            q = jobs.JobQueue(runner)
            for i in range(jobs._MAX_FINISHED + 5):
                _submit(q, f"P{i}")
            self.assertTrue(await _settle(
                q, until=lambda: all(j["status"] == jobs.DONE for j in q.list()), timeout=10))
            _submit(q, "trigger-sweep")
            self.assertLessEqual(len([j for j in q.list() if j["status"] == jobs.DONE]),
                                 jobs._MAX_FINISHED)
            await q.stop()

        _run(main())


class JobEndpointTests(unittest.TestCase):
    """The HTTP wiring. Uses TestClient as a CONTEXT MANAGER, unlike the other endpoint suites,
    because the queue's worker is a background asyncio task and needs the app's event loop to
    outlive a single request — which is precisely the property the feature depends on."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        from app.storage import db
        from app.transcribe import medasr_client
        from app.ui import server

        self.server = server
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_jobs_"))
        self._orig_db = (db.ENC_PATH, db.KEYFILE)
        self._rmtree, self._db = shutil.rmtree, db
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"

        # The lifespan would otherwise load the real MedASR weights.
        self._orig_load = medasr_client.load_model
        self._medasr = medasr_client
        medasr_client.load_model = lambda: None

        # Swap the runner so no model is called. The queue object itself is the real one, so the
        # endpoints are exercised exactly as they ship.
        self._orig_runner = server._job_queue._runner

        async def runner(job, emit):
            emit("## Subjective\nStub note.")
            return {"sections": [{"heading": "Subjective", "body": "Stub note.",
                                  "carried_forward": False}],
                    "missing_info": [], "form_id": job.form_id, "form_name": job.form_name,
                    "used_prior": False}

        server._job_queue._runner = runner

    def tearDown(self):
        self.server._job_queue._runner = self._orig_runner
        self.server._job_queue._jobs.clear()
        self.server._job_queue._order.clear()
        self._medasr.load_model = self._orig_load
        self._db.shutdown()
        self._db.ENC_PATH, self._db.KEYFILE = self._orig_db
        self._rmtree(self._tmp, ignore_errors=True)

    def _client(self):
        from fastapi.testclient import TestClient
        return TestClient(self.server.app)

    def test_enqueue_validates_before_accepting(self):
        with self._client() as c:
            pid = c.post("/api/patients", json={"name": "Ada Lovelace"}).json()["id"]
            self.assertEqual(c.post("/api/generate/jobs", json={
                "patient_id": pid, "form_id": "nope", "summary": "x"}).status_code, 400)
            self.assertEqual(c.post("/api/generate/jobs", json={
                "patient_id": "missing", "form_id": "followup", "summary": "x"}).status_code, 404)

    def test_enqueue_then_poll_to_completion(self):
        with self._client() as c:
            pid = c.post("/api/patients", json={"name": "Ada Lovelace"}).json()["id"]
            r = c.post("/api/generate/jobs", json={
                "patient_id": pid, "form_id": "followup", "summary": "gait training fifteen minutes"})
            self.assertEqual(r.status_code, 202)
            job = r.json()
            self.assertEqual(job["patient_name"], "Ada Lovelace")
            self.assertIn(job["status"], (jobs.QUEUED, jobs.RUNNING))

            for _ in range(200):
                detail = c.get(f"/api/generate/jobs/{job['id']}?cursor=0").json()
                if detail["status"] in (jobs.DONE, jobs.ERROR):
                    break
            self.assertEqual(detail["status"], jobs.DONE)
            self.assertEqual(detail["text"], "## Subjective\nStub note.")
            self.assertEqual(detail["result"]["sections"][0]["heading"], "Subjective")
            # Echoed back so a note reviewed after a page reload still knows its own dictation.
            self.assertEqual(detail["summary"], "gait training fifteen minutes")

            # A cursor at the end returns nothing new — that is what makes polling cheap.
            self.assertEqual(c.get(
                f"/api/generate/jobs/{job['id']}?cursor={detail['cursor']}").json()["text"], "")

            self.assertEqual([j["id"] for j in c.get("/api/generate/jobs").json()], [job["id"]])
            self.assertEqual(c.delete(f"/api/generate/jobs/{job['id']}").status_code, 204)
            self.assertEqual(c.get("/api/generate/jobs").json(), [])

    def test_unknown_job_is_404(self):
        with self._client() as c:
            self.assertEqual(c.get("/api/generate/jobs/nope").status_code, 404)
            self.assertEqual(c.delete("/api/generate/jobs/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
