from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Role = Literal["child", "caregiver", "clinician", "admin"]
EscalationReason = Literal["low_confidence", "low_engagement", "repeated_failure", "manual"]
ReviewPriority = Literal["low", "medium", "high"]
ReviewStatus = Literal["queued", "in_review", "completed"]
OutputAudience = Literal["child", "parent"]
TargetType = Literal["letter", "number", "word"]
VectorModality = Literal["audio", "noise", "lip", "emotion"]


class Goal(BaseModel):
    goal_id: str
    target_text: str
    difficulty: int = Field(ge=1, le=5, default=1)
    cue: str
    active: bool = True


class OutputPolicy(BaseModel):
    policy_id: str
    calmness_level: int = Field(ge=1, le=5, default=5)
    verbosity_limit: int = Field(ge=20, le=240, default=100)
    encouragement_level: int = Field(ge=1, le=5, default=3)
    avoid_overstimulation: bool = True
    avoid_exclamations: bool = True
    avoid_chatter: bool = True


class CommunicationProfile(BaseModel):
    profile_id: str
    audience: OutputAudience
    owner_id: str
    preferred_tone: str
    preferred_pacing: str
    sensory_notes: list[str] = Field(default_factory=list)
    banned_styles: list[str] = Field(default_factory=list)
    preferred_phrases: list[str] = Field(default_factory=list)
    policy: OutputPolicy


class EnvironmentProfile(BaseModel):
    environment_profile_id: str
    child_id: str
    room_label: str
    baseline_room_embedding: list[float] = Field(default_factory=list)
    baseline_visual_clutter_score: float = Field(ge=0.0, le=1.0)
    baseline_noise_score: float = Field(ge=0.0, le=1.0)
    baseline_lighting_score: float = Field(ge=0.0, le=1.0)
    baseline_distraction_notes: list[str] = Field(default_factory=list)
    recommended_adjustments: list[str] = Field(default_factory=list)
    preferred_objects: list[str] = Field(default_factory=list)
    avoid_objects: list[str] = Field(default_factory=list)


class EnvironmentCheckRequest(BaseModel):
    child_id: str
    room_embedding: list[float] = Field(default_factory=list)
    visual_clutter_score: float = Field(ge=0.0, le=1.0)
    noise_score: float = Field(ge=0.0, le=1.0)
    lighting_score: float = Field(ge=0.0, le=1.0)
    observed_objects: list[str] = Field(default_factory=list)


class EnvironmentCheckResult(BaseModel):
    child_id: str
    matches_standard: bool
    similarity_score: float
    alerts: list[str]
    recommended_adjustments: list[str]


class TargetCurriculumItem(BaseModel):
    target_id: str
    target_type: TargetType
    display_text: str
    phoneme_group: str
    month_index: int = 1
    difficulty_level: int = Field(ge=1, le=5, default=1)


class ReferenceVector(BaseModel):
    reference_id: str
    target_id: str
    modality: VectorModality
    source_label: str
    quality_score: float = Field(ge=0.0, le=1.0)
    age_band: str
    notes: str = ""
    embedding: list[float] = Field(default_factory=list)


class ChildAttemptVector(BaseModel):
    attempt_id: str
    child_id: str
    target_id: str
    session_id: str
    audio_embedding: list[float] = Field(default_factory=list)
    lip_embedding: list[float] = Field(default_factory=list)
    emotion_embedding: list[float] = Field(default_factory=list)
    noise_embedding: list[float] = Field(default_factory=list)
    top_match_reference_id: str | None = None
    cosine_similarity: float = 0.0
    success_flag: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class VectorMatchResult(BaseModel):
    target_id: str
    modality: VectorModality
    reference_id: str
    source_label: str
    cosine_similarity: float
    notes: str


class ChildProfile(BaseModel):
    child_id: str
    name: str
    age: int
    caregiver_id: str
    clinician_id: str
    goals: list[Goal]
    streak_days: int = 0
    engagement_baseline: float = 0.75


class CaregiverProfile(BaseModel):
    caregiver_id: str
    name: str
    child_ids: list[str]


class ClinicianProfile(BaseModel):
    clinician_id: str
    name: str
    child_ids: list[str]


class SessionEvent(BaseModel):
    timestamp: datetime
    kind: str
    detail: str


class SessionState(BaseModel):
    session_id: str
    child_id: str
    started_at: datetime
    status: Literal["active", "completed", "escalated"] = "active"
    current_goal_id: str
    current_target: str
    retries_used: int = 0
    max_retries: int = 2
    reward_points: int = 0
    events: list[SessionEvent] = Field(default_factory=list)


class Alert(BaseModel):
    alert_id: str
    session_id: str
    child_id: str
    caregiver_id: str
    reason: EscalationReason
    message: str
    created_at: datetime
    acknowledged: bool = False


class ProgressSnapshot(BaseModel):
    child_id: str
    target_text: str
    attempts: int = 0
    successes: int = 0
    mastery_score: float = 0.0
    last_practiced_at: datetime | None = None


class ExpertDecision(BaseModel):
    expert: str
    provider: str
    confidence: float
    summary: str


class FilteredMessage(BaseModel):
    audience: OutputAudience
    text: str
    style_tags: list[str]


class ProviderComponent(BaseModel):
    component: str
    recommended_service: str
    role: str
    source_url: str
    notes: str


class ProviderStatus(BaseModel):
    provider: str
    purpose: str
    configured: bool
    environment_key: str
    mode: Literal["mock", "live"]
    notes: str


class AgentNode(BaseModel):
    agent_id: str
    title: str
    responsibility: str
    provider: str


class AgentEdge(BaseModel):
    from_agent: str
    to_agent: str
    condition: str


class AgentGraph(BaseModel):
    nodes: list[AgentNode]
    edges: list[AgentEdge]


class ArchitectureBlueprint(BaseModel):
    product_name: str
    approach: str
    components: list[ProviderComponent]
    implementation_notes: list[str]


class SessionStartRequest(BaseModel):
    child_id: str
    environment: EnvironmentCheckRequest | None = None


class SessionStartResponse(BaseModel):
    session_id: str
    child_id: str
    target_text: str
    cue: str
    message: str
    assigned_agents: list[str]
    environment_ok: bool = True
    environment_note: str | None = None
    parent_message: str | None = None


class SpeechInputRequest(BaseModel):
    session_id: str
    transcript: str
    attention_score: float = Field(ge=0.0, le=1.0, default=0.8)


class SpeechEvaluation(BaseModel):
    recognized_text: str
    expected_text: str
    pronunciation_score: float
    confidence_score: float
    engagement_score: float
    action: Literal["advance", "retry", "escalate"]
    feedback: str
    parent_message: str | None = None
    next_target: str | None = None
    caregiver_alert_id: str | None = None
    expert_trace: list[ExpertDecision]


class GoalAssignmentRequest(BaseModel):
    child_id: str
    target_text: str
    cue: str
    difficulty: int = Field(ge=1, le=5, default=1)


class EscalationRequest(BaseModel):
    session_id: str
    reason: EscalationReason
    message: str


class FilterPreviewRequest(BaseModel):
    audience: OutputAudience
    text: str
    owner_id: str | None = None


class FilterPreviewResponse(BaseModel):
    message: FilteredMessage
    expert_trace: list[ExpertDecision]


class ChildReport(BaseModel):
    child: ChildProfile
    progress: list[ProgressSnapshot]
    active_alerts: list[Alert]
    recent_sessions: list[SessionState]


class SessionDetail(BaseModel):
    session: SessionState
    child: ChildProfile
    active_alerts: list[Alert]
    recommended_actions: list[str]


class ClinicianReviewItem(BaseModel):
    review_id: str
    clinician_id: str
    child_id: str
    session_id: str
    priority: ReviewPriority
    status: ReviewStatus = "queued"
    summary: str
    created_at: datetime


class WorkflowQueueSnapshot(BaseModel):
    pending_alerts: list[Alert]
    clinician_reviews: list[ClinicianReviewItem]


class AlertAcknowledgeResponse(BaseModel):
    alert_id: str
    acknowledged: bool
    follow_up_review_id: str | None = None


class SessionCompletionResponse(BaseModel):
    session_id: str
    status: str
    reward_points: int
    total_events: int


class EnterpriseUsage(BaseModel):
    total_children: int
    total_caregivers: int
    total_clinicians: int
    active_sessions: int
    total_alerts: int
    average_mastery: float
