"""Populate the app's OWN database with synthetic demo patients and their generated notes.

WHY THIS IS NOT PART OF THE EVAL HARNESS. `tests/test_eval_isolation.py` structurally forbids
anything under `evals/` from importing `app.storage`, so a scored sweep can never write synthetic
patients into the clinician's encrypted record store. That guarantee is about SWEEPS — a
measurement run must not have side effects on real records. Seeding demo data is the opposite
intent: a deliberate, explicitly-invoked action whose entire purpose IS to write rows, so the
browser UI can be looked at with realistic content in it.

Keeping the two apart is what lets both be true. This script lives in `scripts/`, imports
`app.storage` directly, and reuses `evals.synth` ONLY as a dictation generator — it never calls
`evals.runner`, so nothing in the eval path gains a route to the database.

EVERY row it writes is marked `synthetic = 1` (patients AND notes), so `--clear` removes exactly
what this script created and can never touch a patient a human entered. That column is
`NOT NULL DEFAULT 0` precisely so "unknown" reads as "real, do not delete".

    .venv/Scripts/python.exe scripts/seed_demo_data.py --per-part 2
    .venv/Scripts/python.exe scripts/seed_demo_data.py --list
    .venv/Scripts/python.exe scripts/seed_demo_data.py --clear
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate import billing, chunked, cpt, ollama_client, postprocess, traceability
from app.generate import forms as forms_store
from app.generate.forms import FORMS
from app.generate.ollama_client import OllamaUnavailableError, generate_note
from app.generate.parser import parse_plain
from app.generate.prompt import PatientContext, build_prompt, render_prior_block
from app.storage import db, repository
from evals.synth import banks, generate as synth


def _demographics(rng: random.Random) -> tuple[str, str]:
    """A plausible DOB and MRN. The generator produces clinical content, not identity, and the
    roster looks wrong without these — an empty DOB column reads as a bug, not as demo data."""
    dob = date(rng.randint(1945, 2001), rng.randint(1, 12), rng.randint(1, 28))
    return dob.isoformat(), f"MRN{rng.randint(100000, 999999)}"


async def _generate_note(transcript: str, form, patient_ctx, fast: bool):
    """The SAME pipeline /api/generate runs, called directly rather than over HTTP."""
    prior_block = render_prior_block(form, None, False)
    overhead = chunked.estimate_tokens(build_prompt(form, patient_ctx, "", prior_block, None))
    summary, was_condensed, _still_over = await chunked.fit_dictation(
        transcript, overhead, generate_note)
    prompt = build_prompt(form, patient_ctx, summary, prior_block, None)
    text = await generate_note(prompt, model=ollama_client.model_for(fast))

    draft = billing.extract(transcript)
    parsed = parse_plain(text)
    if parsed is None:
        return [], ["The model did not return a parseable note."], draft

    sections = postprocess.apply(form.id, parsed["sections"])
    sections = traceability.add_verification_flags(sections, transcript)
    sections, code_flags = cpt.suggest_codes(sections, form.id)
    draft = billing.reconcile(draft, sections)
    missing = list(parsed["missing_info"]) + code_flags
    if was_condensed:
        missing.append("This dictation was long and was automatically condensed to fit the model "
                       "— verify the note captured the whole session.")
    return sections, missing, draft


def cmd_list() -> int:
    db.init()
    try:
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT p.id, p.name, p.condition, p.synthetic, "
            "(SELECT COUNT(*) FROM notes n WHERE n.patient_id=p.id) AS n "
            "FROM patients p ORDER BY p.synthetic, p.created_at").fetchall()
        conn.close()
        real = [r for r in rows if not r["synthetic"]]
        demo = [r for r in rows if r["synthetic"]]
        print(f"REAL / pre-existing patients ({len(real)}) — never touched by this script:")
        for r in real:
            print(f"   {r['name'][:30]:<30} {(r['condition'] or '-')[:36]:<36} {r['n']} note(s)")
        print(f"\nDEMO patients ({len(demo)}) — removable with --clear:")
        for r in demo:
            print(f"   {r['name'][:30]:<30} {(r['condition'] or '-')[:36]:<36} {r['n']} note(s)")
    finally:
        db.shutdown()
    return 0


def cmd_clear() -> int:
    db.init()
    try:
        conn = db.get_connection()
        ids = [r["id"] for r in conn.execute("SELECT id FROM patients WHERE synthetic=1")]
        conn.close()
        if not ids:
            print("No demo patients to remove.")
            return 0
        for pid in ids:
            repository.delete_patient(pid)   # removes notes + carry snapshot in dependency order
        db.persist()
        print(f"Removed {len(ids)} demo patient(s) and their notes. Real patients untouched.")
    finally:
        db.shutdown()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-part", type=int, default=2, help="demo patients per body part")
    ap.add_argument("--note-type", default="initial", choices=list(synth.NOTE_TYPES))
    ap.add_argument("--complexity", default="high", choices=list(synth.COMPLEXITIES))
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--body-parts", default=None,
                    help="comma-separated subset (default: every region with a phrase bank)")
    ap.add_argument("--fast", action="store_true",
                    help="use the 2B draft model — much quicker, visibly lower note quality")
    ap.add_argument("--list", action="store_true", help="show what is in the DB and exit")
    ap.add_argument("--clear", action="store_true", help="remove ONLY synthetic=1 rows and exit")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.clear:
        return cmd_clear()

    parts = ([p.strip() for p in args.body_parts.split(",")] if args.body_parts
             else list(banks.TREATMENTS_BY_BODY_PART))
    if not asyncio.run(ollama_client.is_reachable()):
        print("ERROR: Ollama isn't reachable on localhost:11434. Start it and pull MedGemma.")
        return 2

    form = FORMS["initial" if args.note_type == "initial" else "followup"]
    total = len(parts) * args.per_part
    est = total * (1.5 if args.fast else 6)
    print(f"Seeding {total} demo patients ({args.per_part} x {len(parts)} regions), "
          f"{form.name} each, model={ollama_client.model_for(args.fast)}")
    print(f"Rough estimate: {est:.0f} min on this CPU. Rows are marked synthetic=1 and "
          f"removable with --clear.\n")

    db.init()
    made = 0
    used_names: set[str] = set()
    t0 = time.perf_counter()
    try:
        for part in parts:
            samples = synth.generate_corpus(body_part=part, note_type=args.note_type,
                                            count=args.per_part, complexity=args.complexity,
                                            seed=args.seed)
            for s in samples:
                rng = random.Random(f"{args.seed}|{s.id}")
                dob, mrn = _demographics(rng)
                # The generator draws names per body part off the same seed, so the same person
                # can surface in two regions with two different DOBs. Harmless in a corpus file,
                # but in a 12-row roster it reads as a duplicate-record bug.
                name = s.patient_name
                if name in used_names:
                    name = f"{name.split()[0]} {rng.choice(banks.PATIENT_NAMES).split()[-1]}"
                used_names.add(name)
                patient = repository.create_patient(
                    name=name, dob=dob, mrn=mrn,
                    condition=(s.diagnosis_formal or s.diagnosis),
                    scheduling_notes=None, synthetic=True)
                sub = " · ".join([f"MRN {mrn}", f"DOB {dob}", s.diagnosis])
                ctx = PatientContext(name=name, sub=sub)

                made += 1
                print(f"[{made}/{total}] {part:<9} {name[:26]:<26} generating... ",
                      end="", flush=True)
                started = time.perf_counter()
                try:
                    sections, missing, draft = asyncio.run(
                        _generate_note(s.transcript, form, ctx, args.fast))
                except OllamaUnavailableError as e:
                    print(f"\n  ABORT — {e}")
                    break

                repository.create_note(
                    patient_id=patient["id"], form_id=form.id, form_name=form.name,
                    sections=sections, missing_info=missing, dictation_raw=s.transcript,
                    used_prior=False,
                    # Nothing edited yet, so edited_section_count records 0 = "accepted as
                    # generated" rather than NULL = "not captured". A later clinician edit in the
                    # UI then shows up as a real correction against this baseline.
                    original_sections=sections,
                    revise_instructions=[],
                    model_id=ollama_client.model_for(args.fast), fast=args.fast,
                    template_spec_sha=forms_store.spec_sha(form.id),
                    template_customized=forms_store.is_customized(form.id),
                    synthetic=True,
                )
                db.persist()
                print(f"{time.perf_counter() - started:.0f}s  {len(sections)} sections, "
                      f"{len(missing)} flag(s), {len(draft.billable)} billable code(s)")
    finally:
        db.shutdown()

    print(f"\nDone: {made} demo patients in {(time.perf_counter() - t0) / 60:.0f} min.")
    print("Open the app (launcher.py -> http://127.0.0.1:8420), then All Patients.")
    print("Remove them any time with:  scripts/seed_demo_data.py --clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
