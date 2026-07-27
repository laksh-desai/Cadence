"""Reconciliation logic for the bidirectional patient-roster sync. Zero Google
imports here on purpose -- reconcile_one() must stay unit-testable on plain dicts,
with no credentials or network involved (see tests/test_sheets_sync.py).

Invariant, enforced structurally rather than checked at runtime: a local patient is
NEVER deleted because of anything observed in the sheet. A repository.delete_patient
does now exist, but it is reachable ONLY from an explicit, confirmed user action in
the UI (DELETE /api/patients/{id}) -- nothing in this file calls it, and nothing
here ever should. A local patient missing from the current sheet snapshot is treated
purely as "never pushed yet" and gets (re-)pushed -- never as a delete signal. Do not
add a delete path here without re-reading why this matters: a PT accidentally
deleting a row in a shared spreadsheet must never be able to destroy a patient's
clinical history.

(Corollary of the above: a patient deleted locally via the UI leaves an orphaned row
in the sheet. That row is inert -- it keeps its id, so it is never re-pulled as a new
patient, and with no local patient to reconcile against it is simply ignored on every
subsequent cycle. Removing it from the sheet, if desired, is a manual step.)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("could not parse timestamp %r -- treating as unset", value)
        return None


@dataclass(frozen=True)
class Action:
    kind: str  # "noop" | "push" | "append" | "pull"
    timestamp: str | None = None  # the winning/reconciled timestamp, ISO string
    is_conflict: bool = False


def reconcile_one(local: dict, sheet: dict | None) -> Action:
    """local: needs at least updated_at and sheet_synced_at.
    sheet: the matching sheet row dict (needs last_edited), or None if this patient
    has no row in the sheet at all yet.
    """
    if sheet is None:
        return Action(kind="append", timestamp=local.get("updated_at"))

    local_ts = _parse_ts(local.get("updated_at"))
    synced_ts = _parse_ts(local.get("sheet_synced_at"))
    sheet_ts = _parse_ts(sheet.get("last_edited"))

    # A blank last_edited (e.g. a row we just appended ourselves, which the Apps
    # Script onEdit trigger never saw since it wasn't a UI edit) must never look
    # like a sheet-side change -- that's what `sheet_ts is not None` guards against.
    sheet_changed = sheet_ts is not None and (synced_ts is None or sheet_ts > synced_ts)
    local_changed = synced_ts is None or (local_ts is not None and local_ts > synced_ts)

    if not sheet_changed and not local_changed:
        return Action(kind="noop")
    if local_changed and not sheet_changed:
        return Action(kind="push", timestamp=local.get("updated_at"))
    if sheet_changed and not local_changed:
        return Action(kind="pull", timestamp=sheet.get("last_edited"))

    # Both changed since the last reconciliation -- most-recent-edit wins.
    if sheet_ts is not None and local_ts is not None and sheet_ts > local_ts:
        return Action(kind="pull", timestamp=sheet.get("last_edited"), is_conflict=True)
    return Action(kind="push", timestamp=local.get("updated_at"), is_conflict=True)


def run_sync_cycle(client) -> dict:
    """One full poll-and-reconcile pass against the live Sheets API. Synchronous
    on purpose -- the caller (app/ui/server.py's background loop) is responsible
    for running this via asyncio.to_thread, since google-api-python-client's HTTP
    calls are blocking and must never run directly on the FastAPI event loop.
    """
    from app.storage import db, repository

    pushed = pulled = conflicts = new_from_sheet = 0
    errors: list[str] = []

    try:
        sheet_rows = client.fetch_all_rows()
    except Exception as e:
        logger.exception("sheets fetch_all_rows failed")
        return {
            "pushed": 0, "pulled": 0, "conflicts_resolved": 0, "new_from_sheet": 0,
            "errors": [f"could not read the sheet: {e}"],
        }

    sheet_by_id = {r["id"]: r for r in sheet_rows if r.get("id")}
    no_id_rows = [r for r in sheet_rows if not r.get("id")]
    local_by_id = {p["id"]: p for p in repository.list_patients_for_sync()}

    # 1. Brand-new rows a PT typed directly into the sheet, with no id yet.
    for row in no_id_rows:
        if not row.get("name"):
            continue  # a genuinely blank row (trailing empty rows); nothing to create
        try:
            created = repository.upsert_patient_from_sheet(
                patient_id=None,
                name=row.get("name"), dob=row.get("dob"), mrn=row.get("mrn"),
                condition=row.get("condition"), scheduling_notes=row.get("scheduling_notes"),
                sheet_updated_at=row.get("last_edited") or _now_iso(),
            )
            client.write_back_id(row["row_number"], created["id"])
            new_from_sheet += 1
        except Exception as e:
            logger.exception("failed to create local patient from new sheet row")
            errors.append(f"new sheet row at row {row.get('row_number')}: {e}")

    # 2. Reconcile every local patient against its matching sheet row, if any.
    pending_pushes: dict[int, list[str]] = {}
    for patient_id, local in local_by_id.items():
        sheet_row = sheet_by_id.get(patient_id)
        action = reconcile_one(local, sheet_row)
        try:
            if action.kind == "noop":
                continue

            elif action.kind == "append":
                client.append_patient_row(
                    patient_id, local["name"], local["dob"], local["mrn"],
                    local["condition"], local["scheduling_notes"],
                )
                repository.mark_synced(patient_id, action.timestamp or _now_iso())
                pushed += 1

            elif action.kind == "push":
                pending_pushes[sheet_row["row_number"]] = [
                    patient_id, local["name"] or "", local["dob"] or "",
                    local["mrn"] or "", local["condition"] or "", local["scheduling_notes"] or "",
                ]
                repository.mark_synced(patient_id, action.timestamp or _now_iso())
                pushed += 1
                if action.is_conflict:
                    conflicts += 1

            elif action.kind == "pull":
                repository.upsert_patient_from_sheet(
                    patient_id=patient_id,
                    name=sheet_row.get("name") or local["name"], dob=sheet_row.get("dob"),
                    mrn=sheet_row.get("mrn"), condition=sheet_row.get("condition"),
                    scheduling_notes=sheet_row.get("scheduling_notes"),
                    sheet_updated_at=action.timestamp or _now_iso(),
                )
                pulled += 1
                if action.is_conflict:
                    conflicts += 1
        except Exception as e:
            logger.exception("failed to reconcile patient %s", patient_id)
            errors.append(f"patient {patient_id}: {e}")

    if pending_pushes:
        try:
            client.batch_push_patient_rows(pending_pushes)
        except Exception as e:
            logger.exception("batch sheet push failed")
            errors.append(f"batch sheet write: {e}")

    db.persist()
    return {
        "pushed": pushed, "pulled": pulled, "conflicts_resolved": conflicts,
        "new_from_sheet": new_from_sheet, "errors": errors,
    }
