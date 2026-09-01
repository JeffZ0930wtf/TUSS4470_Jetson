from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from usac_runtime.m5_server import create_simulator_api


ROOT = Path(__file__).resolve().parents[3]


def test_simulator_server_factory_never_requires_a_serial_device(tmp_path: Path) -> None:
    api = create_simulator_api(
        schema_path=ROOT / "protocol/schema/tuss4470-parameters-v1.yaml",
        database_path=tmp_path / "captures.sqlite3",
    )

    with TestClient(api) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/api/v1/device").json()["status"]["device_state"] == 2
