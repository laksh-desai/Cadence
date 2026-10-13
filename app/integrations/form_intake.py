"""Google Form intake: dictation submitted from a phone through the practice's Google Form.

The HIPAA-friendly alternative to email. The clinician opens the practice's "Cadence dictation"
Google Form (restricted to @sdmobilept.com accounts) on their phone and submits:
  * Visit date (date question)
  * Note type (Daily Visit / Initial Evaluation / Re-evaluation / Discharge Summary)
  * Dictation (paragraph, optional) and/or Audio recording (file upload, optional)
Responses land in the form's linked Google Sheet; uploaded audio lands in the form owner's Google
Drive. All of that is Google Workspace (Forms, Sheets, Drive — BAA-covered). Cadence reads the
Sheet with the practice's service account, downloads any audio file to THIS computer, transcribes
it locally with MedASR, and queues the note for review exactly like email intake.

Cadence writes "Queued in Cadence <time>" into a "Cadence status" column so each response is used
once; a local state file (row ids and patient ids only, no dictation) covers the gap if that write
ever fails. Setup steps: docs/Intake_Setup_Guide.md.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app.paths import INSTALL_DIR, config_dir

SETTINGS_FILENAME = "form_intake.json"
STATE_FILENAME = "form_intake_state.json"
STATUS_HEADER = "Cadence status"
DEFAULT_SHEET_NAME = "Form Responses 1"
DEFAULT_POLL_SECONDS = 120
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.readonly"]
AUDIO_TYPES = (".wav", ".m4a", ".mp3", ".aac", ".ogg", ".webm", ".3gp", ".amr", ".flac", ".mp4")


class SettingsError(ValueError):
    pass


def _dir() -> Path:
    return config_dir(INSTALL_DIR / "app" / "integrations")


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    from app.integrations.email_intake import _atomic_write
    _atomic_write(path, data)


def default_credentials_path() -> str:
    """The service-account key the Sheets roster sync already uses, if present."""
    return str(_dir() / ".sheets_credentials.json")


def load_settings() -> dict:
    d = _read(_dir() / SETTINGS_FILENAME)
    return {
        "enabled": bool(d.get("enabled", False)),
        "spreadsheet_id": str(d.get("spreadsheet_id") or ""),
        "sheet_name": str(d.get("sheet_name") or DEFAULT_SHEET_NAME),
        "credentials_path": str(d.get("credentials_path") or default_credentials_path()),
        "allowed_domain": str(d.get("allowed_domain") or "sdmobilept.com").lower(),
        "poll_seconds": int(d.get("poll_seconds") or DEFAULT_POLL_SECONDS),
    }


def public_settings() -> dict:
    s = load_settings()
    return {**s, "credentials_found": Path(s["credentials_path"]).exists()}


_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")


def save_settings(body: dict) -> dict:
    if not isinstance(body, dict):
        raise SettingsError("expected an object")
    raw = str(body.get("spreadsheet_id") or "").strip()
    m = _SHEET_ID_RE.search(raw)
    sheet_id = m.group(1) if m else raw
    if sheet_id and not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sheet_id):
        raise SettingsError("paste the responses Sheet's link (or its ID)")
    poll = int(body.get("poll_seconds") or DEFAULT_POLL_SECONDS)
    if not 30 <= poll <= 3600:
        raise SettingsError("check interval must be between 30 and 3600 seconds")
    data = {
        "enabled": bool(body.get("enabled")),
        "spreadsheet_id": sheet_id,
        "sheet_name": str(body.get("sheet_name") or DEFAULT_SHEET_NAME).strip(),
        "credentials_path": str(body.get("credentials_path") or default_credentials_path()).strip(),
        "allowed_domain": str(body.get("allowed_domain") or "sdmobilept.com").strip().lower(),
        "poll_seconds": poll,
    }
    _write(_dir() / SETTINGS_FILENAME, data)
    return public_settings()


def load_state() -> dict:
    s = _read(_dir() / STATE_FILENAME)
    s.setdefault("processed", {})
    s.setdefault("last_check", None)
    s.setdefault("last_result", "")
    return s


def save_state(state: dict) -> None:
    _write(_dir() / STATE_FILENAME, state)


# --- reading responses ---------------------------------------------------------------------

@dataclass
class FormRow:
    row_number: int            # 1-based sheet row
    item_id: str               # stable id: row number + timestamp
    submitted: date | None
    submitter: str
    visit_date_text: str
    note_type: str
    dictation: str             # typed text, plus the local transcript of any audio
    status: str


def _col(headers: list[str], *needles: str) -> int | None:
    for i, h in enumerate(headers):
        hl = h.strip().lower()
        if any(n in hl for n in needles):
            return i
    return None


def _services():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    s = load_settings()
    creds = service_account.Credentials.from_service_account_file(s["credentials_path"], scopes=SCOPES)
    return (build("sheets", "v4", credentials=creds, cache_discovery=False),
            build("drive", "v3", credentials=creds, cache_discovery=False), s)


def _parse_timestamp(text: str) -> date | None:
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


_DRIVE_ID_RE = re.compile(r"(?:id=|/d/)([A-Za-z0-9_-]{20,})")


def fetch_rows() -> list[FormRow]:
    """New responses (empty "Cadence status"), with any uploaded audio transcribed locally."""
    sheets, drive, s = _services()
    rng = f"'{s['sheet_name']}'"
    values = sheets.spreadsheets().values().get(spreadsheetId=s["spreadsheet_id"], range=rng).execute()
    rows = values.get("values", [])
    if not rows:
        return []
    headers = rows[0]
    if STATUS_HEADER not in headers:
        _set_cell(sheets, s, 1, len(headers), STATUS_HEADER)
        headers = headers + [STATUS_HEADER]
    c_ts = _col(headers, "timestamp")
    c_email = _col(headers, "email address", "email")
    c_visit = _col(headers, "visit date", "date of service", "visit")
    c_type = _col(headers, "note type", "type")
    c_text = _col(headers, "dictation", "note text", "notes")
    c_audio = _col(headers, "audio", "recording", "voice")
    c_status = headers.index(STATUS_HEADER)
    out = []
    for i, r in enumerate(rows[1:], start=2):
        def cell(c):
            return r[c].strip() if c is not None and c < len(r) else ""
        if cell(c_status):
            continue
        text = cell(c_text)
        audio = cell(c_audio)
        if audio:
            transcript = _transcribe_links(drive, audio)
            text = (text + "\n\n" + transcript).strip() if transcript else text
        ts = cell(c_ts)
        out.append(FormRow(row_number=i, item_id=f"row{i}:{ts}", submitted=_parse_timestamp(ts),
                           submitter=cell(c_email), visit_date_text=cell(c_visit),
                           note_type=cell(c_type), dictation=text, status=""))
    return out


def _transcribe_links(drive, cell_text: str) -> str:
    """Download each uploaded audio file (Drive links in the cell) to a temp file, transcribe it
    with the local MedASR model, and delete the file. The audio never goes anywhere but this PC."""
    from googleapiclient.http import MediaIoBaseDownload
    from app.transcribe import medasr_client
    parts = []
    for file_id in _DRIVE_ID_RE.findall(cell_text):
        meta = drive.files().get(fileId=file_id, fields="name,mimeType").execute()
        suffix = Path(meta.get("name", "")).suffix.lower() or ".m4a"
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        # In memory only — the audio is never written to disk on this computer either.
        try:
            parts.append(medasr_client.transcribe(buf.getvalue()))
        except Exception:  # noqa: BLE001 - say so in the dictation rather than lose the visit
            parts.append(f"[[NEEDS: the uploaded recording ({suffix}) could not be transcribed — "
                         "type the dictation or upload it as WAV/MP3]]")
    return "\n\n".join(p for p in parts if p)


def _set_cell(sheets, s, row: int, col0: int, value: str) -> None:
    a1 = f"'{s['sheet_name']}'!{_col_letter(col0)}{row}"
    sheets.spreadsheets().values().update(spreadsheetId=s["spreadsheet_id"], range=a1,
                                          valueInputOption="RAW", body={"values": [[value]]}).execute()


def _col_letter(idx0: int) -> str:
    n, out = idx0 + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def write_status(marks: dict[int, str]) -> None:
    sheets, _, s = _services()
    values = sheets.spreadsheets().values().get(spreadsheetId=s["spreadsheet_id"],
                                                range=f"'{s['sheet_name']}'!1:1").execute()
    headers = (values.get("values") or [[]])[0]
    col = headers.index(STATUS_HEADER) if STATUS_HEADER in headers else len(headers)
    for row, text in marks.items():
        _set_cell(sheets, s, row, col, text)


def test_access() -> str:
    """'' when the Sheet can be read, otherwise what to fix."""
    s = load_settings()
    if not Path(s["credentials_path"]).exists():
        return ("No Google service-account key found. Follow docs/Intake_Setup_Guide.md step 2, or "
                "use email intake instead.")
    try:
        sheets, _, s = _services()
        sheets.spreadsheets().values().get(spreadsheetId=s["spreadsheet_id"],
                                           range=f"'{s['sheet_name']}'!1:1").execute()
        return ""
    except Exception as e:  # noqa: BLE001
        return explain_error(e)


def explain_error(e: Exception) -> str:
    msg = str(e)
    if "403" in msg or "PERMISSION_DENIED" in msg or "does not have permission" in msg:
        return ("Google refused access — share the responses Sheet (and the form's upload folder) "
                "with the service account's email as Editor / Viewer, and enable the Sheets and Drive "
                "APIs for its Cloud project.")
    if "404" in msg or "not found" in msg.lower():
        return "Sheet not found — check the link and the tab name (normally 'Form Responses 1')."
    if "Unable to parse range" in msg:
        return "Tab not found — the responses tab is normally called 'Form Responses 1'."
    return e.__class__.__name__ + ": " + msg[:160]


def sender_ok(row: FormRow) -> bool:
    """The form should collect the respondent's email (Settings → Responses → Collect email
    addresses: Verified) and be restricted to the practice domain. If it collects none, the
    domain restriction on the form itself is the control."""
    if not row.submitter:
        return True
    domain = load_settings()["allowed_domain"]
    return row.submitter.lower().rsplit("@", 1)[-1] == domain


def form_for_choice(choice: str) -> str:
    c = (choice or "").lower()
    if "discharge" in c:
        return "discharge"
    if "re-eval" in c or "reeval" in c or "progress" in c:
        return "reeval"
    if "initial" in c or c.strip() in ("evaluation", "eval"):
        return "initial"
    return "followup"
