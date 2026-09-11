from __future__ import annotations

from pathlib import Path
import threading

from fastapi.testclient import TestClient

from usac_runtime.bridge_device_client import ReconnectableBridgeDeviceClient
from usac_runtime.core_server import (
    _parser,
    accept_replacement_bridge,
    create_bridge_api,
    create_simulator_api,
    main,
)


ROOT = Path(__file__).resolve().parents[3]


def test_core_parser_defaults_to_safe_simulator_and_keeps_v1_ports() -> None:
    args = _parser().parse_args([])

    assert args.backend == "simulator"
    assert args.port == 8000
    assert args.bridge_port == 8765


def test_simulator_server_factory_never_requires_a_serial_device(tmp_path: Path) -> None:
    api = create_simulator_api(
        schema_path=ROOT / "protocol/schema/tuss4470-parameters-v1.yaml",
        database_path=tmp_path / "captures.sqlite3",
    )

    with TestClient(api) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/api/v1/device").json()["status"]["device_state"] == 2


def test_bridge_api_starts_before_a_bridge_or_device_is_connected(tmp_path: Path) -> None:
    api = create_bridge_api(
        schema_path=ROOT / "protocol/schema/tuss4470-parameters-v1.yaml",
        database_path=tmp_path / "captures.sqlite3",
        connection=None,
        timeout_s=1.0,
    )

    with TestClient(api) as client:
        device = client.get("/api/v1/device")
        schema = client.get("/api/v1/config/schema")
        draft = client.patch(
            "/api/v1/config",
            json={"changes": {"BURST_PULSE": 2}},
        )
        validated = client.post(
            "/api/v1/config/validate",
            json={"changes": {}},
        )
        applied = client.put(
            "/api/v1/config",
            headers={"If-Match": '"' + "0" * 64 + '"'},
            json={"changes": {}},
        )
        capture = client.post(
            "/api/v1/captures",
            json={
                "expected_profile_sha256": "0" * 64,
                "expected_device_config_crc32": 0,
            },
        )
        periodic = client.post(
            "/api/v1/periodic/start",
            json={
                "expected_profile_sha256": "0" * 64,
                "expected_device_config_crc32": 0,
                "period_us": 100_000,
                "capture_count": 1,
                "lease_timeout_ms": 1_000,
            },
        )
        sweep = client.post(
            "/api/v1/sweeps",
            json={
                "expected_profile_sha256": "0" * 64,
                "expected_device_config_crc32": 0,
                "field": "BURST_PULSE",
                "values": [1],
            },
        )

    assert device.status_code == 200
    assert device.json() == {
        "connected": False,
        "health": "NOT_DETECTED",
        "activity": "IDLE",
        "backend": "BRIDGE",
        "device_id": None,
        "boot_id": None,
        "firmware": None,
        "capabilities": None,
        "status": None,
        "session_generation": 0,
        "diagnostics_observed_utc_ns": None,
    }
    assert len(schema.json()["fields"]) == 47
    assert draft.status_code == 200
    assert draft.json()["requested"]["BURST_PULSE"] == 2
    assert validated.status_code == 200
    assert applied.status_code == 503
    assert applied.json()["detail"] == "device is not connected"
    assert capture.status_code == 503
    assert periodic.status_code == 503
    assert sweep.status_code == 503


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


def test_bridge_server_starts_http_before_accepting_a_bridge(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    applications = []

    class Listener:
        def setsockopt(self, *_args) -> None:
            pass

        def bind(self, _address) -> None:
            pass

        def listen(self, _count) -> None:
            pass

        def settimeout(self, _timeout) -> None:
            pass

        def accept(self):
            calls.append(("accept", threading.current_thread().name))
            raise OSError("listener closed")

        def close(self) -> None:
            pass

    monkeypatch.setattr("usac_runtime.core_server.socket.socket", lambda *_args: Listener())
    monkeypatch.setattr(
        "usac_runtime.core_server.uvicorn.run",
        lambda application, *_args, **_kwargs: (
            applications.append(application),
            calls.append(("http", threading.current_thread().name)),
        ),
    )

    result = main(
        [
            "--backend",
            "bridge",
            "--schema",
            str(ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"),
            "--database",
            str(tmp_path / "captures.sqlite3"),
            "--host-database-path",
            "D:/Desktop/TUSS4470_data/core/acquisition.sqlite3",
        ]
    )

    assert result == 0
    assert ("http", threading.current_thread().name) in calls
    assert all(name != threading.current_thread().name for kind, name in calls if kind == "accept")
    storage_route = next(
        route for route in applications[0].routes if route.path == "/api/v1/storage"
    )
    assert storage_route.endpoint()["host_database_path"] == (
        "D:/Desktop/TUSS4470_data/core/acquisition.sqlite3"
    )
