"""Typed codecs for bounded USAC command and response payloads.

Field order and sizes mirror the machine-readable schema; these functions do
not perform transport IO or device state transitions.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .config_v2 import AcquisitionConfigV2, decode_config_v2, encode_config_v2


def _fixed_bytes(value: bytes, length: int, name: str) -> bytes:
    if len(value) != length:
        raise ValueError(f"{name} must be exactly {length} bytes")
    return value


@dataclass(frozen=True, slots=True)
class HelloRequest:
    host_nonce: bytes
    min_version: int
    max_version: int


def encode_hello_request(message: HelloRequest) -> bytes:
    nonce = _fixed_bytes(message.host_nonce, 16, "host_nonce")
    if not 0 <= message.min_version <= message.max_version <= 0xFF:
        raise ValueError("HELLO version range is invalid")
    return struct.pack("<16sBBH", nonce, message.min_version, message.max_version, 0)


def decode_hello_request(data: bytes) -> HelloRequest:
    if len(data) != 20:
        raise ValueError("HELLO request payload must be 20 bytes")
    nonce, minimum, maximum, reserved = struct.unpack("<16sBBH", data)
    if reserved:
        raise ValueError("HELLO reserved field must be zero")
    message = HelloRequest(nonce, minimum, maximum)
    encode_hello_request(message)
    return message


@dataclass(frozen=True, slots=True)
class HelloResponse:
    host_nonce: bytes
    boot_id: bytes
    device_id: bytes
    negotiated_version: int
    reset_reason: int
    fw_major: int
    fw_minor: int
    fw_patch: int
    fw_build: int
    device_state: int


_HELLO_RESPONSE = struct.Struct("<16s16s16sBBHHHIB3x")


def encode_hello_response(message: HelloResponse) -> bytes:
    return _HELLO_RESPONSE.pack(
        _fixed_bytes(message.host_nonce, 16, "host_nonce"),
        _fixed_bytes(message.boot_id, 16, "boot_id"),
        _fixed_bytes(message.device_id, 16, "device_id"),
        message.negotiated_version,
        message.reset_reason,
        message.fw_major,
        message.fw_minor,
        message.fw_patch,
        message.fw_build,
        message.device_state,
    )


def decode_hello_response(data: bytes) -> HelloResponse:
    if len(data) != _HELLO_RESPONSE.size:
        raise ValueError("HELLO response payload must be 64 bytes")
    if data[-3:] != bytes(3):
        raise ValueError("HELLO response reserved bytes must be zero")
    return HelloResponse(*_HELLO_RESPONSE.unpack(data))


@dataclass(frozen=True, slots=True)
class SetConfigRequest:
    request_id: bytes
    expected_profile_sha256: bytes
    config: AcquisitionConfigV2


def encode_set_config_request(message: SetConfigRequest) -> bytes:
    return (
        _fixed_bytes(message.request_id, 16, "request_id")
        + _fixed_bytes(message.expected_profile_sha256, 32, "expected_profile_sha256")
        + encode_config_v2(message.config)
    )


def decode_set_config_request(data: bytes) -> SetConfigRequest:
    if len(data) < 100:
        raise ValueError("SET_CONFIG payload is truncated")
    return SetConfigRequest(data[:16], data[16:48], decode_config_v2(data[48:]))


@dataclass(frozen=True, slots=True)
class CaptureOnceRequest:
    request_id: bytes
    expected_profile_sha256: bytes
    expected_device_config_crc32: int
    trigger_source: int
    sync_timeout_ms: int


_CAPTURE_ONCE = struct.Struct("<16s32sIB3xI")


def encode_capture_once_request(message: CaptureOnceRequest) -> bytes:
    if message.trigger_source not in (0, 1, 2):
        raise ValueError("trigger_source must be 0, 1, or 2")
    if message.trigger_source == 1:
        if not 1 <= message.sync_timeout_ms <= 60_000:
            raise ValueError("slave sync_timeout_ms must be in 1..60000")
    elif message.sync_timeout_ms != 0:
        raise ValueError("sync_timeout_ms must be zero unless trigger source is slave")
    return _CAPTURE_ONCE.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        _fixed_bytes(message.expected_profile_sha256, 32, "expected_profile_sha256"),
        message.expected_device_config_crc32,
        message.trigger_source,
        message.sync_timeout_ms,
    )


def decode_capture_once_request(data: bytes) -> CaptureOnceRequest:
    if len(data) != _CAPTURE_ONCE.size:
        raise ValueError("CAPTURE_ONCE payload must be 60 bytes")
    message = CaptureOnceRequest(*_CAPTURE_ONCE.unpack(data))
    encode_capture_once_request(message)
    return message


@dataclass(frozen=True, slots=True)
class Io2LoopbackRequest:
    """Request the acceptance-only IO2-to-timer-capture timing check."""

    request_id: bytes
    expected_profile_sha256: bytes
    expected_device_config_crc32: int
    edge_count: int


_IO2_LOOPBACK_REQUEST = struct.Struct("<16s32sIB3x")


def encode_io2_loopback_request(message: Io2LoopbackRequest) -> bytes:
    if message.edge_count != 8:
        raise ValueError("IO2 loopback edge_count must be 8")
    return _IO2_LOOPBACK_REQUEST.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        _fixed_bytes(message.expected_profile_sha256, 32, "expected_profile_sha256"),
        message.expected_device_config_crc32,
        message.edge_count,
    )


def decode_io2_loopback_request(data: bytes) -> Io2LoopbackRequest:
    if len(data) != _IO2_LOOPBACK_REQUEST.size:
        raise ValueError("RUN_IO2_LOOPBACK_TEST request payload must be 56 bytes")
    if data[53:56] != bytes(3):
        raise ValueError("RUN_IO2_LOOPBACK_TEST request reserved bytes must be zero")
    message = Io2LoopbackRequest(*_IO2_LOOPBACK_REQUEST.unpack(data))
    encode_io2_loopback_request(message)
    return message


@dataclass(frozen=True, slots=True)
class Io2LoopbackResult:
    """Fixed timing evidence returned without exposing platform register layout."""

    request_id: bytes
    profile_sha256: bytes
    device_config_crc32: int
    burst_period_ticks: int
    captured_edges: int
    result_flags: int
    capture_ticks: tuple[int, int, int, int, int, int, int, int]
    minimum_interval_ticks: int
    maximum_interval_ticks: int
    pre_spi_status: int
    pre_dev_stat: int
    pre_tof_config: int
    pre_vdrv_ctrl: int
    post_spi_status: int
    post_dev_stat: int
    post_tof_config: int
    post_vdrv_ctrl: int
    final_io2_level: int


_IO2_LOOPBACK_RESULT = struct.Struct("<16s32sIHBB8HHH9Bx")


def encode_io2_loopback_result(message: Io2LoopbackResult) -> bytes:
    if len(message.capture_ticks) != 8:
        raise ValueError("IO2 loopback result must contain exactly 8 capture ticks")
    if message.result_flags & ~0x3F:
        raise ValueError("IO2 loopback result has reserved result flag bits set")
    return _IO2_LOOPBACK_RESULT.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        _fixed_bytes(message.profile_sha256, 32, "profile_sha256"),
        message.device_config_crc32,
        message.burst_period_ticks,
        message.captured_edges,
        message.result_flags,
        *message.capture_ticks,
        message.minimum_interval_ticks,
        message.maximum_interval_ticks,
        message.pre_spi_status,
        message.pre_dev_stat,
        message.pre_tof_config,
        message.pre_vdrv_ctrl,
        message.post_spi_status,
        message.post_dev_stat,
        message.post_tof_config,
        message.post_vdrv_ctrl,
        message.final_io2_level,
    )


def decode_io2_loopback_result(data: bytes) -> Io2LoopbackResult:
    if len(data) != _IO2_LOOPBACK_RESULT.size:
        raise ValueError("RUN_IO2_LOOPBACK_TEST response payload must be 86 bytes")
    if data[-1] != 0:
        raise ValueError("RUN_IO2_LOOPBACK_TEST response reserved byte must be zero")
    values = _IO2_LOOPBACK_RESULT.unpack(data)
    message = Io2LoopbackResult(
        request_id=values[0],
        profile_sha256=values[1],
        device_config_crc32=values[2],
        burst_period_ticks=values[3],
        captured_edges=values[4],
        result_flags=values[5],
        capture_ticks=tuple(values[6:14]),
        minimum_interval_ticks=values[14],
        maximum_interval_ticks=values[15],
        pre_spi_status=values[16],
        pre_dev_stat=values[17],
        pre_tof_config=values[18],
        pre_vdrv_ctrl=values[19],
        post_spi_status=values[20],
        post_dev_stat=values[21],
        post_tof_config=values[22],
        post_vdrv_ctrl=values[23],
        final_io2_level=values[24],
    )
    encode_io2_loopback_result(message)
    return message


@dataclass(frozen=True, slots=True)
class Ack:
    request_id: bytes
    acked_type: int
    resulting_state: int
    status_code: int
    device_config_crc32: int


_ACK = struct.Struct("<16sBBHI")


def encode_ack(message: Ack) -> bytes:
    if message.status_code != 0:
        raise ValueError("ACK status_code must be zero")
    return _ACK.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        message.acked_type,
        message.resulting_state,
        message.status_code,
        message.device_config_crc32,
    )


def decode_ack(data: bytes) -> Ack:
    if len(data) != _ACK.size:
        raise ValueError("ACK payload must be 24 bytes")
    message = Ack(*_ACK.unpack(data))
    encode_ack(message)
    return message


@dataclass(frozen=True, slots=True)
class ErrorResponse:
    request_id: bytes
    failed_type: int
    current_state: int
    error_code: int
    detail_arg0: int
    detail_arg1: int
    message: str


_ERROR_PREFIX = struct.Struct("<16sBBHIIB")


def encode_error(message: ErrorResponse) -> bytes:
    encoded_message = message.message.encode("utf-8")
    if len(encoded_message) > 63:
        raise ValueError("ERROR message must be at most 63 UTF-8 bytes")
    return _ERROR_PREFIX.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        message.failed_type,
        message.current_state,
        message.error_code,
        message.detail_arg0,
        message.detail_arg1,
        len(encoded_message),
    ) + encoded_message


def decode_error(data: bytes) -> ErrorResponse:
    if not _ERROR_PREFIX.size <= len(data) <= _ERROR_PREFIX.size + 63:
        raise ValueError("ERROR payload length is invalid")
    values = _ERROR_PREFIX.unpack_from(data)
    message_length = values[-1]
    if len(data) != _ERROR_PREFIX.size + message_length:
        raise ValueError("ERROR message_length does not match payload")
    try:
        text = data[_ERROR_PREFIX.size :].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("ERROR message is not valid UTF-8") from error
    return ErrorResponse(*values[:-1], text)
