from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import httpx

from app.middleware.auth import ClerkAuthMiddleware
from app.middleware.observability import ObservabilityMiddleware
from app.agentic import orchestrator
from app.data import store
from app.db import persistence
from app.db.client import db
from app.models import (
    Alert,
    AlertAcknowledgeResponse,
    AgentGraph,
    ArchitectureBlueprint,
    AttemptIngestionRequest,
    ChildAnalytics,
    ChildAttemptVector,
    ChildProfile,
    ChildReport,
    ClinicianReviewItem,
    CommunicationProfile,
    DeepgramTranscriptFrameRequest,
    EnterpriseAnalytics,
    EnterpriseUsage,
    EnvironmentCheckRequest,
    EnvironmentCheckResult,
    EnvironmentProfile,
    EscalationRequest,
    FilterPreviewRequest,
    FilterPreviewResponse,
    Goal,
    GoalAssignmentRequest,
    ProviderStatus,
    ReferenceVector,
    SessionCompletionResponse,
    VoicePlaybackEnqueueRequest,
    VoicePlaybackItem,
    VoicePlaybackQueueSnapshot,
    VoicePlaybackStateUpdateRequest,
    SessionDetail,
    SessionStartRequest,
    SessionStartResponse,
    SpeechEvaluation,
    SpeechInputRequest,
    TargetCurriculumItem,
    TtsSynthesisJob,
    TtsSynthesisProcessRequest,
    TtsSynthesisQueueSnapshot,
    TtsSynthesisRequest,
    VectorMatchResult,
    VoiceRuntimeCheckpoint,
    VoiceRuntimeCheckpointRequest,
    VoiceRuntimeEvent,
    VoiceRuntimeEventRequest,
    VoiceRuntimeRequest,
    VoiceRuntimeSession,
    VoiceRuntimeSnapshot,
    VoiceRuntimeTransportConnectRequest,
    VoiceRuntimeTransportConnection,
    VoiceTranscriptIngestionResponse,
    VoiceTranscriptRequest,
    WorkflowQueueSnapshot,
)
from app.runtime import runtime_manager
from app.workflows import workflow_manager

STATIC_DIR = Path(__file__).with_name("static")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Hydrate runtime state from Supabase on startup when configured."""
    if db.enabled():
        for child_id in list(store.children.keys()):
            progress = persistence.load_progress_for_child(child_id)
            if progress:
                store.progress.update(progress)
            sessions = persistence.load_sessions_for_child(child_id)
            for session in sessions:
                store.sessions[session.session_id] = session
            attempts = persistence.load_attempt_vectors_for_child(child_id)
            if attempts:
                store.attempt_vectors[child_id] = attempts
        for alert in persistence.load_alerts():
            store.alerts[alert.alert_id] = alert
        workflow_manager.clinician_reviews = {
            review.review_id: review for review in persistence.load_reviews()
        }
    yield


app = FastAPI(
    title="TalkBuddy AI",
    version="0.8.0",
    description=(
        "Agentic speech therapy platform with Supabase-backed persistence, "
        "profile-aware output filtering, environment-aware sessions, "
        "multimodal attempt ingestion, and analytics."
    ),
    lifespan=lifespan,
)

app.add_middleware(ObservabilityMiddleware)
app.add_middleware(ClerkAuthMiddleware)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def welcome_shell() -> FileResponse:
    return FileResponse(STATIC_DIR / "welcome.html")


@app.get("/session", include_in_schema=False)
def session_shell() -> FileResponse:
    """Child practice session UI — voice-first, tablet/TV optimised."""
    return FileResponse(STATIC_DIR / "session.html")


@app.get("/therapy", include_in_schema=False)
def therapy_shell() -> FileResponse:
    """Parent / therapist monitoring dashboard."""
    return FileResponse(STATIC_DIR / "therapy.html")


@app.get("/console", include_in_schema=False)
def console_shell() -> FileResponse:
    """Developer API console."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    from app.config import settings
    return {
        "status": "ok",
        "version": app.version,
        "env": settings.app_env,
        "live_providers": settings.use_live_provider_calls,
        "openai_configured": settings.configured(settings.openai_api_key),
        "deepgram_configured": settings.configured(settings.deepgram_api_key),
        "livekit_configured": settings.livekit_configured,
        "supabase_enabled": settings.supabase_configured,
        "auth_required": settings.configured(settings.clerk_secret_key),
    }


@app.get("/runtime/voice/tts/speak", include_in_schema=True)
async def tts_speak(
    text: str = Query(..., max_length=1000),
    voice: str = Query("nova"),
    session_id: str | None = Query(None),
) -> StreamingResponse:
    """Stream synthesised speech audio from OpenAI TTS.

    Available when OPENAI_API_KEY and USE_LIVE_PROVIDER_CALLS=true are set.
    Falls back to 503 so the browser can use Web Speech Synthesis instead.
    Supported voices: alloy, echo, fable, onyx, nova, shimmer.
    """
    from app.config import settings

    if not settings.use_live_provider_calls or not settings.configured(settings.openai_api_key):
        raise HTTPException(status_code=503, detail="TTS provider not configured")

    allowed_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    if voice not in allowed_voices:
        voice = "nova"

    async def _stream():
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": "tts-1", "input": text, "voice": voice, "response_format": "mp3"},
            ) as response:
                if response.status_code != 200:
                    return
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    yield chunk

    return StreamingResponse(
        _stream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Session-Id": session_id or ""},
    )


@app.websocket("/runtime/voice/stream")
async def deepgram_voice_stream(
    websocket: WebSocket,
    session_id: str = Query(...),
    child_id: str = Query(...),
) -> None:
    """WebSocket bridge: browser audio → Deepgram streaming STT → transcript frames.

    Browser sends raw PCM audio chunks (16-bit, 16kHz, mono) as binary messages.
    Server relays them to Deepgram and forwards transcript JSON frames back.
    Active when DEEPGRAM_API_KEY and USE_LIVE_PROVIDER_CALLS=true are set.
    Falls back to immediate close with a 4503 code so the client tries Web Speech API.
    """
    from app.config import settings

    if store.sessions.get(session_id) is None or store.children.get(child_id) is None:
        await websocket.close(code=4404, reason="Session or child not found")
        return

    if not settings.use_live_provider_calls or not settings.configured(settings.deepgram_api_key):
        # Signal to browser that Deepgram is unavailable; it falls back to Web Speech API
        await websocket.accept()
        await websocket.close(code=4503, reason="Deepgram not configured")
        return

    await websocket.accept()

    # Browser sends webm/opus via MediaRecorder (native, no transcoding needed).
    # Deepgram auto-detects the container; we hint with encoding=opus for clarity.
    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-2-general"
        "&punctuate=true"
        "&interim_results=true"
        "&endpointing=700"
        "&vad_events=true"
        "&encoding=opus"
        "&container=webm"
        "&channels=1"
    )
    dg_headers = {"Authorization": f"Token {settings.deepgram_api_key}"}

    async with httpx.AsyncClient() as http_client:
        try:
            async with http_client.stream("GET", dg_url, headers=dg_headers) as _dg:
                # httpx doesn't support WebSocket natively; use websockets library
                pass
        except Exception:
            pass

    # Use the websockets library for the Deepgram connection
    try:
        import websockets as _ws_lib  # type: ignore[import]
    except ImportError:
        await websocket.close(code=4503, reason="websockets package not installed")
        return

    try:
        async with _ws_lib.connect(dg_url, extra_headers=dg_headers) as dg_ws:

            async def forward_to_deepgram():
                """Receive browser audio chunks and forward to Deepgram."""
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await dg_ws.send(data)
                except (WebSocketDisconnect, Exception):
                    await dg_ws.close()

            async def relay_transcripts():
                """Receive Deepgram transcript frames and relay to browser."""
                try:
                    async for raw in dg_ws:
                        try:
                            frame = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        channel = frame.get("channel", {})
                        alternatives = channel.get("alternatives", [{}])
                        transcript = (alternatives[0] if alternatives else {}).get("transcript", "")
                        is_final = frame.get("is_final", False)
                        speech_final = frame.get("speech_final", False)
                        confidence = (alternatives[0] if alternatives else {}).get("confidence", 0.0)
                        start_ms = int(frame.get("start", 0) * 1000)
                        duration_ms = int(frame.get("duration", 0) * 1000)

                        if not transcript:
                            continue

                        # Relay to browser as a structured frame matching DeepgramTranscriptFrameRequest
                        browser_frame = {
                            "transcript": transcript,
                            "is_final": is_final,
                            "speech_final": speech_final,
                            "confidence": confidence,
                            "start_ms": start_ms,
                            "duration_ms": duration_ms,
                        }
                        try:
                            await websocket.send_json(browser_frame)
                        except Exception:
                            break

                        # Also ingest into the backend transcript pipeline (fire-and-forget)
                        if is_final or speech_final:
                            asyncio.create_task(
                                _ingest_deepgram_frame(session_id, child_id, browser_frame)
                            )
                except Exception:
                    pass

            await asyncio.gather(forward_to_deepgram(), relay_transcripts())

    except Exception:
        try:
            await websocket.close(code=4500, reason="Deepgram connection failed")
        except Exception:
            pass


async def _ingest_deepgram_frame(session_id: str, child_id: str, frame: dict) -> None:
    """Silently ingest a Deepgram frame through the agentic pipeline for audit logging."""
    from app.models import DeepgramTranscriptFrameRequest
    try:
        payload = DeepgramTranscriptFrameRequest(
            session_id=session_id,
            child_id=child_id,
            transcript=frame["transcript"],
            is_final=frame["is_final"],
            speech_final=frame["speech_final"],
            confidence=frame["confidence"],
            start_ms=frame["start_ms"],
            duration_ms=frame["duration_ms"],
            attention_score=0.8,
        )
        orchestrator.ingest_deepgram_frame(payload)
    except Exception:
        pass


@app.get("/architecture/providers", response_model=ArchitectureBlueprint)
def architecture() -> ArchitectureBlueprint:
    return orchestrator.architecture()


@app.get("/architecture/graph", response_model=AgentGraph)
def architecture_graph() -> AgentGraph:
    return orchestrator.architecture_graph()


@app.get("/providers/status", response_model=list[ProviderStatus])
def provider_status() -> list[ProviderStatus]:
    return orchestrator.provider_statuses()


@app.post("/runtime/voice/session", response_model=VoiceRuntimeSession)
def create_voice_runtime_session(payload: VoiceRuntimeRequest) -> VoiceRuntimeSession:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return runtime_manager.create_session(payload)


@app.post("/runtime/voice/connect", response_model=VoiceRuntimeTransportConnection)
def connect_voice_runtime_transport(payload: VoiceRuntimeTransportConnectRequest) -> VoiceRuntimeTransportConnection:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return runtime_manager.connect_transport(payload)


@app.post("/runtime/voice/checkpoints", response_model=VoiceRuntimeCheckpoint)
def record_voice_runtime_checkpoint(payload: VoiceRuntimeCheckpointRequest) -> VoiceRuntimeCheckpoint:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return runtime_manager.record_checkpoint(payload)


@app.get("/runtime/voice/checkpoints", response_model=VoiceRuntimeSnapshot)
def voice_runtime_snapshot(session_id: str = Query(...)) -> VoiceRuntimeSnapshot:
    if session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return runtime_manager.snapshot(session_id)


@app.post("/runtime/voice/transcript", response_model=VoiceTranscriptIngestionResponse)
def ingest_voice_runtime_transcript(payload: VoiceTranscriptRequest) -> VoiceTranscriptIngestionResponse:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.ingest_runtime_transcript(payload)


@app.post("/runtime/voice/deepgram", response_model=VoiceTranscriptIngestionResponse)
def ingest_deepgram_transcript_frame(payload: DeepgramTranscriptFrameRequest) -> VoiceTranscriptIngestionResponse:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.ingest_deepgram_frame(payload)


@app.post("/runtime/voice/events", response_model=VoiceRuntimeEvent)
def record_voice_runtime_event(payload: VoiceRuntimeEventRequest) -> VoiceRuntimeEvent:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.record_runtime_event(payload)


@app.post("/runtime/voice/playback", response_model=VoicePlaybackItem)
def enqueue_voice_playback(payload: VoicePlaybackEnqueueRequest) -> VoicePlaybackItem:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.enqueue_playback(payload)


@app.post("/runtime/voice/playback/state", response_model=VoicePlaybackItem)
def update_voice_playback_state(payload: VoicePlaybackStateUpdateRequest) -> VoicePlaybackItem:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return orchestrator.update_playback_state(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Playback item not found") from None


@app.get("/runtime/voice/playback", response_model=VoicePlaybackQueueSnapshot)
def get_voice_playback_queue(session_id: str = Query(...)) -> VoicePlaybackQueueSnapshot:
    if session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.playback_queue(session_id)


@app.post("/runtime/voice/tts", response_model=TtsSynthesisJob)
def create_voice_tts_job(payload: TtsSynthesisRequest) -> TtsSynthesisJob:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return orchestrator.create_tts_job(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Playback item not found") from None


@app.post("/runtime/voice/tts/process", response_model=TtsSynthesisJob)
def process_voice_tts_job(payload: TtsSynthesisProcessRequest) -> TtsSynthesisJob:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return orchestrator.process_tts_job(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="TTS job not found") from None


@app.get("/runtime/voice/tts", response_model=TtsSynthesisQueueSnapshot)
def get_voice_tts_queue(session_id: str = Query(...)) -> TtsSynthesisQueueSnapshot:
    if session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.tts_queue(session_id)


@app.post("/filter/preview", response_model=FilterPreviewResponse)
def filter_preview(payload: FilterPreviewRequest) -> FilterPreviewResponse:
    return orchestrator.filter_preview(payload.audience, payload.text, owner_id=payload.owner_id)


@app.get("/profiles/child/{child_id}", response_model=CommunicationProfile)
def child_profile(child_id: str) -> CommunicationProfile:
    if child_id not in store.child_communication_profiles:
        raise HTTPException(status_code=404, detail="Child communication profile not found")
    return orchestrator.get_child_communication_profile(child_id)


@app.get("/profiles/parent/{caregiver_id}", response_model=CommunicationProfile)
def parent_profile(caregiver_id: str) -> CommunicationProfile:
    if caregiver_id not in store.parent_communication_profiles:
        raise HTTPException(status_code=404, detail="Parent communication profile not found")
    return orchestrator.get_parent_communication_profile(caregiver_id)


@app.get("/profiles/environment/{child_id}", response_model=EnvironmentProfile)
def environment_profile(child_id: str) -> EnvironmentProfile:
    if child_id not in store.environment_profiles:
        raise HTTPException(status_code=404, detail="Environment profile not found")
    return orchestrator.get_environment_profile(child_id)


@app.post("/environment/check", response_model=EnvironmentCheckResult)
def check_environment(payload: EnvironmentCheckRequest) -> EnvironmentCheckResult:
    return orchestrator.check_environment(payload)


@app.get("/curriculum", response_model=list[TargetCurriculumItem])
def curriculum() -> list[TargetCurriculumItem]:
    return orchestrator.list_curriculum()


@app.get("/vectors/references", response_model=list[ReferenceVector])
def reference_vectors(target_id: str = Query(...)) -> list[ReferenceVector]:
    return orchestrator.list_reference_vectors(target_id)


@app.get("/vectors/attempts", response_model=list[ChildAttemptVector])
def attempt_vectors(child_id: str = Query(...)) -> list[ChildAttemptVector]:
    return orchestrator.list_attempt_vectors(child_id)


@app.post("/vectors/attempts", response_model=ChildAttemptVector)
def ingest_attempt_vector(payload: AttemptIngestionRequest) -> ChildAttemptVector:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.ingest_attempt(payload)


@app.get("/vectors/match", response_model=VectorMatchResult | None)
def match_reference(target_id: str = Query(...), modality: str = Query(...), embedding: str = Query(...)) -> VectorMatchResult | None:
    values = [float(part.strip()) for part in embedding.split(",") if part.strip()]
    return orchestrator.match_reference(target_id, modality, values)


@app.get("/children", response_model=list[ChildProfile])
def get_children() -> list[ChildProfile]:
    return list(store.children.values())


@app.post("/session/start", response_model=SessionStartResponse)
def create_session(payload: SessionStartRequest) -> SessionStartResponse:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    return orchestrator.start_session(payload)


@app.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    if session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.session_detail(session_id)


@app.post("/sessions/{session_id}/complete", response_model=SessionCompletionResponse)
def complete_session(session_id: str) -> SessionCompletionResponse:
    if session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.complete_session(session_id)


@app.post("/speech/input", response_model=SpeechEvaluation)
def evaluate_speech(payload: SpeechInputRequest) -> SpeechEvaluation:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.process_turn(payload.session_id, payload.transcript, payload.attention_score)


@app.get("/progress", response_model=ChildReport)
def get_progress(child_id: str = Query(...)) -> ChildReport:
    if child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    return orchestrator.build_child_report(child_id)


@app.get("/caregiver/alerts", response_model=list[Alert])
def caregiver_alerts(caregiver_id: str = Query(...)) -> list[Alert]:
    return orchestrator.caregiver_alerts(caregiver_id)


@app.post("/caregiver/alerts/{alert_id}/acknowledge", response_model=AlertAcknowledgeResponse)
def acknowledge_alert(alert_id: str) -> AlertAcknowledgeResponse:
    if alert_id not in store.alerts:
        raise HTTPException(status_code=404, detail="Alert not found")
    return orchestrator.acknowledge_alert(alert_id)


@app.get("/clinician/queue", response_model=list[ClinicianReviewItem])
def clinician_queue(clinician_id: str = Query(...)) -> list[ClinicianReviewItem]:
    if clinician_id not in store.clinicians:
        raise HTTPException(status_code=404, detail="Clinician not found")
    return orchestrator.clinician_queue(clinician_id)


@app.get("/workflows/queues", response_model=WorkflowQueueSnapshot)
def workflow_queues() -> WorkflowQueueSnapshot:
    return orchestrator.workflows_snapshot()


@app.post("/alerts/escalate", response_model=Alert)
def escalate(payload: EscalationRequest) -> Alert:
    if payload.session_id not in store.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return orchestrator.manual_escalation(payload)


@app.post("/goals/assign", response_model=Goal)
def assign_child_goal(payload: GoalAssignmentRequest) -> Goal:
    if payload.child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    return orchestrator.assign_goal(payload)


@app.get("/reports/child/{child_id}", response_model=ChildReport)
def child_report(child_id: str) -> ChildReport:
    if child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    return orchestrator.build_child_report(child_id)


@app.get("/enterprise/usage", response_model=EnterpriseUsage)
def get_enterprise_usage() -> EnterpriseUsage:
    return orchestrator.enterprise_usage()


@app.get("/analytics/child/{child_id}", response_model=ChildAnalytics)
def child_analytics(child_id: str) -> ChildAnalytics:
    if child_id not in store.children:
        raise HTTPException(status_code=404, detail="Child not found")
    return orchestrator.child_analytics(child_id)


@app.get("/analytics/enterprise", response_model=EnterpriseAnalytics)
def enterprise_analytics() -> EnterpriseAnalytics:
    return orchestrator.enterprise_analytics()
