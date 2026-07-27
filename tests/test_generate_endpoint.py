"""Integration test of POST /api/generate with a MOCKED model.

The generate endpoint chains a lot — build_prompt, chunked.fit_dictation, the model call,
parse_plain, postprocess, the verification layer, and the CPT suggestion — and until now it was
only ever exercised by slow manual real generations. This drives the whole endpoint deterministically
by patching the Ollama call with a canned note, against a temp DB, so the wiring is regression-tested
without a model. TestClient is not used as a context manager, so the app lifespan (MedASR load)
never runs.

    .venv/Scripts/python.exe -m unittest tests.test_generate_endpoint -v
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.storage import db, repository
from app.ui import server

CANNED_NOTE = """## Therapeutic Exercise
Minutes: 15
Quad sets and straight leg raises performed.

## Objective
Right quad strength 4/5. Sensation intact.
---MISSING---
- none
"""


async def _fake_generate(prompt, timeout_s=600.0, model=None):
    return CANNED_NOTE


_STREAM_MODELS = []  # records the model each streamed call was given (for the fast-tier test)


async def _fake_stream(prompt, timeout_s=1800.0, model=None):
    _STREAM_MODELS.append(model)
    # Yield the canned note in a few chunks, mimicking Ollama's token stream.
    for chunk in ("## Therapeutic Exercise\n", "Minutes: 15\nQuad sets performed.\n\n",
                  "## Objective\nRight quad strength 4/5. Sensation intact.\n---MISSING---\n- none\n"):
        yield chunk


class GenerateEndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        self._orig = (db.ENC_PATH, db.KEYFILE)
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"
        db.init()
        self.pid = repository.create_patient(name="Test PT", dob=None, mrn=None, condition="knee OA")["id"]
        self.client = TestClient(server.app)

    def tearDown(self):
        db.shutdown()
        db.ENC_PATH, db.KEYFILE = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _post(self, **kw):
        body = {"patient_id": self.pid, "form_id": "followup", "summary": "did quad sets", "use_prior": False}
        body.update(kw)
        return self.client.post("/api/generate", json=body)

    def test_full_pipeline_produces_cpt_and_verification(self):
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self._post(summary="patient did quad sets for 15 minutes")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        headings = [s["heading"] for s in data["sections"]]
        self.assertIn("Therapeutic Exercise", headings)
        te = next(s for s in data["sections"] if s["heading"] == "Therapeutic Exercise")
        self.assertIn("[[CPT: 97110", te["body"])                 # deterministic code suggestion
        obj = next(s for s in data["sections"] if s["heading"] == "Objective")
        self.assertIn("4/5", obj["body"])
        self.assertIn("[[NEEDS:", obj["body"])                    # 4/5 + sensation never dictated -> flagged

    def test_unknown_form_is_400(self):
        with patch("app.ui.server.generate_note", _fake_generate):
            self.assertEqual(self._post(form_id="nope").status_code, 400)

    def test_missing_patient_is_404(self):
        with patch("app.ui.server.generate_note", _fake_generate):
            self.assertEqual(self._post(patient_id="p-nope").status_code, 404)

    def test_stream_endpoint_streams_tokens_then_final_note(self):
        with patch("app.ui.server.generate_note", _fake_generate), \
             patch("app.generate.ollama_client.stream_note", _fake_stream):
            r = self.client.post("/api/generate/stream", json={
                "patient_id": self.pid, "form_id": "followup",
                "summary": "patient did quad sets for 15 minutes", "use_prior": False,
            })
        self.assertEqual(r.status_code, 200, r.text)
        events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
        types = [e["type"] for e in events]
        self.assertIn("token", types)          # streamed live, chunk by chunk
        self.assertEqual(types[-1], "done")    # then the finalized, post-processed note
        result = events[-1]["result"]
        te = next(s for s in result["sections"] if s["heading"] == "Therapeutic Exercise")
        self.assertIn("[[CPT: 97110", te["body"])   # same pipeline as /api/generate (CPT suggestion)
        obj = next(s for s in result["sections"] if s["heading"] == "Objective")
        self.assertIn("[[NEEDS:", obj["body"])       # 4/5 never dictated -> verification flag

    def test_stream_unknown_form_is_400_before_streaming(self):
        with patch("app.generate.ollama_client.stream_note", _fake_stream):
            r = self.client.post("/api/generate/stream", json={
                "patient_id": self.pid, "form_id": "nope", "summary": "x", "use_prior": False,
            })
        self.assertEqual(r.status_code, 400)

    def test_revise_stream_applies_and_reprocesses(self):
        with patch("app.generate.ollama_client.stream_note", _fake_stream):
            r = self.client.post("/api/revise/stream", json={
                "patient_id": self.pid, "form_id": "followup",
                "note_text": "## Therapeutic Exercise\nMinutes: 15\nOld wording.",
                "instruction": "make it more concise",
            })
        self.assertEqual(r.status_code, 200, r.text)
        events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
        self.assertEqual(events[-1]["type"], "done")
        te = next(s for s in events[-1]["result"]["sections"] if s["heading"] == "Therapeutic Exercise")
        self.assertIn("[[CPT: 97110", te["body"])  # post-processing pipeline still runs on a revision

    def test_fast_flag_selects_fast_model(self):
        from app.generate import ollama_client
        _STREAM_MODELS.clear()
        with patch("app.generate.ollama_client.stream_note", _fake_stream):
            self.client.post("/api/generate/stream", json={
                "patient_id": self.pid, "form_id": "followup", "summary": "quad sets 15 min", "fast": True})
            self.client.post("/api/generate/stream", json={
                "patient_id": self.pid, "form_id": "followup", "summary": "quad sets 15 min"})  # default
        self.assertEqual(_STREAM_MODELS[0], ollama_client.FAST_MODEL)
        self.assertEqual(_STREAM_MODELS[1], ollama_client.MODEL)

    def test_model_for_maps_tier(self):
        from app.generate import ollama_client
        self.assertEqual(ollama_client.model_for(True), ollama_client.FAST_MODEL)
        self.assertEqual(ollama_client.model_for(False), ollama_client.MODEL)
        self.assertNotEqual(ollama_client.FAST_MODEL, ollama_client.MODEL)

    def test_revise_requires_instruction_and_note(self):
        base = {"patient_id": self.pid, "form_id": "followup", "note_text": "## A\nx", "instruction": ""}
        self.assertEqual(self.client.post("/api/revise/stream", json=base).status_code, 400)
        base = {"patient_id": self.pid, "form_id": "followup", "note_text": " ", "instruction": "shorten"}
        self.assertEqual(self.client.post("/api/revise/stream", json=base).status_code, 400)

    def test_huge_dictation_is_condensed_and_flagged(self):
        # A dictation far over the context budget must take the chunked path (fit_dictation calls
        # the mocked model per chunk) and surface a visible "condensed" completeness warning.
        huge = ("Patient walked and did exercises today. " * 1500)  # ~60k chars, well over budget
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self._post(summary=huge)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(any("condensed" in m.lower() for m in r.json()["missing_info"]))


if __name__ == "__main__":
    unittest.main()
