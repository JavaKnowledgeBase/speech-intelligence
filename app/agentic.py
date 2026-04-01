from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.data import store
from app.db import persistence
from app.integrations import integration_gateway
from app.models import (
    Alert,
    AlertAcknowledgeResponse,
    AgentGraph,
    ArchitectureBlueprint,
    AttemptIngestionRequest,
    ChildAnalytics,
    ChildAttemptVector,
    ChildProfile,
    ChildReport,
    CommunicationProfile,
    EnterpriseAnalytics,
    EnterpriseUsage,
    EnvironmentCheckRequest,
    EnvironmentCheckResult,
    EnvironmentProfile,
    EscalationRequest,
    FilterPreviewResponse,
    FilteredMessage,
    Goal,
    GoalAssignmentRequest,
    ProgressSnapshot,
    ProviderStatus,
    ReferenceVector,
    SessionCompletionResponse,
    SessionDetail,
    SessionEvent,
    SessionStartRequest,
    SessionStartResponse,
    SessionState,
    SpeechEvaluation,
    TargetCurriculumItem,
    VectorMatchResult,
    WorkflowQueueSnapshot,
)
from app.providers import EngagementExpert, PlannerExpert, ProviderCatalog, ReasoningExpert, SpeechExpert, WorkflowExpert
from app.workflows import workflow_manager


class TherapyOrchestrator:
    def __init__(self) -> None:
        self.speech_expert = SpeechExpert()
        self.engagement_expert = EngagementExpert()
        self.reasoning_expert = ReasoningExpert()
        self.planner_expert = PlannerExpert()
        self.workflow_expert = WorkflowExpert()

    def _progress_for(self, child_id: str, target_text: str) -> ProgressSnapshot:
        return store.progress.get((child_id, target_text), ProgressSnapshot(child_id=child_id, target_text=target_text))

    def _store_session(self, session: SessionState) -> None:
        store.sessions[session.session_id] = session
        persistence.upsert_session(session)

    def _record_event(self, session: SessionState, kind: str, detail: str) -> SessionEvent:
        event = SessionEvent(timestamp=datetime.utcnow(), kind=kind, detail=detail)
        session.events.append(event)
        persistence.append_session_event(session.session_id, event)
        return event

    def child_profile(self, child_id: str) -> CommunicationProfile | None:
        return integration_gateway.get_child_profile(child_id)

    def parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return integration_gateway.get_parent_profile(caregiver_id)

    def environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        return integration_gateway.get_environment_profile(child_id)

    def _filter_output(self, audience: str, text: str, owner_id: str | None = None) -> tuple[FilteredMessage, list]:
        return integration_gateway.filter_output(audience, text, owner_id=owner_id)

    def choose_next_goal(self, child: ChildProfile) -> tuple[Goal, float]:
        ranked_goals = sorted(child.goals, key=lambda goal: self._progress_for(child.child_id, goal.target_text).mastery_score)
        chosen = ranked_goals[0]
        mastery = self._progress_for(child.child_id, chosen.target_text).mastery_score
        return chosen, mastery

    def start_session(self, payload: SessionStartRequest) -> SessionStartResponse:
        child_id = payload.child_id
        child = store.children[child_id]
        goal, mastery = self.choose_next_goal(child)
        planner_trace = self.planner_expert.explain_goal_choice(goal.target_text, mastery)
        workflow_trace = self.workflow_expert.record("Session workflow opened and ready for event streaming.")

        environment_ok = self.environment_profile(child_id) is not None
        environment_note = None if environment_ok else "No environment baseline yet. Ask parent for a 360 degree room photo."
        parent_message = None
        if payload.environment is not None:
            environment_result = self.check_environment(payload.environment)
            environment_ok = environment_result.matches_standard
            if not environment_result.matches_standard:
                environment_note = "; ".join(environment_result.alerts) if environment_result.alerts else "Room setup needs adjustment before starting."
                parent_text = "Please adjust the room before starting. " + " ".join(environment_result.recommended_adjustments[:2])
                filtered_parent, _ = self._filter_output("parent", parent_text, owner_id=child.caregiver_id)
                parent_message = filtered_parent.text
            else:
                environment_note = "Environment matches the child's saved comfort standard."

        filtered_message, filter_trace = self._filter_output("child", f"Let's practice {goal.target_text} with a short, playful repetition round", owner_id=child_id)
        session = SessionState(
            session_id=f"session-{uuid4().hex[:10]}",
            child_id=child_id,
            started_at=datetime.utcnow(),
            current_goal_id=goal.goal_id,
            current_target=goal.target_text,
            events=[],
        )
        self._store_session(session)
        self._record_event(session, "session_started", f"Started target {goal.target_text}")
        self._record_event(session, "planner_trace", planner_trace.summary)
        self._record_event(session, "workflow_trace", workflow_trace.summary)
        self._record_event(session, "output_filter_trace", filter_trace[0].summary)
        if environment_note:
            self._record_event(session, "environment_note", environment_note)
        if parent_message:
            self._record_event(session, "environment_parent_message", parent_message)
        return SessionStartResponse(
            session_id=session.session_id,
            child_id=child_id,
            target_text=goal.target_text,
            cue=goal.cue,
            message=filtered_message.text,
            assigned_agents=["session_conductor", "speech_scoring_expert", "engagement_expert", "care_plan_expert", "workflow_expert", "reporting_expert", "output_filter_expert", "environment_expert"],
            environment_ok=environment_ok,
            environment_note=environment_note,
            parent_message=parent_message,
        )

    def _update_progress(self, child_id: str, target_text: str, success: bool) -> ProgressSnapshot:
        key = (child_id, target_text)
        snapshot = self._progress_for(child_id, target_text)
        snapshot.attempts += 1
        if success:
            snapshot.successes += 1
        snapshot.mastery_score = round(snapshot.successes / snapshot.attempts, 2)
        snapshot.last_practiced_at = datetime.utcnow()
        store.progress[key] = snapshot
        persistence.upsert_progress(child_id, snapshot)
        return snapshot

    def _create_alert(self, session: SessionState, reason: str, message: str) -> tuple[Alert, list]:
        child = store.children[session.child_id]
        filtered_message, filter_trace = self._filter_output("parent", message, owner_id=child.caregiver_id)
        alert = Alert(
            alert_id=f"alert-{uuid4().hex[:8]}",
            session_id=session.session_id,
            child_id=session.child_id,
            caregiver_id=child.caregiver_id,
            reason=reason,
            message=filtered_message.text,
            created_at=datetime.utcnow(),
        )
        store.alerts[alert.alert_id] = alert
        persistence.upsert_alert(alert)
        self._record_event(session, "alert_created", filtered_message.text)
        self._record_event(session, "output_filter_trace", filter_trace[0].summary)
        return alert, filter_trace

    def process_turn(self, session_id: str, transcript: str, attention_score: float) -> SpeechEvaluation:
        session = store.sessions[session_id]
        attempted_target = session.current_target
        pronunciation_score, speech_trace = self.speech_expert.evaluate(attempted_target, transcript)
        engagement_score, engagement_trace = self.engagement_expert.assess(attention_score)
        reasoning_trace = self.reasoning_expert.decide(pronunciation_score=pronunciation_score, engagement_score=engagement_score, retries_used=session.retries_used, max_retries=session.max_retries)
        workflow_trace = self.workflow_expert.record("Therapy turn processed through expert pipeline.")
        success = pronunciation_score >= 0.9 and engagement_score >= 0.55
        confidence_score = reasoning_trace.confidence
        attempt = self.ingest_attempt(
            AttemptIngestionRequest(
                session_id=session_id,
                child_id=session.child_id,
                target_text=attempted_target,
                transcript=transcript,
                pronunciation_score=round(pronunciation_score, 2),
                engagement_score=engagement_score,
                success_flag=success,
            )
        )
        persistence.upsert_attempt_vector(attempt)
        self._record_event(
            session,
            "attempt_vector_recorded",
            f"Stored attempt {attempt.attempt_id} with top match {attempt.top_match_reference_id or 'none'} at similarity {attempt.cosine_similarity:.2f}",
        )

        if success:
            self._update_progress(session.child_id, attempted_target, success=True)
            session.reward_points += 10
            session.retries_used = 0
            self._store_session(session)
            self._record_event(session, "attempt_success", f"Child matched target {attempted_target}")
            child = store.children[session.child_id]
            next_goal, _ = self.choose_next_goal(child)
            session.current_goal_id = next_goal.goal_id
            session.current_target = next_goal.target_text
            self._store_session(session)
            filtered_feedback, filter_trace = self._filter_output("child", "Nice work. We can move to the next sound now", owner_id=session.child_id)
            expert_trace = [speech_trace, engagement_trace, reasoning_trace, workflow_trace, filter_trace[0]]
            return SpeechEvaluation(recognized_text=transcript, expected_text=attempted_target, pronunciation_score=round(pronunciation_score, 2), confidence_score=round(confidence_score, 2), engagement_score=engagement_score, action="advance", feedback=filtered_feedback.text, next_target=next_goal.target_text, expert_trace=expert_trace)

        self._update_progress(session.child_id, attempted_target, success=False)

        if confidence_score >= 0.58 and session.retries_used < session.max_retries:
            session.retries_used += 1
            self._store_session(session)
            self._record_event(session, "attempt_retry", f"Retry requested for {attempted_target}")
            filtered_feedback, filter_trace = self._filter_output("child", "Let us try that one again with one quiet extra cue", owner_id=session.child_id)
            expert_trace = [speech_trace, engagement_trace, reasoning_trace, workflow_trace, filter_trace[0]]
            return SpeechEvaluation(recognized_text=transcript, expected_text=attempted_target, pronunciation_score=round(pronunciation_score, 2), confidence_score=round(confidence_score, 2), engagement_score=engagement_score, action="retry", feedback=filtered_feedback.text, next_target=attempted_target, expert_trace=expert_trace)

        session.status = "escalated"
        self._store_session(session)
        alert, filter_trace = self._create_alert(session, reason="repeated_failure" if session.retries_used >= session.max_retries else "low_confidence", message=f"Please help {store.children[session.child_id].name} with target '{attempted_target}'. Use a calm short prompt and model the sound once")
        priority = "high" if engagement_score < 0.5 else "medium"
        workflow_manager.enqueue_clinician_review(child_id=session.child_id, session_id=session.session_id, summary=f"Review escalated session for target '{attempted_target}' after low AI confidence.", priority=priority)
        filtered_child_feedback, child_filter_trace = self._filter_output("child", "We can pause here. A grown-up will help with the next try", owner_id=session.child_id)
        expert_trace = [speech_trace, engagement_trace, reasoning_trace, workflow_trace, filter_trace[0], child_filter_trace[0]]
        return SpeechEvaluation(recognized_text=transcript, expected_text=attempted_target, pronunciation_score=round(pronunciation_score, 2), confidence_score=round(confidence_score, 2), engagement_score=engagement_score, action="escalate", feedback=filtered_child_feedback.text, parent_message=alert.message, caregiver_alert_id=alert.alert_id, expert_trace=expert_trace)

    def filter_preview(self, audience: str, text: str, owner_id: str | None = None) -> FilterPreviewResponse:
        message, trace = self._filter_output(audience, text, owner_id=owner_id)
        return FilterPreviewResponse(message=message, expert_trace=trace)

    def get_child_communication_profile(self, child_id: str) -> CommunicationProfile:
        return store.child_communication_profiles[child_id]

    def get_parent_communication_profile(self, caregiver_id: str) -> CommunicationProfile:
        return store.parent_communication_profiles[caregiver_id]

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile:
        return store.environment_profiles[child_id]

    def check_environment(self, payload: EnvironmentCheckRequest) -> EnvironmentCheckResult:
        return integration_gateway.check_environment(payload)

    def list_curriculum(self) -> list[TargetCurriculumItem]:
        return integration_gateway.list_curriculum()

    def list_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        return integration_gateway.list_reference_vectors(target_id)

    def list_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        return integration_gateway.list_attempt_vectors(child_id)

    def match_reference(self, target_id: str, modality: str, embedding: list[float]) -> VectorMatchResult | None:
        return integration_gateway.match_reference(target_id, modality, embedding)

    def ingest_attempt(self, payload: AttemptIngestionRequest) -> ChildAttemptVector:
        return integration_gateway.ingest_attempt(payload)

    def assign_goal(self, payload: GoalAssignmentRequest) -> Goal:
        child = store.children[payload.child_id]
        goal = Goal(goal_id=f"goal-{uuid4().hex[:8]}", target_text=payload.target_text, cue=payload.cue, difficulty=payload.difficulty)
        child.goals.append(goal)
        return goal

    def manual_escalation(self, payload: EscalationRequest) -> Alert:
        session = store.sessions[payload.session_id]
        session.status = "escalated"
        self._store_session(session)
        alert, _ = self._create_alert(session, reason=payload.reason, message=payload.message)
        workflow_manager.enqueue_clinician_review(child_id=session.child_id, session_id=session.session_id, summary=f"Manual escalation created: {payload.message}", priority="high")
        return alert

    def build_child_report(self, child_id: str) -> ChildReport:
        child = store.children[child_id]
        progress = [snapshot for key, snapshot in store.progress.items() if key[0] == child_id]
        active_alerts = [alert for alert in store.alerts.values() if alert.child_id == child_id and not alert.acknowledged]
        recent_sessions = [session for session in store.sessions.values() if session.child_id == child_id]
        recent_sessions.sort(key=lambda session: session.started_at, reverse=True)
        return ChildReport(child=child, progress=progress, active_alerts=active_alerts, recent_sessions=recent_sessions[:5])

    def session_detail(self, session_id: str) -> SessionDetail:
        session = store.sessions[session_id]
        child = store.children[session.child_id]
        alerts = [alert for alert in store.alerts.values() if alert.session_id == session_id and not alert.acknowledged]
        recommended_actions = ["Continue autonomous practice" if session.status == "active" else "Complete caregiver assist or clinician review", f"Current target: {session.current_target}", f"Reward points: {session.reward_points}"]
        return SessionDetail(session=session, child=child, active_alerts=alerts, recommended_actions=recommended_actions)

    def complete_session(self, session_id: str) -> SessionCompletionResponse:
        session = store.sessions[session_id]
        session.status = "completed" if session.status == "active" else session.status
        self._store_session(session)
        self._record_event(session, "session_completed", "Session closed by API.")
        return SessionCompletionResponse(session_id=session_id, status=session.status, reward_points=session.reward_points, total_events=len(session.events))

    def caregiver_alerts(self, caregiver_id: str) -> list[Alert]:
        return workflow_manager.caregiver_alerts(caregiver_id)

    def acknowledge_alert(self, alert_id: str) -> AlertAcknowledgeResponse:
        return workflow_manager.acknowledge_alert(alert_id)

    def clinician_queue(self, clinician_id: str):
        return workflow_manager.clinician_queue(clinician_id)

    def workflows_snapshot(self) -> WorkflowQueueSnapshot:
        return workflow_manager.snapshot()

    def enterprise_usage(self) -> EnterpriseUsage:
        mastery_scores = [snapshot.mastery_score for snapshot in store.progress.values()]
        active_sessions = [session for session in store.sessions.values() if session.status == "active"]
        return EnterpriseUsage(total_children=len(store.children), total_caregivers=len(store.caregivers), total_clinicians=len(store.clinicians), active_sessions=len(active_sessions), total_alerts=len(store.alerts), average_mastery=round(sum(mastery_scores) / len(mastery_scores), 2) if mastery_scores else 0.0)

    def architecture(self) -> ArchitectureBlueprint:
        return ProviderCatalog.blueprint()

    def architecture_graph(self) -> AgentGraph:
        return ProviderCatalog.graph()

    def provider_statuses(self) -> list[ProviderStatus]:
        return ProviderCatalog.statuses()

    def child_analytics(self, child_id: str) -> ChildAnalytics:
        child = store.children[child_id]
        progress = [snapshot for key, snapshot in store.progress.items() if key[0] == child_id]
        sessions = [session for session in store.sessions.values() if session.child_id == child_id]
        attempts = store.attempt_vectors.get(child_id, [])

        total_sessions = len(sessions)
        completed = sum(1 for session in sessions if session.status == "completed")
        escalated = sum(1 for session in sessions if session.status == "escalated")
        total_attempts = sum(snapshot.attempts for snapshot in progress)
        successes = sum(snapshot.successes for snapshot in progress)
        targets_mastered = sum(1 for snapshot in progress if snapshot.mastery_score >= 0.8)

        mastery_scores = [snapshot.mastery_score for snapshot in progress]
        overall = round(sum(mastery_scores) / len(mastery_scores), 2) if mastery_scores else 0.0

        if len(attempts) >= 6:
            recent_half = attempts[-len(attempts) // 2 :]
            older_half = attempts[: len(attempts) // 2]
            recent_rate = sum(1 for attempt in recent_half if attempt.success_flag) / len(recent_half)
            older_rate = sum(1 for attempt in older_half if attempt.success_flag) / len(older_half)
            if recent_rate > older_rate + 0.1:
                trend = "improving"
            elif recent_rate < older_rate - 0.1:
                trend = "needs_support"
            else:
                trend = "stable"
        elif overall >= 0.7:
            trend = "improving"
        elif overall <= 0.4:
            trend = "needs_support"
        else:
            trend = "stable"

        top_targets = sorted(progress, key=lambda snapshot: snapshot.mastery_score, reverse=True)[:5]

        return ChildAnalytics(
            child_id=child_id,
            child_name=child.name,
            total_sessions=total_sessions,
            completed_sessions=completed,
            escalated_sessions=escalated,
            total_attempts=total_attempts,
            successful_attempts=successes,
            overall_mastery=overall,
            targets_practiced=len(progress),
            targets_mastered=targets_mastered,
            streak_days=child.streak_days,
            top_targets=top_targets,
            recent_trend=trend,
        )

    def enterprise_analytics(self) -> EnterpriseAnalytics:
        all_sessions = list(store.sessions.values())
        all_alerts = list(store.alerts.values())
        mastery_scores = [snapshot.mastery_score for snapshot in store.progress.values()]
        needs_support = sum(
            1
            for child_id in store.children
            if any(snapshot.mastery_score < 0.4 for key, snapshot in store.progress.items() if key[0] == child_id)
        )
        return EnterpriseAnalytics(
            total_children=len(store.children),
            total_sessions=len(all_sessions),
            completed_sessions=sum(1 for session in all_sessions if session.status == "completed"),
            escalated_sessions=sum(1 for session in all_sessions if session.status == "escalated"),
            average_mastery=round(sum(mastery_scores) / len(mastery_scores), 2) if mastery_scores else 0.0,
            total_alerts=len(all_alerts),
            unacknowledged_alerts=sum(1 for alert in all_alerts if not alert.acknowledged),
            total_reviews=len(workflow_manager.clinician_reviews),
            children_needing_support=needs_support,
        )


orchestrator = TherapyOrchestrator()
