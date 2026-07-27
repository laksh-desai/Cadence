# Generation speed — diagnosis and tuning

Note generation on the target ThinkPad (i5-8365U, 4c/8t, **no GPU**, 16 GB RAM) takes a
few minutes per note. That is expected for a 4B model on CPU — but two things make it
*slower than it needs to be*, and both are fixable. This doc records the measured cause and
every lever, most-effective first.

## The real bottleneck: memory swapping, not CPU

Measured on the deployment machine (2026-07-27, mid-session with Chrome + VS Code open):

| | value |
|---|---|
| Physical RAM | 15.8 GB |
| **Commit charge** | **19.7 GB** — ~4 GB *over* physical → paging to disk |
| Free physical RAM | 2 GB |
| Generation rate (f16 KV cache) | **3.16 tok/s** |
| Generation rate (q8_0 KV cache + flash attn) | **~4.4–5.0 tok/s** |

A 4B-Q4 model on this CPU should do ~5–8 tok/s when it is **not** swapping. Sitting ~4 GB
over physical RAM, every layer touch can hit the pagefile, which is what drags it to ~3.
So the highest-value levers all reduce the memory footprint until the machine stops paging.

## Levers, most effective first

### 1. Free physical RAM during generation — biggest single win, no code
Chrome was using ~3 GB across processes and VS Code ~0.5 GB. Closing the browser (or
heavy tabs) and other apps *while a note generates* can move the machine from "swapping"
to "fits in RAM", which is worth more than any config flag. **Recommend to the clinician:
close other apps before hitting Generate.** (Cadence's own UI is one lightweight tab.)

### 2. Quantize the KV cache + flash attention — applied, measured ~40–55% faster
Ollama server environment variables (set at the User level; already applied on this
machine — restart Ollama after changing):

```
OLLAMA_FLASH_ATTENTION = 1
OLLAMA_KV_CACHE_TYPE   = q8_0
```

`q8_0` roughly halves the ~1 GB KV cache (at num_ctx 8192) with negligible quality loss;
flash attention speeds the attention math and cut prefill from ~8 to ~20–29 tok/s here.
`q4_0` would save more memory but is a bit more aggressive — `q8_0` is the conservative
choice for a clinical tool. To revert: clear both variables and restart Ollama.

Re-run `scripts/validate_quality.py` after changing the KV cache type to confirm note
quality is unaffected.

### 3. Keep the model resident (already done)
`keep_alive: 30m` in `app/generate/ollama_client.py` avoids the ~7–13 s cold reload of the
2.8 GB weights between notes. Confirmed: warm load dropped to 0.4 s. A server/Ollama restart
evicts it, so the first note after a restart pays the reload once.

### 4. Fewer tokens = less time (already done, keep tightening)
Generation time is ~linear in output tokens, so the conciseness rules
(`app/generate/rules.py` WRITING_RULES) and the transcript-artifact/filler preprocessing
(`clean_dictation`) directly cut time by shrinking both the prompt (prefill) and the note
(generation). A shorter, cleaner dictation and a terser template are genuine speedups, not
just style.

### 5. CPU-only, no iGPU offload (code, applied)
`num_gpu: 0` is now sent explicitly so Ollama never partially offloads to the Intel iGPU
(slower + wastes RAM on this box). `num_thread` is left to Ollama's physical-core detection;
generation here is memory-bandwidth bound, so forcing >4 threads does not help. Both are
overridable via `CADENCE_NUM_GPU` / `CADENCE_NUM_THREAD` for experimentation.

### 6. A smaller "fast draft" model — IMPLEMENTED (Quality / Fast draft toggle)
A 4B model is inherently minutes-per-note on CPU, so there is now a **model toggle** on the
Home dictate card:
- **Quality** — MedGemma 4B (medical-tuned), the default and the tier for any note the
  clinician signs.
- **Fast draft** — `gemma2:2b` (same Gemma family, general). Measured **~10.3 tok/s vs
  ~4.5 for the 4B ≈ 2.2× faster** (a note ~5 min → ~2–2.5 min). Not medical-tuned; it is an
  explicit first-pass scaffold the clinician edits (the "Ask for changes" box) or regenerates
  on Quality before signing. Every note is clinician-reviewed regardless.

Wiring: `ollama_client.model_for(fast)` (`MODEL` vs `FAST_MODEL`), a `fast` flag on the
generate/revise requests, and the toggle in `app/ui/static`. The fast model id is overridable
via `CADENCE_FAST_MODEL`, so a lower-quant MedGemma (Q3/Q2 — smaller, still medical-tuned,
faster on this memory-bound box) can be substituted later without a code change; requires
`ollama pull <that model>`.

## What is NOT worth doing
- **A bigger context window** to "go faster" — the opposite; a larger `num_ctx` grows the KV
  cache and prefill cost. 8192 is sized for a full Initial Eval; huge dictations are condensed
  by `app/generate/chunked.py` rather than given an ever-larger context.
- **More threads than physical cores** — memory-bandwidth bound; no gain, possible contention.
- **A lower `num_predict`** to cut time — it is a safety ceiling, not the actual length; the
  model already stops at its stop token well under it.
