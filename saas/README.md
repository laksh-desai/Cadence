# `saas/` — Cadence SaaS fork skeleton

The multi-tenant, hosted build. Separate from the live local app (`app/`) on purpose: the two have
opposite security models, so per the migration plan we **fork rather than mutate** (see
[`docs/saas-migration/`](../docs/saas-migration/)). This package starts with the pieces that (a)
address the highest-severity risks in the Security Risk Analysis and (b) are testable *before* any
cloud infrastructure exists.

## What's real and tested now

| Module | SRA risk | What it does |
|---|---|---|
| `tenancy.py` | **T2** (cross-tenant leakage) | `Principal` + `TenantScopedPatientStore` — every read/write/delete is scoped to the caller's `practice_id`; cross-tenant access is structurally impossible. Tested for isolation against SQLite. |
| `auth.py` | **T1** (unauthenticated access) | The authz half — `require_authenticated` (single choke point) + `require_role`. Real and tested. |
| `audit.py` | **T4** (no audit trail) | Append-only, tenant-scoped audit log of who did what to which PHI record, when. Tested. |
| `app.py` | **T1/T2/T4** wired | FastAPI skeleton tying the three together: every route authenticates → Principal (401), scopes data to the tenant (cross-tenant id → 404), gates privileged actions by role (403), and audits access. Tested end-to-end in-process via `TestClient`. |

Tests: `tests/test_saas_tenancy.py`, `tests/test_saas_audit.py`, `tests/test_saas_app.py` (195 in the full suite).

Run just the SaaS fork tests:
```
.venv/Scripts/python.exe -m unittest tests.test_saas_tenancy tests.test_saas_audit tests.test_saas_app
```

## What's stubbed (needs provisioned infrastructure)

- **Authentication proper** — `StubAuthenticator` maps opaque tokens to principals with *no*
  signature/expiry checks. Replace with a Cognito/OIDC JWT validator once the IdP exists.
- **Datastore** — SQLite here so the invariants are testable today. The target is Aptible-managed
  **PostgreSQL**; the `WHERE practice_id = ?` scoping is identical, plus **Row-Level Security** as a
  defense-in-depth backstop.
- **HTTP wiring** — these are the building blocks a FastAPI app depends on; the hosted server,
  TLS/CORS/CSRF/headers, and deployment (Dockerfile + Aptible manifest) come once infra is live.

## Why SQLite-backed tests aren't throwaway

The isolation logic (tenant-scoped queries), the authz choke points, and the audit-record shape are
all database-agnostic. Moving to Postgres swaps the driver and *adds* RLS; it doesn't change any of
the invariants these tests lock down. Building and proving them now de-risks the highest-severity
work before you spend a dollar on infrastructure.
