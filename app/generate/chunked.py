"""Two-pass condensing for dictations too long to fit the model's context window (CLAUDE.md rule 16).

MEASURED THRESHOLD (2026-08, scripts/validate_longform.py). The budget is not the context window,
it is what is LEFT of it: `num_ctx 8192 - num_predict 3072 - the prompt scaffolding`. For the
Initial Evaluation that scaffolding is ~2,865 tokens, leaving ~2,255 tokens for the dictation —
about **1,350 words, or roughly a 10-minute dictation**. This docstring previously claimed "a
~20-minute dictation already fits", which was wrong by nearly 2x: a real 2,363-word intake measures
1.60x over budget. Condensing is therefore not the rare path it was described as — a full
long-form initial evaluation routinely takes it. The per-form numbers are printed by
`scripts/validate_longform.py --dry-run`; re-check them after any change to the rules or a template.

Ollama's failure mode without this is SILENT: it drops part of the transcript and cuts the note off
mid-sentence, while a 4B model's attention degrades over a very long context anyway, starving the
tail. So for an over-budget dictation we condense it first: split it into chunks,
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

import os
import re

from app.generate.ollama_client import NUM_CTX, NUM_PREDICT

# OFF BY DEFAULT as of 2026-08, because it was measured and it lost (CLAUDE.md rule 16).
#
# Two prompts were tried on a real 2,363-word intake, scored against a 78-fact hand-authored
# ledger, A/B'd against the truncation this feature replaces:
#
#   raw (truncate)                       59/78 facts, 15.3 min
#   condense, prose prompt               18/78 facts, 29.6 min  -- structure destroyed, writer
#                                                                  produced 5 sections not 18
#   condense, structure-keeping prompt   see the run log         -- structure kept, but it
#                                                                  FABRICATED
#
# The second attempt is the reason this is a flag and not a fix. Told to keep the therapist's own
# section labels, the model kept them and then rewrote the CONTENT under one: five specific
# dictated short-term goals ("ambulate three hundred feet with a rolling walker and supervision
# only", "improve Berg Balance Scale to forty five out of fifty six") came back as five generic
# ones ("Improve balance and reduce fall risk"). Every number gone, every goal invented.
#
# That failure is invisible to every guard Cadence has. `traceability` flags values in the NOTE
# that are absent from the DICTATION; here the note ends up with FEWER values, not invented ones,
# so nothing fires. It is rule 14's "arbitrary invented prose" class, introduced by a preprocessing
# step the clinician never sees, upstream of every check.
#
# Truncation is the better failure: it loses the tail VISIBLY (the caller flags it) and it cannot
# invent. So an over-budget dictation now takes the raw path plus a loud warning. Set
# CADENCE_CONDENSE_LONG_DICTATION=1 to re-enable condensing for an experiment; do not turn it on
# for real notes without re-running scripts/validate_longform.py and beating 59/78.
CONDENSE_ENABLED = os.environ.get("CADENCE_CONDENSE_LONG_DICTATION", "").strip() in ("1", "true", "yes")

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


# MEASURED, then rewritten (2026-08, scripts/validate_longform.py — see CLAUDE.md rule 16).
#
# The first version of this prompt ended "do NOT format it as a note — just clean sentences", and
# the A/B says that instruction was the whole problem. It did its stated job well: 73 of 78 ledger
# facts survived the condense pass (94%). But it turned a dictation the therapist had SIGNPOSTED
# out loud — "Medications." … "Cervical range of motion, active." … "Short term goals, four weeks."
# — into flowing narrative, and the note writer then produced 5 sections instead of 18 and scored
# 18/78 against the raw path's 59/78. The facts were all still there; the writer could no longer
# find them.
#
# So the condense pass must preserve STRUCTURE, not just content. A therapist dictating a long
# intake names their sections aloud, and those labels are the only map the 4B model has.
_CONDENSE_PROMPT = (
    "Below is ONE part of a longer physical-therapy dictation — a raw speech-to-text transcript. "
    "Rewrite it more concisely, in clean clinical English.\n\n"
    "KEEP THE STRUCTURE. The therapist says their section names out loud (\"Medications.\", "
    "\"Past medical history.\", \"Cervical range of motion, active.\", \"Short term goals, four "
    "weeks.\"). Keep every one of those labels, in the same order, each starting a new line. Do "
    "not merge sections together and do not reorder them.\n\n"
    "PRESERVE EVERY CLINICAL FACT exactly: every measurement, medication and dose, diagnosis, "
    "past-history item, goal, vital sign, assist level, distance, minutes, and plan value. Keep "
    "lists as lists — every medication, every goal, every measured value.\n\n"
    "Remove ONLY filler words, false starts, repetition, and conversational padding. Do not add "
    "anything. Do not write it as a finished note, and do not add headings the therapist did not "
    'say.\n\nPART:\n"""{chunk}"""'
)


async def fit_dictation(
    dictation: str,
    overhead_tokens: int,
    generate,
    *,
    num_ctx: int = NUM_CTX,
    num_predict: int = NUM_PREDICT,
    enabled: bool | None = None,
) -> tuple[str, bool, bool]:
    """Ensure the dictation fits the generation budget. Returns (text, was_condensed, still_over).

    `overhead_tokens` is the estimated size of the fixed prompt scaffolding (framing + template
    spec + rules + output format + any extra_info) — everything the prompt holds except the
    dictation. `generate` is an async `prompt -> text` function (the real Ollama call in
    production, a stub in tests).

    If the dictation already fits, it is returned unchanged with no model call (the normal path).

    If it does NOT fit and condensing is disabled (the default — see CONDENSE_ENABLED above), the
    dictation is returned unchanged with `still_over=True`, so the caller warns the clinician that
    the model may not have seen all of it. That is the whole contract: Cadence would rather lose
    the tail visibly than hand the note writer content a second model invented.

    With condensing enabled, each chunk is condensed via `generate` and the result is reported,
    along with whether it is STILL over budget afterwards.
    """
    budget = num_ctx - num_predict - overhead_tokens
    if budget <= 0:
        budget = num_ctx // 2  # pathological overhead; still give the dictation a real budget
    if estimate_tokens(dictation) <= budget:
        return dictation, False, False
    if not (CONDENSE_ENABLED if enabled is None else enabled):
        return dictation, False, True

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
