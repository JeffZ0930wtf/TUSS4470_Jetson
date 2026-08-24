from __future__ import annotations

import struct
from dataclasses import dataclass

from .frame import (
    CRC_SIZE,
    HEADER_SIZE,
    HOST_MAX_PAYLOAD_LENGTH,
    MAGIC,
    PROTOCOL_VERSION,
    VALID_FLAGS_MASK,
    CrcMismatchError,
    Frame,
    MessageType,
    ProtocolError,
    decode_frame,
)
from .message_lengths import flags_are_valid_for_message, payload_length_is_valid


HOST_RX_BUFFER_LIMIT = 16424
_HEADER_FIELDS = struct.Struct("<4sBBHII")


@dataclass(slots=True)
class ParserDiagnostics:
    invalid_header: int = 0
    invalid_length: int = 0
    crc_error: int = 0
    resync_discarded_bytes: int = 0
    rx_buffer_limit: int = 0
    incomplete_timeout: int = 0


class HostStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._candidate_started_ms: int | None = None
        self.diagnostics = ParserDiagnostics()

    def feed(self, data: bytes, *, now_ms: int) -> list[Frame]:
        self._buffer.extend(data)
        if len(self._buffer) > HOST_RX_BUFFER_LIMIT:
            self.diagnostics.rx_buffer_limit += 1
            self.diagnostics.resync_discarded_bytes += len(self._buffer) - 3
            self._buffer[:] = self._buffer[-3:]

        frames: list[Frame] = []
        while True:
            magic_index = self._buffer.find(MAGIC)
            if magic_index < 0:
                keep = _magic_prefix_length(self._buffer)
                discard = len(self._buffer) - keep
                self.diagnostics.resync_discarded_bytes += discard
                if discard:
                    del self._buffer[:discard]
                self._candidate_started_ms = None
                break
            if magic_index:
                self.diagnostics.resync_discarded_bytes += magic_index
                del self._buffer[:magic_index]
                self._candidate_started_ms = None
            if self._candidate_started_ms is None:
                self._candidate_started_ms = now_ms
            elif now_ms - self._candidate_started_ms > 2_000:
                self.diagnostics.incomplete_timeout += 1
                self._discard_candidate_byte()
                continue
            if len(self._buffer) < HEADER_SIZE:
                break

            _, version, raw_type, raw_flags, _, payload_length = _HEADER_FIELDS.unpack_from(
                self._buffer
            )
            if payload_length > HOST_MAX_PAYLOAD_LENGTH:
                self.diagnostics.invalid_length += 1
                self._discard_candidate_byte()
                continue
            if (
                version != PROTOCOL_VERSION
                or raw_flags & ~VALID_FLAGS_MASK
                or raw_type not in MessageType._value2member_map_
            ):
                self.diagnostics.invalid_header += 1
                self._discard_candidate_byte()
                continue
            message_type = MessageType(raw_type)
            if not flags_are_valid_for_message(message_type, raw_flags):
                self.diagnostics.invalid_header += 1
                self._discard_candidate_byte()
                continue
            if not payload_length_is_valid(message_type, raw_flags, payload_length):
                self.diagnostics.invalid_length += 1
                self._discard_candidate_byte()
                continue
            frame_size = HEADER_SIZE + payload_length + CRC_SIZE
            if len(self._buffer) < frame_size:
                break
            candidate = bytes(self._buffer[:frame_size])
            try:
                frame = decode_frame(candidate)
            except CrcMismatchError:
                self.diagnostics.crc_error += 1
                self._discard_candidate_byte()
                continue
            except ProtocolError:
                self.diagnostics.invalid_header += 1
                self._discard_candidate_byte()
                continue
            frames.append(frame)
            del self._buffer[:frame_size]
            self._candidate_started_ms = None
        return frames

    def _discard_candidate_byte(self) -> None:
        del self._buffer[0]
        self._candidate_started_ms = None
        self.diagnostics.resync_discarded_bytes += 1


def _magic_prefix_length(data: bytearray) -> int:
    for length in range(min(3, len(data)), 0, -1):
        if bytes(data[-length:]) == MAGIC[:length]:
            return length
    return 0
