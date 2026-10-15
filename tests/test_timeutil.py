from datetime import date

import pytest

from gridpulse.timeutil import date_chunks, day_length_hours, expected_intervals, local_day_bounds


@pytest.mark.parametrize(
    ("day", "hours"),
    [
        (date(2026, 10, 15), 24),
        (date(2026, 3, 29), 23),  # summer time starts
        (date(2025, 10, 26), 25),
        (date(2026, 10, 25), 25),  # the live test from the plan
    ],
)
def test_day_length_follows_dst(day, hours):
    assert day_length_hours(day) == hours
    assert expected_intervals(day, 15) == hours * 4


def test_local_day_bounds_are_utc():
    start, end = local_day_bounds(date(2026, 10, 15))
    assert start.isoformat() == "2026-10-14T21:00:00+00:00"
    assert end.isoformat() == "2026-10-15T21:00:00+00:00"


def test_date_chunks_cover_range_without_gaps():
    chunks = date_chunks(date(2023, 1, 1), date(2023, 3, 5), 31)
    assert chunks[0] == (date(2023, 1, 1), date(2023, 1, 31))
    assert chunks[-1][1] == date(2023, 3, 5)
    total = sum((e - s).days + 1 for s, e in chunks)
    assert total == (date(2023, 3, 5) - date(2023, 1, 1)).days + 1


def test_date_chunks_rejects_reversed_range():
    with pytest.raises(ValueError):
        date_chunks(date(2023, 2, 1), date(2023, 1, 1), 31)
