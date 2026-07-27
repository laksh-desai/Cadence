# Security Risk Analysis — working draft

> **Status: engineering draft, not a completed SRA.** The HIPAA Security Rule (§164.308(a)(1)(ii)(A))
> requires a formal, documented risk analysis. This file is a technical seed for that process —
> produced from a code audit of the app on 2026-07-15 — to hand to your HIPAA counsel and
> compliance platform (Vanta / Drata / Aptible Comply). It is **not legal advice** and is **not
> complete**: the organization-specific parts (workforce, physical facilities, formal
> likelihood/impact scoring, and the final control attestations) must be filled in with them.
> Companion docs: [`phi-inventory.md`](phi-inventory.md), [`subprocessors.md`](subprocessors.md).

## 1. Scope & system characterization

- **System:** Cadence SaaS — a multi-practice, web-hosted clinical-documentation service (PT first).
- **Sensitive data:** PHI — patient identifiers (name, DOB, MRN), clinical narrative (dictation
  transcripts, generated note bodies, carry-forward goals/precautions). Full field list in
  `phi-inventory.md`.
- **Users:** clinicians and practice admins across many tenant practices; you (the vendor) are a
  **Business Associate** to each.
- **Boundary:** hosted app + managed database (Aptible), AI vendor (AWS Bedrock + Transcribe
  Medical), identity provider, and the client browser. Each PHI-touching party needs a BAA.
- **Baseline note:** the current app is a *local, single-machine* build; nearly every technical
  safeguard below is **absent by design today** and must be built for the hosted service. That gap
  is the substance of this analysis.

## 2. Risk register (seeded from the audit)

Likelihood/Impact are placeholder qualitative marks for counsel to finalize. "Current" = state in
today's local codebase; "Target control" = what the SaaS must implement (cross-referenced to the
migration plan).

### Technical safeguards (§164.312)

| # | Risk | Current state | L/I | Target control | Status |
|---|------|---------------|-----|----------------|--------|
| T1 | Unauthenticated access to all PHI | **No auth of any kind**; any client reaching the port has full read/write/delete | H/H | IdP auth (OIDC), MFA for clinicians, session mgmt | **Authz choke points built + tested (`saas/auth.py`)**; authn stubbed pending IdP |
| T2 | Cross-tenant PHI leakage | **No tenant model**; single global data pool, unfiltered queries | H/H | `practice_id` on every PHI row + per-request scoping + **Postgres RLS** backstop | **Tested reference impl (`saas/tenancy.py`)**; Postgres+RLS pending |
| T3 | PHI intercepted in transit | **Plain HTTP**, hardcoded loopback | H/H | TLS-only (Aptible endpoint); HSTS | Planned (Phase 6) |
| T4 | No audit trail of PHI access | **No audit logging** | M/H | Append-only audit log: who read/changed which patient/note, when | **Tested append-only impl (`saas/audit.py`)**; Postgres enforcement pending |
| T5 | Encryption key exposure | Fernet key in **plaintext beside the DB**; whole DB decrypted to OS temp while running | M/H | Platform-managed encryption at rest (Aptible Postgres); no app-managed keyfile; drop decrypt-to-temp | Planned (Phase 3) |
| T6 | AI vendor mishandles PHI | N/A locally (on-device) | -/H | BAA with Bedrock/Transcribe Medical; **confirm no-retention / no-training**; eligible region | Gated (BAA) |
| T7 | Hallucinated clinical values (integrity / billing-fraud) | Deterministic guards + **new verification layer flags unanchored values** (`traceability.py`) | M/M | Keep verification layer; clinician signs every note | **Partially mitigated (shipped)** |
| T8 | CSRF / missing security headers / open API docs | None present; `/docs` public | M/M | CORS lockdown, CSP/HSTS/X-Frame-Options, CSRF for cookie auth, gate `/docs` | Planned (Phase 6) |
| T9 | Secrets in the codebase | HF token, service-account JSON, keyfile as plaintext files (gitignored; no git history here) | M/M | Secrets manager; rotate HF token; secret-scanning in CI | Partly actionable now |

### Administrative safeguards (§164.308)

| # | Risk | Target control | Status |
|---|------|----------------|--------|
| A1 | No formal risk analysis/management | This SRA, finalized + reviewed annually | In progress |
| A2 | No workforce access management / training | Onboarding/offboarding, least-privilege, sanction policy, training | Program (counsel) |
| A3 | No incident-response / breach process | Documented IR + breach-notification (HITECH 60-day) | Program (counsel) |
| A4 | No contingency plan | Backup + **tested restore**, DR, business-continuity | Planned (Phase 7) + program |
| A5 | Subprocessors unmanaged | BAA with each; maintained list (`subprocessors.md`) | In progress |

### Physical safeguards (§164.310)

| # | Risk | Target control | Status |
|---|------|----------------|--------|
| P1 | Facility/server physical security | Inherited from Aptible/AWS under their BAA (data-center controls) | Gated (BAA) |
| P2 | Workstation / endpoint controls | Policy: clinician-device expectations, auto-lock; you control server side only | Program (counsel) |
| P3 | Device & media disposal | Managed-platform disposal + documented retention/destruction policy | Program (counsel) |

## 3. Highest-priority remediations (engineering view)

In rough order of risk-reduction per unit effort, and matching the migration build order:

1. **Auth + tenant isolation (T1, T2)** — the two highest risks; nothing else matters if these leak.
2. **TLS + transmission security (T3)**.
3. **Encryption-at-rest via managed Postgres, retire the plaintext keyfile / decrypt-to-temp (T5)**.
4. **Audit logging (T4)** and **security headers / CSRF / gated docs (T8)**.
5. **Secret hygiene (T9)** — rotate the HF token now; move to a secrets manager.
6. **BAAs (T6 + subprocessors)** — the gating legal step before any real PHI.

## 4. What's already reducing risk today

- **T7 (integrity / fabricated values):** the shipped verification layer flags note values with no
  basis in the dictation, and every note is clinician-reviewed and signed — defense in depth against
  the exact billing-fraud risk that AI scribes are criticized for.
- The app **never logs PHI field values**, never writes dictation audio to disk, and (in the hybrid
  target) keeps audio on-device — shrinking the PHI-in-transit surface before any control is applied.

## 5. Open items for organization-specific completion (with counsel)

- Formal likelihood/impact scoring and risk acceptance sign-off.
- Workforce definition, training records, sanction policy.
- Physical/endpoint policy for clinician devices.
- Data retention & disposal schedule; patient right-of-access and deletion workflows.
- Finalized incident-response and breach-notification runbooks (incl. state-law variations).
- Annual review cadence and change-triggered re-assessment.
