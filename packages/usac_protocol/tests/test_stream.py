from __future__ import annotations

from usac_protocol.frame import Frame, MessageType, encode_frame
from usac_protocol.stream import HostStreamParser


def test_parser_resynchronizes_after_bad_length_and_crc() -> None:
    valid = encode_frame(
        Frame(message_type=MessageType.GET_CONFIG, sequence=9, payload=b"")
    )
    invalid_length = bytearray(valid)
    invalid_length[12:16] = (0xFFFFFFFF).to_bytes(4, "little")
    invalid_crc = bytearray(valid)
    invalid_crc[-1] ^= 0x80

    parser = HostStreamParser()
    frames = parser.feed(b"noise" + invalid_length + invalid_crc + valid, now_ms=10)

    assert frames == [
        Frame(message_type=MessageType.GET_CONFIG, sequence=9, payload=b"")
    ]
    assert parser.diagnostics.invalid_length == 1
    assert parser.diagnostics.crc_error == 1
    assert parser.diagnostics.resync_discarded_bytes > 0


def test_magic_inside_payload_does_not_split_a_valid_frame() -> None:
    original = Frame(
        message_type=MessageType.HELLO,
        sequence=3,
        payload=b"USAC" + bytes(16),
    )
    parser = HostStreamParser()

    assert parser.feed(encode_frame(original), now_ms=0) == [original]


def test_type_specific_invalid_length_is_rejected_and_parser_recovers() -> None:
    wrong = encode_frame(
        Frame(message_type=MessageType.GET_CONFIG, sequence=1, payload=b"x")
    )
    valid = encode_frame(
        Frame(message_type=MessageType.GET_CONFIG, sequence=2, payload=b"")
    )
    parser = HostStreamParser()

    assert parser.feed(wrong + valid, now_ms=0) == [
        Frame(message_type=MessageType.GET_CONFIG, sequence=2, payload=b"")
    ]
    assert parser.diagnostics.invalid_length == 1


def test_incomplete_candidate_times_out_then_recovers() -> None:
    valid = encode_frame(
        Frame(message_type=MessageType.GET_CONFIG, sequence=4, payload=b"")
    )
    parser = HostStreamParser()

    assert parser.feed(valid[:-2], now_ms=100) == []
    assert parser.feed(b"", now_ms=2101) == []
    assert parser.diagnostics.incomplete_timeout == 1
    assert parser.feed(valid, now_ms=2102) == [
        Frame(message_type=MessageType.GET_CONFIG, sequence=4, payload=b"")
    ]


def test_response_only_message_with_request_flags_is_rejected() -> None:
    invalid_ack = encode_frame(Frame(MessageType.ACK, 1, bytes(24)))
    valid = encode_frame(Frame(MessageType.GET_CONFIG, 2, b""))
    parser = HostStreamParser()

    assert parser.feed(invalid_ack + valid, now_ms=0) == [
        Frame(MessageType.GET_CONFIG, 2, b"")
    ]
    assert parser.diagnostics.invalid_header == 1
