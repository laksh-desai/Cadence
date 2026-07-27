# Founder checklist — what you must do manually

The code is the *smaller* half. These are the account/legal/business/market actions **I cannot do
for you** — they gate every technical phase. Ordered so cheap validation comes before expensive
commitment. Don't provision paid HIPAA infra or form an LLC until Step 0 says the product is worth it.

## Step 0 — Validate first (cheap, do before anything below)

- [ ] **Pick the wedge** (Strategic fork #1): PT vs mental-health therapy vs both. **Recommended: PT** —
      Cadence already builds the hard PT-specific parts and you have a live PT pilot, so time-to-pilot is
      weeks not months. Mental health has better self-serve distribution but is a from-scratch build against
      funded incumbents; the platform work is market-agnostic so it stays a later option.
- [ ] **Recruit 3–5 pilot clinicians** willing to trial free. For PT: your existing practice + referrals.
      For therapy: solo therapists in Reddit/Facebook communities.
- [ ] **Run the pilot on synthetic / consented data only** (no LLC or BAAs needed yet if no real PHI,
      but the moment a pilot uses a real patient session you are already handling PHI — get consent + a
      BAA even for pilots, or keep it strictly synthetic).
- [ ] Decide go/no-go on incorporating based on pilot feedback.

## Step 1 — Legal & business formation (before charging or hosting real PHI)

- [ ] **Consult a healthcare attorney** (~a few hundred dollars). Non-negotiable — cheapest insurance you'll buy.
- [ ] **Form an LLC** (liability shield; you'll be a Business Associate with direct HITECH liability).
- [ ] **BAA template** — a real, lawyer-reviewed Business Associate Agreement you sign with each practice.
- [ ] **Terms of Service + Privacy Policy** (with the "we don't train on your data" and "audio handling" statements competitors all publish).
- [ ] **Cyber/breach insurance** (a HIPAA breach can be existential for a solo founder).
- [ ] **State recording-consent law** — the U.S. has one-party and **two-party consent** states.
      Recording therapy sessions requires the right consent flow per state. Build a **consent-script
      generator** + informed-consent templates into the product (also a competitive feature).

## Step 2 — Compliance program (parallel with Step 3; gates go-live)

- [ ] Engage a **compliance platform** (Vanta / Drata / Aptible Comply) — automates most of the below.
- [ ] Complete a **Security Risk Analysis** — seed is [`phi-inventory.md`](phi-inventory.md).
- [ ] Write **policies & procedures** (access control, incident response, backup/contingency, sanction, retention/disposal).
- [ ] **Workforce training** + confidentiality agreements (even if "workforce" is just you today).
- [ ] **Breach-notification process** (HITECH 60-day; some states stricter).
- [ ] **SOC 2** — not day one, but larger practices will ask; start collecting evidence early via the platform.

## Step 3 — Provision infrastructure (each opens a technical phase)

Sign the BAA with each before real PHI. Track in [`subprocessors.md`](subprocessors.md).

- [ ] **Aptible** account + managed PostgreSQL + **sign Aptible BAA** → unblocks storage migration (Phase 3) & deploy (Phase 7).
- [ ] **AWS** account + **sign AWS BAA**; enable **Bedrock** (Claude) and **Transcribe Medical** in a
      HIPAA-eligible region; confirm **no-retention / no-training** terms → unblocks model swap (Phase 5).
- [ ] **Identity provider** — AWS Cognito (in the AWS BAA) or Auth0/Okta (own BAA) → unblocks auth (Phase 4).
- [ ] **Domain name** + DNS; email/support address.
- [ ] **Error monitoring** only if you add one — must have a BAA + PHI scrubbing (or self-host).

## Step 4 — Product/GTM (once validated)

- [ ] Free tier (research suggests ~15 notes/mo) + paid (~$29/mo unlimited); **BAA on all paid tiers**.
- [ ] Billing provider (Stripe — note: Stripe handles payment data, not PHI; no BAA needed for card data alone).
- [ ] Landing page with the **trust-signaling copy** (audio-on-device, no training on your data, BAA available).
- [ ] Distribution: solo-clinician communities (Reddit r/therapists, Facebook groups), referrals from pilots.

## Right now (non-gated, I can help with these next)

- [ ] **Rotate the Hugging Face token** in `app/transcribe/hf_config.yaml` (treat as compromised; reissue on huggingface.co). Don't blank the file — the local app still uses it.
- [ ] Decide the two **strategic forks** (market; hybrid-vs-full-cloud) so I can start the right code.

## Quick "who does what"

| Task type | You | Me (Claude) |
|---|---|---|
| Legal, LLC, BAAs, insurance, consult | ✅ | ✍️ draft/organize text, not legal advice |
| Provision Aptible/AWS/IdP accounts + sign BAAs | ✅ | — |
| Recruit pilots, pricing, GTM | ✅ | ✍️ copy, positioning |
| Rotate the HF token | ✅ (reissue) | ✅ (wire the new one) |
| Storage/auth/model-swap/hardening code | — | ✅ (once accounts exist) |
| Traceability layer, templates, consent generator | — | ✅ |
| SRA, policies, subprocessor list drafting | review | ✅ draft/seed |
