"""Extracts the carry-forward snapshot fields from a just-saved note's own sections
(by heading match) and upserts app.storage.repository's single per-patient
carry_snapshots row. No second LLM call — the model emits headings from a fixed,
per-form spec (templates/*.md), so the same concept is always the same heading text
for a given form.

Not every carry-enabled form has a separately-extractable heading for every field —
e.g. soappt's precautions live inside its Subjective section rather than their own
heading, and discharge has no standalone Precautions/Functional Status headings at
all (it has "Functional Skills Assessment" instead, which is broader in scope and
deliberately NOT folded into functional_status — conflating the two would either
truncate discharge's broader content or pollute a short carry-forward line with it).
Fields with no matching heading for a given form are left None, which is the correct
outcome, not a bug.
"""

import re

from app.storage import repository

# Inline markers ([[NEEDS: ...]] gap/verify flags and [[CPT: ...]] code suggestions) must be
# stripped before a section body is stored as carry-forward context, or the marker would be
# rendered into the NEXT visit's prior-note prompt block and could be echoed. A section that is
# nothing but a marker cleans to None, which render_prior_block correctly omits.
_NEEDS_RE = re.compile(r"\s*\[\[(?:NEEDS|CPT):[^\]]*\]\]")
# The block-format templates put "[carry forward]" next to a field label as an instruction; if the
# model echoes it (or the [[CARRIED FORWARD]] output tag) into the value, strip it before storing.
_CARRY_MARKER_RE = re.compile(r"\s*\[\[?\s*carr(?:y|ied)[^\]]*\]\]?", re.IGNORECASE)


def _clean_carry_body(body: str) -> str | None:
    cleaned = _NEEDS_RE.sub("", body or "")
    cleaned = _CARRY_MARKER_RE.sub("", cleaned).strip()
    return cleaned or None

CARRY_FIELD_HEADING_MAP: dict[str, dict[str, list[str]]] = {
    "followup": {
        "precautions": ["precautions"],
        "functional_status": ["functional status"],
        "short_term_goals": ["short-term goals", "short term goals"],
        "long_term_goals": ["long-term goals", "long term goals"],
    },
}


def _find_labeled_value(sections: list[dict], substrings: list[str]) -> str | None:
    """Block-format fallback: the model routinely folds the whole note under one block (or single)
    heading instead of giving each field its own ## section, so a carry field shows up as a
    "Label: value" LINE inside a section body (e.g. "Functional Status: ambulates 200 ft..."). Find
    the first such line for any of `substrings`. Confirmed against real Follow-Up generations where
    the entire note parsed as a single section (see CLAUDE.md rule 13 on block-format output)."""
    if not substrings:
        return None
    alt = "|".join(re.escape(s) for s in substrings)
    pattern = re.compile(rf"(?im)^[ \t>*.\-\d]*(?:{alt})\s*:\s*(.+)$")
    for section in sections:
        m = pattern.search(section.get("body", ""))
        if m:
            value = _clean_carry_body(m.group(1))
            if value:
                return value
    return None


def extract_snapshot_fields(form_id: str, sections: list[dict]) -> dict[str, str | None]:
    field_map = CARRY_FIELD_HEADING_MAP.get(form_id)
    if field_map is None:
        return {}
    result: dict[str, str | None] = {field: None for field in field_map}
    # Pass 1 — the clean case: each carry field is its own ## section (match on heading).
    for section in sections:
        heading_lower = section["heading"].lower()
        for field, substrings in field_map.items():
            if result[field] is not None:
                continue
            if any(s in heading_lower for s in substrings):
                result[field] = _clean_carry_body(section["body"])
    # Pass 2 — block/flat output: any field not found as a heading is a "Label: value" body line.
    for field, substrings in field_map.items():
        if result[field] is None:
            result[field] = _find_labeled_value(sections, substrings)
    return result


def update_snapshot_after_save(
    patient_id: str, note_id: str, form_id: str, sections: list[dict]
) -> None:
    if form_id not in CARRY_FIELD_HEADING_MAP:
        return
    fields = extract_snapshot_fields(form_id, sections)
    repository.upsert_carry_snapshot(
        patient_id=patient_id,
        source_note_id=note_id,
        precautions=fields.get("precautions"),
        functional_status=fields.get("functional_status"),
        short_term_goals=fields.get("short_term_goals"),
        long_term_goals=fields.get("long_term_goals"),
    )


def rebuild_snapshot_after_delete(patient_id: str) -> None:
    """After a note is deleted, re-derive the patient's carry-forward snapshot from
    their most recent *remaining* carry-eligible note. If none remains, ensure no
    stale snapshot lingers. Idempotent when the deleted note wasn't the snapshot's
    source (it just recomputes the same snapshot), so it's safe to call after
    deleting any note. repository.list_notes returns newest-first, so the first
    carry-eligible hit is the correct new source."""
    for meta in repository.list_notes(patient_id):
        if meta["form_id"] in CARRY_FIELD_HEADING_MAP:
            note = repository.get_note(patient_id, meta["id"])
            if note is not None:
                update_snapshot_after_save(
                    patient_id, note["id"], note["form_id"], note["sections"]
                )
                return
    repository.delete_carry_snapshot(patient_id)
