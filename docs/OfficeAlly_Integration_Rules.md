# Cadence ↔ Office Ally — Practice Rules

These are the standing rules for how Cadence notes reach Office Ally at **SDMPT (SD Mobile PT)**,
as set by the practice on **2026-09-28**. They apply to anyone changing Cadence or its Chrome
extension, human or AI. They are **requirements, not suggestions**. If a change would break one,
the change is wrong.

Each rule says **how it is enforced today**. "Enforced" means code refuses to proceed; "Planned"
means it is agreed but not built yet.

For step-by-step setup and daily use, see [Cadence2Officeally_readme.md](Cadence2Officeally_readme.md).

---

## 1. The workflow

1. The physical therapist visits the patient at home and treats them.
2. The therapist **dictates** the session into Cadence.
3. Cadence's **local** model (MedGemma, on this laptop) structures the note. No cloud AI is ever
   used for patient data.
4. The therapist reviews and saves the note in Cadence.
5. The Chrome extension **fills** the Office Ally note boxes.
6. **The therapist reviews every box and signs the encounter manually in Office Ally.**

**Rule 1.1 — Signing is always manual; saving a DRAFT is allowed** (updated by the practice
2026-09-28: "map it in the layout and save it. Ask clinician to verify"). After a **clean** fill
(every section placed, no box overwritten, every box read back correctly — Rule 1.5), the
extension clicks Office Ally's **Apply**, which saves the note and keeps it open, then tells the
clinician to review every box and sign. If anything is left to fix, nothing is saved. It never
clicks Update-and-close, and never signs, attests, or submits. *Enforced:* `content.js` → `fill` /
`findApplyButton` (matches the "Apply" label only).

**Rule 1.5 — Prove the mapping landed; never assume it** (practice, 2026-09-28: "mapping has to be
done properly"). Two checks, both box by box against the Cadence note:
1. **Before saving:** after filling, the extension reads every box back from the page. If any box
   is empty or holds different text, it names the box and does **not** save.
2. **After saving:** Apply reloads the page. The panel reopens on the same note and compares what
   Office Ally now holds with the note: "Saved and checked: all N boxes match Cadence", or "Saved-note
   check FAILED" naming each empty or different box. If Chrome doesn't reopen the panel by itself,
   the clinician clicks the Cadence icon and the same check runs. Whenever the panel opens on an
   encounter that already has text, it shows this comparison.
*Enforced:* `oaroute.js` → `sameText`, `verifyBoxes`; `content.js` → `fill`, `savedCheck`;
`background.js` → `verifyAfterSave` / `verifyPending`. e2e scenarios 11 and 12.
**Proven only on the saved page, not live:** the test re-creates the page after Apply; the live
check is the panel's "Saved and checked" line in the clinician's own session.

**Rule 1.3 — Keep it seamless for the clinician.** The clinician's path is: **Save → "Send to
Office Ally" (in Cadence) → log in if asked → open or create that day's encounter → Cadence icon →
Fill → review and sign.** Everything else is Cadence's job:
- The **Send to Office Ally** button (in Cadence, under every note) sets up the Chrome extension
  the first time, with copy buttons. It asks once per patient for the Office Ally Patient ID,
  passes the chosen note to the extension (ids only), and opens the patient's Office Ally chart.
- The extension pre-selects that note. Otherwise it picks the only note dated the same day as the
  open encounter. Anything ambiguous is left for the clinician to choose.
- Clinician-facing instructions stay one page: `docs/Clinician_Guide_Send_to_Office_Ally.md`.

**Rule 1.4 — Office Ally logs clinicians out after inactivity; always check first.** If the panel
opens on the Office Ally sign-in page, or the session has timed out, the extension fills nothing
and tells the clinician to log in, reopen the encounter, and click the icon again. *Enforced:*
`pageKind` / `looksLoggedOut` in `oaroute.js`. The encounter-list request doubles as a live session
check at every Fill.

**Rule 1.2 — Office Ally has no write API, so filling happens in the browser.** Office Ally's
SMART-on-FHIR interface is read-only. The extension fills the page the clinician already has open
in their own logged-in session.

---

## 2. Note types

| # | Note type | When | Cadence template | Office Ally layout | Status |
|---|---|---|---|---|---|
| 1 | Initial Evaluation | 1st visit | Initial Evaluation (`initial`, `initial_updated`) | **Cadence Init Eval** (id 374261) | Built |
| 2 | Daily / Follow-Up (progress) note | Visits 2–10 (up to 9 visits) | Follow-Up Visit (`followup`) | **Progress Notes** (id 361919) | Built |
| 3 | Re-evaluation | 10th visit; similar to the Initial Evaluation | — | — | Planned |
| 4 | Discharge Summary | End of care | archived `templates/_archive/discharge.md` | — | Planned |

**Rule 2.1 — Each note type goes into exactly one Office Ally layout.**
- Initial Evaluation → **Cadence Init Eval**
- Follow-Up Visit → **Progress Notes**

**The layouts are set in Cadence → Manage Office** (SoapLayoutID + the name Office Ally shows),
not in code. SoapLayoutIDs are fixed per Office Ally account. Re-evaluation and Discharge layouts
are added there when those note types exist. SDMPT's defaults are 374261 = Cadence Init Eval and
361919 = Progress Notes. Cadence's Send button and the extension read the same settings, so they
cannot disagree.

*Enforced (hard block):* if the open layout doesn't match, the extension **does not switch it and
fills nothing**. It tells the clinician which layout to choose. Matching is by layout id or exact
name, so a look-alike such as "Copy Of Progress Notes" is refused. Custom Cadence templates have no
required layout.

---

## 3. Identity: which patient, which encounter

**Rule 3.1 — Patients are tied by Office Ally Patient ID, never by name or date of birth.** The
Patient ID (e.g. `155793457`) is stored in Cadence as the patient's **MRN**. *Enforced (hard
block):* the extension fills nothing unless the Office Ally page's Patient ID equals the Cadence
patient's MRN. A patient with no MRN is also refused, with the ID to enter.

**Rule 3.2 — An encounter is tied to its VISIT date.** Every Cadence note carries a **Visit date**
(set beside Save; defaults to today; older notes use the day they were saved). The Office Ally
encounter must carry the same date.
- **New encounter** (Add Note): its date is only Office Ally's default (today), so at Fill the
  extension **sets the Encounter Date to the visit date**. That is how a visit from another day is
  entered.
- **Existing encounter**: its date is **never changed**. A mismatch is a hard block that fills
  nothing.

*Enforced:* `oaroute.js` → `visitDateOf`, `isNewEncounter`, `checkEncounterDate`; `content.js` →
`setEncounterDate`. Verified on the real Office Ally page (e2e scenarios 2 and 3).

**Rule 3.3 — At most ONE encounter per patient per day. This is absolute.**
If Office Ally already shows another encounter for the same patient on the same date, Cadence does
not fill a second one. Removing an extra encounter is the clinician's own action in Office Ally;
**Cadence never deletes anything in Office Ally** and has no delete step (the practice dropped the
"Del button" idea on 2026-09-28). *Enforced:* the extension reads the patient's Encounters list
from Office Ally, within the clinician's own session, and:
- **another encounter on that date** → **hard block** with its encounter ID;
- **list can't be read or shows no encounters** → the first Fill click only warns and asks the
  clinician to check the Encounters list themselves; a second click fills.

**Rule 3.5 — Office Ally creates an encounter the moment an Add Note page OPENS.** Both saved
Add Note pages carry an Encounter ID and the title "Add Note / Encounter [Encounter ID …]" before
anything is saved. So every extra Add Note — a second click on Create, a retry after a blocked
fill — leaves another **blank encounter** in the chart. This is the cause of the empty encounters
seen on 2026-09-28. *Enforced:* the extension remembers which encounter each Cadence note went to
(ids only, 30 days, `background.js` → `noteEncounterGet/Set`):
- Cadence's **Create … note** button and the extension's **Create** button refuse to open a second
  Add Note for the same note and name the existing encounter to open instead (a second click is
  allowed, for when that encounter was removed);
- filling a note into a DIFFERENT encounter than the one it already has warns first, naming both
  encounters (e2e scenario 13).

**Initial Evaluation → "Cadence Init Eval" box mapping** (verified on the practice's real form):
Chief Complaint → Chief Complaints · Diagnoses → *Diagnosis* · Medications → Medications ·
Allergies, Referral & Relevant History → Medical History · Social History & Living Environment →
Social History · Fall Risk → *History of Falls* · Objective Summary, Musculoskeletal, Other
Systems, Cardiopulmonary, Coordination/Sensation/Edema → Objective Notes · Functional Mobility →
Functional Status · Assessment Summary → *Clinical Presentation* · Short/Long-Term Goals → Goal
Notes · Plan of Treatment → Plan Notes. The layout's *Personal Factors, Cognition, Patient Goals,
Outcome Measurement tools, Special Test, Patient Education, Rehab Potential, Contra Indication,
Treatment Diagnosis* boxes fill automatically if the Cadence template gains sections of those
names. Custom boxes are only ever chosen by their label, never by position.

**Rule 3.4 — Create ONE encounter per note, on the right layout.**
1. **Create the encounter once**, on the layout the note type requires:
   `https://pm.officeally.com/emr/PatientCharts/PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=<id>&Tab=C&PID=<PatientID>&Scope=&Date1=&Date2=`
   with SoapLayoutID **374261** (Cadence Init Eval) for an Initial Evaluation, or **361919**
   (Progress Notes) for a Follow-Up. (Rule 3.5: opening this page creates the encounter.)
2. The extension sets a new encounter's **Encounter Date** to the note's date (Rule 3.2), fills,
   reads back, saves a draft, and checks the saved note (Rule 1.5).
3. The clinician reviews every box and signs.

*Enforced:* Cadence's **Send to Office Ally** offers a **Create … note** button with the correct
layout, guarded by Rule 3.5. On the Progress Notes list
(`…/PatientChart_ProgressNotes.aspx?PageAction=ProgressNotes,PatientCharts_ProgressNotes_Add&Tab=C&PID=<PatientID>&Scope=&Date1=&Date2=`)
the extension names any encounter already dated that day and its **Create** button refuses — open
that encounter instead. Rule 3.3's duplicate check still runs at Fill as the backstop.

---

## 4. Content rules

**Rule 4.1 — Office Ally's 2,000-character limit per box is never bypassed.** Content is routed
across the layout's meaningful sections instead of being cut arbitrarily. Sections go in whole; a
section longer than a box is split only at a sentence boundary as "(cont.)"; nothing is ever
truncated. Anything that can't be placed is shown for manual copying. *Enforced:*
`extension/lib/oaroute.js`.

**Rule 4.2 — The two templates don't line up; route by meaning.** Cadence's template sections
(Chief Complaint, Diagnoses, Medications, Allergies, …) are mapped to Office Ally's boxes by what
they mean, reading the boxes actually on the page. *Enforced:* `oaroute.js` (see the readme for
the routing table). **If a layout's boxes aren't recognised at all, nothing is filled.** The panel
offers **Copy page structure**, a list of box ids and labels with no contents, so the layout can
be added. Never guess into unrecognised boxes.

**Rule 4.3 — New injury.** A visit counts as a **new injury** only when the clinician explicitly
says the patient has a new injury **compared with the last visit** AND says to **"document it and
evaluate goals"**. When both are said, the note records the injury **in bold**, and the goals are
flagged for re-evaluation, since a new injury may lead to new goals and a new assessment.
Cadence never changes or resets goals by itself. Ordinary pain or soreness is **not** a new injury.
*Status: Planned.*

**Rule 4.4 — Follow-up notes carry the same history.** Daily notes follow the same injuries and
the same goals from the Initial Evaluation. Over several visits a patient may meet some goals and
progress toward others; every follow-up must report progress against the **same goal list**.
*Status:* carry-forward of precautions, functional status, and goals is built; per-goal status
tracking across visits is planned.

**Rule 4.5 — Use Office Ally's structured fields well.** Office Ally layouts support editable
fields, tables, dropdowns, radio buttons, and checkboxes. Fill them only when the clinician's words
map unambiguously to one of the options; otherwise leave them for the clinician. *Status: Planned.*

**Rule 4.6 — Codes.** Cadence's model never writes a CPT or ICD-10 code (see CLAUDE.md, rule 12).
Office Ally's own page forwards the patient's age, sex, and any ICD-10 codes in the form to its
advertising panel. That is Office Ally's behaviour, but it is a reason not to auto-fill diagnosis
codes.

---

## 5. Privacy and security

**Rule 5.1 — Office Ally is a sanctioned destination; the practice has a BAA with Office Ally.**
Only the extension, only into the clinician's open tab, only saved and reviewed notes. See
CLAUDE.md "Non-negotiable constraints".

**Rule 5.2 — Cadence never stores Office Ally credentials.** No username or password in Cadence,
the extension, code, or docs. Clinicians may use Chrome's password manager. A password that has
appeared in a screenshot, chat, or document must be **changed** in Office Ally.

**Rule 5.3 — Never commit saved Office Ally pages.** A saved page (Ctrl+S) contains patient
details and session tokens. `evals/Ingestion/` is git-ignored for this reason.

**Rule 5.4 — Patient data stays local.** Cadence runs entirely on the laptop. The extension talks
only to Cadence at `http://127.0.0.1:8420` and to the Office Ally page in the browser.

---

## 6. Growth

**Rule 6.1 — More practices, same structure.** A second company may be added. The structure above
(Patient ID linking, layout per note type, one encounter per day, routing by meaning) stays the
same; only layout names and ids change. Keep those in one table (`REQUIRED_LAYOUT` in
`extension/lib/oaroute.js`) rather than scattered through the code.

---

## Where each rule lives in the code

| Rule | Code | Tests |
|---|---|---|
| 2.1 Layout per note type | `oaroute.js` → `REQUIRED_LAYOUT`, `checkLayout` | `extension/tests/oaroute.test.js` |
| 3.1 Patient ID = MRN | `oaroute.js` → `checkPatient` | same |
| 3.2 Encounter date = note date | `oaroute.js` → `noteDate`, `checkEncounterDate` | same |
| 3.3 One encounter per day | `oaroute.js` → `parseEncounters`, `checkSameDayEncounters`; `content.js` → `loadEncounters` | same |
| 4.1 / 4.2 Routing, 2,000 limit | `oaroute.js` → `planRouting` | same |
| 1.1 Save draft, never sign | `content.js` → `fill`, `findApplyButton` | `extension/tests/e2e/run_oa_page_test.py` |
| 1.5 Read back + saved-note check | `oaroute.js` → `sameText`, `verifyBoxes`; `content.js` → `fill`, `savedCheck`; `background.js` → `verifyAfterSave`, `verifyPending` | `oaroute.test.js`; e2e 11, 12 |
| 3.5 One encounter per note | `background.js` → `noteEncounterGet/Set`; `content.js` → `noteEncounterCheck`; `bridge.js`; `app.js` → `noteEncounter` | e2e 13 |
| 1.3 Send to Office Ally | `app/ui/static/app.js` → `sendToOfficeAlly`; `extension/bridge.js`; `/api/extension/info` | `tests/test_release_packaging.py` (extension ships) |
| 1.4 Logged in | `oaroute.js` → `pageKind`, `looksLoggedOut`; `content.js` → `loadEncounters` | `extension/tests/oaroute.test.js` |

All checks run when a note is loaded into the panel, and again when **Fill** is clicked, so a date
or layout changed in between is caught.

---

## Testing against a real Office Ally page

`extension/tests/e2e/run_oa_page_test.py` runs the real, unmodified extension code in headless
Chrome against an Office Ally page saved into the git-ignored `evals/Ingestion/` folder. Office
Ally's own scripts are removed, and all outside network access is blocked, so the test never
contacts Office Ally. It checks 13 scenarios on the practice's two real forms (Progress Notes and
Cadence Init Eval): same-day fill + draft save, another day (date set), existing encounter
(blocked), wrong template both ways (blocked), wrong patient (blocked), long section split without
truncation, every Initial Evaluation section in its box, read-back + saved-note check after the
save (all match / one box lost), a note already sent to another encounter (warned), and
unrecognised layout (nothing touched). Run it after any change to `extension/`:

    .venv/Scripts/python.exe extension/tests/e2e/run_oa_page_test.py

The test's local web server must speak HTTP/1.1: with Python's default HTTP/1.0, Chrome and Edge
on the dev machine stalled on about half the runs (the page arrived but never finished loading),
which showed up as "Chrome never reported", never as a wrong result.
