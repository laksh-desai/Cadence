"""Locks the MedASR CTC decode path (app/transcribe/medasr_client.transcribe).

MedASR is a Conformer-CTC model loaded via AutoModelForCTC: it emits per-frame logits and is
decoded by argmax + the processor's CTC-collapsing batch_decode. A CTC model has no autoregressive
`.generate()` — an earlier version called it, which raises and meant transcription never actually
worked. This exercises the real transcribe() body with a fake CTC model whose `.generate()` fails
loudly, so a regression back to that mistake is caught. No real model, no network, no gated HF
download — just a tiny in-memory WAV so the real librosa decode path still runs.

    .venv/Scripts/python.exe -m unittest tests.test_transcribe_decode -v
"""

import io
import struct
import unittest
import wave
from types import SimpleNamespace

import torch

from app.transcribe import medasr_client as m


def _tiny_wav(seconds=0.1, rate=16000):
    """A valid, tiny 16 kHz mono PCM WAV (silence) so librosa.load succeeds without a fixture file."""
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
    return buf.getvalue()


class _FakeCTCModel:
    """Stands in for AutoModelForCTC: a forward call returns an object with `.logits`; `.generate`
    exists only to fail the test loudly if the decode path ever calls it again."""

    def __init__(self, logits):
        self._logits = logits
        self.forward_calls = 0

    def __call__(self, **inputs):
        self.forward_calls += 1
        return SimpleNamespace(logits=self._logits)

    def generate(self, **inputs):  # pragma: no cover - must never run
        raise AssertionError("transcribe() must argmax CTC logits, not call model.generate()")


class _FakeProcessor:
    def __init__(self, text):
        self.text = text
        self.decoded_ids = None
        self.decode_kwargs = None

    def __call__(self, *args, **kwargs):
        return {"input_values": torch.zeros(1, 16000)}

    def batch_decode(self, predicted_ids, **kwargs):
        self.decoded_ids = predicted_ids
        self.decode_kwargs = kwargs
        return [self.text]


class TranscribeDecodeTests(unittest.TestCase):
    def setUp(self):
        self._orig_model, self._orig_proc = m._model, m._processor
        # (1, time=4, vocab=5) logits; argmax over the last dim gives the per-frame ids.
        self.model = _FakeCTCModel(torch.tensor([[[0.1, 0.9, 0.0, 0.0, 0.0],
                                                  [0.8, 0.1, 0.0, 0.0, 0.1],
                                                  [0.0, 0.0, 0.7, 0.3, 0.0],
                                                  [0.2, 0.2, 0.2, 0.2, 0.9]]]))
        self.proc = _FakeProcessor("left knee flexion improved")
        m._model, m._processor = self.model, self.proc

    def tearDown(self):
        m._model, m._processor = self._orig_model, self._orig_proc

    def test_transcribe_uses_forward_and_argmax(self):
        text = m.transcribe(_tiny_wav())
        self.assertEqual(text, "left knee flexion improved")
        self.assertEqual(self.model.forward_calls, 1)  # forward pass, not generate
        # The processor was handed argmax(logits) over the vocab dim: shape (batch, time).
        self.assertEqual(tuple(self.proc.decoded_ids.shape), (1, 4))
        self.assertTrue(torch.equal(self.proc.decoded_ids, torch.tensor([[1, 0, 2, 4]])))
        # Special tokens must be suppressed at decode time (a real E2E run leaked "</s>").
        self.assertTrue(self.proc.decode_kwargs.get("skip_special_tokens"))

    def test_leaked_special_tokens_are_stripped(self):
        # Even if a tokenizer ignores skip_special_tokens, literal markup never reaches the box.
        self.proc.text = "walked 200 feet with a walker.</s>"
        self.assertEqual(m.transcribe(_tiny_wav()), "walked 200 feet with a walker.")

    def test_empty_recording_raises_audio_unreadable(self):
        # A valid WAV header with no frames -> librosa returns an empty array.
        with self.assertRaises(m.AudioUnreadableError):
            m.transcribe(_tiny_wav(seconds=0))

    def test_unreadable_bytes_raise_audio_unreadable(self):
        with self.assertRaises(m.AudioUnreadableError):
            m.transcribe(b"not a wav file at all")

    def test_model_not_loaded_raises_unavailable(self):
        m._model = None
        with self.assertRaises(m.TranscriptionUnavailableError):
            m.transcribe(_tiny_wav())


if __name__ == "__main__":
    unittest.main()
