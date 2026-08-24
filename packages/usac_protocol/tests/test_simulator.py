from __future__ import annotations

import pytest

from usac_protocol.capture_data import decode_capture_data
from usac_protocol.config_v2 import D10X4_REGISTER_PAIRS, AcquisitionConfigV2
from usac_protocol.frame import Flags, Frame, MessageType
from usac_protocol.messages import (
    CaptureOnceRequest,
    HelloRequest,
    SetConfigRequest,
    decode_ack,
    decode_hello_response,
    encode_capture_once_request,
    encode_hello_request,
    encode_set_config_request,
)
from usac_protocol.simulator import SimulatedDevice


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


def test_simulator_completes_hello_config_and_deterministic_capture() -> None:
    device = SimulatedDevice()
    nonce = bytes(range(16))
    hello = Frame(
        message_type=MessageType.HELLO,
        sequence=1,
        payload=encode_hello_request(HelloRequest(nonce, 1, 1)),
    )

    hello_responses = device.handle(hello)

    assert len(hello_responses) == 1
    assert hello_responses[0].flags == Flags.RESPONSE
    hello_response = decode_hello_response(hello_responses[0].payload)
    assert hello_response.host_nonce == nonce
    assert hello_response.device_id == device.device_id

    current = config()
    request_id = bytes(range(0x40, 0x50))
    set_config = Frame(
        message_type=MessageType.SET_CONFIG,
        sequence=2,
        payload=encode_set_config_request(
            SetConfigRequest(request_id, bytes(32), current)
        ),
    )
    set_responses = device.handle(set_config)
    assert len(set_responses) == 1
    assert decode_ack(set_responses[0].payload).device_config_crc32 == 0x5D4FC286

    capture_id = bytes(range(0x50, 0x60))
    capture_request = Frame(
        message_type=MessageType.CAPTURE_ONCE,
        sequence=3,
        payload=encode_capture_once_request(
            CaptureOnceRequest(
                request_id=capture_id,
                expected_profile_sha256=current.profile_sha256,
                expected_device_config_crc32=current.device_config_crc32,
                trigger_source=0,
                sync_timeout_ms=0,
            )
        ),
    )

    first = device.handle(capture_request)
    repeated = device.handle(capture_request)

    assert first == repeated
    assert [frame.message_type for frame in first] == [
        MessageType.ACK,
        MessageType.CAPTURE_DATA,
    ]
    capture = decode_capture_data(first[1].payload)
    assert len(capture.samples) == 2048
    assert capture.samples[:4] == (211, 248, 285, 322)
    assert capture.samples == tuple((index * 37 + 211) & 0x0FFF for index in range(2048))
    assert capture.request_id == capture_id


@pytest.mark.parametrize(
    ("address", "unsafe_value", "message"),
    [
        (0x1A, 0x00, "continuous Burst"),
        (0x1A, 0x41, "pre-driver"),
        (0x13, 0x04, "5 V VOUT"),
        (0x16, 0x50, "20 mA"),
    ],
)
def test_simulator_rejects_draft_legal_but_hardware_unsafe_config(
    address: int, unsafe_value: int, message: str
) -> None:
    device = SimulatedDevice()
    nonce = bytes(range(16))
    device.handle(
        Frame(
            MessageType.HELLO,
            1,
            encode_hello_request(HelloRequest(nonce, 1, 1)),
        )
    )
    safe = config()
    pairs = tuple(
        (pair_address, unsafe_value if pair_address == address else value)
        for pair_address, value in safe.register_pairs
    )
    unsafe = AcquisitionConfigV2.create(
        sample_interval_ticks=safe.sample_interval_ticks,
        sample_count=safe.sample_count,
        pretrigger_count=safe.pretrigger_count,
        adc_bits=safe.adc_bits,
        aux_flags=safe.aux_flags,
        vref_mv=safe.vref_mv,
        burst_period_ticks=safe.burst_period_ticks,
        register_pairs=pairs,
    )
    frame = Frame(
        MessageType.SET_CONFIG,
        2,
        encode_set_config_request(SetConfigRequest(bytes(range(16)), bytes(32), unsafe)),
    )

    with pytest.raises(ValueError, match=message):
        device.handle(frame)
