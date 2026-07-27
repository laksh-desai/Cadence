"""HTTP-layer tests for the patient/note CRUD endpoints via TestClient.

The repository is unit-tested elsewhere; this covers the endpoint wiring the repo tests don't —
status codes, request validation, and the save-note flow that ties create_note + carry-snapshot +
persist together (and the delete-note flow that rebuilds the snapshot). Temp DB, no model, and
TestClient is not a context manager so the app lifespan never runs.

    .venv/Scripts/python.exe -m unittest tests.test_endpoints -v
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.storage import db, repository
from app.ui import server


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_test_"))
        self._orig = (db.ENC_PATH, db.KEYFILE)
        db.ENC_PATH = self._tmp / "cadence.db.enc"
        db.KEYFILE = self._tmp / ".keyfile"
        db.init()
        self.client = TestClient(server.app)

    def tearDown(self):
        db.shutdown()
        db.ENC_PATH, db.KEYFILE = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _patient(self, name="Robert Handy"):
        return self.client.post("/api/patients", json={"name": name}).json()["id"]

    def _save_followup(self, pid):
        return self.client.post(f"/api/patients/{pid}/notes", json={
            "form_id": "followup", "form_name": "Follow-Up",
            "sections": [
                {"heading": "Functional Status", "body": "Ambulates 200 ft with a cane.", "carried_forward": False},
                {"heading": "Short-Term Goals", "body": "Walk 300 ft in 2 weeks.", "carried_forward": False},
            ],
            "missing_info": [], "dictation_raw": "raw", "used_prior": False,
        })

    # --- patients ---
    def test_create_patient_201(self):
        r = self.client.post("/api/patients", json={"name": "Alice", "condition": "knee OA"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["name"], "Alice")

    def test_create_blank_name_400(self):
        self.assertEqual(self.client.post("/api/patients", json={"name": "  "}).status_code, 400)

    def test_get_unknown_patient_404(self):
        self.assertEqual(self.client.get("/api/patients/p-nope").status_code, 404)

    def test_patch_updates_then_404(self):
        pid = self._patient()
        r = self.client.patch(f"/api/patients/{pid}", json={"condition": "ACL rehab"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["condition"], "ACL rehab")
        self.assertEqual(self.client.patch("/api/patients/p-nope", json={"condition": "x"}).status_code, 404)

    def test_delete_204_then_404(self):
        pid = self._patient()
        self.assertEqual(self.client.delete(f"/api/patients/{pid}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/patients/{pid}").status_code, 404)

    # --- notes + carry snapshot ---
    def test_save_note_creates_carry_snapshot(self):
        pid = self._patient()
        r = self._save_followup(pid)
        self.assertEqual(r.status_code, 201)
        snap = repository.get_carry_snapshot(pid)
        self.assertIsNotNone(snap)
        self.assertIn("200 ft", snap["functional_status"])

    def test_save_note_unknown_patient_404(self):
        r = self.client.post("/api/patients/p-nope/notes", json={
            "form_id": "followup", "form_name": "F", "sections": [],
            "missing_info": [], "dictation_raw": "", "used_prior": False,
        })
        self.assertEqual(r.status_code, 404)

    def test_delete_last_carry_note_clears_snapshot(self):
        pid = self._patient()
        nid = self._save_followup(pid).json()["id"]
        self.assertEqual(len(self.client.get(f"/api/patients/{pid}/notes").json()), 1)
        self.assertEqual(self.client.delete(f"/api/patients/{pid}/notes/{nid}").status_code, 204)
        self.assertIsNone(repository.get_carry_snapshot(pid))  # snapshot rebuilt -> cleared


if __name__ == "__main__":
    unittest.main()
