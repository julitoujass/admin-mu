"""In-memory payment terminal for tests and for developing the POS without a device.

Tests script it: `FakeTerminal(script=[ChargeOutcome.DECLINED], lookups=[...], refunds=[...])`.
Each scripted entry is consumed by one call; an entry that is an exception is raised.

Without a script (development, `PAYMENT_TERMINAL=fake`) the outcome depends on the
cents of the amount, so every path can be exercised by hand from the POS:

- `.13` -> DECLINED
- `.99` -> UNKNOWN; lookups keep answering UNKNOWN three times and then APPROVED,
  so the charge is left for the sweep (or the admin's "conciliar") to resolve
- anything else -> APPROVED with a VISA ending in 4242, after `delay` seconds
  (`cancel_current()` interrupts the wait and the charge ends as CANCELLED)

This adapter does no logging at all, so it cannot leak card data.
"""

import secrets
import threading
from typing import Iterable

from app.integrations.payment_terminal.port import (
    ChargeOutcome,
    ChargeRequest,
    ChargeResult,
    RefundOutcome,
    RefundResult,
    TerminalBusy,
    TerminalStatus,
)

DECLINED_CENTS = 13
UNKNOWN_CENTS = 99
UNKNOWN_LOOKUPS_BEFORE_APPROVAL = 3

ChargeScriptEntry = ChargeOutcome | ChargeResult | Exception
LookupScriptEntry = ChargeOutcome | ChargeResult | Exception | None
RefundScriptEntry = RefundOutcome | RefundResult | Exception


class FakeTerminal:
    def __init__(
        self,
        script: Iterable[ChargeScriptEntry] | None = None,
        lookups: Iterable[LookupScriptEntry] | None = None,
        refunds: Iterable[RefundScriptEntry] | None = None,
        delay: float = 0.0,
        connected: bool = True,
    ):
        self.script = list(script or [])
        self.lookups = list(lookups or [])
        self.refunds = list(refunds or [])
        self.delay = delay
        self.connected = connected
        # Recorded calls, for assertions.
        self.charges: list[ChargeRequest] = []
        self.lookup_calls: list[str] = []
        self.refund_calls: list[tuple[str, int | None]] = []
        self.cancel_calls = 0
        self.welcome_calls = 0
        # external id -> final result, and external id -> UNKNOWN answers left before approving.
        self._payments: dict[str, ChargeResult] = {}
        self._unknown_lookups_left: dict[str, int] = {}
        self._requests: dict[str, ChargeRequest] = {}
        self._busy = threading.Lock()
        self._cancel = threading.Event()

    # Port ---------------------------------------------------------------------
    def ping(self) -> bool:
        return self.connected

    def status(self) -> TerminalStatus:
        return TerminalStatus.BUSY if self._busy.locked() else TerminalStatus.IDLE

    def charge(self, req: ChargeRequest) -> ChargeResult:
        if not self._busy.acquire(blocking=False):
            raise TerminalBusy("The fake terminal is processing another charge")
        try:
            self.charges.append(req)
            self._requests[req.external_id] = req
            if self.script:
                return self._remember(req.external_id, self._scripted(self.script.pop(0), req))
            if self.delay > 0 and self._cancel.wait(self.delay):
                return self._remember(req.external_id, ChargeResult(outcome=ChargeOutcome.CANCELLED))
            cents = req.amount_cents % 100
            if cents == DECLINED_CENTS:
                return self._remember(req.external_id, self._build(ChargeOutcome.DECLINED, req))
            if cents == UNKNOWN_CENTS:
                self._unknown_lookups_left[req.external_id] = UNKNOWN_LOOKUPS_BEFORE_APPROVAL
                return self._build(ChargeOutcome.UNKNOWN, req)
            return self._remember(req.external_id, self._build(ChargeOutcome.APPROVED, req))
        finally:
            self._cancel.clear()
            self._busy.release()

    def find_by_external_id(self, external_id: str) -> ChargeResult | None:
        self.lookup_calls.append(external_id)
        if self.lookups:
            entry = self.lookups.pop(0)
            if entry is None:
                return None
            return self._remember(external_id, self._scripted(entry, self._requests.get(external_id)))
        left = self._unknown_lookups_left.get(external_id)
        if left is not None:
            if left > 0:
                self._unknown_lookups_left[external_id] = left - 1
                return self._build(ChargeOutcome.UNKNOWN, self._requests.get(external_id))
            del self._unknown_lookups_left[external_id]
            self._remember(external_id, self._build(ChargeOutcome.APPROVED, self._requests.get(external_id)))
        return self._payments.get(external_id)

    def cancel_current(self) -> None:
        self.cancel_calls += 1
        if self._busy.locked():  # nothing on screen: cancelling is a no-op
            self._cancel.set()

    def refund(self, payment_id: str, amount_cents: int | None) -> RefundResult:
        self.refund_calls.append((payment_id, amount_cents))
        entry = self.refunds.pop(0) if self.refunds else RefundOutcome.DONE
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, RefundResult):
            return entry
        refund_id = f"FAKE-R-{secrets.token_hex(6)}" if entry is RefundOutcome.DONE else None
        error = None if entry is RefundOutcome.DONE else "Reembolso no confirmado por el terminal simulado"
        return RefundResult(outcome=entry, refund_id=refund_id, raw={"simulated": True}, error=error)

    def show_welcome(self) -> None:
        self.welcome_calls += 1

    # Internals ------------------------------------------------------------------
    def _scripted(self, entry, req: ChargeRequest | None) -> ChargeResult:
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, ChargeResult):
            return entry
        return self._build(entry, req)

    def _remember(self, external_id: str, result: ChargeResult) -> ChargeResult:
        """Keep final results so later lookups answer the same."""
        if result.outcome is not ChargeOutcome.UNKNOWN:
            self._payments[external_id] = result
        return result

    @staticmethod
    def _build(outcome: ChargeOutcome, req: ChargeRequest | None) -> ChargeResult:
        raw = {"simulated": True, "result": outcome.value}
        if outcome is ChargeOutcome.APPROVED:
            return ChargeResult(
                outcome=outcome,
                provider_payment_id=f"FAKE-{secrets.token_hex(8)}",
                card_brand="VISA",
                last4="4242",
                auth_code=f"{secrets.randbelow(1_000_000):06d}",
                installments=1,
                entry_type="QR_CODE" if req is not None and req.metodo == "QR" else "EMV_CONTACTLESS",
                raw=raw,
            )
        if outcome is ChargeOutcome.DECLINED:
            return ChargeResult(outcome=outcome, raw=raw, error="Pago rechazado por el terminal simulado")
        return ChargeResult(outcome=outcome, raw=raw)
