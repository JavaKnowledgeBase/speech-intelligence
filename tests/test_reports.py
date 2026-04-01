from __future__ import annotations

"""Tests for child reports and enterprise usage summary."""

import pytest

from app.agentic import TherapyOrchestrator
from app.models import SessionStartRequest


@pytest.fixture
def orch() -> TherapyOrchestrator:
    return TherapyOrchestrator()


class TestChildReport:
    def test_report_has_child(self, orch):
        report = orch.build_child_report("child-1")
        assert report.child.child_id == "child-1"

    def test_report_includes_seeded_progress(self, orch):
        report = orch.build_child_report("child-1")
        # data.py seeds progress for child-1 / ba
        texts = [p.target_text for p in report.progress]
        assert "ba" in texts

    def test_report_no_active_alerts_initially(self, orch):
        report = orch.build_child_report("child-1")
        assert report.active_alerts == []

    def test_report_recent_sessions_limited_to_five(self, orch):
        # Create 6 sessions
        for _ in range(6):
            orch.start_session(SessionStartRequest(child_id="child-1"))
        report = orch.build_child_report("child-1")
        assert len(report.recent_sessions) <= 5


class TestEnterpriseUsage:
    def test_usage_children_count(self, orch):
        usage = orch.enterprise_usage()
        assert usage.total_children == 2

    def test_usage_caregivers_count(self, orch):
        usage = orch.enterprise_usage()
        assert usage.total_caregivers == 2

    def test_usage_clinicians_count(self, orch):
        usage = orch.enterprise_usage()
        assert usage.total_clinicians == 1

    def test_usage_no_active_sessions_initially(self, orch):
        usage = orch.enterprise_usage()
        assert usage.active_sessions == 0

    def test_usage_average_mastery_in_range(self, orch):
        usage = orch.enterprise_usage()
        assert 0.0 <= usage.average_mastery <= 1.0
