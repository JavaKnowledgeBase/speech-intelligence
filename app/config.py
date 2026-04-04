from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str = "") -> str:
    """Return env value with inline comments stripped (e.g. 'val  # note' → 'val')."""
    return os.getenv(key, default).split("#")[0].strip()


def _env_int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, "true" if default else "false").lower() == "true"


@dataclass
class Settings:
    app_env: str = _env("APP_ENV", "development")
    openai_api_key: str = _env("OPENAI_API_KEY")
    google_api_key: str = _env("GOOGLE_API_KEY") or _env("GEMINI_API_KEY")
    deepgram_api_key: str = _env("DEEPGRAM_API_KEY")
    hume_api_key: str = _env("HUME_API_KEY")
    livekit_url: str = _env("LIVEKIT_URL")
    livekit_api_key: str = _env("LIVEKIT_API_KEY")
    livekit_api_secret: str = _env("LIVEKIT_API_SECRET")
    livekit_room_prefix: str = _env("LIVEKIT_ROOM_PREFIX", "talkbuddy")
    livekit_token_ttl_seconds: int = _env_int("LIVEKIT_TOKEN_TTL_SECONDS", 3600)
    temporal_host: str = _env("TEMPORAL_HOST")
    supabase_url: str = _env("SUPABASE_URL")
    supabase_service_role_key: str = _env("SUPABASE_SERVICE_ROLE_KEY")
    supabase_repository_mode: str = _env("SUPABASE_REPOSITORY_MODE", "auto")
    clerk_secret_key: str = _env("CLERK_SECRET_KEY")
    use_live_provider_calls: bool = _env_bool("USE_LIVE_PROVIDER_CALLS")

    def configured(self, value: str) -> bool:
        return bool(value and value.strip())

    @property
    def supabase_configured(self) -> bool:
        return self.configured(self.supabase_url) and self.configured(self.supabase_service_role_key)

    @property
    def livekit_configured(self) -> bool:
        return (
            self.configured(self.livekit_url)
            and self.configured(self.livekit_api_key)
            and self.configured(self.livekit_api_secret)
        )


settings = Settings()
