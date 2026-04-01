from __future__ import annotations

"""Tests for session lifecycle: start, speech turns, complete, and escalation."""

import pytest

from app.agentic import TherapyOrchestrator
from app.data import store
from app.models import (
    EnvironmentCheckRequest,
    GoalAssignmentRequest,
    SessionStartRequest,
    SpeechEvaluation,
)


@pytest.fixture
def orch() -> TherapyOrchestrator:
    return TherapyOrchestrator()


@pytest.fixture
def session_id(orch) -> str:
    resp = orch.start_session(SessionStartRequest(child_id="child-1"))
    return resp.session_id


# ── Session start ─────────────────────────────────────────────────────────────


class TestSessionStart:
    def test_returns_session_id(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        assert resp.session_id.startswith("session-")

    def test_session_stored_in_store(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        assert resp.session_id in store.sessions

    def test_target_text_is_non_empty(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        assert len(resp.target_text) > 0

    def test_message_is_filtered(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        # Filtered output must not have bare exclamation marks
        assert "!" not in resp.message

    def test_assigned_agents_listed(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        assert "output_filter_expert" in resp.assigned_agents

    def test_environment_ok_when_no_payload(self, orch):
        # child-1 has a saved environment profile, so ok=True by default
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        assert resp.environment_ok is True

    def test_environment_alert_when_noisy(self, orch):
        env = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.85,  # way above baseline
            lighting_score=0.72,
        )
        resp = orch.start_session(SessionStartRequest(child_id="child-1", environment=env))
        assert resp.environment_ok is False
        assert resp.environment_note is not None

    def test_environment_ok_when_matching(self, orch):
        env = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.2,
            lighting_score=0.72,
        )
        resp = orch.start_session(SessionStartRequest(child_id="child-1", environment=env))
        assert resp.environment_ok is True


# ── Speech turns ──────────────────────────────────────────────────────────────


class TestSpeechTurns:
    def test_perfect_match_advances(self, orch, session_id):
        session = store.sessions[session_id]
        target = session.current_target
        result = orch.process_turn(session_id, target, attention_score=0.9)
        assert isinstance(result, SpeechEvaluation)
        assert result.action == "advance"
        assert result.pronunciation_score >= 0.9

    def test_perfect_match_records_attempt(self, orch, session_id):
        before = len(store.attempt_vectors.get("child-1", []))
        session = store.sessions[session_id]
        orch.process_turn(session_id, session.current_target, attention_score=0.9)
        after = len(store.attempt_vectors.get("child-1", []))
        assert after == before + 1

    def test_partial_match_retries(self, orch, session_id):
        session = store.sessions[session_id]
        target = session.current_target
        # First letter match → partial score ~0.55
        partial_transcript = target[0] + "zzz"
        result = orch.process_turn(session_id, partial_transcript, attention_score=0.8)
        # Low pronunciation score but decent engagement — should retry
        assert result.action in {"retry", "escalate"}

    def test_empty_transcript_eventually_escalates(self, orch, session_id):
        # Force escalation by exhausting retries with a bad transcript
        for _ in range(4):
            result = orch.process_turn(session_id, "zzzzz", attention_score=0.3)
        assert result.action == "escalate"

    def test_escalation_creates_alert(self, orch, session_id):
        before_alerts = len(store.alerts)
        for _ in range(4):
            orch.process_turn(session_id, "zzzzz", attention_score=0.3)
        assert len(store.alerts) > before_alerts

    def test_advance_updates_progress(self, orch, session_id):
        session = store.sessions[session_id]
        target = session.current_target
        orch.process_turn(session_id, target, attention_score=0.9)
        key = ("child-1", target)
        assert key in store.progress
        snap = store.progress[key]
        assert snap.successes >= 1

    def test_feedback_text_is_filtered(self, orch, session_id):
        session = store.sessions[session_id]
        result = orch.process_turn(session_id, session.current_target, attention_score=0.9)
        assert "!" not in result.feedback
        assert len(result.feedback) > 0

    def test_expert_trace_populated(self, orch, session_id):
        session = store.sessions[session_id]
        result = orch.process_turn(session_id, session.current_target, attention_score=0.9)
        assert len(result.expert_trace) >= 4


# ── Session complete ──────────────────────────────────────────────────────────


class TestSessionComplete:
    def test_complete_marks_completed(self, orch, session_id):
        resp = orch.complete_session(session_id)
        assert resp.status == "completed"

    def test_complete_returns_reward_points(self, orch, session_id):
        resp = orch.complete_session(session_id)
        assert isinstance(resp.reward_points, int)

    def test_complete_returns_event_count(self, orch, session_id):
        resp = orch.complete_session(session_id)
        assert resp.total_events >= 1


# ── Session detail ────────────────────────────────────────────────────────────


class TestSessionDetail:
    def test_detail_has_child(self, orch, session_id):
        detail = orch.session_detail(session_id)
        assert detail.child.child_id == "child-1"

    def test_detail_has_recommended_actions(self, orch, session_id):
        detail = orch.session_detail(session_id)
        assert len(detail.recommended_actions) > 0


# ── Goal assignment ───────────────────────────────────────────────────────────


class TestGoalAssignment:
    def test_assign_adds_goal_to_child(self, orch):
        before = len(store.children["child-1"].goals)
        payload = GoalAssignmentRequest(
            child_id="child-1", target_text="fa", cue="Bite your lip lightly for fa.", difficulty=2
        )
        goal = orch.assign_goal(payload)
        assert goal.goal_id.startswith("goal-")
        assert len(store.children["child-1"].goals) == before + 1
