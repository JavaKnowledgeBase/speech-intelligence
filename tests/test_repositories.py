from __future__ import annotations

"""Tests for TherapyRepository: curriculum, vectors, environment checks."""

import pytest

from app.clock import utc_now
from app.models import EnvironmentCheckRequest
from app.repositories import TherapyRepository


@pytest.fixture
def repo() -> TherapyRepository:
    return TherapyRepository()


# ── Curriculum ────────────────────────────────────────────────────────────────


class TestCurriculum:
    def test_list_curriculum_returns_items(self, repo):
        items = repo.list_curriculum()
        assert len(items) >= 20  # letters a-n + digits 0-9

    def test_curriculum_has_target_ids(self, repo):
        items = repo.list_curriculum()
        assert all(i.target_id for i in items)

    def test_curriculum_includes_letters_and_numbers(self, repo):
        types = {i.target_type for i in repo.list_curriculum()}
        assert "letter" in types
        assert "number" in types


# ── Reference vectors ─────────────────────────────────────────────────────────


class TestReferenceVectors:
    def test_get_reference_vectors_known_target(self, repo):
        refs = repo.get_reference_vectors("target-a")
        assert len(refs) >= 1

    def test_get_reference_vectors_unknown_target(self, repo):
        refs = repo.get_reference_vectors("target-zz")
        assert refs == []

    def test_each_reference_has_embedding(self, repo):
        refs = repo.get_reference_vectors("target-a")
        assert all(len(r.embedding) > 0 for r in refs)

    def test_match_reference_exact_embedding(self, repo):
        # target-a audio ref embedding=[0.91, 0.12, 0.33, 0.44]
        result = repo.match_reference("target-a", "audio", [0.91, 0.12, 0.33, 0.44])
        assert result is not None
        assert result.cosine_similarity >= 0.99

    def test_match_reference_wrong_modality(self, repo):
        # target-a has "audio" but not a non-existent "thermal" modality
        result = repo.match_reference("target-a", "thermal", [0.5, 0.5, 0.5, 0.5])
        assert result is None

    def test_match_reference_wrong_target(self, repo):
        result = repo.match_reference("target-zzz", "audio", [0.5, 0.5, 0.5, 0.5])
        assert result is None

    def test_match_reference_best_score_first(self, repo):
        # Near-perfect match should score higher than random
        perfect = repo.match_reference("target-a", "audio", [0.91, 0.12, 0.33, 0.44])
        weak = repo.match_reference("target-a", "audio", [0.0, 0.0, 0.0, 1.0])
        assert perfect.cosine_similarity >= weak.cosine_similarity


# ── Attempt vectors ───────────────────────────────────────────────────────────


class TestAttemptVectors:
    def test_get_attempt_vectors_returns_seeded(self, repo):
        attempts = repo.get_attempt_vectors("child-1")
        assert len(attempts) >= 1

    def test_get_attempt_vectors_unknown_child(self, repo):
        attempts = repo.get_attempt_vectors("ghost-child")
        assert attempts == []

    def test_save_attempt_vector_stores(self, repo):
        from app.data import store
        from app.models import ChildAttemptVector
        
        attempt = ChildAttemptVector(
            attempt_id="test-attempt-save",
            child_id="child-2",
            target_id="target-b",
            session_id="s-test",
            audio_embedding=[0.5, 0.5, 0.5, 0.5],
            success_flag=True,
            created_at=utc_now(),
        )
        repo.save_attempt_vector(attempt)
        saved = repo.get_attempt_vectors("child-2")
        assert any(a.attempt_id == "test-attempt-save" for a in saved)


# ── Environment checks ────────────────────────────────────────────────────────


class TestEnvironmentCheck:
    def test_no_profile_returns_not_matching(self, repo):
        payload = EnvironmentCheckRequest(
            child_id="no-such-child",
            room_embedding=[0.5, 0.3, 0.6, 0.2],
            visual_clutter_score=0.3,
            noise_score=0.2,
            lighting_score=0.7,
        )
        result = repo.check_environment(payload)
        assert result.matches_standard is False
        assert "No saved environment standard" in result.alerts[0]

    def test_matching_environment_passes(self, repo):
        payload = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.2,
            lighting_score=0.72,
        )
        result = repo.check_environment(payload)
        assert result.matches_standard is True

    def test_dim_lighting_triggers_alert(self, repo):
        payload = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.2,
            lighting_score=0.30,  # well below baseline 0.72
        )
        result = repo.check_environment(payload)
        assert result.matches_standard is False
        assert any("lighting" in a.lower() for a in result.alerts)

    def test_distracting_object_triggers_alert(self, repo):
        payload = EnvironmentCheckRequest(
            child_id="child-1",
            room_embedding=[0.55, 0.33, 0.61, 0.29],
            visual_clutter_score=0.28,
            noise_score=0.2,
            lighting_score=0.72,
            observed_objects=["tv"],  # tv is in avoid_objects for child-1
        )
        result = repo.check_environment(payload)
        assert result.matches_standard is False
        assert any("tv" in a.lower() for a in result.alerts)
