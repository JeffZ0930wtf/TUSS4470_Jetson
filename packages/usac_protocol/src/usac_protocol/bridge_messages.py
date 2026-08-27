"""Bridge/core delivery payloads for durable capture handoff.

These codecs bind an outer delivery identity to the unchanged inner device
frame. They do not persist data or acknowledge a SQLite transaction themselves.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .frame import MessageType, crc32_iso_hdlc, decode_frame


def _identifier(value: bytes, name: str) -> bytes:
    if len(value) != 16:
        raise ValueError(f"{name} must be exactly 16 bytes")
    return value


@dataclass(frozen=True, slots=True)
class BridgeCaptureDelivery:
    connection_id: int
    spool_record_id: int
    source_connection_id: int
    source_first_stream_offset: int
    source_last_stream_offset: int
    stored_utc_ns: int
    inner_frame: bytes


_DELIVERY = struct.Struct("<QQQQQQII")


def encode_bridge_capture_delivery(message: BridgeCaptureDelivery) -> bytes:
    if not 208 <= len(message.inner_frame) <= 4652:
        raise ValueError("delivery inner frame length is outside CAPTURE_DATA bounds")
    if message.source_last_stream_offset - message.source_first_stream_offset + 1 != len(
        message.inner_frame
    ):
        raise ValueError("delivery source offsets do not cover the inner frame")
    inner = decode_frame(message.inner_frame)
    if inner.message_type is not MessageType.CAPTURE_DATA:
        raise ValueError("delivery inner frame must be CAPTURE_DATA")
    return _DELIVERY.pack(
        message.connection_id,
        message.spool_record_id,
        message.source_connection_id,
        message.source_first_stream_offset,
        message.source_last_stream_offset,
        message.stored_utc_ns,
        len(message.inner_frame),
        crc32_iso_hdlc(message.inner_frame),
    ) + message.inner_frame


def decode_bridge_capture_delivery(data: bytes) -> BridgeCaptureDelivery:
    if len(data) < _DELIVERY.size:
        raise ValueError("BRIDGE_CAPTURE_DELIVERY payload is truncated")
    values = _DELIVERY.unpack_from(data)
    inner_length, inner_crc = values[-2:]
    if len(data) != _DELIVERY.size + inner_length:
        raise ValueError("delivery inner_frame_length does not match payload")
    inner = data[_DELIVERY.size :]
    if crc32_iso_hdlc(inner) != inner_crc:
        raise ValueError("delivery inner frame CRC does not match")
    message = BridgeCaptureDelivery(*values[:-2], inner)
    encode_bridge_capture_delivery(message)
    return message


@dataclass(frozen=True, slots=True)
class CaptureCommittedRequest:
    connection_id: int
    spool_record_id: int
    device_id: bytes
    boot_id: bytes
    capture_id: bytes
    inner_frame_crc32: int


_COMMITTED_REQUEST = struct.Struct("<QQ16s16s16sI")


def encode_capture_committed_request(message: CaptureCommittedRequest) -> bytes:
    return _COMMITTED_REQUEST.pack(
        message.connection_id,
        message.spool_record_id,
        _identifier(message.device_id, "device_id"),
        _identifier(message.boot_id, "boot_id"),
        _identifier(message.capture_id, "capture_id"),
        message.inner_frame_crc32,
    )


def decode_capture_committed_request(data: bytes) -> CaptureCommittedRequest:
    if len(data) != _COMMITTED_REQUEST.size:
        raise ValueError("CAPTURE_COMMITTED request payload must be 68 bytes")
    return CaptureCommittedRequest(*_COMMITTED_REQUEST.unpack(data))


@dataclass(frozen=True, slots=True)
class CaptureCommittedResponse:
    connection_id: int
    spool_record_id: int
    disposition: int


_COMMITTED_RESPONSE = struct.Struct("<QQB7x")


def encode_capture_committed_response(message: CaptureCommittedResponse) -> bytes:
    if message.disposition not in (1, 2):
        raise ValueError("CAPTURE_COMMITTED disposition must be 1 or 2")
    return _COMMITTED_RESPONSE.pack(
        message.connection_id, message.spool_record_id, message.disposition
    )


def decode_capture_committed_response(data: bytes) -> CaptureCommittedResponse:
    if len(data) != _COMMITTED_RESPONSE.size:
        raise ValueError("CAPTURE_COMMITTED response payload must be 24 bytes")
    if data[-7:] != bytes(7):
        raise ValueError("CAPTURE_COMMITTED response reserved bytes must be zero")
    return CaptureCommittedResponse(*_COMMITTED_RESPONSE.unpack(data))
