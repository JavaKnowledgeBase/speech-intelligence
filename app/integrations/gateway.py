from __future__ import annotations

"""
IntegrationGateway — central integration layer for speech-intelligence.

All calls from the orchestrator to output filtering, vector retrieval, and
attempt ingestion go through this gateway. This keeps the orchestrator code
free of direct service/store access and makes each integration swappable.

Two modes per capability:
  - HTTP mode  (env var set):   calls the running speech-filters FastAPI service
  - Local mode (fallback):      runs the equivalent logic in-process
"""

import hashlib
import os
import re
from uuid import uuid4

from app.clock import utc_now
from app.data import store
from app.models import (
    AttemptIngestionRequest,
    ChildAttemptVector,
    CommunicationProfile,
    EnvironmentCheckRequest,
    EnvironmentCheckResult,
    EnvironmentProfile,
    ExpertDecision,
    FilteredMessage,
    ReferenceVector,
    TargetCurriculumItem,
    VectorMatchResult,
)
from app.repositories import repository


class IntegrationGateway:
    """
    Routes requests to the output filter service, vector retrieval layer, and
    Supabase-backed or in-memory persistence.

    Config (all optional — defaults to local in-process mode):
        FILTER_SERVICE_URL         Base URL of the running speech-filters service
                                   e.g. http://localhost:8001
        FILTER_SERVICE_TIMEOUT     HTTP request timeout in seconds (default 3)
    """

    def __init__(self) -> None:
        self._filter_url = os.getenv("FILTER_SERVICE_URL", "").rstrip("/")
        self._filter_timeout = int(os.getenv("FILTER_SERVICE_TIMEOUT", "3"))
        self._filter_api_key = os.getenv("FILTER_SERVICE_API_KEY", "")

    # ── Profile access ────────────────────────────────────────────────────────

    def get_child_profile(self, child_id: str) -> CommunicationProfile | None:
        return store.child_communication_profiles.get(child_id)

    def get_parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return store.parent_communication_profiles.get(caregiver_id)

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        return store.environment_profiles.get(child_id)

    # ── Output filtering ──────────────────────────────────────────────────────

    def filter_output(
        self,
        audience: str,
        text: str,
        *,
        owner_id: str | None = None,
        context: str = "general",
        engagement_score: float = 0.75,
        retries_used: int = 0,
        frustration_flag: bool = False,
    ) -> tuple[FilteredMessage, list[ExpertDecision]]:
        """
        Filter a message and return (FilteredMessage, [ExpertDecision]).

        Calls the speech-filters HTTP service when FILTER_SERVICE_URL is set.
        Falls back to the local OutputFilterExpert pipeline on any failure or
        when no URL is configured.
        """
        if self._filter_url:
            result = self._filter_http(
                audience=audience,
                text=text,
                owner_id=owner_id,
                context=context,
                engagement_score=engagement_score,
                retries_used=retries_used,
                frustration_flag=frustration_flag,
            )
            if result is not None:
                return result
        return self._filter_local(audience, text, owner_id=owner_id)

    def _filter_http(
        self,
        audience: str,
        text: str,
        *,
        owner_id: str | None,
        context: str,
        engagement_score: float,
        retries_used: int,
        frustration_flag: bool,
    ) -> tuple[FilteredMessage, list[ExpertDecision]] | None:
        try:
            import httpx
        except ImportError:
            return None

        payload: dict = {
            "audience": audience,
            "text": text,
            "context": context,
            "child_state": {
                "engagement_score": engagement_score,
                "retries_used": retries_used,
                "frustration_flag": frustration_flag,
                "last_action": "none",
            },
        }
        if owner_id:
            payload["owner_id"] = owner_id

        headers = {}
        if self._filter_api_key:
            headers["x-service-api-key"] = self._filter_api_key

        try:
            with httpx.Client(timeout=self._filter_timeout) as client:
                resp = client.post(f"{self._filter_url}/filter", json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            message = FilteredMessage(
                audience=audience,
                text=data["filtered_text"],
                style_tags=data.get("style_tags", []),
            )
            step_count = len(data.get("filter_trace", []))
            trace = [
                ExpertDecision(
                    expert="output_filter_expert",
                    provider="speech-filters-service",
                    confidence=float(data.get("confidence", 0.90)),
                    summary=(
                        f"Filtered via speech-filters service "
                        f"({data.get('architecture', 'rules_only')}): "
                        f"{step_count} steps applied."
                    ),
                )
            ]
            return message, trace
        except Exception:  # noqa: BLE001 — network/parsing failure, fall through to local
            return None

    def _filter_local(
        self,
        audience: str,
        text: str,
        *,
        owner_id: str | None = None,
    ) -> tuple[FilteredMessage, list[ExpertDecision]]:
        from app.providers import OutputFilterExpert

        expert = OutputFilterExpert()
        profile: CommunicationProfile | None = None
        if owner_id:
            if audience == "child":
                profile = self.get_child_profile(owner_id)
            else:
                profile = self.get_parent_profile(owner_id)

        filtered, decision = expert.filter_text(audience, text, profile=profile)
        return filtered, [decision]

    # ── Environment checks ────────────────────────────────────────────────────

    def check_environment(self, payload: EnvironmentCheckRequest) -> EnvironmentCheckResult:
        return repository.check_environment(payload)

    # ── Curriculum and vector access ──────────────────────────────────────────

    def list_curriculum(self) -> list[TargetCurriculumItem]:
        return repository.list_curriculum()

    def list_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        return repository.get_reference_vectors(target_id)

    def list_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        return repository.get_attempt_vectors(child_id)

    def match_reference(
        self, target_id: str, modality: str, embedding: list[float]
    ) -> VectorMatchResult | None:
        return repository.match_reference(target_id, modality, embedding)

    # ── Attempt ingestion ─────────────────────────────────────────────────────

    def ingest_attempt(self, payload: AttemptIngestionRequest) -> ChildAttemptVector:
        """
        Record a child speech attempt, find the nearest audio reference, and
        persist the result.

        A stub audio embedding is derived from the pronunciation score until
        real multimodal embeddings are wired. The stub has the same dimension
        as the seeded reference vectors (4 floats) so cosine similarity is
        immediately meaningful.
        """
        target_id = self._target_id_for(payload.target_text)

        audio_embedding = self._build_embedding(
            f"audio|{payload.target_text}|{payload.transcript}", payload.pronunciation_score
        )
        lip_embedding = self._build_embedding(
            f"lip|{payload.target_text}|{payload.transcript}", payload.pronunciation_score
        )
        emotion_embedding = self._build_embedding(
            f"emotion|{payload.target_text}|{payload.transcript}", payload.engagement_score
        )
        noise_floor = max(0.0, min(1.0, 1.0 - payload.engagement_score))
        noise_embedding = self._build_embedding(
            f"noise|{payload.target_text}|{payload.transcript}", noise_floor
        )

        top_match = repository.match_reference(
            target_id=target_id,
            modality="audio",
            embedding=audio_embedding,
        )

        attempt = ChildAttemptVector(
            attempt_id=f"attempt-{uuid4().hex[:10]}",
            child_id=payload.child_id,
            target_id=target_id,
            session_id=payload.session_id,
            audio_embedding=audio_embedding,
            lip_embedding=lip_embedding,
            emotion_embedding=emotion_embedding,
            noise_embedding=noise_embedding,
            top_match_reference_id=top_match.reference_id if top_match else None,
            cosine_similarity=top_match.cosine_similarity if top_match else 0.0,
            success_flag=payload.success_flag,
            created_at=utc_now(),
        )
        repository.save_attempt_vector(attempt)
        return attempt

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _target_id_for(target_text: str) -> str:
        """Resolve target_id from display text; return a synthetic ID if not found."""
        normalized = target_text.strip().lower()
        curriculum = list(store.curriculum.values())
        # Exact match first
        for item in curriculum:
            if item.display_text.lower() == normalized:
                return item.target_id
        # Prefix match (e.g. "ba" starts with curriculum item "b")
        for item in curriculum:
            if normalized.startswith(item.display_text.lower()):
                return item.target_id
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        return f"target-{slug or 'unknown'}"

    @staticmethod
    def _build_embedding(seed: str, score_hint: float) -> list[float]:
        """
        Build a 4-dim stub embedding from a seed string and a score hint.

        Uses SHA-256 so embeddings are deterministic per (target, transcript) pair
        rather than purely positional. Score hint biases the values toward the
        actual pronunciation / engagement quality so cosine similarity is
        meaningful against the seeded reference vectors.
        """
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        values: list[float] = []
        for i in range(4):
            start = i * 4
            raw = int.from_bytes(digest[start : start + 4], byteorder="big") / 4_294_967_295
            values.append(round((raw * 0.7) + (score_hint * 0.3), 4))
        return values


integration_gateway = IntegrationGateway()
