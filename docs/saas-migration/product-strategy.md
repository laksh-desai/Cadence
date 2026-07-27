# Product strategy & competitive positioning

Captured from founder market research (2026-07). This is the *product* half of the SaaS
migration — the compliance/technical half lives in [`README.md`](README.md),
[`phi-inventory.md`](phi-inventory.md), and the plan file. Read the two **strategic forks** at
the bottom first; they change what gets built.

> **Market-scope flag.** This doc holds competitor research for **both** candidate markets:
> **physical therapy** (Cadence's current domain — ScribePT, SPRY, WebPT AI, Prompt Sidekick,
> OneChart, Claire) and **mental-health therapy** (Twofold/Upheal/Blueprint). Which to pursue is
> **Strategic fork #1** — but note the asymmetry below: Cadence already implements much of the PT
> table-stakes, so the PT wedge is materially closer to shippable. Vendor sources (esp. SPRY) rank
> themselves; treat rankings skeptically, but the *feature set* is consistent across independent write-ups.

---

## PT competitor research (Cadence's current domain)

### Table stakes — copy these to be credible

1. **Structured objective capture from ambient audio** — ROM in degrees, MMT grades, functional
   mobility status pulled into *dedicated structured sections*, not prose. The single biggest
   PT-vs-general-scribe difference: numbers into fields.
2. **Full note-type lifecycle** — evaluations, daily notes, progress notes, plus a discharge
   summary that auto-compiles baseline→discharge functional-outcome comparisons. Evals are the time
   sink (one practice: 30–40 min → ~5 min).
3. **CPT/ICD-10 suggestion tied to interventions** — ScribePT maps treatment interventions to CPT.
   In PT, the note *is* the billing justification.
4. **Medicare compliance machinery** — 8-minute-rule calc, functional-outcome-measure tracking,
   plan-of-care generation, Medicare progress-note support, PTA co-sign workflows. "Audit-defensible"
   is the selling word here the way "sounds like you" is in therapy scribes.
5. **Editable-until-finalized drafts** with conversational speech mapped to the right SOAP sections. Nobody trusts auto-finalization.

### Differentiators worth copying

6. **Pre-visit briefing** — SPRY summarizes prior visits, ROM progression, and goals before the
   provider walks in. Cheap once you store structured data; clinicians love it.
7. **Plain-language global corrections** — SPRY's "change left shoulder to right throughout" updates
   every affected field at once. A brilliant editing primitive that fits the minimal-edits philosophy.
8. **Structured field write-back, not text dump** — ScribePT/Sidekick populate MMT grids, goal lists,
   dropdowns directly in the EHR. Cadence's deterministic field mapping is exactly this, aimed at the long tail.
9. **HEP tie-in** — Claire generates patient visit summaries reinforcing home-exercise-program compliance. A patient-facing artifact from the same audio, nearly free.
10. **Mobile-first capture** — PT isn't a desk specialty; therapists move between treatment areas and the gym floor.
11. **Outcome/progress visibility** — visual goal tracking over time + trend flags. PT's version of the mental-health "golden thread": goals → interventions → measured progress.

### Gaps nobody fills — your openings

12. **Concurrent patient handling** — outpatient PTs run 2–3 overlapping patients; ambient scribes
    assume one continuous encounter. A "pause / switch patient" model with per-patient audio
    threading would be genuinely novel (no competitor found addresses it).
13. **Verification layer** — per-claim audio traceback + confidence flags. *More* valuable in PT than
    mental health, because hallucinated **numbers** (ROM, MMT) are **billing-fraud** risks, not just quality issues.
14. **Long-tail EHR support** — ScribePT integrates natively only with WebPT/HENO; budget tools are
    copy-paste. Office Ally-class practices are unserved — the wedge.
15. **Price floor** — PT-specific tools run $79/mo (OneChart) to $129/mo (DeepCura); Twofold undercuts
    at $69 but with generic PT support. A genuinely PT-native scribe under ~$50 has no competition.

**Strategic read:** the market splits into full EMRs with native AI (SPRY, WebPT, Prompt) and
documentation layers on top (ScribePT, OneChart, Claire). *Don't fight the EMRs — be the best
documentation layer for practices whose EMR has no AI: the Office Ally world you already know.*
Items 1–4 make you credible, 8+13 make you different, 15 lets you spread.

### PT is closer to shippable than it looks — what Cadence already has

This is the key asymmetry vs. the mental-health option. Cadence already implements, in production code, several PT table-stakes *and* the hardest differentiator:

| PT market item | Already in Cadence | Gap to close |
|---|---|---|
| 1 — Structured ROM/MMT capture | `postprocess.normalize_strength_grades` writes MMT as `3+/5`; templates have structured objective sections | Emit into EHR *fields*, not just note sections |
| 2 — Full lifecycle + discharge comparison | Eval / Follow-Up / Progress / Discharge templates + carry-forward snapshots | Auto-compile baseline→discharge deltas |
| 3 — CPT/ICD | **Deliberately flags, never auto-authors** (`flag_code_sections` → `[[NEEDS]]`, rule 12) | Offer *suggestion-with-mandatory-confirm* while keeping the anti-fraud guard |
| 5 — Editable drafts, clinician signs | Core principle + `[[NEEDS]]` gap flags; nothing auto-finalizes | — |
| 6 — Pre-visit briefing | `carry_snapshots` already stores precautions / functional status / goals per patient | Render a briefing view from stored data (cheap) |
| 8 — Structured field write-back | Guided-mode deterministic field mapping | Generalize to a browser-extension EHR pusher |
| 9 — HEP / patient summary | **After-Visit Letter** template (patient-facing, plain-language) already exists | Wire it to HEP content |
| 13 — Numeric-hallucination guard | Bounded MMT normalization + "never invent clinical values" + code flagging | Add per-claim audio traceback + confidence flags |

Takeaway for fork #1: choosing **PT** means you're extending a product that already does the hard,
PT-specific parts. Choosing mental health means building the therapy-native format/outcome-measure
machinery from scratch against better-funded incumbents. One design tension to resolve: the market
expects **CPT suggestion** (item 3), but Cadence deliberately refuses to author codes (rule 12) —
reconcile by *suggesting* codes with mandatory clinician confirmation, never silent auto-fill.

---

## Mental-health therapy competitor research

## What competitors do right (copy this)

- **Therapy-native note formats.** SOAP alone doesn't cut it; winners cover SOAP, DAP, BIRP, GIRP
  and more (Twofold: 50+ formats incl. EMDR and narrative styles). Table stakes.
- **Style learning.** Twofold's core pitch is notes that *sound like the clinician wrote them*.
  Therapists reread every note; matching their voice cuts editing time — the real product.
- **Trust signaling as a feature.** "Audio not retained by default once the note is generated" and
  explicit "your session data isn't used for training" appear on every serious competitor's page.
  Plus **consent tooling** — informed-consent templates for clients (patient consent for
  recording/AI documentation is legally required, and varies by state).
- **Free tier as acquisition.** Twofold: 20 free notes/month; Upheal has a free tier. Solo
  therapists trial before buying.
- **The "golden thread."** Blueprint ties session content to outcome measures (PHQ-9, GAD-7) —
  notes connected to treatment plans and measurable progress, which is exactly what insurance
  audits look for.

## Gaps to exploit (the moats)

1. **Privacy architecture, not privacy promises.** Everyone says "encrypted, BAA, audio deleted."
   Almost none can say **"audio never leaves your device."** Cadence already built local
   transcription. A **hybrid** — on-device transcription, only de-identified text to the cloud for
   generation (or a fully-local "paranoid tier") — is a real technical moat the $49/mo incumbents
   can't bolt on quickly. (See **Strategic fork #2** — this partly conflicts with the approved
   full-cloud plan.)
2. **Hallucination accountability / traceability.** AI-scribe studies found patient-safety risks
   from transcription errors, falling hardest on speakers with speech disorders or psychiatric
   illness — literally the therapy population. Nobody ships a verification layer. Ship **"every
   claim in the note is traceable to a timestamp"**: click-a-sentence-to-hear-the-source-audio +
   confidence flags on low-certainty segments. Maps directly onto Cadence's existing
   `[[NEEDS: ...]]` gap-flagging and `postprocess.py` deterministic backstops — a feature no one
   else has. *Tracked as a first-class differentiator in the todo list.*
3. **Couples/group speaker attribution.** Most tools handle 1-on-1 well and multi-speaker poorly.
   Solid diarization for couples/family/group therapy is an underserved wedge.
4. **Long-tail EHR integration.** Competitors integrate SimplePractice / TherapyNotes; cheap EHRs
   (Office Ally tier) get copy-paste. Cadence's deterministic field-mapping idea generalizes into a
   browser-extension "push to any EHR" story for exactly the practices big players ignore.
5. **Price floor.** Psych Scribe charges $18/mo by not recording at all; ambient players cluster at
   $39–69. Local-first has near-zero per-user inference cost — undercut everyone **sustainably**,
   not as a loss leader.

## Phased build plan (from research)

- **Phase 1 — validate (~2 mo):** Web app, therapy-only. Record/upload → diarized transcript →
  DAP/SOAP/BIRP note. Local-first recording with on-device transcription (WebGPU/wasm Whisper where
  hardware allows), cloud fallback on a BAA stack (Bedrock/Azure). Built-in consent-script
  generator. Recruit 3–5 pilot therapists free (the PT-practice pattern repeats).
- **Phase 2 — differentiate (~3 mo):** Style learning from a therapist's past notes; verification
  layer (per-sentence audio traceback + low-confidence highlighting); treatment-plan linkage
  (golden thread); browser extension for long-tail EHR push.
- **Phase 3 — monetize:** Free 15 notes/mo; ~$29/mo unlimited (undercut Twofold); BAA on all paid
  tiers. Solo therapists first — they self-serve, decide fast, and dominate the Reddit/Facebook
  therapist communities where these tools get discovered.

## Legal reality check (from research; expanded in `founder-checklist.md`)

The moment you host PHI you're a **Business Associate**. Before charging anyone: an **LLC**, a real
**BAA template**, **SOC 2** (eventually), **breach insurance**, and **audio-consent handling that
varies by state** (two-party-consent states matter for recording). Budget a **healthcare-attorney
consult before launch** — a few hundred dollars that prevents existential mistakes. Local-first
architecture *shrinks* this surface but doesn't eliminate it once anything syncs.

**Honest bottom line (research):** the tech is within reach — Cadence proves the hard parts. Bet on
the **verification/traceability layer** and **true on-device privacy**, because those are
architecture-level moats incumbents can't quickly copy. The risk isn't building it; it's that
**distribution and compliance overhead** are where solo projects stall. Phase 1 with real pilot
therapists tells you cheaply whether it's worth incorporating.

## How this maps to what Cadence already has

| Research recommendation | Already in Cadence | Gap to build |
|---|---|---|
| On-device transcription moat | Browser WAV capture + local MedASR (`app/transcribe/`) | Swap to WebGPU/wasm Whisper for zero-install browser use; keep audio on-device |
| Verification / traceability | `[[NEEDS]]` gap flags, `postprocess.py` backstops | Timestamp alignment + click-to-hear-source + confidence flags |
| Deterministic field mapping → EHR | Guided-mode field mapping, `postprocess.py` | Generalize to a browser-extension EHR pusher |
| Therapy-native formats | 11 PT templates + REQUIRE/OMIT engine | Add DAP/BIRP/GIRP/EMDR templates (if mental-health pivot) |
| Style learning | Per-form fixed prompts | Fine-tune / few-shot on a clinician's own reviewed notes (already a roadmap item) |
| Consent tooling | — | New: consent-script generator + per-state recording-consent logic |

## The two strategic forks (decide before building)

- **Fork #1 — Market:** PT (current) vs mental-health therapy vs both. *Recommendation: start with
  **PT**.* Two reasons the PT research surfaced: (a) Cadence already implements the hard,
  PT-specific parts (structured MMT/ROM, code-flagging, carry-forward, patient letter — see the
  asymmetry table above), so time-to-first-pilot is weeks, not months; and (b) you have a **live PT
  pilot** (the practice) today. Mental health has better self-serve distribution but means building
  therapy-native format + outcome-measure machinery from scratch against better-funded incumbents.
  Validate PT first; the SaaS platform work (auth, tenancy, hosting) is market-agnostic, so a later
  mental-health expansion reuses all of it.
- **Fork #2 — Architecture:** The approved plan chose **full cloud AI** (incl. cloud transcription
  via Transcribe Medical). The research argues **on-device transcription is the moat**.
  *Recommendation: amend to a **hybrid** — keep transcription on-device (audio never leaves the
  device), send only text to Bedrock for generation. This preserves the marketing moat and shrinks
  the PHI-in-transit surface, at the cost of browser-hardware variability (mitigated by a cloud
  fallback for weak devices).* This amendment is compatible with the rest of the approved plan.
