"""Input-guard tests for POST /api/transcribe (app/ui/server.py).

Covers the request-validation paths that don't need the actual MedASR model: model-not-ready
degrades to 503, empty audio is 400, and an over-size upload is rejected (413) before it can be
buffered into memory. The size limit is monkeypatched down so no giant payload is needed. The
TestClient is not used as a context manager, so the app lifespan (which would load MedASR) never
runs — app.state is set by hand instead.

    .venv/Scripts/python.exe -m unittest tests.test_transcribe_guard -v
"""

import unittest

from fastapi.testclient import TestClient

from app.ui import server


class TranscribeGuardTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server.app.state.medasr_ready = True
        server.app.state.medasr_error = None
        self._orig_max = server.MAX_AUDIO_BYTES

    def tearDown(self):
        server.MAX_AUDIO_BYTES = self._orig_max

    def _post(self, content):
        return self.client.post("/api/transcribe", files={"audio": ("clip.wav", content, "audio/wav")})

    def test_empty_audio_is_400(self):
        self.assertEqual(self._post(b"").status_code, 400)

    def test_oversize_audio_is_413(self):
        server.MAX_AUDIO_BYTES = 10
        self.assertEqual(self._post(b"x" * 50).status_code, 413)

    def test_medasr_not_ready_is_503(self):
        server.app.state.medasr_ready = False
        self.assertEqual(self._post(b"x" * 5).status_code, 503)


if __name__ == "__main__":
    unittest.main()
