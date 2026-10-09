from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile

from fastapi.testclient import TestClient

from usac_protocol.bridge_messages import BridgeCaptureDelivery
from usac_protocol.simulator import SimulatedDevice
from usac_runtime.api import create_api
from usac_runtime.application import AcquisitionApplication
from usac_runtime.bridge_device_client import ReconnectableBridgeDeviceClient
from usac_runtime.core_store import CaptureStore
from usac_runtime.device_executor import SingleDeviceExecutor
from usac_runtime.export_cli import main
from usac_runtime.parameter_service import ParameterService
from usac_runtime.simulated_device_client import SimulatedDeviceClient


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"


def _make_group(database: Path) -> tuple[CaptureStore, str, str, str]:
    store = CaptureStore(database)
    experiment = store.create_experiment(name="offline test", notes="metadata")
    group = store.create_group(
        experiment["experiment_id"], name="group one", cell_id="cell 7"
    )
    raw = bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )
    delivery = BridgeCaptureDelivery(
        connection_id=1,
        spool_record_id=2,
        source_connection_id=3,
        source_first_stream_offset=0,
        source_last_stream_offset=len(raw) - 1,
        stored_utc_ns=4,
        inner_frame=raw,
    )
    stored = store.commit_delivery(delivery)
    store.assign_capture_group([stored.receipt.capture_id], group["group_id"])
    return store, experiment["experiment_id"], group["group_id"], stored.receipt.capture_id.hex()


def _api(store: CaptureStore) -> tuple[TestClient, AcquisitionApplication]:
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    device = ReconnectableBridgeDeviceClient()
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    return TestClient(create_api(application), raise_server_exceptions=False), application


def _archive(payload: bytes) -> tuple[ZipFile, BytesIO]:
    buffer = BytesIO(payload)
    return ZipFile(buffer), buffer


def test_group_api_export_streams_exact_capture_blobs_and_full_context(
    tmp_path: Path,
) -> None:
    database = tmp_path / "group-export.sqlite3"
    store, experiment_id, group_id, capture_id = _make_group(
        database
    )
    other_group = store.create_group(
        experiment_id, name="separate group", cell_id="cell 8"
    )
    service = ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)
    device = SimulatedDeviceClient(SimulatedDevice())
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    applied = application.apply_config({}, expected_etag=application.etag())
    other_capture = application.capture_once(
        expected_profile_sha256=str(applied["actual"]["profile_sha256"]),
        expected_device_config_crc32=int(applied["actual"]["device_config_crc32"]),
        trigger_source="SOFTWARE",
        sync_timeout_ms=0,
        group_id=other_group["group_id"],
    )
    api, _application = _api(store)

    response = api.get(f"/api/v1/groups/{group_id}/export.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f"group-{group_id}.zip" in response.headers["content-disposition"]
    archive, _buffer = _archive(response.content)
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["experiment"]["experiment_id"] == experiment_id
    assert manifest["group"]["group_id"] == group_id
    assert manifest["capture_ids"] == [capture_id]
    assert manifest["capture_count"] == 1
    assert other_capture["capture_id"] not in archive.namelist()

    record = store.get_capture(bytes.fromhex(capture_id))
    assert archive.read(f"{capture_id}.usac") == record.wire_frame
    assert archive.read(f"{capture_id}.u16le") == record.sample_blob
    metadata = json.loads(archive.read(f"{capture_id}.json"))
    assert metadata["requested_config"] == record.requested_config
    assert metadata["encoded_config"] == record.encoded_config
    assert metadata["readback_config"] == record.readback_config
    assert metadata["actual_config"] == record.actual_config
    assert metadata["run_plan"] == record.run_plan
    assert isinstance(metadata["events"], list)
    assert metadata["grouping_metadata"]["group_id"] == group_id
    assert metadata["group"]["group_id"] == group_id
    assert metadata["experiment"]["experiment_id"] == experiment_id


def test_empty_group_export_and_offline_group_cli_share_zip_format(
    tmp_path: Path, capsys,
) -> None:
    database = tmp_path / "group-cli.sqlite3"
    store = CaptureStore(database)
    experiment = store.create_experiment(name="cli test")
    group = store.create_group(experiment["experiment_id"], name="empty")
    api, _application = _api(store)

    empty = api.get(f"/api/v1/groups/{group['group_id']}/export.zip")

    assert empty.status_code == 200
    empty_archive, _buffer = _archive(empty.content)
    assert empty_archive.namelist() == ["manifest.json"]
    assert json.loads(empty_archive.read("manifest.json"))["capture_count"] == 0

    _store, _experiment_id, populated_group_id, capture_id = _make_group(database)
    output = tmp_path / "group.zip"
    exit_code = main(
        [
            "group",
            "--sqlite",
            str(database),
            "--group-id",
            populated_group_id,
            "--output",
            str(output),
        ]
    )
    cli_result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert cli_result["capture_count"] == 1
    assert cli_result["output"] == str(output.resolve())
    cli_archive = ZipFile(output)
    assert cli_archive.namelist() == [
        f"{capture_id}.usac",
        f"{capture_id}.u16le",
        f"{capture_id}.json",
        "manifest.json",
    ]


def test_group_export_closes_temporary_files_after_success_and_build_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    store, _experiment_id, group_id, _capture_id = _make_group(
        tmp_path / "group-cleanup.sqlite3"
    )
    api, application = _api(store)
    opened = []
    real_temporary_file = tempfile.TemporaryFile

    def track_temporary_file(*args, **kwargs):
        handle = real_temporary_file(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(tempfile, "TemporaryFile", track_temporary_file)
    successful = api.get(f"/api/v1/groups/{group_id}/export.zip")
    assert successful.status_code == 200
    assert opened[-1].closed

    def fail_build(_group_id: str, _output) -> None:
        raise RuntimeError("injected ZIP build failure")

    monkeypatch.setattr(application, "write_group_export", fail_build)
    failed = api.get(f"/api/v1/groups/{group_id}/export.zip")
    assert failed.status_code == 500
    assert opened[-1].closed
