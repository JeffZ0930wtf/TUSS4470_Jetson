"""Minimal localhost bridge/core delivery loop for M4 capture persistence."""

from __future__ import annotations

import socket
import struct

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedResponse,
    decode_bridge_capture_delivery,
    decode_capture_committed_request,
    decode_capture_committed_response,
    encode_bridge_capture_delivery,
    encode_capture_committed_request,
    encode_capture_committed_response,
)
from usac_protocol.frame import (
    CRC_SIZE,
    HEADER_SIZE,
    HOST_MAX_PAYLOAD_LENGTH,
    Flags,
    Frame,
    MessageType,
    decode_frame,
    encode_frame,
)
from usac_runtime.core_store import CaptureStore
from usac_runtime.spool import CaptureSpool, PendingCapture


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("peer closed before a complete frame was received")
        data.extend(chunk)
    return bytes(data)


def _receive_frame(connection: socket.socket) -> Frame:
    header = _receive_exact(connection, HEADER_SIZE)
    payload_length = struct.unpack_from("<I", header, 12)[0]
    if payload_length > HOST_MAX_PAYLOAD_LENGTH:
        raise ValueError("peer frame exceeds the host payload limit")
    return decode_frame(
        header + _receive_exact(connection, payload_length + CRC_SIZE)
    )


def handle_core_delivery(connection: socket.socket, store: CaptureStore) -> int:
    """Persist one bridge delivery, confirm it, and verify bridge cleanup."""

    frame = _receive_frame(connection)
    if (
        frame.message_type is not MessageType.BRIDGE_CAPTURE_DELIVERY
        or frame.flags != Flags.ASYNC
    ):
        raise ValueError("core expected one asynchronous BRIDGE_CAPTURE_DELIVERY")
    delivery = decode_bridge_capture_delivery(frame.payload)
    result = store.commit_delivery(delivery)

    # commit_delivery returns only after its SQLite context has committed, so
    # this send can never acknowledge an uncommitted core record.
    connection.sendall(
        encode_frame(
            Frame(
                MessageType.CAPTURE_COMMITTED,
                frame.sequence,
                encode_capture_committed_request(result.receipt),
            )
        )
    )
    response_frame = _receive_frame(connection)
    if (
        response_frame.message_type is not MessageType.CAPTURE_COMMITTED
        or response_frame.flags != Flags.RESPONSE
        or response_frame.sequence != frame.sequence
    ):
        raise ValueError("bridge returned an invalid CAPTURE_COMMITTED response")
    response = decode_capture_committed_response(response_frame.payload)
    if (
        response.connection_id != delivery.connection_id
        or response.spool_record_id != delivery.spool_record_id
    ):
        raise ValueError("bridge commit response does not match the delivery")
    return response.disposition


def deliver_pending(
    connection: socket.socket,
    spool: CaptureSpool,
    pending: PendingCapture,
    *,
    connection_id: int,
    sequence: int,
) -> int:
    """Deliver one pending frame and delete it only after a matching receipt."""

    delivery = BridgeCaptureDelivery(
        connection_id=connection_id,
        spool_record_id=pending.record_id,
        source_connection_id=pending.source_connection_id,
        source_first_stream_offset=pending.source_first_stream_offset,
        source_last_stream_offset=pending.source_last_stream_offset,
        stored_utc_ns=pending.stored_utc_ns,
        inner_frame=pending.inner_frame,
    )
    connection.sendall(
        encode_frame(
            Frame(
                MessageType.BRIDGE_CAPTURE_DELIVERY,
                sequence,
                encode_bridge_capture_delivery(delivery),
                Flags.ASYNC,
            )
        )
    )
    receipt_frame = _receive_frame(connection)
    if (
        receipt_frame.message_type is not MessageType.CAPTURE_COMMITTED
        or receipt_frame.flags != Flags.NONE
        or receipt_frame.sequence != sequence
    ):
        raise ValueError("core returned an invalid CAPTURE_COMMITTED receipt")
    receipt = decode_capture_committed_request(receipt_frame.payload)
    if receipt.connection_id != connection_id or receipt.spool_record_id != pending.record_id:
        raise ValueError("core commit receipt does not match the active delivery")
    disposition = spool.mark_committed(
        receipt.spool_record_id,
        device_id=receipt.device_id,
        boot_id=receipt.boot_id,
        capture_id=receipt.capture_id,
        inner_frame_crc32=receipt.inner_frame_crc32,
    )
    connection.sendall(
        encode_frame(
            Frame(
                MessageType.CAPTURE_COMMITTED,
                sequence,
                encode_capture_committed_response(
                    CaptureCommittedResponse(
                        connection_id=connection_id,
                        spool_record_id=pending.record_id,
                        disposition=disposition,
                    )
                ),
                Flags.RESPONSE,
            )
        )
    )
    return disposition
