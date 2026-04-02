"""Structured observability middleware for TalkBuddy.

Captures per-request timing and emits structured log lines that can be
ingested by Datadog, CloudWatch, Grafana Loki, or any JSON log sink.

Voice-specific latency
----------------------
The voice runtime uses /runtime/voice/checkpoints to record per-turn
latency milestones (turn_ended → first_transcript → first_audio_byte →
playback_started). This middleware records the full HTTP response time
for each runtime endpoint so infrastructure dashboards can correlate
network latency with in-session speech latency.

Medical audit trail
-------------------
Every request to a session endpoint logs the session_id and child_id
(when present in the query string) so that the request trail can be
correlated with session events in Supabase.

Fields emitted per request
--------------------------
ts, method, path, status, duration_ms, session_id, child_id, user_id,
provider_failure (true when a 502/503 occurs on a voice or provider route)
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("talkbuddy.observability")

# Voice and provider routes we care about most for latency tracking
_VOICE_PREFIXES = (
    "/runtime/voice/",
    "/session/",
    "/speech/",
    "/runtime/voice/tts/speak",
    "/runtime/voice/stream",
)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Emits a structured JSON log line for every HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        path = request.url.path
        is_voice = any(path.startswith(p) for p in _VOICE_PREFIXES)
        provider_failure = is_voice and response.status_code in (502, 503, 504)

        # Extract session context from query params for correlation
        session_id = request.query_params.get("session_id", "")
        child_id = request.query_params.get("child_id", "")
        user_id = getattr(getattr(request, "state", None), "user_id", "")

        record = {
            "method": request.method,
            "path": path,
            "status": response.status_code,
            "duration_ms": elapsed_ms,
        }
        if session_id:
            record["session_id"] = session_id
        if child_id:
            record["child_id"] = child_id
        if user_id:
            record["user_id"] = user_id
        if provider_failure:
            record["provider_failure"] = True

        # Log at WARNING when voice endpoints are slow (>2s) or failing
        if provider_failure or (is_voice and elapsed_ms > 2000):
            log.warning("voice_latency_alert %s", record)
        elif is_voice:
            log.info("voice_request %s", record)
        else:
            log.debug("http_request %s", record)

        # Propagate timing as a response header for browser devtools
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        return response
