from __future__ import annotations

"""
SupabasePersistence — writes runtime state to Supabase and loads it back.

All methods are no-ops when Supabase is not configured.
The in-memory store is always the primary source during a request; Supabase
provides durability so state survives restarts.

Table mapping (schema: docs/supabase_schema.sql):
  sessions            → SessionState
  session_events      → SessionEvent (appended, not updated)
  progress_snapshots  → ProgressSnapshot
  alerts              → Alert
  clinician_reviews   → ClinicianReviewItem
  goals               → Goal (upserted alongside children)
"""

from datetime import datetime

from app.db.client import db
from app.models import (
    Alert,
    ChildAttemptVector,
    ClinicianReviewItem,
    Goal,
    ProgressSnapshot,
    SessionEvent,
    SessionState,
)


def _client():
    return db.get()


# ── Sessions ──────────────────────────────────────────────────────────────────


def upsert_session(session: SessionState) -> None:
    client = _client()
    if client is None:
        return
    try:
        payload = {
            "external_session_id": session.session_id,
            "child_id": _child_uuid(client, session.child_id),
            "current_target": session.current_target,
            "status": session.status,
            "retries_used": session.retries_used,
            "reward_points": session.reward_points,
            "started_at": session.started_at.isoformat(),
        }
        if payload["child_id"] is None:
            return
        client.table("sessions").upsert(payload, on_conflict="external_session_id").execute()
    except Exception:  # noqa: BLE001
        pass


def append_session_event(session_id: str, event: SessionEvent) -> None:
    client = _client()
    if client is None:
        return
    try:
        session_uuid = _session_uuid(client, session_id)
        if session_uuid is None:
            return
        client.table("session_events").insert(
            {
                "session_id": session_uuid,
                "kind": event.kind,
                "detail": event.detail,
                "created_at": event.timestamp.isoformat(),
            }
        ).execute()
    except Exception:  # noqa: BLE001
        pass


# ── Progress ──────────────────────────────────────────────────────────────────


def upsert_progress(child_id: str, snapshot: ProgressSnapshot) -> None:
    client = _client()
    if client is None:
        return
    try:
        child_uuid = _child_uuid(client, child_id)
        if child_uuid is None:
            return
        client.table("progress_snapshots").upsert(
            {
                "child_id": child_uuid,
                "target_text": snapshot.target_text,
                "attempts": snapshot.attempts,
                "successes": snapshot.successes,
                "mastery_score": snapshot.mastery_score,
                "last_practiced_at": (
                    snapshot.last_practiced_at.isoformat()
                    if snapshot.last_practiced_at
                    else None
                ),
            },
            on_conflict="child_id,target_text",
        ).execute()
    except Exception:  # noqa: BLE001
        pass


# ── Alerts ────────────────────────────────────────────────────────────────────


def upsert_alert(alert: Alert) -> None:
    client = _client()
    if client is None:
        return
    try:
        child_uuid = _child_uuid(client, alert.child_id)
        session_uuid = _session_uuid(client, alert.session_id)
        if child_uuid is None:
            return
        client.table("alerts").upsert(
            {
                "external_alert_id": alert.alert_id,
                "session_id": session_uuid,
                "child_id": child_uuid,
                "caregiver_external_id": alert.caregiver_id,
                "reason": alert.reason,
                "message": alert.message,
                "acknowledged": alert.acknowledged,
                "created_at": alert.created_at.isoformat(),
            },
            on_conflict="external_alert_id",
        ).execute()
    except Exception:  # noqa: BLE001
        pass


def acknowledge_alert(alert_id: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.table("alerts").update({"acknowledged": True}).eq(
            "external_alert_id", alert_id
        ).execute()
    except Exception:  # noqa: BLE001
        pass


# ── Clinician reviews ─────────────────────────────────────────────────────────


def upsert_review(review: ClinicianReviewItem) -> None:
    client = _client()
    if client is None:
        return
    try:
        child_uuid = _child_uuid(client, review.child_id)
        session_uuid = _session_uuid(client, review.session_id)
        if child_uuid is None:
            return
        client.table("clinician_reviews").upsert(
            {
                "external_review_id": review.review_id,
                "session_id": session_uuid,
                "child_id": child_uuid,
                "clinician_external_id": review.clinician_id,
                "priority": review.priority,
                "status": review.status,
                "summary": review.summary,
                "created_at": review.created_at.isoformat(),
            },
            on_conflict="external_review_id",
        ).execute()
    except Exception:  # noqa: BLE001
        pass


# ── Attempt vectors ───────────────────────────────────────────────────────────


def upsert_attempt_vector(attempt: ChildAttemptVector) -> None:
    client = _client()
    if client is None:
        return
    try:
        child_uuid = _child_uuid(client, attempt.child_id)
        if child_uuid is None:
            return
        client.table("child_attempt_vectors").upsert(
            {
                "external_attempt_id": attempt.attempt_id,
                "child_id": child_uuid,
                "external_session_id": attempt.session_id,
                "audio_embedding": attempt.audio_embedding or None,
                "lip_embedding": attempt.lip_embedding or None,
                "emotion_embedding": attempt.emotion_embedding or None,
                "noise_embedding": attempt.noise_embedding or None,
                "top_match_reference_external_id": attempt.top_match_reference_id,
                "cosine_similarity": attempt.cosine_similarity,
                "success_flag": attempt.success_flag,
                "created_at": attempt.created_at.isoformat(),
            },
            on_conflict="external_attempt_id",
        ).execute()
    except Exception:  # noqa: BLE001
        pass


# ── Loaders (startup hydration) ───────────────────────────────────────────────


def load_sessions_for_child(child_id: str) -> list[SessionState]:
    """Load recent sessions from Supabase into the in-memory store at startup."""
    client = _client()
    if client is None:
        return []
    try:
        child_uuid = _child_uuid(client, child_id)
        if child_uuid is None:
            return []
        rows = (
            client.table("sessions")
            .select("*, session_events(*)")
            .eq("child_id", child_uuid)
            .order("started_at", desc=True)
            .limit(20)
            .execute()
            .data
            or []
        )
        result: list[SessionState] = []
        for row in rows:
            events = [
                SessionEvent(
                    timestamp=datetime.fromisoformat(ev["created_at"]),
                    kind=ev["kind"],
                    detail=ev["detail"],
                )
                for ev in (row.get("session_events") or [])
            ]
            result.append(
                SessionState(
                    session_id=row["external_session_id"],
                    child_id=child_id,
                    started_at=datetime.fromisoformat(row["started_at"]),
                    status=row["status"],
                    current_goal_id="",
                    current_target=row["current_target"],
                    retries_used=row["retries_used"],
                    reward_points=row["reward_points"],
                    events=events,
                )
            )
        return result
    except Exception:  # noqa: BLE001
        return []


def load_progress_for_child(child_id: str) -> dict[tuple[str, str], ProgressSnapshot]:
    """Load progress snapshots for a child from Supabase."""
    client = _client()
    if client is None:
        return {}
    try:
        child_uuid = _child_uuid(client, child_id)
        if child_uuid is None:
            return {}
        rows = (
            client.table("progress_snapshots")
            .select("*")
            .eq("child_id", child_uuid)
            .execute()
            .data
            or []
        )
        result: dict[tuple[str, str], ProgressSnapshot] = {}
        for row in rows:
            snap = ProgressSnapshot(
                child_id=child_id,
                target_text=row["target_text"],
                attempts=row["attempts"],
                successes=row["successes"],
                mastery_score=float(row["mastery_score"]),
                last_practiced_at=(
                    datetime.fromisoformat(row["last_practiced_at"])
                    if row.get("last_practiced_at")
                    else None
                ),
            )
            result[(child_id, row["target_text"])] = snap
        return result
    except Exception:  # noqa: BLE001
        return {}


def load_alerts(caregiver_id: str | None = None) -> list[Alert]:
    """Load unacknowledged alerts from Supabase."""
    client = _client()
    if client is None:
        return []
    try:
        query = client.table("alerts").select("*").eq("acknowledged", False)
        if caregiver_id:
            query = query.eq("caregiver_external_id", caregiver_id)
        rows = query.order("created_at", desc=True).limit(100).execute().data or []
        return [
            Alert(
                alert_id=row["external_alert_id"],
                session_id=row.get("external_session_id", ""),
                child_id=row.get("external_child_id", ""),
                caregiver_id=row["caregiver_external_id"],
                reason=row["reason"],
                message=row["message"],
                created_at=datetime.fromisoformat(row["created_at"]),
                acknowledged=row["acknowledged"],
            )
            for row in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def load_reviews(clinician_id: str | None = None) -> list[ClinicianReviewItem]:
    """Load queued clinician reviews from Supabase."""
    client = _client()
    if client is None:
        return []
    try:
        query = client.table("clinician_reviews").select("*").eq("status", "queued")
        if clinician_id:
            query = query.eq("clinician_external_id", clinician_id)
        rows = query.order("created_at", desc=True).limit(100).execute().data or []
        return [
            ClinicianReviewItem(
                review_id=row["external_review_id"],
                clinician_id=row["clinician_external_id"],
                child_id=row.get("external_child_id", ""),
                session_id=row.get("external_session_id", ""),
                priority=row["priority"],
                status=row["status"],
                summary=row["summary"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
    except Exception:  # noqa: BLE001
        return []


# ── UUID helpers ──────────────────────────────────────────────────────────────


def _child_uuid(client, external_child_id: str) -> str | None:
    """Resolve a child's Supabase UUID from its external string ID."""
    try:
        rows = (
            client.table("children")
            .select("id")
            .eq("external_child_id", external_child_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0]["id"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def _session_uuid(client, external_session_id: str) -> str | None:
    """Resolve a session's Supabase UUID from its external string ID."""
    try:
        rows = (
            client.table("sessions")
            .select("id")
            .eq("external_session_id", external_session_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0]["id"] if rows else None
    except Exception:  # noqa: BLE001
        return None
