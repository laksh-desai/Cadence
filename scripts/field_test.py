"""Field test: run realistic FAKE visits through the exact pipeline the clinician uses, end to end.

Why this exists. Unit tests prove each guard works; the clinician's complaints ("slow", "no
output", "duplicated", "poor quality") are about what the WHOLE pipeline does on a real model.
This drives the same functions the background queue runs (`server._run_generation_job`: prompt ->
streaming generation with the loop guard -> postprocess -> verification -> CPT -> Billing section),
then saves each note through the real API (so carry-forward feeds the next visit exactly as in the
clinic) and runs the pre-send audit — over whole episodes: evaluation -> daily visits ->
re-evaluation -> discharge.

PHI: none. Cases are hand-written fake dictations (evals/data/field_cases.json) and everything is
written to a THROWAWAY database in a temp folder; the clinician's encrypted database is never opened.
Results (synthetic) go to evals/results/field/.

Usage:
    python scripts/field_test.py                 # all cases
    python scripts/field_test.py --only A2,B2    # some cases (prior visits of that patient still run)
    python scripts/field_test.py --fast          # the fast-draft model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.generate import billing_section, compliance, loopguard, ollama_client  # noqa: E402
from app.generate.forms import FORMS, spec_section_labels  # noqa: E402
from app.storage import db, repository  # noqa: E402
from app.ui import server  # noqa: E402

CASES = ROOT / "evals" / "data" / "field_cases.json"
OUT_DIR = ROOT / "evals" / "results" / "field"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def score(visit: dict, result: dict, audit: dict, stats: dict, seconds: float) -> dict:
    sections = result.get("sections") or []
    form_id = visit["form_id"]
    expect = visit.get("expect", {})
    labels = spec_section_labels(form_id)
    headings = [_norm(s["heading"]) for s in sections]
    present = [l for l in labels if any(_norm(l) == h or h.startswith(_norm(l)) for h in headings)]
    body_text = "\n".join(s["body"] for s in sections)
    dup_headings = len(headings) - len(set(headings))
    billing = next((s for s in sections if billing_section.is_billing_heading(s["heading"])), None)
    bbody = billing["body"] if billing else ""

    code_errors = []
    for code, minutes in (expect.get("codes") or {}).items():
        line = next((l for l in bbody.splitlines() if code in l), "")
        if not line:
            code_errors.append(f"{code} missing")
        elif minutes is not None and not re.search(rf"\b{minutes} min\b", line):
            code_errors.append(f"{code} minutes != {minutes}: {line.strip()[:80]}")
        elif minutes is None and "NEEDS" not in line:
            code_errors.append(f"{code} should be flagged for minutes")
    tt = expect.get("total_time")
    m = re.search(r"Total treatment time: (\d+)", bbody)
    if tt is not None and (not m or int(m.group(1)) != tt):
        code_errors.append(f"total time != {tt}")
    if "total_time" in expect and tt is None and m:
        code_errors.append("total time present but none was dictated")

    return {
        "id": visit["id"], "form_id": form_id,
        "seconds": round(seconds, 1),
        "prompt_tokens": stats.get("prompt_tokens"), "prompt_seconds": stats.get("prompt_seconds"),
        "output_tokens": stats.get("output_tokens"), "output_seconds": stats.get("output_seconds"),
        "parsed": bool(sections),
        "sections": len(sections),
        "template_labels_present": f"{len(present)}/{len(labels)}",
        "missing_labels": [l for l in labels if l not in present],
        "duplicate_headings": dup_headings,
        "looping": loopguard.is_looping(body_text),
        "needs_flags": body_text.count("[[NEEDS:"),
        "empty_bodies": sum(1 for s in sections if not s["body"].strip()),
        "billing_section": bool(billing),
        "billing_errors": code_errors,
        "audit_ready": audit.get("ready"),
        "audit_expected_ready": expect.get("audit_ready", True),
        "audit_findings": [f["level"] + ": " + f["text"] for f in audit.get("findings", [])],
        "chars": len(body_text),
        "stopped_by_loop_guard": bool(stats.get("stopped_by_loop_guard")),
        "medicare_fix": [f["element"] + ": " + f["text"] for f in compliance.check(form_id, sections)
                         if f["level"] == "fix"],
        "medicare_check": [f["element"] for f in compliance.check(form_id, sections)
                           if f["level"] == "check"],
        "sections_detail": sections,
        "ok": bool(sections) and not dup_headings and not loopguard.is_looping(body_text)
              and not code_errors and len(sections) >= expect.get("sections_min", 1)
              and not any(f["level"] == "fix" for f in compliance.check(form_id, sections)
                          if f["element"] not in ("Interventions",)),
    }


async def generate(payload: dict) -> tuple[dict, float]:
    job = SimpleNamespace(payload=payload, detail="")
    t0 = time.time()
    result = await server._run_generation_job(job, lambda _chunk: None)
    return result, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated case id prefixes, e.g. A2,B1")
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()
    only = [o.strip() for o in args.only.split(",") if o.strip()]
    cases = json.loads(CASES.read_text(encoding="utf-8"))

    tmp = Path(tempfile.mkdtemp(prefix="cadence_field_"))
    db.ENC_PATH, db.KEYFILE = tmp / "cadence.db.enc", tmp / ".keyfile"
    db.init()
    server.app.state.medasr_ready, server.app.state.medasr_error = False, "field test"
    client = TestClient(server.app)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rows, notes_md = [], [f"# Field test {stamp} (synthetic)\n"]
    try:
        for patient in cases["patients"]:
            visits = patient["visits"]
            if only:
                last = max((i for i, v in enumerate(visits) if any(v["id"].startswith(o) for o in only)),
                           default=-1)
                if last < 0:
                    continue
                visits = visits[: last + 1]
            pid = repository.create_patient(name=patient["name"], dob=None, mrn=None,
                                            condition=patient["condition"], synthetic=True)["id"]
            for visit in visits:
                payload = {"patient_id": pid, "form_id": visit["form_id"],
                           "summary": visit["dictation"], "use_prior": True, "fast": args.fast}
                print(f"-> {visit['id']} ({FORMS[visit['form_id']].name}) ...", flush=True)
                try:
                    result, secs = asyncio.run(generate(payload))
                except Exception as e:  # noqa: BLE001 - record and continue the sweep
                    rows.append({"id": visit["id"], "form_id": visit["form_id"], "ok": False,
                                 "error": repr(e)})
                    print("   ERROR", e, flush=True)
                    continue
                stats = dict(ollama_client.last_stats)
                saved = client.post(f"/api/patients/{pid}/notes", json={
                    "form_id": result["form_id"], "form_name": result["form_name"],
                    "sections": result["sections"], "missing_info": result["missing_info"],
                    "dictation_raw": visit["dictation"], "used_prior": result["used_prior"],
                    "synthetic": True,
                }).json()
                audit = client.get(f"/api/patients/{pid}/notes/{saved['id']}/audit").json()
                row = score(visit, result, audit, stats, secs)
                row["used_prior"] = result["used_prior"]
                rows.append(row)
                print(f"   {'OK ' if row['ok'] else 'BAD'} {row['seconds']}s  prompt {row['prompt_tokens']} tok/"
                      f"{row['prompt_seconds']}s  out {row['output_tokens']} tok/{row['output_seconds']}s  "
                      f"labels {row['template_labels_present']}  billing errs {row['billing_errors']}", flush=True)
                notes_md.append(f"\n## {visit['id']} — {result['form_name']}\n")
                for s in result["sections"]:
                    notes_md.append(f"### {s['heading']}\n{s['body']}\n")
                if result["missing_info"]:
                    notes_md.append("**Missing info:** " + " | ".join(result["missing_info"]) + "\n")
                notes_md.append("**Audit:** " + json.dumps(audit.get("findings")) + "\n")
    finally:
        (OUT_DIR / f"{stamp}_field.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        (OUT_DIR / f"{stamp}_notes.md").write_text("\n".join(notes_md), encoding="utf-8")
        db.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    good = sum(1 for r in rows if r.get("ok"))
    timed = [r["seconds"] for r in rows if r.get("seconds")]
    print(f"\n{good}/{len(rows)} OK; mean {sum(timed)/max(len(timed),1):.0f}s per note; "
          f"results in {OUT_DIR / (stamp + '_field.json')}")
    return 0 if good == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
