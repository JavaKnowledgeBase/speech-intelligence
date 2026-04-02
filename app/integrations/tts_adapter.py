from __future__ import annotations

import hashlib

from app.models import TtsSynthesisArtifact, TtsSynthesisJob, TtsSynthesisRequest, VoicePlaybackItem


class TtsPlaybackAdapter:
    provider_name = "Dedicated streaming TTS"

    def _build_artifact(self, job: TtsSynthesisJob) -> TtsSynthesisArtifact:
        digest = hashlib.sha256(job.synthesis_key.encode("utf-8")).hexdigest()[:16]
        words = max(1, len(job.text.split()))
        duration_ms = words * 340
        size_bytes = max(1024, words * 4800)
        mime_type = "audio/L16" if job.output_format == "pcm_s16le" else "audio/mpeg"
        return TtsSynthesisArtifact(
            artifact_uri=f"mock://tts/{digest}.{job.output_format}",
            mime_type=mime_type,
            duration_ms=duration_ms,
            size_bytes=size_bytes,
        )

    def to_synthesis_job(self, payload: TtsSynthesisRequest, playback_item: VoicePlaybackItem) -> TtsSynthesisJob:
        delivery_mode = "streaming_tts" if payload.output_format == "pcm_s16le" else "local_mock"
        synthesis_key = f"{payload.session_id}:{payload.playback_id}:{payload.voice_name}"
        return TtsSynthesisJob(
            session_id=payload.session_id,
            playback_id=payload.playback_id,
            provider=payload.provider,
            voice_name=payload.voice_name,
            text=playback_item.text,
            output_format=payload.output_format,
            sample_rate_hz=payload.sample_rate_hz,
            delivery_mode=delivery_mode,
            status="queued",
            synthesis_key=synthesis_key,
            notes=[
                "Playback text was normalized through the queue before synthesis.",
                "Child-facing audio should stay filter-approved before provider handoff.",
            ],
        )

    def finalize_job(self, job: TtsSynthesisJob) -> TtsSynthesisJob:
        job.status = "ready"
        job.artifact = self._build_artifact(job)
        job.notes.append("Mock synthesis worker produced deterministic artifact metadata.")
        return job


tts_playback_adapter = TtsPlaybackAdapter()
