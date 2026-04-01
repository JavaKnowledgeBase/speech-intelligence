from __future__ import annotations

"""Supabase-backed durability helpers for runtime state.

All methods are no-ops when Supabase is not configured. The in-memory store stays
authoritative during a request, while Supabase provides durability across restarts.
"""

from datetime import datetime

from app.db.client import db
from app.models import (
    Alert,
    ChildAttemptVector,
    ClinicianReviewItem,
    ProgressSnapshot,
    SessionEvent,
    SessionState,
)


def _client():
    return db.get()


def upsert_session(session: SessionState) -> None:
    client = _client()
    if client is None:
        return
    try:
        child_uuid = _child_uuid(client, session.child_id)
        if child_uuid is None:
            return
        payload = {
            "external_session_id": session.session_id,
            "child_id": child_uuid,
            "current_target": session.current_target,
            "status": session.status,
            "retries_used": session.retries_used,
            "reward_points": session.reward_points,
            "started_at": session.started_at.isoformat(),
        }
        goal_uuid = _goal_uuid(client, session.current_goal_id)
        if goal_uuid is not None:
            payload["current_goal_id"] = goal_uuid
        client.table("sessions").upsert(payload, on_conflict="external_session_id").execute()
    except Exception:
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
    except Exception:
        pass


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
                "last_practiced_at": snapshot.last_practiced_at.isoformat() if snapshot.last_practiced_at else None,
            },
            on_conflict="child_id,target_text",
        ).execute()
    except Exception:
        pass


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
    except Exception:
        pass


def acknowledge_alert(alert_id: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.table("alerts").update({"acknowledged": True}).eq("external_alert_id", alert_id).execute()
    except Exception:
        pass


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
    except Exception:
        pass


def upsert_attempt_vector(attempt: ChildAttemptVector) -> None:
    client = _client()
    if client is None:
        return
    try:
        child_uuid = _child_uuid(client, attempt.child_id)
        target_uuid = _target_uuid(client, attempt.target_id)
        if child_uuid is None or target_uuid is None:
            return
        client.table("child_attempt_vectors").upsert(
            {
                "external_attempt_id": attempt.attempt_id,
                "child_id": child_uuid,
                "target_id": target_uuid,
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
    except Exception:
        pass


def load_sessions_for_child(child_id: str) -> list[SessionState]:
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
            goal_id = _goal_external_id(client, row.get("current_goal_id")) if row.get("current_goal_id") else ""
            events = [
                SessionEvent(
                    timestamp=datetime.fromisoformat(event_row["created_at"]),
                    kind=event_row["kind"],
                    detail=event_row["detail"],
                )
                for event_row in sorted(row.get("session_events") or [], key=lambda item: item["created_at"])
            ]
            result.append(
                SessionState(
                    session_id=row["external_session_id"],
                    child_id=child_id,
                    started_at=datetime.fromisoformat(row["started_at"]),
                    status=row["status"],
                    current_goal_id=goal_id,
                    current_target=row["current_target"],
                    retries_used=row["retries_used"],
                    reward_points=row["reward_points"],
                    events=events,
                )
            )
        return result
    except Exception:
        return []


def load_progress_for_child(child_id: str) -> dict[tuple[str, str], ProgressSnapshot]:
    client = _client()
    if client is None:
        return {}
    try:
        child_uuid = _child_uuid(client, child_id)
        if child_uuid is None:
            return {}
        rows = client.table("progress_snapshots").select("*").eq("child_id", child_uuid).execute().data or []
        result: dict[tuple[str, str], ProgressSnapshot] = {}
        for row in rows:
            snapshot = ProgressSnapshot(
                child_id=child_id,
                target_text=row["target_text"],
                attempts=row["attempts"],
                successes=row["successes"],
                mastery_score=float(row["mastery_score"]),
                last_practiced_at=datetime.fromisoformat(row["last_practiced_at"]) if row.get("last_practiced_at") else None,
            )
            result[(child_id, row["target_text"])] = snapshot
        return result
    except Exception:
        return {}


def load_attempt_vectors_for_child(child_id: str) -> list[ChildAttemptVector]:
    client = _client()
    if client is None:
        return []
    try:
        child_uuid = _child_uuid(client, child_id)
        if child_uuid is None:
            return []
        rows = (
            client.table("child_attempt_vectors")
            .select("*")
            .eq("child_id", child_uuid)
            .order("created_at", desc=False)
            .limit(200)
            .execute()
            .data
            or []
        )
        attempts: list[ChildAttemptVector] = []
        for row in rows:
            attempts.append(
                ChildAttemptVector(
                    attempt_id=row["external_attempt_id"],
                    child_id=child_id,
                    target_id=_target_external_id(client, row.get("target_id")) or "unknown-target",
                    session_id=row["external_session_id"],
                    audio_embedding=row.get("audio_embedding") or [],
                    lip_embedding=row.get("lip_embedding") or [],
                    emotion_embedding=row.get("emotion_embedding") or [],
                    noise_embedding=row.get("noise_embedding") or [],
                    top_match_reference_id=row.get("top_match_reference_external_id"),
                    cosine_similarity=float(row.get("cosine_similarity") or 0.0),
                    success_flag=bool(row.get("success_flag")),
                    created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.utcnow(),
                )
            )
        return attempts
    except Exception:
        return []


def load_alerts(caregiver_id: str | None = None) -> list[Alert]:
    client = _client()
    if client is None:
        return []
    try:
        query = client.table("alerts").select("*").eq("acknowledged", False)
        if caregiver_id:
            query = query.eq("caregiver_external_id", caregiver_id)
        rows = query.order("created_at", desc=True).limit(100).execute().data or []
        alerts: list[Alert] = []
        for row in rows:
            alerts.append(
                Alert(
                    alert_id=row["external_alert_id"],
                    session_id=_session_external_id(client, row.get("session_id")) or "",
                    child_id=_child_external_id(client, row.get("child_id")) or "",
                    caregiver_id=row["caregiver_external_id"],
                    reason=row["reason"],
                    message=row["message"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    acknowledged=row["acknowledged"],
                )
            )
        return alerts
    except Exception:
        return []


def load_reviews(clinician_id: str | None = None) -> list[ClinicianReviewItem]:
    client = _client()
    if client is None:
        return []
    try:
        query = client.table("clinician_reviews").select("*").eq("status", "queued")
        if clinician_id:
            query = query.eq("clinician_external_id", clinician_id)
        rows = query.order("created_at", desc=True).limit(100).execute().data or []
        reviews: list[ClinicianReviewItem] = []
        for row in rows:
            reviews.append(
                ClinicianReviewItem(
                    review_id=row["external_review_id"],
                    clinician_id=row["clinician_external_id"],
                    child_id=_child_external_id(client, row.get("child_id")) or "",
                    session_id=_session_external_id(client, row.get("session_id")) or "",
                    priority=row["priority"],
                    status=row["status"],
                    summary=row["summary"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return reviews
    except Exception:
        return []


def _child_uuid(client, external_child_id: str) -> str | None:
    return _lookup_uuid(client, "children", "external_child_id", external_child_id)


def _session_uuid(client, external_session_id: str) -> str | None:
    return _lookup_uuid(client, "sessions", "external_session_id", external_session_id)


def _target_uuid(client, external_target_id: str) -> str | None:
    return _lookup_uuid(client, "curriculum_targets", "external_target_id", external_target_id)


def _goal_uuid(client, external_goal_id: str) -> str | None:
    if not external_goal_id:
        return None
    return _lookup_uuid(client, "goals", "external_goal_id", external_goal_id)


def _lookup_uuid(client, table: str, field: str, value: str) -> str | None:
    try:
        rows = client.table(table).select("id").eq(field, value).limit(1).execute().data or []
        return rows[0]["id"] if rows else None
    except Exception:
        return None


def _child_external_id(client, child_uuid: str | None) -> str | None:
    return _lookup_external_id(client, "children", child_uuid, "external_child_id")


def _session_external_id(client, session_uuid: str | None) -> str | None:
    return _lookup_external_id(client, "sessions", session_uuid, "external_session_id")


def _target_external_id(client, target_uuid: str | None) -> str | None:
    return _lookup_external_id(client, "curriculum_targets", target_uuid, "external_target_id")


def _goal_external_id(client, goal_uuid: str | None) -> str | None:
    return _lookup_external_id(client, "goals", goal_uuid, "external_goal_id")


def _lookup_external_id(client, table: str, record_uuid: str | None, external_field: str) -> str | None:
    if not record_uuid:
        return None
    try:
        rows = client.table(table).select(external_field).eq("id", record_uuid).limit(1).execute().data or []
        return rows[0][external_field] if rows else None
    except Exception:
        return None
