# Cadence — running context (Kushang + Claude)

**This is the living context file.** Every working session appends to it (newest log entry at the
bottom of §9) so work can be picked up later without re-explaining. Older detailed handover:
`docs/kushang_context_Handover.md` (snapshot of 2026-09-28). Project rules: `CLAUDE.md`.

Never put here: passwords, the Office Ally login or company id, patient names/DOB/details, session
data. This file is in git.

Last updated: 2026-10-03 · Branch: `kushang-branch` (GitHub: laksh-desai/Cadence)

---

## 1. What Cadence is
Local, offline note generator for SD Mobile PT (SDMPT). Therapist dictates → MedASR transcribes →
MedGemma 4B (Ollama, CPU) fills the template → clinician reviews → saved notes go to Office Ally via
the Chrome extension. PHI leaves the machine only to Google Workspace and Office Ally (both BAAs).

## 2. Start / stop (no Claude needed)

**Start Cadence** — PowerShell, keep the window open:
```powershell
cd C:\Users\localuser\Cadence
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"
.\.venv\Scripts\python.exe -m uvicorn app.ui.server:app --host 127.0.0.1 --port 8420
```
Open http://127.0.0.1:8420. The offline flags are required (MedASR fails on this network's SSL
otherwise). **Stop:** Ctrl+C or close the window. Save notes first — "Notes in progress" is lost on stop.

**Website preview:**
```powershell
cd C:\Users\localuser\Cadence\website
..\.venv\Scripts\python.exe -m http.server 8430 --bind 127.0.0.1
```
The desktop shortcut (`launcher.py`) does NOT set the offline flags yet — use the commands above.

## 3. Models (Ollama)
| Model | Use | Status |
|---|---|---|
| `williamljx/medgemma-4b-it-Q4_K_M-GGUF` | every note | installed |
| `gemma2:2b` | fast-draft mode | installed 2026-09-29; now **required** in `setup.ps1` + README |

Do not update models casually — a new model changes what notes say; everything was tested on these.
No Python package upgrades either (versions are pinned). Do keep Windows updates on.

## 4. Office Ally integration (extension/)
- Flow: saved note → **Send to Office Ally** → opens
  `https://pm.officeally.com/emr/PatientCharts/PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=<layout>&Tab=C&PID=<MRN>&Scope=&Date1=&Date2=`
  → log in if asked → Cadence icon → **Fill & save draft** (fills, reads back, Apply = draft only,
  re-checks after reload) → clinician signs in OA.
- Routing by meaning (`extension/lib/oaroute.js`); 2,000 chars/box, newline = 2; overflow into
  same-SOAP-part standard boxes or "(cont)" boxes; no automatic rewording.
- Hard stops: wrong patient, wrong layout, existing encounter with a different date, logged out.
  Relaxed (user's request): same-day duplicate encounter = note only; gaps don't need a second click.
- Opening AddNote creates an encounter — open once per note. Never sign, never delete in OA.
- Layouts set in Cadence **Manage Office** (nothing hard-coded). Init Eval → "Cadence Init Eval",
  Follow-Up → "Progress Notes". Patient ID = Cadence MRN.
- Load extension: `chrome://extensions` → Developer mode → Load unpacked →
  `C:\Users\localuser\Cadence\extension`; reload ↻ after code changes.

## 5. Website — LIVE (Cloudflare Pages)
- Files: `website/` (`index.html`, `book/`, `cadence/`, `assets/site.css`). Guide:
  `docs/Website_Publish_Guide.md`.
- Hosting: Cloudflare **Pages** project `sdmobilept` → `sdmobilept.pages.dev`.
  - Lesson: the first upload created a **Worker** (`blue-boat-487f…workers.dev`). Workers need the
    whole domain moved to Cloudflare (nameservers) — the wrong path. Use **Pages** → Upload assets.
    The Worker can be deleted.
  - "Connect your domain" screen with AI-bot settings + "Import DNS records" = adding the whole
    domain to Cloudflare → click **Back**. Custom domains must be added inside the Pages project.
- DNS at **Squarespace Domains**, reached by signing in with the **Google Workspace admin**
  account (admin.google.com → Account → Domains → Manage domains, or Squarespace "Continue with
  Google"). A plain Squarespace login shows "There are no domains".
- Records (2026-10-02): CNAME `www` → `sdmobilept.pages.dev`, CNAME `cadence` →
  `sdmobilept.pages.dev`, MX `@` smtp.google.com (1), TXT SPF, TXT `google._domainkey` DKIM.
  **Never touch MX / SPF / DKIM.**
- Verified 2026-10-03: www.sdmobilept.com, sdmobilept.com and cadence.sdmobilept.com all return the
  new site over https (cadence redirects to /cadence/ in the browser).
- Domain registered 2025-02-01, **expires 2027-02-01** — check auto-renew is on.
- One domain covers both addresses (`www`, `cadence` are free subdomains).
- Reviews: real ones only (FTC); add to `REVIEWS` in `index.html`.
- Update the site: edit `website/` → Cloudflare → Workers & Pages → sdmobilept → Create deployment
  → drag `website` folder → Deploy.

## 6. Working agreements
- **Engineering mode** until Kushang says "production mode": quick targeted tests, short steps.
- Commit/push only when asked; push to `kushang-branch`.
- Never commit `evals/Ingestion/` or `launcher.log`; never store OA credentials anywhere.
- No fake reviews; no automatic clinical rewording; no Del-button / auto-delete in OA.
- Keep this file updated every session (§9 log).

## 7. Open items
1. Website Step 4 checks: booking calendar shows times; three forms open; phone layout;
   **test email to info@sdmobilept.com both ways**.
2. Retire Google Site after a week of the new site working (remove its custom domain).
3. Delete the unused Cloudflare Worker `blue-boat-487f`.
4. Squarespace billing: domain auto-renew on; cancel any unused website plan.
5. Cadence 1.1.0 release (untrack launcher.log, merge to main, bump version, release notes,
   `scripts/release.py`, Drive folder, link Download button on `website/cadence/`).
6. `launcher.py` / desktop shortcut: set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
7. `scripts/update.py --zip` for Drive-delivered updates.
8. Docs out of date with relaxed OA rules (`docs/OfficeAlly_Integration_Rules.md` 3.3–3.5, CLAUDE.md
   OA paragraph) — fix in production mode.
9. Optional: "Shorten in Cadence" panel button; warning when the loop guard stops a note.
10. Re-eval / Discharge layouts; new-injury rule (bold + re-evaluate goals only when explicitly said).
11. Change the Office Ally password if not done (it appeared in a screenshot).
12. Back up Cadence data regularly (`scripts/backup.py`, USB).

## 8. Key files
| File | What |
|---|---|
| `CLAUDE.md` | binding project rules |
| `docs/kushang_context_Handover.md` | detailed snapshot 2026-09-28 |
| `docs/OfficeAlly_Integration_Rules.md` | practice OA rules (partly outdated) |
| `docs/Website_Publish_Guide.md` | website hosting steps |
| `extension/` | Chrome extension; tests in `extension/tests/` |
| `app/generate/loopguard.py` | stops repetition loops in generation |
| `website/` | the public website |

## 9. Session log (append newest at the bottom)
- **2026-09-28** — OA fill working end to end; relaxed encounter checks; nothing hard-coded;
  overflow routing; loop guard; clean OA test fixtures; new website built; Cloudflare chosen;
  handover written (commits up to `ff38586`).
- **2026-09-29** — start/stop commands documented; models reviewed (no updates needed);
  `gemma2:2b` installed and made required (`20fd3f9`).
- **2026-10-02** — Website published: Pages project `sdmobilept` created (after a Worker mix-up),
  www and cadence CNAMEs added at Squarespace (via Google Workspace admin login); www live.
- **2026-10-03** — All three addresses confirmed live over https. This context file created.
