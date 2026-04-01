from __future__ import annotations

import hashlib
import re
from uuid import uuid4

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
from app.providers import OutputFilterExpert
from app.repositories import TherapyRepository, repository


class SpeechIntegrationGateway:
    def __init__(
        self,
        data_repository: TherapyRepository | None = None,
        output_filter: OutputFilterExpert | None = None,
    ) -> None:
        self.repository = data_repository or repository
        self.output_filter = output_filter or OutputFilterExpert()

    def get_child_profile(self, child_id: str) -> CommunicationProfile | None:
        return self.repository.get_child_profile(child_id)

    def get_parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return self.repository.get_parent_profile(caregiver_id)

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        return self.repository.get_environment_profile(child_id)

    def filter_output(
        self,
        audience: str,
        text: str,
        owner_id: str | None = None,
    ) -> tuple[FilteredMessage, list[ExpertDecision]]:
        profile = None
        if audience == "child" and owner_id:
            profile = self.get_child_profile(owner_id)
        if audience == "parent" and owner_id:
            profile = self.get_parent_profile(owner_id)
        filtered, trace = self.output_filter.filter_text(audience, text, profile=profile)
        return filtered, [trace]

    def list_curriculum(self) -> list[TargetCurriculumItem]:
        return self.repository.list_curriculum()

    def list_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        return self.repository.get_reference_vectors(target_id)

    def list_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        return self.repository.get_attempt_vectors(child_id)

    def match_reference(self, target_id: str, modality: str, embedding: list[float]) -> VectorMatchResult | None:
        return self.repository.match_reference(target_id, modality, embedding)

    def check_environment(self, payload: EnvironmentCheckRequest) -> EnvironmentCheckResult:
        return self.repository.check_environment(payload)

    def ingest_attempt(self, payload: AttemptIngestionRequest) -> ChildAttemptVector:
        target_id = self._resolve_target_id(payload.target_text)
        audio_embedding = self._build_embedding(f"audio|{payload.target_text}|{payload.transcript}", payload.pronunciation_score)
        lip_embedding = self._build_embedding(f"lip|{payload.target_text}|{payload.transcript}", payload.pronunciation_score)
        emotion_embedding = self._build_embedding(f"emotion|{payload.target_text}|{payload.transcript}", payload.engagement_score)
        noise_floor = max(0.0, min(1.0, 1.0 - payload.engagement_score))
        noise_embedding = self._build_embedding(f"noise|{payload.target_text}|{payload.transcript}", noise_floor)
        top_match = self.match_reference(target_id, "audio", audio_embedding)
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
        )
        return self.repository.save_attempt_vector(attempt)

    def _resolve_target_id(self, target_text: str) -> str:
        normalized = target_text.strip().lower()
        curriculum = self.list_curriculum()
        exact_match = next((item.target_id for item in curriculum if item.display_text.lower() == normalized), None)
        if exact_match:
            return exact_match
        prefix_match = next((item.target_id for item in curriculum if normalized.startswith(item.display_text.lower())), None)
        if prefix_match:
            return prefix_match
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        return f"target-{slug or 'unknown'}"

    def _build_embedding(self, seed: str, score_hint: float) -> list[float]:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        values: list[float] = []
        for index in range(4):
            start = index * 4
            raw_value = int.from_bytes(digest[start:start + 4], byteorder="big") / 4294967295
            blended = round((raw_value * 0.7) + (score_hint * 0.3), 3)
            values.append(blended)
        return values


integration_gateway = SpeechIntegrationGateway()
