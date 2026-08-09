"""Corpus evaluation harness for the note-generation pipeline.

Observes `app/` — never modifies it. It exists to measure the pipeline against a synthetic
transcript corpus so note quality can be tracked as prompts and templates change (go-live
checklist step 4).

**ONE-WAY EXCEPTION (2026-08).** This package used to state that nothing in it was imported by the
running application. That is no longer true: `app/ui/evals_api.py` backs the browser's Evals tab
and calls `evals.runner`, `evals.synth`, and `evals.results`. The dependency runs `app -> evals`
ONLY — nothing here may import from `app.ui` or `app.storage`. Two properties make the exception
safe, and `tests/test_eval_isolation.py` enforces both:

  * the imports happen INSIDE the request handlers, never at module import, so a broken or absent
    evals package can never stop the clinical app from starting (same posture as the optional
    MedASR load in the server lifespan); and
  * `evals.runner`'s functions take an `EvalRecord` and a `FormSpec`. There is no parameter a
    patient id could enter through, and no module under `evals/` imports `app.storage` — which is
    what makes it structurally impossible for a sweep to write a synthetic patient into the
    clinician's encrypted record store.

SYNTHETIC DATA ONLY throughout. See `evals/data/README.md` for the provenance requirement.
"""
