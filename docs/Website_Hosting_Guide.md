# Moving sdmobilept.com to the new website

Step-by-step guide for putting the new website (`website/` in this project) online at
**www.sdmobilept.com**, with the Cadence page at **cadence.sdmobilept.com**. About 45 minutes of
clicking, then up to a day for the internet to catch up (usually under an hour).

---

## What you have today (checked 2026-09-28)

| Piece | Where it lives | Change? |
|---|---|---|
| **Domain name** sdmobilept.com (registration, renewal) | **Squarespace Domains** (moved there from Google Domains) | **Keep.** You still need it. |
| **DNS** (the address book that says where the site and email are) | Squarespace Domains | **Edit 2–3 records** (Step 3) |
| **Website** www.sdmobilept.com | **Google Sites** (`www` → `ghs.googlehosted.com`) | **Replace** with Netlify |
| sdmobilept.com (no www) | Squarespace forwards it to www (records `198.49.23.144/145`, `198.185.159.144/145`) | **Replace** with Netlify |
| **Email** info@sdmobilept.com | **Google Workspace** (MX `smtp.google.com`, TXT `v=spf1 include:_spf.google.com ~all`) | **DO NOT TOUCH** |
| Booking calendar, patient forms (Google Drive) | Google Workspace | Unchanged — the new site links to them |

**Squarespace is not hosting your website** — only your domain. And Squarespace can't host a
custom-built site like this one, so the site goes on **Netlify** (free, secure, fast). You keep
paying Squarespace only for the domain.

**Google Sites:** you won't need it once the new site is live (Step 5). Keep it untouched until then
— it is your fallback.

---

## Step 1 — Create a free Netlify account (5 min)

1. Go to **app.netlify.com/signup**.
2. Sign up with the **practice Google account** (the one for info@sdmobilept.com), so the practice —
   not one person — owns the site.
3. Skip any questions about teams or plans. The **Free** plan is enough.

## Step 2 — Upload the site (5 min)

1. In Netlify: **Add new site → Deploy manually**.
2. Open File Explorer at `C:\Users\localuser\Cadence\` and **drag the whole `website` folder** onto
   the upload box.
3. Netlify gives the site a temporary address like `https://gentle-otter-12345.netlify.app`.
   **Write it down** — you need it in Step 3.
4. Rename it so it's easy to recognise: **Site configuration → Change site name** → e.g.
   `sdmobilept`. The address becomes `https://sdmobilept.netlify.app`.
5. **Check it:** open that address. Try the menu, **Book a visit**, the three forms, and
   `https://sdmobilept.netlify.app/cadence/`.

Nothing public has changed yet — patients still see the old site.

## Step 3 — Connect your domain (15 min)

### 3a. Tell Netlify about your addresses
1. In Netlify: **Domain management → Add a domain** → type `www.sdmobilept.com` → **Verify** →
   **Add domain**. When asked, also add `sdmobilept.com`.
2. **Add a domain** again → `cadence.sdmobilept.com` (add it as a **domain alias**).
3. Netlify now shows "Awaiting External DNS" and tells you the records to create. They should match
   the table below — **if Netlify shows different values, use Netlify's**.

### 3b. Change the records in Squarespace
Go to **account.squarespace.com → Domains → sdmobilept.com → DNS** (sometimes "DNS Settings").

**First, remove the forwarding** of sdmobilept.com → www:
- If there is a **Domain forwarding** / **Forwarding** rule for `sdmobilept.com`, **delete it**.
- In the DNS records, delete the four **A** records for `@` pointing to `198.49.23.144`,
  `198.49.23.145`, `198.185.159.144`, `198.185.159.145` (they may be grouped as
  "Squarespace Defaults" — delete that group).

**Then set these records:**

| Type | Host / Name | Value / Data | What it does |
|---|---|---|---|
| **A** | `@` | `75.2.60.5` | sdmobilept.com → Netlify |
| **CNAME** | `www` | `sdmobilept.netlify.app` *(your Netlify address from Step 2, without https://)* | **Edit** the existing www record (it now says `ghs.googlehosted.com`) |
| **CNAME** | `cadence` | `sdmobilept.netlify.app` | New: cadence.sdmobilept.com |

**Leave everything else exactly as it is** — especially:
- **MX** `smtp.google.com` (your email)
- **TXT** `v=spf1 include:_spf.google.com ~all` (your email)
- any **TXT** starting `google-site-verification=`

Click **Save**.

### 3c. Wait, then turn on the padlock (https)
1. Back in Netlify → **Domain management**, click **Verify DNS configuration** every 10–15 minutes.
   Usually done within an hour; can take up to 24 hours.
2. When the domains show as verified, go to **HTTPS → Verify DNS / Provision certificate**. Netlify
   gets a free certificate (Let's Encrypt) and renews it automatically.

## Step 4 — Check everything (10 min)

Open each in a private/incognito window:

- [ ] `https://www.sdmobilept.com` — the new site, with the padlock
- [ ] `https://sdmobilept.com` — goes to www
- [ ] `https://www.sdmobilept.com/book/` — booking calendar shows your times
- [ ] Intake form, ABN English, ABN Español open
- [ ] `https://cadence.sdmobilept.com` — the Cadence page
- [ ] **Send a test email** to info@sdmobilept.com from another account, and reply to it — email
      must still work both ways
- [ ] On your phone: the site looks right and the menu opens

## Step 5 — Retire the old Google Site (after a week of the new site working)

1. **sites.google.com** → open the old site → **Settings (gear) → Custom domains** → remove
   `www.sdmobilept.com`.
2. Optionally **Unpublish** it. You can keep the draft as a record; it costs nothing.
3. **Do not delete** the forms in Google Drive — the new site links to them.

## Step 6 — Check what you pay Squarespace

In **account.squarespace.com → Billing**:
- Keep the **domain registration** for sdmobilept.com and turn on **auto-renew** — if it lapses, the
  website AND email stop.
- If you're paying for a Squarespace **website plan** you never used, you can cancel that plan.
  (Only cancel a *website* subscription, never the *domain*.)

---

## Updating the site later

1. Edit the files in `C:\Users\localuser\Cadence\website\` (or ask Claude to).
2. Preview at `http://127.0.0.1:8430/`.
3. In Netlify → **Deploys**, drag the `website` folder onto the box again. Live in seconds. Netlify
   keeps every previous version — **Deploys → (an older one) → Publish deploy** undoes a change.

*Optional later:* connect Netlify to the GitHub repository (base directory `website`) so every push
publishes automatically.

## If something goes wrong

- **Site down after the DNS change:** in Squarespace, set the `www` CNAME back to
  `ghs.googlehosted.com` — the old Google Site comes back. Then ask for help.
- **Email stopped:** the MX or TXT records were changed. Put back **MX `smtp.google.com`**
  (priority 1) and **TXT `v=spf1 include:_spf.google.com ~all`**.
- **"Not secure" warning:** the certificate isn't issued yet — wait for Step 3c to finish.

## Notes

- The site files are plain HTML/CSS: `index.html` (patients), `book/` (booking), `cadence/`
  (clinicians), `assets/site.css` (design), `_redirects` (tells Netlify that
  cadence.sdmobilept.com shows the Cadence page and that sdmobilept.com goes to www).
- The Cadence page is **public** (it contains no patient data and no passwords). The Cadence
  **download** itself stays private: it links to the practice's Google Drive folder shared only
  with clinicians.
- No patient data is ever on the website. The booking calendar is Google's (covered by the
  practice's Google Workspace agreement).
