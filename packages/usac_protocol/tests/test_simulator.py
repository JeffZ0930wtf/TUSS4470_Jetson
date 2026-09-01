from __future__ import annotations

import pytest

from usac_protocol.capture_data import decode_capture_data
from usac_protocol.config_v2 import D10X4_REGISTER_PAIRS, AcquisitionConfigV2
from usac_protocol.frame import Flags, Frame, MessageType
from usac_protocol.messages import (
    CaptureOnceRequest,
    HelloRequest,
    RenewPeriodicLease,
    SetConfigRequest,
    StartPeriodicRequest,
    StopRequest,
    decode_ack,
    decode_capabilities_response,
    decode_hello_response,
    decode_renew_periodic_lease,
    decode_status_response,
    encode_capture_once_request,
    encode_hello_request,
    encode_renew_periodic_lease,
    encode_set_config_request,
    encode_start_periodic_request,
    encode_stop_request,
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


def establish_session(device: SimulatedDevice, current: AcquisitionConfigV2) -> None:
    """Put the deterministic device into the same configured state as a host would."""

    device.handle(
        Frame(
            MessageType.HELLO,
            1,
            encode_hello_request(HelloRequest(bytes(range(16)), 1, 1)),
        )
    )
    device.handle(
        Frame(
            MessageType.SET_CONFIG,
            2,
            encode_set_config_request(
                SetConfigRequest(bytes(range(16, 32)), bytes(32), current)
            ),
        )
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


def test_simulator_reports_first_version_capabilities_and_applied_status() -> None:
    device = SimulatedDevice()
    current = AcquisitionConfigV2.create(
        sample_interval_ticks=731,
        sample_count=2048,
        pretrigger_count=64,
        adc_bits=12,
        aux_flags=3,
        vref_mv=3300,
        burst_period_ticks=347,
        register_pairs=D10X4_REGISTER_PAIRS,
    )
    establish_session(device, current)

    capabilities_frame = device.handle(Frame(MessageType.GET_CAPABILITIES, 3, b""))[0]
    capabilities = decode_capabilities_response(capabilities_frame.payload)
    status_frame = device.handle(Frame(MessageType.GET_STATUS, 4, b""))[0]
    status = decode_status_response(status_frame.payload)

    assert capabilities_frame.flags == Flags.RESPONSE
    assert capabilities.capability_flags == 0x7F
    assert capabilities.supported_io_modes == 0x0F
    assert (capabilities.min_sample_interval_ticks, capabilities.max_sample_interval_ticks) == (
        120,
        960,
    )
    assert (capabilities.min_burst_period_ticks, capabilities.max_burst_period_ticks) == (
        24,
        800,
    )
    assert status.profile_sha256 == current.profile_sha256
    assert status.device_config_crc32 == current.device_config_crc32
    assert (status.out3_enabled, status.out4_enabled) == (1, 1)
    assert status.active_schedule_id == bytes(16)


def test_simulator_preserves_adjustable_ticks_and_emits_separate_aux_events() -> None:
    device = SimulatedDevice()
    current = AcquisitionConfigV2.create(
        sample_interval_ticks=731,
        sample_count=2048,
        pretrigger_count=64,
        adc_bits=12,
        aux_flags=3,
        vref_mv=3300,
        burst_period_ticks=347,
        register_pairs=D10X4_REGISTER_PAIRS,
    )
    establish_session(device, current)
    request_id = bytes(range(64, 80))

    frames = device.handle(
        Frame(
            MessageType.CAPTURE_ONCE,
            3,
            encode_capture_once_request(
                CaptureOnceRequest(
                    request_id,
                    current.profile_sha256,
                    current.device_config_crc32,
                    0,
                    0,
                )
            ),
        )
    )
    capture = decode_capture_data(frames[1].payload)

    assert capture.sample_interval_ticks == 731
    assert capture.burst_period_ticks == 347
    assert len(capture.samples) == 2048
    assert [(event.channel, event.sample_index) for event in capture.events] == [
        (3, 96),
        (4, 128),
    ]
    assert capture.samples[:4] == (211, 248, 285, 322)


def test_simulator_runs_finite_periodic_schedule_and_stops_after_count() -> None:
    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    current = config()
    establish_session(device, current)
    request_id = bytes(range(32, 48))
    schedule_id = bytes(range(48, 64))
    start = StartPeriodicRequest(
        request_id,
        schedule_id,
        current.profile_sha256,
        current.device_config_crc32,
        100_000,
        2,
        1_000,
    )

    response = device.handle(
        Frame(MessageType.START_PERIODIC, 3, encode_start_periodic_request(start))
    )
    assert decode_ack(response[0].payload).acked_type == MessageType.START_PERIODIC
    assert device.poll() == []

    now_us[0] = 100_000
    first = device.poll()
    now_us[0] = 200_000
    second = device.poll()

    assert len(first) == len(second) == 1
    assert first[0].flags == Flags.ASYNC
    assert first[0].sequence == 1
    assert second[0].sequence == 2
    assert decode_capture_data(first[0].payload).schedule_id == schedule_id
    status = decode_status_response(
        device.handle(Frame(MessageType.GET_STATUS, 4, b""))[0].payload
    )
    assert status.active_schedule_id == bytes(16)


def test_simulator_renews_and_expires_unattended_periodic_schedule() -> None:
    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    current = config()
    establish_session(device, current)
    schedule_id = bytes(range(48, 64))
    device.handle(
        Frame(
            MessageType.START_PERIODIC,
            3,
            encode_start_periodic_request(
                StartPeriodicRequest(
                    bytes(range(32, 48)),
                    schedule_id,
                    current.profile_sha256,
                    current.device_config_crc32,
                    100_000,
                    0,
                    1_000,
                )
            ),
        )
    )
    assert device.boot_id is not None
    now_us[0] = 900_000
    renewal = RenewPeriodicLease(device.boot_id, schedule_id, 1, 1_000)
    renewed = device.handle(
        Frame(
            MessageType.RENEW_PERIODIC_LEASE,
            4,
            encode_renew_periodic_lease(renewal),
        )
    )[0]
    assert decode_renew_periodic_lease(renewed.payload) == renewal

    now_us[0] = 1_899_000
    assert device.poll()
    now_us[0] = 1_900_000
    assert device.poll() == []
    expired = decode_status_response(
        device.handle(Frame(MessageType.GET_STATUS, 5, b""))[0].payload
    )
    assert expired.active_schedule_id == bytes(16)
    assert expired.last_error == 18


def test_simulator_stop_is_idempotent_and_prevents_later_periodic_capture() -> None:
    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    current = config()
    establish_session(device, current)
    schedule_id = bytes(range(48, 64))
    device.handle(
        Frame(
            MessageType.START_PERIODIC,
            3,
            encode_start_periodic_request(
                StartPeriodicRequest(
                    bytes(range(32, 48)),
                    schedule_id,
                    current.profile_sha256,
                    current.device_config_crc32,
                    100_000,
                    0,
                    1_000,
                )
            ),
        )
    )
    stop = Frame(
        MessageType.STOP,
        4,
        encode_stop_request(StopRequest(bytes(range(64, 80)), schedule_id)),
    )

    first = device.handle(stop)
    repeated = device.handle(stop)
    now_us[0] = 100_000

    assert first == repeated
    assert decode_ack(first[0].payload).acked_type == MessageType.STOP
    assert device.poll() == []


def test_simulator_preserves_non_integer_millisecond_period_us() -> None:
    now_us = [0]
    device = SimulatedDevice(clock_us=lambda: now_us[0])
    current = config()
    establish_session(device, current)
    device.handle(
        Frame(
            MessageType.START_PERIODIC,
            3,
            encode_start_periodic_request(
                StartPeriodicRequest(
                    bytes(range(32, 48)),
                    bytes(range(48, 64)),
                    current.profile_sha256,
                    current.device_config_crc32,
                    100_001,
                    1,
                    1_000,
                )
            ),
        )
    )

    now_us[0] = 100_000
    assert device.poll() == []
    now_us[0] = 100_001
    assert len(device.poll()) == 1
