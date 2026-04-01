from __future__ import annotations

"""Legacy compatibility shim.

This module keeps the older function-based API stable while delegating all real
behavior to the orchestrator and integration gateway.
"""

from app.agentic import orchestrator
from app.models import (
    Alert,
    ChildProfile,
    ChildReport,
    EnterpriseUsage,
    EscalationRequest,
    Goal,
    GoalAssignmentRequest,
    SessionStartRequest,
    SessionStartResponse,
    SpeechEvaluation,
)


def choose_next_goal(child: ChildProfile) -> Goal:
    goal, _ = orchestrator.choose_next_goal(child)
    return goal


def start_session(child_id: str) -> SessionStartResponse:
    return orchestrator.start_session(SessionStartRequest(child_id=child_id))


def process_speech_input(session_id: str, transcript: str, attention_score: float) -> SpeechEvaluation:
    return orchestrator.process_turn(session_id, transcript, attention_score)


def assign_goal(payload: GoalAssignmentRequest) -> Goal:
    return orchestrator.assign_goal(payload)


def manual_escalation(payload: EscalationRequest) -> Alert:
    return orchestrator.manual_escalation(payload)


def build_child_report(child_id: str) -> ChildReport:
    return orchestrator.build_child_report(child_id)


def enterprise_usage() -> EnterpriseUsage:
    return orchestrator.enterprise_usage()
