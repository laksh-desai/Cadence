# Summary of Implementation

What is built, as of **2026-10-03** (branch `kushang-branch`). About a 5-minute read.
Part A is Cadence, Part B is the website, Part C is the change log, which is updated with every
change from now on.

---

# Part A — Cadence (PT note generator)

## A1. What it is
- Local, offline app: the therapist dictates, Cadence writes the note, the clinician reviews and
  signs.
- Runs on the laptop's CPU (no GPU), in the browser at **http://127.0.0.1:8420**.
- Patient data leaves the machine only to **Google Workspace** and **Office Ally**; both are covered
  by BAAs.
- Version **1.0.0**. Version 1.1.0 is planned and not yet released.

## A2. Getting the session in (4 ways, all on-device)
- **Type** rough notes into the dictation box.
- **Dictate** with the mic, in clips of up to 3 minutes.
- **Upload audio** from a recording file.
- **Record session**: captures the whole visit in ~3-minute pieces, transcribed in the background.
  It does not tell speakers apart and needs the patient's consent.
- **Guided mode**: walks through the form section by section with an example for each.
- Transcription uses **MedASR** (Google, runs locally). The audio never leaves the laptop.

## A3. Writing the note
- **MedGemma 4B** via Ollama writes every note. **gemma2:2b** writes "Fast draft" notes.
- **5 note types:** Initial Evaluation, Initial Evaluation — Updated Version, **Daily Visit**
  (Medicare treatment note), **Re-evaluation / Progress Report**, and **Discharge Summary**.
  Daily Visit, Re-evaluation and Discharge carry goals, precautions and status forward; the
  Initial Evaluations seed them.
- **Templates tab:** view, edit, duplicate, create, reset or delete templates. Editing a template
  changes what the model is asked to write.
- **Background queue:** start a note and walk away. The "Notes in progress" tray shows each note's
  place in line, and reattaches after a page reload.
  - Each note takes about **5–9 min** on this hardware.
  - Queued notes are lost if the server restarts, by design.
- **Safety clean-up after generation** (automatic, deterministic):
  - fixes headings that swallowed their content
  - removes template instruction text and "not performed" treatment sections
  - standardizes strength grades (e.g. "3+/5")
  - strips any CPT or ICD code the model wrote
  - **Loop guard:** stops the model when it repeats itself, and removes repeated text.
- **Fabrication flags** (amber `[[NEEDS: …]]` chips) mark things the note says but the dictation
  didn't:
  - numbers (pain, MMT, ROM, minutes, distance)
  - "normal" findings, vitals and assistive devices
  - pain scores and copy-pasted sentences
  
  These flags never delete anything; the clinician decides.
- **Very long dictations:** they are not shortened by a second AI pass. That was tested, made notes
  worse and invented goals, so it is turned off. The note is warned as "part not seen" instead.
- **Ask for changes:** a typed or spoken instruction rewrites only the named section and leaves the
  rest untouched.

## A4. Reviewing and saving
- Review screen: amber gap chips, per-section edit boxes, a visit-date picker, Save, Copy and Print.
- Saved in an **encrypted local database**, protected against two copies of the app writing at once.
- Clinician corrections are recorded (original vs edited, change requests) for future quality work.
  They are not exported anywhere.
- Patient roster and per-patient note history are in the **All Patients** tab.

## A5. Billing (ON — practice choice, 2026-10-11)
- **CPT suggestions** come from the treatments named in the note and dictation, using a fixed table.
  The model never writes a code.
- **ICD-10 suggestions** come from fixed tables for 6 body regions: shoulder, knee, lumbar,
  cervical, hip and ankle/foot.
- **8-minute-rule units** are shown both ways, CMS and AMA.
- **On by the practice's choice** (Manage Office setting). The ICD-10 tables are still not
  coder-verified (`scripts/coding_signoff.py`), so every ICD line says "confirm" and one test fails
  on purpose until a coder signs off.
- **Billing section** on every note (written by code): codes, minutes per code, total timed
  minutes, total treatment time, units, ICD-10 to confirm. Missing values are flagged.
- **Pre-send audit + Medicare documentation checklist** before Send to Office Ally and in the
  extension panel. It flags; it does not guarantee payment.

## A6. Office Ally (Chrome extension, `extension/`, v0.3.0)
- **Flow:**
  1. On a saved note, click **Send to Office Ally**.
  2. Cadence opens Office Ally's Add Note page for the right patient and layout.
  3. Log in if asked.
  4. Click the Cadence icon, then **Fill & save draft**.
  5. Review and sign in Office Ally.
- The note is handed between tabs automatically (ids only, never note text).
- **Smart mapping:** each Cadence section goes to the Office Ally box with the matching meaning.
  - Office Ally boxes hold 2,000 characters. Long sections continue into other boxes of the same
    SOAP part as "(cont.)".
  - Nothing is cut off; anything that doesn't fit is listed with how much to shorten.
- **Proof it landed:**
  - every box is read back before saving
  - Office Ally's **Apply** saves a draft only, never a signature
  - after the save, the saved boxes are checked against the note again
- **Hard stops (nothing is filled):** wrong patient, wrong layout for the note type, an existing
  encounter on a different date, or not logged in.
- **Relaxed (warnings only):** another encounter the same day; unresolved gaps.
- **Nothing hard-coded:** layouts are set in the **Manage Office** tab, and the patient ID is the
  patient's MRN.
- Cadence never signs, submits or deletes anything in Office Ally, and never stores Office Ally
  passwords.
- **Fallback:** "Copy for Office Ally" groups the note into S/O/A/P for manual pasting.

## A7. Other tabs and tools
- **Status:** shows whether the models, transcription and integrations are working.
- **Evals:** runs test sweeps on synthetic (fake) dictations.
- **Google Sheets roster sync:** code complete, **blocked** on Google Cloud permissions.
- **Release and update tools:** `release.py` and `update.py` (no auto-update). Updates keep patient
  data separate from the program.
- **Backups:** `scripts/backup.py`, including a restore rehearsal.
- **`saas/`:** early skeleton for a future multi-practice hosted version (tenancy, login checks,
  audit log). Not in use.

## A8. Quality and testing
- **764 Python tests.** The only failure is the intentional billing sign-off test.
- **49 extension unit tests**, plus **13 real-page browser scenarios** run on cleaned Office Ally
  page copies.
- Billing accuracy on 1,440 synthetic cases:
  - ICD: 99% precision, 97% recall
  - CPT: zero false codes
- On 18 real generated notes, no medications were invented or dropped.
- All test data is synthetic or self-authored. **No real clinician dictation has been tested yet.**
  That is the most important next step.

## A9. How to run
- **Start:**
  ```powershell
  cd C:\Users\localuser\Cadence
  $env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"
  .\.venv\Scripts\python.exe -m uvicorn app.ui.server:app --host 127.0.0.1 --port 8420
  ```
  Then open http://127.0.0.1:8420.
- **Stop:** Ctrl+C. Save notes first.
- **Easiest:** double-click **`Start_Server.bat`** (starts with the offline flags, opens the
  browser; just opens the browser if already running) and **`Stop_Server.bat`** (stops it and
  deletes the leftover decrypted temp copy of the database).
- **Models:** `williamljx/medgemma-4b-it-Q4_K_M-GGUF` and `gemma2:2b`. Don't update them casually.

## A10. Open items (Cadence)
1. Run one **real dictation** on the target ThinkPad, end to end.
2. Coder sign-off of the ICD tables, which unlocks billing.
3. Release **1.1.0**:
   - stop tracking `launcher.log`
   - merge to `main` and bump the version
   - zip the release, put it on Drive, and link it from the website
4. The desktop shortcut doesn't set the offline flags yet, so the mic may fail.
5. `update.py` can't install from a downloaded zip yet.
6. Follow-Up notes sometimes stop before Plan and Goals.
7. Docs are out of date for the relaxed Office Ally rules.
8. Planned features: Re-evaluation and Discharge note types, the new-injury rule, and a "Shorten in
   Cadence" button.
9. Google Sheets sync permissions.
10. Back up the data to USB regularly.

---

# Part B — Website (sdmobilept.com)

## B1. What is live
- **Live since 2026-10-02** on **Cloudflare Pages** (free, unlimited), project `sdmobilept` →
  `sdmobilept.pages.dev`.
- Confirmed working over https: **www.sdmobilept.com**, **sdmobilept.com** and
  **cadence.sdmobilept.com**.
- Files live in `website/`: plain HTML/CSS with no build step.

## B2. Pages
- **Home (`index.html`):** services, places served, how it works, insurance (Medicare, United
  Healthcare, Cigna, self-pay), reviews, forms and contact.
  - Phone 619-289-7110, info@sdmobilept.com, fax 858-544-5256.
  - **Reviews:** real ones only (FTC rule). While `REVIEWS` in `index.html` is empty, the Reviews
    section and its menu link are **hidden**. Adding a review shows both automatically; with 2+ the
    section is a rotating carousel (one review at a time, every 7 s, arrows + dots, pauses on hover).
- **Book a visit (`book/`):** Google Calendar appointment booking embedded in the site's colours,
  plus the 3 patient forms (from Google Drive).
- **Cadence page (`cadence/`):** for clinicians (install, Chrome add-on, updates).
  - cadence.sdmobilept.com lands here.
  - The **Download button isn't linked yet**; it waits for the 1.1.0 release.

- **Appointment booked by PT (`pt-booking/`)** — for therapists/staff booking on a patient's
  behalf: same Google Calendar booking embed, steps (enter the PATIENT's contact so reminders reach
  them), "no diagnoses in bookings" note, link to Google Calendar for off-schedule times. Hidden from
  search engines (noindex) but publicly reachable. Linked from the home page footer, above
  Patient forms · Contact · For clinicians.
- **Exercises (`exercises/`)** — SD Mobile PT's home-exercise program builder (source project:
  `C:/Users/localuser/Claude_Projects/SDMPT_Exercises`, copied in with its
  `publish_to_website.bat`). Linked as **Exercises** in the nav of the home, Book a visit and
  Appointment-booked-by-PT pages. Opens a staff login page with the SD Mobile PT logo (fixed
  username/password in `exercises/js/config.js`). This is a browser-side gate only, not real
  security; no patient records are stored. Patient handout links (`exercises/#p=...`) skip the
  login. 54 illustrated exercises, printable handouts, phone links/QR, templates. Hidden from
  search engines (noindex).

## B3. Domain and DNS
- The domain is at **Squarespace Domains**. Reach it by signing in with the **Google Workspace
  admin** account; a plain Squarespace login shows no domains.
- DNS records:
  - CNAME `www` → `sdmobilept.pages.dev`
  - CNAME `cadence` → `sdmobilept.pages.dev`
- Email records (MX, SPF, DKIM) are untouched. **Never edit them.**
- The domain **expires 2027-02-01**; keep auto-renew on.

## B4. Open items (website)
1. Send a test email to info@sdmobilept.com and confirm both directions work.
2. Confirm the booking calendar shows times.
3. After a week, remove the custom domain from the old Google Site.
4. Delete the unused Cloudflare Worker `blue-boat-487f`.
5. Cancel any unused Squarespace website plan; keep the domain.
6. Link the Cadence download once 1.1.0 is released.
- **To update the site:** edit `website/`, then in Cloudflare open Workers & Pages → sdmobilept →
  Create deployment, and drag the folder in.

---

# Part C — Change log

**Guard rail:** every project change appends here: a `### YYYY-MM-DD` heading (reuse today's if it
exists) and plain bullets of what changed. Append only; never edit past entries. If what is built
changes, update Parts A/B too. Enforced by `.githooks/pre-commit` and by the rule in `CLAUDE.md`.

### 2026-10-03
- Created this summary file from a full read of the code (app, extension, scripts, tests, docs,
  website).
- Added the change-log guard rail:
  - `.githooks/pre-commit` blocks commits that change the project without an entry here
  - a matching rule in `CLAUDE.md`
- Hooks enabled on this machine with `git config core.hooksPath .githooks` (needed once per new
  copy of the repo).
- `.gitattributes`: the hook keeps Unix line endings so it runs on Windows.
- Website: new page **Appointment booked by PT** (`website/pt-booking/`) for staff booking on a
  patient's behalf; home-page footer gets an "Appointment booked by PT" link above Patient forms ·
  Contact · For clinicians (`index.html`, `assets/site.css`). Not live until re-uploaded to
  Cloudflare Pages.
- Website re-deployed to Cloudflare Pages (5:32 PM); www.sdmobilept.com/pt-booking/ and the new
  footer link confirmed live.
- Added `to_do_list.md` (repo root): flexible PT/admin booking options, work ↔ family calendar
  sharing steps (free/busy only, no patient details in personal Gmail), website follow-ups.

### 2026-10-07
- Website: new **Exercises** page (`website/exercises/`): the SD Mobile PT exercise program builder
  from `Claude_Projects/SDMPT_Exercises`, copied in by that project's `publish_to_website.bat`. It
  opens a staff login page with the SD Mobile PT logo (username `SDMPT`, password `Exercises`, set
  in `exercises/js/config.js`). This is a simple browser-side gate, not real security. Patient
  handout links skip the login so patients can open them.
- Website: **Exercises** link added to the nav on the home page, `book/` and `pt-booking/`.
- Website (`assets/site.css`): with 7 nav links the bar overflowed between about 860 and 1300 px
  wide. The phone number now hides below 1320 px, and the hamburger menu starts below 1140 px
  (was 1040 / 860).
- Website: Reviews section now rotates when it has 2+ real reviews. One large review at a time,
  auto-advancing every 7 s, with previous/next arrows and dots; it pauses on hover/focus and doesn't
  auto-rotate for visitors who turn off motion. Stars show only if the review itself had a rating
  (optional `stars` field). `REVIEWS` stays empty: no reviews were written or invented (FTC rule).
  The empty "Share your experience" box is unchanged until real reviews are added (`index.html`,
  `assets/site.css`).
- Website: no public reviews of SD Mobile PT exist yet, so the Reviews section and its "Reviews"
  menu link are now hidden while `REVIEWS` is empty (no empty "Share your experience" box). Both
  reappear automatically when a real review is added. The empty-state code was removed.
- Not live until the `website` folder is re-uploaded to Cloudflare Pages.

### 2026-10-09
- Added `start_cadence.bat` and `stop_cadence.bat` (repo root): double-click to start Cadence
  (sets the offline flags, runs the server in a minimized "Cadence Server" window, opens the
  browser) and to stop it. Stop also deletes the decrypted working copy of the database that a
  forced stop leaves in %TEMP% (saved data is already encrypted). Tested: stop → start → running.
- `.gitattributes`: `.bat` files keep Windows line endings.

### 2026-10-11 / 2026-10-12
- **Note types:** Daily Visit rebuilt to Medicare treatment-note standard (Subjective, one section
  per treatment with minutes and skilled detail, Objective Measures, Assessment with medical
  necessity, goals, Plan). New **Re-evaluation / Progress Report** and **Discharge Summary**
  templates. Initial Evaluations now feed their goals into the next visit's carry-forward.
- **Speed:** the prompt now puts the fixed template and rules first so the model can reuse them
  between notes (reading the prompt went from ~120 s to ~10 s; Daily Visits ~1–2.5 min end to end
  in testing). The model and the Daily Visit instructions are pre-loaded at startup. Generation
  timings are logged (numbers only).
- **Billing on:** CPT and ICD-10 suggestions switched on by the practice (Manage Office setting);
  ICD tables still marked unverified until a coder signs off. Re-evaluations always ask whether
  97164 is justified or it is a non-billable Progress Report.
- **Billing section:** every note gets a code-written "Billing — CPT & Minutes" section (codes,
  minutes per code, total timed minutes, total treatment time, units, ICD-10 to confirm); missing
  minutes or total time are flagged, never guessed. Spoken totals like "total was forty minutes"
  and self-corrections ("forty five, uh, forty") are now read, with a confirm flag.
- **Pre-send audit + Medicare checklist:** Send to Office Ally first shows what would not be paid
  (missing minutes / total time / codes) and what a Medicare reviewer would question (unskilled
  wording, no patient response, unmeasurable goals, no comparison on a progress report, …). The same
  list appears in the Chrome extension panel. It flags; the clinician decides.
- **Office Ally:** boxes whose label matches a Cadence heading are filled one-to-one; Billing
  section has its own box (falls back to Procedure Notes). Confirmed CPT codes no longer reach
  Office Ally as raw `[[...]]` text. Four Office Ally layout specs for the Office Ally team:
  `templates/OfficeAlly_Initial_Eval_Template.md`, `..._Daily_Visit_...`, `..._Reevaluation_...`,
  `..._Discharge_Summary_...`.
- **Reliability:** loop guard no longer cuts off legitimate notes that repeat a flag across sections
  (likely cause of missing sections); the queue ignores an identical note submitted twice
  (double-click). New `scripts/field_test.py` runs whole fake episodes through the real pipeline.
- Tests: new `test_billing_audit.py`, `test_compliance.py`, loop-guard and queue tests; extension
  routing tests for exact labels and Billing.

### 2026-10-12 (later)
- `start_cadence.bat` now restarts every time (stop if running -> `wsl --shutdown` -> start ->
  browser); `start_cadence.bat stop` stops only. `stop_cadence.bat` removed (merged).
- Manage Office: Billing codes switch (On / On after coder sign-off / Off). Evals tab hidden from
  clinicians (`?dev=1` shows it).
- Field-test repairs: stacked "Label — value" lines split back into sections; "not performed"
  treatment sections dropped; undictated treatments flagged (audit "fix"); bare "MET" goals flagged;
  Pain sections only when stated; a treatment-free discharge is a "check", not a "fix".
- Laptop check: ThinkPad X1 Carbon Gen 9, 8 GB LPDDR4x soldered — RAM cannot be upgraded.

### 2026-10-13
- Back to two files at the user's request: `Start_Server.bat` (start only) and `Stop_Server.bat`
  (stop only). `start_cadence.bat` removed. Tested: start -> running -> stop.
- Investigated "the server file rebooted my machine": Windows logged "critical thermal event"
  shutdowns (Kernel-Power 86) on 2026-10-12 — the laptop overheated, after hours of 100%-CPU field
  testing; nothing Cadence-related starts automatically. Long test runs will not be run on this
  X1 Carbon.
- **Fix (empty Daily Visit):** a note came back as headings only. Cause: the 2026-10-11 speed change
  moved the writing rules above the dictation. Measured on the same fake note: 5/14 sections (rules
  first) vs 14/14 (rules last). Reverted to rules-after-dictation; only the template outline is
  still pre-loaded. Any note with more than half its sections empty now shows "INCOMPLETE NOTE —
  regenerate" at the top. Speed for Daily Visits is therefore closer to ~3 min than ~1.5 min.
- A treatment section the dictation says was **declined**, from a prior visit, only planned, or a
  home-program item (e.g. "patient declined soft-tissue mobilization" -> Manual Therapy section) is
  now flagged in the note and as a "fix" in the pre-send audit, like an undictated one.

### 2026-10-13 (intake + security)
- **Dictation from the iPhone / Android tablet** without opening Cadence — two options, both inside
  Google Workspace (BAA): **Email** (subject contains "Cadence" + visit date; practice senders only;
  any number of subscribed mailboxes) and **Google Form** (visit date, note type, typed dictation or
  an attached recording, transcribed locally). Each becomes a draft under a new "Unknown patient"
  (visit date in DOB) in Notes in progress; nothing saved unreviewed; never processed twice;
  re-picked if Cadence restarts before saving. Manage Office card "Dictation from phone or email"
  (enable, mailboxes, app passwords, Sheet link, Test connection, Check now); Status line.
  Setup: `docs/Intake_Setup_Guide.md`. End-to-end check: `scripts/intake_e2e.py` (fake inputs).
- Phone recordings (.m4a etc.) now decode locally: new requirement **`av==19.0.1`** (PyAV).
- **Security hardening:** decrypted DB working copy now EFS-encrypted; intake secrets
  DPAPI-locked to the Windows user (`app/secure_store.py`); "Data protection" line on Status.
- Tests: `test_intake.py`, `test_secure_store.py` (823 total; only the coder sign-off test fails,
  on purpose).
- `Stop_Server.bat` now waits until the port is actually released before returning, so an immediate
  `Start_Server.bat` starts a fresh server instead of assuming the old one is still running.
- `Start_Server.bat` now writes the server's output to `logs\server.log` (previous run kept as
  `server.prev.log`; `logs/` is git-ignored), so a server that stops on its own leaves its reason
  on disk. Only startup messages, request lines, timings and errors — never note text.
