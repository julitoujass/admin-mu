"""Supabase persistence of the Clover connection (OAuth columns of the `integracion_terminal` row).

Tokens arrive here already encrypted; this module never sees them in clear.
"""

from datetime import datetime, timezone

from app.core.supabase import supabase

INTEGRATION = "integracion_terminal"
INTEGRATION_ID = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseCloverStore:
    def get(self) -> dict | None:
        res = supabase.table(INTEGRATION).select("*").eq("id", INTEGRATION_ID).limit(1).execute()
        return res.data[0] if res.data else None

    def replace_tokens(
        self, expected_refresh_cifrado: str, access_cifrado: str, refresh_cifrado: str, access_expira_at: datetime
    ) -> bool:
        """Compare-and-set: only the process that still sees the spent refresh token stores its renewal."""
        values = {
            "access_token_cifrado": access_cifrado,
            "refresh_token_cifrado": refresh_cifrado,
            "access_expira_at": access_expira_at.isoformat(),
        }
        res = (
            supabase.table(INTEGRATION)
            .update(values)
            .eq("id", INTEGRATION_ID)
            .eq("refresh_token_cifrado", expected_refresh_cifrado)
            .execute()
        )
        return bool(res.data)

    def disable(self) -> None:
        supabase.table(INTEGRATION).update({"habilitado": False, "updated_at": _now_iso()}).eq(
            "id", INTEGRATION_ID
        ).execute()

    def save_connection(
        self,
        access_cifrado: str,
        refresh_cifrado: str,
        access_expira_at: datetime,
        merchant_id: str | None,
        user_id: str,
    ) -> dict | None:
        values = {
            "proveedor": "clover",
            "merchant_id": merchant_id,
            "access_token_cifrado": access_cifrado,
            "refresh_token_cifrado": refresh_cifrado,
            "access_expira_at": access_expira_at.isoformat(),
            "updated_at": _now_iso(),
            "updated_by": str(user_id),
        }
        res = supabase.table(INTEGRATION).update(values).eq("id", INTEGRATION_ID).execute()
        return res.data[0] if res.data else None

    def clear_connection(self, user_id: str) -> dict | None:
        values = {
            "habilitado": False,
            "merchant_id": None,
            "access_token_cifrado": None,
            "refresh_token_cifrado": None,
            "access_expira_at": None,
            "updated_at": _now_iso(),
            "updated_by": str(user_id),
        }
        res = supabase.table(INTEGRATION).update(values).eq("id", INTEGRATION_ID).execute()
        return res.data[0] if res.data else None
