from __future__ import annotations

from usac_protocol.config_v2 import D10X4_REGISTER_PAIRS, AcquisitionConfigV2
from usac_protocol.frame import Flags, MessageType
from usac_protocol.message_lengths import (
    flags_are_valid_for_message,
    payload_length_is_valid,
)
from usac_protocol.messages import (
    Ack,
    CaptureOnceRequest,
    ErrorResponse,
    HelloRequest,
    Io2LoopbackRequest,
    Io2LoopbackResult,
    SetConfigRequest,
    decode_ack,
    decode_capture_once_request,
    decode_error,
    decode_hello_request,
    decode_io2_loopback_request,
    decode_io2_loopback_result,
    decode_set_config_request,
    encode_ack,
    encode_capture_once_request,
    encode_error,
    encode_hello_request,
    encode_io2_loopback_request,
    encode_io2_loopback_result,
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


def test_io2_loopback_request_has_exact_56_byte_layout() -> None:
    current = config()
    request = Io2LoopbackRequest(
        request_id=bytes(range(16)),
        expected_profile_sha256=current.profile_sha256,
        expected_device_config_crc32=current.device_config_crc32,
        edge_count=8,
    )

    encoded = encode_io2_loopback_request(request)

    assert len(encoded) == 56
    assert encoded[-4:] == bytes.fromhex("08 00 00 00")
    assert decode_io2_loopback_request(encoded) == request


def test_io2_loopback_result_has_exact_86_byte_layout() -> None:
    current = config()
    result = Io2LoopbackResult(
        request_id=bytes(range(16)),
        profile_sha256=current.profile_sha256,
        device_config_crc32=current.device_config_crc32,
        burst_period_ticks=50,
        captured_edges=8,
        result_flags=1,
        capture_ticks=(100, 150, 200, 250, 300, 350, 400, 450),
        minimum_interval_ticks=50,
        maximum_interval_ticks=50,
        pre_spi_status=1,
        pre_dev_stat=2,
        pre_tof_config=3,
        pre_vdrv_ctrl=4,
        post_spi_status=5,
        post_dev_stat=6,
        post_tof_config=7,
        post_vdrv_ctrl=8,
        final_io2_level=1,
    )

    encoded = encode_io2_loopback_result(result)

    assert len(encoded) == 86
    assert encoded[-1] == 0
    assert decode_io2_loopback_result(encoded) == result


def test_io2_loopback_payloads_reject_nonzero_reserved_bytes() -> None:
    current = config()
    request = Io2LoopbackRequest(
        request_id=bytes(16),
        expected_profile_sha256=current.profile_sha256,
        expected_device_config_crc32=current.device_config_crc32,
        edge_count=8,
    )
    encoded = bytearray(encode_io2_loopback_request(request))
    encoded[-1] = 1

    try:
        decode_io2_loopback_request(bytes(encoded))
    except ValueError as error:
        assert "reserved" in str(error)
    else:
        raise AssertionError("nonzero reserved request byte was accepted")


def test_io2_loopback_frame_direction_and_lengths_are_exact() -> None:
    message_type = MessageType.RUN_IO2_LOOPBACK_TEST

    assert flags_are_valid_for_message(message_type, int(Flags.NONE))
    assert flags_are_valid_for_message(message_type, int(Flags.RESPONSE))
    assert payload_length_is_valid(message_type, int(Flags.NONE), 56)
    assert payload_length_is_valid(message_type, int(Flags.RESPONSE), 86)
    assert not payload_length_is_valid(message_type, int(Flags.NONE), 86)
    assert not payload_length_is_valid(message_type, int(Flags.RESPONSE), 56)


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
