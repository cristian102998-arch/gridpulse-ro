import importlib.util
from datetime import date
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "make_holidays", Path(__file__).resolve().parents[1] / "scripts" / "make_holidays.py"
)
make_holidays = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_holidays)


@pytest.mark.parametrize(
    "easter",
    [date(2023, 4, 16), date(2024, 5, 5), date(2025, 4, 20), date(2026, 4, 12), date(2027, 5, 2)],
)
def test_orthodox_easter_known_dates(easter):
    assert make_holidays.orthodox_easter(easter.year) == easter


def test_2024_adds_epiphany_and_counts_17_days():
    days = make_holidays.holidays(2024)
    names = {name for _, name in days}
    assert {"Boboteaza", "Sfântul Ioan"} <= names
    assert len(days) == 17
    assert "Boboteaza" not in {name for _, name in make_holidays.holidays(2023)}
