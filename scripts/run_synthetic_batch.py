"""Run every synthetic sample input through the REAL local pipeline and collect the notes in a file.

Reads the 15 transcripts straight out of docs/synthetic-data-plan.md (single source of truth), then
for each one runs the exact production path /api/generate uses:

    build_prompt -> generate_note (Ollama/MedGemma) -> parse_plain -> postprocess -> traceability -> cpt

and appends the finished note to docs/synthetic-run-outputs.md AS IT GOES, so a long CPU run leaves a
useful partial file even if interrupted. FAKE data only — no PHI (see docs/synthetic-data-plan.md).

    .venv/Scripts/python.exe scripts/run_synthetic_batch.py
    .venv/Scripts/python.exe scripts/run_synthetic_batch.py --fast     # gemma2:2b draft tier (faster)
    .venv/Scripts/python.exe scripts/run_synthetic_batch.py --only 2,7  # just those sample numbers

Carry-forward note: followups are run WITHOUT a prior snapshot (a fresh first run), so the carried
sections are told to flag rather than reconcile — reconciliation only fires when a stored prior note
exists. The dictations still state today's values, so the notes are complete regardless.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.generate import cpt, postprocess, traceability
from app.generate.forms import FORMS
from app.generate.ollama_client import generate_note, is_reachable, model_for
from app.generate.parser import parse_plain
from app.generate.prompt import PatientContext, build_prompt, render_prior_block

PLAN = ROOT / "docs" / "synthetic-data-plan.md"
OUT = ROOT / "docs" / "synthetic-run-outputs.md"

_HEADER_RE = re.compile(r"^\*\*(\d+)\s*[·]\s*(.+?)\*\*")


def parse_transcripts(plan_path: Path) -> list[dict]:
    """Pull {n, title, form_id, text} for each sample out of the plan's 'Sample inputs' section."""
    entries: list[dict] = []
    cur: dict | None = None
    form_id: str | None = None
    in_samples = False
    for raw in plan_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## Sample inputs"):
            in_samples = True
            continue
        if not in_samples:
            continue
        if line.startswith("## "):  # next H2 -> end of the samples section
            break
        if line.startswith("### "):
            m = re.search(r"`([a-z_]+)`", line)
            if m:
                form_id = m.group(1)
            continue
        hm = _HEADER_RE.match(line)
        if hm:
            if cur:
                entries.append(cur)
            cur = {"n": int(hm.group(1)), "title": hm.group(2).strip(), "form_id": form_id, "text": ""}
            continue
        if line.startswith(">") and cur is not None:
            piece = line[1:].strip()
            cur["text"] = (cur["text"] + " " + piece).strip() if cur["text"] else piece
    if cur:
        entries.append(cur)
    return entries


def run_pipeline(form, model_text: str, transcript: str):
    parsed = parse_plain(model_text)
    if not parsed:
        return None, []  # model didn't follow the ## contract; caller renders raw
    sections = postprocess.apply(form.id, parsed["sections"])
    sections = traceability.add_verification_flags(sections, transcript)
    sections, _ = cpt.suggest_codes(sections, form.id)
    return sections, parsed.get("missing_info", [])


def render_note(sections) -> str:
    out = []
    for s in sections:
        cf = "  [carried forward]" if s.get("carried_forward") else ""
        out.append(f"### {s['heading']}{cf}\n{s['body']}")
    return "\n\n".join(out)


def flag_summary(text: str) -> str:
    needs = re.findall(r"\[\[NEEDS:\s*(.+?)\]\]", text)
    cpts = re.findall(r"\[\[CPT:\s*(.+?)\]\]", text)
    bits = [f"{len(needs)} gap/verify flag(s)", f"{len(cpts)} CPT chip(s)"]
    return " · ".join(bits)


def _resolve(p: Path) -> Path:
    return p if p.is_absolute() else (ROOT / p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="use the gemma2:2b draft tier (default: quality model)")
    ap.add_argument("--only", help="comma-separated sample numbers to run, e.g. 2,7,12")
    ap.add_argument("--sources", help="comma-separated markdown files each with a '## Sample inputs' "
                    "section (default: docs/synthetic-data-plan.md). Pass both the 15-sample plan and "
                    "the long-form set to run all 25.")
    ap.add_argument("--out", help="output markdown path (default: docs/synthetic-run-outputs.md). A "
                    "machine-readable <out>.json sidecar is written alongside.")
    args = ap.parse_args()

    if not asyncio.run(is_reachable()):
        print("Ollama isn't reachable on localhost:11434. Start it, then re-run.")
        return 1

    model = model_for(args.fast)
    sources = [_resolve(Path(s.strip())) for s in args.sources.split(",")] if args.sources else [PLAN]
    out_path = _resolve(Path(args.out)) if args.out else OUT
    json_path = out_path.with_suffix(".json")

    entries: list[dict] = []
    for s in sources:
        entries += parse_transcripts(s)
    if args.only:
        wanted = {int(x) for x in args.only.split(",")}
        entries = [e for e in entries if e["n"] in wanted]
    if not entries:
        print(f"No transcripts parsed from {', '.join(str(s) for s in sources)}.")
        return 1

    started = datetime.now()
    src_names = ", ".join(f"[{s.name}]({s.name})" for s in sources)
    header = (
        f"# Synthetic batch run — generated notes\n\n"
        f"Model: `{model}` · run started {started:%Y-%m-%d %H:%M} · {len(entries)} inputs.\n"
        f"FAKE data only, no PHI. Every note here is a DRAFT — clinician review still required.\n"
        f"Source transcripts: {src_names}. Regenerate with `scripts/run_synthetic_batch.py`.\n\n---\n"
    )
    out_path.write_text(header, encoding="utf-8")
    print(f"Writing to {out_path}  (model: {model}, {len(entries)} inputs)")

    records: list[dict] = []
    total_t0 = time.perf_counter()
    times = []
    for i, e in enumerate(entries, 1):
        form = FORMS[e["form_id"]]
        ctx = PatientContext(name=f"Sample {e['n']} (fake)", sub=f"synthetic — {e['form_id']} — no PHI")
        prompt = build_prompt(form, ctx, e["text"], render_prior_block(form, None, False), None)
        print(f"[{i}/{len(entries)}] #{e['n']} {e['title']} ({form.name}) — generating…", flush=True)
        t0 = time.perf_counter()
        try:
            model_text = asyncio.run(generate_note(prompt, model=model))
        except Exception as ex:  # noqa: BLE001
            block = f"\n## #{e['n']} · {e['title']}\n\n**Form:** {form.name} — GENERATION FAILED: {ex}\n\n---\n"
            with out_path.open("a", encoding="utf-8") as f:
                f.write(block)
            records.append({"n": e["n"], "title": e["title"], "form_id": e["form_id"],
                            "error": str(ex), "sections": None, "missing": [], "transcript": e["text"]})
            json_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
            print(f"    FAILED: {ex}", flush=True)
            continue
        dt = time.perf_counter() - t0
        times.append(dt)

        sections, missing = run_pipeline(form, model_text, e["text"])
        if sections is None:
            body = f"_Model did not follow the `## heading` contract — raw output:_\n\n```\n{model_text.strip()}\n```"
            summary = "unparsed"
        else:
            body = render_note(sections)
            summary = f"{len(sections)} sections · {flag_summary(body)}"
            if missing:
                body += "\n\n**Missing-info list:** " + "; ".join(missing)

        block = (
            f"\n## #{e['n']} · {e['title']}\n\n"
            f"**Form:** {form.name} · **{dt:.0f}s** · {summary} · {len(model_text)} chars\n\n"
            f"<details><summary>Input transcript</summary>\n\n> {e['text']}\n\n</details>\n\n"
            f"{body}\n\n---\n"
        )
        with out_path.open("a", encoding="utf-8") as f:
            f.write(block)
        records.append({"n": e["n"], "title": e["title"], "form_id": e["form_id"], "form_name": form.name,
                        "seconds": round(dt, 1), "chars": len(model_text), "raw_text": model_text,
                        "sections": sections, "missing": missing, "transcript": e["text"]})
        json_path.write_text(json.dumps(records, indent=1), encoding="utf-8")  # updated as-we-go
        print(f"    done in {dt:.0f}s — {summary}", flush=True)

    total = time.perf_counter() - total_t0
    avg = sum(times) / len(times) if times else 0
    footer = (
        f"\n## Run summary\n\n"
        f"- {len(times)} notes generated in **{total/60:.1f} min** total (avg {avg:.0f}s/note)\n"
        f"- Model: `{model}`\n"
        f"- Finished {datetime.now():%Y-%m-%d %H:%M}\n"
    )
    with out_path.open("a", encoding="utf-8") as f:
        f.write(footer)
    print(f"\nAll done: {len(times)} notes in {total/60:.1f} min (avg {avg:.0f}s). Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
