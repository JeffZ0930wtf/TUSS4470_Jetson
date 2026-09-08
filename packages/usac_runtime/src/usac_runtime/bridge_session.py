"""One bounded, single-device bridge session for M5 laboratory operation.

The bridge forwards ordinary USAC command/response frames byte-for-byte. A
CAPTURE_DATA frame is the sole exception: it is committed to the bridge spool
first and then delivered to core using BRIDGE_CAPTURE_DELIVERY. The serial
reader waits for the matching post-SQLite receipt, so at most one waveform is
in flight and accumulated history cannot grow process RAM.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Protocol

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedResponse,
    decode_capture_committed_request,
    encode_bridge_capture_delivery,
    encode_capture_committed_response,
)
from usac_protocol.frame import (
    CRC_SIZE,
    HEADER_SIZE,
    Flags,
    Frame,
    HOST_MAX_PAYLOAD_LENGTH,
    MessageType,
    decode_frame,
    encode_frame,
)

from .spool import CaptureSpool


class SerialByteStream(Protocol):
    def read(self, size: int) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


_DEVICE_REQUESTS = {
    MessageType.HELLO,
    MessageType.GET_CAPABILITIES,
    MessageType.GET_CONFIG,
    MessageType.SET_CONFIG,
    MessageType.CAPTURE_ONCE,
    MessageType.START_PERIODIC,
    MessageType.STOP,
    MessageType.GET_STATUS,
    MessageType.RENEW_PERIODIC_LEASE,
}


def _socket_frame(connection: socket.socket) -> tuple[Frame, bytes]:
    def exact(size: int) -> bytes:
        output = bytearray()
        while len(output) < size:
            chunk = connection.recv(size - len(output))
            if not chunk:
                raise ConnectionError("core closed the bridge connection")
            output.extend(chunk)
        return bytes(output)

    header = exact(HEADER_SIZE)
    payload_length = struct.unpack_from("<I", header, 12)[0]
    if payload_length > HOST_MAX_PAYLOAD_LENGTH:
        raise ValueError("core frame exceeds host payload limit")
    raw = header + exact(payload_length + CRC_SIZE)
    return decode_frame(raw), raw


def _serial_frame(
    connection: SerialByteStream,
    stop: threading.Event,
    *,
    assembly_timeout_s: float = 2.0,
) -> tuple[Frame, bytes] | None:
    """Read one serial frame while allowing an idle session to stop promptly."""

    raw = bytearray()
    started: float | None = None
    expected = HEADER_SIZE
    while len(raw) < expected:
        if stop.is_set():
            return None
        chunk = connection.read(expected - len(raw))
        if chunk:
            if started is None:
                started = time.monotonic()
            raw.extend(chunk)
            if len(raw) == HEADER_SIZE:
                payload_length = struct.unpack_from("<I", raw, 12)[0]
                if payload_length > HOST_MAX_PAYLOAD_LENGTH:
                    raise ValueError("serial frame exceeds host payload limit")
                expected = HEADER_SIZE + payload_length + CRC_SIZE
            continue
        if started is not None and time.monotonic() - started >= assembly_timeout_s:
            raise TimeoutError("serial frame assembly timed out")
    complete = bytes(raw)
    return decode_frame(complete), complete


def _write_serial(connection: SerialByteStream, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = connection.write(data[offset:])
        if written <= 0:
            raise ConnectionError("serial write made no progress")
        offset += written


def proxy_bridge_session(
    *,
    core_connection: socket.socket,
    serial_connection: SerialByteStream,
    spool: CaptureSpool,
    connection_id: int,
    source_connection_id: int,
    commit_timeout_s: float = 3.0,
) -> None:
    """Run one TCP/serial session until either side disconnects or validation fails."""

    if commit_timeout_s <= 0:
        raise ValueError("commit_timeout_s must be positive")
    # socket.create_connection leaves its connection timeout installed. That
    # timeout bounds connection establishment, not a valid idle device
    # session; capture commit latency remains bounded separately below.
    core_connection.settimeout(None)
    stop = threading.Event()
    send_lock = threading.Lock()
    serial_write_lock = threading.Lock()
    pending_lock = threading.Lock()
    pending_events: dict[int, threading.Event] = {}
    worker_error: list[BaseException] = []
    forwarding_lock = threading.Lock()
    forwarding_enabled = False
    deferred_commands: list[bytes] = []

    def send_core(frame: Frame) -> None:
        with send_lock:
            core_connection.sendall(encode_frame(frame))

    def deliver_pending(pending, sequence: int) -> None:
        event = threading.Event()
        with pending_lock:
            pending_events[pending.record_id] = event
        send_core(
            Frame(
                MessageType.BRIDGE_CAPTURE_DELIVERY,
                sequence,
                encode_bridge_capture_delivery(
                    BridgeCaptureDelivery(
                        connection_id,
                        pending.record_id,
                        pending.source_connection_id,
                        pending.source_first_stream_offset,
                        pending.source_last_stream_offset,
                        pending.stored_utc_ns,
                        pending.inner_frame,
                    )
                ),
                Flags.ASYNC,
            )
        )
        if not event.wait(commit_timeout_s):
            raise TimeoutError("core did not confirm the capture before timeout")
        with pending_lock:
            pending_events.pop(pending.record_id, None)

    def core_reader() -> None:
        nonlocal forwarding_enabled
        try:
            while not stop.is_set():
                frame, raw = _socket_frame(core_connection)
                if frame.message_type is MessageType.CAPTURE_COMMITTED:
                    if frame.flags != Flags.NONE:
                        raise ValueError("CAPTURE_COMMITTED request has invalid flags")
                    receipt = decode_capture_committed_request(frame.payload)
                    disposition = spool.mark_committed(
                        receipt.spool_record_id,
                        device_id=receipt.device_id,
                        boot_id=receipt.boot_id,
                        capture_id=receipt.capture_id,
                        inner_frame_crc32=receipt.inner_frame_crc32,
                    )
                    send_core(
                        Frame(
                            MessageType.CAPTURE_COMMITTED,
                            frame.sequence,
                            encode_capture_committed_response(
                                CaptureCommittedResponse(
                                    receipt.connection_id,
                                    receipt.spool_record_id,
                                    disposition,
                                )
                            ),
                            Flags.RESPONSE,
                        )
                    )
                    with pending_lock:
                        event = pending_events.get(receipt.spool_record_id)
                    if event is None:
                        raise ValueError("commit receipt does not match an in-flight delivery")
                    event.set()
                else:
                    if frame.flags != Flags.NONE or frame.message_type not in _DEVICE_REQUESTS:
                        raise ValueError("core sent a frame that cannot be forwarded to the MCU")
                    if frame.message_type is not MessageType.HELLO:
                        with forwarding_lock:
                            if not forwarding_enabled:
                                if len(deferred_commands) >= 8:
                                    raise RuntimeError("too many commands arrived during spool replay")
                                deferred_commands.append(raw)
                                continue
                    with serial_write_lock:
                        _write_serial(serial_connection, raw)
        except ConnectionError:
            stop.set()
        except BaseException as error:
            worker_error.append(error)
            stop.set()

    reader = threading.Thread(target=core_reader, name="usac-bridge-core-reader", daemon=True)
    reader.start()
    stream_offset = 0
    try:
        while not stop.is_set():
            item = _serial_frame(serial_connection, stop)
            if item is None:
                break
            frame, raw = item
            first_offset = stream_offset
            stream_offset += len(raw)
            if frame.message_type is not MessageType.CAPTURE_DATA:
                send_core(frame)
                if frame.message_type is MessageType.HELLO and frame.flags & Flags.RESPONSE:
                    while batch := spool.pending_records(limit=64):
                        for pending in batch:
                            deliver_pending(pending, pending.record_id & 0xFFFFFFFF)
                    # Hold the serial write lock while enabling forwarding so
                    # commands queued during replay cannot overtake each other.
                    with serial_write_lock:
                        with forwarding_lock:
                            forwarding_enabled = True
                            queued = tuple(deferred_commands)
                            deferred_commands.clear()
                        for command in queued:
                            _write_serial(serial_connection, command)
                continue
            pending = spool.store_capture(
                raw,
                source_connection_id=source_connection_id,
                source_first_stream_offset=first_offset,
                source_last_stream_offset=stream_offset - 1,
                stored_utc_ns=time.time_ns(),
            )
            deliver_pending(pending, frame.sequence)
    finally:
        stop.set()
        try:
            core_connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        core_connection.close()
        if hasattr(serial_connection, "dtr"):
            serial_connection.dtr = False
            time.sleep(0.1)
        serial_connection.close()
        reader.join(timeout=1.0)
    if worker_error:
        raise worker_error[0]
