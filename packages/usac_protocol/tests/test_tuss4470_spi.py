from __future__ import annotations

import pytest

from usac_protocol.tuss4470_spi import encode_read, encode_write


@pytest.mark.parametrize(
    ("address", "value", "expected"),
    [
        (0x10, 0x2E, "20 2E"),
        (0x16, 0x40, "2D 40"),
        (0x1A, 0x01, "35 01"),
    ],
)
def test_spi_write_vectors_are_msb_first_with_odd_parity(
    address: int, value: int, expected: str
) -> None:
    frame = encode_write(address, value)

    assert frame == bytes.fromhex(expected)
    assert int.from_bytes(frame, "big").bit_count() % 2 == 1


@pytest.mark.parametrize(
    ("address", "expected"),
    [(0x10, "A1 00"), (0x16, "AD 00"), (0x1A, "B5 00")],
)
def test_spi_read_vectors_are_msb_first_with_odd_parity(
    address: int, expected: str
) -> None:
    frame = encode_read(address)

    assert frame == bytes.fromhex(expected)
    assert int.from_bytes(frame, "big").bit_count() % 2 == 1


def test_spi_rejects_address_outside_six_bit_range() -> None:
    with pytest.raises(ValueError, match="address"):
        encode_read(0x40)
