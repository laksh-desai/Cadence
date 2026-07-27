"""Local MedASR (CTC) transcription. Loaded once at process startup (see
app/ui/server.py's lifespan) and reused for every request -- mirrors
app/generate/forms.py's FORMS module-level-singleton pattern, except this
singleton is populated explicitly from the lifespan (not at import time) since
loading involves network access (first run) and meaningful CPU time every run,
neither of which should happen as a side effect of `import app.transcribe...`.
"""

import io
import logging
import re

import torch
from transformers import AutoModelForCTC, AutoProcessor

from app.transcribe.hf_config import load_hf_token

logger = logging.getLogger(__name__)

MODEL_ID = "google/medasr"

_processor = None
_model = None


class TranscriptionUnavailableError(Exception):
    """Model isn't loaded -- never downloaded, HF auth missing/rejected, or any
    other load-time failure. Caught in server.py and turned into a clean HTTP
    error, same pattern as app.generate.ollama_client.OllamaUnavailableError."""


class AudioUnreadableError(Exception):
    """The uploaded audio couldn't be decoded (corrupt, empty, wrong format)."""


def load_model() -> None:
    """Call once, at FastAPI startup. Raises TranscriptionUnavailableError with
    an actionable message on any failure (gated-model auth missing/rejected, no
    network on first run, etc.) -- the caller decides whether that's fatal; the
    rest of Cadence must keep working even if MedASR setup isn't done yet.
    """
    global _processor, _model
    token = load_hf_token()
    try:
        _processor = AutoProcessor.from_pretrained(MODEL_ID, token=token)
        _model = AutoModelForCTC.from_pretrained(MODEL_ID, token=token).to("cpu")
        _model.eval()
        _warmup()
    except Exception as e:
        _processor = None
        _model = None
        raise TranscriptionUnavailableError(_explain(e, token)) from e


def _warmup() -> None:
    """Absorb the first-call JIT/kernel-selection cost here, at startup, not on
    the clinician's first real dictation."""
    import numpy as np

    silence = np.zeros(16000, dtype=np.float32)  # 1s of silence at 16kHz
    inputs = _processor(silence, sampling_rate=16000, return_tensors="pt", padding=True)
    with torch.no_grad():
        _model(**inputs)  # a plain forward pass — CTC has no autoregressive generate step


def _explain(e: Exception, token: str | None) -> str:
    msg = str(e)
    if "gated" in msg.lower() or "403" in msg or "401" in msg:
        if not token:
            return (
                "MedASR couldn't load: no Hugging Face token configured. "
                "See docs/medasr-setup.md to set one up (one-time)."
            )
        return (
            "MedASR couldn't load: Hugging Face rejected the token, or the "
            "model's usage terms haven't been accepted yet on huggingface.co. "
            "See docs/medasr-setup.md."
        )
    return f"MedASR couldn't load: {msg}"


def is_loaded() -> bool:
    return _model is not None


def transcribe(wav_bytes: bytes) -> str:
    """Blocking, CPU-bound -- callers MUST run this via asyncio.to_thread, same
    treatment as app.integrations.sheets_sync.run_sync_cycle.
    """
    if _model is None:
        raise TranscriptionUnavailableError("MedASR is not loaded.")

    import librosa

    try:
        speech, _ = librosa.load(io.BytesIO(wav_bytes), sr=16000, mono=True)
    except Exception as e:
        raise AudioUnreadableError("Couldn't read the recorded audio.") from e
    if speech.size == 0:
        raise AudioUnreadableError("The recording was empty.")

    # MedASR is a Conformer-CTC model (AutoModelForCTC): it emits per-frame logits, not an
    # autoregressive sequence, so it is decoded by argmax over the vocab then CTC-collapsed by the
    # processor's batch_decode. It has no `.generate()` — calling one would raise.
    inputs = _processor(speech, sampling_rate=16000, return_tensors="pt", padding=True)
    with torch.no_grad():
        logits = _model(**inputs).logits
    predicted_ids = torch.argmax(logits, dim=-1)
    text = _processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
    # Belt-and-suspenders: a real E2E run leaked a literal "</s>" into the transcript before
    # skip_special_tokens was passed; strip any stray special-token markup so it can never land in
    # the clinician's dictation box even if a tokenizer ignores the flag.
    return re.sub(r"</?s>|<pad>|<unk>", "", text).strip()
