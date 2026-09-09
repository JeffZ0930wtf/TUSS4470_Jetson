from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient
import pytest

from usac_protocol.simulator import SimulatedDevice
from usac_runtime.application import AcquisitionApplication
from usac_runtime.bridge_device_client import ReconnectableBridgeDeviceClient
from usac_runtime.core_store import CaptureStore, SavePolicy
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
    assert "超声采集控制台" in page.text
    assert script.status_code == 200
    assert 'fetchJson("/api/v1/config/schema")' in script.text
    assert "BPF_HPF_FREQ" not in script.text
    assert 'id="capture-mode"' in page.text
    assert 'id="save-policy"' in page.text
    assert 'id="capture-start"' in page.text
    assert 'id="capture-stop"' in page.text
    assert 'id="periodic-fields"' in page.text
    assert 'id="trigger-fields"' in page.text
    assert 'id="periodic-trigger-hint"' in page.text
    assert 'id="sweep-fields"' in page.text
    assert 'id="periodic-start"' not in page.text
    assert 'id="sweep-start"' not in page.text
    assert 'id="baseline-button"' in page.text
    assert 'id="save-draft-button"' in page.text
    assert 'fetchJson("/api/v1/config", { method: "PATCH"' in script.text
    assert 'const RUN_PLAN_FIELDS = new Set' in script.text
    assert 'save_policy: $("#save-policy").value' in script.text
    assert 'const DEVICE_HEALTH_LABELS' in script.text
    assert 'function startCapture()' in script.text
    assert "function refreshLatestWaveform(payload)" in script.text
    assert "function loadBaseline()" in script.text
    assert 'className = "field-state"' in script.text
    assert 'id="capture-history"' in page.text
    assert 'id="history-more"' in page.text
    assert 'id="language-toggle"' in page.text
    assert 'data-i18n="app.title"' in page.text
    assert 'fetchJson(`/api/v1/captures?${query}`)' in script.text
    assert '/samples`' in script.text
    assert "const I18N =" in script.text
    assert 'localStorage.getItem("usac-language")' in script.text
    assert "function setLanguage(language)" in script.text
    assert '"device.health.normal"' in script.text
    assert '"capture.status.singleComplete"' in script.text
    assert '"history.empty"' in script.text
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


def test_device_endpoint_does_not_wait_for_sweep_executor_lock(tmp_path: Path) -> None:
    class ClosableSimulatedDeviceClient(SimulatedDeviceClient):
        def close(self) -> None:
            pass

    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    session = ClosableSimulatedDeviceClient(SimulatedDevice())
    device = ReconnectableBridgeDeviceClient(session)
    executor = SingleDeviceExecutor(service, device)
    application = AcquisitionApplication(
        service,
        executor,
        device,
        store=CaptureStore(tmp_path / "device-view.sqlite3"),
    )
    applied = application.apply_config({}, expected_etag=application.etag())
    initial = application.device()
    started = application.start_sweep(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        field_name="BPF_HPF_FREQ",
        values=(46, 47),
        loops=1,
        start_delay_ms=10_000,
        loop_delay_ms=0,
        trigger_source="SOFTWARE",
        sync_timeout_ms=0,
    )
    running = application._sessions[bytes.fromhex(started["session_id"])]
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if not executor._lock.acquire(blocking=False):
            break
        executor._lock.release()
        time.sleep(0.001)

    payload = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        query = pool.submit(application.device)
        try:
            payload = query.result(timeout=0.25)
        except FutureTimeout:
            pass
        finally:
            application.stop_sweep(started["session_id"])
            running.thread.join(timeout=1)

    assert payload is not None
    assert payload["activity"] == "SWEEPING"
    assert payload["device_id"] == initial["device_id"]
    assert payload["boot_id"] == initial["boot_id"]

    device.close()
    disconnected = application.device()
    assert disconnected["connected"] is False
    assert disconnected["device_id"] is None
    assert disconnected["boot_id"] is None
    assert disconnected["status"] is None
    assert disconnected["session_generation"] == 1


def test_first_device_query_returns_disconnected_snapshot(tmp_path: Path) -> None:
    class DisconnectsOnStatus(SimulatedDeviceClient):
        def status(self):
            raise ConnectionError("injected bridge disconnect")

        def close(self) -> None:
            pass

    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    device = ReconnectableBridgeDeviceClient(
        DisconnectsOnStatus(SimulatedDevice())
    )
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=CaptureStore(tmp_path / "first-disconnect.sqlite3"),
    )
    api = TestClient(create_api(application), raise_server_exceptions=False)

    response = api.get("/api/v1/device")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is False
    assert payload["health"] == "NOT_DETECTED"
    assert payload["session_generation"] == 1
    assert payload["device_id"] is None
    assert payload["boot_id"] is None
    assert payload["status"] is None
    assert payload["capabilities"] is None


def test_interrupted_session_remains_queryable_after_core_restart(tmp_path: Path) -> None:
    path = tmp_path / "captures.sqlite3"
    session_id = "52" * 16
    CaptureStore(path).save_session_summary(
        {
            "session_id": session_id,
            "kind": "PERIODIC",
            "state": "RUNNING",
            "save_policy": "SAVE_NONE",
            "requested_count": 10,
            "acquired_count": 3,
            "saved_count": 0,
            "discarded_by_policy_count": 3,
            "last_capture_id": None,
            "last_saved_capture_id": None,
            "terminal_reason": None,
        }
    )

    response = client(path).get(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["state"] == "INTERRUPTED"
    assert response.json()["terminal_reason"] == "CORE_RESTART"


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


def test_capture_storage_decision_is_accounted_before_bridge_confirmation(
    tmp_path: Path,
) -> None:
    class ConfirmationFails(SimulatedDeviceClient):
        def confirm_capture(self, receipt) -> None:
            raise ConnectionError("bridge disconnected before confirmation")

    path = tmp_path / "confirm-failure.sqlite3"
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    device = ConfirmationFails(SimulatedDevice())
    store = CaptureStore(path)
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    applied = application.apply_config({}, expected_etag='"' + "0" * 64 + '"')

    with pytest.raises(ConnectionError, match="before confirmation"):
        application.capture_once(
            expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
            expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
            trigger_source="SOFTWARE",
            sync_timeout_ms=0,
            save_policy=SavePolicy.SAVE_ALL,
        )

    with sqlite3.connect(path) as connection:
        raw = connection.execute(
            "SELECT summary_json FROM acquisition_sessions"
        ).fetchone()[0]
    summary = json.loads(raw)
    assert summary["state"] == "FAILED"
    assert summary["acquired_count"] == 1
    assert summary["saved_count"] == 1
    assert summary["last_saved_capture_id"] == summary["last_capture_id"]


def test_single_capture_save_none_is_transient_and_not_in_history(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()

    response = api.post(
        "/api/v1/captures",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "trigger_source": "SOFTWARE",
            "sync_timeout_ms": 0,
            "save_policy": "SAVE_NONE",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["resolution"] == "DISCARDED_BY_POLICY"
    assert payload["save_policy"] == "SAVE_NONE"
    assert payload["acquired_count"] == 1
    assert payload["saved_count"] == 0
    assert payload["discarded_by_policy_count"] == 1
    assert api.get("/api/v1/captures").json()["items"] == []
    samples = api.get(f"/api/v1/captures/{payload['capture_id']}/samples")
    assert samples.status_code == 200
    assert samples.headers["x-usac-storage"] == "TRANSIENT"
    assert len(samples.content) == 4096


def test_archived_and_transient_capture_metadata_have_the_same_contract(
    tmp_path: Path,
) -> None:
    def capture_with_policy(name: str, policy: str) -> dict[str, object]:
        api = client(tmp_path / f"{name}.sqlite3")
        applied = api.put(
            "/api/v1/config",
            headers={"If-Match": ZERO_ETAG},
            json={"changes": {}},
        ).json()
        response = api.post(
            "/api/v1/captures",
            json={
                "expected_profile_sha256": applied["actual"]["profile_sha256"],
                "expected_device_config_crc32": applied["actual"][
                    "device_config_crc32"
                ],
                "save_policy": policy,
            },
        )
        assert response.status_code == 201
        return response.json()

    archived = capture_with_policy("archived", "SAVE_ALL")
    transient = capture_with_policy("transient", "SAVE_NONE")
    for name in (
        "adc_bits",
        "sample_encoding",
        "vref_mv",
        "smclk_nominal_hz",
        "smclk_calibrated_hz",
        "frame_start_tick48",
        "t_trigger_offset_ticks",
        "adc0_hold_offset_ticks",
        "adc_aperture_ns",
        "trigger_to_tx_output_ns",
        "calibration_version",
        "out3_start_level",
        "out4_start_level",
        "quality_flags",
    ):
        assert archived[name] == transient[name]


def test_single_capture_save_last_is_archived_like_save_all(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {}},
    ).json()

    response = api.post(
        "/api/v1/captures",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "save_policy": "SAVE_LAST",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["resolution"] == "RAW_ARCHIVED"
    assert payload["save_policy"] == "SAVE_LAST"
    assert payload["saved_count"] == 1
    assert payload["discarded_by_policy_count"] == 0
    assert api.get(f"/api/v1/captures/{payload['capture_id']}").status_code == 200


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


def test_periodic_save_last_archives_only_the_final_capture(tmp_path: Path) -> None:
    database = tmp_path / "captures.sqlite3"
    api = client(database)
    applied = api.put(
        "/api/v1/config", headers={"If-Match": ZERO_ETAG}, json={"changes": {}}
    ).json()
    started = api.post(
        "/api/v1/periodic/start",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "period_us": 100_000,
            "capture_count": 3,
            "lease_timeout_ms": 1_000,
            "save_policy": "SAVE_LAST",
        },
    ).json()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sessions/{started['session_id']}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.01)

    assert session["state"] == "COMPLETED"
    assert session["acquired_count"] == 3
    assert session["saved_count"] == 1
    assert session["discarded_by_policy_count"] == 2
    assert session["last_saved_capture_id"] == session["last_capture_id"]
    history = api.get("/api/v1/captures").json()["items"]
    assert [item["capture_id"] for item in history] == [session["last_capture_id"]]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM configuration_contexts").fetchone()[0] == 0


def test_periodic_save_none_keeps_only_bounded_transient_latest(tmp_path: Path) -> None:
    database = tmp_path / "captures.sqlite3"
    api = client(database)
    applied = api.put(
        "/api/v1/config", headers={"If-Match": ZERO_ETAG}, json={"changes": {}}
    ).json()
    started = api.post(
        "/api/v1/periodic/start",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "period_us": 100_000,
            "capture_count": 3,
            "lease_timeout_ms": 1_000,
            "save_policy": "SAVE_NONE",
        },
    ).json()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sessions/{started['session_id']}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.01)

    assert session["state"] == "COMPLETED"
    assert session["acquired_count"] == 3
    assert session["saved_count"] == 0
    assert session["discarded_by_policy_count"] == 3
    assert api.get("/api/v1/captures").json()["items"] == []
    samples = api.get(f"/api/v1/captures/{session['last_capture_id']}/samples")
    assert samples.status_code == 200
    assert samples.headers["x-usac-storage"] == "TRANSIENT"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM configuration_contexts").fetchone()[0] == 0


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


def test_sweep_save_last_archives_only_the_final_step(tmp_path: Path) -> None:
    api = client(tmp_path / "captures.sqlite3")
    applied = api.put(
        "/api/v1/config", headers={"If-Match": ZERO_ETAG}, json={"changes": {}}
    ).json()
    started = api.post(
        "/api/v1/sweeps",
        json={
            "expected_profile_sha256": applied["actual"]["profile_sha256"],
            "expected_device_config_crc32": applied["actual"]["device_config_crc32"],
            "field": "BURST_PULSE",
            "values": [1, 2, 3],
            "loops": 1,
            "save_policy": "SAVE_LAST",
        },
    ).json()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        session = api.get(f"/api/v1/sweeps/{started['session_id']}").json()
        if session["state"] == "COMPLETED":
            break
        time.sleep(0.01)

    assert session["state"] == "COMPLETED"
    assert session["acquired_count"] == 3
    assert session["saved_count"] == 1
    assert session["discarded_by_policy_count"] == 2
    archived = api.get(f"/api/v1/captures/{session['last_saved_capture_id']}").json()
    assert archived["requested_config"]["BURST_PULSE"] == 3


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


def test_finished_sessions_remain_queryable_after_memory_cache_pruning(tmp_path: Path) -> None:
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

    first = api.get(f"/api/v1/sessions/{session_ids[0]}")
    second = api.get(f"/api/v1/sessions/{session_ids[1]}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["state"] == "STOPPED"
    assert second.json()["state"] == "STOPPED"
