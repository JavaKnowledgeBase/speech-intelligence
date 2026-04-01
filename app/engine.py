from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.data import store
from app.models import (
    Alert,
    ChildProfile,
    ChildReport,
    EnterpriseUsage,
    EscalationRequest,
    Goal,
    GoalAssignmentRequest,
    ProgressSnapshot,
    SessionEvent,
    SessionStartResponse,
    SessionState,
    SpeechEvaluation,
)


def choose_next_goal(child: ChildProfile) -> Goal:
    ranked_goals = sorted(
        child.goals,
        key=lambda goal: store.progress.get(
            (child.child_id, goal.target_text),
            ProgressSnapshot(child_id=child.child_id, target_text=goal.target_text),
        ).mastery_score,
    )
    return ranked_goals[0]


def start_session(child_id: str) -> SessionStartResponse:
    child = store.children[child_id]
    goal = choose_next_goal(child)
    session_id = f"session-{uuid4().hex[:10]}"
    session = SessionState(
        session_id=session_id,
        child_id=child_id,
        started_at=datetime.utcnow(),
        current_goal_id=goal.goal_id,
        current_target=goal.target_text,
        events=[
            SessionEvent(
                timestamp=datetime.utcnow(),
                kind="session_started",
                detail=f"Started target {goal.target_text}",
            )
        ],
    )
    store.sessions[session_id] = session
    return SessionStartResponse(
        session_id=session_id,
        child_id=child_id,
        target_text=goal.target_text,
        cue=goal.cue,
        message=f"Let's practice {goal.target_text} with a short, playful repetition round.",
    )


def _score_attempt(expected: str, transcript: str) -> float:
    expected_clean = expected.strip().lower()
    transcript_clean = transcript.strip().lower()
    if transcript_clean == expected_clean:
        return 0.96
    if expected_clean in transcript_clean or transcript_clean in expected_clean:
        return 0.72
    if transcript_clean and transcript_clean[0] == expected_clean[0]:
        return 0.55
    return 0.24


def _confidence(pronunciation_score: float, attention_score: float, retries_used: int) -> float:
    retry_penalty = min(retries_used * 0.08, 0.2)
    return max(0.0, min(1.0, (pronunciation_score * 0.7) + (attention_score * 0.3) - retry_penalty))


def _update_progress(child_id: str, target_text: str, success: bool) -> ProgressSnapshot:
    key = (child_id, target_text)
    snapshot = store.progress.get(
        key,
        ProgressSnapshot(child_id=child_id, target_text=target_text),
    )
    snapshot.attempts += 1
    if success:
        snapshot.successes += 1
    snapshot.mastery_score = round(snapshot.successes / snapshot.attempts, 2)
    snapshot.last_practiced_at = datetime.utcnow()
    store.progress[key] = snapshot
    return snapshot


def _create_alert(session: SessionState, reason: str, message: str) -> Alert:
    child = store.children[session.child_id]
    alert = Alert(
        alert_id=f"alert-{uuid4().hex[:8]}",
        session_id=session.session_id,
        child_id=session.child_id,
        caregiver_id=child.caregiver_id,
        reason=reason,
        message=message,
        created_at=datetime.utcnow(),
    )
    store.alerts[alert.alert_id] = alert
    session.events.append(
        SessionEvent(
            timestamp=datetime.utcnow(),
            kind="alert_created",
            detail=message,
        )
    )
    return alert


def process_speech_input(session_id: str, transcript: str, attention_score: float) -> SpeechEvaluation:
    session = store.sessions[session_id]
    pronunciation_score = _score_attempt(session.current_target, transcript)
    confidence_score = _confidence(pronunciation_score, attention_score, session.retries_used)
    engagement_score = round(attention_score, 2)
    attempted_target = session.current_target
    success = pronunciation_score >= 0.9 and attention_score >= 0.55

    if success:
        _update_progress(session.child_id, attempted_target, success=True)
        session.reward_points += 10
        session.retries_used = 0
        session.events.append(
            SessionEvent(
                timestamp=datetime.utcnow(),
                kind="attempt_success",
                detail=f"Child matched target {attempted_target}",
            )
        )
        child = store.children[session.child_id]
        next_goal = choose_next_goal(child)
        session.current_goal_id = next_goal.goal_id
        session.current_target = next_goal.target_text
        return SpeechEvaluation(
            recognized_text=transcript,
            expected_text=attempted_target,
            pronunciation_score=round(pronunciation_score, 2),
            confidence_score=round(confidence_score, 2),
            engagement_score=engagement_score,
            action="advance",
            feedback="Nice work. The AI is confident enough to move to the next target.",
            next_target=next_goal.target_text,
        )

    _update_progress(session.child_id, attempted_target, success=False)

    if confidence_score >= 0.58 and session.retries_used < session.max_retries:
        session.retries_used += 1
        session.events.append(
            SessionEvent(
                timestamp=datetime.utcnow(),
                kind="attempt_retry",
                detail=f"Retry requested for {attempted_target}",
            )
        )
        return SpeechEvaluation(
            recognized_text=transcript,
            expected_text=attempted_target,
            pronunciation_score=round(pronunciation_score, 2),
            confidence_score=round(confidence_score, 2),
            engagement_score=engagement_score,
            action="retry",
            feedback="Let's try that one again with an extra cue from the avatar.",
            next_target=attempted_target,
        )

    session.status = "escalated"
    alert = _create_alert(
        session,
        reason="repeated_failure" if session.retries_used >= session.max_retries else "low_confidence",
        message=f"Please help {store.children[session.child_id].name} with target '{attempted_target}'.",
    )
    return SpeechEvaluation(
        recognized_text=transcript,
        expected_text=attempted_target,
        pronunciation_score=round(pronunciation_score, 2),
        confidence_score=round(confidence_score, 2),
        engagement_score=engagement_score,
        action="escalate",
        feedback="The AI is no longer confident enough to continue alone, so caregiver help was requested.",
        caregiver_alert_id=alert.alert_id,
    )


def assign_goal(payload: GoalAssignmentRequest) -> Goal:
    child = store.children[payload.child_id]
    goal = Goal(
        goal_id=f"goal-{uuid4().hex[:8]}",
        target_text=payload.target_text,
        cue=payload.cue,
        difficulty=payload.difficulty,
    )
    child.goals.append(goal)
    return goal


def manual_escalation(payload: EscalationRequest) -> Alert:
    session = store.sessions[payload.session_id]
    session.status = "escalated"
    return _create_alert(session, reason=payload.reason, message=payload.message)


def build_child_report(child_id: str) -> ChildReport:
    child = store.children[child_id]
    progress = [snapshot for key, snapshot in store.progress.items() if key[0] == child_id]
    active_alerts = [
        alert for alert in store.alerts.values()
        if alert.child_id == child_id and not alert.acknowledged
    ]
    recent_sessions = [
        session for session in store.sessions.values()
        if session.child_id == child_id
    ]
    recent_sessions.sort(key=lambda session: session.started_at, reverse=True)
    return ChildReport(
        child=child,
        progress=progress,
        active_alerts=active_alerts,
        recent_sessions=recent_sessions[:5],
    )


def enterprise_usage() -> EnterpriseUsage:
    mastery_scores = [snapshot.mastery_score for snapshot in store.progress.values()]
    active_sessions = [session for session in store.sessions.values() if session.status == "active"]
    return EnterpriseUsage(
        total_children=len(store.children),
        total_caregivers=len(store.caregivers),
        total_clinicians=len(store.clinicians),
        active_sessions=len(active_sessions),
        total_alerts=len(store.alerts),
        average_mastery=round(sum(mastery_scores) / len(mastery_scores), 2) if mastery_scores else 0.0,
    )
