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
        # Imported here so the fake setup never loads the Clover adapter nor needs its secrets.
        from app.integrations.clover.wiring import build_clover_terminal

        return build_clover_terminal()
    raise ValueError(f"Unknown PAYMENT_TERMINAL: {settings.PAYMENT_TERMINAL!r}")
