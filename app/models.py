from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.clock import utc_now


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
    created_at: datetime = Field(default_factory=utc_now)


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
    max_retries: int = 4
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


class VoiceRuntimeCheckpointRequest(BaseModel):
    session_id: str
    checkpoint_kind: Literal[
        "turn_started",
        "turn_ended",
        "first_transcript",
        "first_token",
        "first_audio_byte",
        "playback_started",
    ]
    elapsed_ms: int = Field(ge=0)
    detail: str | None = None


class VoiceRuntimeCheckpoint(BaseModel):
    session_id: str
    checkpoint_kind: str
    elapsed_ms: int
    created_at: datetime
    detail: str | None = None


class VoiceRuntimeSnapshot(BaseModel):
    session_id: str
    checkpoints: list[VoiceRuntimeCheckpoint]
    latest_by_kind: dict[str, VoiceRuntimeCheckpoint]


class VoiceTranscriptRequest(BaseModel):
    session_id: str
    transcript: str
    is_final: bool = False
    elapsed_ms: int = Field(ge=0, default=0)
    attention_score: float = Field(ge=0.0, le=1.0, default=0.8)
    source: Literal["stt_stream", "fallback_form", "gemini_live", "browser_backup"] = "stt_stream"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class VoiceTranscriptRecord(BaseModel):
    session_id: str
    transcript: str
    is_final: bool
    elapsed_ms: int
    attention_score: float
    source: str
    confidence: float | None = None
    created_at: datetime


class VoiceTranscriptIngestionResponse(BaseModel):
    session_id: str
    accepted: bool = True
    transcript_record: VoiceTranscriptRecord
    evaluation: SpeechEvaluation | None = None


class DeepgramTranscriptFrameRequest(BaseModel):
    session_id: str
    child_id: str
    channel_index: int = 0
    transcript: str
    is_final: bool = False
    speech_final: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    start_ms: int = Field(ge=0, default=0)
    duration_ms: int = Field(ge=0, default=0)
    attention_score: float = Field(ge=0.0, le=1.0, default=0.8)
    provider: Literal["deepgram"] = "deepgram"
    model: str = "flux-general-en"


class VoiceRuntimeEventRequest(BaseModel):
    session_id: str
    event_kind: Literal[
        "barge_in",
        "playback_interrupted",
        "client_joined",
        "client_left",
        "vad_started",
        "vad_stopped",
    ]
    elapsed_ms: int = Field(ge=0, default=0)
    detail: str | None = None


class VoiceRuntimeEvent(BaseModel):
    session_id: str
    event_kind: str
    elapsed_ms: int
    created_at: datetime
    detail: str | None = None


class VoicePlaybackEnqueueRequest(BaseModel):
    session_id: str
    child_id: str
    text: str
    voice_name: str = "calm-coach"
    audience: OutputAudience = "child"
    source: Literal["session_feedback", "manual_preview", "runtime_replay"] = "session_feedback"


class VoicePlaybackStateUpdateRequest(BaseModel):
    session_id: str
    playback_id: str
    status: Literal["pending", "synthesizing", "ready", "playing", "interrupted", "played"]
    detail: str | None = None
    elapsed_ms: int = Field(ge=0, default=0)


class VoicePlaybackItem(BaseModel):
    playback_id: str
    session_id: str
    child_id: str
    text: str
    voice_name: str
    audience: OutputAudience
    source: str
    status: Literal["pending", "synthesizing", "ready", "playing", "interrupted", "played"]
    created_at: datetime
    updated_at: datetime
    detail: str | None = None


class VoicePlaybackQueueSnapshot(BaseModel):
    session_id: str
    items: list[VoicePlaybackItem]
    active_item: VoicePlaybackItem | None = None


class TtsSynthesisRequest(BaseModel):
    session_id: str
    playback_id: str
    voice_name: str = "calm-coach"
    provider: Literal["dedicated_streaming_tts"] = "dedicated_streaming_tts"
    output_format: Literal["pcm_s16le", "mp3"] = "pcm_s16le"
    sample_rate_hz: int = 24000


class TtsSynthesisArtifact(BaseModel):
    artifact_uri: str
    mime_type: str
    duration_ms: int
    size_bytes: int


class TtsSynthesisProcessRequest(BaseModel):
    session_id: str
    playback_id: str


class TtsSynthesisJob(BaseModel):
    session_id: str
    playback_id: str
    provider: str
    voice_name: str
    text: str
    output_format: str
    sample_rate_hz: int
    delivery_mode: Literal["local_mock", "streaming_tts"]
    status: Literal["queued", "synthesizing", "ready"]
    synthesis_key: str
    artifact: TtsSynthesisArtifact | None = None
    notes: list[str] = Field(default_factory=list)


class TtsSynthesisQueueSnapshot(BaseModel):
    session_id: str
    jobs: list[TtsSynthesisJob]
    latest_ready_job: TtsSynthesisJob | None = None


class VoiceRuntimeRequest(BaseModel):
    session_id: str
    child_id: str
    audio_enabled: bool = True


class VoiceRuntimeLane(BaseModel):
    lane_id: str
    lane_role: Literal["stt", "tts", "transcript", "events"]
    provider: str
    delivery_mode: Literal["local_only", "https_poll", "https_stream", "webrtc_data"]
    codec: str | None = None
    path: str | None = None
    notes: list[str] = Field(default_factory=list)


class VoiceRuntimeDataChannel(BaseModel):
    label: str
    direction: Literal["publish", "subscribe", "bidirectional"]
    purpose: str


class VoiceRuntimeClientConfig(BaseModel):
    transport_kind: Literal["local_mock", "livekit_webrtc"]
    turn_protocol: Literal["manual_turn", "server_vad_stream"]
    transcript_mode: Literal["fallback_form", "streaming_partial"]
    playback_mode: Literal["manual_ready", "streaming_tts"]
    event_endpoint: str
    health_endpoint: str
    join_endpoint: str
    reconnect_strategy: Literal["manual", "token_refresh"]
    data_channels: list[VoiceRuntimeDataChannel] = Field(default_factory=list)
    input_sample_rate_hz: int = 16000
    output_sample_rate_hz: int = 24000
    frame_duration_ms: int = 20
    stt_lane: VoiceRuntimeLane
    tts_lane: VoiceRuntimeLane
    transcript_lane: VoiceRuntimeLane
    event_lane: VoiceRuntimeLane


class VoiceRuntimeTransportConnectRequest(BaseModel):
    session_id: str
    child_id: str
    requested_transport: Literal["local_mock", "livekit_webrtc"] | None = None


class VoiceRuntimeTransportConnection(BaseModel):
    session_id: str
    child_id: str
    connection_state: Literal["mock_connected", "ready_to_join", "blocked"]
    transport_kind: Literal["local_mock", "livekit_webrtc"]
    join_url: str
    room_name: str
    participant_identity: str
    access_token: str | None = None
    token_status: Literal["mock", "ready", "missing_config"]
    data_channels: list[VoiceRuntimeDataChannel] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class VoiceRuntimeSession(BaseModel):
    session_id: str
    child_id: str
    runtime_mode: Literal["mock", "live"]
    transport_provider: str
    room_name: str
    participant_identity: str
    participant_name: str
    transport_url: str
    access_token: str | None = None
    token_status: Literal["mock", "ready", "missing_config"]
    expires_at: datetime | None = None
    speech_to_text_provider: str
    tts_provider: str
    conductor_provider: str
    transcript_fallback_enabled: bool = True
    barge_in_enabled: bool = True
    client_config: VoiceRuntimeClientConfig
    notes: list[str] = Field(default_factory=list)


class ChildCreateRequest(BaseModel):
    name: str
    age: int = 4


class SessionStartRequest(BaseModel):
    child_id: str
    environment: EnvironmentCheckRequest | None = None


class RealtimeReadiness(BaseModel):
    provider: str
    ready: bool
    mode: Literal["gemini_live", "openai_realtime", "browser_backup", "offline"]
    status: str
    detail: str | None = None


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
    realtime_readiness: RealtimeReadiness | None = None


class SpeechInputRequest(BaseModel):
    session_id: str
    transcript: str
    attention_score: float = Field(ge=0.0, le=1.0, default=0.8)


class AttemptIngestionRequest(BaseModel):
    session_id: str
    child_id: str
    target_text: str
    transcript: str
    pronunciation_score: float = Field(ge=0.0, le=1.0)
    engagement_score: float = Field(ge=0.0, le=1.0)
    success_flag: bool


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


class ChildAnalytics(BaseModel):
    child_id: str
    child_name: str
    total_sessions: int
    completed_sessions: int
    escalated_sessions: int
    total_attempts: int
    successful_attempts: int
    overall_mastery: float
    targets_practiced: int
    targets_mastered: int
    streak_days: int
    top_targets: list[ProgressSnapshot]
    recent_trend: Literal["improving", "stable", "needs_support"]


class EnterpriseAnalytics(BaseModel):
    total_children: int
    total_sessions: int
    completed_sessions: int
    escalated_sessions: int
    average_mastery: float
    total_alerts: int
    unacknowledged_alerts: int
    total_reviews: int
    children_needing_support: int
