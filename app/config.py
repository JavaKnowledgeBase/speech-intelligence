from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    hume_api_key: str = os.getenv("HUME_API_KEY", "")
    livekit_url: str = os.getenv("LIVEKIT_URL", "")
    livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
    livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
    livekit_room_prefix: str = os.getenv("LIVEKIT_ROOM_PREFIX", "talkbuddy")
    livekit_token_ttl_seconds: int = int(os.getenv("LIVEKIT_TOKEN_TTL_SECONDS", "3600"))
    temporal_host: str = os.getenv("TEMPORAL_HOST", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_repository_mode: str = os.getenv("SUPABASE_REPOSITORY_MODE", "auto")
    clerk_secret_key: str = os.getenv("CLERK_SECRET_KEY", "")
    use_live_provider_calls: bool = os.getenv("USE_LIVE_PROVIDER_CALLS", "false").lower() == "true"

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
