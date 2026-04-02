from __future__ import annotations

"""Tests for child analytics, enterprise analytics, and related models."""

import pytest

from app.clock import utc_now
from app.agentic import TherapyOrchestrator
from app.data import store
from app.models import (
    ChildAnalytics,
    EnterpriseAnalytics,
    SessionStartRequest,
    SpeechEvaluation,
)


@pytest.fixture
def orch() -> TherapyOrchestrator:
    return TherapyOrchestrator()


# ── Child analytics ───────────────────────────────────────────────────────────


class TestChildAnalytics:
    def test_returns_child_analytics(self, orch):
        result = orch.child_analytics("child-1")
        assert isinstance(result, ChildAnalytics)

    def test_child_name_correct(self, orch):
        result = orch.child_analytics("child-1")
        assert result.child_name == "Liam"

    def test_child_id_correct(self, orch):
        result = orch.child_analytics("child-1")
        assert result.child_id == "child-1"

    def test_streak_days_from_profile(self, orch):
        result = orch.child_analytics("child-1")
        assert result.streak_days == 3  # seeded value

    def test_overall_mastery_from_seeded_progress(self, orch):
        # child-1 has ba=0.75, ma=0.40 → avg=0.575
        result = orch.child_analytics("child-1")
        assert 0.0 <= result.overall_mastery <= 1.0

    def test_targets_practiced_count(self, orch):
        # child-1 has 2 seeded progress entries (ba, ma)
        result = orch.child_analytics("child-1")
        assert result.targets_practiced == 2

    def test_targets_mastered_threshold(self, orch):
        # ba=0.75 (not mastered), ma=0.40 → 0 mastered
        result = orch.child_analytics("child-1")
        assert result.targets_mastered == 0

    def test_mastered_count_after_high_mastery(self, orch):
        # Manually push mastery above 0.8
        from app.models import ProgressSnapshot
        store.progress[("child-1", "ba")] = ProgressSnapshot(
            child_id="child-1", target_text="ba",
            attempts=10, successes=9, mastery_score=0.9,
            last_practiced_at=utc_now(),
        )
        result = orch.child_analytics("child-1")
        assert result.targets_mastered >= 1

    def test_total_sessions_zero_initially(self, orch):
        result = orch.child_analytics("child-1")
        assert result.total_sessions == 0

    def test_total_sessions_increments(self, orch):
        orch.start_session(SessionStartRequest(child_id="child-1"))
        result = orch.child_analytics("child-1")
        assert result.total_sessions == 1

    def test_top_targets_limited_to_five(self, orch):
        result = orch.child_analytics("child-1")
        assert len(result.top_targets) <= 5

    def test_trend_is_valid(self, orch):
        result = orch.child_analytics("child-1")
        assert result.recent_trend in {"improving", "stable", "needs_support"}

    def test_trend_needs_support_for_low_mastery(self, orch):
        from app.models import ProgressSnapshot
        store.progress[("child-1", "ba")] = ProgressSnapshot(
            child_id="child-1", target_text="ba",
            attempts=10, successes=2, mastery_score=0.2,
            last_practiced_at=utc_now(),
        )
        store.progress[("child-1", "ma")] = ProgressSnapshot(
            child_id="child-1", target_text="ma",
            attempts=5, successes=1, mastery_score=0.2,
            last_practiced_at=utc_now(),
        )
        result = orch.child_analytics("child-1")
        assert result.recent_trend == "needs_support"

    def test_trend_improving_for_high_mastery(self, orch):
        from app.models import ProgressSnapshot
        # Both targets must be high so overall >= 0.7
        store.progress[("child-1", "ba")] = ProgressSnapshot(
            child_id="child-1", target_text="ba",
            attempts=10, successes=9, mastery_score=0.9,
            last_practiced_at=utc_now(),
        )
        store.progress[("child-1", "ma")] = ProgressSnapshot(
            child_id="child-1", target_text="ma",
            attempts=10, successes=8, mastery_score=0.8,
            last_practiced_at=utc_now(),
        )
        result = orch.child_analytics("child-1")
        assert result.recent_trend == "improving"

    def test_attempt_based_trend_improving(self, orch):
        from app.models import ChildAttemptVector
                # 3 older failures + 3 recent successes → improving
        base = utc_now()
        vectors = [
            ChildAttemptVector(attempt_id=f"a{i}", child_id="child-1", target_id="target-b",
                               session_id="s1", success_flag=(i >= 3), created_at=base)
            for i in range(6)
        ]
        store.attempt_vectors["child-1"] = vectors
        result = orch.child_analytics("child-1")
        assert result.recent_trend == "improving"


# ── Enterprise analytics ──────────────────────────────────────────────────────


class TestEnterpriseAnalytics:
    def test_returns_enterprise_analytics(self, orch):
        result = orch.enterprise_analytics()
        assert isinstance(result, EnterpriseAnalytics)

    def test_total_children(self, orch):
        result = orch.enterprise_analytics()
        assert result.total_children == 2

    def test_no_sessions_initially(self, orch):
        result = orch.enterprise_analytics()
        assert result.total_sessions == 0

    def test_session_count_after_start(self, orch):
        orch.start_session(SessionStartRequest(child_id="child-1"))
        result = orch.enterprise_analytics()
        assert result.total_sessions == 1

    def test_no_alerts_initially(self, orch):
        result = orch.enterprise_analytics()
        assert result.total_alerts == 0
        assert result.unacknowledged_alerts == 0

    def test_average_mastery_from_seeded_progress(self, orch):
        result = orch.enterprise_analytics()
        assert 0.0 <= result.average_mastery <= 1.0

    def test_children_needing_support_low_mastery(self, orch):
        from app.models import ProgressSnapshot
        # Drive child-1 mastery below 0.4
        store.progress[("child-1", "ba")] = ProgressSnapshot(
            child_id="child-1", target_text="ba",
            attempts=10, successes=2, mastery_score=0.2,
            last_practiced_at=utc_now(),
        )
        result = orch.enterprise_analytics()
        assert result.children_needing_support >= 1


# ── Persistence no-op (Supabase not configured) ────────────────────────────────


class TestPersistenceNoOp:
    """
    When Supabase is not configured, all persistence calls must be no-ops —
    they must not raise and must not affect in-memory state.
    """

    def test_upsert_session_no_op(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        # If persistence raised, the session still exists in memory
        assert resp.session_id in store.sessions

    def test_upsert_progress_no_op(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        session = store.sessions[resp.session_id]
        # Perfect match → advances and updates progress
        orch.process_turn(resp.session_id, session.current_target, attention_score=0.9)
        # No exception raised; progress updated in memory
        assert any(s.attempts > 0 for s in store.progress.values())

    def test_upsert_alert_no_op(self, orch):
        resp = orch.start_session(SessionStartRequest(child_id="child-1"))
        from app.models import EscalationRequest
        orch.manual_escalation(EscalationRequest(
            session_id=resp.session_id, reason="manual", message="Test."
        ))
        assert len(store.alerts) == 1

    def test_load_progress_no_op_returns_empty(self):
        from app.db import persistence
        result = persistence.load_progress_for_child("child-1")
        assert result == {}

    def test_load_sessions_no_op_returns_empty(self):
        from app.db import persistence
        result = persistence.load_sessions_for_child("child-1")
        assert result == []

    def test_load_alerts_no_op_returns_empty(self):
        from app.db import persistence
        result = persistence.load_alerts()
        assert result == []

    def test_seed_script_dry_run(self):
        """seed_supabase.py --dry-run must complete without errors."""
        from scripts.seed_supabase import seed
        seed(dry_run=True)  # should not raise
