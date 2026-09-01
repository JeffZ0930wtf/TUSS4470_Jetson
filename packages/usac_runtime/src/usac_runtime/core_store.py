"""Core-side transactional storage for raw ultrasonic capture deliveries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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
    tuss_dev_stat: int
    transport_crc32: int
    wire_frame: bytes
    sample_blob: bytes
    requested_config: dict[str, object]
    encoded_config: dict[str, object]
    readback_config: dict[str, object]
    actual_config: dict[str, object]
    run_plan: dict[str, object]
    adc_clipping: bool
    interpolated: bool


@dataclass(frozen=True, slots=True)
class CaptureEventRecord:
    ordinal: int
    channel: int
    edge: int
    capture_method: int
    level_after: int
    sample_index: int
    subsample_tick: int
    uncertainty_ticks: int
    frame_offset_ticks: int


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
                    requested_config_json TEXT NOT NULL DEFAULT '{}',
                    encoded_config_json TEXT NOT NULL DEFAULT '{}',
                    readback_config_json TEXT NOT NULL DEFAULT '{}',
                    actual_config_json TEXT NOT NULL DEFAULT '{}',
                    run_plan_json TEXT NOT NULL DEFAULT '{}',
                    adc_clipping INTEGER NOT NULL DEFAULT 0,
                    transport_crc32 INTEGER NOT NULL DEFAULT 0,
                    stored_utc_ns INTEGER NOT NULL,
                    UNIQUE(device_id, boot_id, capture_id)
                )
                """
            )
            self._migrate_m5(connection)

    @staticmethod
    def _migrate_m5(connection: sqlite3.Connection) -> None:
        """Add M5 metadata without replacing an existing M4 capture table."""

        columns = {row[1] for row in connection.execute("PRAGMA table_info(captures)")}
        additions = {
            "requested_config_json": "TEXT NOT NULL DEFAULT '{}'",
            "encoded_config_json": "TEXT NOT NULL DEFAULT '{}'",
            "readback_config_json": "TEXT NOT NULL DEFAULT '{}'",
            "actual_config_json": "TEXT NOT NULL DEFAULT '{}'",
            "run_plan_json": "TEXT NOT NULL DEFAULT '{}'",
            "adc_clipping": "INTEGER NOT NULL DEFAULT 0",
            "transport_crc32": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE captures ADD COLUMN {name} {definition}")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS configuration_contexts (
                profile_sha256 BLOB NOT NULL,
                device_config_crc32 INTEGER NOT NULL,
                request_id BLOB NOT NULL,
                requested_config_json TEXT NOT NULL,
                encoded_config_json TEXT NOT NULL,
                readback_config_json TEXT NOT NULL,
                actual_config_json TEXT NOT NULL,
                run_plan_json TEXT NOT NULL,
                PRIMARY KEY(profile_sha256, device_config_crc32, request_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS capture_events (
                capture_row_id INTEGER NOT NULL REFERENCES captures(row_id),
                ordinal INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                edge INTEGER NOT NULL,
                capture_method INTEGER NOT NULL,
                level_after INTEGER NOT NULL,
                sample_index INTEGER NOT NULL,
                subsample_tick INTEGER NOT NULL,
                uncertainty_ticks INTEGER NOT NULL,
                frame_offset_ticks INTEGER NOT NULL,
                PRIMARY KEY(capture_row_id, ordinal)
            )
            """
        )

    @staticmethod
    def _canonical_json(value: Mapping[str, object]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def save_configuration_context(
        self,
        *,
        profile_sha256: bytes,
        device_config_crc32: int,
        request_id: bytes,
        requested: Mapping[str, object],
        encoded: Mapping[str, object],
        readback: Mapping[str, object],
        actual: Mapping[str, object],
        run_plan: Mapping[str, object],
    ) -> None:
        """Persist the host context that a later CAPTURE_DATA hash/CRC binds."""

        if len(profile_sha256) != 32:
            raise ValueError("profile_sha256 must be 32 bytes")
        if len(request_id) != 16:
            raise ValueError("request_id must be 16 bytes")
        values = tuple(
            self._canonical_json(item)
            for item in (requested, encoded, readback, actual, run_plan)
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO configuration_contexts (
                    profile_sha256, device_config_crc32, request_id,
                    requested_config_json,
                    encoded_config_json, readback_config_json, actual_config_json,
                    run_plan_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_sha256, device_config_crc32, request_id) DO UPDATE SET
                    requested_config_json=excluded.requested_config_json,
                    encoded_config_json=excluded.encoded_config_json,
                    readback_config_json=excluded.readback_config_json,
                    actual_config_json=excluded.actual_config_json,
                    run_plan_json=excluded.run_plan_json
                """,
                (profile_sha256, device_config_crc32, request_id, *values),
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
        adc_clipping = any(sample in (0, (1 << capture.adc_bits) - 1) for sample in capture.samples)
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
            context = connection.execute(
                """
                SELECT requested_config_json, encoded_config_json,
                       readback_config_json, actual_config_json, run_plan_json
                FROM configuration_contexts
                WHERE profile_sha256=? AND device_config_crc32=? AND request_id=?
                """,
                (
                    capture.profile_sha256,
                    capture.device_config_crc32,
                    capture.request_id,
                ),
            ).fetchone()
            context_values = tuple(context) if context is not None else (
                "{}", configuration, "{}", "{}", "{}"
            )
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
                        configuration_json, requested_config_json,
                        encoded_config_json, readback_config_json,
                        actual_config_json, run_plan_json, adc_clipping,
                        transport_crc32, stored_utc_ns
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                        *context_values,
                        int(adc_clipping),
                        inner_crc,
                        delivery.stored_utc_ns,
                    ),
                )
                capture_row_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                connection.executemany(
                    """
                    INSERT INTO capture_events (
                        capture_row_id, ordinal, channel, edge, capture_method,
                        level_after, sample_index, subsample_tick,
                        uncertainty_ticks, frame_offset_ticks
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            capture_row_id,
                            ordinal,
                            event.channel,
                            event.edge,
                            event.capture_method,
                            event.level_after,
                            event.sample_index,
                            event.subsample_tick,
                            event.uncertainty_ticks,
                            event.frame_offset_ticks,
                        )
                        for ordinal, event in enumerate(capture.events)
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
                       pretrigger_count, quality_flags, tuss_dev_stat,
                       inner_frame_crc32, wire_frame_blob, sample_blob,
                       requested_config_json, encoded_config_json,
                       readback_config_json, actual_config_json, run_plan_json,
                       adc_clipping
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
            tuss_dev_stat=int(row[12]),
            transport_crc32=int(row[13]),
            wire_frame=bytes(row[14]),
            sample_blob=bytes(row[15]),
            requested_config=json.loads(row[16]),
            encoded_config=json.loads(row[17]),
            readback_config=json.loads(row[18]),
            actual_config=json.loads(row[19]),
            run_plan=json.loads(row[20]),
            adc_clipping=bool(row[21]),
            interpolated=False,
        )

    def get_capture_events(self, capture_id: bytes) -> tuple[CaptureEventRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event.ordinal, event.channel, event.edge,
                       event.capture_method, event.level_after, event.sample_index,
                       event.subsample_tick, event.uncertainty_ticks,
                       event.frame_offset_ticks
                FROM capture_events AS event
                JOIN captures AS capture ON capture.row_id=event.capture_row_id
                WHERE capture.capture_id=?
                ORDER BY event.ordinal
                """,
                (capture_id,),
            ).fetchall()
        return tuple(CaptureEventRecord(*map(int, row)) for row in rows)
