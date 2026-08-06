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

`cpt_codes` is the corpus's **only ground-truth label** and is what Tier A scores. Only the
`code` values are compared; the descriptions are not, since the corpus wording won't match
Cadence's own labels for the same code.

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
