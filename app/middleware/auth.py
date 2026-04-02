"""Clerk JWT authentication middleware for TalkBuddy.

Design
------
Medical apps require authenticated access to clinical and caregiver data.
This middleware verifies the Authorization: Bearer <token> header on
protected routes using Clerk's backend verification API.

Behaviour
---------
- When CLERK_SECRET_KEY is set: protected routes require a valid JWT.
  The token is verified against Clerk's /v1/tokens/verify endpoint.
  On success the decoded user payload is attached to request.state.user.
  On failure a 401 JSON response is returned immediately.

- When CLERK_SECRET_KEY is not set (development / CI):
  All requests pass through without authentication checks.
  A warning is logged once at startup.

Protected route prefixes
------------------------
Sensitive clinical, caregiver, and enterprise routes. The therapy UI and
the voice runtime endpoints are intentionally left unprotected so that
tablet / TV devices can operate without login during a live session.
Session-level security relies on session_id and child_id validation.

Audit trail
-----------
Every authenticated request records the authenticated user ID so that
subsequent session events can be attributed to the correct clinician
or caregiver. This is a HIPAA-relevant requirement.
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("talkbuddy.auth")

# Routes that require a valid Clerk JWT when CLERK_SECRET_KEY is set.
# Ordered from most specific to least specific.
_PROTECTED = (
    "/clinician/",
    "/enterprise/",
    "/analytics/",
    "/caregiver/",
    "/goals/",
    "/reports/",
    "/workflows/",
    "/alerts/escalate",
    "/admin/",
)

_WARNED = False


class ClerkAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that verifies Clerk JWTs on protected routes."""

    async def dispatch(self, request: Request, call_next):
        global _WARNED
        from app.config import settings

        # Dev / CI mode: no CLERK_SECRET_KEY configured
        if not settings.configured(settings.clerk_secret_key):
            if not _WARNED:
                log.warning(
                    "CLERK_SECRET_KEY not set — auth middleware is in passthrough mode. "
                    "All protected routes are open. Do not deploy without a Clerk secret key."
                )
                _WARNED = True
            return await call_next(request)

        path = request.url.path
        if not any(path.startswith(prefix) for prefix in _PROTECTED):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"detail": "Authorization required", "code": "missing_token"},
                status_code=401,
            )

        token = auth_header[7:]
        user = await _verify_clerk_token(token, settings.clerk_secret_key)
        if user is None:
            return JSONResponse(
                {"detail": "Invalid or expired token", "code": "invalid_token"},
                status_code=401,
            )

        request.state.user = user
        request.state.user_id = user.get("sub", "unknown")
        return await call_next(request)


async def _verify_clerk_token(token: str, clerk_secret_key: str) -> dict | None:
    """Verify a Clerk session token using Clerk's backend API.

    Returns the decoded claims dict on success, None on any failure.
    Caches nothing — Clerk's CDN handles JWKS caching at the network layer.

    In high-traffic production this should be replaced with a local JWT
    signature verification using Clerk's JWKS endpoint to avoid an extra
    network hop per request.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://api.clerk.com/v1/tokens/verify",
                headers={
                    "Authorization": f"Bearer {clerk_secret_key}",
                    "Content-Type": "application/json",
                },
                json={"token": token},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            # Clerk returns {"sub": "...", "sid": "...", "org_id": "...", ...}
            return data
    except Exception:
        return None
