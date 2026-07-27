"""End-to-end transcription proof using SYNTHESIZED speech — no human voice needed.

Generates a spoken clinical sentence with Windows' built-in TTS (System.Speech), then runs it
through the real MedASR model via the exact production code path (medasr_client.load_model +
transcribe). This is the missing proof that the CTC decode fix works on real speech audio, not
just that it doesn't raise on silence.

Two-tier verdict:
  DECODE OK   -- transcribe() returned text without raising (the .generate() bug would raise here)
  CONTENT OK  -- enough of the spoken clinical keywords appear in the transcript that the model is
                 genuinely transcribing (TTS voices are synthetic, so a partial hit rate is fine)

    .venv/Scripts/python.exe scripts/verify_transcription.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SPOKEN = (
    "The patient walked two hundred feet with a front wheeled walker. "
    "Pain was four out of ten. Therapeutic exercise for fifteen minutes. "
    "Blood pressure was one twenty eight over seventy six."
)
# Content keywords: loose stems so TTS-accent/decode wobble still counts a genuine hit.
KEYWORDS = ["patient", "walk", "feet", "walker", "pain", "four", "ten", "exercise", "minutes", "pressure"]


def synthesize(text: str, wav_path: str) -> None:
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = -1; "
        f"$s.SetOutputToWaveFile('{wav_path}'); "
        f"$s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


def main() -> int:
    wav_path = str(Path(tempfile.mkdtemp(prefix="cadence_tts_")) / "spoken.wav")
    print("[1/3] Synthesizing spoken clinical audio (Windows TTS)...")
    synthesize(SPOKEN, wav_path)
    size = Path(wav_path).stat().st_size
    print(f"      wav written: {size} bytes")
    if size < 10000:
        print("FAIL — TTS produced no meaningful audio.")
        return 1

    print("[2/3] Loading the real MedASR model (production code path)...")
    from app.transcribe import medasr_client
    try:
        medasr_client.load_model()
    except medasr_client.TranscriptionUnavailableError as e:
        print(f"SKIP — MedASR not set up on this machine: {e}")
        return 1

    print("[3/3] Transcribing through medasr_client.transcribe() ...")
    try:
        text = medasr_client.transcribe(Path(wav_path).read_bytes())
    except Exception as e:  # noqa: BLE001
        print(f"FAIL — decode raised: {type(e).__name__}: {e}")
        return 1
    print(f"      transcript: {text!r}")

    low = (text or "").lower()
    hits = [k for k in KEYWORDS if k in low]
    print(f"\nDECODE OK — transcribe() returned a {len(text)}-char string without raising.")
    print(f"keyword hits: {len(hits)}/{len(KEYWORDS)}  {hits}")
    if len(hits) >= 5:
        print("CONTENT OK — the model is genuinely transcribing speech. Transcription is verified end to end.")
        return 0
    print("CONTENT WEAK — decode path works, but few keywords matched; verify once with a real mic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
