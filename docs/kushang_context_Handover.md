# Kushang — context handover (Cadence → Office Ally + website)

Written 2026-09-28 at the end of a long working session, so the work can be picked up later — by
Kushang or by Claude — without re-explaining. Branch: **`kushang-branch`** (pushed to GitHub).
Nothing here contains passwords, the Office Ally login, the practice's Office Ally company id, or
patient details — keep it that way; this file is in git.

**Start here next time:** read this file, then `docs/OfficeAlly_Integration_Rules.md` (binding practice
rules — partly out of date, see §6), then `docs/Website_Publish_Guide.md` if working on the site.

---

## 1. What was built

### Cadence → Office Ally (Chrome extension, `extension/`)
The clinician's path (works end to end, confirmed live on the "Cadence Init Eval" layout):
1. In Cadence, open a **saved** note → **Send to Office Ally**. Cadence opens Office Ally's Add Note
   page directly:
   `https://pm.officeally.com/emr/PatientCharts/PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=<id>&Tab=C&PID=<MRN>&Scope=&Date1=&Date2=`
   (`<MRN>` = the patient's Office Ally Patient ID stored as MRN in Cadence; `<id>` = the layout for the
   note type from **Manage Office**).
2. Log in if Office Ally asks (its login drops the path → Cadence's Send window has a button to reopen it).
3. On the Office Ally tab click the **Cadence icon** → the note sent from Cadence is pre-selected
   (hand-off between tabs via `chrome.storage.session`, ids only).
4. **Fill & save draft** (one click): fills every box, **reads each box back**, clicks Office Ally's
   **Apply** (draft save — never signs), and after the reload **re-checks the saved boxes** ("Saved and
   checked: all N boxes match Cadence").
5. The clinician reviews and signs in Office Ally.

Key behaviour:
- **Routing by meaning** (`extension/lib/oaroute.js` → `planRouting`): each Cadence section is matched
  to an Office Ally box by heading concept and box label. Sections are packed whole; a section longer
  than a box is split at sentence ends into "(cont.)" parts. **Overflow** goes into the other standard
  boxes of the same SOAP part (e.g. Objective Notes → Functional Status) and boxes labelled
  "(Cont)/Continue" — never into topic boxes (Special Test, Contra Indication…). Nothing is truncated;
  a section that can't fit is reported with how many characters to cut. **No automatic rewording**
  (unsafe — see CLAUDE.md rule 16); the clinician shortens with "Ask for changes".
- Office Ally's limit is 2,000 characters per box; newlines count as 2 (CRLF).
- **Hard stops** (fill nothing): wrong patient (page PID ≠ MRN), wrong layout for the note type,
  an EXISTING encounter dated differently from the note's visit date, logged out.
- **Relaxed at Kushang's request** (no extra clicks): same-day duplicate encounter (now only a note),
  "one encounter per note" warning (removed), unresolved `[! …]` gaps (filled visibly, counted in status).
- A NEW encounter's date is set to the note's **visit date** (visit date is chosen beside Save in
  Cadence; defaults to today).
- Office Ally **creates an encounter the moment an Add Note page opens** — every extra open = a blank
  encounter. Open Add Note once per note.
- Fixed bug: every logged-in Office Ally page contains "CleanLogon" in a keep-alive script; login is
  now judged by redirect/password box only.
- **Nothing practice- or patient-specific is built in**: layouts only from Manage Office
  (`app/integrations/office_ally.py`, settings file `office_ally.json`, git-ignored); Patient ID only
  from each patient's MRN.

### Cadence app changes
- `app/generate/loopguard.py`: stops a generation when MedGemma repeats the same sentences (was
  looping "Objective" text to the 3,072-token ceiling) and removes exact repeated sentences/sections.
- Visit date on notes (`visit_date` column), Manage Office tab, `/api/office-ally/settings`,
  `/api/extension/info`, bridge between Cadence page and extension (`extension/bridge.js`).

### Tests
- Extension unit tests: `extension/tests/oaroute.test.js` (43).
- Real-page browser test: `extension/tests/e2e/run_oa_page_test.py` (13 scenarios). Uses the private
  saved pages in `evals/Ingestion/` when present, else the clean templates in
  `extension/tests/fixtures/` (`E2E_FIXTURES=1` forces templates). Its test server must be HTTP/1.1
  (HTTP/1.0 made Chrome stall intermittently on this machine).
- `scripts/make_oa_template.py` turns a saved Office Ally page into a clean template (allowlist; refuses
  if any real id/DOB/login/company id/session data remains).
- Python: 764 tests; the only failure is the deliberate billing sign-off gate.

### Website (`website/`)
- `index.html` — new patient site for SD Mobile PT built from sdmobilept.com content (services,
  places, how it works, insurance: **Medicare, United Healthcare, Cigna, self-pay**, forms, contact).
  **Reviews section shows REAL reviews only** — add them in the `REVIEWS` list at the bottom of
  `index.html` (fake reviews are illegal under the FTC rule; testimonials need patient permission).
- `book/` — "Book a visit" page with the Google Calendar appointment schedule embedded (Google styles
  the calendar box itself; can't be recoloured). **Not yet confirmed the embed shows times** in a real
  browser.
- `cadence/` — clinician page for cadence.sdmobilept.com (install, Chrome add-on, updates). **Download
  button not linked yet** (waits for the 1.1.0 release).
- Plan: host on **Cloudflare Pages** (free, unlimited). Full steps: **`docs/Website_Publish_Guide.md`**.
  Domain/DNS stay at Squarespace; email is Google Workspace — never touch MX/SPF records.

---

## 2. How to run things (this machine)

| Task | Command / action |
|---|---|
| Start Cadence server | `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m uvicorn app.ui.server:app --host 127.0.0.1 --port 8420` (offline flags: MedASR otherwise fails on this network's SSL) |
| Website preview | in `website/`: `..\.venv\Scripts\python.exe -m http.server 8430 --bind 127.0.0.1` → http://127.0.0.1:8430/ |
| Reload the extension after a change | `chrome://extensions` → ↻ on "Cadence → Office Ally"; Ctrl+F5 the Cadence tab |
| Install extension fresh | `chrome://extensions` → Developer mode → Load unpacked → `C:\Users\localuser\Cadence\extension` |
| Extension unit tests | VS Code's Node: `ELECTRON_RUN_AS_NODE=1 "%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe" --test extension/tests/oaroute.test.js` |
| Real-page test | `.venv/Scripts/python.exe extension/tests/e2e/run_oa_page_test.py` (~4 min; `E2E_ONLY=8` runs one scenario) |
| Python tests | `.venv/Scripts/python.exe -m unittest discover -s tests` |

Restarting the Cadence server **loses unsaved generated notes** in the "Notes in progress" tray —
save them first.

---

## 3. Working agreements with Kushang

- **Engineering mode** (until he says "production mode"): fast loop — run only the targeted quick
  tests, give short try-steps, defer doc updates. "Production mode" = run everything + update docs.
- Commit/push only when asked; push to `kushang-branch`. `launcher.log` is a runtime log — don't
  commit it (it was committed once in 57e3e3a; consider `git rm --cached launcher.log` + .gitignore).
- Never store Office Ally credentials anywhere; never commit `evals/Ingestion/` (saved Office Ally
  pages hold the login name, company id, patient details, session data).
- Practice-owner decisions so far: Del-button/auto-delete of duplicate encounters — **dropped**;
  encounter checks relaxed (above); fake reviews — declined (legal); website on Cloudflare Pages.
- The test patient used during development is Kushang himself (his MRN in Cadence is his Office Ally
  Patient ID). Don't hard-code it anywhere.

---

## 4. Open items / next steps

1. **Publish the website** — follow `docs/Website_Publish_Guide.md` (Cloudflare account → upload
   `website/` → www CNAME to `<project>.pages.dev`, add `cadence` CNAME → check email still works →
   retire Google Sites after a week).
2. **Confirm the booking calendar** shows times on `/book/` in a real browser.
3. **Cadence 1.1.0 release** (Option 1 "download from website"): untrack `launcher.log`, merge
   `kushang-branch` → `main`, bump `app/__init__.py` to 1.1.0, write `docs/release-notes/1.1.0.md`,
   `scripts/release.py`, upload the zip to a Google Drive folder "Cadence Releases" shared with
   clinicians only, link it from `website/cadence/` (Download button + version text).
4. Make the desktop shortcut (`launcher.py`/`setup.ps1`) start Cadence with `HF_HUB_OFFLINE=1`.
5. Updater can't install from a downloaded zip yet (`scripts/update.py` only downloads from the URL in
   `CADENCE_UPDATE_URL`) — add `--zip <file>` if updates come from Drive.
6. **Docs out of date** with the relaxed rules: `docs/OfficeAlly_Integration_Rules.md` (rules 3.3–3.5),
   CLAUDE.md's Office Ally paragraph ("at most one encounter per day … blocks") — update in production
   mode.
7. Optional: panel button "Shorten in Cadence" for sections too long for their boxes; visible warning
   when the loop guard stops a generation early.
8. Future note types: Re-evaluation (visit 10) and Discharge Summary — add their layouts in Manage
   Office; new-injury rule (bold + re-evaluate goals only when the clinician explicitly says so) is
   still planned, not built.

---

## 5. Commits in this work (kushang-branch)

| Commit | What |
|---|---|
| `35780a7` | Enabling Chrome Extension — 1st try |
| `39ae877` | Office Ally: one-click fill + save draft, read-back and saved-note checks, login fix |
| `05253d5` | Nothing built in for the practice/patient; same-SOAP-part overflow; repetition-loop guard |
| `6dfecbe` | Clean Office Ally page templates for tests + generator script |
| `57e3e3a` | (Kushang) launcher.log |
| `7cfb843` | New website: main site, booking page, Cadence page |
| `16e2942`, `2e1dc03` | Website hosting: Netlify → Cloudflare Pages; publish guide |
| (this commit) | Publish guide renamed; this handover file |

## 6. Where the binding rules live
- `CLAUDE.md` — project constraints (local-only, PHI, Office Ally as second sanctioned destination).
- `docs/OfficeAlly_Integration_Rules.md` — the practice's Office Ally rules (some relaxed since; see §1).
- `docs/Clinician_Guide_Send_to_Office_Ally.md` — one-page clinician steps.
- `docs/Cadence2Officeally_readme.md` — detailed setup/reference.
- `docs/Website_Publish_Guide.md` — putting the website live.
