"""HTTP wiring for the Evals tab.

The two things worth locking here are the ones a UI makes easy to get wrong: the sample endpoint
must stay INSTANT and model-free (it is the cheap first half of the deliberate two-step flow), and
starting a sweep must return immediately rather than blocking an HTTP request for forty minutes.

TestClient is not used as a context manager, so the app lifespan (MedASR load) never runs.

    .venv/Scripts/python.exe -m unittest tests.test_evals_api -v
"""

import unittest

from fastapi.testclient import TestClient

from app.ui import server


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_options_are_driven_by_the_data_tables(self):
        """The pickers read this, so adding a body part is a data-only change with no JS edit."""
        from app.generate import coding_tables
        data = self.client.get("/api/evals/options").json()
        self.assertIn("shoulder", data["body_parts"])
        self.assertEqual(set(data["note_types"]), {"initial", "followup"})
        self.assertEqual(set(data["complexities"]), {"low", "medium", "high"})
        for part in data["body_parts"]:
            self.assertIn(part, coding_tables.BODY_PARTS)

    def test_the_icd_verification_state_is_exposed(self):
        """The UI shows a warning banner while the code table is unsigned-off, so the flag has to
        reach the client rather than living only in a test."""
        from app.generate import coding_tables
        data = self.client.get("/api/evals/options").json()
        self.assertEqual(
            data["icd_table_verified"],
            bool(coding_tables.ICD_TABLE_VERIFIED_BY and coding_tables.ICD_TABLE_VERIFIED_ON),
        )


class SampleEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def _post(self, **kw):
        body = {"body_part": "shoulder", "note_type": "followup", "count": 3,
                "complexity": "medium", "seed": 77}
        body.update(kw)
        return self.client.post("/api/evals/samples", json=body)

    def test_samples_come_back_with_their_gold_labels(self):
        data = self._post().json()
        self.assertEqual(data["count"], 3)
        s = data["samples"][0]
        for key in ("transcript", "icd_codes", "interventions", "distractors",
                    "total_timed_minutes", "expected_units", "expected_units_ama"):
            self.assertIn(key, s)
        self.assertTrue(s["transcript"])

    def test_samples_are_deterministic(self):
        self.assertEqual([x["transcript"] for x in self._post().json()["samples"]],
                         [x["transcript"] for x in self._post().json()["samples"]])

    def test_samples_are_not_written_to_disk_unless_asked(self):
        self.assertEqual(self._post().json()["written_to"], "")

    def test_a_bad_body_part_is_400_not_500(self):
        self.assertEqual(self._post(body_part="elbow").status_code, 400)

    def test_a_bad_complexity_is_400(self):
        self.assertEqual(self._post(complexity="extreme").status_code, 400)


class RunEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_unknown_run_id_is_404(self):
        self.assertEqual(self.client.get("/api/evals/runs/nope").status_code, 404)
        self.assertEqual(self.client.post("/api/evals/runs/nope/cancel").status_code, 404)

    def test_listing_runs_works_with_no_history(self):
        data = self.client.get("/api/evals/runs").json()
        self.assertIn("active", data)
        self.assertIn("past", data)
        self.assertIsInstance(data["past"], list)

    def test_starting_a_sweep_returns_202_immediately(self):
        """A sweep runs for tens of minutes. If this ever blocked, the browser would time out and
        the clinician would have no way to see progress or stop it."""
        from app.ui import evals_api

        original = evals_api._run_sweep
        try:
            # Replace the sweep body so nothing touches Ollama — this test is about the transport,
            # not the pipeline (which tests/test_eval_isolation.py drives with a mocked model).
            async def _noop(job, body):
                job.status = "done"
            evals_api._run_sweep = _noop
            r = self.client.post("/api/evals/runs", json={
                "body_part": "shoulder", "note_type": "followup", "count": 1,
                "complexity": "low", "seed": 5, "include_handwritten": False})
            self.assertEqual(r.status_code, 202, r.text)
            self.assertIn("total", r.json())
            run_id = r.json()["run_id"]
            # The job is registered and pollable straight away.
            self.assertEqual(self.client.get(f"/api/evals/runs/{run_id}").status_code, 200)
        finally:
            evals_api._run_sweep = original

    def test_cancel_flags_the_job(self):
        from app.ui import evals_api
        job = evals_api.EvalJob(run_id="test-cancel", total=5, config={})
        evals_api._JOBS["test-cancel"] = job
        try:
            r = self.client.post("/api/evals/runs/test-cancel/cancel")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(job.cancel)
        finally:
            evals_api._JOBS.pop("test-cancel", None)

    def test_job_snapshot_reports_progress_and_an_eta(self):
        from app.ui import evals_api
        job = evals_api.EvalJob(run_id="x", total=10, config={})
        job.done = 4
        snap = job.snapshot()
        self.assertEqual((snap["done"], snap["total"]), (4, 10))
        self.assertGreaterEqual(snap["eta_seconds"], 0)
        self.assertEqual(snap["status"], "running")


if __name__ == "__main__":
    unittest.main()
