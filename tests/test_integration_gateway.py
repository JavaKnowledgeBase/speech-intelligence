from __future__ import annotations

"""Tests for app.integrations.gateway.IntegrationGateway."""

import pytest

from app.integrations.gateway import IntegrationGateway
from app.models import (
    AttemptIngestionRequest,
    ChildAttemptVector,
    CommunicationProfile,
    EnvironmentCheckRequest,
    FilteredMessage,
    ExpertDecision,
    VectorMatchResult,
)


@pytest.fixture
def gateway() -> IntegrationGateway:
    return IntegrationGateway()


# ── Profile access ────────────────────────────────────────────────────────────


class TestProfileAccess:
    def test_get_child_profile_known(self, gateway):
        profile = gateway.get_child_profile("child-1")
        assert isinstance(profile, CommunicationProfile)
        assert profile.owner_id == "child-1"
        assert profile.audience == "child"

    def test_get_child_profile_unknown_returns_none(self, gateway):
        assert gateway.get_child_profile("does-not-exist") is None

    def test_get_parent_profile_known(self, gateway):
        profile = gateway.get_parent_profile("caregiver-1")
        assert isinstance(profile, CommunicationProfile)
        assert profile.audience == "parent"

    def test_get_parent_profile_unknown_returns_none(self, gateway):
        assert gateway.get_parent_profile("ghost-caregiver") is None

    def test_get_environment_profile_known(self, gateway):
        from app.models import EnvironmentProfile
        ep = gateway.get_environment_profile("child-1")
        assert isinstance(ep, EnvironmentProfile)
        assert ep.child_id == "child-1"

    def test_get_environment_profile_unknown_returns_none(self, gateway):
        assert gateway.get_environment_profile("no-child") is None


# ── Output filtering ──────────────────────────────────────────────────────────


class TestFilterOutput:
    def test_returns_filtered_message_and_trace(self, gateway):
        msg, trace = gateway.filter_output("child", "Let us try again now.")
        assert isinstance(msg, FilteredMessage)
        assert isinstance(msg.text, str)
        assert len(msg.text) > 0
        assert isinstance(trace, list)
        assert len(trace) >= 1
        assert isinstance(trace[0], ExpertDecision)

    def test_child_output_is_brief(self, gateway):
        msg, _ = gateway.filter_output("child", "This is a child facing message.")
        assert len(msg.text) <= 120

    def test_parent_output_has_clear_tag(self, gateway):
        msg, _ = gateway.filter_output("parent", "Please help your child now.")
        assert "clear" in msg.style_tags or "supportive" in msg.style_tags

    def test_profile_aware_applies_verbosity_limit(self, gateway):
        long_text = "Let us try this again together with a quiet sound now. " * 5
        msg, _ = gateway.filter_output("child", long_text, owner_id="child-1")
        # child-1 has verbosity_limit=72
        assert len(msg.text) <= 76  # limit + small buffer for terminal period

    def test_trace_has_summary(self, gateway):
        _, trace = gateway.filter_output("child", "Nice work.")
        assert trace[0].summary
        assert len(trace[0].summary) > 5

    def test_filter_escalation_context(self, gateway):
        msg, trace = gateway.filter_output(
            "parent",
            "Please help with the current target.",
            owner_id="caregiver-1",
            context="escalation",
            retries_used=2,
        )
        assert isinstance(msg.text, str)
        assert trace[0].confidence > 0


# ── Environment checks ────────────────────────────────────────────────────────


class TestEnvironmentCheck:
    def test_check_no_profile_returns_not_matching(self, gateway):
        payload = EnvironmentCheckRequest(
            child_id="unknown-child",
            room_embedding=[0.5, 0.3, 0.6, 0.3],
            visual_clutter_score=0.3,
            noise_score=0.2,
            lighting_score=0.7,
        )
        result = gateway.check_environment(payload)
        assert result.matches_standard is False
        assert len(result.alerts) > 0

    def test_check_matching_environment(self, gateway):
        # child-1 baseline: embedding=[0.55,0.33,0.61,0.29], clutter=0.28, noise=0.2, light=0.72
        payload = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.2,
            lighting_score=0.72,
        )
        result = gateway.check_environment(payload)
        assert result.matches_standard is True
        assert result.similarity_score >= 0.99

    def test_check_noisy_environment_adds_alert(self, gateway):
        payload = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.60,  # well above baseline 0.2
            lighting_score=0.72,
        )
        result = gateway.check_environment(payload)
        assert result.matches_standard is False
        assert any("noise" in a.lower() for a in result.alerts)


# ── Curriculum and vector access ──────────────────────────────────────────────


class TestCurriculumAndVectors:
    def test_list_curriculum_non_empty(self, gateway):
        items = gateway.list_curriculum()
        assert len(items) > 0
        assert all(hasattr(i, "target_id") for i in items)

    def test_list_curriculum_contains_letters_and_numbers(self, gateway):
        items = gateway.list_curriculum()
        types = {i.target_type for i in items}
        assert "letter" in types
        assert "number" in types

    def test_list_reference_vectors_known_target(self, gateway):
        refs = gateway.list_reference_vectors("target-a")
        assert isinstance(refs, list)
        assert len(refs) >= 1

    def test_list_reference_vectors_unknown_target(self, gateway):
        refs = gateway.list_reference_vectors("target-zz")
        assert refs == []

    def test_match_reference_with_embedding(self, gateway):
        result = gateway.match_reference(
            "target-a", "audio", [0.91, 0.12, 0.33, 0.44]
        )
        assert isinstance(result, VectorMatchResult)
        assert result.target_id == "target-a"
        assert result.cosine_similarity > 0.9

    def test_match_reference_no_candidates_returns_none(self, gateway):
        # target-zz has no seeded references
        result = gateway.match_reference("target-zz", "audio", [0.5, 0.5, 0.5, 0.5])
        assert result is None


# ── Attempt ingestion ─────────────────────────────────────────────────────────


class TestIngestAttempt:
    def _make_payload(self, success: bool = True) -> AttemptIngestionRequest:
        return AttemptIngestionRequest(
            session_id="session-test-1",
            child_id="child-1",
            target_text="ba",
            transcript="ba",
            pronunciation_score=0.95,
            engagement_score=0.80,
            success_flag=success,
        )

    def test_returns_child_attempt_vector(self, gateway):
        attempt = gateway.ingest_attempt(self._make_payload())
        assert isinstance(attempt, ChildAttemptVector)
        assert attempt.child_id == "child-1"
        assert attempt.session_id == "session-test-1"

    def test_attempt_id_is_unique(self, gateway):
        a1 = gateway.ingest_attempt(self._make_payload())
        a2 = gateway.ingest_attempt(self._make_payload())
        assert a1.attempt_id != a2.attempt_id

    def test_attempt_stored_in_memory(self, gateway):
        from app.data import store
        before = len(store.attempt_vectors.get("child-1", []))
        gateway.ingest_attempt(self._make_payload())
        after = len(store.attempt_vectors.get("child-1", []))
        assert after == before + 1

    def test_success_flag_preserved(self, gateway):
        attempt = gateway.ingest_attempt(self._make_payload(success=False))
        assert attempt.success_flag is False

    def test_embeddings_have_correct_dimension(self, gateway):
        attempt = gateway.ingest_attempt(self._make_payload())
        assert len(attempt.audio_embedding) == 4
        assert len(attempt.lip_embedding) == 4
        assert len(attempt.emotion_embedding) == 4
        assert len(attempt.noise_embedding) == 4

    def test_top_match_populated_for_known_target(self, gateway):
        # target-a through target-g have seeded reference vectors; "ba" won't map
        # directly but target-b does. Use target text "a" to map to target-a.
        payload = AttemptIngestionRequest(
            session_id="s1",
            child_id="child-1",
            target_text="a",
            transcript="a",
            pronunciation_score=0.95,
            engagement_score=0.80,
            success_flag=True,
        )
        attempt = gateway.ingest_attempt(payload)
        # target-a has audio refs seeded
        assert attempt.top_match_reference_id is not None
        assert attempt.cosine_similarity > 0.0

    def test_target_id_resolution_unknown_text(self, gateway):
        payload = AttemptIngestionRequest(
            session_id="s1",
            child_id="child-1",
            target_text="xyz unknown",
            transcript="xyz",
            pronunciation_score=0.3,
            engagement_score=0.5,
            success_flag=False,
        )
        attempt = gateway.ingest_attempt(payload)
        assert attempt.target_id == "target-xyz-unknown"


class TestHttpFilterIntegration:
    def test_filter_http_sends_owner_id_and_api_key(self, monkeypatch):
        monkeypatch.setenv("FILTER_SERVICE_URL", "http://filter-service")
        monkeypatch.setenv("FILTER_SERVICE_API_KEY", "secret-key")

        captured = {}

        class DummyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "filtered_text": "Quiet try. Nice work.",
                    "style_tags": ["calm"],
                    "filter_trace": [{"filter_name": "calming_filter"}],
                    "confidence": 0.92,
                    "architecture": "rules_only",
                }

        class DummyClient:
            def __init__(self, timeout):
                captured["timeout"] = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, json, headers):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return DummyResponse()

        import httpx
        monkeypatch.setattr(httpx, "Client", DummyClient)

        gateway = IntegrationGateway()
        message, trace = gateway.filter_output(
            "child",
            "Great job.",
            owner_id="child-1",
            context="success",
        )

        assert message.text == "Quiet try. Nice work."
        assert trace[0].provider == "speech-filters-service"
        assert captured["url"] == "http://filter-service/filter"
        assert captured["json"]["owner_id"] == "child-1"
        assert "child_id" not in captured["json"]
        assert captured["headers"]["x-service-api-key"] == "secret-key"
