from __future__ import annotations

"""
Supabase client singleton for speech-intelligence.

Usage:
    from app.db.client import db
    client = db.get()          # returns None when Supabase is not configured
    if client:
        client.table("sessions").upsert(...).execute()
"""

from app.config import settings


class SupabaseClient:
    """
    Lazy Supabase client wrapper.

    All operations are skipped when SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY
    are not configured — the in-memory store remains authoritative.
    """

    def __init__(self) -> None:
        self._client = None

    def enabled(self) -> bool:
        return settings.supabase_configured

    def get(self):
        """Return the Supabase client or None if not configured."""
        if not self.enabled():
            return None
        if self._client is None:
            try:
                from supabase import create_client  # type: ignore[import]
                self._client = create_client(
                    settings.supabase_url, settings.supabase_service_role_key
                )
            except Exception:  # noqa: BLE001
                return None
        return self._client


db = SupabaseClient()
