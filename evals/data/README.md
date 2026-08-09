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

## What gets shared on GitHub

| path | shared? | why |
|---|---|---|
| `evals/data/*.jsonl` | **yes** | the synthetic corpus, so eval results are reproducible |
| `evals/data/*.local.jsonl` | no | holds REAL dictation; still loads locally |
| `evals/results/*.json` | **yes** | per-sweep scores — this is what a teammate reviews |
| `evals/results/*.local.json` | no | a sweep whose corpus included real dictation |
| `evals/runs*/` | no | one JSON + one note per generation; regenerable and churns every run |

**One rule: `.local` means "never leaves this machine".** It applies to corpus files and results
files alike.

The results split is **automatic**, not a convention to remember, because the failure mode is
silently publishing patient speech: `RecordResult.flags[].context` embeds a ~120-character
transcript excerpt so a reviewer can adjudicate a flag. That is harmless for a fictional patient
and is PHI for a real one — and GitHub is a non-BAA third party, so PHI may never go there
(CLAUDE.md non-negotiable #1). `evals/results.py:write_run` detects any `*.local.jsonl` in the
sweep's corpus and writes `*.local.json` plus a separate `index.local.jsonl`, both gitignored.
Local runs still appear in your own run history and in the Evals tab — "local" hides them from
git, not from you.

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

# all six regions at once
for p in shoulder knee lumbar cervical hip ankle; do
  .venv/Scripts/python.exe scripts/gen_synthetic.py --body-part $p --count 24 --complexity high --seed 1234
done
```

Supported regions: **shoulder, knee, lumbar, cervical, hip, ankle**. Each writes
`<region>_synth.jsonl` with its own id block (shoulder 1001+, knee 2001+, lumbar 3001+,
cervical 4001+, hip 5001+, ankle 6001+) so the loader's cross-file uniqueness check can never
collide. Adding a region needs an `ICD_BY_BODY_PART` entry in `app/generate/coding_tables.py` and
a phrase bank in `evals/synth/banks.py` — no code changes anywhere else.

Deterministic and offline — no model. The same arguments always produce the same file, and
raising `--count` leaves earlier records byte-identical, so the committed corpus diffs readably.
Ids are blocked per body part (shoulder synthetic = 1001+, hand-written = 101-108) so the
loader's cross-file uniqueness check can never collide.

## The hand-written control set

`shoulder.jsonl` (records 101-108) and `<region>_control.jsonl` (201/202 knee, 301/302 lumbar,
401/402 cervical, 501/502 hip, 601/602 ankle) are **hand-written prose, hand-labeled**. They are
the non-circular control, and they are not optional — the generator and the extractor share an
author, so a synthetic-only score can look good while both are wrong about real dictation.

The two sets stress different things, which is why neither replaces the other:

| | stresses | example |
|---|---|---|
| `*_synth.jsonl` | **vocabulary** — unknown phrasings for a known service | "hands-on work", "functional activities" |
| `*_control.jsonl` | **structure** — how minutes, negations and post-op framings are really spoken | "we spent about twenty-five minutes on", "held off on the e-stim", "she's four weeks out from" |

**Every defect found so far came from the structural axis**, which a template generator cannot
probe: a four-code overbill from `"Interventions planned include …"`, a false-positive diagnosis
from an HPI clause, and two missed post-op diagnosis framings.

Read the **direction** of the synthetic-vs-hand-written gap, not just its size. Synthetic scoring
*higher* is the circularity failure. Synthetic scoring *lower* — where the corpus sits now — means
the generator is stress-testing harder than reality, which is the intended state.

Their gold labels must be verified **by the clinician**; `gold_provenance.verified_by` is blank
until then and `tests/test_billing_extract.py` keeps saying so. Never label them by running the
extractor and accepting its output. See CLAUDE.md rule 21.
`scripts/_add_control_records.py` holds the labels and the rationale for each non-shoulder record.

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
