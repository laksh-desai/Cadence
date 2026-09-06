"""Preflight the Google Sheets roster sync and say exactly which setup step is unfinished.

Sheets sync is code-complete and unit-tested but has never run for real — it is blocked on Google
Cloud project permissions, which is an account problem, not a code one. That blocker will clear on
someone else's schedule, and when it does the person finishing the setup will be following an
eight-step doc through two Google consoles with, until now, exactly one signal available to them:
the Status page saying "Configured", which only means a YAML file exists. Every actual failure —
API not enabled, Sheet not shared with the service account, wrong tab name, wrong header row —
looks identical from there, and surfaces as a stack trace in a log during a background poll.

This runs the same calls the sync does, in the order the setup doc builds them up, and stops at
the first failure with the step that caused it. Read-only: it never writes to the Sheet.

    python scripts/verify_sheets.py

A companion to verify_pipeline.py (generation) and verify_transcription.py (MedASR): one script
per integration, each answering "is this actually working on THIS machine".

PHI note: the roster Sheet is the ONE sanctioned destination for patient data outside this device,
and only under the practice's Google Workspace business account, which the BAA covers. This script
checks WHICH account owns the credentials and warns if it does not look like a Workspace service
account, because a personal Gmail is not covered — see CLAUDE.md's non-negotiable constraints.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.integrations.sheets_client import (  # noqa: E402
    COLUMNS, CONFIG_PATH, INTEGRATIONS_DIR, SheetsClient, load_sheets_config,
)

OK, BAD, WARN = "  OK  ", " FAIL ", " WARN "


def _say(status: str, step: str, detail: str = "") -> None:
    print(f"[{status}] {step}" + (f"\n         {detail}" if detail else ""))


def _fail(step: str, detail: str, fix: str) -> int:
    _say(BAD, step, detail)
    print(f"\n  -> {fix}")
    print("     Full walkthrough: docs/google-sheets-sync-setup.md")
    return 1


def main() -> int:
    print("Google Sheets roster sync — preflight\n")

    # 1. config file
    if not CONFIG_PATH.exists():
        return _fail("sheets_config.yaml", f"not found at {CONFIG_PATH}",
                     f"Copy {INTEGRATIONS_DIR / 'sheets_config.example.yaml'} to "
                     f"{CONFIG_PATH.name} and fill in the spreadsheet id (step 5 of the doc).")
    config = load_sheets_config()
    if config is None:
        return _fail("sheets_config.yaml", "present but unusable (invalid YAML, missing "
                     "spreadsheet_id, or the credentials file it points at does not exist)",
                     "Check spreadsheet_id is set and that "
                     f"{INTEGRATIONS_DIR / '.sheets_credentials.json'} exists (steps 3 and 5).")
    _say(OK, "sheets_config.yaml", f"sheet '{config.sheet_name}', poll every "
                                   f"{config.poll_interval_seconds}s")

    # 2. credentials file — read it directly so we can name the service account
    try:
        creds = json.loads(Path(config.credentials_path).read_text(encoding="utf-8"))
        sa_email = creds.get("client_email", "")
        if creds.get("type") != "service_account" or not sa_email:
            raise ValueError("not a service-account key")
    except Exception as e:  # noqa: BLE001
        return _fail("service-account key", f"{config.credentials_path}: {e}",
                     "Download a JSON key for the service account and save it as "
                     ".sheets_credentials.json (step 2/3). An OAuth *client* JSON is a different "
                     "file and will not work.")
    _say(OK, "service-account key", sa_email)
    if sa_email.endswith(".iam.gserviceaccount.com"):
        _say(WARN, "BAA check",
             "Confirm this service account lives in a Cloud project owned by the practice's "
             "Google WORKSPACE account. A project under a personal Gmail is NOT covered by the "
             "BAA, and the roster contains patient data.")

    # 3. the API call the sync actually makes
    try:
        client = SheetsClient(config.credentials_path, config.spreadsheet_id, config.sheet_name)
        rows = client.fetch_all_rows()
    except Exception as e:  # noqa: BLE001
        text = str(e)
        if "has not been used" in text or "SERVICE_DISABLED" in text or "accessNotConfigured" in text:
            return _fail("read the Sheet", text[:300],
                         "Enable the Google Sheets API in this Cloud project "
                         "(APIs & Services -> Library -> Google Sheets API -> Enable), step 1.")
        if "403" in text or "PERMISSION_DENIED" in text:
            return _fail("read the Sheet", text[:300],
                         f"Share the Sheet with {sa_email} as an Editor (step 4). A service "
                         "account cannot see a Sheet nobody shared with it.")
        if "404" in text or "notFound" in text:
            return _fail("read the Sheet", text[:300],
                         "The spreadsheet_id in sheets_config.yaml does not resolve. It is the "
                         "long id in the Sheet's URL between /d/ and /edit (step 5).")
        if "Unable to parse range" in text:
            return _fail("read the Sheet", text[:300],
                         f"No tab named '{config.sheet_name}' in that spreadsheet. Rename the tab "
                         "or change sheet_name in sheets_config.yaml (step 4).")
        return _fail("read the Sheet", text[:300],
                     "Unrecognised error — the message above is Google's. Re-check steps 1-5.")
    _say(OK, "read the Sheet", f"{len(rows)} data row(s) found")

    # 4. header row — a wrong header silently maps columns to the wrong fields
    if rows:
        present = [c for c in COLUMNS if c in rows[0]]
        if len(present) != len(COLUMNS):
            return _fail("header row", f"expected {COLUMNS}, parsed {sorted(rows[0])}",
                         "Row 1 must hold these exact column names in this exact order, A-G "
                         "(step 4). A mismatch writes patient data into the wrong columns.")
        _say(OK, "header row", " | ".join(COLUMNS))
    else:
        _say(WARN, "header row", "the Sheet has no data rows yet, so the column mapping is "
                                 "unverified. Re-run after the first sync.")

    print("\nSync is ready. Start Cadence and the roster will sync every "
          f"{config.poll_interval_seconds}s; the Status page will show it as Configured.")
    print("Nothing was written to the Sheet by this check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
