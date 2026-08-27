"""Transport-independent M2 HELLO/GET_CONFIG verification sequence.

The optional write reapplies only the exact configuration that was just read
and requires matching ACK identity/CRC. No code path constructs CAPTURE_ONCE.
"""

from __future__ import annotations

import hashlib
import secrets
import struct
import time
from dataclasses import dataclass

from usac_protocol.config_v2 import AcquisitionConfigV2, decode_config_v2
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
    HelloRequest,
    SetConfigRequest,
    decode_ack,
    decode_error,
    decode_hello_response,
    encode_hello_request,
    encode_set_config_request,
)
from usac_runtime.serial import SerialConnection


@dataclass(frozen=True, slots=True)
class M2SmokeResult:
    device_id: bytes
    boot_id: bytes
    firmware_version: tuple[int, int, int, int]
    device_state: int
    config: AcquisitionConfigV2 | None
    applied_same_config: bool


def _write_all(connection: SerialConnection, data: bytes) -> None:
    written = connection.write(data)
    if written != len(data):
        raise RuntimeError(f"short serial write: {written} of {len(data)} bytes")


def _read_exact(
    connection: SerialConnection,
    size: int,
    *,
    timeout_s: float,
) -> bytes:
    deadline = time.monotonic() + timeout_s
    output = bytearray()
    while len(output) < size:
        chunk = connection.read(size - len(output))
        if chunk:
            output.extend(chunk)
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError(f"serial response timed out at {len(output)} of {size} bytes")
    return bytes(output)


def _read_frame(connection: SerialConnection, *, timeout_s: float) -> Frame:
    header = _read_exact(connection, HEADER_SIZE, timeout_s=timeout_s)
    payload_length = struct.unpack_from("<I", header, 12)[0]
    if payload_length > HOST_MAX_PAYLOAD_LENGTH:
        raise RuntimeError(f"device response payload is too large: {payload_length}")
    remainder = _read_exact(
        connection,
        payload_length + CRC_SIZE,
        timeout_s=timeout_s,
    )
    return decode_frame(header + remainder)


def _exchange(
    connection: SerialConnection,
    request: Frame,
    *,
    timeout_s: float,
) -> Frame:
    _write_all(connection, encode_frame(request))
    response = _read_frame(connection, timeout_s=timeout_s)
    if response.sequence != request.sequence:
        raise RuntimeError(
            f"response sequence mismatch: {response.sequence} != {request.sequence}"
        )
    if response.flags != Flags.RESPONSE:
        raise RuntimeError(f"response flags are invalid: {response.flags!r}")
    if response.message_type is MessageType.ERROR:
        error = decode_error(response.payload)
        raise RuntimeError(
            f"device ERROR {error.error_code} for type 0x{error.failed_type:02X} "
            f"(state={error.current_state}, detail0={error.detail_arg0})"
        )
    return response


def run_m2_smoke(
    connection: SerialConnection,
    *,
    host_nonce: bytes,
    apply_same_config: bool = False,
    hello_only: bool = False,
    request_id: bytes | None = None,
    timeout_s: float = 2.0,
) -> M2SmokeResult:
    """Run HELLO/GET_CONFIG and optionally reapply that exact config.

    This M2-only function intentionally has no CAPTURE command path.
    """

    if len(host_nonce) != 16:
        raise ValueError("host_nonce must be exactly 16 bytes")
    if hello_only and apply_same_config:
        raise ValueError("hello_only and apply_same_config are mutually exclusive")
    hello_response_frame = _exchange(
        connection,
        Frame(
            MessageType.HELLO,
            1,
            encode_hello_request(HelloRequest(host_nonce, 1, 1)),
        ),
        timeout_s=timeout_s,
    )
    if hello_response_frame.message_type is not MessageType.HELLO:
        raise RuntimeError("device did not return a HELLO response")
    hello = decode_hello_response(hello_response_frame.payload)
    if hello.host_nonce != host_nonce:
        raise RuntimeError("HELLO host_nonce echo mismatch")
    expected_boot_id = hashlib.sha256(
        b"USAC-BOOT-ID-V1" + hello.device_id + host_nonce
    ).digest()[:16]
    if hello.boot_id != expected_boot_id:
        raise RuntimeError("HELLO boot_id derivation mismatch")

    config = None
    if not hello_only:
        config_response = _exchange(
            connection,
            Frame(MessageType.GET_CONFIG, 2, b""),
            timeout_s=timeout_s,
        )
        if config_response.message_type is not MessageType.GET_CONFIG:
            raise RuntimeError("device did not return GET_CONFIG")
        config = decode_config_v2(config_response.payload)

    applied = False
    if apply_same_config:
        if config is None:
            raise RuntimeError("configuration readback is unavailable")
        effective_request_id = request_id or secrets.token_bytes(16)
        if len(effective_request_id) != 16:
            raise ValueError("request_id must be exactly 16 bytes")
        set_response = _exchange(
            connection,
            Frame(
                MessageType.SET_CONFIG,
                3,
                encode_set_config_request(
                    SetConfigRequest(
                        effective_request_id,
                        config.profile_sha256,
                        config,
                    )
                ),
            ),
            timeout_s=timeout_s,
        )
        if set_response.message_type is not MessageType.ACK:
            raise RuntimeError("device did not ACK SET_CONFIG")
        ack = decode_ack(set_response.payload)
        if (
            ack.request_id != effective_request_id
            or ack.acked_type != MessageType.SET_CONFIG
            or ack.device_config_crc32 != config.device_config_crc32
        ):
            raise RuntimeError("SET_CONFIG ACK does not match the request/config")
        applied = True

    return M2SmokeResult(
        device_id=hello.device_id,
        boot_id=hello.boot_id,
        firmware_version=(
            hello.fw_major,
            hello.fw_minor,
            hello.fw_patch,
            hello.fw_build,
        ),
        device_state=hello.device_state,
        config=config,
        applied_same_config=applied,
    )
