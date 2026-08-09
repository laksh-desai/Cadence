"""Seeded, offline synthetic dictation generator with exact billing ground truth.

SYNTHETIC DATA ONLY — fictional patients, no PHI. Nothing here calls a model or touches
app/storage. See `generate.py` for the label-first design and `banks.py` for the deliberate
paraphrase gap that keeps the eval from scoring itself.
"""
