# Sending a Cadence Note to Office Ally

Cadence types your finished note into the patient's Office Ally chart, saves it there as a
**draft**, and checks that every box really holds your note. **You still review and sign every
note in Office Ally.** Cadence never signs anything.

---

## Every visit — 5 steps

1. **In Cadence:** dictate, review the note, and click **Save**. Check the **Visit date** beside
   Save is the day of the visit.
2. **Click "Send to Office Ally"** (under the note). Office Ally opens in a new tab, and Cadence
   shows a window with a button for each step. **Log in to Office Ally** in the new tab.
3. **Create the note — once:** click **Create … note**. It opens a new encounter already on the
   right layout (Cadence Init Eval for an Initial Evaluation, Progress Notes for a Follow-Up).
   **Office Ally creates the encounter as soon as this page opens**, so click it only once per
   note. If you click it again, Cadence tells you which encounter this note already has.

   *Logged out part-way?* Log in again and click the button for the step you were on. Nothing is
   lost.
4. **Click the Cadence icon** at the top-right of Chrome. Your note is already selected. When
   every check shows **✓**, click **Fill & save draft**. Cadence:
   - fills each box and reads it back,
   - saves the draft (the page reloads),
   - then checks the saved note box by box. You should see **"Saved and checked: … all boxes match
     Cadence."** If the panel doesn't come back by itself, click the Cadence icon.
5. **Read every box, then sign** in Office Ally as usual.

---

## Only the first time

- **On a new computer:** the first time you click **Send to Office Ally**, Cadence shows a short
  setup (about 2 minutes) to add its Chrome add-on. Follow the steps on screen; they have **Copy**
  buttons, so there's nothing to type.
- **For each new patient:** Cadence asks once for the patient's **Office Ally Patient ID**, the
  number at the top of their Office Ally chart (e.g. `155793457`). You can also enter it when
  adding or editing the patient, in the **Office Ally Patient ID (MRN)** box.

---

## If Cadence stops you

Cadence checks these things so a note never lands in the wrong place. When one fails, **nothing is
filled or saved**, and the panel says what to fix.

| The panel says | What to do |
|---|---|
| **Not logged in / session timed out** | Log in to Office Ally in that tab, open the encounter again, and click the Cadence icon. Office Ally logs you out after a period of inactivity. |
| **Wrong chart** | You're on a different patient's chart. Go back to Cadence and click **Send to Office Ally** again. |
| **Template mismatch** | Change **SOAP Note Layout** in Office Ally to the one named (Cadence Init Eval or Progress Notes), then click **Fill** again. |
| **Date mismatch** | You opened an encounter from a different day. Open the encounter with the same date as the Cadence note. |
| **Duplicate encounter** | The patient already has an encounter that day. Open that one instead. Only one encounter per day is allowed. |
| **? One Office Ally encounter for this note** | This note was already put in (or opened as) a different encounter. Use one of them: click **Fill** again to use this one, then remove the other, blank one in Office Ally. |
| **?** next to "Only one encounter" | Cadence couldn't check. Look at the patient's Encounters list yourself, then click **Fill** again. |
| **Office Ally did NOT keep the text in …** | Those boxes didn't hold the note after filling, so nothing was saved. Click **Fill** again; if it repeats, copy those sections in by hand. |
| **Saved-note check FAILED** | After saving, the named boxes are empty or different in Office Ally. Look for an Office Ally message on the page, then click **Fill** again. |
| **Unresolved gaps** | The note has items marked for you to complete. Fix them in Cadence, or click **Fill** again to fill with them visible. |
| **Not placed** (in red) | That section didn't fit in an Office Ally box. Copy it in by hand. |
| **Not overwritten** | That Office Ally box already had text. Clear it if you want it replaced, and fill again. |

---

*Practice rules behind these checks: [OfficeAlly_Integration_Rules.md](OfficeAlly_Integration_Rules.md).
Detailed setup and troubleshooting for whoever installs Cadence:
[Cadence2Officeally_readme.md](Cadence2Officeally_readme.md).*
