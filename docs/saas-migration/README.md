# Cadence SaaS migration

Working notes for turning Cadence from a **local, single-machine** app into a
**HIPAA-compliant, multi-practice SaaS**. The full approved plan lives in the plan file
(`can-you-start-generating-hazy-koala.md`); this folder holds the living, actionable
artifacts that support it.

**In this folder:**
- [`founder-checklist.md`](founder-checklist.md) — **what *you* must do manually** (legal, accounts, market), ordered.
- [`product-strategy.md`](product-strategy.md) — competitive positioning, feature moats, phased build plan, pricing.
- [`phi-inventory.md`](phi-inventory.md) — PHI data-flow map (the Security Risk Analysis seed).
- [`security-risk-analysis-draft.md`](security-risk-analysis-draft.md) — SRA working draft / risk register (for counsel + compliance platform).
- [`subprocessors.md`](subprocessors.md) — vendor + BAA tracker.
- [`traceability-spike.md`](traceability-spike.md) — verification-layer feasibility + what shipped.

**Two strategic forks are unresolved and gate what gets built** (details in `product-strategy.md`):
1. **Market** — PT (current) vs mental-health therapy vs both. *Recommended: **PT*** — Cadence
   already implements the hard PT-specific parts (structured MMT/ROM, code-flagging, carry-forward,
   patient letter) and you have a live PT pilot; the platform work is market-agnostic, so mental
   health stays a later expansion. See `product-strategy.md`.
2. **Architecture** — the approved plan is full cloud AI; the research argues **on-device
   transcription is the moat**. Recommended amendment: a **hybrid** (audio stays on-device, only
   text goes to Bedrock). Compatible with the rest of the plan.

> **Founding-premise inversion.** Today's HIPAA posture is *"nothing leaves the machine;
> the real backstop is BitLocker + OS login"* (`docs/hipaa-local.md`). The SaaS discards
> that: PHI lives on a server you operate, on the internet, for many practices at once.
> As a SaaS vendor you become a **Business Associate** to each practice and are **directly
> liable** under HITECH/Omnibus. This is ~70% compliance *program*, ~30% code.

## Architectural stance: fork, don't mutate

Keep the working local app (`app/`) running for the current practice. Build the SaaS as a
separate service that **reuses only the model-agnostic core** — the `app/generate/`
prompt → rules → `postprocess.py` pipeline, `templates/`, and the UI shell. The local and
hosted apps have opposite security models and must not share a deployment.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Compliance program kickoff + this seed (PHI inventory, subprocessors) | **In progress (this folder)** |
| 2 | Secret hygiene (rotate HF token, secrets manager) | Actionable now |
| 3 | Storage: SQLite → Postgres + `practice_id` tenant columns | **Gated: needs a Postgres instance** |
| 4 | Multi-tenancy + auth (practice/user model, IdP, RLS) | **Gated: needs an IdP** |
| 5 | Model swap → Bedrock + Transcribe Medical (seam refactor is not gated) | **Gated: needs AWS + BAA** |
| 6 | Security hardening (TLS/CORS/headers/CSRF/rate-limit/audit log) | Follows 3–4 |
| 7 | Deploy to Aptible; staging (synthetic data); security review; prod | **Gated: needs Aptible** |
| 8 | Rewrite `CLAUDE.md` + `docs/hipaa-local.md` compliance posture | After the model is chosen and live |

## What only *you* can unblock (do these to open the gates)

These are account/legal/infra steps I cannot perform — the code phases wait on them:

1. **Engage HIPAA counsel** and pick a compliance platform (Vanta / Drata / Aptible Comply).
   Start the **Security Risk Analysis** — see [`phi-inventory.md`](phi-inventory.md) for the seed.
2. **Provision Aptible** (app + managed PostgreSQL) and **sign Aptible's BAA**.
3. **Provision the AI vendor** — recommended **AWS Bedrock** (Claude) + **AWS Transcribe
   Medical**, both HIPAA-eligible under the **AWS BAA**. Alt: Anthropic API under Anthropic's BAA.
4. **Choose + provision an IdP** that signs a BAA — recommended **AWS Cognito** (stays in the
   AWS umbrella); Auth0/Okta are smoother but add another BAA.
5. **Sign a BAA with each practice** before that practice's real PHI touches the system.
6. Track every vendor in [`subprocessors.md`](subprocessors.md).

## Immediate actions (non-gated)

- **Rotate the Hugging Face token** in `app/transcribe/hf_config.yaml`. Correction to an
  earlier note: it is **gitignored** (`.gitignore:13`) and this workspace is **not a git repo**,
  so it was never committed to history — but it is plaintext on disk and was shared in-session,
  so treat it as compromised and reissue. Do **not** blank the file yet; the running local app
  still needs it for MedASR. In the SaaS it moves to a secrets manager and likely disappears
  entirely once transcription moves to Transcribe Medical.

## Hard rule until the program gate clears

**No real PHI on any hosted environment** until BAAs are signed, the SRA is complete, and the
core policies exist. All pre-go-live testing uses **synthetic data only**.
