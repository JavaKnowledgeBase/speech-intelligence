from __future__ import annotations

from app.data import store
from app.models import (
    ChildAttemptVector,
    CommunicationProfile,
    EnvironmentCheckRequest,
    EnvironmentCheckResult,
    EnvironmentProfile,
    ReferenceVector,
    TargetCurriculumItem,
    VectorMatchResult,
)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return round(dot / (mag_a * mag_b), 3)


class TherapyRepository:
    def list_curriculum(self) -> list[TargetCurriculumItem]:
        return list(store.curriculum.values())

    def get_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        return store.reference_vectors.get(target_id, [])

    def get_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        return store.attempt_vectors.get(child_id, [])

    def get_child_profile(self, child_id: str) -> CommunicationProfile | None:
        return store.child_communication_profiles.get(child_id)

    def get_parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return store.parent_communication_profiles.get(caregiver_id)

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        return store.environment_profiles.get(child_id)

    def match_reference(self, target_id: str, modality: str, embedding: list[float]) -> VectorMatchResult | None:
        candidates = [ref for ref in self.get_reference_vectors(target_id) if ref.modality == modality]
        scored = [
            (ref, _cosine_similarity(embedding, ref.embedding))
            for ref in candidates
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        if not scored:
            return None
        ref, score = scored[0]
        return VectorMatchResult(
            target_id=target_id,
            modality=modality,
            reference_id=ref.reference_id,
            source_label=ref.source_label,
            cosine_similarity=score,
            notes=ref.notes,
        )

    def check_environment(self, payload: EnvironmentCheckRequest) -> EnvironmentCheckResult:
        profile = self.get_environment_profile(payload.child_id)
        if profile is None:
            return EnvironmentCheckResult(
                child_id=payload.child_id,
                matches_standard=False,
                similarity_score=0.0,
                alerts=["No saved environment standard found yet."],
                recommended_adjustments=["Ask parent for a 360 degree room photo to establish a baseline."],
            )

        similarity = _cosine_similarity(payload.room_embedding, profile.baseline_room_embedding)
        alerts: list[str] = []
        adjustments: list[str] = []

        if payload.visual_clutter_score > profile.baseline_visual_clutter_score + 0.15:
            alerts.append("Visual clutter appears higher than the child's usual learning standard.")
            adjustments.append("Remove extra visible toys or colorful distractions around the seat.")
        if payload.noise_score > profile.baseline_noise_score + 0.15:
            alerts.append("Background noise appears higher than the saved standard.")
            adjustments.append("Reduce TV, device sounds, or nearby conversation before starting.")
        if payload.lighting_score < profile.baseline_lighting_score - 0.15:
            alerts.append("Lighting appears dimmer than the preferred baseline.")
            adjustments.append("Increase soft room lighting so lips and face are easy to see.")
        for obj in payload.observed_objects:
            if obj.lower() in {item.lower() for item in profile.avoid_objects}:
                alerts.append(f"Detected potentially distracting object: {obj}.")
                adjustments.append(f"Move or hide {obj} before the session.")

        matches = similarity >= 0.9 and not alerts
        if matches:
            adjustments.append("Environment matches the child's usual comfort standard.")

        return EnvironmentCheckResult(
            child_id=payload.child_id,
            matches_standard=matches,
            similarity_score=similarity,
            alerts=alerts,
            recommended_adjustments=adjustments or profile.recommended_adjustments,
        )


repository = TherapyRepository()
