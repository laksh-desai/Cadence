# Dictating from the phone or tablet — setup

Send a visit's dictation from the **iPhone** or the **Android tablet** without opening Cadence.
Cadence (on the laptop, while it is running) picks it up and writes the note. Each one appears in
**Notes in progress** under a new patient called **Unknown patient**, with the **visit date in the
DOB column**. Open it, review it, rename the patient to the real one (All Patients → edit), and
**Save**.

Two ways to send. Use either, or both.

| | Option 1 — Email | Option 2 — Google Form (recommended for phones) |
|---|---|---|
| On the phone | Gmail app, signed in as a practice account | A home-screen shortcut to a practice Google Form |
| Can send a voice recording? | Typed or pasted text | **Yes**, attach a recording, or type |
| Setup | ~5 minutes (an app password) | ~20 minutes (form + a Google Cloud service account) |
| Where the data sits | Gmail in the practice Workspace | Forms / Sheets / Drive in the practice Workspace |

Both stay inside **Google Workspace, which the practice's Google BAA covers**. Cadence copies the
dictation onto the laptop and nowhere else. Recordings are transcribed **on the laptop** by MedASR.

## HIPAA rules for sending (please read)

- **Send only from a practice (@sdmobilept.com) account**, never a personal Gmail, iCloud or other
  account. The BAA covers only the Workspace account. Cadence ignores anything from another domain.
- **Do not use the keyboard's microphone button** (Gboard voice typing, Apple dictation) to speak
  into the email or form. That sends the audio to Google's or Apple's speech service, which the BAA
  does not cover. Instead, **record with the phone's recorder app and attach the file** (Option 2),
  or type.
- Keep names out of the subject line where you can. The dictation body can contain what a normal
  note contains.
- The phone/tablet needs a screen lock, and should be signed in to the Workspace account only.

---

## Option 1 — Email (~5 minutes)

**1. Allow IMAP for the mailbox** (admin, one time). In **admin.google.com → Apps → Google
Workspace → Gmail → End User Access**, make sure **IMAP access** is on.

**2. Create an app password** for info@sdmobilept.com:
1. Sign in to **myaccount.google.com** as info@sdmobilept.com.
2. **Security → 2-Step Verification** must be ON (turn it on if needed).
3. **Security → 2-Step Verification → App passwords** (or search "App passwords") → name it
   "Cadence" → **Create**. Copy the 16-letter password.
   *If "App passwords" is missing, the Workspace admin has disabled them (Admin console → Security
   → Authentication → allow users to manage less secure apps / app passwords). Then use Option 2.*

**3. In Cadence → Manage Office → Dictation from phone or email:**
- Tick **Check these mailboxes**. info@sdmobilept.com is already listed; paste the app password.
- **+ Subscribe another mailbox** adds more (each needs its own app password).
- "Accept senders from" defaults to `sdmobilept.com`. You can list exact addresses instead.
- **Save → Test connection** should say ✓ Connected.

**4. To send a note**, email info@sdmobilept.com **from a practice address**:
- **Subject** must contain **Cadence**, plus the visit date, e.g. `Cadence 10/14/2026`.
  Add `eval`, `re-eval` or `discharge` for those note types (otherwise it's a Daily Visit).
- **Body:** the dictation (or a written note). The visit date may also go in the body
  (`Visit date: 10/14/2026`).

Cadence checks every 2 minutes (adjustable), marks the email as read once queued, and never
processes the same email twice.

---

## Option 2 — Google Form (~20 minutes, recommended for phones)

**1. Make the form** (forms.google.com, signed in as a practice account), named "Cadence dictation":
- **Visit date**: *Date* question, required
- **Note type**: *Multiple choice*: Daily Visit, Initial Evaluation, Re-evaluation / Progress
  Report, Discharge Summary
- **Dictation**: *Paragraph*, not required
- **Audio recording**: *File upload*, not required, allow **Audio**, max 1 file, 100 MB
- **Settings → Responses:** **Collect email addresses = Verified**, and **Restrict to users in
  SD Mobile PT** (your domain). This keeps every submission inside the Workspace.
- **Responses tab → Link to Sheets → Create a new spreadsheet.** Open it and copy its link.

**2. A Google service account** (one time; also used by the optional roster sync):
1. **console.cloud.google.com** (practice account) → create a project "Cadence".
2. **APIs & Services → Enable APIs:** enable **Google Sheets API** and **Google Drive API**.
3. **IAM & Admin → Service accounts → Create** → name "cadence-intake" → **Keys → Add key → JSON**.
   A `.json` file downloads.
4. Save that file on the laptop as
   `C:\Users\localuser\Cadence\app\integrations\.sheets_credentials.json` (git-ignored).
5. Copy the service account's email (…@….iam.gserviceaccount.com). **Share** with it:
   - the responses **Sheet** → **Editor** (Cadence writes a "Cadence status" column)
   - the form's upload folder in Drive (**My Drive → "Cadence dictation (File responses)"**) →
     **Viewer**

**3. In Cadence → Manage Office:** tick **Check the form responses**, paste the **Sheet link**,
keep the tab name `Form Responses 1`, then **Save → Test connection**.

**4. Put it on the phone and tablet:**
- **iPhone (Safari):** open the form link → Share → **Add to Home Screen**.
- **Android tablet (Chrome):** open the form link → ⋮ → **Add to Home screen**.

**5. To send a note:** open the shortcut, pick the date and note type, then either **attach a
recording** (iPhone: Voice Memos → … → Save to Files, then attach; Android: the Recorder app's
file) or type the dictation, and **Submit**. Within a couple of minutes it's in Cadence. The Sheet's
"Cadence status" column says **Queued in Cadence** with the time.

---

## What happens in Cadence

1. While Cadence is running, each source is checked every 2 minutes. **The laptop must be on with
   Cadence started.** Anything sent while it's off is picked up the next time it starts.
2. Each submission → a new **Unknown patient** (visit date in DOB) → the note is written and waits
   in **Notes in progress**. Daily Visit unless the subject or form says otherwise.
3. You review, rename the patient (or move the note's content to the real patient), and **Save**.
4. Nothing is saved without you. If Cadence restarts before you save, the submission is picked up
   again automatically.

**Manage Office** shows when each source was last checked and what was found; **Status** shows
whether intake is on. **Check now** checks immediately.

## Troubleshooting

| Message | Fix |
|---|---|
| "Google refused the sign-in" | Use the **app password**, not the normal password; check IMAP is on (Option 1 step 1) |
| "Google refused access" (Form) | Share the Sheet (Editor) and the upload folder (Viewer) with the service-account email; enable Sheets + Drive APIs |
| "Sheet not found" | Re-paste the Sheet link; tab should be `Form Responses 1` |
| Note shows "the uploaded recording could not be transcribed" | Record as M4A/MP3/WAV; very long recordings: split the visit |
| Nothing arrives | Is Cadence running? Subject contains "Cadence"? Sent from an @sdmobilept.com account? |
