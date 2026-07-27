"""CRUD functions used by the API layer. Plain dicts in/out — no separate ORM model
layer; Pydantic models in app/ui/schemas.py are the only typed boundary, at the HTTP
edge. Callers are responsible for calling db.persist() once after a request's writes
are done (a save can touch both `notes` and `carry_snapshots` in one request; we only
want to re-encrypt once per request, not once per table write).
"""

import json
import re
import uuid
from datetime import datetime, timezone

from app.storage import db

# Sentinel distinguishing "field not provided" (leave unchanged) from an explicit
# `None` (clear this field) in update_patient's partial-update kwargs.
_UNSET = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def create_patient(
    name: str, dob: str | None, mrn: str | None, condition: str | None,
    scheduling_notes: str | None = None,
) -> dict:
    patient_id = _new_id("p")
    created_at = _now_iso()
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO patients (id, name, dob, mrn, condition, created_at, "
            "scheduling_notes, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (patient_id, name, dob, mrn, condition, created_at, scheduling_notes, created_at),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "id": patient_id, "name": name, "dob": dob, "mrn": mrn, "condition": condition,
        "scheduling_notes": scheduling_notes, "has_prior": False, "note_count": 0,
    }


def list_patients() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.dob, p.mrn, p.condition, p.scheduling_notes,
                   (SELECT COUNT(*) FROM notes n WHERE n.patient_id = p.id) AS note_count,
                   (SELECT COUNT(*) FROM carry_snapshots c WHERE c.patient_id = p.id) AS has_prior
            FROM patients p ORDER BY p.created_at ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"], "name": r["name"], "dob": r["dob"], "mrn": r["mrn"],
            "condition": r["condition"], "scheduling_notes": r["scheduling_notes"],
            "has_prior": bool(r["has_prior"]), "note_count": r["note_count"],
        }
        for r in rows
    ]


def get_patient(patient_id: str) -> dict | None:
    conn = db.get_connection()
    try:
        r = conn.execute(
            """
            SELECT p.id, p.name, p.dob, p.mrn, p.condition, p.scheduling_notes,
                   (SELECT COUNT(*) FROM notes n WHERE n.patient_id = p.id) AS note_count,
                   (SELECT COUNT(*) FROM carry_snapshots c WHERE c.patient_id = p.id) AS has_prior
            FROM patients p WHERE p.id = ?
            """,
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    if r is None:
        return None
    return {
        "id": r["id"], "name": r["name"], "dob": r["dob"], "mrn": r["mrn"],
        "condition": r["condition"], "scheduling_notes": r["scheduling_notes"],
        "has_prior": bool(r["has_prior"]), "note_count": r["note_count"],
    }


def update_patient(
    patient_id: str, *, name=_UNSET, dob=_UNSET, mrn=_UNSET, condition=_UNSET,
    scheduling_notes=_UNSET, updated_at: str | None = None,
) -> dict | None:
    """Partial update. Omitted kwargs (the _UNSET default) leave that column
    unchanged; passing None explicitly clears it. `updated_at` lets sync code stamp
    a specific pulled-from-sheet timestamp; omit it for local edits to stamp now."""
    fields = {
        "name": name, "dob": dob, "mrn": mrn, "condition": condition,
        "scheduling_notes": scheduling_notes,
    }
    provided = {k: v for k, v in fields.items() if v is not _UNSET}
    provided["updated_at"] = updated_at or _now_iso()

    conn = db.get_connection()
    try:
        existing = conn.execute("SELECT id FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if existing is None:
            return None
        set_clause = ", ".join(f"{col} = ?" for col in provided)
        conn.execute(
            f"UPDATE patients SET {set_clause} WHERE id = ?",
            (*provided.values(), patient_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_patient(patient_id)


def delete_patient(patient_id: str) -> bool:
    """Permanently delete a patient and ALL of their clinical data (saved notes and
    the carry-forward snapshot). Returns False if no such patient existed.

    This is only ever reached from an explicit, confirmed user action in the UI
    (DELETE /api/patients/{id}). The Sheets sync path must NEVER call this -- a
    patient vanishing from the shared spreadsheet is treated as "never pushed," not
    as a delete signal (see app/integrations/sheets_sync.py's module docstring).

    Foreign keys have no ON DELETE CASCADE and PRAGMA foreign_keys is ON, so the
    children are removed first, in dependency order (carry_snapshots references both
    patients and notes; notes references patients), all in one transaction.
    """
    conn = db.get_connection()
    try:
        existing = conn.execute("SELECT id FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if existing is None:
            return False
        conn.execute("DELETE FROM carry_snapshots WHERE patient_id = ?", (patient_id,))
        conn.execute("DELETE FROM notes WHERE patient_id = ?", (patient_id,))
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def delete_note(patient_id: str, note_id: str) -> bool:
    """Permanently delete one saved note. Returns False if no such note exists for
    this patient.

    carry_snapshots.source_note_id has a foreign key to notes(id) and PRAGMA
    foreign_keys is ON, so if this note is the current snapshot's source the snapshot
    must be cleared before the note row can be deleted. The caller is responsible for
    rebuilding the snapshot afterward from the most recent remaining carry-forward
    note (carry_forward.rebuild_snapshot_after_delete) -- kept out of here to avoid a
    repository -> carry_forward import cycle (carry_forward already imports this
    module).
    """
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM notes WHERE patient_id = ? AND id = ?", (patient_id, note_id)
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "DELETE FROM carry_snapshots WHERE patient_id = ? AND source_note_id = ?",
            (patient_id, note_id),
        )
        conn.execute("DELETE FROM notes WHERE patient_id = ? AND id = ?", (patient_id, note_id))
        conn.commit()
    finally:
        conn.close()
    return True


def delete_carry_snapshot(patient_id: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM carry_snapshots WHERE patient_id = ?", (patient_id,))
        conn.commit()
    finally:
        conn.close()


def list_patients_for_sync() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, dob, mrn, condition, scheduling_notes, updated_at, "
            "sheet_synced_at FROM patients"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def upsert_patient_from_sheet(
    patient_id: str | None, name: str, dob: str | None, mrn: str | None,
    condition: str | None, scheduling_notes: str | None, sheet_updated_at: str,
) -> dict:
    """A pull from the sheet. patient_id=None means this row had no id yet (a PT
    typed a brand-new row directly into the sheet) -- create a new local patient and
    return it (including the freshly generated id) so the caller can write that id
    back into the sheet. Otherwise, update the existing patient. Either way, both
    `updated_at` and `sheet_synced_at` are set to `sheet_updated_at` -- a pull means
    the two sides just agreed, so there's no drift between them to detect next time.
    """
    if patient_id is None:
        new_id = _new_id("p")
        conn = db.get_connection()
        try:
            conn.execute(
                "INSERT INTO patients (id, name, dob, mrn, condition, created_at, "
                "scheduling_notes, updated_at, sheet_synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id, name, dob, mrn, condition, sheet_updated_at,
                    scheduling_notes, sheet_updated_at, sheet_updated_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return get_patient(new_id)

    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE patients SET name = ?, dob = ?, mrn = ?, condition = ?, "
            "scheduling_notes = ?, updated_at = ?, sheet_synced_at = ? WHERE id = ?",
            (
                name, dob, mrn, condition, scheduling_notes, sheet_updated_at,
                sheet_updated_at, patient_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_patient(patient_id)


def mark_synced(patient_id: str, synced_at: str) -> None:
    """A push (local -> sheet) succeeded: advance sheet_synced_at without touching
    updated_at (the local edit's own timestamp is still the correct record of when
    it was last *changed*; this only records when it was last *agreed* with the sheet).
    """
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE patients SET sheet_synced_at = ? WHERE id = ?", (synced_at, patient_id)
        )
        conn.commit()
    finally:
        conn.close()


def create_note(
    patient_id: str, form_id: str, form_name: str, sections: list[dict],
    missing_info: list[str], dictation_raw: str, used_prior: bool,
) -> dict:
    note_id = _new_id("n")
    created_at = _now_iso()
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO notes (id, patient_id, form_id, form_name, created_at, "
            "sections_json, missing_json, dictation_raw, used_prior) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                note_id, patient_id, form_id, form_name, created_at,
                json.dumps(sections), json.dumps(missing_info), dictation_raw,
                1 if used_prior else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": note_id, "created_at": created_at}


def list_notes(patient_id: str) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, form_id, form_name, created_at, sections_json, missing_json "
            "FROM notes WHERE patient_id = ? ORDER BY created_at DESC",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        sections = json.loads(r["sections_json"])
        missing = json.loads(r["missing_json"])
        # First section with real content (after stripping the inline [[NEEDS]]/[[CPT]] markers),
        # so a section that is only a marker doesn't leave a blank or marker-filled snippet.
        snippet = ""
        for sec in sections:
            body = re.sub(r"\[\[(?:NEEDS|CPT):[^\]]*\]\]", "", sec.get("body", ""))
            body = re.sub(r"\s+", " ", body).strip()
            if body:
                snippet = body[:170]
                break
        out.append(
            {
                "id": r["id"], "form_id": r["form_id"], "form_name": r["form_name"],
                "created_at": r["created_at"], "missing_count": len(missing),
                "snippet": snippet,
            }
        )
    return out


def get_note(patient_id: str, note_id: str) -> dict | None:
    conn = db.get_connection()
    try:
        r = conn.execute(
            "SELECT id, form_id, form_name, created_at, sections_json, missing_json "
            "FROM notes WHERE patient_id = ? AND id = ?",
            (patient_id, note_id),
        ).fetchone()
    finally:
        conn.close()
    if r is None:
        return None
    return {
        "id": r["id"], "form_id": r["form_id"], "form_name": r["form_name"],
        "created_at": r["created_at"], "sections": json.loads(r["sections_json"]),
        "missing_info": json.loads(r["missing_json"]),
    }


def get_carry_snapshot(patient_id: str) -> dict | None:
    conn = db.get_connection()
    try:
        r = conn.execute(
            "SELECT precautions, functional_status, short_term_goals, long_term_goals "
            "FROM carry_snapshots WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    if r is None:
        return None
    return dict(r)


def upsert_carry_snapshot(
    patient_id: str, source_note_id: str, precautions: str | None,
    functional_status: str | None, short_term_goals: str | None, long_term_goals: str | None,
) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO carry_snapshots
                (patient_id, source_note_id, updated_at, precautions, functional_status,
                 short_term_goals, long_term_goals)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                source_note_id=excluded.source_note_id, updated_at=excluded.updated_at,
                precautions=excluded.precautions, functional_status=excluded.functional_status,
                short_term_goals=excluded.short_term_goals, long_term_goals=excluded.long_term_goals
            """,
            (
                patient_id, source_note_id, _now_iso(), precautions, functional_status,
                short_term_goals, long_term_goals,
            ),
        )
        conn.commit()
    finally:
        conn.close()
