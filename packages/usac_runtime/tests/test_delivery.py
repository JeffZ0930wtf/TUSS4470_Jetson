from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedRequest,
    decode_bridge_capture_delivery,
    encode_capture_committed_request,
)
from usac_protocol.capture_data import decode_capture_data
from usac_protocol.frame import (
    Flags,
    Frame,
    MessageType,
    crc32_iso_hdlc,
    decode_frame,
    encode_frame,
)
from usac_runtime.core_store import CaptureStore
from usac_runtime.delivery import _receive_frame, deliver_pending, handle_core_delivery
from usac_runtime.spool import CaptureSpool


ROOT = Path(__file__).resolve().parents[3]


def _raw_capture() -> bytes:
    return bytes.fromhex(
        (ROOT / "protocol/vectors/capture-data-v1.hex").read_text(encoding="ascii")
    )


def _pending(spool: CaptureSpool):
    raw = _raw_capture()
    return spool.store_capture(
        raw,
        source_connection_id=3,
        source_first_stream_offset=100,
        source_last_stream_offset=100 + len(raw) - 1,
        stored_utc_ns=4,
    )


def _serve_once(server: socket.socket, store: CaptureStore) -> None:
    try:
        handle_core_delivery(server, store)
    finally:
        server.close()


def _send_wrong_connection_receipt(server: socket.socket) -> None:
    try:
        frame = _receive_frame(server)
        delivery = decode_bridge_capture_delivery(frame.payload)
        capture = decode_capture_data(decode_frame(delivery.inner_frame).payload)
        receipt = CaptureCommittedRequest(
            connection_id=delivery.connection_id + 1,
            spool_record_id=delivery.spool_record_id,
            device_id=capture.device_id,
            boot_id=capture.boot_id,
            capture_id=capture.capture_id,
            inner_frame_crc32=crc32_iso_hdlc(delivery.inner_frame),
        )
        server.sendall(
            encode_frame(
                Frame(
                    MessageType.CAPTURE_COMMITTED,
                    frame.sequence,
                    encode_capture_committed_request(receipt),
                    Flags.NONE,
                )
            )
        )
    finally:
        server.close()


def test_delivery_closes_spool_only_after_core_commit(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge.sqlite3")
    store = CaptureStore(tmp_path / "core.sqlite3")
    pending = _pending(spool)
    bridge_socket, core_socket = socket.socketpair()
    worker = threading.Thread(target=_serve_once, args=(core_socket, store))
    worker.start()

    disposition = deliver_pending(
        bridge_socket,
        spool,
        pending,
        connection_id=20,
        sequence=21,
    )
    bridge_socket.close()
    worker.join(timeout=2)

    assert disposition == 1
    assert worker.is_alive() is False
    assert spool.pending_records() == []
    assert store.capture_count() == 1
    assert store.get_capture(pending.capture_id).wire_frame == pending.inner_frame


def test_delivery_recovers_when_core_committed_before_receipt_was_received(
    tmp_path: Path,
) -> None:
    spool_path = tmp_path / "bridge.sqlite3"
    store = CaptureStore(tmp_path / "core.sqlite3")
    pending = _pending(CaptureSpool(spool_path))
    store.commit_delivery(
        BridgeCaptureDelivery(
            connection_id=10,
            spool_record_id=pending.record_id,
            source_connection_id=pending.source_connection_id,
            source_first_stream_offset=pending.source_first_stream_offset,
            source_last_stream_offset=pending.source_last_stream_offset,
            stored_utc_ns=pending.stored_utc_ns,
            inner_frame=pending.inner_frame,
        )
    )

    restarted_spool = CaptureSpool(spool_path)
    bridge_socket, core_socket = socket.socketpair()
    worker = threading.Thread(target=_serve_once, args=(core_socket, store))
    worker.start()
    disposition = deliver_pending(
        bridge_socket,
        restarted_spool,
        restarted_spool.pending_records()[0],
        connection_id=30,
        sequence=31,
    )
    bridge_socket.close()
    worker.join(timeout=2)

    assert disposition == 1
    assert restarted_spool.pending_records() == []
    assert store.capture_count() == 1


def test_delivery_keeps_pending_record_when_core_is_unavailable(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge.sqlite3")
    pending = _pending(spool)
    bridge_socket, core_socket = socket.socketpair()
    core_socket.close()

    try:
        deliver_pending(
            bridge_socket,
            spool,
            pending,
            connection_id=40,
            sequence=41,
        )
    except (ConnectionError, OSError):
        pass
    finally:
        bridge_socket.close()

    assert spool.pending_records() == [pending]


def test_delivery_validates_receipt_before_deleting_pending(tmp_path: Path) -> None:
    spool = CaptureSpool(tmp_path / "bridge.sqlite3")
    pending = _pending(spool)
    bridge_socket, core_socket = socket.socketpair()
    worker = threading.Thread(target=_send_wrong_connection_receipt, args=(core_socket,))
    worker.start()

    with pytest.raises(ValueError, match="active delivery"):
        deliver_pending(
            bridge_socket,
            spool,
            pending,
            connection_id=50,
            sequence=51,
        )
    bridge_socket.close()
    worker.join(timeout=2)

    assert spool.pending_records() == [pending]
