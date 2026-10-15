"""The raw zone and backups on Azure Blob, via fsspec/adlfs. Runs against Azurite in CI."""

import os
import uuid
from datetime import date

import fsspec
import pytest

from gridpulse.backup import prune_backups
from gridpulse.raw_store import write_raw

CONN = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
pytestmark = pytest.mark.skipif(not CONN, reason="no Azure/Azurite connection string")


@pytest.fixture
def container():
    from azure.storage.blob import BlobServiceClient

    name = f"test-{uuid.uuid4().hex[:8]}"
    svc = BlobServiceClient.from_connection_string(CONN)
    svc.create_container(name)
    yield name
    svc.delete_container(name)


def test_raw_zone_on_blob(container):
    path = write_raw(
        f"abfs://{container}/raw",
        "energy_charts",
        "public_power",
        date(2026, 10, 15),
        '{"ok": true}',
    )
    assert path == f"abfs://{container}/raw/energy_charts/public_power/2026/10/15.json"
    with fsspec.open(path, "r") as f:
        assert f.read() == '{"ok": true}'


def test_prune_on_blob(container):
    fs = fsspec.filesystem("abfs")
    for name in ("2026-09-01", "2026-10-14"):
        fs.pipe(f"{container}/backups/{name}/manifest.json", b"{}")
    assert prune_backups(f"abfs://{container}", date(2026, 10, 15), 14) == ["2026-09-01"]
