# Fine-tuning the note-writer — the recipe, and why it is not yet time

**Status: NOT YET.** This document exists so the decision is written down rather than
re-litigated, and so the corpus that would make it possible accrues in the meantime.

---

## The constraint that makes this unusual — read this first

There is **no GPU**. The dev box runs `torch 2.12.1+cpu`; the target machine is a Lenovo ThinkPad
i5-8365U with Intel UHD 620 (see CLAUDE.md → Target hardware). A 4B QLoRA needs roughly 10–16 GB
of VRAM. It runs on neither.

Training is therefore **necessarily off-device**. Off-device means a third party that is not
Google Workspace — and the CLAUDE.md non-negotiable forbids PHI from touching any such party.

> **Therefore the only trainable corpus Cadence can ever have is
> `(synthetic dictation → clinician-corrected note)`.**
>
> Real clinician-corrected notes can inform prompt rules, deterministic backstops, and
> measurement. They can **never** be training data. This does not change if the corpus gets large,
> if the results look promising, or if a deadline gets tight — it is a property of where the
> compute lives, not a policy that can be traded off.

This is CLAUDE.md **rule 22**. The captured corrections in the `notes` table are real patient
content; `tests/test_correction_capture.py::PhiBoundaryTests` enforces that no export path exists,
and the `synthetic INTEGER NOT NULL DEFAULT 0` column means that if one is ever built it must
filter `WHERE synthetic = 1` at the SQL level rather than relying on someone remembering which
patient was fake.

---

## The three preconditions

1. **The format-compliance failure class is measurably fixed by deterministic repair.**
   Largely done: `postprocess.split_folded_headings` repairs the folded-heading failure that
   motivated this whole question. Confirm on a real sweep that "content in bodies, not headings"
   and "every section has a non-empty body" hold, and watch `folded_headings_raw` — the count of
   how often the MODEL folds, measured before the repair — to see whether the underlying behaviour
   is getting worse.
2. **A corpus exists.** Realistically 200–500 clinician-corrected pairs before a 4B LoRA is worth
   the setup cost. `app/storage/schema.sql`'s correction-capture columns accrue these as a
   by-product of normal use; before they existed, every correction was destroyed on edit.
3. **Clinician time exists.** Currently the binding constraint.

Only (1) is in reach today.

---

## Do not shortcut with deterministically-rendered targets

The tempting move is a template filler that renders the "correct" note from a synthetic sample's
own gold labels, producing thousands of free pairs with no clinician involved. Don't. Two
independent reasons:

- **It teaches templated prose.** Rule 9 requires unique, non-boilerplate wording every session,
  precisely so insurance submissions don't look templated. A model trained on a renderer's output
  learns the renderer's sentence skeletons and emits them every visit — defeating the product's
  stated purpose.
- **It is circular in exactly the way rule 21 warns about.** The generator (`evals/synth/`) and
  the target renderer would share an author, so the model would learn the renderer, and the
  synthetic half of the eval — authored in the same place — would score it highly. Rule 21(c)'s
  "synthetic scoring HIGHER is the circularity failure" would fire, and only the hand-written
  control set would be telling the truth.

There is no way to buy out of clinician time here. That is why this is deferred rather than done.

---

## The cheapest form of clinician time

Do **not** ask the clinician to author target notes. Ask them to **correct a Cadence draft of a
synthetic dictation**, in the review UI they already use — minutes per note.

1. Generate a synthetic corpus (`scripts/gen_synthetic.py`) for the regions the practice sees.
2. Create a throwaway synthetic-patient roster and run the dictations through the app normally.
3. The clinician reviews and corrects in the existing Edit / "Ask for changes" step.
4. The `(original_sections, final_sections)` pair the capture columns record **is** the training
   row — and because the patient is synthetic, it is the one class of captured correction that may
   legally leave the device. Mark those notes `synthetic = 1`.

---

## Mechanics, when the preconditions hold

- QLoRA (4-bit NF4) on `google/medgemma-4b-it` via `peft` + `transformers` + `bitsandbytes`, on a
  rented single 24 GB GPU (L4 / A10G / 3090-class). 1–3 epochs over a few hundred pairs. Loss on
  the completion only.
- **The training prompt must be the byte-identical production prompt** — the output of
  `build_prompt(form, ctx, dictation, prior_block, extra)`. Train on anything else and you have
  tuned for a prompt you do not ship.
- Merge the adapter → `llama.cpp/convert_hf_to_gguf.py` → quantize Q4_K_M → `ollama create` from a
  Modelfile. Watch the chat template: the app sends a single `{"role": "user"}` message and relies
  on Ollama's built-in template, so the fine-tune must be trained with the same one or the
  Modelfile must carry a matching `TEMPLATE` block.
- Prefer pinning and re-quantizing the upstream `google/medgemma-4b-it` yourself rather than
  assuming the community GGUF currently in `MODEL` has tensors matching your training base.

## Swapping it in, and the A/B

`app/generate/ollama_client.py`'s `MODEL` (now `CADENCE_MODEL`-overridable) and `model_for()` are
the **only** places a quality-tier model name is chosen — every path routes through them, including
the eval runner. So the whole procedure is:

```powershell
.venv/Scripts/python.exe scripts/eval_corpus.py --runs 1                 # base
$env:CADENCE_MODEL = "cadence-medgemma:v1"
.venv/Scripts/python.exe scripts/eval_corpus.py --runs 1                 # tuned
.venv/Scripts/python.exe scripts/eval_compare.py <base>.json <tuned>.json --scope handwritten
```

`eval_corpus.py` already records the model id in every sweep's config, and `eval_compare.py`
already prints the safety metrics first and separately, with `--scope handwritten` for rule 21's
non-circular control. No new infrastructure is needed.

## The go/no-go is not "it scores higher"

Per rule 21(d) — read the direction, not the average:

- every Tier-B invariant ≥ base on every record;
- **no rise** in `distractor_leaks`, `units_overstated`, `minutes_fabricated`, or
  `laterality_errors`;
- `[[NEEDS: …]]` counts read as triage, not as a score.

**A tuned model that writes prettier notes and fabricates one more value is a regression.**

## What not to do

- Don't train on MedGemma's own unreviewed output (`docs/synthetic-data-plan.md` guardrail #2 — it
  bakes hallucinations in).
- Don't train on Claude-authored target notes — same reason, plus the circularity above.
- Don't send any real transcript or note to a rented GPU, a cloud notebook, or any LLM. That is
  the exact HIPAA disclosure the prototype's cloud call was removed to prevent.
- **Don't fine-tune a failure class that has a deterministic repair.** Rule 19's corollary is that
  the deterministic backstops held on 100% of runs while every prompt-only rule fluctuated. A
  fine-tune is a *probabilistic* fix with a much larger price tag; exhaust `postprocess.py` first.
