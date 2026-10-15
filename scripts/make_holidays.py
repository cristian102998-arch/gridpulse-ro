"""Generate dbt/seeds/ro_public_holidays.csv (Codul Muncii, art. 139).

Usage: uv run python scripts/make_holidays.py 2023 2030
Orthodox Easter uses the Meeus Julian algorithm, converted to the Gregorian calendar (+13 days,
valid 1900-2099). Boboteaza and Sf. Ioan are public holidays from 2024 (Legea 52/2023).
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "ro_public_holidays.csv"


def orthodox_easter(year: int) -> date:
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return date(year, month, day + 1) + timedelta(days=13)


def holidays(year: int) -> list[tuple[date, str]]:
    easter = orthodox_easter(year)
    rows = [
        (date(year, 1, 1), "Anul Nou"),
        (date(year, 1, 2), "Anul Nou (a doua zi)"),
        (date(year, 1, 24), "Ziua Unirii Principatelor Române"),
        (easter - timedelta(days=2), "Vinerea Mare"),
        (easter, "Paștele"),
        (easter + timedelta(days=1), "Paștele (a doua zi)"),
        (date(year, 5, 1), "Ziua Muncii"),
        (date(year, 6, 1), "Ziua Copilului"),
        (easter + timedelta(days=49), "Rusaliile"),
        (easter + timedelta(days=50), "Rusaliile (a doua zi)"),
        (date(year, 8, 15), "Adormirea Maicii Domnului"),
        (date(year, 11, 30), "Sfântul Andrei"),
        (date(year, 12, 1), "Ziua Națională"),
        (date(year, 12, 25), "Crăciunul"),
        (date(year, 12, 26), "Crăciunul (a doua zi)"),
    ]
    if year >= 2024:
        rows += [(date(year, 1, 6), "Boboteaza"), (date(year, 1, 7), "Sfântul Ioan")]
    return sorted(rows)


def main(first: int, last: int) -> None:
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["holiday_date", "holiday_name"])
        for year in range(first, last + 1):
            seen = set()
            for d, name in holidays(year):
                if d not in seen:  # e.g. 1 May falling on Easter or Rusalii
                    seen.add(d)
                    w.writerow([d.isoformat(), name])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
