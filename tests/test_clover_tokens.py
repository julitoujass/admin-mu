"""Clover token vault: encryption at rest, renewal, single-use refresh token and failures."""

import logging
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.integrations.clover.oauth import CloverOAuthRejected, CloverOAuthUnavailable
from app.integrations.clover.tokens import RECONNECT, CloverTokenProvider, TokenCipher
from app.integrations.payment_terminal.port import TerminalUnavailable
from app.repositories import supabase_clover_store
from app.repositories.supabase_clover_store import SupabaseCloverStore
from tests.fakes import FakeSupabase
from tests.fakes_clover import CIPHER, NOW, InMemoryCloverStore, ScriptedOAuth, tokens


def provider(store, oauth=None):
    oauth = oauth or ScriptedOAuth()
    return CloverTokenProvider(store=store, oauth=oauth, cipher=CIPHER, now=lambda: NOW), oauth


def test_encryption_round_trip_and_ciphertext_is_not_the_token():
    cipher_text = CIPHER.encrypt("secret-access-token")

    assert "secret-access-token" not in cipher_text
    assert CIPHER.decrypt(cipher_text) == "secret-access-token"
    assert CIPHER.encrypt("secret-access-token") != cipher_text  # random IV


def test_a_different_key_cannot_decrypt():
    other = TokenCipher(Fernet.generate_key().decode())

    with pytest.raises(InvalidToken):
        other.decrypt(CIPHER.encrypt("secret"))


def test_a_fresh_token_is_returned_without_refreshing():
    store = InMemoryCloverStore(expires_in=301)
    vault, oauth = provider(store)

    assert vault.get_access_token() == "access-1"
    assert oauth.refresh_calls == []


@pytest.mark.parametrize("expires_in", [300, 60, -10])
def test_a_token_expiring_within_five_minutes_is_renewed_and_stored_encrypted(expires_in):
    store = InMemoryCloverStore(expires_in=expires_in)
    vault, oauth = provider(store)

    assert vault.get_access_token() == "access-2"

    assert oauth.refresh_calls == ["refresh-1"]
    assert (store.access, store.refresh) == ("access-2", "refresh-2")
    assert "access-2" not in store.row["access_token_cifrado"]
    assert store.row["access_expira_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert store.row["habilitado"] is True
    # The renewed token is used from then on: the single-use refresh token is not spent again.
    assert vault.get_access_token() == "access-2"
    assert oauth.refresh_calls == ["refresh-1"]


def test_missing_expiry_means_renew():
    store = InMemoryCloverStore()
    store.row["access_expira_at"] = None
    vault, oauth = provider(store)

    assert vault.get_access_token() == "access-2"


def test_a_rejected_token_forces_a_renewal_once():
    store = InMemoryCloverStore()
    vault, oauth = provider(store)

    assert vault.get_access_token(rejected="access-1") == "access-2"
    # Someone already renewed it: the stored token is not the rejected one any more.
    assert vault.get_access_token(rejected="access-1") == "access-2"
    assert oauth.refresh_calls == ["refresh-1"]


def test_without_tokens_the_admin_must_reconnect():
    store = InMemoryCloverStore(access=None, refresh=None)
    vault, oauth = provider(store)

    with pytest.raises(TerminalUnavailable) as error:
        vault.get_access_token()

    assert str(error.value) == RECONNECT == "Reconectá Clover desde Configuración"
    assert oauth.refresh_calls == []


def test_refresh_rejected_disables_the_integration():
    store = InMemoryCloverStore(expires_in=0)
    vault, oauth = provider(store, ScriptedOAuth(CloverOAuthRejected("/oauth/v2/refresh")))

    with pytest.raises(TerminalUnavailable) as error:
        vault.get_access_token()

    assert str(error.value) == "Reconectá Clover desde Configuración"
    assert store.row["habilitado"] is False


def test_refresh_unreachable_does_not_disable():
    store = InMemoryCloverStore(expires_in=0)
    vault, oauth = provider(store, ScriptedOAuth(CloverOAuthUnavailable("/oauth/v2/refresh")))

    with pytest.raises(TerminalUnavailable):
        vault.get_access_token()

    assert store.row["habilitado"] is True
    assert store.refresh == "refresh-1"
    # Next call tries again.
    assert vault.get_access_token() == "access-3"


def test_losing_the_compare_and_set_uses_what_the_other_process_stored():
    store = InMemoryCloverStore(expires_in=0)
    store.before_replace.append(lambda: store.set_tokens("access-other", "refresh-other"))
    vault, oauth = provider(store)

    assert vault.get_access_token() == "access-other"

    assert (store.access, store.refresh) == ("access-other", "refresh-other")
    assert store.row["habilitado"] is True


def test_losing_the_compare_and_set_to_a_disconnection_asks_to_reconnect():
    store = InMemoryCloverStore(expires_in=0)
    store.before_replace.append(lambda: store.clear_connection("admin"))
    vault, oauth = provider(store)

    with pytest.raises(TerminalUnavailable):
        vault.get_access_token()

    assert store.row["access_token_cifrado"] is None


def test_refresh_token_spent_by_another_process_is_not_a_failure():
    store = InMemoryCloverStore(expires_in=0)

    class RacingOAuth(ScriptedOAuth):
        def refresh(self, refresh_token):
            # Another process renewed between our read and our call to Clover.
            store.set_tokens("access-other", "refresh-other")
            self.refresh_calls.append(refresh_token)
            raise CloverOAuthRejected("/oauth/v2/refresh")

    vault, oauth = provider(store, RacingOAuth())

    assert vault.get_access_token() == "access-other"
    assert store.row["habilitado"] is True


def test_tokens_stored_with_another_key_disable_the_integration():
    store = InMemoryCloverStore()
    store.row["access_token_cifrado"] = TokenCipher(Fernet.generate_key().decode()).encrypt("access-1")
    vault, oauth = provider(store)

    with pytest.raises(TerminalUnavailable):
        vault.get_access_token()

    assert store.row["habilitado"] is False
    assert oauth.refresh_calls == []


def test_tokens_are_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    store = InMemoryCloverStore(expires_in=0)
    vault, oauth = provider(store)
    vault.get_access_token()

    failing, _ = provider(InMemoryCloverStore(expires_in=0), ScriptedOAuth(CloverOAuthRejected("x")))
    with pytest.raises(TerminalUnavailable):
        failing.get_access_token()

    for secret in ("access-1", "refresh-1", "access-2", "refresh-2"):
        assert secret not in caplog.text
    assert "refresh-2" not in repr(tokens("access-2", "refresh-2"))


# --- Supabase adapter ------------------------------------------------------------------------------


@pytest.fixture
def db(monkeypatch):
    def install(*responses):
        fake = FakeSupabase(*responses)
        monkeypatch.setattr(supabase_clover_store, "supabase", fake)
        return fake

    return install


def test_store_replace_tokens_is_a_compare_and_set_on_the_spent_refresh_token(db):
    fake = db([{"id": 1}], [])
    store = SupabaseCloverStore()

    assert store.replace_tokens("enc-old", "enc-a", "enc-r", NOW) is True
    assert store.replace_tokens("enc-old", "enc-a2", "enc-r2", NOW) is False

    query = fake.table_calls("integracion_terminal")[0]
    assert query.args_of("update") == [
        ({"access_token_cifrado": "enc-a", "refresh_token_cifrado": "enc-r", "access_expira_at": NOW.isoformat()},)
    ]
    assert query.args_of("eq") == [("id", 1), ("refresh_token_cifrado", "enc-old")]


def test_store_save_and_clear_connection(db):
    fake = db([{"id": 1}], [{"id": 1}], [])
    store = SupabaseCloverStore()

    assert store.save_connection("enc-a", "enc-r", NOW, "M123", "user-1") == {"id": 1}
    assert store.clear_connection("user-1") == {"id": 1}
    store.disable()

    saved, cleared, disabled = (query.args_of("update")[0][0] for query in fake.table_calls("integracion_terminal"))
    assert {key: saved[key] for key in saved if key != "updated_at"} == {
        "proveedor": "clover",
        "merchant_id": "M123",
        "access_token_cifrado": "enc-a",
        "refresh_token_cifrado": "enc-r",
        "access_expira_at": NOW.isoformat(),
        "updated_by": "user-1",
    }
    assert "habilitado" not in saved  # connecting never enables charging by itself
    assert {key: cleared[key] for key in cleared if key not in ("updated_at", "updated_by")} == {
        "habilitado": False,
        "merchant_id": None,
        "access_token_cifrado": None,
        "refresh_token_cifrado": None,
        "access_expira_at": None,
    }
    assert disabled["habilitado"] is False and "access_token_cifrado" not in disabled
