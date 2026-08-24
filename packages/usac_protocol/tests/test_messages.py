from __future__ import annotations

from usac_protocol.config_v2 import D10X4_REGISTER_PAIRS, AcquisitionConfigV2
from usac_protocol.messages import (
    Ack,
    CaptureOnceRequest,
    ErrorResponse,
    HelloRequest,
    SetConfigRequest,
    decode_ack,
    decode_capture_once_request,
    decode_error,
    decode_hello_request,
    decode_set_config_request,
    encode_ack,
    encode_capture_once_request,
    encode_error,
    encode_hello_request,
    encode_set_config_request,
)


def config() -> AcquisitionConfigV2:
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


def test_hello_request_has_exact_20_byte_payload() -> None:
    request = HelloRequest(host_nonce=bytes(range(16)), min_version=1, max_version=1)

    encoded = encode_hello_request(request)

    assert encoded == bytes(range(16)) + bytes.fromhex("01 01 00 00")
    assert decode_hello_request(encoded) == request


def test_set_config_request_has_exact_variable_layout() -> None:
    current = config()
    request = SetConfigRequest(
        request_id=bytes(range(16)),
        expected_profile_sha256=bytes(32),
        config=current,
    )

    encoded = encode_set_config_request(request)

    assert len(encoded) == 120
    assert decode_set_config_request(encoded) == request


def test_capture_once_request_has_exact_60_byte_layout() -> None:
    current = config()
    request = CaptureOnceRequest(
        request_id=bytes(range(16)),
        expected_profile_sha256=current.profile_sha256,
        expected_device_config_crc32=current.device_config_crc32,
        trigger_source=0,
        sync_timeout_ms=0,
    )

    encoded = encode_capture_once_request(request)

    assert len(encoded) == 60
    assert decode_capture_once_request(encoded) == request


def test_ack_has_exact_24_byte_layout() -> None:
    ack = Ack(
        request_id=bytes(range(16)),
        acked_type=4,
        resulting_state=2,
        status_code=0,
        device_config_crc32=0x5D4FC286,
    )

    encoded = encode_ack(ack)

    assert len(encoded) == 24
    assert decode_ack(encoded) == ack


def test_error_utf8_length_is_explicit_and_bounded() -> None:
    error = ErrorResponse(
        request_id=bytes(range(16)),
        failed_type=5,
        current_state=1,
        error_code=25,
        detail_arg0=1,
        detail_arg1=2,
        message="unsafe burst configuration",
    )

    encoded = encode_error(error)

    assert len(encoded) == 29 + len(error.message.encode("utf-8"))
    assert decode_error(encoded) == error
