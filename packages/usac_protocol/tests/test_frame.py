from __future__ import annotations

from pathlib import Path

import pytest

from usac_protocol.frame import (
    CrcMismatchError,
    Flags,
    Frame,
    MessageType,
    decode_frame,
    encode_frame,
)


ROOT = Path(__file__).resolve().parents[3]
HELLO_FRAME = bytes.fromhex(
    (ROOT / "protocol/vectors/hello-request-v1.hex").read_text(encoding="ascii")
)


def test_hello_fixed_vector_decodes_and_reencodes_byte_for_byte() -> None:
    frame = decode_frame(HELLO_FRAME)

    assert frame.message_type is MessageType.HELLO
    assert frame.flags is Flags.NONE
    assert frame.sequence == 1
    assert frame.payload == bytes(range(16)) + bytes.fromhex("01 01 00 00")
    assert encode_frame(frame) == HELLO_FRAME


def test_crc_error_is_rejected() -> None:
    damaged = bytearray(HELLO_FRAME)
    damaged[20] ^= 0x01

    with pytest.raises(CrcMismatchError):
        decode_frame(bytes(damaged))


def test_reserved_flag_is_rejected_before_encoding() -> None:
    frame = Frame(
        message_type=MessageType.HELLO,
        flags=Flags(0x0008),
        sequence=1,
        payload=b"",
    )

    with pytest.raises(ValueError, match="reserved flag"):
        encode_frame(frame)
