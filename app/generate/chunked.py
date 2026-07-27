"""Two-pass condensing for dictations too long to fit the model's context window (CLAUDE.md rule 16).

A ~20-minute dictation already fits `num_ctx=8192`, but a genuinely huge one (30-40+ minutes) would
overflow — and Ollama's failure mode is SILENT: it drops the tail of the transcript and cuts the
note off mid-sentence, while a 4B model's attention degrades over a very long context anyway,
starving the tail. So for an over-budget dictation we condense it first: split it into chunks,
have the model rewrite each chunk into clean clinical prose that preserves EVERY stated fact (a far
simpler task than writing the whole note, done with good attention over a small chunk), then feed
the concatenated result to the normal generation pipeline.

Conservative by construction:
  * Condensing only runs when the dictation would actually overflow, so a normal-length dictation
    takes the EXACT same path as before (`fit_dictation` returns it unchanged, no extra model call).
  * Even an imperfect condense beats the current silent-truncation outcome, which loses the tail
    entirely — and the caller always surfaces a visible "verify completeness" flag when condensing
    happened, turning a silent failure into one the clinician sees.
  * The raw dictation is unaffected on disk; only the text fed to *this* generation is condensed.

Caveat (per rules 14/15): the condense pass is itself a 4B-model call and could drop a fact, so it
does not eliminate risk — the visible warning + clinician review are the backstop. Verify behaviour
on a genuinely huge real dictation before relying on it.
"""

from __future__ import annotations

import re

from app.generate.ollama_client import NUM_CTX, NUM_PREDICT

# chars-per-token heuristic, biased to slightly OVER-estimate so we'd rather condense a borderline
# dictation than let the model silently truncate its tail.
_CHARS_PER_TOKEN = 4
# Per-chunk size for the map pass: small enough that the model has good attention over each chunk
# and the condensed output comfortably fits NUM_PREDICT.
_MAX_CHUNK_TOKENS = 2600


def estimate_tokens(text: str) -> int:
    return len(text or "") // _CHARS_PER_TOKEN


def split_into_chunks(text: str, max_chunk_tokens: int = _MAX_CHUNK_TOKENS) -> list[str]:
    """Split at sentence boundaries into chunks each <= max_chunk_tokens (best-effort: a single
    sentence longer than the limit is kept whole rather than cut mid-clause)."""
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    chunks: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for s in sentences:
        if not s:
            continue
        st = estimate_tokens(s)
        if cur and cur_tok + st > max_chunk_tokens:
            chunks.append(" ".join(cur))
            cur, cur_tok = [], 0
        cur.append(s)
        cur_tok += st
    if cur:
        chunks.append(" ".join(cur))
    return chunks


_CONDENSE_PROMPT = (
    "Below is ONE part of a longer physical-therapy dictation — a raw speech-to-text transcript. "
    "Rewrite it as clean, connected clinical prose. PRESERVE EVERY clinical fact exactly: every "
    "measurement, medication and dose, diagnosis, past-history item, goal, vital sign, assist "
    "level, distance, minutes, and plan value. Do NOT drop or summarize away any fact, do NOT add "
    "anything, and do NOT format it as a note — just clean sentences. Remove only filler words and "
    'repetition.\n\nPART:\n"""{chunk}"""'
)


async def fit_dictation(
    dictation: str,
    overhead_tokens: int,
    generate,
    *,
    num_ctx: int = NUM_CTX,
    num_predict: int = NUM_PREDICT,
) -> tuple[str, bool, bool]:
    """Ensure the dictation fits the generation budget. Returns (text, was_condensed, still_over).

    `overhead_tokens` is the estimated size of the fixed prompt scaffolding (framing + template
    spec + rules + output format + any extra_info) — everything the prompt holds except the
    dictation. `generate` is an async `prompt -> text` function (the real Ollama call in
    production, a stub in tests).

    If the dictation already fits, it is returned unchanged with no model call (the normal path).
    Otherwise each chunk is condensed via `generate` and the result is reported, along with whether
    it is STILL over budget after condensing (so the caller can warn accordingly).
    """
    budget = num_ctx - num_predict - overhead_tokens
    if budget <= 0:
        budget = num_ctx // 2  # pathological overhead; still give the dictation a real budget
    if estimate_tokens(dictation) <= budget:
        return dictation, False, False

    parts: list[str] = []
    for chunk in split_into_chunks(dictation):
        parts.append((await generate(_CONDENSE_PROMPT.format(chunk=chunk))).strip())
    condensed = "\n\n".join(p for p in parts if p)
    if not condensed:
        # Condensing produced nothing (the model returned empty for every chunk). Never generate
        # from an empty dictation — fall back to the raw one (the model handles the overflow as it
        # did before this feature) and still flag it as over-budget so the clinician is warned.
        return dictation, True, True
    return condensed, True, estimate_tokens(condensed) > budget
