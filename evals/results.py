"""Timestamped, structured sweep results in `evals/results/`, for run-over-run comparison.

Two directories, two jobs, deliberately not merged:

  evals/runs/     one JSON + one .note.md PER GENERATION — debug artifacts, and the cache
                  `--resume` reads. Noisy, rewritten constantly.
  evals/results/  one file PER SWEEP — config + aggregate + every record. This is the thing you
                  diff against last week.

**Aggregates are always reported three ways: `synthetic`, `handwritten`, `all`.** The generator
and the extractor share an author, so a synthetic-only score can be high while both are wrong
about real dictation. The eight hand-written records are the non-circular control, and a large
gap between the two columns is the signal that the generator has taught the extractor its own
blind spots. Reading only the `all` number hides exactly that.

`config.cadence_git_sha` and `config.generator_version` are what make two runs comparable at all;
`compare()` refuses to diff across generator versions without `force=True`, because a corpus
change and a code change would otherwise be indistinguishable in a score delta.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evals import runner

SCHEMA_VERSION = 1
RESULTS_DIR = Path(__file__).resolve().parent / "results"
INDEX_PATH = RESULTS_DIR / "index.jsonl"


def git_sha() -> str:
    """Short SHA of the working tree, or "unknown". Never raises — a results file must still be
    writable in a tarball with no .git."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=Path(__file__).resolve().parent.parent,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def split_aggregate(results) -> dict:
    """Aggregate three ways. See the module docstring for why the split is not optional."""
    synthetic = [r for r in results if r.is_synthetic]
    handwritten = [r for r in results if not r.is_synthetic]
    return {
        "all": runner.aggregate(results),
        "synthetic": runner.aggregate(synthetic),
        "handwritten": runner.aggregate(handwritten),
    }


def touched_real_dictation(config: dict) -> bool:
    """True if this sweep's corpus included a `*.local.jsonl` file — the documented escape hatch
    for REAL patient dictation (evals/data/README.md).

    This matters because `RecordResult.flags[].context` embeds a ~120-char TRANSCRIPT EXCERPT so a
    reviewer can adjudicate a flag. For synthetic patients that is harmless and useful. For real
    dictation it is PHI, and results files are committed to git — which is a non-BAA third party
    and therefore somewhere PHI may never go (CLAUDE.md non-negotiable #1).
    """
    return any(str(f).endswith(".local.jsonl") for f in config.get("corpus_files", ()))


def write_run(results, *, config: dict, run_id: str | None = None,
              started_at: str | None = None, out_dir: Path | None = None) -> Path:
    """Write one sweep's full results and append a one-line summary to the index.

    A sweep that touched real dictation is written as `*.local.json` and indexed separately, both
    of which `.gitignore` keeps out of the repo. Automatic rather than a convention someone has to
    remember, because the failure mode is silently publishing patient speech.
    """
    directory = out_dir or RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    rid = run_id or new_run_id()
    is_local = touched_real_dictation(config)

    cfg = dict(config)
    cfg.setdefault("cadence_git_sha", git_sha())
    from evals.synth.generate import GENERATOR_VERSION
    cfg.setdefault("generator_version", GENERATOR_VERSION)

    aggregate = split_aggregate(results)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": rid,
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
        "aggregate": aggregate,
        "records": [r.to_dict() for r in results],
    }

    name = "_".join(str(x) for x in [
        rid, cfg.get("body_part", "corpus"), cfg.get("note_type", "all"),
        f"n{len(results)}",
    ])
    # `.local.json` is gitignored; the plain name is committed for teammates to review.
    path = directory / (f"{name}.local.json" if is_local else f"{name}.json")
    payload["contains_real_dictation"] = is_local
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = directory / ("index.local.jsonl" if is_local else INDEX_PATH.name)
    with index.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "run_id": rid, "file": path.name, "finished_at": payload["finished_at"],
            "config": cfg, "aggregate": aggregate["all"],
        }) + "\n")
    return path


def load_run(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_runs(out_dir: Path | None = None, limit: int = 50) -> list[dict]:
    """Past sweeps, newest first.

    Reads BOTH indexes. "Local" means "never leaves this machine", not "hidden from the person who
    ran it" — a sweep over real dictation must still show up in the clinician's own run history,
    it just never reaches git.
    """
    directory = out_dir or RESULTS_DIR
    rows = []
    for name in (INDEX_PATH.name, "index.local.jsonl"):
        index = directory / name
        if not index.exists():
            continue
        for line in index.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a truncated line from an interrupted write must not break the list
            row.setdefault("contains_real_dictation", name != INDEX_PATH.name)
            rows.append(row)
    rows.sort(key=lambda r: r.get("finished_at", ""))
    return list(reversed(rows))[:limit]


#: Metrics where a HIGHER number is worse. Kept explicit so `compare` can label a delta as an
#: improvement or a regression instead of leaving the reader to remember which way each one runs.
LOWER_IS_BETTER = frozenset({
    "distractor_leaks", "untimed_leaks", "laterality_errors", "minutes_fabricated",
    "minutes_not_extracted", "minutes_mae", "mean_seconds",
})


def compare(older: dict, newer: dict, *, force: bool = False, scope: str = "all") -> dict:
    """Metric-by-metric delta between two sweeps.

    Refuses to compare across generator versions unless forced: a corpus that changed and code
    that changed produce the same shape of score movement, and conflating them is how a
    regression gets explained away as "the data changed".
    """
    ov = older.get("config", {}).get("generator_version")
    nv = newer.get("config", {}).get("generator_version")
    if ov != nv and not force:
        raise ValueError(
            f"generator_version differs ({ov} -> {nv}); the corpora are not the same samples, so "
            "a metric delta would mix a data change with a code change. Regenerate the corpus at "
            "one version, or pass force=True if you know what you're comparing."
        )
    a = older.get("aggregate", {}).get(scope, {}) or {}
    b = newer.get("aggregate", {}).get(scope, {}) or {}
    deltas = {}
    for key in sorted(set(a) | set(b)):
        av, bv = a.get(key), b.get(key)
        if not isinstance(av, (int, float)) or not isinstance(bv, (int, float)):
            continue
        diff = round(bv - av, 4)
        if diff == 0:
            direction = "same"
        elif key in LOWER_IS_BETTER:
            direction = "better" if diff < 0 else "worse"
        else:
            direction = "better" if diff > 0 else "worse"
        deltas[key] = {"before": av, "after": bv, "delta": diff, "direction": direction}
    return {
        "scope": scope,
        "older_run": older.get("run_id"),
        "newer_run": newer.get("run_id"),
        "generator_version": {"before": ov, "after": nv},
        "git_sha": {"before": older.get("config", {}).get("cadence_git_sha"),
                    "after": newer.get("config", {}).get("cadence_git_sha")},
        "metrics": deltas,
    }
