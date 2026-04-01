from __future__ import annotations

"""Tests for expert providers: SpeechExpert, EngagementExpert, ReasoningExpert,
PlannerExpert, WorkflowExpert, and OutputFilterExpert."""

import pytest

from app.models import CommunicationProfile, OutputPolicy
from app.providers import (
    EngagementExpert,
    OutputFilterExpert,
    PlannerExpert,
    ReasoningExpert,
    SpeechExpert,
    WorkflowExpert,
)


# ── SpeechExpert ──────────────────────────────────────────────────────────────


class TestSpeechExpert:
    def test_exact_match_score(self):
        expert = SpeechExpert()
        score, trace = expert.evaluate("ba", "ba")
        assert score == 0.96
        assert "Strong match" in trace.summary

    def test_partial_match_score(self):
        expert = SpeechExpert()
        score, trace = expert.evaluate("ba", "ba ba ba")
        assert score == 0.72

    def test_first_phoneme_match(self):
        expert = SpeechExpert()
        score, _ = expert.evaluate("ba", "bzzz")
        assert score == 0.55

    def test_no_match_score(self):
        expert = SpeechExpert()
        score, _ = expert.evaluate("ba", "zzz")
        assert score == 0.24

    def test_trace_confidence_equals_score(self):
        expert = SpeechExpert()
        score, trace = expert.evaluate("pa", "pa")
        assert trace.confidence == round(score, 2)


# ── EngagementExpert ──────────────────────────────────────────────────────────


class TestEngagementExpert:
    def test_high_engagement(self):
        expert = EngagementExpert()
        score, trace = expert.assess(0.90)
        assert score == 0.90
        assert "engaged" in trace.summary.lower()

    def test_medium_engagement(self):
        expert = EngagementExpert()
        score, trace = expert.assess(0.60)
        assert 0.5 <= score < 0.75
        assert "softening" in trace.summary.lower()

    def test_low_engagement(self):
        expert = EngagementExpert()
        _, trace = expert.assess(0.30)
        assert "low" in trace.summary.lower()


# ── ReasoningExpert ───────────────────────────────────────────────────────────


class TestReasoningExpert:
    def test_advance_decision(self):
        expert = ReasoningExpert()
        trace = expert.decide(
            pronunciation_score=0.96,
            engagement_score=0.80,
            retries_used=0,
            max_retries=2,
        )
        assert "Advance" in trace.summary

    def test_retry_decision(self):
        expert = ReasoningExpert()
        trace = expert.decide(
            pronunciation_score=0.55,
            engagement_score=0.80,
            retries_used=0,
            max_retries=2,
        )
        assert "Retry" in trace.summary

    def test_escalate_decision(self):
        expert = ReasoningExpert()
        trace = expert.decide(
            pronunciation_score=0.24,
            engagement_score=0.30,
            retries_used=2,
            max_retries=2,
        )
        assert "Escalate" in trace.summary

    def test_retry_penalty_applies(self):
        expert = ReasoningExpert()
        no_retry = expert.decide(0.72, 0.75, 0, 2)
        with_retry = expert.decide(0.72, 0.75, 2, 2)
        assert no_retry.confidence > with_retry.confidence


# ── PlannerExpert ─────────────────────────────────────────────────────────────


class TestPlannerExpert:
    def test_explains_goal_choice(self):
        expert = PlannerExpert()
        trace = expert.explain_goal_choice("ba", 0.4)
        assert "ba" in trace.summary
        assert trace.confidence >= 0.5


# ── WorkflowExpert ────────────────────────────────────────────────────────────


class TestWorkflowExpert:
    def test_records_message(self):
        expert = WorkflowExpert()
        trace = expert.record("Session opened.")
        assert "Session opened" in trace.summary
        assert trace.confidence == 0.9


# ── OutputFilterExpert ────────────────────────────────────────────────────────


class TestOutputFilterExpert:
    def _profile(self, audience: str, owner_id: str) -> CommunicationProfile:
        return CommunicationProfile(
            profile_id="p1",
            audience=audience,
            owner_id=owner_id,
            preferred_tone="gentle",
            preferred_pacing="slow",
            sensory_notes=[],
            banned_styles=["loud"],
            preferred_phrases=["quiet try"],
            policy=OutputPolicy(
                policy_id="pol1",
                calmness_level=5,
                verbosity_limit=60,
                encouragement_level=3,
            ),
        )

    def test_default_child_filter(self):
        expert = OutputFilterExpert()
        msg, trace = expert.filter_text("child", "Let us try again now!")
        assert "!" not in msg.text
        assert "gentle" in msg.style_tags

    def test_exclamation_replaced(self):
        expert = OutputFilterExpert()
        msg, _ = expert.filter_text("child", "Great work!")
        assert "!" not in msg.text

    def test_verbosity_limit_applied(self):
        expert = OutputFilterExpert()
        profile = self._profile("child", "child-1")
        long_text = "Let us try together nicely and quietly. " * 10
        msg, _ = expert.filter_text("child", long_text, profile=profile)
        assert len(msg.text) <= 65  # limit=60 + small margin

    def test_banned_style_removed(self):
        expert = OutputFilterExpert()
        profile = self._profile("child", "child-1")
        msg, _ = expert.filter_text("child", "This was loud work today.", profile=profile)
        assert "loud" not in msg.text

    def test_profile_aware_confidence_higher(self):
        expert = OutputFilterExpert()
        profile = self._profile("child", "child-1")
        _, with_profile = expert.filter_text("child", "Try now.", profile=profile)
        _, without = expert.filter_text("child", "Try now.")
        assert with_profile.confidence >= without.confidence

    def test_parent_filter_tags(self):
        expert = OutputFilterExpert()
        msg, _ = expert.filter_text("parent", "Please help your child.")
        assert "clear" in msg.style_tags or "supportive" in msg.style_tags
