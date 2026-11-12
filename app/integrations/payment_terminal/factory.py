from functools import lru_cache

from app.core.config import settings
from app.integrations.payment_terminal.fake import FakeTerminal
from app.integrations.payment_terminal.port import PaymentTerminal


@lru_cache(maxsize=1)
def get_terminal() -> PaymentTerminal:
    """The terminal adapter selected by `PAYMENT_TERMINAL`. One instance per process: there is one device."""
    if settings.PAYMENT_TERMINAL == "fake":
        return FakeTerminal(delay=settings.PAYMENT_FAKE_DELAY_SECONDS)
    if settings.PAYMENT_TERMINAL == "clover":
        raise NotImplementedError("The Clover adapter arrives in stage C; use PAYMENT_TERMINAL=fake for now")
    raise ValueError(f"Unknown PAYMENT_TERMINAL: {settings.PAYMENT_TERMINAL!r}")
