"""Exact CAPTURE_DATA metadata, event, register, and raw-sample codec.

Samples are serialized exactly as supplied; this module never interpolates,
normalizes, smooths, or replaces acquisition values.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


PAYLOAD_SCHEMA_VERSION = 1
FIXED_HEADER_LENGTH = 188
SAMPLE_ENCODING_UINT16_LE = 1
TIMING_UNCALIBRATED = 0x20
EVENT_OVERFLOW = 0x40
EVENT_TIME_AMBIGUOUS = 0x80
_EVENT = struct.Struct("<BBBBiHHI")


def _fixed(value: bytes, size: int, name: str) -> bytes:
    if len(value) != size:
        raise ValueError(f"{name} must be exactly {size} bytes")
    return value


@dataclass(frozen=True, slots=True)
class CaptureEvent:
    channel: int
    edge: int
    capture_method: int
    level_after: int
    sample_index: int
    subsample_tick: int
    uncertainty_ticks: int
    frame_offset_ticks: int


@dataclass(frozen=True, slots=True)
class CaptureData:
    request_id: bytes
    schedule_id: bytes
    capture_id: bytes
    boot_id: bytes
    device_id: bytes
    profile_sha256: bytes
    device_config_crc32: int
    capture_sequence: int
    sample_interval_ticks: int
    burst_period_ticks: int
    sample_count: int
    pretrigger_count: int
    adc_bits: int
    sample_encoding: int
    vref_mv: int
    smclk_nominal_hz: int
    smclk_calibrated_hz: int
    frame_start_tick48: int
    t_trigger_offset_ticks: int
    adc0_hold_offset_ticks: int
    adc_aperture_ns: int
    trigger_to_tx_output_ns: int
    calibration_version: int
    quality_flags: int
    tuss_dev_stat: int
    out3_start_level: int
    out4_start_level: int
    register_pairs: tuple[tuple[int, int], ...]
    events: tuple[CaptureEvent, ...]
    samples: tuple[int, ...]


def _validate(capture: CaptureData) -> None:
    for name in ("request_id", "schedule_id", "capture_id", "boot_id", "device_id"):
        _fixed(getattr(capture, name), 16, name)
    _fixed(capture.profile_sha256, 32, "profile_sha256")
    if capture.sample_count != len(capture.samples):
        raise ValueError("sample_count does not match samples")
    if not 0 <= capture.pretrigger_count < capture.sample_count:
        raise ValueError("pretrigger_count does not match sample range")
    if capture.adc_bits != 12:
        raise ValueError("adc_bits must be 12")
    if capture.sample_encoding != SAMPLE_ENCODING_UINT16_LE:
        raise ValueError("sample_encoding must be uint16 little-endian")
    if capture.frame_start_tick48 >> 48:
        raise ValueError("frame_start_tick48 has non-zero upper bits")
    if len(capture.register_pairs) > 10 or len(capture.events) > 17:
        raise ValueError("register or event count exceeds first-version maximum")
    previous_address = -1
    for address, value in capture.register_pairs:
        if address <= previous_address or not 0 <= address <= 0x3F or not 0 <= value <= 0xFF:
            raise ValueError("register pairs must be ordered valid bytes")
        previous_address = address
    if any(not 0 <= sample <= 0xFFFF for sample in capture.samples):
        raise ValueError("sample is outside uint16 range")
    for event in capture.events:
        if event.channel not in (3, 4) or event.edge not in (1, 2):
            raise ValueError("event channel or edge is invalid")
        if event.capture_method not in (1, 2) or event.level_after not in (0, 1):
            raise ValueError("event capture method or level is invalid")
        if not 0 <= event.subsample_tick < capture.sample_interval_ticks:
            raise ValueError("event subsample_tick is outside sample interval")


def encode_capture_data(capture: CaptureData) -> bytes:
    _validate(capture)
    data = bytearray(struct.pack("<HH", PAYLOAD_SCHEMA_VERSION, FIXED_HEADER_LENGTH))
    for name in ("request_id", "schedule_id", "capture_id", "boot_id", "device_id"):
        data.extend(getattr(capture, name))
    data.extend(capture.profile_sha256)
    data.extend(struct.pack("<II", capture.device_config_crc32, capture.capture_sequence))
    data.extend(struct.pack("<HH", capture.sample_interval_ticks, capture.burst_period_ticks))
    data.extend(struct.pack("<HH", capture.sample_count, capture.pretrigger_count))
    data.extend(struct.pack("<BBH", capture.adc_bits, capture.sample_encoding, capture.vref_mv))
    data.extend(struct.pack("<II", capture.smclk_nominal_hz, capture.smclk_calibrated_hz))
    data.extend(struct.pack("<Q", capture.frame_start_tick48))
    data.extend(struct.pack("<Ii", capture.t_trigger_offset_ticks, capture.adc0_hold_offset_ticks))
    data.extend(
        struct.pack(
            "<IIII",
            capture.adc_aperture_ns,
            capture.trigger_to_tx_output_ns,
            capture.calibration_version,
            capture.quality_flags,
        )
    )
    data.extend(
        struct.pack(
            "<BBBBB3x",
            capture.tuss_dev_stat,
            capture.out3_start_level,
            capture.out4_start_level,
            len(capture.events),
            len(capture.register_pairs),
        )
    )
    data.extend(struct.pack("<I", len(capture.samples) * 2))
    if len(data) != FIXED_HEADER_LENGTH:
        raise AssertionError("CAPTURE_DATA fixed header encoder has the wrong size")
    data.extend(bytes(value for pair in capture.register_pairs for value in pair))
    for event in capture.events:
        data.extend(
            _EVENT.pack(
                event.channel,
                event.edge,
                event.capture_method,
                event.level_after,
                event.sample_index,
                event.subsample_tick,
                event.uncertainty_ticks,
                event.frame_offset_ticks,
            )
        )
    if capture.samples:
        data.extend(struct.pack(f"<{len(capture.samples)}H", *capture.samples))
    return bytes(data)


def decode_capture_data(data: bytes) -> CaptureData:
    if len(data) < FIXED_HEADER_LENGTH:
        raise ValueError("CAPTURE_DATA payload is truncated")
    schema_version, fixed_length = struct.unpack_from("<HH", data)
    if schema_version != PAYLOAD_SCHEMA_VERSION or fixed_length != FIXED_HEADER_LENGTH:
        raise ValueError("CAPTURE_DATA schema version or fixed header length is invalid")
    offset = 4

    def take(size: int) -> bytes:
        nonlocal offset
        value = data[offset : offset + size]
        if len(value) != size:
            raise ValueError("CAPTURE_DATA payload is truncated")
        offset += size
        return value

    identifiers = tuple(take(16) for _ in range(5))
    profile_hash = take(32)
    config_crc, capture_sequence = struct.unpack("<II", take(8))
    sample_interval, burst_period = struct.unpack("<HH", take(4))
    sample_count, pretrigger_count = struct.unpack("<HH", take(4))
    adc_bits, sample_encoding, vref_mv = struct.unpack("<BBH", take(4))
    smclk_nominal, smclk_calibrated = struct.unpack("<II", take(8))
    frame_start = struct.unpack("<Q", take(8))[0]
    trigger_offset, adc0_offset = struct.unpack("<Ii", take(8))
    aperture, tx_delay, calibration, quality = struct.unpack("<IIII", take(16))
    status, out3, out4, event_count, register_count, reserved = struct.unpack(
        "<BBBBB3s", take(8)
    )
    if reserved != bytes(3):
        raise ValueError("CAPTURE_DATA reserved bytes must be zero")
    sample_bytes = struct.unpack("<I", take(4))[0]
    if offset != FIXED_HEADER_LENGTH:
        raise AssertionError("CAPTURE_DATA fixed header decoder has the wrong size")
    expected_length = fixed_length + register_count * 2 + event_count * 16 + sample_bytes
    if len(data) != expected_length or sample_bytes != sample_count * 2:
        raise ValueError("CAPTURE_DATA counts do not match payload length")
    pairs = tuple((take(1)[0], take(1)[0]) for _ in range(register_count))
    events = tuple(CaptureEvent(*_EVENT.unpack(take(16))) for _ in range(event_count))
    sample_data = take(sample_bytes)
    samples = struct.unpack(f"<{sample_count}H", sample_data) if sample_count else ()
    capture = CaptureData(
        request_id=identifiers[0],
        schedule_id=identifiers[1],
        capture_id=identifiers[2],
        boot_id=identifiers[3],
        device_id=identifiers[4],
        profile_sha256=profile_hash,
        device_config_crc32=config_crc,
        capture_sequence=capture_sequence,
        sample_interval_ticks=sample_interval,
        burst_period_ticks=burst_period,
        sample_count=sample_count,
        pretrigger_count=pretrigger_count,
        adc_bits=adc_bits,
        sample_encoding=sample_encoding,
        vref_mv=vref_mv,
        smclk_nominal_hz=smclk_nominal,
        smclk_calibrated_hz=smclk_calibrated,
        frame_start_tick48=frame_start,
        t_trigger_offset_ticks=trigger_offset,
        adc0_hold_offset_ticks=adc0_offset,
        adc_aperture_ns=aperture,
        trigger_to_tx_output_ns=tx_delay,
        calibration_version=calibration,
        quality_flags=quality,
        tuss_dev_stat=status,
        out3_start_level=out3,
        out4_start_level=out4,
        register_pairs=pairs,
        events=events,
        samples=tuple(samples),
    )
    _validate(capture)
    return capture
