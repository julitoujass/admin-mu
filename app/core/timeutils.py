from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# Business timezone: every "day" in the POS is an Argentina local day.
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_argentina() -> datetime:
    return datetime.now(ARGENTINA_TZ)


def local_day_bounds_utc(now: datetime) -> tuple[str, str]:
    """Return [start, end) of the Argentina local day containing `now`, as UTC ISO strings.

    `now` must be timezone-aware. The strings use the `Z` suffix so they are safe
    to send as PostgREST filter values (no `+` to URL-encode).
    """
    local_day = now.astimezone(ARGENTINA_TZ).date()
    start = datetime.combine(local_day, time.min, tzinfo=ARGENTINA_TZ)
    end = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=ARGENTINA_TZ)
    return (
        start.astimezone(timezone.utc).strftime(_UTC_FORMAT),
        end.astimezone(timezone.utc).strftime(_UTC_FORMAT),
    )
