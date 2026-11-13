"""Builds the Clover adapter and its collaborators from the settings (one instance per process)."""

from functools import lru_cache

from app.core.config import APP_VERSION, settings
from app.integrations.clover.cloud_terminal import CloverCloudTerminal
from app.integrations.clover.oauth import CloverOAuthClient
from app.integrations.clover.tokens import CloverTokenProvider, TokenCipher
from app.repositories.supabase_clover_store import SupabaseCloverStore

USER_AGENT = f"MundoUniformePOS/{APP_VERSION}"


@lru_cache(maxsize=1)
def get_clover_store() -> SupabaseCloverStore:
    return SupabaseCloverStore()


@lru_cache(maxsize=1)
def get_token_cipher() -> TokenCipher:
    return TokenCipher(settings.CLOVER_TOKEN_KEY.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_oauth_client() -> CloverOAuthClient:
    return CloverOAuthClient(
        oauth_url=settings.clover_oauth_url,
        api_url=settings.clover_api_url,
        app_id=settings.CLOVER_APP_ID,
        app_secret=settings.CLOVER_APP_SECRET.get_secret_value().strip(),
    )


def build_clover_terminal() -> CloverCloudTerminal:
    store = get_clover_store()
    return CloverCloudTerminal(
        base_url=settings.clover_connect_url,
        tokens=CloverTokenProvider(store=store, oauth=get_oauth_client(), cipher=get_token_cipher()),
        get_integration=store.get,
        default_pos_id=settings.CLOVER_POS_ID,
        user_agent=USER_AGENT,
    )
