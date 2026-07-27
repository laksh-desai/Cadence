# Go-live checklist

The Cadence software is feature-complete: local transcription, local note
generation (block-format built-in templates plus clinician-created ones via the
Templates tab), encrypted storage, the full browser UI, and the optional Google
Sheets sync are all built and tested. What remains before the clinician can rely on
it day to day is **not more code** — it's the steps below,
each of which needs a person at the physical machine, the clinician's judgment, or a
Google admin. They're listed in the order that unblocks the most.

Legend: **[blocker]** must be done before real use · **[optional]** not required to launch.

---

## 1. Provision the laptop — **[blocker]**

The target ThinkPad had ~2 GB free at last check; the local models plus toolchain
need far more.

- [ ] Free up disk — aim for **30–40 GB free** before downloading anything.
- [ ] Confirm Python venv is set up and `requirements.txt` is installed
      (`.venv/Scripts/python.exe -c "import torch, transformers, librosa, fastapi"`).

**Done when:** the app starts (`launcher.py`) and the **System Status** page loads.

## 2. Install and pull the local models — **[blocker]**

Note generation and transcription each depend on a model that must exist on the
machine. Neither ships in this repo (they're large; Ollama is your own service).

- [ ] Install [Ollama](https://ollama.com) and pull MedGemma 4B
      (`williamljx/medgemma-4b-it-Q4_K_M-GGUF`); confirm it runs CPU-only.
- [ ] Complete the one-time MedASR/Hugging Face setup — see
      [`medasr-setup.md`](medasr-setup.md) (free HF account → accept the model
      terms → read-only token → `app/transcribe/hf_config.yaml`).

**Done when:** the **System Status** page shows both "Local note generation" and
"Local transcription" as ready, and the three verification scripts pass:
`scripts/verify_pipeline.py` (models respond end-to-end),
`scripts/verify_transcription.py` (synthesized speech → real MedASR transcript — no mic needed),
and `scripts/validate_quality.py` (a real generation auto-scored for the known defect classes).

## 3. Harden the device (HIPAA) — **[blocker]**

The app encrypts the data *file*; these protect the *device* it lives on (lost /
stolen / left unlocked). Full detail and exact click-paths in
[`device-safeguards-checklist.md`](device-safeguards-checklist.md).

- [ ] **BitLocker** full-disk encryption **On** for C: — needs admin rights; store
      the recovery key somewhere physically secure. *(Currently unverified.)*
- [ ] **Require password on wake** — Settings → Accounts → Sign-in options.
      *(Display-off/sleep timeouts are set; the password-on-wake toggle is unverified.)*
- [ ] Confirm the project folder is **not** inside a OneDrive/Google Drive synced
      directory, so the encrypted DB and keyfile never sync to an uncovered cloud.
      *(Currently safe — keep it that way.)*

**Done when:** all three boxes are verified on the actual machine.

## 4. Validate note quality with the clinician — **[blocker, ongoing]**

This is the highest-leverage remaining work and the one nothing else can substitute
for. MedGemma "isn't yet clinical grade"; every note is clinician-reviewed, but the
model still needs validation and likely fine-tuning on the practice's own notes
(CLAUDE.md rules #11–#14 document the known failure modes).

- [ ] Run a batch of **real (or realistic) dictations** across the note types the
      practice actually uses.
- [ ] Have the clinician review each draft and record corrections — especially any
      invented values, mis-carried-forward sections, or wrong flags.
- [ ] Feed each correction back as a **permanent prompt/logic rule** (the standing
      workflow instruction in CLAUDE.md), and keep the reviewed notes as fine-tuning
      data for later.

**Done when:** the clinician is comfortable that drafts are consistently a good
starting point, and correction patterns have been captured as rules.

## 5. Go live on Google Sheets roster sync — **[optional]**

Code-complete and unit-tested; blocked only on a Google Cloud permission, not code.
The practice's Workspace BAA is confirmed to cover Cloud Platform.

- [ ] Resolve the project-creator permission gap: create the Cloud project from the
      Workspace **super-admin** account, or have an org admin grant
      `roles/resourcemanager.projectCreator` at the org level.
- [ ] Then follow [`google-sheets-sync-setup.md`](google-sheets-sync-setup.md) from
      step 1 (Cloud project → Sheets API → service account → JSON key → share the
      Sheet with the service-account email → Apps Script `onEdit` trigger →
      `app/integrations/sheets_config.yaml` → restart → `POST /api/sync/now`).

**Done when:** an edit in the Sheet appears in the app and vice-versa. Roster fields
only — clinical note content never syncs.

---

## What's already done (no action needed)

- All application code (transcription, generation, storage, UI, sync).
- The prototype's old cloud call — removed; it makes no outbound model calls.
- Automated tests: storage delete/rebuild paths, Sheets sync, and the generation
  pipeline (parser, prompt builder, carry-forward extraction, and the deterministic
  postprocess safeguards) — run with
  `.venv/Scripts/python.exe -m unittest discover -s tests`.
