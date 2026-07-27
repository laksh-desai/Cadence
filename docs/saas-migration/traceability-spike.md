# Traceability / verification layer — feasibility spike

The single highest-value unmet feature in both competitor markets (product-strategy.md, item 13,
and the mental-health "hallucination accountability" gap): **every claim in a generated note is
traceable to what the clinician actually said**, with low-confidence segments flagged and — the
demo feature — click-a-note-sentence-to-hear-the-source-audio. In PT it's worth even more than in
mental health, because a hallucinated *number* (ROM, MMT, minutes) is a **billing-fraud** risk,
not just a quality issue.

## The feature decomposes into two independent mappings

1. **Word → audio timestamp** (comes from the ASR). *Feasible on every candidate backend:*
   - **Current MedASR (Conformer-CTC):** CTC is frame-aligned — each output token maps to specific
     input frames — so per-word start/end times come from the per-frame logits via CTC forced
     alignment. Caveat to verify in code: the model card drives MedASR through `_model.generate()`
     + `batch_decode` (`app/transcribe/medasr_client.py`), which hides the frame logits. Getting
     timestamps means also exposing the `logits` path (`_model(**inputs).logits` → argmax →
     collapse blanks/repeats → frame→time), and confirming the frame stride. This is an additive
     change to the transcribe layer, not a rewrite.
   - **WebGPU/wasm Whisper (hybrid-tier option):** `word_timestamps=True` (cross-attention
     alignment) gives word timing natively.
   - **AWS Transcribe Medical (cloud fallback):** returns per-word `start_time`/`end_time` **and a
     confidence score** in its JSON — the richest source, zero extra work.

2. **Note claim → transcript span** (the novel, model-agnostic part — nobody ships this). The LLM
   rewrites/normalizes the transcript, so this mapping is *not* given by the ASR. **This spike built
   and tested it** for the fraud-risk subset (clinical values).

## What this spike built (and proved)

`app/generate/traceability.py` + `tests/test_traceability.py` (13 tests, all passing):

- `normalize_for_matching()` — canonicalizes spoken and written forms to one comparable digit form
  so the normalized note ("3+/5", "4/10", "15 minutes") can be compared against the spoken
  transcript ("three plus out of five", "four out of ten", "fifteen minutes"). Bounded to 0–99.
- `anchor_note_to_transcript()` / `unanchored_values()` — for each clinical value in the note
  (MMT, pain, minutes, degrees), decides ANCHORED (present in the transcript) vs **UNANCHORED
  (probable fabrication → flag for review).**

**Proof it works on real output:** fed the actual note MedGemma produced in the model-seam smoke
test — where the model invented `120 degrees`, `110 degrees`, `60 degrees`, `4/5`, and a `30
minutes` endurance that were never dictated — the anchorer flagged **exactly those five** as
unanchored and left the real `4/10` alone. That is the verification layer catching genuine
hallucinated numbers, deterministically, with no model cooperation required.

## Deferred (needs the ASR half) and known limits

- **Timestamp join:** turning an ANCHORED value into an audio time is a later step — map the
  transcript char offset → word index → the ASR's word timestamp. Trivial once (1) above emits word
  timings; not built here because the current path returns only a bare string.
- **Offset preservation:** matching happens on the *normalized* transcript; mapping back to the
  original transcript's exact character offsets (for highlight ranges) needs a normalized→original
  token map. Straightforward, deferred.
- **Scope:** covers numeric clinical values (the fraud-risk set), not arbitrary prose claims. Prose
  provenance ("patient reports difficulty on stairs" → which transcript span) is a harder,
  fuzzier/semantic-match problem — a later phase; numbers are where the money and the risk are.
- **Spoken hundreds:** ROM ≥ 100° spoken as "one hundred twenty" isn't normalized yet (digit form
  "120 degrees" works). Extend the number parser when needed.

## Recommended build order for the full feature

1. **Ship value-anchoring now (no ASR change): DONE.** `traceability.flag_unanchored_in_sections()`
   runs in `/api/generate` (`app/ui/server.py`) after postprocess and appends an amber
   `[[NEEDS: "X" not found in dictation — verify or remove]]` marker to any section stating an
   unanchored clinical value. Backend-independent (identical on Ollama and Bedrock). Hardened for
   spoken hundreds so real ROM ≥100° isn't false-flagged. 21 traceability tests. **Known false-
   positive vectors** (hedged by the "verify" wording, safe because the clinician signs every note):
   a value the clinician stated in a phrasing the normalizer doesn't cover (e.g. pain said as bare
   "pain of four" without "out of ten"), or value types outside the ROM/MMT/pain/minutes set.
2. **Add word timestamps to the transcribe layer** (CTC logits path on MedASR, or word timing from
   whichever backend the hybrid uses). Store them alongside `dictation_raw`.
3. **Join anchors → timestamps** and add the click-to-hear-source UI + low-confidence highlighting.
4. **Later:** extend from numeric values to prose-claim provenance via semantic matching.
