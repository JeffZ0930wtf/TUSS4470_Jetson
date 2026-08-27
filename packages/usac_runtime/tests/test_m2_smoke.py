from __future__ import annotations

import hashlib

import pytest

from usac_protocol.config_v2 import (
    D10X4_REGISTER_PAIRS,
    AcquisitionConfigV2,
    encode_config_v2,
)
from usac_protocol.frame import Flags, Frame, MessageType, decode_frame, encode_frame
from usac_protocol.messages import (
    Ack,
    HelloResponse,
    decode_hello_request,
    decode_set_config_request,
    encode_ack,
    encode_hello_response,
)
from usac_runtime.m2_smoke import run_m2_smoke


def d10x4_config() -> AcquisitionConfigV2:
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


class FakeM2Connection:
    def __init__(self) -> None:
        self.pending = bytearray()
        self.requests: list[Frame] = []
        self.config = d10x4_config()
        self.device_id = bytes(range(16))

    def write(self, data: bytes) -> int:
        request = decode_frame(data)
        self.requests.append(request)
        if request.message_type is MessageType.HELLO:
            hello = decode_hello_request(request.payload)
            boot_id = hashlib.sha256(
                b"USAC-BOOT-ID-V1" + self.device_id + hello.host_nonce
            ).digest()[:16]
            payload = encode_hello_response(
                HelloResponse(
                    hello.host_nonce,
                    boot_id,
                    self.device_id,
                    1,
                    0,
                    0,
                    2,
                    0,
                    2,
                    6,
                )
            )
            response_type = MessageType.HELLO
        elif request.message_type is MessageType.GET_CONFIG:
            payload = encode_config_v2(self.config)
            response_type = MessageType.GET_CONFIG
        elif request.message_type is MessageType.SET_CONFIG:
            decoded = decode_set_config_request(request.payload)
            assert decoded.config == self.config
            payload = encode_ack(
                Ack(decoded.request_id, MessageType.SET_CONFIG, 6, 0, self.config.device_config_crc32)
            )
            response_type = MessageType.ACK
        else:
            raise AssertionError(f"smoke tool sent forbidden request {request.message_type}")
        self.pending.extend(
            encode_frame(
                Frame(response_type, request.sequence, payload, Flags.RESPONSE)
            )
        )
        return len(data)

    def read(self, size: int) -> bytes:
        if not self.pending:
            return b""
        chunk = bytes(self.pending[:size])
        del self.pending[:size]
        return chunk


def test_read_only_smoke_never_sends_capture_or_configuration() -> None:
    connection = FakeM2Connection()
    result = run_m2_smoke(connection, host_nonce=bytes(range(16)))

    assert [frame.message_type for frame in connection.requests] == [
        MessageType.HELLO,
        MessageType.GET_CONFIG,
    ]
    assert result.device_id == bytes(range(16))
    assert result.config == d10x4_config()


def test_hello_only_smoke_does_not_access_unpowered_tuss4470() -> None:
    connection = FakeM2Connection()
    result = run_m2_smoke(
        connection,
        host_nonce=bytes(range(16)),
        hello_only=True,
    )

    assert [frame.message_type for frame in connection.requests] == [MessageType.HELLO]
    assert result.config is None
    assert result.applied_same_config is False


def test_explicit_apply_same_config_only_reapplies_verified_config() -> None:
    connection = FakeM2Connection()
    result = run_m2_smoke(
        connection,
        host_nonce=bytes(range(16)),
        apply_same_config=True,
        request_id=bytes(range(16, 32)),
    )

    assert [frame.message_type for frame in connection.requests] == [
        MessageType.HELLO,
        MessageType.GET_CONFIG,
        MessageType.SET_CONFIG,
    ]
    assert result.applied_same_config is True


def test_smoke_rejects_wrong_boot_id() -> None:
    connection = FakeM2Connection()
    original_write = connection.write

    def corrupt_hello(data: bytes) -> int:
        count = original_write(data)
        request = decode_frame(data)
        if request.message_type is MessageType.HELLO:
            response = decode_frame(bytes(connection.pending))
            corrupted = bytearray(response.payload)
            corrupted[16] ^= 1
            connection.pending[:] = encode_frame(
                Frame(response.message_type, response.sequence, bytes(corrupted), response.flags)
            )
        return count

    connection.write = corrupt_hello  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="boot_id"):
        run_m2_smoke(connection, host_nonce=bytes(range(16)))
