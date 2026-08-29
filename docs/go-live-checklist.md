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

## 0. Install from a release, not a git clone — **[blocker]**

As of v1.0.0 Cadence ships as a versioned release rather than a copied project folder, because an
installed copy has to be able to take an update without losing the clinician's data. Install the
layout described in [`releasing.md`](releasing.md):

- [ ] Unzip the release to `C:\Cadence\versions\<version>\` — NOT to a bare folder. The
      `versions\` parent is what tells Cadence where its data lives.
- [ ] Run `setup.ps1` from inside that folder. It builds the shared venv at `C:\Cadence\.venv` and
      points the desktop shortcut at `C:\Cadence\current`, so an update does not leave the
      clinician launching the old build.
- [ ] Confirm the Status page shows the version number you installed.

**Why it matters:** in this layout the encrypted database, the clinician's own templates and the
credentials live in `C:\Cadence\data\`, which an update never touches. Installed as a plain folder
they would sit inside the version directory and be stranded by the first update.

**Done when:** `python scripts\update.py --status` reports the installed version and the data
directory.

---

## 1. Provision the laptop — **[blocker]**

The target ThinkPad had ~2 GB free at last check; the local models plus toolchain
need far more.

- [ ] Free up disk — aim for **30–40 GB free** before downloading anything.
- [ ] Confirm Python venv is set up and `requirements.txt` is installed
      (`.venv/Scripts/python.exe -c "import torch, transformers, librosa, fastapi"`).

> Steps 1–2 are largely automated by **`setup.ps1`** (project root) — see
> [`shipping.md`](shipping.md) section A. Run it after installing Python + Ollama.

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

## 4b. Sign off the billing code tables — **[blocker before BILLING; no longer blocks launch]**

> **This no longer blocks go-live.** v1.0.0 ships with code suggestions switched OFF:
> `cpt.billing_enabled()` is computed from `TABLE_PROVENANCE`, so the CPT/ICD chips and the billing
> card are hidden and the Status page states the reason. They turn on by themselves once the last
> region is signed — no reinstall, nothing to remember. The clinician gets the note-writing half
> now and the billing half once it has been checked.
>
> Produce the coder's worksheet with `python scripts/coding_signoff.py --out signoff.md`, and
> record a completed region with
> `python scripts/coding_signoff.py --sign <region> --by "<name, credential>" --on <date>`.

Cadence now drafts CPT codes, ICD-10 codes, treatment minutes, and billing units from the
dictation (`app/generate/billing.py`). It never lets the model author a code, but the tables it
maps from are **not yet reviewed by anyone qualified**, and a wrong code rendered as a confident
chip is worse than no chip at all.

- [ ] Have the clinician or a certified coder verify the ICD-10 tables in
      `app/generate/coding_tables.py` against the current ICD-10-CM year, then fill in
      `verified_by` / `verified_on` in `TABLE_PROVENANCE`. **`tests/test_billing_extract.py` fails
      until they do** — that failure is the gate, not a bug. **Sign-off is per region** (shoulder,
      knee, lumbar, cervical, hip, ankle), so start with the regions the practice actually sees;
      the others stay visibly unverified and banner themselves in the Evals tab.
- [ ] Have the clinician verify the billing gold labels on the eight hand-written records in
      `evals/data/shoulder.jsonl` (each carries a `gold_provenance` block; `verified_by` is
      blank). These are the **non-circular control** for every accuracy number the eval reports —
      they were hand-read from the transcripts, not produced by the extractor, but they still
      need a clinician's eye. See CLAUDE.md rule 21.
- [ ] Watch the **wrong-claim** counters on a sweep — billing something the therapist said wasn't
      done, counting untimed minutes, a wrong-side diagnosis, an invented duration, an
      **over-counted unit**. These measure overbilling, not incompleteness, and must stay at zero:
      `.venv/Scripts/python.exe scripts/eval_corpus.py --limit 5 --runs 1` (or the **Evals** tab).
      Read `units_overstated` rather than `units_exact`: under-counting is a safe gap the clinician
      fills, over-counting is a claim. Likewise `cpt_surfaced_recall` (raised for confirmation)
      rather than only `cpt_detection_recall` (billed outright).
- [ ] Confirm with the biller which unit rule the practice's payers use. Cadence deliberately
      reports **both** CMS substitution and the AMA rule of eights, because they genuinely
      disagree; it does not pick one.

**Done when:** both `VERIFIED_` fields are filled, the eight control records are clinician-
verified, and a sweep reports zero wrong claims.

## 4c. Clear the demo data before real use — **[blocker if the seed was ever run]**

`scripts/seed_demo_data.py` can populate the app with synthetic patients for UX review. They are
fictional, but a roster mixing demo and real patients is a clinical-safety hazard in its own right.

- [ ] `.venv/Scripts/python.exe scripts/seed_demo_data.py --list` — confirm what is demo vs real.
- [ ] `.venv/Scripts/python.exe scripts/seed_demo_data.py --clear` on the clinician's machine
      before the first real visit. It deletes only `synthetic = 1` rows.

**Done when:** `--list` shows zero demo patients on the production machine.

## 4d. Rehearse an update and a rollback — **[blocker, before the SECOND release]**

Not before the first install — there is nothing to update from — but before you ship a second
version to a machine holding real notes.

- [ ] `python scripts\update.py --check` from the installed copy. It should report the current
      version and either reach the manifest or say plainly that it could not, which is harmless.
- [ ] After cutting a second release: `--apply`, then confirm the roster and a few notes are still
      there and Status shows the NEW version.
- [ ] `--rollback`, confirm the app still opens and the notes are still there, then `--apply`
      again. Rolling forward is always safe; this is to prove rollback works before you need it at
      9am on a Tuesday.

**Done when:** you have updated and rolled back once on a machine with data in it.

## 5. Set up a backup routine — **[blocker, once real notes exist]**

Notes live only in the local encrypted DB — there is **no cross-device note sync**, so a
lost or dead laptop loses everything unless it's backed up. `scripts/backup.py` copies the
`.keyfile` + `cadence.db.enc` pair together, verifies the copy decrypts, and restores it.

- [ ] Back up to a **local encrypted external/USB drive kept on-site** — never a cloud-synced
      folder (`python scripts/backup.py backup --dest <drive>`; full detail in
      [`shipping.md`](shipping.md) section C).
- [ ] **Test a restore once** so you know the routine works before relying on it. Use
      `python scripts\backup.py restore <folder> --dry-run` — it verifies the backup decrypts and
      reports what would change without writing anything, so testing a backup no longer means
      overwriting the live database.

**Done when:** a backup has been taken and a test restore succeeded.

## 6. Go live on Google Sheets roster sync — **[optional]**

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
