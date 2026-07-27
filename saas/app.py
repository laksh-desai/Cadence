"""SaaS HTTP skeleton — wires auth + tenancy + audit into a real (in-process testable) API.

This is where the three security modules become an actual request path: every route authenticates
the caller to a Principal (401 if not), scopes all data access to that Principal's practice (so a
cross-tenant id simply 404s), gates privileged actions by role (403 if not), and records an audit
entry. It runs and is tested end-to-end via FastAPI's in-process TestClient — no cloud infra needed.

Deliberately minimal and injectable: `create_app()` takes the authenticator/store/audit so tests
supply stubs and an in-memory DB. The production app swaps StubAuthenticator for an IdP JWT
validator and the SQLite store for Postgres+RLS — the routing, scoping, and audit stay identical.
The HTTP hardening (TLS/CORS/CSRF/security headers/rate limiting) is Phase 6, added when this is
actually deployed behind Aptible.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from saas.audit import AuditLog
from saas.auth import (
    PRACTICE_ADMIN,
    AuthError,
    Authenticator,
    PermissionDenied,
    require_authenticated,
    require_role,
)
from saas.tenancy import Principal, TenantScopedPatientStore


class PatientIn(BaseModel):
    name: str
    dob: str | None = None
    mrn: str | None = None
    condition: str | None = None


def create_app(*, authenticator: Authenticator, store: TenantScopedPatientStore, audit: AuditLog) -> FastAPI:
    app = FastAPI(title="Cadence SaaS (skeleton)")

    def principal_dep(authorization: str | None = Header(default=None)) -> Principal:
        token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
        try:
            return require_authenticated(authenticator, token)
        except AuthError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    @app.exception_handler(PermissionDenied)
    async def _permission_denied(request, exc: PermissionDenied):  # noqa: ANN001
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.get("/patients")
    def list_patients(principal: Principal = Depends(principal_dep)):
        audit.record(principal, "patient.list", "patient", None)
        return store.list_patients(principal)

    @app.post("/patients", status_code=201)
    def create_patient(body: PatientIn, principal: Principal = Depends(principal_dep)):
        pt = store.create_patient(principal, name=body.name, dob=body.dob, mrn=body.mrn, condition=body.condition)
        audit.record(principal, "patient.create", "patient", pt["id"])
        return pt

    @app.get("/patients/{patient_id}")
    def get_patient(patient_id: str, principal: Principal = Depends(principal_dep)):
        pt = store.get_patient(principal, patient_id)
        audit.record(principal, "patient.read", "patient", patient_id)
        if pt is None:  # covers both "no such patient" and "belongs to another tenant"
            raise HTTPException(status_code=404, detail="patient not found")
        return pt

    @app.delete("/patients/{patient_id}", status_code=204)
    def delete_patient(patient_id: str, principal: Principal = Depends(principal_dep)):
        require_role(principal, PRACTICE_ADMIN)  # deleting a patient is an admin action
        ok = store.delete_patient(principal, patient_id)
        audit.record(principal, "patient.delete", "patient", patient_id)
        if not ok:
            raise HTTPException(status_code=404, detail="patient not found")

    return app
