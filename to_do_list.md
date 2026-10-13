# To-do list (Kushang)

Things to do when there's time. Tick `[x]` when done; add new items at the bottom.
Saved 2026-10-03.

---

## 1. Flexible booking for PT / admin (Google Calendar)

The fixed times only limit what **patients** see. Staff signed into the practice calendar can book any time.

- [ ] **Option A — book directly (works today):** calendar.google.com as **info@sdmobilept.com** →
      click the time or **Create → Event** → title "<first name> – PT visit", address in Location
      (no diagnoses) → **Add guests:** patient's email → Save → send invite.
- [ ] **Option B — staff-only flexible booking page (recommended):**
  1. Google Calendar (info@) → **Create → Appointment schedule** → name "Staff booking – flexible".
  2. Availability: wide hours (e.g. Mon–Sun 7 AM–8 PM), slots 30 or 60 min.
  3. Booking settings: Minimum notice **None**, Buffer **0**, no daily limit.
  4. **Save → Share → copy booking page link**.
  5. Give the link to Claude → it replaces the calendar on `website/pt-booking/` (patients keep fixed
     times). Then re-deploy the website to Cloudflare Pages.
- [ ] *(Option C, as needed)* extra hours for one day: edit the appointment schedule →
      **Adjusted availability** → add hours for that date.

## 2. Work calendar ↔ personal/family calendar

> ⚠️ Never copy appointment **details** (patient names, addresses) into personal Gmail. The Google
> BAA covers only the Workspace account (info@). Share **free/busy only** from work → personal. Don't
> forward info@ email to personal Gmail.

- [ ] **Easiest — view both on the phone:** Google Calendar app → profile picture → **Add another
      account** → info@sdmobilept.com. Both calendars in one view, nothing leaves Workspace.
- [ ] **Step 1 — allow free/busy sharing (admin, once):** admin.google.com → Apps → Google Workspace
      → Calendar → Sharing settings → *External sharing options for primary calendars* → **"Only
      free/busy information (hide event details)"** → Save.
- [ ] **Step 2 — work → personal (busy blocks only):** calendar.google.com as info@ → ⚙️ Settings →
      your calendar → **Share with specific people** → kushang@gmail.com → **"See only free/busy
      (hide details)"** → Send. Accept in personal Gmail.
- [ ] **Step 3 — family → work:** calendar.google.com as kushang@gmail.com → ⚙️ Settings → family
      calendar → **Share with specific people** → info@sdmobilept.com → "See only free/busy" (or all
      details) → Send. Accept in info@ (appears under *Other calendars*).
- [ ] **Step 4 — no bookings over family time:** info@ → appointment schedule → **Edit** →
      **"Calendars checked for availability"** → add the family calendar. Patients then see only
      times free on both. (Menu names may differ slightly — screenshot to Claude if stuck.)

## 3. Website follow-ups (from earlier)

- [ ] Send a test email to info@sdmobilept.com from another account and reply — check both ways.
- [ ] Open www.sdmobilept.com/book/ and /pt-booking/ in a real browser — calendar shows times.
- [ ] After a week of the new site working: remove `www.sdmobilept.com` from the old Google Site.
- [ ] Delete the unused Cloudflare Worker `blue-boat-487f`.
- [ ] Squarespace billing: domain auto-renew ON (expires 2027-02-01); cancel any unused website plan.
- [ ] Change the Office Ally password if not done yet.

---

## 4. Pending as of 2026-10-13 (consolidated)

**Done already:** Workspace BAA accepted · laptop Device encryption / BitLocker ON · 2-Step
Verification on info@ · info@ app password saved in Cadence, Test connection ✓ · automatic email
checking ON (every 2 min).

**A. This week (≈30 min)**
- [ ] BitLocker recovery key saved (Microsoft account / USB / printed) — confirm you have a copy.
- [ ] Review the test "Unknown patient — Daily Visit" note in Notes in progress; delete the test
      patient in All Patients if it was only a test.
- [ ] Send one more fake test email (subject `Cadence <date>`, from an @sdmobilept.com account) and
      do NOT click Check now — confirm it appears by itself within ~2 min.
- [ ] admin.google.com → Security → Authentication → 2-step verification → **Enforcement: On**
      (all users, not just info@).
- [ ] admin.google.com → Devices → Mobile & endpoints → Universal settings → Mobile management:
      **Basic**; sign in on the iPhone and the Android tablet and accept the screen-lock prompt.
- [ ] Laptop: Windows Hello sign-in + screen lock after 5 minutes.
- [ ] Reload the Chrome extension (chrome://extensions → ↻) to get the billing audit + new mapping.

**B. Office Ally**
- [ ] Email the 4 layout specs to Office Ally: `templates/OfficeAlly_Initial_Eval_Template.md`,
      `OfficeAlly_Daily_Visit_Template.md`, `OfficeAlly_Reevaluation_Template.md`,
      `OfficeAlly_Discharge_Summary_Template.md`.
- [ ] When they deliver the layouts: enter each SoapLayoutID + name in Manage Office (incl.
      Re-evaluation and Discharge Summary).
- [ ] Ask Office Ally whether the Billing box can feed their charge / superbill screen.

**C. Billing / compliance**
- [ ] Coder sign-off of the ICD-10 tables: run `scripts/coding_signoff.py --out signoff.md`, give
      it to a certified coder; until then every ICD code says "confirm".
- [ ] First REAL dictation end to end on the target 16 GB ThinkPad (not this X1 — it overheats on
      long runs).

**D. Optional — Google Form intake (voice recordings from the phone)**
- [ ] Build the "Cadence dictation" form (visit date, note type, dictation, audio upload; Verified
      email collection; restricted to SD Mobile PT; link to a Sheet).
- [ ] Google Cloud service account (Sheets + Drive APIs, JSON key saved as
      `app/integrations/.sheets_credentials.json`; share Sheet = Editor, upload folder = Viewer).
- [ ] Manage Office → paste Sheet link → tick Check the form responses → Save → Test connection.
- [ ] Add the form to the iPhone and tablet home screens.
  (Steps: `docs/Intake_Setup_Guide.md`.)

**E. Website** (sections 1–3 above still apply)
- [ ] Test email to info@ from an outside account, both directions.
- [ ] Booking calendar shows times on /book/ and /pt-booking/.
- [ ] After a week: remove the custom domain from the old Google Site; delete the Cloudflare
      Worker `blue-boat-487f`; cancel any unused Squarespace website plan (keep the domain).
- [ ] Decide whether the exercise builder's login (SDMPT / Exercises, visible in the page source)
      needs to be stronger.

**F. Housekeeping**
- [ ] Delete the leftover `start_cadence.bat.disabled` from the Cadence folder.
- [ ] Back up Cadence data to a USB stick now and then (`scripts/backup.py`).
