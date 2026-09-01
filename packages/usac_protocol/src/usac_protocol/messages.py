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
class CapabilitiesResponse:
    capability_flags: int
    mcu_max_command_payload: int
    max_samples: int
    min_sample_interval_ticks: int
    max_sample_interval_ticks: int
    min_burst_period_ticks: int
    max_burst_period_ticks: int
    max_register_pairs: int
    max_out3_events: int
    max_out4_events: int
    adc_bits: int
    supported_io_modes: int


_CAPABILITIES = struct.Struct("<I6H5B3x")


def encode_capabilities_response(message: CapabilitiesResponse) -> bytes:
    if message.capability_flags & ~0x1FF:
        raise ValueError("capability_flags contains an unknown first-version bit")
    if message.min_sample_interval_ticks > message.max_sample_interval_ticks:
        raise ValueError("sample interval capability range is inverted")
    if message.min_burst_period_ticks > message.max_burst_period_ticks:
        raise ValueError("burst period capability range is inverted")
    if message.supported_io_modes & ~0x0F:
        raise ValueError("supported_io_modes contains an unknown mode bit")
    return _CAPABILITIES.pack(
        message.capability_flags,
        message.mcu_max_command_payload,
        message.max_samples,
        message.min_sample_interval_ticks,
        message.max_sample_interval_ticks,
        message.min_burst_period_ticks,
        message.max_burst_period_ticks,
        message.max_register_pairs,
        message.max_out3_events,
        message.max_out4_events,
        message.adc_bits,
        message.supported_io_modes,
    )


def decode_capabilities_response(data: bytes) -> CapabilitiesResponse:
    if len(data) != _CAPABILITIES.size:
        raise ValueError("GET_CAPABILITIES response payload must be 24 bytes")
    if data[-3:] != bytes(3):
        raise ValueError("GET_CAPABILITIES reserved bytes must be zero")
    message = CapabilitiesResponse(*_CAPABILITIES.unpack(data))
    encode_capabilities_response(message)
    return message


@dataclass(frozen=True, slots=True)
class StartPeriodicRequest:
    request_id: bytes
    schedule_id: bytes
    expected_profile_sha256: bytes
    expected_device_config_crc32: int
    period_us: int
    capture_count: int
    lease_timeout_ms: int


_START_PERIODIC = struct.Struct("<16s16s32sIIII")


def encode_start_periodic_request(message: StartPeriodicRequest) -> bytes:
    if message.schedule_id == bytes(16):
        raise ValueError("schedule_id must not be all zero")
    if not 1 <= message.period_us <= 0xFFFFFFFF:
        raise ValueError("period_us must be a positive u32")
    if not 0 <= message.capture_count <= 0xFFFFFFFF:
        raise ValueError("capture_count must be a u32")
    if not 1_000 <= message.lease_timeout_ms <= 10_000:
        raise ValueError("lease_timeout_ms must be in 1000..10000")
    return _START_PERIODIC.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        _fixed_bytes(message.schedule_id, 16, "schedule_id"),
        _fixed_bytes(message.expected_profile_sha256, 32, "expected_profile_sha256"),
        message.expected_device_config_crc32,
        message.period_us,
        message.capture_count,
        message.lease_timeout_ms,
    )


def decode_start_periodic_request(data: bytes) -> StartPeriodicRequest:
    if len(data) != _START_PERIODIC.size:
        raise ValueError("START_PERIODIC payload must be 80 bytes")
    message = StartPeriodicRequest(*_START_PERIODIC.unpack(data))
    encode_start_periodic_request(message)
    return message


@dataclass(frozen=True, slots=True)
class RenewPeriodicLease:
    """Common 40-byte lease layout; the last field is timeout or remaining time."""

    boot_id: bytes
    schedule_id: bytes
    lease_sequence: int
    lease_timeout_or_remaining_ms: int


_RENEW_PERIODIC = struct.Struct("<16s16sII")


def encode_renew_periodic_lease(message: RenewPeriodicLease) -> bytes:
    if message.boot_id == bytes(16) or message.schedule_id == bytes(16):
        raise ValueError("boot_id and schedule_id must not be all zero")
    if not 1 <= message.lease_sequence <= 0xFFFFFFFF:
        raise ValueError("lease_sequence must be in 1..u32_max")
    if not 0 <= message.lease_timeout_or_remaining_ms <= 10_000:
        raise ValueError("lease timeout/remaining value must be in 0..10000 ms")
    return _RENEW_PERIODIC.pack(
        _fixed_bytes(message.boot_id, 16, "boot_id"),
        _fixed_bytes(message.schedule_id, 16, "schedule_id"),
        message.lease_sequence,
        message.lease_timeout_or_remaining_ms,
    )


def decode_renew_periodic_lease(data: bytes) -> RenewPeriodicLease:
    if len(data) != _RENEW_PERIODIC.size:
        raise ValueError("RENEW_PERIODIC_LEASE payload must be 40 bytes")
    message = RenewPeriodicLease(*_RENEW_PERIODIC.unpack(data))
    encode_renew_periodic_lease(message)
    return message


@dataclass(frozen=True, slots=True)
class StopRequest:
    request_id: bytes
    schedule_id: bytes


_STOP = struct.Struct("<16s16s")


def encode_stop_request(message: StopRequest) -> bytes:
    return _STOP.pack(
        _fixed_bytes(message.request_id, 16, "request_id"),
        _fixed_bytes(message.schedule_id, 16, "schedule_id"),
    )


def decode_stop_request(data: bytes) -> StopRequest:
    if len(data) != _STOP.size:
        raise ValueError("STOP payload must be 32 bytes")
    return StopRequest(*_STOP.unpack(data))


@dataclass(frozen=True, slots=True)
class StatusResponse:
    boot_id: bytes
    device_state: int
    last_error: int
    profile_sha256: bytes
    device_config_crc32: int
    capture_sequence: int
    missed_capture_count: int
    quality_flags: int
    tuss_dev_stat: int
    vdrv_ready: int
    out3_enabled: int
    out4_enabled: int
    clock_fault_flags: int
    active_schedule_id: bytes
    lease_sequence: int
    lease_remaining_ms: int


_STATUS = struct.Struct("<16sBxH32sIIIIBBBBH2x16sII")


def encode_status_response(message: StatusResponse) -> bytes:
    if any(level not in (0, 1) for level in (message.vdrv_ready, message.out3_enabled, message.out4_enabled)):
        raise ValueError("status boolean fields must be 0 or 1")
    if message.clock_fault_flags & ~0x0F:
        raise ValueError("clock_fault_flags contains a reserved bit")
    if message.active_schedule_id == bytes(16) and (
        message.lease_sequence != 0 or message.lease_remaining_ms != 0
    ):
        raise ValueError("inactive schedule must report zero lease state")
    return _STATUS.pack(
        _fixed_bytes(message.boot_id, 16, "boot_id"),
        message.device_state,
        message.last_error,
        _fixed_bytes(message.profile_sha256, 32, "profile_sha256"),
        message.device_config_crc32,
        message.capture_sequence,
        message.missed_capture_count,
        message.quality_flags,
        message.tuss_dev_stat,
        message.vdrv_ready,
        message.out3_enabled,
        message.out4_enabled,
        message.clock_fault_flags,
        _fixed_bytes(message.active_schedule_id, 16, "active_schedule_id"),
        message.lease_sequence,
        message.lease_remaining_ms,
    )


def decode_status_response(data: bytes) -> StatusResponse:
    if len(data) != _STATUS.size:
        raise ValueError("GET_STATUS response payload must be 100 bytes")
    if data[17] != 0 or data[74:76] != bytes(2):
        raise ValueError("GET_STATUS reserved bytes must be zero")
    message = StatusResponse(*_STATUS.unpack(data))
    encode_status_response(message)
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
