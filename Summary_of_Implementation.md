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
- **3 note types:** Initial Evaluation, Initial Evaluation — Updated Version, and Follow-Up Visit.
  Follow-Up carries goals, precautions and status forward from the last visit.
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

## A5. Billing (built, but switched OFF)
- **CPT suggestions** come from the treatments named in the note and dictation, using a fixed table.
  The model never writes a code.
- **ICD-10 suggestions** come from fixed tables for 6 body regions: shoulder, knee, lumbar,
  cervical, hip and ankle/foot.
- **8-minute-rule units** are shown both ways, CMS and AMA.
- **Blocked:** the tables need a certified coder or clinician to sign off
  (`scripts/coding_signoff.py`). Billing turns on by itself once every region is signed. One test
  fails on purpose until then.

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
  - **Reviews:** real ones only (FTC rule). The list is empty and shows a "Share your experience"
    link.
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
