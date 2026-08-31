"""Durable bridge-side storage for complete, uncommitted CAPTURE_DATA frames.

The spool owns only the delivery gap between USB reception and core SQLite
commit. It never edits waveform bytes and removes a frame only after a matching
commit receipt has been verified.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from usac_protocol.capture_data import decode_capture_data
from usac_protocol.frame import MessageType, crc32_iso_hdlc, decode_frame


DELETED = 1
ALREADY_COMMITTED = 2


class SpoolConflictError(RuntimeError):
    """Raised when a stable capture identity is associated with other bytes."""


@dataclass(frozen=True, slots=True)
class PendingCapture:
    record_id: int
    device_id: bytes
    boot_id: bytes
    capture_id: bytes
    capture_sequence: int
    source_connection_id: int
    source_first_stream_offset: int
    source_last_stream_offset: int
    inner_frame_crc32: int
    inner_frame: bytes
    stored_utc_ns: int


_PENDING_COLUMNS = """
record_id, device_id, boot_id, capture_id, capture_sequence,
source_connection_id, source_first_stream_offset, source_last_stream_offset,
inner_frame_crc32, inner_frame, stored_utc_ns
"""


class CaptureSpool:
    """Small SQLite WAL spool with one durable transaction per state change."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_captures (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id BLOB NOT NULL,
                    boot_id BLOB NOT NULL,
                    capture_id BLOB NOT NULL,
                    capture_sequence INTEGER NOT NULL,
                    source_connection_id INTEGER NOT NULL,
                    source_first_stream_offset INTEGER NOT NULL,
                    source_last_stream_offset INTEGER NOT NULL,
                    inner_frame_crc32 INTEGER NOT NULL,
                    inner_frame BLOB NOT NULL,
                    stored_utc_ns INTEGER NOT NULL,
                    UNIQUE(device_id, boot_id, capture_id)
                );

                CREATE TABLE IF NOT EXISTS committed_tombstones (
                    record_id INTEGER PRIMARY KEY,
                    device_id BLOB NOT NULL,
                    boot_id BLOB NOT NULL,
                    capture_id BLOB NOT NULL,
                    inner_frame_crc32 INTEGER NOT NULL,
                    UNIQUE(device_id, boot_id, capture_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _pending(row: tuple[object, ...]) -> PendingCapture:
        return PendingCapture(
            record_id=int(row[0]),
            device_id=bytes(row[1]),
            boot_id=bytes(row[2]),
            capture_id=bytes(row[3]),
            capture_sequence=int(row[4]),
            source_connection_id=int(row[5]),
            source_first_stream_offset=int(row[6]),
            source_last_stream_offset=int(row[7]),
            inner_frame_crc32=int(row[8]),
            inner_frame=bytes(row[9]),
            stored_utc_ns=int(row[10]),
        )

    def store_capture(
        self,
        inner_frame: bytes,
        *,
        source_connection_id: int,
        source_first_stream_offset: int,
        source_last_stream_offset: int,
        stored_utc_ns: int,
    ) -> PendingCapture:
        """Validate and FULL-commit one unchanged device frame before delivery."""

        frame = decode_frame(inner_frame)
        if frame.message_type is not MessageType.CAPTURE_DATA:
            raise ValueError("spool accepts only CAPTURE_DATA frames")
        if source_last_stream_offset - source_first_stream_offset + 1 != len(
            inner_frame
        ):
            raise ValueError("source offsets do not cover the complete frame")
        capture = decode_capture_data(frame.payload)
        inner_crc = crc32_iso_hdlc(inner_frame)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT {_PENDING_COLUMNS} FROM pending_captures "
                "WHERE device_id=? AND boot_id=? AND capture_id=?",
                (capture.device_id, capture.boot_id, capture.capture_id),
            ).fetchone()
            if existing is not None:
                pending = self._pending(existing)
                if pending.inner_frame != inner_frame or pending.inner_frame_crc32 != inner_crc:
                    raise SpoolConflictError(
                        "capture identity already exists with a different frame"
                    )
                return pending

            cursor = connection.execute(
                """
                INSERT INTO pending_captures (
                    device_id, boot_id, capture_id, capture_sequence,
                    source_connection_id, source_first_stream_offset,
                    source_last_stream_offset, inner_frame_crc32, inner_frame,
                    stored_utc_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture.device_id,
                    capture.boot_id,
                    capture.capture_id,
                    capture.capture_sequence,
                    source_connection_id,
                    source_first_stream_offset,
                    source_last_stream_offset,
                    inner_crc,
                    inner_frame,
                    stored_utc_ns,
                ),
            )
            record_id = int(cursor.lastrowid)
            row = connection.execute(
                f"SELECT {_PENDING_COLUMNS} FROM pending_captures WHERE record_id=?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("spool insert did not produce a pending record")
            return self._pending(row)

    def pending_records(self) -> list[PendingCapture]:
        """Return pending frames in their permanent delivery order."""

        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_PENDING_COLUMNS} FROM pending_captures ORDER BY record_id"
            ).fetchall()
        return [self._pending(row) for row in rows]

    def mark_committed(
        self,
        record_id: int,
        *,
        device_id: bytes,
        boot_id: bytes,
        capture_id: bytes,
        inner_frame_crc32: int,
    ) -> int:
        """Delete one matching pending BLOB and retain a durable receipt marker."""

        expected = (device_id, boot_id, capture_id, inner_frame_crc32)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT device_id, boot_id, capture_id, inner_frame_crc32
                FROM pending_captures WHERE record_id=?
                """,
                (record_id,),
            ).fetchone()
            if row is not None:
                actual = (bytes(row[0]), bytes(row[1]), bytes(row[2]), int(row[3]))
                if actual != expected:
                    raise SpoolConflictError("commit receipt does not match pending record")
                connection.execute(
                    """
                    INSERT INTO committed_tombstones (
                        record_id, device_id, boot_id, capture_id, inner_frame_crc32
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (record_id, *expected),
                )
                connection.execute(
                    "DELETE FROM pending_captures WHERE record_id=?", (record_id,)
                )
                return DELETED

            tombstone = connection.execute(
                """
                SELECT device_id, boot_id, capture_id, inner_frame_crc32
                FROM committed_tombstones WHERE record_id=?
                """,
                (record_id,),
            ).fetchone()
            if tombstone is None:
                raise SpoolConflictError("commit receipt does not match a known record")
            actual = (
                bytes(tombstone[0]),
                bytes(tombstone[1]),
                bytes(tombstone[2]),
                int(tombstone[3]),
            )
            if actual != expected:
                raise SpoolConflictError("commit receipt does not match tombstone")
            return ALREADY_COMMITTED
