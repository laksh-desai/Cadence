# Subprocessors & BAA tracker

Every third party that stores, processes, or transmits PHI on your behalf is a **subprocessor**
and needs a signed **Business Associate Agreement (BAA)** before it touches real PHI. HIPAA also
expects you to publish/maintain this list for your customer practices. Keep it current — it is a
living compliance artifact and a go-live gate.

> A vendor being "HIPAA-eligible" is **not** the same as having a BAA. Eligibility means the
> vendor *will* sign one and *can* be used for PHI; you still have to actually sign it **and**
> use only the HIPAA-eligible services/regions covered by it.

## Planned subprocessors (SaaS target stack)

| Vendor | Role | PHI it sees | HIPAA-eligible? | BAA status | Notes |
|---|---|---|---|---|---|
| **Aptible** | App hosting + managed PostgreSQL + backups | All PHI at rest + in transit | Yes (HIPAA PaaS) | ☐ To sign | Primary infra; pre-solves much of the safeguard layer |
| **AWS** (Bedrock) | Note generation (Claude) | Dictation + note context in prompts/responses | Yes (Bedrock is HIPAA-eligible) | ☐ To sign (AWS BAA) | Confirm **no data retention / not used for training**; pick eligible region |
| **AWS** (Transcribe Medical) | Speech-to-text | Dictation audio + transcript | Yes | ☐ Covered by AWS BAA | Same AWS BAA umbrella as Bedrock |
| **IdP** — AWS Cognito (rec.) *or* Auth0/Okta | Authentication, MFA | User identities (clinician PII; not patient PHI, but protect) | Cognito: yes (AWS BAA); Auth0/Okta: yes (own BAA) | ☐ To sign | Cognito keeps it in the AWS BAA; Auth0/Okta = extra BAA |
| **Error monitoring** (e.g. Sentry) | Crash/exception telemetry | **Risk:** stack traces / payloads can capture PHI | Yes, with BAA + PHI scrubbing | ☐ To sign | Only if used; enable server-side scrubbing; many teams self-host to avoid |
| **Transactional email** (e.g. password reset) | Auth emails | Email addresses; avoid PHI in message bodies | Varies | ☐ To sign if used | Keep PHI out of emails entirely if possible |
| **Google Workspace** (per practice) | Optional roster sync to Sheets | name/DOB/MRN/condition/scheduling_notes | Yes (Workspace BAA) | ☐ Per-practice | Each practice's **own** Workspace/BAA; still on **your** list because your platform relays it |
| **Compliance platform** (Vanta/Drata/Aptible Comply) | SRA, policy, evidence | Metadata, not patient PHI | Yes | ☐ To sign | Runs the program, not the data plane |

## The other direction: practices

You are the **Business Associate**; each practice is a **Covered Entity**. Sign a BAA with
**every practice** before onboarding their real PHI. Track them in your CRM/compliance platform,
not here.

## Rules of thumb

- **No BAA → no real PHI.** Synthetic data only until every row above is signed.
- Add a vendor here **before** wiring it in code; wiring a PHI-touching vendor with no BAA is a reportable gap.
- Re-review on renewal and whenever a vendor changes sub-processors or terms.
- Prefer keeping the AI + auth inside the **one AWS BAA** (Bedrock + Transcribe Medical + Cognito)
  to shrink the BAA surface Aptible already anchors.
