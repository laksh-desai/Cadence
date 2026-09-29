# Moving sdmobilept.com to the new website

Step-by-step guide for putting the new website (`website/` in this project) online at
**www.sdmobilept.com**, with the Cadence page at **cadence.sdmobilept.com**, on **Cloudflare Pages**
(free, unlimited visitors). About 30 minutes of clicking, then up to a day for the internet to catch
up (usually under an hour).

---

## What you have today (checked 2026-09-28)

| Piece | Where it lives | Change? |
|---|---|---|
| **Domain name** sdmobilept.com (registration, renewal) | **Squarespace Domains** (moved there from Google Domains) | **Keep.** |
| **DNS** (the address book saying where the site and email are) | Squarespace Domains | **Edit 1 record, add 1** (Step 3) |
| **Website** www.sdmobilept.com | **Google Sites** (`www` → `ghs.googlehosted.com`) | **Replace** with Cloudflare Pages |
| sdmobilept.com (no www) | Squarespace **forwards** it to www | **Keep as is** — it will forward to the new site |
| **Email** info@sdmobilept.com | **Google Workspace** (MX `smtp.google.com`, TXT `v=spf1 include:_spf.google.com ~all`) | **DO NOT TOUCH** |
| Booking calendar, patient forms (Google Drive) | Google Workspace | Unchanged — the new site links to them |

Squarespace is **not hosting your website** — only your domain — and it can't host a custom-built
site. You keep paying Squarespace only for the domain.

**Google Sites:** not needed once the new site is live (Step 5). Leave it untouched until then — it is
your fallback.

### Why Cloudflare Pages
Free with **unlimited visitors and bandwidth**, business use allowed, free https, drag-and-drop
updates (500 a month), no credit card. And you keep your DNS at Squarespace — no moving nameservers,
so your email is never at risk.

---

## Step 1 — Create a free Cloudflare account (5 min)

1. Go to **dash.cloudflare.com/sign-up**.
2. Sign up with **info@sdmobilept.com** (the practice account), so the practice — not one person —
   owns the site. Confirm the email Cloudflare sends.
3. If it asks to "add a site/domain" — **skip it**. You are NOT moving your domain to Cloudflare.

## Step 2 — Upload the site (5 min)

1. In the Cloudflare dashboard: **Workers & Pages** (left menu) → **Create** → **Pages** tab →
   **Upload assets** (a.k.a. Direct Upload).
2. **Project name:** `sdmobilept` → **Create project**.
3. Drag the whole folder `C:\Users\localuser\Cadence\website` onto the upload box → **Deploy site**.
4. You get a test address: **`https://sdmobilept.pages.dev`** (if the name was taken, Cloudflare
   adds letters — **write down the exact address**; you need it in Step 3).
5. **Check it:** open that address. Try the menu, **Book a visit**, the three forms, and
   `https://sdmobilept.pages.dev/cadence/`.

Nothing public has changed yet — patients still see the old site.

## Step 3 — Connect your addresses (10 min)

### 3a. www.sdmobilept.com
1. In Cloudflare: your **sdmobilept** project → **Custom domains** → **Set up a custom domain** →
   type `www.sdmobilept.com` → **Continue**.
2. Cloudflare says your DNS is elsewhere and shows **"Begin CNAME setup"**: a CNAME record for
   `www` pointing to `sdmobilept.pages.dev`. Keep this page open.
3. In another tab: **account.squarespace.com → Domains → sdmobilept.com → DNS** (or "DNS Settings").
4. Find the **CNAME** record with host **`www`** — it currently says **`ghs.googlehosted.com`**.
   **Edit** it and change the value to **`sdmobilept.pages.dev`** (your address from Step 2, without
   `https://`). **Save.**
5. Back in Cloudflare, click **Check DNS records / Activate domain**.

### 3b. cadence.sdmobilept.com
1. Same project → **Custom domains** → **Set up a custom domain** → `cadence.sdmobilept.com`.
2. In Squarespace DNS, **add** a record:

   | Type | Host / Name | Value / Data |
   |---|---|---|
   | **CNAME** | `cadence` | `sdmobilept.pages.dev` |

3. **Save**, then back in Cloudflare **Activate domain**.

(The site sends anyone arriving at cadence.sdmobilept.com straight to the Cadence page.)

### 3c. Leave everything else exactly as it is
In Squarespace **do not change or delete**:
- **MX** `smtp.google.com` — your email
- **TXT** `v=spf1 include:_spf.google.com ~all` — your email
- any **TXT** starting `google-site-verification=`
- the **forwarding** of `sdmobilept.com` → `www.sdmobilept.com` (and its `198.x` A records) — it keeps
  working and now forwards to the new site

### 3d. Wait for "Active"
In Cloudflare → **Custom domains**, both domains change from "Verifying"/"Pending" to **Active**
(usually minutes, up to 24 hours). Cloudflare issues the free https certificate automatically.

## Step 4 — Check everything (10 min)

Open each in a private/incognito window:

- [ ] `https://www.sdmobilept.com` — the new site, with the padlock
- [ ] `sdmobilept.com` (typed without www) — lands on the new site
- [ ] `https://www.sdmobilept.com/book/` — booking calendar shows your times
- [ ] Intake form, ABN English, ABN Español open
- [ ] `https://cadence.sdmobilept.com` — the Cadence page
- [ ] **Send a test email** to info@sdmobilept.com from another account, and reply — email must still
      work both ways
- [ ] On your phone: the site looks right and the menu opens

## Step 5 — Retire the old Google Site (after a week of the new site working)

1. **sites.google.com** → open the old site → **Settings (gear) → Custom domains** → remove
   `www.sdmobilept.com`.
2. Optionally **Unpublish** it. Keeping the draft costs nothing.
3. **Do not delete** the forms in Google Drive — the new site links to them.

## Step 6 — Check what you pay Squarespace

**account.squarespace.com → Billing**:
- Keep the **domain registration** and turn on **auto-renew** — if the domain lapses, the website AND
  email stop.
- If you pay for a Squarespace **website plan** you never used, you can cancel that plan. (Only a
  *website* subscription — never the *domain*.)

---

## Updating the site later

1. Edit the files in `C:\Users\localuser\Cadence\website\` (or ask Claude to).
2. Preview at `http://127.0.0.1:8430/`.
3. Cloudflare → **Workers & Pages → sdmobilept → Create deployment** (or "Upload assets") → drag the
   `website` folder again → **Deploy**. Live in under a minute.
4. Every version is kept: **Deployments → (an older one) → ⋯ → Rollback** undoes a change.

*Optional later:* connect the project to the GitHub repository (root directory `website`) so every
push publishes automatically.

## If something goes wrong

- **Site down after the DNS change:** in Squarespace set the `www` CNAME back to
  `ghs.googlehosted.com` — the old Google Site comes back.
- **Email stopped:** the MX or TXT records were changed. Put back **MX `smtp.google.com`**
  (priority 1) and **TXT `v=spf1 include:_spf.google.com ~all`**.
- **"Not secure" warning:** the domain isn't Active yet in Cloudflare — wait for Step 3d.

## Notes

- Site files: `index.html` (patients), `book/` (booking), `cadence/` (clinicians),
  `assets/site.css` (design). Plain HTML/CSS — no build step.
- The Cadence page is **public** (no patient data, no passwords). The Cadence **download** stays
  private: it links to the practice's Google Drive folder shared only with clinicians.
- No patient data is ever on the website. The booking calendar is Google's (covered by the practice's
  Google Workspace agreement).
