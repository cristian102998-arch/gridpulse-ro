"""Raw landing zone on any fsspec filesystem: <root>/<source>/<dataset>/YYYY/MM/DD.json."""

from datetime import date

import fsspec


def raw_path(root: str, source: str, dataset: str, day: date) -> str:
    return f"{root.rstrip('/')}/{source}/{dataset}/{day:%Y/%m/%d}.json"


def write_raw(root: str, source: str, dataset: str, day: date, body: str) -> str:
    path = raw_path(root, source, dataset, day)
    with fsspec.open(path, "w", encoding="utf-8", auto_mkdir=True) as f:
        f.write(body)
    return path
