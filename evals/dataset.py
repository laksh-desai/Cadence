"""Loader for the synthetic transcript corpus.

The corpus arrives as several JSONL files with a slightly inconsistent schema: every record
has id / patient_name / diagnosis / visit_type / date / transcript, and SOME also carry
`cpt_codes` (a list of {code, description} objects). This module reads them all into one
normalized list, defaults the missing `cpt_codes` to an empty tuple, and derives the Cadence
`form_id` each record should be generated against.

SYNTHETIC DATA ONLY. These are fictional patients with no real PHI (see evals/data/README.md).
Nothing here touches app/storage — the eval path deliberately bypasses the encrypted database
so a sweep can never write synthetic patients into the clinician's real record store.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# Assigned when visit_type doesn't clearly indicate an evaluation or a follow-up. Deliberately
# a loud sentinel rather than a silent default: scoring a record against the wrong template
# would produce structural failures that look like model defects but are harness bugs.
UNMAPPED = "UNMAPPED"

REQUIRED_FIELDS = ("id", "patient_name", "diagnosis", "visit_type", "date", "transcript")

# visit_type -> form_id. Checked in order; first hit wins, so the more specific patterns
# ("re-evaluation" is still an evaluation) come before the generic ones.
_FORM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:initial|intake|new[ -]patient)\b", re.I), "initial"),
    (re.compile(r"\b(?:re-?eval|evaluation|assessment)\b", re.I), "initial"),
    (re.compile(r"\b(?:follow[ -]?up|f/u|progress|interim|treatment|re-?check)\b", re.I), "followup"),
]


def form_id_for_visit_type(visit_type: str) -> str:
    """Map a free-text visit_type onto one of the loaded built-in forms.

    Evaluations map to `initial` (field-per-section) rather than `initial_updated` (the one
    remaining block-format template) because block output folds the note under a single
    heading, which suppresses the per-treatment CPT chips this harness scores — see
    CLAUDE.md "Block-format vs field-per-section". Run `--form initial_updated` to compare
    the two deliberately.
    """
    for pattern, form_id in _FORM_PATTERNS:
        if pattern.search(visit_type or ""):
            return form_id
    return UNMAPPED


@dataclass(frozen=True)
class EvalRecord:
    id: int
    patient_name: str
    diagnosis: str
    visit_type: str
    date: str
    transcript: str
    form_id: str
    source_file: str
    # Gold-label CPT codes, normalized to bare code strings ("97110"). The dataset's
    # descriptions are kept separately and are NOT compared against Cadence's own labels —
    # they're differently worded for the same code, so only the codes are scored.
    cpt_codes: tuple[str, ...] = ()
    cpt_descriptions: dict[str, str] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.transcript.split())


class DatasetError(Exception):
    """A corpus file is missing, empty, or malformed — always a harness/data problem."""


def _normalize_cpt(raw) -> tuple[tuple[str, ...], dict[str, str]]:
    """Accept the documented [{"code": "97110", "description": "..."}] shape, and tolerate a
    bare list of code strings, since the corpus schema is already known to be inconsistent."""
    codes: list[str] = []
    descriptions: dict[str, str] = {}
    for item in raw or ():
        if isinstance(item, dict):
            code = str(item.get("code", "")).strip()
            if code:
                descriptions[code] = str(item.get("description", "")).strip()
        else:
            code = str(item).strip()
        if code and code not in codes:
            codes.append(code)
    return tuple(codes), descriptions


def parse_record(obj: dict, source_file: str) -> EvalRecord:
    missing = [f for f in REQUIRED_FIELDS if f not in obj]
    if missing:
        raise DatasetError(f"{source_file}: record is missing required field(s) {missing}")
    codes, descriptions = _normalize_cpt(obj.get("cpt_codes"))
    visit_type = str(obj["visit_type"])
    return EvalRecord(
        id=int(obj["id"]),
        patient_name=str(obj["patient_name"]),
        diagnosis=str(obj["diagnosis"]),
        visit_type=visit_type,
        date=str(obj["date"]),
        transcript=str(obj["transcript"]),
        form_id=form_id_for_visit_type(visit_type),
        source_file=source_file,
        cpt_codes=codes,
        cpt_descriptions=descriptions,
    )


def load_file(path: Path) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue  # blank lines are tolerated; JSONL files often end with one
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise DatasetError(f"{path.name}:{lineno}: not valid JSON — {e}") from e
        records.append(parse_record(obj, path.name))
    return records


def load_corpus(data_dir: Path | None = None) -> list[EvalRecord]:
    """Read every *.jsonl under data_dir into one normalized list, sorted by record id.

    Ids are checked for uniqueness ACROSS files — the three files number their records
    independently, so a collision would silently make two records indistinguishable in the
    per-record run output.
    """
    directory = data_dir or DATA_DIR
    if not directory.exists():
        raise DatasetError(
            f"No corpus directory at {directory}. Put the synthetic JSONL files there "
            "(see evals/data/README.md)."
        )
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        raise DatasetError(
            f"No .jsonl files found in {directory}. Put the synthetic corpus files there "
            "(see evals/data/README.md)."
        )
    records: list[EvalRecord] = []
    for path in paths:
        records.extend(load_file(path))

    seen: dict[int, str] = {}
    for r in records:
        if r.id in seen:
            raise DatasetError(
                f"duplicate record id {r.id} in {r.source_file} (already seen in {seen[r.id]}) — "
                "ids must be unique across all corpus files"
            )
        seen[r.id] = r.source_file
    return sorted(records, key=lambda r: r.id)


def select(
    records: list[EvalRecord],
    *,
    form: str | None = None,
    ids: list[int] | None = None,
    limit: int | None = None,
) -> list[EvalRecord]:
    """Filter a loaded corpus for a run. `form` FILTERS by the record's derived form here;
    overriding which template a record is generated against is a separate concern handled by
    the runner, so that `--form` can serve both roles without this function guessing."""
    out = records
    if ids:
        wanted = set(ids)
        out = [r for r in out if r.id in wanted]
    if form:
        out = [r for r in out if r.form_id == form]
    if limit is not None:
        out = out[:limit]
    return out


def summarize(records: list[EvalRecord]) -> str:
    by_form: dict[str, int] = {}
    with_codes = 0
    for r in records:
        by_form[r.form_id] = by_form.get(r.form_id, 0) + 1
        if r.cpt_codes:
            with_codes += 1
    words = [r.word_count for r in records] or [0]
    parts = [f"{len(records)} records"]
    parts.append("forms: " + ", ".join(f"{k}={v}" for k, v in sorted(by_form.items())))
    parts.append(f"{with_codes} with gold CPT codes")
    parts.append(f"transcript words: min {min(words)} / median {sorted(words)[len(words) // 2]} / max {max(words)}")
    return " | ".join(parts)
