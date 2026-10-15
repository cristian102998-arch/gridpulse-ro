from datetime import date

import fsspec

from gridpulse.raw_store import raw_path, write_raw


def test_raw_path_is_partitioned_by_day():
    assert (
        raw_path("data/raw/", "energy_charts", "public_power", date(2026, 1, 5))
        == "data/raw/energy_charts/public_power/2026/01/05.json"
    )


def test_write_raw_on_any_fsspec_filesystem():
    path = write_raw("memory://raw", "energy_charts", "public_power", date(2026, 1, 5), '{"a": 1}')
    with fsspec.open(path, "r") as f:
        assert f.read() == '{"a": 1}'
