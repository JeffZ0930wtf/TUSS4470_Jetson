from __future__ import annotations

from pathlib import Path

import pytest

from usac_protocol.config_v2 import (
    D10X4_REGISTER_PAIRS,
    D10X4_SHA256,
    AcquisitionConfigV2,
    canonical_profile_bytes,
    decode_config_v2,
    encode_config_v2,
)


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_D10X4 = bytes.fromhex(
    (ROOT / "protocol/vectors/d10x4-profile-canonical-v2.hex").read_text(
        encoding="ascii"
    )
)


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


def test_d10x4_canonical_bytes_crc_and_sha_match_fixed_vector() -> None:
    config = d10x4_config()

    assert canonical_profile_bytes(config) == CANONICAL_D10X4
    assert config.device_config_crc32 == 0x5D4FC286
    assert config.profile_sha256 == D10X4_SHA256
    assert config.profile_sha256.hex().upper() == (
        "B8826EAF278D7360189D49ACED322FF9E404D8266A25E76A011065C2FDA5C998"
    )


def test_config_v2_round_trips_explicit_72_byte_layout() -> None:
    config = d10x4_config()

    encoded = encode_config_v2(config)

    assert len(encoded) == 72
    assert encoded[-4:] == bytes.fromhex("86 C2 4F 5D")
    assert decode_config_v2(encoded) == config


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sample_interval_ticks": 119}, "sample_interval_ticks"),
        ({"burst_period_ticks": 801}, "burst_period_ticks"),
        ({"pretrigger_count": 2048}, "pretrigger_count"),
        ({"aux_flags": 4}, "aux_flags"),
    ],
)
def test_config_rejects_out_of_range_values(changes: dict[str, int], message: str) -> None:
    values = {
        "sample_interval_ticks": 120,
        "sample_count": 2048,
        "pretrigger_count": 64,
        "adc_bits": 12,
        "aux_flags": 0,
        "vref_mv": 3300,
        "burst_period_ticks": 50,
        "register_pairs": D10X4_REGISTER_PAIRS,
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        AcquisitionConfigV2.create(**values)


def test_config_rejects_duplicate_or_unsorted_register_addresses() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        AcquisitionConfigV2.create(
            sample_interval_ticks=120,
            sample_count=2048,
            pretrigger_count=64,
            adc_bits=12,
            aux_flags=0,
            vref_mv=3300,
            burst_period_ticks=50,
            register_pairs=((0x11, 0), (0x10, 0x2E), (0x10, 0x2E)),
        )
