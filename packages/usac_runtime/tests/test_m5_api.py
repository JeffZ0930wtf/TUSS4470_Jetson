from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from usac_protocol.simulator import SimulatedDevice
from usac_runtime.application import AcquisitionApplication
from usac_runtime.core_store import CaptureStore
from usac_runtime.device_executor import SingleDeviceExecutor
from usac_runtime.m5_api import create_api
from usac_runtime.parameter_service import ParameterService
from usac_runtime.simulated_device_client import SimulatedDeviceClient


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"
ZERO_ETAG = '"' + "0" * 64 + '"'


def client(
    sqlite_path: Path | None = None,
    *,
    session_history_limit: int = 100,
    raise_server_exceptions: bool = True,
) -> TestClient:
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    device = SimulatedDeviceClient(SimulatedDevice())
    store = CaptureStore(sqlite_path) if sqlite_path is not None else None
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
        session_history_limit=session_history_limit,
    )
    return TestClient(
        create_api(application),
        raise_server_exceptions=raise_server_exceptions,
    )


def test_schema_device_and_draft_config_share_one_application_state() -> None:
    api = client()

    health = api.get("/api/v1/health")
    device = api.get("/api/v1/device")
    schema = api.get("/api/v1/config/schema")
    config = api.get("/api/v1/config")

    assert health.json() == {"status": "ok"}
    assert device.json()["capabilities"]["supported_io_modes"] == 0x0F
    assert len(schema.json()["fields"]) == 47
    assert config.json()["state"] == "DRAFT"
    assert config.headers["etag"] == ZERO_ETAG


def test_web_console_is_served_without_hardcoded_parameter_table() -> None:
    api = client()

    page = api.get("/")
    script = api.get("/assets/m5-app.js")
    styles = api.get("/assets/m5-styles.css")

    assert page.status_code == 200
    assert "Ultrasonic acquisition console" in page.text
    assert script.status_code == 200
    assert 'fetchJson("/api/v1/config/schema")' in script.text
    assert "BPF_HPF_FREQ" not in script.text
    assert 'id="sweep-start-delay"' in page.text
    assert 'id="baseline-button"' in page.text
    assert 'id="save-draft-button"' in page.text
    assert 'fetchJson("/api/v1/config", { method: "PATCH"' in script.text
    assert 'start_delay_ms: Number($("#sweep-start-delay").value)' in script.text
    assert "function loadBaseline()" in script.text
    assert 'className = "field-state"' in script.text
    assert 'id="capture-history"' in page.text
    assert 'id="history-more"' in page.text
    assert 'fetchJson(`/api/v1/captures?${query}`)' in script.text
    assert '/samples`' in script.text
    assert styles.status_code == 200
    assert "--signal-blue" in styles.text


def test_device_endpoint_includes_session_identity_and_firmware() -> None:
    payload = client().get("/api/v1/device").json()

    assert len(payload["device_id"]) == 32
    assert len(payload["boot_id"]) == 32
    assert payload["firmware"] == {
        "major": 0,
        "minor": 1,
        "patch": 0,
        "build": 1,
    }


def test_validate_reports_field_error_without_mutating_current_config() -> None:
    api = client()

    response = api.post(
        "/api/v1/config/validate",
        json={"changes": {"PRE_DRIVER_MODE": True}},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "DRAFT"
    assert response.json()["errors"] == [
        {
            "field": "PRE_DRIVER_MODE",
            "code": "UNSUPPORTED_HARDWARE_PROFILE",
            "message": "pre-driver requires an external-driver hardware profile",
        }
    ]
    assert api.get("/api/v1/config").json()["requested"]["PRE_DRIVER_MODE"] is False


def test_patch_saves_a_shared_unsafe_draft_without_touching_hardware() -> None:
    api = client()

    saved = api.patch(
        "/api/v1/config",
        json={"changes": {"PRE_DRIVER_MODE": True, "BURST_PULSE": 0}},
    )

    assert saved.status_code == 200
    assert saved.json()["state"] == "DRAFT"
    assert saved.json()["requested"]["PRE_DRIVER_MODE"] is True
    assert saved.json()["requested"]["BURST_PULSE"] == 0
    assert api.get("/api/v1/config").json() == saved.json()


def test_put_requires_etag_then_applies_and_reads_back_semantic_changes() -> None:
    api = client()
    body = {
        "changes": {
            "IO_MODE": "io_mode_2",
            "BURST_PULSE": 7,
            "sample_interval_ticks": 731,
            "burst_period_ticks": 347,
            "out3_enabled": True,
        }
    }

    assert api.put("/api/v1/config", json=body).status_code == 428
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json=body,
    )

    assert applied.status_code == 200
    payload = applied.json()
    assert payload["state"] == "APPLIED"
    assert payload["requested"]["IO_MODE"] == "io_mode_2"
    assert payload["requested"]["BURST_PULSE"] == 7
    assert payload["readback"]["sample_interval_ticks"] == 731
    assert payload["readback"]["burst_period_ticks"] == 347
    assert payload["readback"]["fields"]["IO_MODE"] == "io_mode_2"
    assert payload["readback"]["fields"]["BURST_PULSE"] == 7
    assert payload["readback"]["fields"]["out3_enabled"] is True
    assert payload["readback"]["fields"]["requested_sample_rate_hz"] == round(24_000_000 / 731)
    assert "loops" in payload["readback"]["host_only_fields"]
    assert applied.headers["etag"] == '"' + payload["actual"]["profile_sha256"] + '"'

    stale = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {"BURST_PULSE": 2}},
    )
    assert stale.status_code == 409
    assert api.get("/api/v1/config").json()["requested"]["BURST_PULSE"] == 7


def test_capture_commits_raw_samples_context_and_events_before_success(
    tmp_path: Path,
) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {"out3_enabled": True, "out4_enabled": True}},
    ).json()

    response = api.post(
        "/api/v1/captures",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    )

    assert response.status_code == 201
    capture_id = response.json()["capture_id"]
    metadata = api.get(f"/api/v1/captures/{capture_id}")
    samples = api.get(f"/api/v1/captures/{capture_id}/samples")
    assert metadata.status_code == 200
    assert metadata.json()["sample_count"] == 2048
    assert metadata.json()["requested_config"]["out3_enabled"] is True
    assert metadata.json()["run_plan"]["trigger_source"] == "SOFTWARE"
    assert [event["channel"] for event in metadata.json()["events"]] == [3, 4]
    assert samples.status_code == 200
    assert samples.headers["content-type"] == "application/octet-stream"
    assert len(samples.content) == 4096
    assert samples.content[:8] == bytes.fromhex("d300f8001d014201")


def test_capture_requires_current_applied_identity(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")

    response = api.post(
        "/api/v1/captures",
        json={
            "expected_profile_sha256": "0" * 64,
            "expected_device_config_crc32": 0,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    )

    assert response.status_code == 409


def test_capture_maps_explicit_device_error_to_unprocessable_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_capture(self, **_kwargs):
        raise RuntimeError(
            "device ERROR 26 for type 0x05: detail0=65536, detail1=0"
        )

    monkeypatch.setattr(AcquisitionApplication, "capture_once", fail_capture)
    api = client(
        tmp_path / "captures.sqlite3",
        raise_server_exceptions=False,
    )

    response = api.post(
        "/api/v1/captures",
        json={
            "expected_profile_sha256": "0" * 64,
            "expected_device_config_crc32": 0,
            "trigger_source": "EXTERNAL_SYNC_SLAVE",
            "sync_timeout_ms": 1000,
        },
    )

    assert response.status_code == 422
    assert "device ERROR 26" in response.json()["detail"]


def test_finite_periodic_session_renews_persists_and_completes(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()

    started = api.post(
        "/api/v1/periodic/start",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "period_us": 100_000,
            "capture_count": 2,
            "lease_timeout_ms": 1_000,
        },
    )

    assert started.status_code == 202
    session_id = started.json()["session_id"]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sessions/{session_id}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.02)
    assert session["state"] == "COMPLETED"
    assert session["capture_count"] == 2
    assert len(session["capture_ids"]) == 2
    assert all(
        api.get(f"/api/v1/captures/{capture_id}").status_code == 200
        for capture_id in session["capture_ids"]
    )


def test_infinite_periodic_session_can_be_stopped_without_waiting_for_capture(
    tmp_path: Path,
) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    started = api.post(
        "/api/v1/periodic/start",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "period_us": 1_000_000,
            "capture_count": 0,
            "lease_timeout_ms": 1_000,
        },
    ).json()

    stopped = api.post(
        "/api/v1/periodic/stop",
        json={
            "session_id": started["session_id"],
            "schedule_id": started["schedule_id"],
        },
    )

    assert stopped.status_code == 200
    assert stopped.json()["state"] == "STOPPED"
    assert api.get("/api/v1/device").json()["status"]["active_schedule_id"] == "00" * 16


def test_sweep_persists_each_step_context_and_restores_baseline(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    started = api.post(
        "/api/v1/sweeps",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "field": "BURST_PULSE",
            "values": [2, 3],
            "loops": 2,
            "start_delay_ms": 0,
            "loop_delay_ms": 0,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    )

    assert started.status_code == 202
    sweep_id = started.json()["session_id"]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sweeps/{sweep_id}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.01)
    assert session["state"] == "COMPLETED"
    assert session["capture_count"] == 4
    captures = [
        api.get(f"/api/v1/captures/{capture_id}").json()
        for capture_id in session["capture_ids"]
    ]
    assert [item["requested_config"]["BURST_PULSE"] for item in captures] == [2, 2, 3, 3]
    assert all(item["readback_config"]["sample_interval_ticks"] == 120 for item in captures)
    assert [item["run_plan"]["sweep_index"] for item in captures] == [0, 0, 1, 1]
    assert api.get("/api/v1/config").json()["requested"]["BURST_PULSE"] == 1


def test_sweep_stop_interrupts_start_delay_without_capture(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    started = api.post(
        "/api/v1/sweeps",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "field": "BURST_PULSE",
            "values": [2, 3],
            "loops": 1,
            "start_delay_ms": 500,
            "loop_delay_ms": 0,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    ).json()

    stopped = api.post(f"/api/v1/sweeps/{started['session_id']}/stop")

    assert stopped.status_code == 200
    assert stopped.json()["state"] in {"STOPPING", "STOPPED"}
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sweeps/{started['session_id']}").json()
        if session["state"] == "STOPPED":
            break
        time.sleep(0.01)
    assert session["state"] == "STOPPED"
    assert session["capture_count"] == 0


def test_long_sweep_status_keeps_total_and_only_one_hundred_recent_ids(
    tmp_path: Path,
) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    started = api.post(
        "/api/v1/sweeps",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "field": "BURST_PULSE",
            "values": [1] * 105,
            "loops": 1,
            "start_delay_ms": 0,
            "loop_delay_ms": 0,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    ).json()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sessions/{started['session_id']}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.01)

    assert session["state"] == "COMPLETED"
    assert session["capture_count"] == 105
    assert len(session["capture_ids"]) == 100
    assert session["recent_capture_ids"] == session["capture_ids"]
    assert session["last_capture_id"] == session["capture_ids"][-1]


def test_capture_history_is_stably_paginated(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    capture_ids = []
    for _ in range(3):
        result = api.post(
            "/api/v1/captures",
            json={
                "expected_profile_sha256": applied["actual"]["profile_sha256"],
                "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
                "trigger_source": "SOFTWARE",
                "sync_timeout_ms": 0,
            },
        )
        capture_ids.append(result.json()["capture_id"])

    first = api.get("/api/v1/captures", params={"limit": 2})
    second = api.get(
        "/api/v1/captures",
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
    )

    assert [item["capture_id"] for item in first.json()["items"]] == capture_ids[:2]
    assert first.json()["next_cursor"] is not None
    assert [item["capture_id"] for item in second.json()["items"]] == capture_ids[2:]
    assert second.json()["next_cursor"] is None


def test_capture_history_can_be_filtered_by_session(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    started = api.post(
        "/api/v1/sweeps",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "field": "BURST_PULSE",
            "values": [1, 2],
            "loops": 1,
            "start_delay_ms": 0,
            "loop_delay_ms": 0,
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    ).json()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sessions/{started['session_id']}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.01)
    assert session["state"] == "COMPLETED"

    api.post(
        "/api/v1/captures",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
        },
    )
    page = api.get(
        "/api/v1/captures",
        params={"session_id": started["session_id"], "limit": 100},
    )

    assert page.status_code == 200
    assert [item["capture_id"] for item in page.json()["items"]] == session[
        "capture_ids"
    ]
    assert {item["session_id"] for item in page.json()["items"]} == {
        started["session_id"]
    }


def test_finished_session_cache_is_bounded(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3", session_history_limit=1)
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()
    session_ids = []
    for _ in range(2):
        started = api.post(
            "/api/v1/sweeps",
            json={
                "expected_profile_sha256": applied["actual"]["profile_sha256"],
                "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
                "field": "BURST_PULSE",
                "values": [1],
                "loops": 1,
                "start_delay_ms": 500,
                "loop_delay_ms": 0,
                "trigger_source": "SOFTWARE",
                "sync_timeout_ms": 0,
            },
        ).json()
        session_ids.append(started["session_id"])
        api.post(f"/api/v1/sweeps/{started['session_id']}/stop")
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            session = api.get(f"/api/v1/sessions/{started['session_id']}").json()
            if session["state"] == "STOPPED":
                break
            time.sleep(0.01)
        assert session["state"] == "STOPPED"

    assert api.get(f"/api/v1/sessions/{session_ids[0]}").status_code == 404
    assert api.get(f"/api/v1/sessions/{session_ids[1]}").status_code == 200
