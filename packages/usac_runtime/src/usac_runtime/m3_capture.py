"""Windows M3 one-shot workflow and lossless artifact writer.

This module performs only the fixed d10x4_v1 acceptance sequence: verified
configuration, no-Burst IO2 loopback, then one authorized capture. It writes
the validated protocol frame and ADC words without transforming samples.
"""

from __future__ import annotations

import json
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from usac_protocol.capture_data import (
    TIMING_UNCALIBRATED,
    CaptureData,
    decode_capture_data,
)
from usac_protocol.config_v2 import AcquisitionConfigV2, D10X4_REGISTER_PAIRS
from usac_protocol.frame import (
    CRC_SIZE,
    HEADER_SIZE,
    HOST_MAX_PAYLOAD_LENGTH,
    Flags,
    Frame,
    MessageType,
    decode_frame,
    encode_frame,
)
from usac_protocol.messages import (
    CaptureOnceRequest,
    Io2LoopbackRequest,
    Io2LoopbackResult,
    decode_ack,
    decode_error,
    decode_io2_loopback_result,
    encode_capture_once_request,
    encode_io2_loopback_request,
)
from usac_runtime.m2_smoke import M2SmokeResult, _read_exact, _write_all, run_m2_smoke
from usac_runtime.serial import SerialConnection


@dataclass(frozen=True, slots=True)
class M3CaptureResult:
    smoke: M2SmokeResult
    loopback: Io2LoopbackResult
    capture: CaptureData
    raw_frame_path: Path
    metadata_path: Path
    samples_path: Path


@dataclass(frozen=True, slots=True)
class M3LoopbackResult:
    smoke: M2SmokeResult
    loopback: Io2LoopbackResult


@dataclass(frozen=True, slots=True)
class M3CaptureProgress:
    """Observation-only evidence for locating a host capture failure."""

    stage: str
    received_bytes: int = 0
    expected_bytes: int | None = None


M3ProgressCallback = Callable[[M3CaptureProgress], None]
M3_CAPTURE_READ_CHUNK_SIZE = 256


def _read_raw_frame(connection: SerialConnection, *, timeout_s: float) -> tuple[Frame, bytes]:
    header = _read_exact(connection, HEADER_SIZE, timeout_s=timeout_s)
    payload_length = struct.unpack_from("<I", header, 12)[0]
    if payload_length > HOST_MAX_PAYLOAD_LENGTH:
        raise RuntimeError(f"device response payload is too large: {payload_length}")
    raw = header + _read_exact(
        connection, payload_length + CRC_SIZE, timeout_s=timeout_s
    )
    return decode_frame(raw), raw


def _read_capture_frame(
    connection: SerialConnection,
    *,
    timeout_s: float,
    progress: M3ProgressCallback,
) -> tuple[Frame, bytes]:
    """Read CAPTURE_DATA while exposing only frame-level byte progress."""

    deadline = time.monotonic() + timeout_s
    header_buffer = bytearray()
    while len(header_buffer) < HEADER_SIZE:
        chunk = connection.read(HEADER_SIZE - len(header_buffer))
        if chunk:
            header_buffer.extend(chunk)
            deadline = time.monotonic() + timeout_s
            if len(header_buffer) < HEADER_SIZE:
                progress(
                    M3CaptureProgress(
                        "capture_data_receiving", len(header_buffer), None
                    )
                )
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"serial response timed out at {len(header_buffer)} of {HEADER_SIZE} bytes"
            )
    header = bytes(header_buffer)
    payload_length = struct.unpack_from("<I", header, 12)[0]
    if payload_length > HOST_MAX_PAYLOAD_LENGTH:
        raise RuntimeError(f"device response payload is too large: {payload_length}")
    expected_bytes = HEADER_SIZE + payload_length + CRC_SIZE
    progress(M3CaptureProgress("capture_data_header_received", HEADER_SIZE, expected_bytes))

    deadline = time.monotonic() + timeout_s
    remainder_size = payload_length + CRC_SIZE
    remainder = bytearray()
    while len(remainder) < remainder_size:
        # A CAPTURE_DATA frame is intentionally streamed in small USB CDC
        # segments. Bound each host read so progress can refresh the idle
        # deadline instead of one 4 KiB read consuming the entire time budget.
        requested = min(
            remainder_size - len(remainder), M3_CAPTURE_READ_CHUNK_SIZE
        )
        chunk = connection.read(requested)
        if chunk:
            remainder.extend(chunk)
            deadline = time.monotonic() + timeout_s
            progress(
                M3CaptureProgress(
                    "capture_data_receiving",
                    HEADER_SIZE + len(remainder),
                    expected_bytes,
                )
            )
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"serial response timed out at {len(remainder)} of {remainder_size} bytes"
            )
    raw = header + bytes(remainder)
    return decode_frame(raw), raw


def _require_response(frame: Frame, *, sequence: int) -> None:
    if frame.sequence != sequence or frame.flags != Flags.RESPONSE:
        raise RuntimeError("device response sequence or flags are invalid")
    if frame.message_type is MessageType.ERROR:
        error = decode_error(frame.payload)
        raise RuntimeError(
            f"device ERROR {error.error_code} for type 0x{error.failed_type:02X} "
            f"(detail0={error.detail_arg0}, detail1={error.detail_arg1})"
        )


def _fixed_d10x4() -> AcquisitionConfigV2:
    return AcquisitionConfigV2.create(
        sample_interval_ticks=120,
        sample_count=2048,
        pretrigger_count=64,
        adc_bits=12,
        aux_flags=0,
        vref_mv=3300,
        burst_period_ticks=50,
        register_pairs=D10X4_REGISTER_PAIRS,
    )


def _validate_identifier(value: bytes, name: str) -> None:
    if len(value) != 16:
        raise ValueError(f"{name} must be exactly 16 bytes")


def run_m3_loopback(
    connection: SerialConnection,
    *,
    host_nonce: bytes,
    set_config_request_id: bytes,
    loopback_request_id: bytes,
    timeout_s: float = 3.0,
) -> M3LoopbackResult:
    """Apply the fixed profile and return IO2 timing evidence without capture."""

    for value, name in (
        (host_nonce, "host_nonce"),
        (set_config_request_id, "set_config_request_id"),
        (loopback_request_id, "loopback_request_id"),
    ):
        _validate_identifier(value, name)

    smoke = run_m2_smoke(
        connection,
        host_nonce=host_nonce,
        apply_same_config=True,
        request_id=set_config_request_id,
        timeout_s=timeout_s,
    )
    expected_config = _fixed_d10x4()
    if smoke.config != expected_config:
        raise RuntimeError("M3 requires the exact d10x4_v1 fixed configuration")

    loopback_sequence = 4
    loopback_request = Frame(
        MessageType.RUN_IO2_LOOPBACK_TEST,
        loopback_sequence,
        encode_io2_loopback_request(
            Io2LoopbackRequest(
                loopback_request_id,
                expected_config.profile_sha256,
                expected_config.device_config_crc32,
                8,
            )
        ),
    )
    _write_all(connection, encode_frame(loopback_request))
    loopback_frame, _ = _read_raw_frame(connection, timeout_s=timeout_s)
    _require_response(loopback_frame, sequence=loopback_sequence)
    if loopback_frame.message_type is not MessageType.RUN_IO2_LOOPBACK_TEST:
        raise RuntimeError("device did not return IO2 loopback evidence")
    loopback = decode_io2_loopback_result(loopback_frame.payload)
    if (
        loopback.request_id != loopback_request_id
        or loopback.profile_sha256 != expected_config.profile_sha256
        or loopback.device_config_crc32 != expected_config.device_config_crc32
        or loopback.result_flags != 1
        or loopback.captured_edges != 8
        or loopback.minimum_interval_ticks < 49
        or loopback.maximum_interval_ticks > 51
        or loopback.final_io2_level != 1
    ):
        raise RuntimeError(
            "IO2 loopback did not satisfy the fixed M3 gate: "
            f"result_flags=0x{loopback.result_flags:02x}, "
            f"captured_edges={loopback.captured_edges}, "
            f"interval_ticks={loopback.minimum_interval_ticks}.."
            f"{loopback.maximum_interval_ticks}, "
            f"capture_ticks={loopback.capture_ticks}, "
            f"final_io2_level={loopback.final_io2_level}, "
            f"pre_dev_stat=0x{loopback.pre_dev_stat:02x}, "
            f"post_dev_stat=0x{loopback.post_dev_stat:02x}"
        )
    return M3LoopbackResult(smoke, loopback)


def run_m3_capture(
    connection: SerialConnection,
    *,
    host_nonce: bytes,
    set_config_request_id: bytes,
    loopback_request_id: bytes,
    capture_request_id: bytes,
    output_directory: Path,
    timeout_s: float = 3.0,
    progress: M3ProgressCallback | None = None,
) -> M3CaptureResult:
    """Run one fixed M3 transaction and persist its unmodified data products."""

    last_progress: M3CaptureProgress | None = None

    def emit(event: M3CaptureProgress) -> None:
        nonlocal last_progress
        last_progress = event
        if progress is not None:
            try:
                progress(event)
            except Exception:
                # Diagnostics are observation-only. A broken stderr/log sink
                # must never alter a single-use hardware transaction.
                pass

    try:
        _validate_identifier(capture_request_id, "capture_request_id")
        loopback_result = run_m3_loopback(
            connection,
            host_nonce=host_nonce,
            set_config_request_id=set_config_request_id,
            loopback_request_id=loopback_request_id,
            timeout_s=timeout_s,
        )
        emit(M3CaptureProgress("loopback_passed"))
        return _run_authorized_capture(
            connection,
            loopback_result=loopback_result,
            capture_request_id=capture_request_id,
            output_directory=output_directory,
            timeout_s=timeout_s,
            progress=emit,
        )
    except Exception as error:
        if (progress is not None) and (last_progress is not None):
            detail = (
                f"M3 capture last_stage={last_progress.stage}, "
                f"received_bytes={last_progress.received_bytes}"
            )
            if last_progress.expected_bytes is not None:
                detail += f", expected_bytes={last_progress.expected_bytes}"
            error.add_note(detail)
        raise


def _run_authorized_capture(
    connection: SerialConnection,
    *,
    loopback_result: M3LoopbackResult,
    capture_request_id: bytes,
    output_directory: Path,
    timeout_s: float,
    progress: M3ProgressCallback,
) -> M3CaptureResult:
    """Execute the single-use capture after the loopback gate has passed."""

    smoke = loopback_result.smoke
    loopback = loopback_result.loopback
    expected_config = _fixed_d10x4()

    capture_sequence = 5
    capture_request = Frame(
        MessageType.CAPTURE_ONCE,
        capture_sequence,
        encode_capture_once_request(
            CaptureOnceRequest(
                capture_request_id,
                expected_config.profile_sha256,
                expected_config.device_config_crc32,
                0,
                0,
            )
        ),
    )
    _write_all(connection, encode_frame(capture_request))
    progress(M3CaptureProgress("capture_once_sent"))
    ack_frame, _ = _read_raw_frame(connection, timeout_s=timeout_s)
    _require_response(ack_frame, sequence=capture_sequence)
    if ack_frame.message_type is not MessageType.ACK:
        raise RuntimeError("device did not ACK CAPTURE_ONCE")
    ack = decode_ack(ack_frame.payload)
    if (
        ack.request_id != capture_request_id
        or ack.acked_type != MessageType.CAPTURE_ONCE
        or ack.device_config_crc32 != expected_config.device_config_crc32
    ):
        raise RuntimeError("CAPTURE_ONCE ACK does not match the request/config")
    progress(M3CaptureProgress("capture_ack_received"))

    capture_frame, raw_capture_frame = _read_capture_frame(
        connection, timeout_s=timeout_s, progress=progress
    )
    _require_response(capture_frame, sequence=capture_sequence)
    if capture_frame.message_type is not MessageType.CAPTURE_DATA:
        raise RuntimeError("device did not return CAPTURE_DATA")
    capture = decode_capture_data(capture_frame.payload)
    if (
        capture.request_id != capture_request_id
        or capture.boot_id != smoke.boot_id
        or capture.device_id != smoke.device_id
        or capture.profile_sha256 != expected_config.profile_sha256
        or capture.device_config_crc32 != expected_config.device_config_crc32
        or capture.sample_interval_ticks != 120
        or capture.burst_period_ticks != 50
        or capture.sample_count != 2048
        or capture.pretrigger_count != 64
        or len(capture.samples) != 2048
    ):
        raise RuntimeError("CAPTURE_DATA does not match the fixed M3 contract")
    if not capture.quality_flags & TIMING_UNCALIBRATED:
        raise RuntimeError("uncalibrated M3 frame is missing TIMING_UNCALIBRATED")

    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    prefix = capture.capture_id.hex()
    raw_path = output_directory / f"{prefix}.usac"
    metadata_path = output_directory / f"{prefix}.json"
    samples_path = output_directory / f"{prefix}.u16le"
    raw_path.write_bytes(raw_capture_frame)
    samples_path.write_bytes(struct.pack("<2048H", *capture.samples))
    metadata = {
        "capture_id": prefix,
        "device_id": capture.device_id.hex(),
        "boot_id": capture.boot_id.hex(),
        "request_id": capture.request_id.hex(),
        "profile_sha256": capture.profile_sha256.hex(),
        "device_config_crc32": capture.device_config_crc32,
        "sample_count": capture.sample_count,
        "pretrigger_count": capture.pretrigger_count,
        "sample_interval_ticks": capture.sample_interval_ticks,
        "burst_period_ticks": capture.burst_period_ticks,
        "smclk_nominal_hz": capture.smclk_nominal_hz,
        "smclk_calibrated_hz": capture.smclk_calibrated_hz,
        "quality_flags": capture.quality_flags,
        "interpolated": False,
        "register_pairs": [list(pair) for pair in capture.register_pairs],
        "loopback": {
            "request_id": loopback.request_id.hex(),
            "profile_sha256": loopback.profile_sha256.hex(),
            "device_config_crc32": loopback.device_config_crc32,
            "burst_period_ticks": loopback.burst_period_ticks,
            "captured_edges": loopback.captured_edges,
            "result_flags": loopback.result_flags,
            "capture_ticks": list(loopback.capture_ticks),
            "minimum_interval_ticks": loopback.minimum_interval_ticks,
            "maximum_interval_ticks": loopback.maximum_interval_ticks,
            "pre_spi_status": loopback.pre_spi_status,
            "pre_dev_stat": loopback.pre_dev_stat,
            "pre_tof_config": loopback.pre_tof_config,
            "pre_vdrv_ctrl": loopback.pre_vdrv_ctrl,
            "post_spi_status": loopback.post_spi_status,
            "post_dev_stat": loopback.post_dev_stat,
            "post_tof_config": loopback.post_tof_config,
            "post_vdrv_ctrl": loopback.post_vdrv_ctrl,
            "final_io2_level": loopback.final_io2_level,
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    progress(
        M3CaptureProgress(
            "artifacts_saved", len(raw_capture_frame), len(raw_capture_frame)
        )
    )
    return M3CaptureResult(
        smoke, loopback, capture, raw_path, metadata_path, samples_path
    )
