"""Thin wrapper isolating all google-api-python-client / google-auth usage. No
business logic here -- app.integrations.sheets_sync owns the reconciliation logic
and has zero Google imports, so it stays unit-testable without credentials.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column order is the sheet's contract -- row 1 is a header row matching this
# exactly. "id" must never be edited by hand; it's how rows are matched to local
# patients (never by row position -- PTs editing a shared sheet will sort/insert/
# delete rows). "last_edited" is stamped by an Apps Script onEdit trigger as a
# plain ISO-8601 UTC string (see docs/google-sheets-sync-setup.md) -- the app
# itself NEVER writes to this column, since overwriting it would destroy the only
# signal conflict resolution has for "a human edited this row, and when."
COLUMNS = ["id", "name", "dob", "mrn", "condition", "scheduling_notes", "last_edited"]
EDITABLE_COLUMNS = COLUMNS[:-1]  # everything except last_edited

INTEGRATIONS_DIR = Path(__file__).resolve().parent
CONFIG_PATH = INTEGRATIONS_DIR / "sheets_config.yaml"


@dataclass(frozen=True)
class SheetsConfig:
    spreadsheet_id: str
    sheet_name: str
    poll_interval_seconds: int
    credentials_path: str


def load_sheets_config() -> SheetsConfig | None:
    """Returns None (sync disabled) if config/credentials are absent or invalid --
    this must never crash app startup over a missing/malformed optional integration.
    """
    if not CONFIG_PATH.exists():
        return None
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        spreadsheet_id = raw["spreadsheet_id"]
        sheet_name = raw.get("sheet_name", "Patients")
        poll_interval_seconds = int(raw.get("poll_interval_seconds", 90))
        credentials_path = raw.get(
            "credentials_path", str(INTEGRATIONS_DIR / ".sheets_credentials.json")
        )
    except Exception:
        logger.exception("sheets_config.yaml present but invalid -- sync disabled")
        return None

    creds_file = Path(credentials_path)
    if not creds_file.is_absolute():
        creds_file = INTEGRATIONS_DIR.parent.parent / credentials_path
    if not creds_file.exists():
        logger.warning(
            "sheets_config.yaml found but credentials file %s is missing -- sync disabled",
            creds_file,
        )
        return None

    return SheetsConfig(
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name,
        poll_interval_seconds=poll_interval_seconds,
        credentials_path=str(creds_file),
    )


def _editable_row_values(patient_id, name, dob, mrn, condition, scheduling_notes) -> list[str]:
    return [patient_id, name or "", dob or "", mrn or "", condition or "", scheduling_notes or ""]


class SheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_id: str, sheet_name: str):
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self._svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._spreadsheet_id = spreadsheet_id
        self._sheet_name = sheet_name

    def fetch_all_rows(self) -> list[dict]:
        """Reads the full data range A2:G (everything below the header row),
        including last_edited. Each returned dict has one key per COLUMNS entry
        plus "row_number" (1-based, absolute sheet row -- valid only for the
        duration of this call; never cached, since rows shift if a PT inserts/
        deletes/reorders rows in the sheet).

        valueRenderOption=FORMATTED_VALUE is required -- the default
        (UNFORMATTED_VALUE) would silently turn DOB into a Sheets date serial
        number instead of the displayed "YYYY-MM-DD"-ish string. last_edited is
        stored by the Apps Script trigger as plain ISO-8601 text, so FORMATTED_VALUE
        returns it verbatim with no locale ambiguity either.
        """
        last_col = chr(ord("A") + len(COLUMNS) - 1)
        result = (
            self._svc.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._sheet_name}!A2:{last_col}",
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
        rows = result.get("values", [])
        out = []
        for i, row in enumerate(rows):
            padded = row + [None] * (len(COLUMNS) - len(row))
            entry = dict(zip(COLUMNS, (v if v != "" else None for v in padded)))
            entry["row_number"] = i + 2  # +2: 1-based, plus the header row
            out.append(entry)
        return out

    def append_patient_row(self, patient_id, name, dob, mrn, condition, scheduling_notes) -> None:
        """A brand-new local patient being pushed for the first time. Only writes
        columns A-F; leaves last_edited blank (no human has touched this row yet)."""
        last_col = chr(ord("A") + len(EDITABLE_COLUMNS) - 1)
        values = _editable_row_values(patient_id, name, dob, mrn, condition, scheduling_notes)
        self._svc.spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=f"{self._sheet_name}!A1:{last_col}1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        ).execute()

    def push_patient_row(self, row_number, patient_id, name, dob, mrn, condition, scheduling_notes) -> None:
        """Pushes local field values into an existing sheet row. Only ever writes
        columns A-F -- never touches last_edited (column G), since that's the only
        signal conflict resolution has for 'a human edited this row, and when.'"""
        last_col = chr(ord("A") + len(EDITABLE_COLUMNS) - 1)
        values = _editable_row_values(patient_id, name, dob, mrn, condition, scheduling_notes)
        self._svc.spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=f"{self._sheet_name}!A{row_number}:{last_col}{row_number}",
            valueInputOption="RAW",
            body={"values": [values]},
        ).execute()

    def batch_push_patient_rows(self, updates: dict[int, list[str]]) -> None:
        """updates: {row_number: [id, name, dob, mrn, condition, scheduling_notes]}."""
        if not updates:
            return
        last_col = chr(ord("A") + len(EDITABLE_COLUMNS) - 1)
        data = [
            {"range": f"{self._sheet_name}!A{row_number}:{last_col}{row_number}", "values": [values]}
            for row_number, values in updates.items()
        ]
        self._svc.spreadsheets().values().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

    def write_back_id(self, row_number: int, patient_id: str) -> None:
        """Fills in the id column (A) for a row a PT typed directly into the sheet
        with no id yet, after a new local patient has been created for it."""
        self._svc.spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=f"{self._sheet_name}!A{row_number}",
            valueInputOption="RAW",
            body={"values": [[patient_id]]},
        ).execute()
