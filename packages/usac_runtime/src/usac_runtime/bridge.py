"""Minimal Windows bridge helpers for M4 staging, spool, and replay."""

from __future__ import annotations

import secrets
import socket
from pathlib import Path

from usac_runtime.delivery import deliver_pending
from usac_runtime.serial import SerialConnection
from usac_runtime.spool import CaptureSpool, PendingCapture


class CountingConnection:
    """Transparent serial wrapper that records the COM receive stream offset."""

    def __init__(self, connection: SerialConnection) -> None:
        self.connection = connection
        self.received_bytes = 0

    def read(self, size: int) -> bytes:
        data = self.connection.read(size)
        self.received_bytes += len(data)
        return data

    def write(self, data: bytes) -> int:
        return self.connection.write(data)

    def close(self) -> None:
        self.connection.close()


def new_sqlite_integer_id() -> int:
    """Return a nonzero random ID representable by SQLite INTEGER.

    The wire contract permits an unsigned 64-bit connection ID, while SQLite
    INTEGER is signed. Locally generated source IDs deliberately use the
    positive 63-bit subset so persistence cannot fail nondeterministically.
    """

    return secrets.randbits(63) or 1


def spool_artifacts(
    spool: CaptureSpool,
    *,
    raw_path: Path,
    metadata_path: Path,
    samples_path: Path,
    source_connection_id: int,
    source_first_stream_offset: int,
    stored_utc_ns: int,
) -> PendingCapture:
    """Move one completed M3 artifact set into the durable M4 spool."""

    inner_frame = raw_path.read_bytes()
    pending = spool.store_capture(
        inner_frame,
        source_connection_id=source_connection_id,
        source_first_stream_offset=source_first_stream_offset,
        source_last_stream_offset=source_first_stream_offset + len(inner_frame) - 1,
        stored_utc_ns=stored_utc_ns,
    )
    # These files are only crash-visible staging. Once the complete frame is in
    # the spool, the core can recreate both samples and metadata from it.
    raw_path.unlink()
    metadata_path.unlink()
    samples_path.unlink()
    return pending


def deliver_spool(
    spool: CaptureSpool,
    *,
    core_host: str,
    core_port: int,
    timeout_s: float = 2.0,
) -> int:
    """Replay pending records in bounded batches with one delivery in flight."""

    delivered = 0
    while batch := spool.pending_records(limit=64):
        for pending in batch:
            with socket.create_connection((core_host, core_port), timeout=timeout_s) as connection:
                connection.settimeout(timeout_s)
                connection_id = secrets.randbits(64) or 1
                deliver_pending(
                    connection,
                    spool,
                    pending,
                    connection_id=connection_id,
                    sequence=pending.record_id & 0xFFFFFFFF,
                )
            delivered += 1
    return delivered
