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
