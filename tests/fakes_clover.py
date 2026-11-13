"""Stand-ins shared by the Clover tests: an in-memory integration row and a scripted OAuth client."""

import copy
from datetime import datetime, timedelta, timezone

from app.integrations.clover.oauth import CloverTokens
from app.integrations.clover.tokens import TokenCipher

TOKEN_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="  # Fernet key of 32 "0" bytes: tests only
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
CIPHER = TokenCipher(TOKEN_KEY)


class InMemoryCloverStore:
    """The `integracion_terminal` row, with the same compare-and-set as the Supabase adapter."""

    def __init__(self, access="access-1", refresh="refresh-1", expires_in=3600, device_id="C0123", **extra):
        self.row = {
            "id": 1,
            "proveedor": "clover",
            "habilitado": True,
            "merchant_id": "M123",
            "device_id": device_id,
            "pos_id": None,
            "access_token_cifrado": CIPHER.encrypt(access) if access else None,
            "refresh_token_cifrado": CIPHER.encrypt(refresh) if refresh else None,
            "access_expira_at": (NOW + timedelta(seconds=expires_in)).isoformat() if access else None,
            "updated_by": None,
            **extra,
        }
        self.reads = 0
        # Callbacks run right before a compare-and-set, to simulate another process getting there first.
        self.before_replace = []

    def get(self):
        self.reads += 1
        return copy.deepcopy(self.row)

    def replace_tokens(self, expected_refresh_cifrado, access_cifrado, refresh_cifrado, access_expira_at):
        while self.before_replace:
            self.before_replace.pop(0)()
        if self.row["refresh_token_cifrado"] != expected_refresh_cifrado:
            return False
        self.row.update(
            access_token_cifrado=access_cifrado,
            refresh_token_cifrado=refresh_cifrado,
            access_expira_at=access_expira_at.isoformat(),
        )
        return True

    def disable(self):
        self.row["habilitado"] = False

    def save_connection(self, access_cifrado, refresh_cifrado, access_expira_at, merchant_id, user_id):
        self.row.update(
            proveedor="clover",
            merchant_id=merchant_id,
            access_token_cifrado=access_cifrado,
            refresh_token_cifrado=refresh_cifrado,
            access_expira_at=access_expira_at.isoformat(),
            updated_by=user_id,
        )
        return self.get()

    def clear_connection(self, user_id):
        self.row.update(
            habilitado=False,
            merchant_id=None,
            access_token_cifrado=None,
            refresh_token_cifrado=None,
            access_expira_at=None,
            updated_by=user_id,
        )
        return self.get()

    # Test helpers
    def set_tokens(self, access, refresh, expires_in=3600):
        self.row.update(
            access_token_cifrado=CIPHER.encrypt(access),
            refresh_token_cifrado=CIPHER.encrypt(refresh),
            access_expira_at=(NOW + timedelta(seconds=expires_in)).isoformat(),
        )

    @property
    def access(self):
        return CIPHER.decrypt(self.row["access_token_cifrado"])

    @property
    def refresh(self):
        return CIPHER.decrypt(self.row["refresh_token_cifrado"])


class ScriptedOAuth:
    """`refresh()` answers the scripted entries in order (an exception is raised); then numbered tokens."""

    def __init__(self, *script):
        self.script = list(script)
        self.refresh_calls = []

    def refresh(self, refresh_token):
        self.refresh_calls.append(refresh_token)
        if self.script:
            entry = self.script.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return entry
        number = len(self.refresh_calls) + 1
        return tokens(f"access-{number}", f"refresh-{number}")


def tokens(access, refresh, expires_in=3600):
    return CloverTokens(access, refresh, NOW + timedelta(seconds=expires_in))
