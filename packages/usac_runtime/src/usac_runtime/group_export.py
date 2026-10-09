"""Shared, offline ZIP serialization for archived experiment groups."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile

from .core_store import CaptureRecord, CaptureStore


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _grouping_metadata(record: CaptureRecord) -> dict[str, object]:
    return {
        "group_id": record.group_id,
        "experiment_id": record.experiment_id,
        "group_name": record.group_name,
        "experiment_name": record.experiment_name,
        "cell_id": record.cell_id,
    }


def _capture_metadata(
    record: CaptureRecord,
    *,
    group: dict[str, object],
    experiment: dict[str, object],
) -> dict[str, object]:
    """Retain individual CLI metadata and add complete group export context."""

    return {
        "capture_id": record.capture_id.hex(),
        "device_id": record.device_id.hex(),
        "boot_id": record.boot_id.hex(),
        "request_id": record.request_id.hex(),
        "profile_sha256": record.profile_sha256.hex(),
        "device_config_crc32": record.device_config_crc32,
        "capture_sequence": record.capture_sequence,
        "sample_interval_ticks": record.sample_interval_ticks,
        "burst_period_ticks": record.burst_period_ticks,
        "sample_count": record.sample_count,
        "pretrigger_count": record.pretrigger_count,
        "adc_bits": record.adc_bits,
        "sample_encoding": record.sample_encoding,
        "vref_mv": record.vref_mv,
        "smclk_nominal_hz": record.smclk_nominal_hz,
        "smclk_calibrated_hz": record.smclk_calibrated_hz,
        "frame_start_tick48": record.frame_start_tick48,
        "t_trigger_offset_ticks": record.t_trigger_offset_ticks,
        "adc0_hold_offset_ticks": record.adc0_hold_offset_ticks,
        "adc_aperture_ns": record.adc_aperture_ns,
        "trigger_to_tx_output_ns": record.trigger_to_tx_output_ns,
        "calibration_version": record.calibration_version,
        "quality_flags": record.quality_flags,
        "tuss_dev_stat": record.tuss_dev_stat,
        "out3_start_level": record.out3_start_level,
        "out4_start_level": record.out4_start_level,
        "transport_crc32": record.transport_crc32,
        "requested_config": record.requested_config,
        "encoded_config": record.encoded_config,
        "readback_config": record.readback_config,
        "actual_config": record.actual_config,
        "run_plan": record.run_plan,
        "adc_clipping": record.adc_clipping,
        "interpolated": record.interpolated,
        "events": [_json_value(event) for event in record.events],
        "grouping_metadata": _grouping_metadata(record),
        "group": group,
        "experiment": experiment,
    }


def write_group_export(
    store: CaptureStore,
    group_id: str,
    output: BinaryIO,
) -> dict[str, object]:
    """Write one consistent group snapshot to an existing binary file object.

    Capture rows and their BLOBs are consumed one at a time inside the store's
    pinned snapshot. The manifest is written after capture members because its
    member ID list is only known once that cursor has been consumed.
    """

    capture_ids: list[str] = []
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        with store.group_export_snapshot(group_id) as (
            group,
            experiment,
            records,
        ):
            for record in records:
                capture_id = record.capture_id.hex()
                capture_ids.append(capture_id)
                archive.writestr(f"{capture_id}.usac", record.wire_frame)
                archive.writestr(f"{capture_id}.u16le", record.sample_blob)
                metadata = _capture_metadata(
                    record,
                    group=group,
                    experiment=experiment,
                )
                archive.writestr(
                    f"{capture_id}.json",
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                )
            manifest: dict[str, object] = {
                "experiment": experiment,
                "group": group,
                "capture_ids": capture_ids,
                "capture_count": len(capture_ids),
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
    return manifest
