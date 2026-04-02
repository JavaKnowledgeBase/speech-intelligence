from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.data import store
from app.db import persistence
from app.models import (
    VoiceRuntimeCheckpoint,
    VoiceRuntimeCheckpointRequest,
    VoiceRuntimeClientConfig,
    VoiceRuntimeDataChannel,
    VoiceRuntimeLane,
    VoiceRuntimeRequest,
    VoiceRuntimeSession,
    VoiceRuntimeSnapshot,
    VoiceRuntimeTransportConnectRequest,
    VoiceRuntimeTransportConnection,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_encode(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url(signature)}"


class BaseTransportProvider:
    provider_name = "transport"

    def _data_channels(self, *, runtime_mode: str) -> list[VoiceRuntimeDataChannel]:
        if runtime_mode == "live":
            return [
                VoiceRuntimeDataChannel(label="tb-transcript", direction="publish", purpose="Partial and final transcript frames"),
                VoiceRuntimeDataChannel(label="tb-events", direction="bidirectional", purpose="Barge-in, VAD, and transport state events"),
                VoiceRuntimeDataChannel(label="tb-tts", direction="subscribe", purpose="Future playback control and synthesis acknowledgements"),
            ]
        return [
            VoiceRuntimeDataChannel(label="tb-local-events", direction="bidirectional", purpose="Mock harness runtime event coordination"),
        ]

    def _build_lanes(self, *, runtime_mode: str) -> dict[str, VoiceRuntimeLane]:
        if runtime_mode == "live":
            return {
                "stt_lane": VoiceRuntimeLane(
                    lane_id="stt-primary",
                    lane_role="stt",
                    provider="Deepgram Flux",
                    delivery_mode="webrtc_data",
                    codec="pcm_s16le",
                    path="livekit://audio/input",
                    notes=["Primary streaming speech input lane for child turns."],
                ),
                "tts_lane": VoiceRuntimeLane(
                    lane_id="tts-primary",
                    lane_role="tts",
                    provider="Dedicated streaming TTS",
                    delivery_mode="webrtc_data",
                    codec="pcm_s16le",
                    path="livekit://audio/output",
                    notes=["Child-facing playback should stay filter-approved before synthesis."],
                ),
                "transcript_lane": VoiceRuntimeLane(
                    lane_id="transcript-events",
                    lane_role="transcript",
                    provider="OpenAI Responses API",
                    delivery_mode="https_stream",
                    path="/runtime/voice/transcript",
                    notes=["Partial and final transcripts will be mirrored for auditability."],
                ),
                "event_lane": VoiceRuntimeLane(
                    lane_id="runtime-events",
                    lane_role="events",
                    provider="FastAPI Voice Runtime",
                    delivery_mode="https_stream",
                    path="/runtime/voice/events",
                    notes=["Barge-in and runtime coordination events feed observability dashboards."],
                ),
            }
        return {
            "stt_lane": VoiceRuntimeLane(
                lane_id="stt-fallback",
                lane_role="stt",
                provider="Transcript fallback form",
                delivery_mode="local_only",
                codec="text/plain",
                path="/runtime/voice/transcript",
                notes=["Manual transcript entry stands in for streaming speech capture during dev."],
            ),
            "tts_lane": VoiceRuntimeLane(
                lane_id="tts-placeholder",
                lane_role="tts",
                provider="Speaker-ready placeholder",
                delivery_mode="local_only",
                path=None,
                notes=["UI placeholder keeps the playback lane visible before TTS wiring lands."],
            ),
            "transcript_lane": VoiceRuntimeLane(
                lane_id="transcript-local",
                lane_role="transcript",
                provider="FastAPI session loop",
                delivery_mode="https_poll",
                path="/runtime/voice/transcript",
                notes=["Recognized text is returned inline with session feedback today."],
            ),
            "event_lane": VoiceRuntimeLane(
                lane_id="runtime-events",
                lane_role="events",
                provider="FastAPI Voice Runtime",
                delivery_mode="https_poll",
                path="/runtime/voice/events",
                notes=["Runtime event telemetry is available before realtime transport is enabled."],
            ),
        }

    def build_client_config(self, *, runtime_mode: str) -> VoiceRuntimeClientConfig:
        lanes = self._build_lanes(runtime_mode=runtime_mode)
        return VoiceRuntimeClientConfig(
            transport_kind="local_mock",
            turn_protocol="manual_turn" if runtime_mode == "mock" else "server_vad_stream",
            transcript_mode="fallback_form" if runtime_mode == "mock" else "streaming_partial",
            playback_mode="manual_ready" if runtime_mode == "mock" else "streaming_tts",
            event_endpoint="/runtime/voice/events",
            health_endpoint="/health",
            join_endpoint="/runtime/voice/connect",
            reconnect_strategy="manual" if runtime_mode == "mock" else "token_refresh",
            data_channels=self._data_channels(runtime_mode=runtime_mode),
            stt_lane=lanes["stt_lane"],
            tts_lane=lanes["tts_lane"],
            transcript_lane=lanes["transcript_lane"],
            event_lane=lanes["event_lane"],
        )


class MockTransportProvider(BaseTransportProvider):
    provider_name = "Mock Voice Harness"


class LiveKitTransportProvider(BaseTransportProvider):
    provider_name = "LiveKit"

    def build_client_config(self, *, runtime_mode: str) -> VoiceRuntimeClientConfig:
        config = super().build_client_config(runtime_mode=runtime_mode)
        config.transport_kind = "livekit_webrtc"
        config.turn_protocol = "server_vad_stream"
        config.transcript_mode = "streaming_partial"
        config.playback_mode = "streaming_tts"
        return config


class VoiceRuntimeManager:
    def _room_name(self, child_id: str, session_id: str) -> str:
        return f"{settings.livekit_room_prefix}-{child_id}-{session_id}"

    def _participant_identity(self, child_id: str) -> str:
        return f"{child_id}-voice-client"

    def _transport_url(self) -> str:
        return settings.livekit_url or "wss://livekit-not-configured.invalid"

    def create_session(self, payload: VoiceRuntimeRequest) -> VoiceRuntimeSession:
        child = store.children[payload.child_id]
        room_name = self._room_name(payload.child_id, payload.session_id)
        participant_identity = self._participant_identity(payload.child_id)
        transport_url = self._transport_url()
        notes = [
            "Transcript fallback stays enabled until the realtime transport is fully wired.",
            "All child-facing output should still pass through the output filter before TTS playback.",
        ]

        if settings.use_live_provider_calls and settings.livekit_configured:
            provider = LiveKitTransportProvider()
            issued_at = datetime.now(UTC)
            expires_at = issued_at + timedelta(seconds=settings.livekit_token_ttl_seconds)
            token = _jwt_encode(
                {
                    "iss": settings.livekit_api_key,
                    "sub": participant_identity,
                    "nbf": int(issued_at.timestamp()),
                    "exp": int(expires_at.timestamp()),
                    "name": child.name,
                    "video": {
                        "roomJoin": True,
                        "room": room_name,
                        "canPublish": True,
                        "canSubscribe": True,
                        "canPublishData": True,
                    },
                },
                settings.livekit_api_secret,
            )
            notes.append("LiveKit transport is configured for signed token handoff.")
            return VoiceRuntimeSession(
                session_id=payload.session_id,
                child_id=payload.child_id,
                runtime_mode="live",
                transport_provider=provider.provider_name,
                room_name=room_name,
                participant_identity=participant_identity,
                participant_name=child.name,
                transport_url=transport_url,
                access_token=token,
                token_status="ready",
                expires_at=expires_at,
                speech_to_text_provider="Deepgram Flux",
                tts_provider="Dedicated streaming TTS",
                conductor_provider="OpenAI Responses API",
                transcript_fallback_enabled=True,
                barge_in_enabled=True,
                client_config=provider.build_client_config(runtime_mode="live"),
                notes=notes,
            )

        provider = MockTransportProvider()
        if not settings.livekit_configured:
            notes.append("LiveKit credentials are incomplete, so the runtime remains in mock transport mode.")
        elif not settings.use_live_provider_calls:
            notes.append("USE_LIVE_PROVIDER_CALLS is false, so the runtime remains in mock transport mode.")

        return VoiceRuntimeSession(
            session_id=payload.session_id,
            child_id=payload.child_id,
            runtime_mode="mock",
            transport_provider=provider.provider_name,
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=child.name,
            transport_url=transport_url,
            access_token=None,
            token_status="mock",
            expires_at=None,
            speech_to_text_provider="Deepgram Flux",
            tts_provider="Dedicated streaming TTS",
            conductor_provider="OpenAI Responses API",
            transcript_fallback_enabled=True,
            barge_in_enabled=True,
            client_config=provider.build_client_config(runtime_mode="mock"),
            notes=notes,
        )


    def connect_transport(self, payload: VoiceRuntimeTransportConnectRequest) -> VoiceRuntimeTransportConnection:
        runtime_session = self.create_session(
            VoiceRuntimeRequest(
                session_id=payload.session_id,
                child_id=payload.child_id,
                audio_enabled=True,
            )
        )
        requested_transport = payload.requested_transport or runtime_session.client_config.transport_kind
        requested_transport = requested_transport if requested_transport in {"local_mock", "livekit_webrtc"} else runtime_session.client_config.transport_kind
        notes = list(runtime_session.notes)
        connection_state = "mock_connected"
        join_url = runtime_session.transport_url

        if requested_transport == "livekit_webrtc":
            if runtime_session.token_status == "ready":
                connection_state = "ready_to_join"
                notes.append("Client can now call LiveKit connect with the issued token and room details.")
            else:
                connection_state = "blocked"
                notes.append("Live transport was requested but credentials are incomplete, so join remains blocked.")
        else:
            join_url = "mock://voice-harness"
            notes.append("Mock transport stays local and does not require a realtime room join.")

        connection = VoiceRuntimeTransportConnection(
            session_id=payload.session_id,
            child_id=payload.child_id,
            connection_state=connection_state,
            transport_kind=requested_transport,
            join_url=join_url,
            room_name=runtime_session.room_name,
            participant_identity=runtime_session.participant_identity,
            access_token=runtime_session.access_token if connection_state == "ready_to_join" else None,
            token_status=runtime_session.token_status,
            data_channels=runtime_session.client_config.data_channels,
            notes=notes,
        )
        store.voice_runtime_connections[payload.session_id] = connection
        return connection

    def record_checkpoint(self, payload: VoiceRuntimeCheckpointRequest) -> VoiceRuntimeCheckpoint:
        checkpoint = VoiceRuntimeCheckpoint(
            session_id=payload.session_id,
            checkpoint_kind=payload.checkpoint_kind,
            elapsed_ms=payload.elapsed_ms,
            created_at=datetime.now(UTC),
            detail=payload.detail,
        )
        store.voice_runtime_checkpoints.setdefault(payload.session_id, []).append(checkpoint)
        persistence.append_voice_checkpoint(payload.session_id, checkpoint)
        return checkpoint

    def snapshot(self, session_id: str) -> VoiceRuntimeSnapshot:
        checkpoints = list(store.voice_runtime_checkpoints.get(session_id, []))
        latest_by_kind: dict[str, VoiceRuntimeCheckpoint] = {}
        for checkpoint in checkpoints:
            latest_by_kind[checkpoint.checkpoint_kind] = checkpoint
        return VoiceRuntimeSnapshot(
            session_id=session_id,
            checkpoints=checkpoints,
            latest_by_kind=latest_by_kind,
        )


runtime_manager = VoiceRuntimeManager()
