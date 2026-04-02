from __future__ import annotations

from app.clock import utc_now

from app.db import persistence
from app.models import ChildAttemptVector


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.last_upsert_payload = None
        self.last_insert_payload = None
        self.last_update_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def upsert(self, payload, **_kwargs):
        self.last_upsert_payload = payload
        return self

    def insert(self, payload, **_kwargs):
        self.last_insert_payload = payload
        return self

    def update(self, payload, **_kwargs):
        self.last_update_payload = payload
        return self

    def execute(self):
        return FakeResult(self.rows)


class FakeClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return self.tables[name]


def test_upsert_attempt_vector_includes_target_uuid(monkeypatch):
    attempt_table = FakeTable()
    client = FakeClient({"child_attempt_vectors": attempt_table})
    monkeypatch.setattr(persistence, "_client", lambda: client)
    monkeypatch.setattr(persistence, "_child_uuid", lambda _client, _child_id: "child-uuid")
    monkeypatch.setattr(persistence, "_target_uuid", lambda _client, _target_id: "target-uuid")

    attempt = ChildAttemptVector(
        attempt_id="attempt-1",
        child_id="child-1",
        target_id="target-b",
        session_id="session-1",
        audio_embedding=[0.1, 0.2, 0.3, 0.4],
        success_flag=True,
        created_at=utc_now(),
    )

    persistence.upsert_attempt_vector(attempt)

    assert attempt_table.last_upsert_payload is not None
    assert attempt_table.last_upsert_payload["child_id"] == "child-uuid"
    assert attempt_table.last_upsert_payload["target_id"] == "target-uuid"


def test_load_alerts_resolves_external_child_and_session_ids(monkeypatch):
    client = FakeClient(
        {
            "alerts": FakeTable(
                [
                    {
                        "external_alert_id": "alert-1",
                        "session_id": "session-uuid",
                        "child_id": "child-uuid",
                        "caregiver_external_id": "caregiver-1",
                        "reason": "manual",
                        "message": "Please help.",
                        "acknowledged": False,
                        "created_at": utc_now().isoformat(),
                    }
                ]
            )
        }
    )
    monkeypatch.setattr(persistence, "_client", lambda: client)
    monkeypatch.setattr(persistence, "_session_external_id", lambda _client, _uuid: "session-1")
    monkeypatch.setattr(persistence, "_child_external_id", lambda _client, _uuid: "child-1")

    alerts = persistence.load_alerts()

    assert len(alerts) == 1
    assert alerts[0].session_id == "session-1"
    assert alerts[0].child_id == "child-1"


def test_load_reviews_resolves_external_child_and_session_ids(monkeypatch):
    client = FakeClient(
        {
            "clinician_reviews": FakeTable(
                [
                    {
                        "external_review_id": "review-1",
                        "session_id": "session-uuid",
                        "child_id": "child-uuid",
                        "clinician_external_id": "slp-1",
                        "priority": "high",
                        "status": "queued",
                        "summary": "Needs review.",
                        "created_at": utc_now().isoformat(),
                    }
                ]
            )
        }
    )
    monkeypatch.setattr(persistence, "_client", lambda: client)
    monkeypatch.setattr(persistence, "_session_external_id", lambda _client, _uuid: "session-1")
    monkeypatch.setattr(persistence, "_child_external_id", lambda _client, _uuid: "child-1")

    reviews = persistence.load_reviews()

    assert len(reviews) == 1
    assert reviews[0].session_id == "session-1"
    assert reviews[0].child_id == "child-1"


def test_load_attempt_vectors_resolves_external_target_id(monkeypatch):
    client = FakeClient(
        {
            "child_attempt_vectors": FakeTable(
                [
                    {
                        "external_attempt_id": "attempt-1",
                        "target_id": "target-uuid",
                        "external_session_id": "session-1",
                        "audio_embedding": [0.1, 0.2, 0.3, 0.4],
                        "lip_embedding": [0.1, 0.2, 0.3, 0.4],
                        "emotion_embedding": [0.1, 0.2, 0.3, 0.4],
                        "noise_embedding": [0.1, 0.2, 0.3, 0.4],
                        "top_match_reference_external_id": "target-b-audio-1",
                        "cosine_similarity": 0.91,
                        "success_flag": True,
                        "created_at": utc_now().isoformat(),
                    }
                ]
            )
        }
    )
    monkeypatch.setattr(persistence, "_client", lambda: client)
    monkeypatch.setattr(persistence, "_child_uuid", lambda _client, _child_id: "child-uuid")
    monkeypatch.setattr(persistence, "_target_external_id", lambda _client, _uuid: "target-b")

    attempts = persistence.load_attempt_vectors_for_child("child-1")

    assert len(attempts) == 1
    assert attempts[0].child_id == "child-1"
    assert attempts[0].target_id == "target-b"
