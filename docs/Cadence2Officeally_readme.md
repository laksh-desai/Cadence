# Cadence → Office Ally: Setup and Daily Use

> **Clinicians:** use the one-page [Clinician_Guide_Send_to_Office_Ally.md](Clinician_Guide_Send_to_Office_Ally.md).
> Cadence's **Send to Office Ally** button now does the setup (Part 1) and the patient linking
> (Part 3) on screen, and pre-selects the note in the extension. This document is the detailed
> reference for whoever installs and supports Cadence.

This guide shows how to move a finished Cadence note into Office Ally with one click, using the
**Cadence → Office Ally** Chrome extension. No technical background is needed. Follow the parts
in order the first time; after that, only **Part 5** is needed for each visit.

---

## What this does, and why

After each visit you dictate a note in Cadence. Office Ally is where the note has to end up. Before
this tool, that meant copying each section by hand into the right Office Ally box.

The extension does that copying for you:

- It reads a **saved** note from Cadence on this laptop.
- It works out which Office Ally box each section belongs in. Cadence and Office Ally organise a
  note differently, so it matches sections by meaning, not by position.
- It types the text into those boxes on the Office Ally page you have open.

**What it never does:**
- It saves a note only as a DRAFT (Office Ally's Apply), only after every box reads back correctly, and then re-checks the saved boxes. It never submits or signs. **You review and sign every note yourself.**
- It never stores your Office Ally username or password. It works inside the Office Ally tab you
  are already logged in to.
- It never sends anything to the internet. It only talks to Cadence on this laptop and the Office
  Ally page in your browser. The practice has a Business Associate Agreement (BAA) with Office Ally.

---

## Part 1 — Add the extension to Chrome (one time, about 2 minutes)

The extension is a small add-on that lives in your Cadence folder. It is not in the Chrome Web
Store, because it is a private tool for your practice, so Chrome has to be told where to find it.

1. **Open Chrome's extensions page.** Type `chrome://extensions` in the address bar and press
   Enter.

2. **Turn on "Developer mode".** It is a switch in the **top-right corner** of that page.
   *Why:* Chrome only allows extensions from the Web Store unless Developer mode is on. Turning it
   on lets Chrome load an extension from a folder on your computer. Nothing is published anywhere.

3. **Click "Load unpacked".** This button appears at the **top-left** only after step 2.

4. **Select the extension folder.** In the window that opens, go to:
   ```
   C:\Users\localuser\Cadence\extension
   ```
   Click once on the **`extension`** folder to highlight it. Do not open it or pick a file inside.
   Then click **Select Folder**.

   A card called **"Cadence → Office Ally"** now appears. It has a **Reload** button (a circular
   arrow), which you only need when the extension is updated (see Part 7).

5. **Pin it to the toolbar.** Click the **puzzle-piece icon** at the top-right of Chrome, find
   **"Cadence → Office Ally"**, and click the **pin** next to it. The Cadence icon now stays next to
   the address bar, so opening it is one click.

---

## Part 2 — Make sure Cadence is running

The extension gets each note from Cadence, so Cadence must be running whenever you use it.

1. Start Cadence with its **desktop shortcut**.
2. Check it by opening `http://127.0.0.1:8420` in Chrome. You should see the Cadence home page.

If Cadence is not running, the extension panel says **"Couldn't reach Cadence"**.

---

## Part 3 — Link each patient to their Office Ally chart (once per patient)

The extension checks that the Cadence patient and the open Office Ally chart are the **same
person**. It refuses to fill anything if they are not. This is the most important safety check: it
makes it impossible to put a note into the wrong patient's chart.

The link is the **Office Ally Patient ID**, stored in Cadence in the patient's **MRN** box.

1. **Find the Patient ID in Office Ally.** Open the patient's chart. The header at the top shows
   **Patient ID** (for example `155793457`). It is also in the page address as `PID=155793457`.
2. **Enter it in Cadence.** On Cadence's **Home** tab, select the patient and click **Edit** (or
   use **+ New** for a new patient). Type the Patient ID into the **MRN** box and save.

You only do this once per patient. After that, when you open that patient's chart in Office Ally
and click the Cadence icon, the panel selects the right Cadence patient for you.

---

## Part 4 — Practise on the fake Office Ally page (recommended the first time)

A practice page with the same boxes as the Office Ally **Progress Notes** form comes with the
extension. It holds no real chart data and cannot save anything, so it is a safe place to see how
the extension behaves.

1. **Start the practice page.** Open **PowerShell** (Start menu → type "PowerShell" → Enter),
   paste this line, and press Enter:
   ```
   cd C:\Users\localuser\Cadence\extension; ..\.venv\Scripts\python.exe -m http.server 8080
   ```
   Leave this window open while you practise. Close it when you are done.
   *Why:* this makes the practice page available in Chrome on this laptop only.

2. **Open the practice page** in Chrome:
   ```
   http://localhost:8080/test-oa-form.html?PID=155793457
   ```
   Replace `155793457` with the Patient ID of any Cadence patient who has a saved note.

3. **Click the Cadence icon** in the toolbar. A panel opens on the right. It should show
   **"Office Ally Patient ID 155793457"** and select the matching patient.

4. **Choose the saved note**, check the preview (see Part 6), and click **Fill & save draft**.
   On the practice page:
   - Set the **SOAP Note Layout** dropdown to match the note (**Cadence Init Eval** for an Initial
     Evaluation, **Progress Notes** for a Follow-Up). Otherwise the fill is blocked with "Template
     mismatch" — which is the rule working.
   - The **Encounter Date** defaults to today. Change it to see "Date mismatch" block the fill.
   - The practice page has no real encounter list, so "Only one encounter" shows **?**. The first
     click warns; click **Fill & save draft** again to continue.

5. **Look at the filled boxes.** The **Update** button on this page only shows a message; it
   saves nothing.

---

## Part 5 — Everyday use with a real patient

The binding rules behind these steps are in
[OfficeAlly_Integration_Rules.md](OfficeAlly_Integration_Rules.md).

1. **In Cadence:** generate the note, review it, and click **Save** — **on the day of the visit**.
   The extension only works with saved notes, and the note's date is the day it was saved. That
   date must match the Office Ally encounter's date.

2. **In Office Ally, open ONE encounter for that date.** Use **Send to Office Ally → Create … note**
   (it opens Add Note on the right layout), or open that day's existing encounter from the chart:
   - **Cadence Init Eval** for an Initial Evaluation
   - **Progress Notes** for a Follow-Up Visit

   **Office Ally creates an encounter the moment its Add Note page opens** — before anything is
   saved. Every extra Add Note is an extra blank encounter in the chart, so open it once per note.
   Cadence remembers each note's encounter and warns before a second one.

3. **Click the Cadence icon.** The panel selects the patient for you (from the Patient ID). Pick
   the **saved note** from the list.

4. **Read the checks at the top of the panel.** Each shows ✓ (fine), ✕ (blocked — the reason is
   underneath), or ? (couldn't be checked — look yourself):
   - Patient ID matches MRN
   - Layout matches note type
   - Encounter date = note date
   - Only one encounter on that date

   Any ✕ means nothing will be filled until it's fixed. The extension never changes the layout or
   date for you.

5. **Check the preview** under **"Automatic fill — where each section will go"** (see Part 6).

6. **Click "Fill & save draft".** All checks run again at this moment, in case something changed.
   The extension fills each box, **reads every box back** (a box that didn't keep its text is named
   and nothing is saved), clicks Office Ally's **Apply** to save a draft, and after the page reloads
   **checks the saved note box by box** — "Saved and checked: all N boxes match Cadence". If the
   panel doesn't reopen by itself, click the Cadence icon and the same check runs.

7. **Review every box in Office Ally, then sign it yourself.** Cadence never signs.

---

## Part 6 — Reading the preview

Before filling, the panel shows each Office Ally box it will use, which Cadence sections go into
it, and its character count, for example:

```
Assessment                     1,432 / 2,000
Diagnoses · Assessment Summary
```

- **Every Office Ally box holds at most 2,000 characters.** The extension never goes over that and
  never cuts text off. Office Ally counts each line break as two characters when it saves, and so
  does the extension.
- **Sections go in whole, each labelled with its Cadence heading.** When a box is full, the next
  section moves whole to the next suitable box, e.g. **Assessment → Assessment (Cont)**.
- **A very long section** is split only at the end of a sentence, and the second part is labelled
  **"(cont.)"**.
- **A red "Not placed" line** means a section did not fit anywhere. Copy that section from Cadence
  into Office Ally by hand, and tell the Cadence developer which one it was.

**How it decides where a section goes:**
1. A box the practice has **named** for that topic, e.g. a box labelled "Medications".
2. Otherwise, Office Ally's **built-in** box for it: Chief Complaints, Functional Status, Goal
   Notes, Plan Notes, Procedure Notes.
3. Otherwise, the **general box** for its part of the note: Subjective → History Of Present
   Illness, Objective → Objective Notes, Assessment → Assessment, Plan → Plan Notes.

It matches by meaning, not just by words. "Musculoskeletal Assessment" is exam findings, so it
goes to **Objective**, not Assessment. "Therapeutic Exercise" done today goes to **Procedure
Notes**, not "Exercises (Continue)".

Example on the **Progress Notes** layout:

| Cadence section | Office Ally box |
|---|---|
| Chief Complaint | Chief Complaints |
| Medications, Allergies, Relevant History | History Of Present Illness (each labelled) |
| Diagnoses, Assessment Summary | Assessment → Assessment (Cont) if full |
| Musculoskeletal, Fall Risk, Vitals | Objective Notes |
| Functional Mobility | Functional Status |
| Short-Term and Long-Term Goals | Goal Notes → Goals (Continue) if full |
| Plan of Treatment | Plan Notes |

---

## Built-in safety checks

| When you click Fill… | What happens | Why |
|---|---|---|
| The chart's Patient ID ≠ the patient's MRN in Cadence | Nothing is filled; the panel says "Wrong chart" | A note must never go into the wrong chart |
| Wrong layout: an Initial Evaluation not in **Cadence Init Eval**, or a Follow-Up not in **Progress Notes** | Nothing is filled; the panel says "Template mismatch" and which layout to choose. It never switches the layout for you. | Practice rule 2.1 |
| The encounter's **Encounter Date** ≠ the Cadence note's date | Nothing is filled; the panel says "Date mismatch" | Each encounter belongs to one visit date (rule 3.2) |
| Office Ally already has **another encounter on the same date** | Nothing is filled; the panel names that encounter. Delete the older one in Office Ally, then retry. | Only one encounter per patient per day (rule 3.3) |
| The encounter list couldn't be read | The first click only warns; check the Encounters list yourself, then click again | Cadence can't confirm there's only one encounter that day |
| The patient has no MRN in Cadence | Nothing is filled; the panel tells you which ID to enter | The link hasn't been made yet (Part 3) |
| The note still has unresolved `[! …]` gaps | The first click only warns; a second click fills anyway | Unfinished items shouldn't reach the chart unnoticed |
| An Office Ally box already has different text | That box is left alone and named in the message | Never overwrite what someone typed |
| A filled box is in a collapsed section | The section is opened | Every filled box should be seen and reviewed |
| Always | Never clicks Update, Apply, Save, or Sign | The clinician reviews and signs every note |

---

## Part 7 — When the extension is updated

When the extension's files change (for example after the developer improves the routing):

1. Go to `chrome://extensions`.
2. On the **"Cadence → Office Ally"** card, click the **Reload** button (circular arrow).
3. Refresh any open Office Ally tab before using the extension again.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| "Couldn't reach Cadence" | Start Cadence (Part 2). |
| "Wrong chart…" or "has no Office Ally Patient ID" | Put the chart's Patient ID in the patient's MRN box in Cadence (Part 3). |
| "No Office Ally note boxes on this page" | Follow the directions in the panel: open the encounter for the note's date, or create one with the matching layout. Then click the Cadence icon again. |
| "Template mismatch" | Change the **SOAP Note Layout** dropdown in Office Ally to the layout the panel names, then click Fill again. |
| "Date mismatch" | You're in the wrong encounter. Open the encounter dated the same day as the Cadence note (or create it). A note saved in Cadence the day after the visit carries the later date. |
| "Duplicate encounter" | Delete the older encounter for that day in Office Ally, then click the Cadence icon and Fill again. |
| The saved-note list is empty | Save the note in Cadence first (Part 5, step 1). |
| A red "Not placed" line | Copy that section by hand; report which section it was. |
| "Not overwritten (already has text)" | Clear that Office Ally box if you want it replaced, then fill again. |
| Clicking the icon does nothing | Refresh the Office Ally page and click again. If still nothing, reload the extension (Part 7). |
| No "Load unpacked" button | Developer mode is off (Part 1, step 2). |

---

## Security reminders

- **Never type your Office Ally password into Cadence or the extension.** Let Chrome's password
  manager remember it if you want.
- If an Office Ally password has been shared in a screenshot or message, **change it** in Office
  Ally.
- Don't save Office Ally pages (Ctrl+S) into the Cadence folder. A saved page contains patient
  details and login session data.
