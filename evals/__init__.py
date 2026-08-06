"""Corpus evaluation harness for the note-generation pipeline.

Observes `app/` — never modifies it. Nothing in this package is imported by the running
application; it exists to measure the pipeline against a synthetic transcript corpus so
note quality can be tracked as prompts and templates change (go-live checklist step 4).
"""
