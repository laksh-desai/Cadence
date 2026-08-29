# Google Sheets roster sync — one-time setup

This connects Cadence's patient roster to a Google Sheet so other physical
therapists at the practice can view and edit it without using the Cadence app
directly. Only roster fields sync (name, DOB, MRN, condition, scheduling notes) —
clinical note content never leaves the app. This is covered by the practice's
existing Business Associate Agreement with Google under its **Workspace business
account** — see CLAUDE.md's non-negotiable constraints for why that distinction
matters. Do every step below signed into that Workspace account, not a personal
Gmail.

You don't need to write any code for this — it's all clicking through Google's
consoles, plus pasting one small script once.

## 1. Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com), signed into
   the practice's Workspace account.
2. Create a new project (any name, e.g. "Cadence Sync").
3. In that project: **APIs & Services → Library** → search "Google Sheets API" →
   **Enable**.

## 2. Create a service account

A service account is a robot identity Cadence uses to talk to Sheets — it has its
own email address and isn't tied to any one person's personal account.

1. **APIs & Services → Credentials → Create Credentials → Service Account.**
2. Name it (e.g. "cadence-sync"). No project-level IAM roles are needed — access is
   granted per-Sheet in step 4, not at the project level. Click **Done**.
3. Click into the new service account → **Keys** tab → **Add Key → Create new key →
   JSON**. This downloads a file like `cadence-sync-xxxxx.json`. Keep it safe —
   whoever holds this file can read/write that Sheet.

## 3. Install the key in Cadence

Move the downloaded file into the project and rename it exactly to:

```
app/integrations/.sheets_credentials.json
```

(The leading dot matters — it's already in `.gitignore`, same as the database
encryption key.)

## 4. Create the Sheet and share it

1. Create a new Google Sheet (or pick an existing one) under the Workspace account.
2. In row 1, enter this header exactly, one per column A–G:

   ```
   id | name | dob | mrn | condition | scheduling_notes | last_edited
   ```

3. Click **Share**, paste the service account's email address — it's the
   `client_email` field inside the JSON file you downloaded, looks like
   `cadence-sync@your-project-123456.iam.gserviceaccount.com` — set its role to
   **Editor**, uncheck "Notify people" (it's a robot), and send.
4. Copy the Sheet's ID from its URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`

## 5. Add the "last edited" trigger

This is the one script-paste step. It stamps column G with a timestamp whenever a
person edits a row — Cadence uses this to know which side (the app or the Sheet)
was changed more recently if the same patient was edited in both places.

1. In the Sheet: **Extensions → Apps Script.**
2. Delete whatever's in the editor and paste:

   ```javascript
   function onEdit(e) {
     var sheet = e.range.getSheet();
     var lastEditedCol = 7; // column G
     if (e.range.getColumn() === lastEditedCol) return; // don't re-trigger on our own stamp
     if (e.range.getRow() === 1) return; // ignore header row edits
     sheet.getRange(e.range.getRow(), lastEditedCol).setValue(new Date().toISOString());
   }
   ```

3. **File → Save** (name the project anything, e.g. "Cadence Last-Edited Stamper").
   No need to run it manually or grant it any extra permissions — a simple trigger
   bound to this one sheet doesn't require that.

## 6. Configure Cadence

Copy `app/integrations/sheets_config.example.yaml` to
`app/integrations/sheets_config.yaml` (same folder) and fill in the Sheet ID from
step 4:

```yaml
spreadsheet_id: "paste the ID from the Sheet's URL here"
sheet_name: "Patients"          # must match the actual tab name, case-sensitive
poll_interval_seconds: 90
credentials_path: "app/integrations/.sheets_credentials.json"
```

## 7. Restart and verify

Close and reopen Cadence (via the desktop shortcut). On startup it syncs once
immediately, then checks the Sheet every `poll_interval_seconds` after that. To
confirm it's working without waiting:

- `POST /api/sync/now` (or `http://127.0.0.1:8420/docs` → try it out) should return
  something like `{"pushed": 2, "pulled": 0, "conflicts_resolved": 0,
  "new_from_sheet": 0, "errors": []}` — any existing patients get pushed in on the
  first run.
- Open the Sheet — your existing patients should now appear, with `last_edited`
  blank (Cadence's own writes never trigger the human-edit stamp).
- Edit a cell directly in the Sheet (e.g. change a condition) — `last_edited`
  should fill in immediately. Within one poll interval (or after another manual
  sync), that change should show up back in the app.

## What never happens

- **Clinical note content is never synced**, in either direction — only the roster
  fields above.
- **Deleting a row in the Sheet never deletes a patient or their notes.** Cadence
  treats a missing row as "hasn't been pushed yet" and re-adds it on the next sync,
  not as an instruction to delete anything locally.
- **A personal Gmail account is never a valid target** for this integration — the
  BAA only covers the practice's Workspace business account. If you ever recreate
  this setup, do it signed into that account.

## If something looks wrong

**Run the preflight first — it names the failing step instead of making you guess:**

```
python scripts/verify_sheets.py
```

It walks the same calls the sync makes, in the order this doc builds them up, and stops at the
first failure with the fix for it: API not enabled, Sheet not shared with the service account,
wrong tab name, wrong header row, bad spreadsheet id. It is read-only and never writes to the
Sheet. The Status page inside the app can only tell you a config file *exists*, which every one of
those failures looks identical from.

- **Sync isn't running at all**: check that both `app/integrations/.sheets_credentials.json`
  and `app/integrations/sheets_config.yaml` exist. If either is missing, sync is
  silently disabled (by design — the app must work normally with zero Google setup)
  and `POST /api/sync/now` will return a 503 explaining why.
- **Edits in the Sheet aren't showing up in the app**: confirm the Apps Script
  trigger actually fired — edit a cell and check that `last_edited` updates within
  a second or two. If it doesn't, re-check step 5.
- **A patient looks duplicated or wrong after editing both places**: most-recent
  edit wins by timestamp. If your computer's or the Sheet locale's clock is wrong,
  the "most recent" comparison will be wrong too — check both.
