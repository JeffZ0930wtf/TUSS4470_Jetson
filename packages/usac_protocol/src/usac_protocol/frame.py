from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum, IntFlag


MAGIC = b"USAC"
PROTOCOL_VERSION = 1
HEADER_SIZE = 16
CRC_SIZE = 4
HOST_MAX_PAYLOAD_LENGTH = 8192
VALID_FLAGS_MASK = 0x0007
_HEADER = struct.Struct("<4sBBHII")
_CRC = struct.Struct("<I")


class ProtocolError(ValueError):
    """Base class for a malformed USAC frame."""


class CrcMismatchError(ProtocolError):
    """Raised when a complete frame has an invalid CRC."""


class MessageType(IntEnum):
    HELLO = 0x01
    GET_CAPABILITIES = 0x02
    GET_CONFIG = 0x03
    SET_CONFIG = 0x04
    CAPTURE_ONCE = 0x05
    START_PERIODIC = 0x06
    STOP = 0x07
    GET_STATUS = 0x08
    READ_REGISTER = 0x09
    WRITE_REGISTER = 0x0A
    RESET_DEVICE = 0x0B
    RENEW_PERIODIC_LEASE = 0x0C
    CAPTURE_DATA = 0x40
    BRIDGE_HELLO = 0x70
    BRIDGE_HEARTBEAT = 0x71
    CORE_CHALLENGE = 0x72
    BRIDGE_DIAGNOSTIC = 0x73
    BRIDGE_CAPTURE_DELIVERY = 0x74
    CAPTURE_COMMITTED = 0x75
    BRIDGE_SPOOL_STATUS = 0x76
    REQUEST_ATTACHED = 0x7D
    ACK = 0x7E
    ERROR = 0x7F


class Flags(IntFlag):
    NONE = 0
    RESPONSE = 1 << 0
    ASYNC = 1 << 1
    WARNING = 1 << 2


@dataclass(frozen=True, slots=True)
class Frame:
    message_type: MessageType
    sequence: int
    payload: bytes
    flags: Flags = Flags.NONE
    protocol_version: int = PROTOCOL_VERSION


def crc32_iso_hdlc(data: bytes) -> int:
    """Return CRC-32/ISO-HDLC using the protocol's reflected parameters."""

    return zlib.crc32(data) & 0xFFFFFFFF


def _validate_frame_fields(frame: Frame) -> None:
    if frame.protocol_version != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    if int(frame.flags) & ~VALID_FLAGS_MASK:
        raise ValueError("reserved flag bits must be zero")
    if not 0 <= frame.sequence <= 0xFFFFFFFF:
        raise ValueError("sequence is outside u32 range")
    if len(frame.payload) > HOST_MAX_PAYLOAD_LENGTH:
        raise ValueError("payload exceeds host maximum")


def encode_frame(frame: Frame) -> bytes:
    _validate_frame_fields(frame)
    header = _HEADER.pack(
        MAGIC,
        frame.protocol_version,
        int(frame.message_type),
        int(frame.flags),
        frame.sequence,
        len(frame.payload),
    )
    crc = crc32_iso_hdlc(header[4:] + frame.payload)
    return header + frame.payload + _CRC.pack(crc)


def decode_frame(data: bytes) -> Frame:
    if len(data) < HEADER_SIZE + CRC_SIZE:
        raise ProtocolError("frame is truncated")
    magic, version, raw_type, raw_flags, sequence, payload_length = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ProtocolError("invalid magic")
    expected_size = HEADER_SIZE + payload_length + CRC_SIZE
    if payload_length > HOST_MAX_PAYLOAD_LENGTH:
        raise ProtocolError("payload exceeds host maximum")
    if len(data) != expected_size:
        raise ProtocolError("frame length does not match header")
    try:
        message_type = MessageType(raw_type)
    except ValueError as error:
        raise ProtocolError("unsupported message type") from error
    frame = Frame(
        message_type=message_type,
        flags=Flags(raw_flags),
        sequence=sequence,
        payload=data[HEADER_SIZE:-CRC_SIZE],
        protocol_version=version,
    )
    _validate_frame_fields(frame)
    expected_crc = _CRC.unpack_from(data, len(data) - CRC_SIZE)[0]
    actual_crc = crc32_iso_hdlc(data[4:-CRC_SIZE])
    if actual_crc != expected_crc:
        raise CrcMismatchError(
            f"CRC mismatch: expected 0x{expected_crc:08X}, calculated 0x{actual_crc:08X}"
        )
    return frame
