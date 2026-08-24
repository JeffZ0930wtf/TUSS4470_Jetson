from __future__ import annotations


def _encode(address: int, value: int, *, read: bool) -> bytes:
    if not isinstance(address, int) or isinstance(address, bool) or not 0 <= address <= 0x3F:
        raise ValueError("SPI address must be a six-bit integer")
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFF:
        raise ValueError("SPI value must be a byte")
    frame = (int(read) << 15) | (address << 9) | value
    if frame.bit_count() % 2 == 0:
        frame |= 1 << 8
    return frame.to_bytes(2, "big")


def encode_write(address: int, value: int) -> bytes:
    """Encode one TUSS4470 write as a 16-bit MSB-first odd-parity frame."""

    return _encode(address, value, read=False)


def encode_read(address: int) -> bytes:
    """Encode one TUSS4470 read as a 16-bit MSB-first odd-parity frame."""

    return _encode(address, 0, read=True)
