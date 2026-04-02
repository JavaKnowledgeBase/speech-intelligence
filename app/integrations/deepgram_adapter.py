from __future__ import annotations

from app.models import DeepgramTranscriptFrameRequest, VoiceTranscriptRequest


class DeepgramTranscriptAdapter:
    provider_name = "Deepgram Flux"

    def to_voice_transcript(self, payload: DeepgramTranscriptFrameRequest) -> VoiceTranscriptRequest:
        transcript = " ".join(payload.transcript.strip().split())
        elapsed_ms = max(0, payload.start_ms + payload.duration_ms)
        is_final = payload.is_final or payload.speech_final
        return VoiceTranscriptRequest(
            session_id=payload.session_id,
            transcript=transcript,
            is_final=is_final,
            elapsed_ms=elapsed_ms,
            attention_score=payload.attention_score,
            source="stt_stream",
            confidence=payload.confidence,
        )


deepgram_transcript_adapter = DeepgramTranscriptAdapter()
