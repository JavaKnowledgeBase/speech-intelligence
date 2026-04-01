from __future__ import annotations

"""Tests for WorkflowManager: clinician reviews, alerts, acknowledgment."""

import pytest

from app.agentic import TherapyOrchestrator
from app.data import store
from app.models import (
    EscalationRequest,
    SessionStartRequest,
)
from app.workflows import WorkflowManager


@pytest.fixture
def mgr() -> WorkflowManager:
    return WorkflowManager()


@pytest.fixture
def orch() -> TherapyOrchestrator:
    return TherapyOrchestrator()


@pytest.fixture
def session_id(orch) -> str:
    resp = orch.start_session(SessionStartRequest(child_id="child-1"))
    return resp.session_id


# ── Clinician review queue ────────────────────────────────────────────────────


class TestClinicianReviews:
    def test_enqueue_adds_review(self, mgr):
        mgr.enqueue_clinician_review(
            child_id="child-1",
            session_id="session-x",
            summary="Review test.",
            priority="high",
        )
        queue = mgr.clinician_queue("slp-1")
        assert len(queue) == 1
        assert queue[0].priority == "high"

    def test_enqueue_assigns_correct_clinician(self, mgr):
        mgr.enqueue_clinician_review(
            child_id="child-1",
            session_id="session-x",
            summary="Test review.",
            priority="medium",
        )
        assert mgr.clinician_queue("slp-1")[0].clinician_id == "slp-1"

    def test_clinician_queue_filtered_by_clinician(self, mgr):
        mgr.enqueue_clinician_review("child-1", "s1", "Child 1 review.", "medium")
        mgr.enqueue_clinician_review("child-2", "s2", "Child 2 review.", "low")
        # child-1 and child-2 both use slp-1
        all_reviews = mgr.clinician_queue("slp-1")
        assert len(all_reviews) == 2

    def test_snapshot_includes_reviews(self, mgr):
        mgr.enqueue_clinician_review("child-1", "s1", "Review.", "high")
        snap = mgr.snapshot()
        assert len(snap.clinician_reviews) == 1


# ── Caregiver alerts ──────────────────────────────────────────────────────────


class TestCaregiverAlerts:
    def test_escalation_creates_alert(self, orch, session_id):
        payload = EscalationRequest(
            session_id=session_id, reason="manual", message="Manual test escalation."
        )
        orch.manual_escalation(payload)
        alerts = orch.caregiver_alerts("caregiver-1")
        assert len(alerts) >= 1

    def test_alert_caregiver_id_matches(self, orch, session_id):
        payload = EscalationRequest(
            session_id=session_id, reason="manual", message="Test."
        )
        orch.manual_escalation(payload)
        alerts = orch.caregiver_alerts("caregiver-1")
        assert all(a.caregiver_id == "caregiver-1" for a in alerts)


# ── Alert acknowledgment ──────────────────────────────────────────────────────


class TestAlertAcknowledgment:
    def _make_alert(self, orch, session_id) -> str:
        payload = EscalationRequest(
            session_id=session_id, reason="manual", message="Needs review."
        )
        orch.manual_escalation(payload)
        return list(store.alerts.keys())[-1]

    def test_acknowledge_sets_acknowledged(self, orch, session_id):
        alert_id = self._make_alert(orch, session_id)
        resp = orch.acknowledge_alert(alert_id)
        assert resp.acknowledged is True
        assert store.alerts[alert_id].acknowledged is True

    def test_acknowledge_creates_follow_up_review(self, orch, session_id):
        alert_id = self._make_alert(orch, session_id)
        resp = orch.acknowledge_alert(alert_id)
        assert resp.follow_up_review_id is not None


# ── Snapshot ──────────────────────────────────────────────────────────────────


class TestWorkflowSnapshot:
    def test_snapshot_empty_initially(self, orch):
        snap = orch.workflows_snapshot()
        assert snap.pending_alerts == []
        assert snap.clinician_reviews == []

    def test_snapshot_pending_alerts_after_escalation(self, orch, session_id):
        payload = EscalationRequest(
            session_id=session_id, reason="manual", message="Check this."
        )
        orch.manual_escalation(payload)
        snap = orch.workflows_snapshot()
        assert len(snap.pending_alerts) == 1
