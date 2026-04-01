from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings
from app.data import store
from app.models import (
    ChildAttemptVector,
    CommunicationProfile,
    EnvironmentCheckRequest,
    EnvironmentCheckResult,
    EnvironmentProfile,
    OutputPolicy,
    ReferenceVector,
    TargetCurriculumItem,
    VectorMatchResult,
)


logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return round(dot / (mag_a * mag_b), 3)


class RepositoryError(RuntimeError):
    pass


class InMemoryTherapyRepository:
    mode = "memory"

    def list_curriculum(self) -> list[TargetCurriculumItem]:
        return list(store.curriculum.values())

    def get_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        return store.reference_vectors.get(target_id, [])

    def get_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        return store.attempt_vectors.get(child_id, [])

    def save_attempt_vector(self, attempt: ChildAttemptVector) -> ChildAttemptVector:
        store.attempt_vectors.setdefault(attempt.child_id, []).append(attempt)
        return attempt

    def get_child_profile(self, child_id: str) -> CommunicationProfile | None:
        return store.child_communication_profiles.get(child_id)

    def get_parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return store.parent_communication_profiles.get(caregiver_id)

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        return store.environment_profiles.get(child_id)

    def match_reference(self, target_id: str, modality: str, embedding: list[float]) -> VectorMatchResult | None:
        candidates = [ref for ref in self.get_reference_vectors(target_id) if ref.modality == modality]
        scored = [(ref, _cosine_similarity(embedding, ref.embedding)) for ref in candidates]
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


class SupabaseRestClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/") + "/rest/v1"
        self.api_key = api_key

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}/{path}{query}"
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RepositoryError(f"Supabase request failed with HTTP {exc.code}: {details or exc.reason}") from exc
        except URLError as exc:
            raise RepositoryError(f"Supabase request failed: {exc.reason}") from exc
        if not payload:
            return []
        parsed = json.loads(payload)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        raise RepositoryError("Supabase returned an unexpected payload shape")


class SupabaseTherapyRepository:
    mode = "supabase"

    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def list_curriculum(self) -> list[TargetCurriculumItem]:
        rows = self.client.request(
            "GET",
            "curriculum_targets",
            params={
                "select": "external_target_id,target_type,display_text,phoneme_group,month_index,difficulty_level",
                "order": "month_index.asc,display_text.asc",
            },
        )
        return [
            TargetCurriculumItem(
                target_id=row["external_target_id"],
                target_type=row["target_type"],
                display_text=row["display_text"],
                phoneme_group=row["phoneme_group"],
                month_index=int(row["month_index"]),
                difficulty_level=int(row["difficulty_level"]),
            )
            for row in rows
        ]

    def get_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        target_row = self._lookup_row("curriculum_targets", "external_target_id", target_id)
        if target_row is None:
            return []
        rows = self.client.request(
            "GET",
            "reference_vectors",
            params={
                "select": "external_reference_id,modality,source_label,quality_score,age_band,notes,embedding",
                "target_id": f"eq.{target_row['id']}",
                "order": "external_reference_id.asc",
            },
        )
        return [self._reference_from_row(target_id, row) for row in rows]

    def get_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        child_row = self._lookup_row("children", "external_child_id", child_id)
        if child_row is None:
            return []
        rows = self.client.request(
            "GET",
            "child_attempt_vectors",
            params={
                "select": "external_attempt_id,external_session_id,audio_embedding,lip_embedding,emotion_embedding,noise_embedding,top_match_reference_external_id,cosine_similarity,success_flag,created_at,target_id",
                "child_id": f"eq.{child_row['id']}",
                "order": "created_at.asc",
            },
        )
        target_names = self._target_external_ids({row.get("target_id") for row in rows if row.get("target_id")})
        attempts: list[ChildAttemptVector] = []
        for row in rows:
            attempts.append(
                ChildAttemptVector(
                    attempt_id=row["external_attempt_id"],
                    child_id=child_id,
                    target_id=target_names.get(row.get("target_id"), "unknown-target"),
                    session_id=row["external_session_id"],
                    audio_embedding=self._vector(row.get("audio_embedding")),
                    lip_embedding=self._vector(row.get("lip_embedding")),
                    emotion_embedding=self._vector(row.get("emotion_embedding")),
                    noise_embedding=self._vector(row.get("noise_embedding")),
                    top_match_reference_id=row.get("top_match_reference_external_id"),
                    cosine_similarity=float(row.get("cosine_similarity") or 0.0),
                    success_flag=bool(row.get("success_flag")),
                    created_at=row.get("created_at"),
                )
            )
        return attempts

    def save_attempt_vector(self, attempt: ChildAttemptVector) -> ChildAttemptVector:
        child_row = self._lookup_row("children", "external_child_id", attempt.child_id)
        target_row = self._lookup_row("curriculum_targets", "external_target_id", attempt.target_id)
        if child_row is None or target_row is None:
            raise RepositoryError("Cannot persist attempt because child or target is missing in Supabase")
        self.client.request(
            "POST",
            "child_attempt_vectors",
            body={
                "external_attempt_id": attempt.attempt_id,
                "child_id": child_row["id"],
                "target_id": target_row["id"],
                "external_session_id": attempt.session_id,
                "audio_embedding": attempt.audio_embedding,
                "lip_embedding": attempt.lip_embedding,
                "emotion_embedding": attempt.emotion_embedding,
                "noise_embedding": attempt.noise_embedding,
                "top_match_reference_external_id": attempt.top_match_reference_id,
                "cosine_similarity": attempt.cosine_similarity,
                "success_flag": attempt.success_flag,
            },
            prefer="return=minimal",
        )
        return attempt

    def get_child_profile(self, child_id: str) -> CommunicationProfile | None:
        return self._communication_profile("child", child_id)

    def get_parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return self._communication_profile("parent", caregiver_id)

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        child_row = self._lookup_row("children", "external_child_id", child_id)
        if child_row is None:
            return None
        rows = self.client.request(
            "GET",
            "environment_profiles",
            params={
                "select": "external_environment_profile_id,room_label,baseline_room_embedding,baseline_visual_clutter_score,baseline_noise_score,baseline_lighting_score,baseline_distraction_notes,recommended_adjustments,preferred_objects,avoid_objects",
                "child_id": f"eq.{child_row['id']}",
                "limit": 1,
            },
        )
        if not rows:
            return None
        row = rows[0]
        return EnvironmentProfile(
            environment_profile_id=row["external_environment_profile_id"],
            child_id=child_id,
            room_label=row["room_label"],
            baseline_room_embedding=self._vector(row.get("baseline_room_embedding")),
            baseline_visual_clutter_score=float(row.get("baseline_visual_clutter_score") or 0.0),
            baseline_noise_score=float(row.get("baseline_noise_score") or 0.0),
            baseline_lighting_score=float(row.get("baseline_lighting_score") or 0.0),
            baseline_distraction_notes=list(row.get("baseline_distraction_notes") or []),
            recommended_adjustments=list(row.get("recommended_adjustments") or []),
            preferred_objects=list(row.get("preferred_objects") or []),
            avoid_objects=list(row.get("avoid_objects") or []),
        )

    def match_reference(self, target_id: str, modality: str, embedding: list[float]) -> VectorMatchResult | None:
        candidates = [ref for ref in self.get_reference_vectors(target_id) if ref.modality == modality]
        scored = [(ref, _cosine_similarity(embedding, ref.embedding)) for ref in candidates]
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
        return InMemoryTherapyRepository().check_environment(payload) if self.get_environment_profile(payload.child_id) is None else InMemoryTherapyRepository().check_environment(payload)

    def _communication_profile(self, audience: str, owner_id: str) -> CommunicationProfile | None:
        rows = self.client.request(
            "GET",
            "communication_profiles",
            params={
                "select": "external_profile_id,preferred_tone,preferred_pacing,sensory_notes,banned_styles,preferred_phrases,calmness_level,verbosity_limit,encouragement_level,avoid_overstimulation,avoid_exclamations,avoid_chatter",
                "audience": f"eq.{audience}",
                "owner_external_id": f"eq.{owner_id}",
                "limit": 1,
            },
        )
        if not rows:
            return None
        row = rows[0]
        return CommunicationProfile(
            profile_id=row["external_profile_id"],
            audience=audience,
            owner_id=owner_id,
            preferred_tone=row["preferred_tone"],
            preferred_pacing=row["preferred_pacing"],
            sensory_notes=list(row.get("sensory_notes") or []),
            banned_styles=list(row.get("banned_styles") or []),
            preferred_phrases=list(row.get("preferred_phrases") or []),
            policy=OutputPolicy(
                policy_id=f"policy-{row['external_profile_id']}",
                calmness_level=int(row.get("calmness_level") or 5),
                verbosity_limit=int(row.get("verbosity_limit") or 100),
                encouragement_level=int(row.get("encouragement_level") or 3),
                avoid_overstimulation=bool(row.get("avoid_overstimulation", True)),
                avoid_exclamations=bool(row.get("avoid_exclamations", True)),
                avoid_chatter=bool(row.get("avoid_chatter", True)),
            ),
        )

    def _lookup_row(self, table: str, field: str, value: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            table,
            params={
                "select": "id",
                field: f"eq.{value}",
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    def _target_external_ids(self, target_ids: set[str]) -> dict[str, str]:
        if not target_ids:
            return {}
        rows = self.client.request(
            "GET",
            "curriculum_targets",
            params={
                "select": "id,external_target_id",
                "id": f"in.({','.join(sorted(target_ids))})",
            },
        )
        return {row["id"]: row["external_target_id"] for row in rows}

    def _reference_from_row(self, target_id: str, row: dict[str, Any]) -> ReferenceVector:
        return ReferenceVector(
            reference_id=row["external_reference_id"],
            target_id=target_id,
            modality=row["modality"],
            source_label=row["source_label"],
            quality_score=float(row.get("quality_score") or 0.0),
            age_band=row["age_band"],
            notes=row.get("notes") or "",
            embedding=self._vector(row.get("embedding")),
        )

    def _vector(self, value: Any) -> list[float]:
        if value is None:
            return []
        if isinstance(value, list):
            return [float(item) for item in value]
        if isinstance(value, str):
            stripped = value.strip().strip("[]")
            if not stripped:
                return []
            return [float(part.strip()) for part in stripped.split(",") if part.strip()]
        return []


class TherapyRepository:
    def __init__(self) -> None:
        self.memory = InMemoryTherapyRepository()
        self.remote = SupabaseTherapyRepository(SupabaseRestClient(settings.supabase_url, settings.supabase_service_role_key)) if settings.supabase_configured else None

    @property
    def mode(self) -> str:
        configured_mode = settings.supabase_repository_mode.lower().strip()
        if configured_mode == "memory" or self.remote is None:
            return "memory"
        if configured_mode == "supabase":
            return "supabase"
        return "supabase_with_fallback"

    def list_curriculum(self) -> list[TargetCurriculumItem]:
        return self._call("list_curriculum")

    def get_reference_vectors(self, target_id: str) -> list[ReferenceVector]:
        return self._call("get_reference_vectors", target_id)

    def get_attempt_vectors(self, child_id: str) -> list[ChildAttemptVector]:
        return self._call("get_attempt_vectors", child_id)

    def save_attempt_vector(self, attempt: ChildAttemptVector) -> ChildAttemptVector:
        return self._call("save_attempt_vector", attempt)

    def get_child_profile(self, child_id: str) -> CommunicationProfile | None:
        return self._call("get_child_profile", child_id)

    def get_parent_profile(self, caregiver_id: str) -> CommunicationProfile | None:
        return self._call("get_parent_profile", caregiver_id)

    def get_environment_profile(self, child_id: str) -> EnvironmentProfile | None:
        return self._call("get_environment_profile", child_id)

    def match_reference(self, target_id: str, modality: str, embedding: list[float]) -> VectorMatchResult | None:
        return self._call("match_reference", target_id, modality, embedding)

    def check_environment(self, payload: EnvironmentCheckRequest) -> EnvironmentCheckResult:
        profile = self.get_environment_profile(payload.child_id)
        if profile is None:
            return self.memory.check_environment(payload)

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

    def _call(self, method_name: str, *args: Any) -> Any:
        configured_mode = settings.supabase_repository_mode.lower().strip()
        if configured_mode == "memory" or self.remote is None:
            return getattr(self.memory, method_name)(*args)
        try:
            return getattr(self.remote, method_name)(*args)
        except RepositoryError as exc:
            logger.warning("Supabase repository call failed for %s: %s", method_name, exc)
            return getattr(self.memory, method_name)(*args)


repository = TherapyRepository()
