"""Optional live checks against the Clover sandbox. Never part of the default run nor of CI.

    CLOVER_SANDBOX_LIVE=1 pytest -m clover_sandbox

Needs the real `.env` (PAYMENT_TERMINAL=clover, CLOVER_* and Supabase), the account connected from
Configuración and the device serial saved. They only read: nothing is charged.
"""

import os
from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.clover_sandbox,
    pytest.mark.skipif(os.environ.get("CLOVER_SANDBOX_LIVE") != "1", reason="set CLOVER_SANDBOX_LIVE=1 to run"),
]


@pytest.fixture(scope="module")
def terminal():
    from app.core.config import settings
    from app.integrations.clover.wiring import build_clover_terminal

    if settings.PAYMENT_TERMINAL != "clover" or settings.CLOVER_ENV != "sandbox":
        pytest.skip("needs PAYMENT_TERMINAL=clover and CLOVER_ENV=sandbox")
    return build_clover_terminal()


def test_device_answers_ping_and_status(terminal):
    from app.integrations.payment_terminal.port import TerminalStatus

    assert terminal.ping() is True
    assert terminal.status() in set(TerminalStatus)


def test_unknown_external_id_is_a_definitive_not_found(terminal):
    """How Clover reports a missing payment is not documented: this pins the adapter's assumption."""
    assert terminal.find_by_external_id(uuid4().hex) is None


def test_welcome_screen(terminal):
    terminal.show_welcome()
