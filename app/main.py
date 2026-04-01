from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from app.agentic import orchestrator
from app.data import store
from app.models import (
    Alert,
    AlertAcknowledgeResponse,
    AgentGraph,
    ArchitectureBlueprint,
    ChildAttemptVector,
    ChildProfile,
    ChildReport,
    ClinicianReviewItem,
    CommunicationProfile,
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
    SessionDetail,
    SessionStartRequest,
    SessionStartResponse,
    SpeechEvaluation,
    SpeechInputRequest,
    TargetCurriculumItem,
    VectorMatchResult,
    WorkflowQueueSnapshot,
)


app = FastAPI(
    title="TalkBuddy AI MVP",
    version="0.7.0",
    description="Agentic speech therapy MVP with profile-aware output filtering, environment-aware session start, workflow queues, and curriculum/vector scaffolding.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/architecture/providers", response_model=ArchitectureBlueprint)
def architecture() -> ArchitectureBlueprint:
    return orchestrator.architecture()


@app.get("/architecture/graph", response_model=AgentGraph)
def architecture_graph() -> AgentGraph:
    return orchestrator.architecture_graph()


@app.get("/providers/status", response_model=list[ProviderStatus])
def provider_status() -> list[ProviderStatus]:
    return orchestrator.provider_statuses()


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
