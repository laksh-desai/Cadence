"""Write a seeded synthetic corpus file with full billing ground truth (SYNTHETIC DATA ONLY).

Deterministic and offline — no model, no network, milliseconds for hundreds of samples. The same
arguments always produce the same file, and raising --count leaves the earlier records
byte-identical, so a committed corpus diffs meaningfully.

    .venv/Scripts/python.exe scripts/gen_synthetic.py --body-part shoulder --note-type followup \
        --count 20 --complexity high --seed 1234
    .venv/Scripts/python.exe scripts/gen_synthetic.py --preview 2        # print, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate import coding_tables
from evals.synth import banks, generate as synth

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "evals" / "data"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body-part", default="shoulder", choices=sorted(banks.TREATMENTS_BY_BODY_PART))
    ap.add_argument("--note-type", default="followup", choices=list(synth.NOTE_TYPES))
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--complexity", default="medium", choices=list(synth.COMPLEXITIES))
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--target-units", type=int, default=4,
                    help="units the timed total should land on (4 = a 53-67 min session)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output .jsonl (default evals/data/<body-part>_synth.jsonl)")
    ap.add_argument("--preview", type=int, default=0, metavar="N",
                    help="print N samples and exit without writing")
    args = ap.parse_args()

    if args.body_part not in coding_tables.BODY_PARTS:
        print(f"ERROR: {args.body_part!r} has a phrase bank but no ICD table in "
              f"app/generate/coding_tables.py — samples would carry no gold ICD code.")
        return 2

    samples = synth.generate_corpus(
        body_part=args.body_part, note_type=args.note_type, count=args.count,
        complexity=args.complexity, seed=args.seed, target_units=args.target_units,
    )

    if args.preview:
        for s in samples[:args.preview]:
            print("=" * 78)
            print(f"#{s.id}  {s.visit_type}  ({s.diagnosis})")
            print("-" * 78)
            print(s.transcript)
            print("-" * 78)
            print(f"  ICD      {list(s.icd_codes)}")
            for i in s.interventions:
                print(f"  CPT      {i.code} {i.label:<38} "
                      f"{'timed  ' if i.timed else 'untimed'} "
                      f"{str(i.minutes) + ' min' if i.minutes else '(no minutes)'}")
            for d in s.distractors:
                print(f"  ignore   {d.code} ({d.reason})")
            print(f"  TOTAL    {s.total_timed_minutes} timed min -> "
                  f"{s.expected_units} units CMS / {s.expected_units_ama} units AMA")
        return 0

    out = args.out or (DEFAULT_OUT_DIR / f"{args.body_part}_synth.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(s.to_record(), ensure_ascii=False) for s in samples) + "\n",
        encoding="utf-8",
    )

    units = {}
    for s in samples:
        units[s.expected_units] = units.get(s.expected_units, 0) + 1
    diverging = sum(1 for s in samples if s.expected_units != s.expected_units_ama)
    print(f"Wrote {len(samples)} samples to {out}")
    print(f"  ids           {samples[0].id}-{samples[-1].id}")
    print(f"  units (CMS)   " + ", ".join(f"{u}u x{n}" for u, n in sorted(units.items())))
    print(f"  CMS/AMA differ on {diverging} sample(s)")
    print(f"  distractors   {sum(len(s.distractors) for s in samples)} total")
    print("\nSynthetic data only — fictional patients, safe to commit (evals/data/README.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
