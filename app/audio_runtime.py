from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class AudioRuntimeService:
    """Server-side audio runtime registry for provider readiness and shared policy."""

    started: bool = False
    started_at: datetime | None = None
    providers: dict[str, bool] = field(default_factory=dict)

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.started_at = datetime.now(UTC)

    def stop(self) -> None:
        self.started = False

    def register_provider(self, name: str, configured: bool) -> None:
        self.providers[name] = bool(configured)

    def snapshot(self) -> dict:
        return {
            "started": self.started,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "providers": dict(self.providers),
        }


audio_runtime = AudioRuntimeService()
