from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from usac_protocol.simulator import SimulatedDevice
from usac_runtime.application import AcquisitionApplication
from usac_runtime.device_executor import SingleDeviceExecutor
from usac_runtime.m5_api import create_api
from usac_runtime.parameter_service import ParameterService
from usac_runtime.simulated_device_client import SimulatedDeviceClient


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"
ZERO_ETAG = '"' + "0" * 64 + '"'


def client() -> TestClient:
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    device = SimulatedDeviceClient(SimulatedDevice())
    application = AcquisitionApplication(service, SingleDeviceExecutor(service, device), device)
    return TestClient(create_api(application))


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
    assert applied.headers["etag"] == '"' + payload["actual"]["profile_sha256"] + '"'

    stale = api.put(
        "/api/v1/config",
        headers={"If-Match": ZERO_ETAG},
        json={"changes": {"BURST_PULSE": 2}},
    )
    assert stale.status_code == 409
    assert api.get("/api/v1/config").json()["requested"]["BURST_PULSE"] == 7
