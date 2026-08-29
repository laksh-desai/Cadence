# Shipping Cadence to another device

Cadence is not a single-file installer — it's a Python app plus two local model
services. "Shipping" means reproducing that environment on the target machine. This
doc is the exact, step-by-step procedure. Read the **Data & keys** section before
moving any real patient data.

Target assumption: **Windows 10/11 Pro**, same as development. The launcher and paths
(`\.venv\Scripts\`, `pythonw.exe`, `CREATE_NO_WINDOW`) are Windows-specific; a Mac/Linux
target would need `.venv/bin/` paths and a different launcher.

---

> **As of v1.0.0, read [`releasing.md`](releasing.md) first.** This document describes copying the
> project folder, which is still exactly right for a DEVELOPER moving their own checkout. But a
> CLINICIAN's machine should be installed from a release zip into the versioned layout
> (`C:\Cadence\versions\<v>\`, with the data in `C:\Cadence\data\`), because that is what lets it
> take an update later without stranding the patient database inside an old version folder.
> Everything below — prerequisites, models, the HF token, the HIPAA hardening — applies to both;
> only the folder you unzip into differs.

## What actually has to exist on the new machine

| Piece | Ships in the folder? | How it gets there |
|---|---|---|
| App source (`app/`, `templates/`, `docs/`, `launcher.py`, `requirements.txt`) | yes | copy the folder |
| Python 3.12 | no | install on the device |
| `.venv/` (virtualenv + all deps incl. CPU torch) | no (gitignored, machine-specific) | rebuild from `requirements.txt` |
| Ollama + MedGemma 4B model | no | install Ollama, pull the model |
| MedASR model (~400 MB) | no | auto-downloads on first run from the HF token |
| `app/transcribe/hf_config.yaml` (HF token) | no (gitignored) | create from the `.example` file |
| `app/integrations/sheets_config.yaml` + creds *(optional)* | no (gitignored) | create only if using Sheets sync |
| `app/storage/.keyfile` + `cadence.db.enc` (encrypted patient data) | no (gitignored) | **fresh device: auto-created empty.** **Migrating data: copy both, securely — see below** |

The `.venv` is deliberately **not** copied between machines — virtualenvs hard-code
absolute paths and platform-specific binaries. Always rebuild it on the target.

---

## A. Fresh install (new device, no existing patient data)

> **Shortcut:** `setup.ps1` (project root) automates steps **4–9** — venv + dependencies,
> the Ollama model pulls, the HF token, the performance env vars, and the desktop shortcut,
> then runs a quick verify. Do the manual prerequisites first (steps 1–3: Python, copy the
> folder, install Ollama), then run `powershell -ExecutionPolicy Bypass -File .\setup.ps1`,
> then do step 10 (device hardening). It's idempotent and never touches existing data. The
> manual steps below remain the reference for what it does.

### 1. Prerequisites
- Windows 10/11 **Pro** (Pro is needed for BitLocker later).
- **~40 GB free disk.** Models + toolchain are large.
- An internet connection for the one-time downloads (steps 4–6). The app runs offline
  afterward.
- Administrator access for BitLocker (step 9) — not needed for the app itself.

### 2. Install Python 3.12
- Download Python **3.12.x** from python.org (match the dev version — the pinned
  wheels in `requirements.txt`, e.g. `torch==2.12.1`, resolve for cp312/Windows).
- During install, tick **"Add python.exe to PATH."**
- Verify in a new terminal: `python --version` → `Python 3.12.x`.

### 3. Copy the project folder
- Copy the whole `Modality_Project` folder to the new device — **but not** into a
  OneDrive / Google Drive / Dropbox synced directory. A good location:
  `C:\Users\<you>\Modality_Project`.
- If you're copying from the dev machine directly, it's fine if `.venv`,
  `__pycache__`, and the gitignored data/config files tag along or not — you'll
  rebuild/recreate them. (If migrating data, see section B for the two files that
  *must* come along.)

### 4. Build the virtualenv and install dependencies
From the project root, in a terminal:
```
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
`requirements.txt` already points torch at the CPU wheel index
(`--extra-index-url https://download.pytorch.org/whl/cpu`), so no separate torch
step is needed. This download is large (torch alone is hundreds of MB).

Verify: `.venv\Scripts\python.exe -c "import torch, transformers, librosa, fastapi; print('ok')"`.

### 5. Install Ollama and pull the generation model
- Install [Ollama](https://ollama.com/download) for Windows.
- Pull the model Cadence expects:
  ```
  ollama pull williamljx/medgemma-4b-it-Q4_K_M-GGUF
  ```
- Ollama runs a local service on `127.0.0.1:11434`. Leave it running (it starts with
  Windows by default). Confirm CPU-only generation works — first generation takes
  1–2 minutes on this hardware, which is expected.

### 6. Set up transcription (MedASR / Hugging Face)
Follow [`medasr-setup.md`](medasr-setup.md). In short:
- Create a free Hugging Face account, accept the `google/medasr` model terms on its
  model page, and create a **read-only** access token.
- Copy the template and paste the token:
  ```
  copy app\transcribe\hf_config.example.yaml app\transcribe\hf_config.yaml
  ```
  then edit `hf_config.yaml` and replace the placeholder with your token.
- The ~400 MB model downloads automatically on the **first** app launch (needs
  internet once); it's cached locally after that.
- The same token can be reused across devices — treat it as a secret.

### 7. (Optional) Google Sheets roster sync
Only if the practice wants the roster mirrored to Sheets. Follow
[`google-sheets-sync-setup.md`](google-sheets-sync-setup.md) and create
`app\integrations\sheets_config.yaml` (from the `.example`) plus the service-account
JSON key. Skip entirely otherwise — the app runs fine without it.

### 8. First launch
```
.venv\Scripts\python.exe launcher.py
```
or run `.venv\Scripts\python.exe -m uvicorn app.ui.server:app --host 127.0.0.1 --port 8420`
and open <http://127.0.0.1:8420>.

On first launch with no existing data, the app **auto-creates** a fresh
`app\storage\.keyfile` and an empty encrypted database. Open the **System Status**
page and confirm:
- Local note generation (Ollama / MedGemma) → ready
- Local transcription (MedASR) → ready (after the first-run download)
- Google Sheets → configured, or "not configured (optional)"

### 9. Create a desktop shortcut (so it's double-click launchable)
- Right-click the desktop → **New → Shortcut**.
- Target (use `pythonw.exe` so no console window appears):
  ```
  C:\Users\<you>\Modality_Project\.venv\Scripts\pythonw.exe C:\Users\<you>\Modality_Project\launcher.py
  ```
- Name it "Cadence." Optionally set "Start in" to the project root.
- Double-clicking it starts the server (if not already up) and opens the browser.

### 10. Device-level HIPAA hardening — **required before real patient data**
Follow [`device-safeguards-checklist.md`](device-safeguards-checklist.md):
- Turn **BitLocker** on for C: and store the recovery key somewhere physically
  secure. (This is what actually protects the `.keyfile` + encrypted DB if the
  laptop is lost or stolen — they sit on the same disk.)
- Set **require password on wake** (Settings → Accounts → Sign-in options).
- Keep the project folder out of any cloud-sync directory.

---

## B. Migrating existing patient data to the new device

The database is encrypted with a key that lives **only** in `app/storage/.keyfile`.
`cadence.db.enc` without its matching `.keyfile` is permanently unrecoverable, and a
`.keyfile` is useless without its database. To move real data you must move **both,
together**.

This is protected health information — move it over a **secure channel** (a physically
carried USB drive, or an encrypted transfer), **never** through an uncovered cloud
service. (The Google Workspace BAA covers the roster-sync Sheet only, not a file
transfer of the database.)

1. On the **old** device, fully close Cadence so the encrypted file is current. On a
   clean shutdown the app re-encrypts and removes its temp working copy; if it was
   force-killed, relaunch and close it normally once to guarantee `cadence.db.enc` is
   up to date.
2. Do the fresh-install steps (section A, steps 1–7) on the new device — but **do not**
   launch the app yet (launching first would generate a *different* empty keyfile you'd
   then have to delete).
3. Securely copy these two files from the old device to the **same paths** on the new
   device, creating `app\storage\` if needed:
   - `app\storage\.keyfile`
   - `app\storage\cadence.db.enc`
4. Now launch (section A, step 8). It will decrypt the copied database with the copied
   keyfile. If you see a "could not decrypt … with the current keyfile" error, the two
   files are mismatched — recopy both from the same source machine.
5. Verify the patient roster and a few saved notes appear.
6. When retiring the old device, either keep BitLocker on or securely wipe
   `app\storage\.keyfile` + `cadence.db.enc` — a copy of the key + data is a copy of
   all the PHI.

---

## C. Backups (do this once real notes exist)

Because notes live only in the local encrypted DB and there is **no cross-device note sync**
(see the limitation below), that one `cadence.db.enc` + `.keyfile` pair *is* the practice's
record. A dead or lost laptop loses everything unless it's backed up.

`scripts/backup.py` copies both files **together** (one is useless without the other),
verifies the copied pair actually decrypts, and restores them:

```
python scripts/backup.py backup  --dest "E:\CadenceBackups"     # to a local encrypted USB drive
python scripts/backup.py list     --dest "E:\CadenceBackups"
python scripts/backup.py restore  "E:\CadenceBackups\cadence-backup-YYYYMMDD-HHMMSS"
python scripts/backup.py verify                                  # check the live pair decrypts
```

Rules: back up to a **local encrypted external/USB drive kept on-site — never a cloud-synced
folder** (OneDrive/Google Drive; the Google BAA covers only the roster Sheet, not a DB copy).
Restore only while Cadence is **closed**; `restore` refuses to overwrite existing data without
`--force`, and with `--force` it saves the current files aside to `*.pre-restore-*` first.
Test a restore once so you know the routine works before you rely on it.

## Important limitation: Cadence is single-device by design

Patient **notes** are stored only in the local encrypted database on whichever machine
generated them. There is **no cross-device note sync.** Two machines running Cadence
will have independent, diverging note stores.

- "Shipping to another device" is meant as **migrate/replace** (section B), or as
  independent installs that don't share note history.
- The **only** thing that can be shared across machines is the patient **roster**, and
  only if Google Sheets sync is configured on each (roster fields only — never note
  content). If you need two active machines to share the roster, point both at the same
  sheet; note history still won't merge.

---

## No frozen `.exe` today (and why)

There is currently no PyInstaller/py2exe bundle. Freezing torch + transformers into a
single executable is fragile and huge, and it wouldn't remove the two things that
genuinely can't be frozen anyway — the Ollama service and the model downloads. The
supported distribution path is this source + venv procedure, sped up by **`setup.ps1`**
(project root), which automates section A steps 4–9 — the right investment here rather
than a frozen binary.

That reasoning still holds at v1.0.0; only the packaging AROUND it changed. `scripts/release.py`
builds a checksummed source zip from an ALLOWLIST, so no database, keyfile or credential can be
swept in, and `scripts/update.py` installs it into a versioned layout so an update is reversible.
Still no frozen binary, and still for the same reason.
