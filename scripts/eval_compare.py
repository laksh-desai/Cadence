"""Diff two sweep result files from evals/results/ to see whether a change helped.

Safety metrics are printed first and separately, because they answer a different question from
the accuracy ones: a leak is a wrong claim, an accuracy dip is an incomplete draft.

    .venv/Scripts/python.exe scripts/eval_compare.py                      # newest two runs
    .venv/Scripts/python.exe scripts/eval_compare.py old.json new.json
    .venv/Scripts/python.exe scripts/eval_compare.py --scope handwritten  # the non-circular control
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import results as results_store

SAFETY = ("distractor_leaks", "untimed_leaks", "laterality_errors", "minutes_fabricated")


def _resolve(args) -> tuple[Path, Path] | None:
    if args.older and args.newer:
        return Path(args.older), Path(args.newer)
    rows = results_store.list_runs(args.dir)
    if len(rows) < 2:
        print(f"Need two sweeps in {args.dir or results_store.RESULTS_DIR}; found {len(rows)}.")
        return None
    directory = args.dir or results_store.RESULTS_DIR
    return directory / rows[1]["file"], directory / rows[0]["file"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("older", nargs="?", default=None)
    ap.add_argument("newer", nargs="?", default=None)
    ap.add_argument("--dir", type=Path, default=None, help="results dir (default evals/results)")
    ap.add_argument("--scope", default="all", choices=("all", "synthetic", "handwritten"),
                    help="'handwritten' is the non-circular control — read it before 'all'")
    ap.add_argument("--force", action="store_true",
                    help="compare across differing generator versions (mixes data and code changes)")
    args = ap.parse_args()

    pair = _resolve(args)
    if pair is None:
        return 2
    older_path, newer_path = pair
    for p in (older_path, newer_path):
        if not p.exists():
            print(f"ERROR: no such results file: {p}")
            return 2

    try:
        diff = results_store.compare(results_store.load_run(older_path),
                                     results_store.load_run(newer_path),
                                     force=args.force, scope=args.scope)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2

    print("=" * 78)
    print(f"{older_path.name}  ->  {newer_path.name}   [scope: {diff['scope']}]")
    print(f"git {diff['git_sha']['before']} -> {diff['git_sha']['after']}   "
          f"generator v{diff['generator_version']['before']} -> v{diff['generator_version']['after']}")
    print("=" * 78)

    metrics = diff["metrics"]
    if not metrics:
        print("\nNo comparable metrics — is this scope empty in one of the runs?")
        return 0

    def _row(key, m):
        arrow = {"better": "+", "worse": "!", "same": " "}[m["direction"]]
        return f"  {arrow} {key:<26} {m['before']!s:>8} -> {m['after']!s:>8}   ({m['delta']:+})"

    print("\nSAFETY  (nonzero is a wrong claim, not an incomplete one)")
    for key in SAFETY:
        if key in metrics:
            print(_row(key, metrics[key]))

    print("\nACCURACY")
    for key, m in metrics.items():
        if key not in SAFETY:
            print(_row(key, m))

    regressions = [k for k, m in metrics.items() if m["direction"] == "worse"]
    unsafe = [k for k in SAFETY if metrics.get(k, {}).get("direction") == "worse"]
    print("\n" + "=" * 78)
    if unsafe:
        print(f"REGRESSED ON SAFETY: {unsafe} — a wrong claim got through that didn't before.")
    elif regressions:
        print(f"Accuracy regressions: {regressions}")
    else:
        print("No regressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
