import logging
import threading

import pytest

from app.integrations.payment_terminal import factory
from app.integrations.payment_terminal.fake import FakeTerminal
from app.integrations.payment_terminal.port import (
    ChargeOutcome,
    ChargeRequest,
    ChargeResult,
    PaymentTerminal,
    RefundOutcome,
    RefundResult,
    TerminalBusy,
    TerminalStatus,
    TerminalUnavailable,
)


def request(amount_cents=150000, external_id="a" * 32, metodo="Tarjeta"):
    return ChargeRequest(external_id=external_id, amount_cents=amount_cents, metodo=metodo, description="Venta POS")


def test_fake_terminal_satisfies_the_port():
    assert isinstance(FakeTerminal(), PaymentTerminal)


def test_default_charge_is_approved_with_a_test_card():
    terminal = FakeTerminal()

    result = terminal.charge(request())

    assert result.outcome is ChargeOutcome.APPROVED
    assert (result.card_brand, result.last4) == ("VISA", "4242")
    assert result.provider_payment_id
    assert result.auth_code and result.auth_code.isdigit() and len(result.auth_code) == 6
    assert result.installments == 1
    assert terminal.charges == [request()]


@pytest.mark.parametrize(
    ("amount_cents", "outcome"),
    [(150013, ChargeOutcome.DECLINED), (150099, ChargeOutcome.UNKNOWN), (150000, ChargeOutcome.APPROVED)],
)
def test_default_outcome_depends_on_the_cents(amount_cents, outcome):
    assert FakeTerminal().charge(request(amount_cents)).outcome is outcome


def test_script_overrides_the_default_outcomes_in_order():
    custom = ChargeResult(outcome=ChargeOutcome.APPROVED, provider_payment_id="P1", card_brand="MASTERCARD", last4="1111")
    terminal = FakeTerminal(script=[ChargeOutcome.DECLINED, custom, TerminalBusy("busy")])

    assert terminal.charge(request(external_id="one")).outcome is ChargeOutcome.DECLINED
    assert terminal.charge(request(external_id="two")) == custom
    with pytest.raises(TerminalBusy):
        terminal.charge(request(external_id="three"))
    # Script exhausted: back to the default behaviour.
    assert terminal.charge(request(external_id="four")).outcome is ChargeOutcome.APPROVED


def test_find_by_external_id_returns_what_was_charged():
    terminal = FakeTerminal()
    charged = terminal.charge(request(external_id="known"))

    assert terminal.find_by_external_id("known") == charged
    assert terminal.find_by_external_id("never-seen") is None
    assert terminal.lookup_calls == ["known", "never-seen"]


def test_scripted_lookups_are_consumed_in_order():
    terminal = FakeTerminal(
        script=[ChargeOutcome.UNKNOWN],
        lookups=[TerminalUnavailable("down"), None, ChargeOutcome.UNKNOWN, ChargeOutcome.APPROVED],
    )
    terminal.charge(request(external_id="x"))

    with pytest.raises(TerminalUnavailable):
        terminal.find_by_external_id("x")
    assert terminal.find_by_external_id("x") is None
    assert terminal.find_by_external_id("x").outcome is ChargeOutcome.UNKNOWN
    approved = terminal.find_by_external_id("x")
    assert approved.outcome is ChargeOutcome.APPROVED
    # Once resolved, the answer is stable.
    assert terminal.find_by_external_id("x") == approved


def test_default_unknown_charge_resolves_as_approved_after_three_lookups():
    terminal = FakeTerminal()
    terminal.charge(request(150099, external_id="slow"))

    outcomes = [terminal.find_by_external_id("slow").outcome for _ in range(4)]

    assert outcomes == [ChargeOutcome.UNKNOWN] * 3 + [ChargeOutcome.APPROVED]


def test_delay_is_waited_and_cancel_current_interrupts_it():
    terminal = FakeTerminal(delay=30)
    results = []
    worker = threading.Thread(target=lambda: results.append(terminal.charge(request())))
    worker.start()
    while terminal.status() is not TerminalStatus.BUSY:
        pass

    with pytest.raises(TerminalBusy):
        terminal.charge(request(external_id="second"))
    terminal.cancel_current()
    worker.join(timeout=5)

    assert [result.outcome for result in results] == [ChargeOutcome.CANCELLED]
    assert terminal.status() is TerminalStatus.IDLE
    assert terminal.cancel_calls == 1


def test_refund_defaults_to_done_and_can_be_scripted():
    terminal = FakeTerminal(refunds=[RefundOutcome.FAILED, TerminalUnavailable("down")])

    assert terminal.refund("P1", None).outcome is RefundOutcome.FAILED
    with pytest.raises(TerminalUnavailable):
        terminal.refund("P1", 500)
    done = terminal.refund("P1", None)
    assert isinstance(done, RefundResult) and done.outcome is RefundOutcome.DONE
    assert terminal.refund_calls == [("P1", None), ("P1", 500), ("P1", None)]


def test_ping_and_welcome():
    terminal = FakeTerminal()
    assert terminal.ping() is True
    assert FakeTerminal(connected=False).ping() is False
    terminal.show_welcome()
    assert terminal.welcome_calls == 1


def test_fake_terminal_never_logs(caplog):
    caplog.set_level(logging.DEBUG)
    terminal = FakeTerminal()

    terminal.charge(request())
    terminal.find_by_external_id("a" * 32)
    terminal.refund("P1", None)

    assert "4242" not in caplog.text


def test_factory_builds_the_fake_by_default(monkeypatch):
    factory.get_terminal.cache_clear()
    monkeypatch.setattr(factory.settings, "PAYMENT_TERMINAL", "fake")
    monkeypatch.setattr(factory.settings, "PAYMENT_FAKE_DELAY_SECONDS", 1.5)

    terminal = factory.get_terminal()

    assert isinstance(terminal, FakeTerminal)
    assert terminal.delay == 1.5
    assert factory.get_terminal() is terminal  # one device, one instance
    factory.get_terminal.cache_clear()


def test_factory_builds_the_clover_adapter(monkeypatch):
    from app.integrations.clover.cloud_terminal import CloverCloudTerminal
    from app.integrations.payment_terminal.port import PaymentTerminal

    factory.get_terminal.cache_clear()
    monkeypatch.setattr(factory.settings, "PAYMENT_TERMINAL", "clover")

    terminal = factory.get_terminal()

    assert isinstance(terminal, CloverCloudTerminal)
    assert isinstance(terminal, PaymentTerminal)
    assert terminal._base_url == "https://apisandbox.dev.clover.com/connect"
    factory.get_terminal.cache_clear()
