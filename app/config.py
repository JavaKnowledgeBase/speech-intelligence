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
    temporal_host: str = os.getenv("TEMPORAL_HOST", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    clerk_secret_key: str = os.getenv("CLERK_SECRET_KEY", "")
    use_live_provider_calls: bool = os.getenv("USE_LIVE_PROVIDER_CALLS", "false").lower() == "true"

    def configured(self, value: str) -> bool:
        return bool(value and value.strip())


settings = Settings()
