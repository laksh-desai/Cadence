"""Authentication + authorization boundary for the SaaS fork (SRA risk T1).

Split deliberately:
  * AUTHENTICATION (who is the caller?) is a thin, swappable boundary. The real implementation
    validates an IdP-issued token — AWS Cognito / OIDC JWT: verify signature, issuer, audience,
    expiry, then read practice_id/role claims — and returns a Principal. That needs a provisioned
    IdP, so it's stubbed here behind a Protocol.
  * AUTHORIZATION (may they do this?) — tenant scoping (saas/tenancy.py) and the role checks below
    — is REAL and tested now, because that is where cross-tenant PHI leakage actually happens. An
    IdP swap doesn't change any of it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from saas.tenancy import Principal

CLINICIAN = "clinician"
PRACTICE_ADMIN = "practice_admin"
ROLES = frozenset({CLINICIAN, PRACTICE_ADMIN})


class AuthError(Exception):
    """Authentication failed — missing, invalid, or expired token. Maps to HTTP 401."""


class PermissionDenied(Exception):
    """Authenticated but not authorized for this action/role. Maps to HTTP 403."""


@runtime_checkable
class Authenticator(Protocol):
    """Turns a bearer token into a Principal, or None if it can't be trusted."""

    def authenticate(self, token: str) -> Principal | None:
        ...


class StubAuthenticator:
    """DEV/TEST ONLY. Maps opaque tokens to principals from a dict. Replace with a Cognito/OIDC
    JWT validator before any deployment — this performs no signature or expiry verification."""

    def __init__(self, tokens: dict[str, Principal] | None = None):
        self._tokens = dict(tokens or {})

    def authenticate(self, token: str) -> Principal | None:
        return self._tokens.get(token)


def require_authenticated(authenticator: Authenticator, token: str | None) -> Principal:
    """Resolve a request's Principal or raise AuthError. The single choke point every hosted
    route would depend on (as a FastAPI dependency) so no endpoint is ever unauthenticated."""
    if not token:
        raise AuthError("missing bearer token")
    principal = authenticator.authenticate(token)
    if principal is None:
        raise AuthError("invalid or expired token")
    return principal


def require_role(principal: Principal, *allowed: str) -> None:
    """Raise PermissionDenied unless the principal holds one of the allowed roles."""
    if principal.role not in allowed:
        raise PermissionDenied(f"role {principal.role!r} not permitted; requires one of {sorted(allowed)}")
