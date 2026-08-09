"""Local Ollama call, ported from test_medgemma.py's validated request shape."""

import json
import os

import httpx

# Quality tier: the medical-tuned 4B used for every note the clinician signs.
# Env-overridable so a fine-tuned build can be A/B'd against the base with no code edit and no
# rebuild — `set CADENCE_MODEL=cadence-medgemma:v1` then re-run the sweep. This and `model_for()`
# below are the ONLY places a quality-tier model name is chosen; every path (generate, stream,
# revise, the eval runner, and chunked's condense callback) routes through them.
# See docs/finetune-when-viable.md.
MODEL = os.environ.get("CADENCE_MODEL", "williamljx/medgemma-4b-it-Q4_K_M-GGUF")
# Fast-draft tier: a much smaller general model for a quick first pass the clinician then edits
# (or re-runs on the quality model before signing). Same Gemma family, ~2B params, so ~2-4x faster
# on this CPU-only box. Deliberately NOT the default -- it is not medical-tuned; every note is
# clinician-reviewed regardless, and the fast draft is explicitly a scaffold, not the final record.
# Overridable so a lower-quant MedGemma could be swapped in later without a code change.
FAST_MODEL = os.environ.get("CADENCE_FAST_MODEL", "gemma2:2b")
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def model_for(fast: bool) -> str:
    return FAST_MODEL if fast else MODEL

# Context window. A long (e.g. 20-minute) dictation plus the full note template and
# the generation rules easily exceeded the old 4096 ceiling, so Ollama silently
# dropped the tail of the transcript AND cut the note off mid-sentence (observed: a
# note ending on the dangling fragment "Certification period"). 8192 gives comfortable
# headroom for a full Initial Evaluation prompt+output on the target 16 GB machine
# (the KV cache is only ~1 GB and Ollama runs in its own process). If a genuinely
# huge dictation ever overflows this too, the fix is chunked/two-pass generation, not
# a bigger single context — a 4B model's attention over a very long context degrades.
NUM_CTX = 8192
# Explicit output ceiling so the note is never cut short by an implicit default, and
# never runs away in a repeat loop. ~3072 tokens is far more than any single note
# needs while still leaving room inside NUM_CTX after the prompt.
NUM_PREDICT = 3072
# Keep the model resident between notes so the 2nd..Nth generation in a clinic session doesn't pay
# the cold-load penalty. Ollama unloads an idle model after ~5 minutes by default; reloading the
# ~2.5 GB MedGemma weights from disk adds tens of seconds and was the most common cause of a slow or
# seemingly-failed FIRST attempt (the app then shows "the models might be slow sometimes"). 30
# minutes comfortably covers gaps between patients while still freeing RAM when a session ends.
KEEP_ALIVE = os.environ.get("CADENCE_KEEP_ALIVE", "30m")

# CPU-only inference on the target hardware (i5-8365U, no dedicated GPU). Sending num_gpu=0
# explicitly keeps Ollama from probing/partially offloading to the Intel iGPU, which on this box is
# slower and wastes memory. num_thread is left to Ollama's own physical-core detection unless
# overridden (CADENCE_NUM_THREAD); on a 4-core/8-thread CPU, generation is memory-bandwidth bound, so
# forcing more threads than physical cores does not help and can hurt.
#
# The single biggest speed lever here is NOT in this payload — it is freeing physical RAM so Ollama
# stops swapping (measured: ~3.2 tok/s while ~4 GB into swap vs ~5 tok/s after freeing the KV cache),
# plus the Ollama-server env flags OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0 (halve the
# KV cache, speed attention). See docs/performance-tuning.md.
NUM_GPU = int(os.environ.get("CADENCE_NUM_GPU", "0"))
_NUM_THREAD = os.environ.get("CADENCE_NUM_THREAD")  # None -> let Ollama decide


class OllamaUnavailableError(Exception):
    pass


def _build_payload(prompt: str, model: str | None = None) -> dict:
    options = {
        "temperature": 0.3,
        "num_ctx": NUM_CTX,
        "num_predict": NUM_PREDICT,
        "num_gpu": NUM_GPU,
    }
    if _NUM_THREAD:
        options["num_thread"] = int(_NUM_THREAD)
    return {
        "model": model or MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": options,
    }


async def generate_note(prompt: str, timeout_s: float = 1800.0, model: str | None = None) -> str:
    # 30-minute ceiling. Measured on a RAM-starved CPU box (swapping): ~3.4 tok/s, and a long
    # Initial Eval is a ~5000-token prompt + ~2500-token output = ~15-20 min of pure generation.
    # A shorter timeout aborts a note that IS still generating and throws the result away (the exact
    # "couldn't reach the model" failure on a 20-minute run). Real fixes for the SLOWNESS are freeing
    # RAM and/or token streaming; this just stops a working generation from being discarded.
    payload = _build_payload(prompt, model)
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(OLLAMA_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise OllamaUnavailableError(
            "Could not reach the local model. Is Ollama running?"
        ) from e
    return data.get("message", {}).get("content", "")


async def stream_note(prompt: str, timeout_s: float = 1800.0, model: str | None = None):
    """Async-generator variant of generate_note: yields the model's output token chunk-by-chunk as
    Ollama produces it (stream=true, newline-delimited JSON). Same payload / keep_alive / timeout and
    the same OllamaUnavailableError on a transport failure — the caller streams these to the browser
    so a long note is watched live and never lost to a timeout, instead of one blocking wait.
    """
    payload = _build_payload(prompt, model)
    payload["stream"] = True
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            async with client.stream("POST", OLLAMA_URL, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # skip a partial/garbled line rather than abort the whole note
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        return
    except httpx.HTTPError as e:
        raise OllamaUnavailableError(
            "Could not reach the local model. Is Ollama running?"
        ) from e


async def is_reachable() -> bool:
    """Lightweight health check for the Status page -- does not load/run the
    model, just confirms Ollama's API is up."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(OLLAMA_TAGS_URL)
            resp.raise_for_status()
        return True
    except httpx.HTTPError:
        return False
