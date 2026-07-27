"""End-to-end smoke check for the REAL local models — run this on the provisioned machine.

The unit tests stub every model call, so a green test run does NOT prove the pipeline produces a
note on this hardware. This script drives the actual backends once, with FAKE data only (no PHI):

  * Transcription — loads MedASR and decodes a synthesized clip. Its real job is to prove the
    CTC decode path runs end to end without raising (the bug that made `.generate()` fail); a
    synthesized tone won't yield meaningful words, that's expected.
  * Generation — builds a real prompt for the Initial Evaluation and asks Ollama/MedGemma to
    fill it, confirming a non-empty note comes back.

Each component is checked independently, so a machine with only one set up still gets a useful
report. This is the concrete "Done when… a test dictation generates a note" step in
docs/go-live-checklist.md.

    .venv/Scripts/python.exe scripts/verify_pipeline.py
"""

from __future__ import annotations

import asyncio
import io
import math
import struct
import sys
import wave
from pathlib import Path

# Allow running as `python scripts/verify_pipeline.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _synth_wav(seconds=1.0, rate=16000, freq=220.0) -> bytes:
    """A short mono 16 kHz PCM tone — enough to exercise the decode path without a mic or fixture."""
    n = int(seconds * rate)
    frames = (int(0.2 * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *frames))
    return buf.getvalue()


def check_transcription() -> bool:
    print("\n[1/2] Transcription (MedASR, local, CPU)")
    try:
        from app.transcribe import medasr_client
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL — could not import the transcription client: {e}")
        return False
    try:
        medasr_client.load_model()
    except medasr_client.TranscriptionUnavailableError as e:
        print(f"  SKIP — MedASR is not set up yet: {e}")
        print("         (see docs/medasr-setup.md — the rest of the app still works without it)")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL — MedASR failed to load: {e}")
        return False
    try:
        text = medasr_client.transcribe(_synth_wav())
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL — decode raised (this is the CTC-decode bug if it says 'generate'): {e}")
        return False
    if not isinstance(text, str):
        print(f"  FAIL — transcribe() returned {type(text).__name__}, expected str")
        return False
    print(f"  PASS — model loaded and the CTC decode ran end to end (returned {len(text)} chars).")
    print(f"         transcript of the synthetic tone: {text!r} (gibberish is expected here)")
    return True


def check_generation() -> bool:
    print("\n[2/2] Note generation (Ollama / MedGemma, local, CPU)")
    try:
        from app.generate import cpt, postprocess, traceability
        from app.generate.forms import FORMS, FORM_ORDER
        from app.generate.ollama_client import OllamaUnavailableError, generate_note, is_reachable
        from app.generate.parser import parse_plain
        from app.generate.prompt import PatientContext, build_prompt, render_prior_block
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL — could not import the generation pipeline: {e}")
        return False

    if not asyncio.run(is_reachable()):
        print("  SKIP — Ollama isn't reachable on localhost:11434. Start it and pull MedGemma 4B")
        print("         (williamljx/medgemma-4b-it-Q4_K_M-GGUF), then re-run.")
        return False

    form = FORMS[FORM_ORDER[0]]  # the Initial Evaluation
    ctx = PatientContext(name="Test Patient (fake)", sub="fake demo record — no PHI")
    dictation = (
        "Initial evaluation, left knee, three weeks after a total knee replacement. "
        "Left knee active range five to ninety degrees, quad strength three plus out of five. "
        "Walks one hundred feet with a front wheeled walker, contact guard assist. "
        "Pain four out of ten. Plan is therapy twice a week for six weeks."
    )
    prompt = build_prompt(form, ctx, dictation, render_prior_block(form, None, False), None)
    print(f"  running a real generation for \"{form.name}\" — this can take 1-2 minutes on CPU…")
    try:
        text = asyncio.run(generate_note(prompt))
    except OllamaUnavailableError as e:
        print(f"  FAIL — {e}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL — generation raised: {e}")
        return False
    if not (text and text.strip()):
        print("  FAIL — the model returned an empty note.")
        return False

    # Run the same post-generation pipeline as /api/generate so the printed note matches what the
    # app actually produces (raw model output over-tags [[CARRIED FORWARD]] etc.; postprocess fixes it).
    parsed = parse_plain(text)
    if not parsed:
        print(f"  PASS — model returned a {len(text)}-char note, but it didn't parse into sections")
        print("         (unusual formatting — the app would show it as raw text). Raw first lines:")
        for line in text.strip().splitlines()[:6]:
            print(f"         | {line}")
        return True
    sections = postprocess.apply(form.id, parsed["sections"])
    sections = traceability.add_verification_flags(sections, dictation)
    sections, _ = cpt.suggest_codes(sections, form.id)
    print(f"  PASS — got a {len(text)}-char note; {len(sections)} sections after the full pipeline:")
    for s in sections[:10]:
        cf = "  [carried forward]" if s.get("carried_forward") else ""
        print(f"         | ## {s['heading']}{cf}")
    return True


def main() -> int:
    print("Cadence local-pipeline smoke check (fake data only — no PHI leaves this machine).")
    t_ok = check_transcription()
    g_ok = check_generation()
    print("\nSummary:")
    print(f"  Transcription (MedASR):        {'PASS' if t_ok else 'not verified'}")
    print(f"  Note generation (MedGemma):    {'PASS' if g_ok else 'not verified'}")
    if t_ok and g_ok:
        print("\nBoth local models are working end to end. 🎉")
        return 0
    print("\nAt least one component isn't verified yet — see the messages above. This is expected")
    print("until the models are installed (docs/go-live-checklist.md steps 1-2).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
