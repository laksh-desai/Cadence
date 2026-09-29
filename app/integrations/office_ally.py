"""Office Ally settings the practice manages in Cadence's "Manage Office" tab.

Today that is one thing: which Office Ally SOAP layout each Cadence note type goes into, as the
layout's SoapLayoutID (the number in Office Ally's Add Note link, e.g.
`PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=374261&...`) and its name as shown in
Office Ally's "SOAP Note Layout" dropdown. SoapLayoutIDs are fixed per Office Ally account, so a
second practice — or a new layout for Re-evaluation or Discharge — is a settings change, not a
code change.

Cadence's "Send to Office Ally" button and the Chrome extension both read these values: the
button to open the right Add Note link, the extension to REFUSE filling a note into any other
layout (docs/OfficeAlly_Integration_Rules.md, rule 2.1).

No patient data here — layout ids and names only. Stored as JSON in the config folder, beside
the Sheets and Hugging Face settings.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from app.paths import INSTALL_DIR, config_dir

SETTINGS_FILENAME = "office_ally.json"

#: SDMPT's layouts (set by the practice 2026-09-28). Used until the practice saves its own.
DEFAULT_LAYOUTS: dict[str, dict[str, str]] = {
    "initial": {"id": "374261", "name": "Cadence Init Eval"},
    "initial_updated": {"id": "374261", "name": "Cadence Init Eval"},
    "followup": {"id": "361919", "name": "Progress Notes"},
}

_ID_RE = re.compile(r"^\d{1,12}$")
MAX_NAME = 80


def settings_path() -> Path:
    return config_dir(INSTALL_DIR / "app" / "integrations") / SETTINGS_FILENAME


def load_layouts() -> dict[str, dict[str, str]]:
    """The saved layouts, or the defaults when nothing has been saved (or the file is unreadable —
    a broken settings file must not stop notes from being sent; the defaults are the practice's
    known-good values)."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        layouts = data.get("layouts")
        if isinstance(layouts, dict):
            return {k: {"id": str(v.get("id", "")), "name": str(v.get("name", ""))}
                    for k, v in layouts.items() if isinstance(v, dict) and v.get("id")}
    except (OSError, ValueError, AttributeError):
        pass
    return {k: dict(v) for k, v in DEFAULT_LAYOUTS.items()}


class SettingsError(ValueError):
    pass


def validate_layouts(layouts: dict, known_form_ids: set[str]) -> dict[str, dict[str, str]]:
    """Clean what the Manage Office form sent. An empty id removes that note type's rule."""
    if not isinstance(layouts, dict):
        raise SettingsError("layouts must be an object")
    out: dict[str, dict[str, str]] = {}
    for form_id, row in layouts.items():
        if form_id not in known_form_ids:
            raise SettingsError(f"unknown note type: {form_id}")
        if not isinstance(row, dict):
            raise SettingsError(f"{form_id}: expected an id and a name")
        layout_id = str(row.get("id") or "").strip()
        name = " ".join(str(row.get("name") or "").split())
        if not layout_id:
            continue
        if not _ID_RE.match(layout_id):
            raise SettingsError(f"{form_id}: SoapLayoutID must be digits only, e.g. 374261")
        if not name:
            raise SettingsError(f"{form_id}: enter the layout name as Office Ally shows it")
        if len(name) > MAX_NAME:
            raise SettingsError(f"{form_id}: layout name is too long")
        out[form_id] = {"id": layout_id, "name": name}
    return out


def save_layouts(layouts: dict[str, dict[str, str]]) -> None:
    """Atomic write: a half-written settings file would silently fall back to the defaults."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".office_ally.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"layouts": layouts}, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
