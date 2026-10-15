"""Time helpers. Everything is stored in UTC; a "day" always means a local Bucharest day."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) of a local day. Lasts 23, 24 or 25 hours around DST changes."""
    start = datetime.combine(day, time(0), tzinfo=TZ)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def day_length_hours(day: date) -> int:
    start, end = local_day_bounds(day)
    return int((end - start).total_seconds() // 3600)


def expected_intervals(day: date, resolution_minutes: int) -> int:
    return day_length_hours(day) * 60 // resolution_minutes


def local_day_of(unix_seconds: int) -> date:
    return datetime.fromtimestamp(unix_seconds, TZ).date()


def yesterday_local() -> date:
    return datetime.now(TZ).date() - timedelta(days=1)


def date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    """Split the inclusive range [start, end] into inclusive chunks of at most max_days."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def days_between(start: date, end: date) -> list[date]:
    """Inclusive list of days from start to end."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
