# Eval corpus — SYNTHETIC DATA ONLY

Put the corpus JSONL files in this directory. `evals/dataset.py` reads **every `*.jsonl`**
here and merges them into one normalized list.

## Provenance requirement

**Only synthetic, fictional-patient data belongs in this directory, and it is committed to
git.** Real patient transcripts are PHI and must never be placed here — see the
non-negotiable constraints in `CLAUDE.md`. If you need to run the harness against real
dictation, name the file `*.local.jsonl`, which `.gitignore` excludes; it still loads.

Nothing in the eval path writes to `app/storage/`, so a sweep can never mix corpus records
into the clinician's encrypted patient database.

## Schema

One JSON object per line. Required on every record:

| Field | Type | Notes |
|---|---|---|
| `id` | int | Must be unique **across all files** — the loader rejects duplicates |
| `patient_name` | str | Fictional |
| `diagnosis` | str | Ground-truth context; becomes part of the patient sub-line |
| `visit_type` | str | Drives the template choice — see below |
| `date` | str | ISO date |
| `transcript` | str | Raw, unstructured PT dictation, not pre-organized into SOAP |

Optional:

| Field | Type | Notes |
|---|---|---|
| `cpt_codes` | list | `[{"code": "97110", "description": "..."}]`, or a bare list of code strings. Missing → `[]` |

Only the `code` values are compared; the descriptions are not, since the corpus wording won't
match Cadence's own labels for the same code.

### Billing gold labels (optional)

The synthetic corpus adds ground truth for ICD-10, per-intervention minutes, and units. Every
field below defaults to empty, so the hand-written records keep loading unchanged;
`EvalRecord.has_billing_gold` is what the scorers gate on.

| Field | Type | Notes |
|---|---|---|
| `body_part` | str | Selects the ICD table in `app/generate/coding_tables.py` |
| `icd_codes` | list | Same shape as `cpt_codes` |
| `interventions` | list | `[{"code","label","minutes","timed","billable"}]`. `minutes` is `null` for untimed modalities |
| `distractors` | list | `[{"code","reason"}]` — named in the transcript but **must not be billed**. `reason` ∈ `negated`, `prior_visit`, `planned`, `home_program`, `self_corrected` |
| `total_timed_minutes` | int | Sum of TIMED interventions only |
| `expected_units` | int | 8-minute rule over `total_timed_minutes` (CMS substitution) |
| `expected_units_ama` | int | Same minutes under the AMA rule of eights — the two genuinely differ |
| `synth` | object | Generator provenance. Its presence is what marks a record synthetic |

`cpt_codes` is **derived** from `interventions where billable`, so Tier A reads exactly what it
always did while the richer labels sit alongside it.

`distractors` is what makes a precision failure attributable: a scorer can report "a prior-visit
treatment was billed" rather than only "precision dropped", which points at the specific guard in
`app/generate/billing.py` that let it through.

## Generating a synthetic corpus

```
.venv/Scripts/python.exe scripts/gen_synthetic.py --body-part shoulder --note-type followup \
    --count 24 --complexity high --seed 1234
.venv/Scripts/python.exe scripts/gen_synthetic.py --preview 3      # print, write nothing
```

Deterministic and offline — no model. The same arguments always produce the same file, and
raising `--count` leaves earlier records byte-identical, so the committed corpus diffs readably.
Ids are blocked per body part (shoulder synthetic = 1001+, hand-written = 101-108) so the
loader's cross-file uniqueness check can never collide.

**Keep the hand-written records.** They are the non-circular control: the generator and the
extractor share an author, so a synthetic-only score can look good while both are wrong about
real dictation. Their billing gold fields must be labeled **by hand by the clinician** — never by
running the extractor and accepting its output. See CLAUDE.md rule 21.

## `visit_type` → template

The loader maps `visit_type` onto one of the three loaded built-in forms:

- matches *initial / intake / new patient / evaluation / re-eval / assessment* → **`initial`**
- matches *follow-up / f/u / progress / interim / treatment / re-check* → **`followup`**
- anything else → **`UNMAPPED`**, and the sweep refuses to run until you either extend
  `_FORM_PATTERNS` in `evals/dataset.py` or pass `--form` to override.

Evaluations map to `initial` (field-per-section) rather than `initial_updated` (the one
remaining block-format template) because block output folds the note under a single heading,
which suppresses the per-treatment CPT chips Tier A scores. Use
`--form initial_updated` to compare the two deliberately.

## Example record

```json
{"id": 1, "patient_name": "Marcus Delgado", "diagnosis": "S/P Left ACL Reconstruction (autograft, hamstring)", "visit_type": "Follow-up, post-op week 6", "date": "2026-06-02", "transcript": "Okay this is Marcus Delgado...", "cpt_codes": [{"code": "97110", "description": "Therapeutic exercise"}]}
```

## Running

```
.venv/bin/python scripts/eval_corpus.py --limit 3 --runs 1     # smoke
.venv/bin/python scripts/eval_corpus.py --runs 3 --resume      # full sweep
```
