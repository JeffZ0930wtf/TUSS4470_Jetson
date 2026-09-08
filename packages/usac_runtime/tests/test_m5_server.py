from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from usac_runtime.bridge_device_client import ReconnectableBridgeDeviceClient
from usac_runtime.m5_server import accept_replacement_bridge, create_simulator_api


ROOT = Path(__file__).resolve().parents[3]


def test_simulator_server_factory_never_requires_a_serial_device(tmp_path: Path) -> None:
    api = create_simulator_api(
        schema_path=ROOT / "protocol/schema/tuss4470-parameters-v1.yaml",
        database_path=tmp_path / "captures.sqlite3",
    )

    with TestClient(api) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/api/v1/device").json()["status"]["device_state"] == 2


def test_accept_replacement_bridge_publishes_only_initialized_session() -> None:
    class Session:
        def __init__(self, label: str) -> None:
            self.label = label
            self.closed = False

        def status(self) -> str:
            return self.label

        def close(self) -> None:
            self.closed = True

    class Listener:
        def accept(self):
            return object(), ("127.0.0.1", 12345)

    old = Session("old")
    new = Session("new")
    slot = ReconnectableBridgeDeviceClient(old)
    received = []

    accept_replacement_bridge(
        Listener(),
        slot,
        client_factory=lambda connection: received.append(connection) or new,
    )

    assert len(received) == 1
    assert old.closed is True
    assert slot.status() == "new"
    assert slot.session_generation == 1
