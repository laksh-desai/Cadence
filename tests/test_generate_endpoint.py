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
import os
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
        # Billing ships GATED OFF until a coder signs off the ICD tables (cpt.billing_enabled).
        # This suite asserts billing behaviour, so it opts in explicitly rather than depending on
        # the shipped default — and BillingGateTests below covers the default itself.
        self._orig_billing = os.environ.get("CADENCE_BILLING")
        os.environ["CADENCE_BILLING"] = "on"
        self.pid = repository.create_patient(name="Test PT", dob=None, mrn=None, condition="knee OA")["id"]
        self.client = TestClient(server.app)

    def tearDown(self):
        if self._orig_billing is None:
            os.environ.pop("CADENCE_BILLING", None)
        else:
            os.environ["CADENCE_BILLING"] = self._orig_billing
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

    # --- billing draft (app/generate/billing.py) wiring ----------------------------------
    # The draft is derived from the DICTATION, not the note, so these assert WHERE it comes from
    # as much as that it exists — a billing draft built from model-written prose would be the
    # rule-12 misfire the whole design avoids.

    SHOULDER_DICTATION = (
        "Follow-up, right shoulder. Referring diagnosis is right rotator cuff tendinopathy. "
        "Therapeutic exercise for twenty minutes. We did not do gait training today."
    )

    def test_billing_draft_is_returned_for_a_billable_form(self):
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self._post(summary=self.SHOULDER_DICTATION)
        billing = r.json()["billing"]
        self.assertIsNotNone(billing)
        self.assertTrue(billing["confirm_required"])
        self.assertEqual(billing["body_part"], "shoulder")
        self.assertEqual(billing["total_timed_minutes"], 20)
        self.assertEqual(billing["units"]["total_units"], 1)   # 20 min is band 8-22 -> 1 unit
        self.assertEqual(billing["units"]["method"], "cms_substitution")
        self.assertEqual(billing["units_alt"]["method"], "ama_rule_of_eights")
        self.assertIn("M75.101", [c["code"] for c in billing["icd_candidates"]])

    def test_a_negated_treatment_is_returned_but_not_billed(self):
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self._post(summary=self.SHOULDER_DICTATION)
        lines = {li["code"]: li["status"] for li in r.json()["billing"]["interventions"]}
        self.assertEqual(lines["97116"], "negated")
        self.assertEqual(lines["97110"], "performed")

    def test_billing_reconciles_against_the_notes_own_cpt_chips(self):
        """The canned note has a 97110 section but the dictation below names manual therapy, so
        the two sources must disagree in both directions."""
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self._post(summary="Right shoulder. Manual therapy for fifteen minutes.")
        kinds = {c["kind"] for c in r.json()["billing"]["conflicts"]}
        self.assertIn("dictation_only", kinds)   # 97140 dictated, no section written
        self.assertIn("note_only", kinds)        # 97110 charted, never dictated

    def test_billing_survives_a_note_that_failed_to_parse(self):
        """The draft comes from the dictation, so a model that ignored the ## output contract
        entirely still leaves the clinician a usable billing draft."""
        async def _garbage(prompt, timeout_s=600.0, model=None):
            return "I am sorry, I cannot help with that."

        with patch("app.ui.server.generate_note", _garbage):
            r = self._post(summary=self.SHOULDER_DICTATION)
        data = r.json()
        self.assertEqual(data["sections"], [])
        self.assertIsNotNone(data["raw_text"])
        self.assertEqual(data["billing"]["total_timed_minutes"], 20)

    def test_revise_returns_no_billing_draft(self):
        """/api/revise/stream's only input is the NOTE's prose. Billing from it would scan
        model-written text for interventions — the exact rule-12 misfire. The client keeps
        showing the draft from the original generate instead."""
        with patch("app.generate.ollama_client.stream_note", _fake_stream):
            r = self.client.post("/api/revise/stream", json={
                "patient_id": self.pid, "form_id": "followup",
                "note_text": "## Manual Therapy\nMinutes: 15\nGraded mobilizations.",
                "instruction": "make it more concise",
            })
        events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
        self.assertIsNone(events[-1]["result"]["billing"])

    def test_stream_endpoint_returns_the_same_billing_draft(self):
        with patch("app.ui.server.generate_note", _fake_generate), \
             patch("app.generate.ollama_client.stream_note", _fake_stream):
            r = self.client.post("/api/generate/stream", json={
                "patient_id": self.pid, "form_id": "followup",
                "summary": self.SHOULDER_DICTATION, "use_prior": False,
            })
        events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
        billing = events[-1]["result"]["billing"]
        self.assertEqual(billing["total_timed_minutes"], 20)
        self.assertTrue(billing["confirm_required"])

    def test_huge_dictation_is_flagged_as_not_fully_read(self):
        """Over-budget input must never be SILENT — that is the whole of CLAUDE.md rule 16.

        Condensing is off by default now (it measured worse than truncation AND fabricated), so
        the note takes the raw path; the non-negotiable part is that the clinician is told the
        model did not see all of it.
        """
        huge = ("Patient walked and did exercises today. " * 1500)  # ~60k chars, well over budget
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self._post(summary=huge)
        self.assertEqual(r.status_code, 200, r.text)
        warnings = [m for m in r.json()["missing_info"] if "too long for the model" in m.lower()]
        self.assertEqual(len(warnings), 1, r.json()["missing_info"])

    def test_huge_dictation_is_condensed_and_flagged_when_condensing_is_enabled(self):
        """The condense path still works when explicitly turned on for an experiment."""
        huge = ("Patient walked and did exercises today. " * 1500)
        with patch("app.ui.server.generate_note", _fake_generate),              patch("app.generate.chunked.CONDENSE_ENABLED", True):
            r = self._post(summary=huge)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(any("condensed" in m.lower() for m in r.json()["missing_info"]))


class BillingGateTests(unittest.TestCase):
    """Cadence ships with code suggestions OFF until the ICD-10 tables are signed off.

    The gate is COMPUTED from `coding_tables.TABLE_PROVENANCE` rather than configured, so it
    cannot be left on by forgetting a setting — and it opens by itself the moment a coder signs
    the last region. A deliberately-failing test protects the developer; this protects the
    clinician, which is the one that matters once the app leaves the dev machine.
    """

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_gate_"))
        self._orig = (db.ENC_PATH, db.KEYFILE)
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"
        db.init()
        self._orig_billing = os.environ.get("CADENCE_BILLING")
        os.environ.pop("CADENCE_BILLING", None)          # exercise the SHIPPED default
        # /api/status reads state the lifespan normally sets; TestClient is deliberately not used
        # as a context manager here (see the module docstring), so stub it.
        server.app.state.medasr_ready = False
        server.app.state.medasr_error = "not loaded in tests"
        self.pid = repository.create_patient(name="Gate PT", dob=None, mrn=None,
                                             condition="knee OA")["id"]
        self.client = TestClient(server.app)

    def tearDown(self):
        if self._orig_billing is not None:
            os.environ["CADENCE_BILLING"] = self._orig_billing
        db.shutdown()
        db.ENC_PATH, db.KEYFILE = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_unverified_tables_mean_no_codes_reach_the_note(self):
        with patch("app.ui.server.generate_note", _fake_generate):
            r = self.client.post("/api/generate", json={
                "patient_id": self.pid, "form_id": "followup",
                "summary": "Therapeutic exercise for fifteen minutes.", "use_prior": False})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertIsNone(data["billing"], "no billing card while the tables are unverified")
        for sec in data["sections"]:
            self.assertNotIn("[[CPT:", sec["body"], "no CPT chip either — the note is the claim")

    def test_the_status_page_says_why_billing_is_off(self):
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        line = next(i for i in r.json()["integrations"] if i["name"] == "Billing code suggestions")
        self.assertFalse(line["ready"])
        self.assertIn("coder", line["detail"].lower())

    def test_the_status_page_reports_the_running_version(self):
        from app import __version__
        self.assertEqual(self.client.get("/api/status").json()["version"], __version__)


if __name__ == "__main__":
    unittest.main()
