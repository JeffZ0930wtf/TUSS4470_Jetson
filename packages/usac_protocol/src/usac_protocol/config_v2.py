"""Canonical acquisition/profile configuration shared with MSP430 firmware.

SHA-256 identifies semantic profile content, while CRC-32 detects accidental
wire corruption. Both cover the same explicitly ordered canonical bytes.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .frame import crc32_iso_hdlc


PROFILE_SCHEMA_VERSION = 2
D10X4_REGISTER_PAIRS = (
    (0x10, 0x2E),
    (0x11, 0x00),
    (0x12, 0x00),
    (0x13, 0x00),
    (0x14, 0x03),
    (0x16, 0x40),
    (0x17, 0x07),
    (0x18, 0x14),
    (0x1A, 0x01),
    (0x1B, 0x02),
)
D10X4_SHA256 = bytes.fromhex(
    "B8826EAF278D7360189D49ACED322FF9E404D8266A25E76A011065C2FDA5C998"
)
_CANONICAL_PREFIX = struct.Struct("<HHHHBHBHB")
_CONFIG_PREFIX = struct.Struct("<HHHHBBHHBB")


@dataclass(frozen=True, slots=True)
class AcquisitionConfigV2:
    profile_schema_version: int
    sample_interval_ticks: int
    sample_count: int
    pretrigger_count: int
    adc_bits: int
    aux_flags: int
    vref_mv: int
    burst_period_ticks: int
    register_pairs: tuple[tuple[int, int], ...]
    profile_sha256: bytes
    device_config_crc32: int

    @classmethod
    def create(
        cls,
        *,
        sample_interval_ticks: int,
        sample_count: int,
        pretrigger_count: int,
        adc_bits: int,
        aux_flags: int,
        vref_mv: int,
        burst_period_ticks: int,
        register_pairs: tuple[tuple[int, int], ...],
        profile_schema_version: int = PROFILE_SCHEMA_VERSION,
    ) -> AcquisitionConfigV2:
        normalized_pairs = tuple(tuple(pair) for pair in register_pairs)
        _validate_values(
            profile_schema_version=profile_schema_version,
            sample_interval_ticks=sample_interval_ticks,
            sample_count=sample_count,
            pretrigger_count=pretrigger_count,
            adc_bits=adc_bits,
            aux_flags=aux_flags,
            vref_mv=vref_mv,
            burst_period_ticks=burst_period_ticks,
            register_pairs=normalized_pairs,
        )
        unhashed = cls(
            profile_schema_version=profile_schema_version,
            sample_interval_ticks=sample_interval_ticks,
            sample_count=sample_count,
            pretrigger_count=pretrigger_count,
            adc_bits=adc_bits,
            aux_flags=aux_flags,
            vref_mv=vref_mv,
            burst_period_ticks=burst_period_ticks,
            register_pairs=normalized_pairs,
            profile_sha256=b"",
            device_config_crc32=0,
        )
        canonical = canonical_profile_bytes(unhashed)
        return cls(
            profile_schema_version=profile_schema_version,
            sample_interval_ticks=sample_interval_ticks,
            sample_count=sample_count,
            pretrigger_count=pretrigger_count,
            adc_bits=adc_bits,
            aux_flags=aux_flags,
            vref_mv=vref_mv,
            burst_period_ticks=burst_period_ticks,
            register_pairs=normalized_pairs,
            profile_sha256=hashlib.sha256(canonical).digest(),
            device_config_crc32=crc32_iso_hdlc(canonical),
        )


def _validate_values(
    *,
    profile_schema_version: int,
    sample_interval_ticks: int,
    sample_count: int,
    pretrigger_count: int,
    adc_bits: int,
    aux_flags: int,
    vref_mv: int,
    burst_period_ticks: int,
    register_pairs: tuple[tuple[int, int], ...],
) -> None:
    if profile_schema_version != PROFILE_SCHEMA_VERSION:
        raise ValueError("profile_schema_version must be 2")
    if not 120 <= sample_interval_ticks <= 960:
        raise ValueError("sample_interval_ticks must be in 120..960")
    if not 1 <= sample_count <= 2048:
        raise ValueError("sample_count must be in 1..2048")
    if not 0 <= pretrigger_count <= sample_count:
        raise ValueError("pretrigger_count must not exceed sample_count")
    if adc_bits != 12:
        raise ValueError("adc_bits must be 12")
    if aux_flags & ~0x03:
        raise ValueError("aux_flags contains reserved bits")
    if vref_mv != 3300:
        raise ValueError("vref_mv must be 3300")
    if not 24 <= burst_period_ticks <= 800:
        raise ValueError("burst_period_ticks must be in 24..800")
    if len(register_pairs) > 10:
        raise ValueError("register_count must not exceed 10")
    previous_address = -1
    for address, value in register_pairs:
        if address <= previous_address:
            raise ValueError("register addresses must be strictly increasing")
        if not 0 <= address <= 0x3F or not 0 <= value <= 0xFF:
            raise ValueError("register address or value is outside wire range")
        previous_address = address


def canonical_profile_bytes(config: AcquisitionConfigV2) -> bytes:
    _validate_values(
        profile_schema_version=config.profile_schema_version,
        sample_interval_ticks=config.sample_interval_ticks,
        sample_count=config.sample_count,
        pretrigger_count=config.pretrigger_count,
        adc_bits=config.adc_bits,
        aux_flags=config.aux_flags,
        vref_mv=config.vref_mv,
        burst_period_ticks=config.burst_period_ticks,
        register_pairs=config.register_pairs,
    )
    prefix = _CANONICAL_PREFIX.pack(
        config.profile_schema_version,
        config.sample_interval_ticks,
        config.sample_count,
        config.pretrigger_count,
        config.adc_bits,
        config.vref_mv,
        config.aux_flags,
        config.burst_period_ticks,
        len(config.register_pairs),
    )
    pairs = bytes(value for pair in config.register_pairs for value in pair)
    return prefix + pairs


def encode_config_v2(config: AcquisitionConfigV2) -> bytes:
    canonical = canonical_profile_bytes(config)
    expected_hash = hashlib.sha256(canonical).digest()
    expected_crc = crc32_iso_hdlc(canonical)
    if config.profile_sha256 != expected_hash or config.device_config_crc32 != expected_crc:
        raise ValueError("configuration hash or CRC does not match canonical fields")
    prefix = _CONFIG_PREFIX.pack(
        config.profile_schema_version,
        config.sample_interval_ticks,
        config.sample_count,
        config.pretrigger_count,
        config.adc_bits,
        config.aux_flags,
        config.vref_mv,
        config.burst_period_ticks,
        len(config.register_pairs),
        0,
    )
    pairs = bytes(value for pair in config.register_pairs for value in pair)
    return prefix + pairs + config.profile_sha256 + struct.pack(
        "<I", config.device_config_crc32
    )


def decode_config_v2(data: bytes) -> AcquisitionConfigV2:
    if len(data) < _CONFIG_PREFIX.size + 32 + 4:
        raise ValueError("AcquisitionConfigV2 is truncated")
    (
        profile_schema_version,
        sample_interval_ticks,
        sample_count,
        pretrigger_count,
        adc_bits,
        aux_flags,
        vref_mv,
        burst_period_ticks,
        register_count,
        reserved,
    ) = _CONFIG_PREFIX.unpack_from(data)
    if reserved != 0:
        raise ValueError("AcquisitionConfigV2 reserved byte must be zero")
    expected_length = _CONFIG_PREFIX.size + 2 * register_count + 32 + 4
    if len(data) != expected_length:
        raise ValueError("AcquisitionConfigV2 length does not match register_count")
    pair_offset = _CONFIG_PREFIX.size
    register_pairs = tuple(
        (data[pair_offset + index * 2], data[pair_offset + index * 2 + 1])
        for index in range(register_count)
    )
    digest_offset = pair_offset + 2 * register_count
    supplied_hash = data[digest_offset : digest_offset + 32]
    supplied_crc = struct.unpack_from("<I", data, digest_offset + 32)[0]
    config = AcquisitionConfigV2.create(
        profile_schema_version=profile_schema_version,
        sample_interval_ticks=sample_interval_ticks,
        sample_count=sample_count,
        pretrigger_count=pretrigger_count,
        adc_bits=adc_bits,
        aux_flags=aux_flags,
        vref_mv=vref_mv,
        burst_period_ticks=burst_period_ticks,
        register_pairs=register_pairs,
    )
    if config.profile_sha256 != supplied_hash or config.device_config_crc32 != supplied_crc:
        raise ValueError("AcquisitionConfigV2 hash or CRC mismatch")
    return config
