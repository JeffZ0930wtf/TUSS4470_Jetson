"""Core-side transactional storage for raw ultrasonic capture deliveries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from usac_protocol.bridge_messages import (
    BridgeCaptureDelivery,
    CaptureCommittedRequest,
    encode_bridge_capture_delivery,
)
from usac_protocol.capture_data import decode_capture_data
from usac_protocol.frame import crc32_iso_hdlc, decode_frame


class StorageConflictError(RuntimeError):
    """Raised when one capture identity is delivered with different bytes."""


@dataclass(frozen=True, slots=True)
class CoreCommitResult:
    receipt: CaptureCommittedRequest
    inserted: bool


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    capture_id: bytes
    device_id: bytes
    boot_id: bytes
    request_id: bytes
    profile_sha256: bytes
    device_config_crc32: int
    capture_sequence: int
    sample_interval_ticks: int
    burst_period_ticks: int
    sample_count: int
    pretrigger_count: int
    quality_flags: int
    wire_frame: bytes
    sample_blob: bytes
    interpolated: bool


class CaptureStore:
    """SQLite/WAL capture archive that returns only post-COMMIT receipts."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id BLOB NOT NULL,
                    boot_id BLOB NOT NULL,
                    capture_id BLOB NOT NULL,
                    request_id BLOB NOT NULL,
                    schedule_id BLOB NOT NULL,
                    profile_sha256 BLOB NOT NULL,
                    device_config_crc32 INTEGER NOT NULL,
                    capture_sequence INTEGER NOT NULL,
                    sample_interval_ticks INTEGER NOT NULL,
                    burst_period_ticks INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    pretrigger_count INTEGER NOT NULL,
                    quality_flags INTEGER NOT NULL,
                    tuss_dev_stat INTEGER NOT NULL,
                    source_connection_id INTEGER NOT NULL,
                    source_first_stream_offset INTEGER NOT NULL,
                    source_last_stream_offset INTEGER NOT NULL,
                    bridge_spool_record_id INTEGER NOT NULL,
                    inner_frame_crc32 INTEGER NOT NULL,
                    wire_frame_blob BLOB NOT NULL,
                    sample_blob BLOB NOT NULL,
                    configuration_json TEXT NOT NULL,
                    stored_utc_ns INTEGER NOT NULL,
                    UNIQUE(device_id, boot_id, capture_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _receipt(
        delivery: BridgeCaptureDelivery,
        *,
        device_id: bytes,
        boot_id: bytes,
        capture_id: bytes,
        inner_frame_crc32: int,
    ) -> CaptureCommittedRequest:
        return CaptureCommittedRequest(
            connection_id=delivery.connection_id,
            spool_record_id=delivery.spool_record_id,
            device_id=device_id,
            boot_id=boot_id,
            capture_id=capture_id,
            inner_frame_crc32=inner_frame_crc32,
        )

    def commit_delivery(self, delivery: BridgeCaptureDelivery) -> CoreCommitResult:
        """Commit one validated delivery and return its receipt after commit."""

        # Reusing the protocol encoder here keeps core validation identical to
        # bridge/core wire validation without introducing a second rule set.
        encode_bridge_capture_delivery(delivery)
        frame = decode_frame(delivery.inner_frame)
        capture = decode_capture_data(frame.payload)
        inner_crc = crc32_iso_hdlc(delivery.inner_frame)
        sample_bytes = capture.sample_count * 2
        sample_blob = frame.payload[-sample_bytes:] if sample_bytes else b""
        configuration = json.dumps(
            {
                "profile_sha256": capture.profile_sha256.hex(),
                "device_config_crc32": capture.device_config_crc32,
                "sample_interval_ticks": capture.sample_interval_ticks,
                "burst_period_ticks": capture.burst_period_ticks,
                "sample_count": capture.sample_count,
                "pretrigger_count": capture.pretrigger_count,
                "register_pairs": [list(pair) for pair in capture.register_pairs],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        receipt = self._receipt(
            delivery,
            device_id=capture.device_id,
            boot_id=capture.boot_id,
            capture_id=capture.capture_id,
            inner_frame_crc32=inner_crc,
        )

        inserted = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT inner_frame_crc32, wire_frame_blob
                FROM captures
                WHERE device_id=? AND boot_id=? AND capture_id=?
                """,
                (capture.device_id, capture.boot_id, capture.capture_id),
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != inner_crc or bytes(existing[1]) != delivery.inner_frame:
                    raise StorageConflictError(
                        "capture identity already exists with a different frame"
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO captures (
                        device_id, boot_id, capture_id, request_id, schedule_id,
                        profile_sha256, device_config_crc32, capture_sequence,
                        sample_interval_ticks, burst_period_ticks, sample_count,
                        pretrigger_count, quality_flags, tuss_dev_stat,
                        source_connection_id, source_first_stream_offset,
                        source_last_stream_offset, bridge_spool_record_id,
                        inner_frame_crc32, wire_frame_blob, sample_blob,
                        configuration_json, stored_utc_ns
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        capture.device_id,
                        capture.boot_id,
                        capture.capture_id,
                        capture.request_id,
                        capture.schedule_id,
                        capture.profile_sha256,
                        capture.device_config_crc32,
                        capture.capture_sequence,
                        capture.sample_interval_ticks,
                        capture.burst_period_ticks,
                        capture.sample_count,
                        capture.pretrigger_count,
                        capture.quality_flags,
                        capture.tuss_dev_stat,
                        delivery.source_connection_id,
                        delivery.source_first_stream_offset,
                        delivery.source_last_stream_offset,
                        delivery.spool_record_id,
                        inner_crc,
                        delivery.inner_frame,
                        sample_blob,
                        configuration,
                        delivery.stored_utc_ns,
                    ),
                )
                inserted = True

        # The context manager has committed successfully before this object can
        # escape to the network service as CAPTURE_COMMITTED.
        return CoreCommitResult(receipt=receipt, inserted=inserted)

    def capture_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0])

    def get_capture(self, capture_id: bytes) -> CaptureRecord:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT capture_id, device_id, boot_id, request_id, profile_sha256,
                       device_config_crc32, capture_sequence,
                       sample_interval_ticks, burst_period_ticks, sample_count,
                       pretrigger_count, quality_flags, wire_frame_blob, sample_blob
                FROM captures WHERE capture_id=?
                """,
                (capture_id,),
            ).fetchall()
        if len(rows) != 1:
            raise KeyError(f"capture_id {capture_id.hex()} was not found uniquely")
        row = rows[0]
        return CaptureRecord(
            capture_id=bytes(row[0]),
            device_id=bytes(row[1]),
            boot_id=bytes(row[2]),
            request_id=bytes(row[3]),
            profile_sha256=bytes(row[4]),
            device_config_crc32=int(row[5]),
            capture_sequence=int(row[6]),
            sample_interval_ticks=int(row[7]),
            burst_period_ticks=int(row[8]),
            sample_count=int(row[9]),
            pretrigger_count=int(row[10]),
            quality_flags=int(row[11]),
            wire_frame=bytes(row[12]),
            sample_blob=bytes(row[13]),
            interpolated=False,
        )
