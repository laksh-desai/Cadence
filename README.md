# Cadence

Local, offline, privacy-first dictation-to-note app for a physical therapy practice.
A therapist speaks a short summary after a session; Cadence transcribes it and fills the
practice's note templates automatically — flagging missing fields instead of inventing
them, carrying forward the right sections from prior visits, and writing each note
uniquely. It is a self-hosted replacement for ScopeHealth.

**Status:** The local app (`app/`) is built and feature-complete — local transcription,
local note generation, encrypted storage, and the full browser UI all work end-to-end on
one machine. What remains before real day-to-day use is **not** more features: it's
clinical validation of note quality, provisioning the target laptop (disk + models), and
device-level HIPAA hardening. See [Remaining work](#remaining-work-to-real-use) below.

**Privacy stance:** Everything runs on the local machine. No patient data leaves the
device, with one narrow sanctioned exception (Google Workspace, under a signed BAA). See
`CLAUDE.md` for the full constraint list.

---

## What's built

- **Local transcription** — MedASR (`google/medasr`, Conformer-CTC), CPU-only, in
  `app/transcribe/`. Audio is captured and WAV-encoded in the browser and never leaves
  the device. One-time setup: `docs/medasr-setup.md`.
- **Local note generation** — MedGemma 4B (text-only) via Ollama, CPU-only, in
  `app/generate/`. Templates are wired with their REQUIRE/OMIT completeness modes and
  carry-forward behavior. The app ships with a small block-format built-in set (Initial
  Evaluation, Initial Evaluation — Updated Version, Follow-Up Visit); the clinician adds
  any other note types via the Templates tab (below). Deterministic safeguards in
  `app/generate/postprocess.py` backstop known model failure modes (see the generation
  rules in `CLAUDE.md`).
- **Editable / creatable templates** — a **Templates** tab (`/api/forms/{id}/template`)
  where the clinician reads each note's full outline large and readable beside the
  dictation box, edits a built-in's outline (saved as an override, one-click resettable to
  the shipped default), and creates / duplicates / deletes their own custom templates. The
  outline *is* the generation spec, so edits change what the model is told to produce
  (every note is still clinician-reviewed).
- **Verification layer (anti-hallucination)** — `app/generate/traceability.py` runs after
  generation and flags, in amber, five fabrication/quality classes the clinician should check
  before signing: clinical **values** absent from the dictation (fabricated ROM/MMT/pain/minutes/
  distance), **"normal" exam findings** asserted about body systems never mentioned
  (skin/neuro/sensation/coordination/edema/O2), invented **vitals** (BP/HR/O2), invented
  **assistive devices** (cane/walker/…), and **paste-duplicated** text repeated across sections.
  Deterministic and model-independent; it flags, never rewrites (rules 19–20 in `CLAUDE.md`).
- **CPT code suggestion** — `app/generate/cpt.py` maps each treatment section's stated intervention
  to its CPT code from a fixed table (gait training → 97116, manual therapy → 97140, …) as a
  confirmable blue chip; the model never authors codes (rule 12), and evaluation complexity / units
  are surfaced for the clinician, not auto-assigned.
- **Editable review before finalize** — after generation the clinician reviews the note, clicks
  **Edit** to change any section (including confirming or changing a suggested code), then **Save** —
  nothing is persisted until they do. Reinforces "the clinician reviews and signs every note."
- **Encrypted local storage** — Fernet-encrypted SQLite in `app/storage/`; patients,
  saved notes, and per-patient carry-forward snapshots. Full add/edit/delete for
  patients and notes.
- **Browser UI** — `app/ui/`, served by a local FastAPI backend. Multi-page nav
  (Home / All Patients / Templates / System Status).
- **Google Sheets roster sync** *(optional)* — bidirectional, code-complete and
  unit-tested in `app/integrations/`, but **not yet live** (blocked on a Google Cloud
  permissions step, not code — see `docs/google-sheets-sync-setup.md`). Syncs roster
  fields only, never clinical note content.
- **Launcher** — `launcher.py`, a double-click entry point that starts the local server
  and opens the browser.

**Input modalities (reference: Twofold AI).** Four ways to get a session in, all fully on-device:
type into the dictation box, dictate a summary (mic → local MedASR), **upload an audio file** (the
"Upload audio" button; WAV works best), or **Record session** — continuous live capture of the
whole visit, auto-chunked and transcribed locally as it runs. Live capture is v1: **no speaker
separation** yet (the transcript mixes clinician + patient, so review before generating), and it
needs the patient's consent. The borrowed idea is Twofold's input *flexibility*, not its cloud
architecture. See `CLAUDE.md` → Conventions.

---

## Running the app

Prerequisite: [Ollama](https://ollama.com) installed with the MedGemma 4B model pulled,
and the one-time MedASR token set up (`docs/medasr-setup.md`).

```
# from the project root, with the virtualenv created and requirements.txt installed
.venv/Scripts/python.exe -m uvicorn app.ui.server:app --host 127.0.0.1 --port 8420
```

Then open http://127.0.0.1:8420 — or just run `launcher.py` (or its desktop shortcut),
which does both. The app binds to `127.0.0.1` only; it is never exposed to the network.

To set this up on a **different machine** (or migrate patient data to one), follow
[`docs/shipping.md`](docs/shipping.md) — the full step-by-step, including the
encryption-key handling that data migration requires.

If MedASR or Ollama isn't set up yet, the rest of the app still runs — the **System
Status** page shows what's reachable, and the mic/generate actions surface a clear,
actionable error instead of crashing.

### The prototype (`cadence-prototype.html`)

A standalone single-file **UX/note-quality reference** at the repo root. It no longer
calls any model — its Generate button points you to the running local app. Use fake data
only; the patients/files in it live only for the browser session.

---

## Folder layout

```
Modality_Project/
├── CLAUDE.md                    # Project context + rules Claude Code reads every session
├── README.md                   # This file
├── cadence-prototype.html      # Standalone UX/note-quality reference (no model calls)
├── launcher.py                 # Double-click entry point (starts server, opens browser)
├── requirements.txt
├── templates/                  # Built-in block-format note templates (+ overrides/, custom/, _archive/)
├── docs/
│   ├── note-rules.md           # Generation rules + the two completeness modes
│   ├── hipaa-local.md          # Local/offline compliance posture
│   ├── device-safeguards-checklist.md
│   ├── medasr-setup.md         # One-time transcription setup
│   └── google-sheets-sync-setup.md
├── tests/                      # unittest suites (storage delete paths, sheets sync)
└── app/                        # The real local app
    ├── transcribe/             # MedASR integration
    ├── generate/               # MedGemma prompts, parsing, postprocess safeguards
    ├── storage/                # Encrypted local DB + carry-forward
    ├── integrations/           # Google Sheets roster sync
    └── ui/                     # FastAPI backend + browser UI
```

---

## Remaining work (to real use)

The feature set is done; the load-bearing remaining work is the part you can't shortcut.
It's consolidated as a sequenced checklist in
[`docs/go-live-checklist.md`](docs/go-live-checklist.md); in short:

1. **Clinical validation & likely fine-tuning** — MedGemma "isn't yet clinical grade."
   Run real dictations through it, capture the clinician's corrections, and use her
   reviewed notes as fine-tuning data. This validates quality and is the highest-leverage
   next step. (Every note is clinician-reviewed regardless — see `CLAUDE.md`.)
2. **Provision the target laptop** — the local models (MedASR + MedGemma 4B) plus the dev
   toolchain need room; aim for **30–40 GB free** before downloading models.
3. **Device-level HIPAA hardening** — full-disk encryption (BitLocker), require-password-
   on-wake, local-only backups. Tracked in `docs/device-safeguards-checklist.md`; the
   remaining items are in-person device settings, not code.
4. **Go live on Google Sheets sync** *(optional)* — finish the one-time Google Cloud
   setup once the project-creator permission is sorted (`docs/google-sheets-sync-setup.md`).

## Notes on quality

The model drafts; the clinician reviews and signs every note. Expect to keep tightening
the per-form prompts as real edge cases appear — every correction becomes a permanent
rule (see the standing workflow instruction in `CLAUDE.md`).
