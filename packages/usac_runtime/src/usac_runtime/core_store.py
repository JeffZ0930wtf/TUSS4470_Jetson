"""Core-side transactional storage for raw ultrasonic capture deliveries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from enum import Enum
import hashlib
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


class SavePolicy(str, Enum):
    """User-selected lifetime for fully validated raw capture frames."""

    SAVE_NONE = "SAVE_NONE"
    SAVE_ALL = "SAVE_ALL"
    SAVE_LAST = "SAVE_LAST"


class CaptureResolution(str, Enum):
    """Durable core decision that permits bridge spool acknowledgement."""

    RAW_ARCHIVED = "RAW_ARCHIVED"
    ROLLING_LATEST = "ROLLING_LATEST"
    DISCARDED_BY_POLICY = "DISCARDED_BY_POLICY"


@dataclass(frozen=True, slots=True)
class CoreCommitResult:
    receipt: CaptureCommittedRequest
    inserted: bool
    resolution: CaptureResolution


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


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    row_id: int
    capture_id: str
    device_id: str
    boot_id: str
    capture_sequence: int
    sample_count: int
    stored_utc_ns: int
    session_id: str | None


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
                    session_id TEXT NOT NULL DEFAULT '',
                    UNIQUE(device_id, boot_id, capture_id)
                )
                """
            )
            self._migrate_m5(connection)
            self._migrate_m6_save_policy(connection)

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
            "session_id": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE captures ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS captures_session_row "
            "ON captures(session_id, row_id)"
        )
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

    @staticmethod
    def _migrate_m6_save_policy(connection: sqlite3.Connection) -> None:
        """Add bounded processing receipts and one rolling frame per session."""

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS capture_resolution_tombstones (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id BLOB NOT NULL,
                boot_id BLOB NOT NULL,
                capture_id BLOB NOT NULL,
                inner_frame_crc32 INTEGER NOT NULL,
                inner_frame_sha256 BLOB NOT NULL,
                resolution TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                resolved_utc_ns INTEGER NOT NULL,
                UNIQUE(device_id, boot_id, capture_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_latest_captures (
                session_id TEXT PRIMARY KEY,
                connection_id INTEGER NOT NULL,
                spool_record_id INTEGER NOT NULL,
                source_connection_id INTEGER NOT NULL,
                source_first_stream_offset INTEGER NOT NULL,
                source_last_stream_offset INTEGER NOT NULL,
                stored_utc_ns INTEGER NOT NULL,
                inner_frame_blob BLOB NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS acquisition_sessions (
                session_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                save_policy TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                updated_utc_ns INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_delivery_stats (
                session_id TEXT PRIMARY KEY,
                acquired_count INTEGER NOT NULL,
                last_capture_id BLOB
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_policy_contexts (
                device_id BLOB NOT NULL,
                boot_id BLOB NOT NULL,
                session_id TEXT NOT NULL,
                save_policy TEXT NOT NULL,
                PRIMARY KEY(device_id, boot_id)
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

    def register_delivery_policy(
        self,
        *,
        device_id: bytes,
        boot_id: bytes,
        session_id: str,
        save_policy: SavePolicy | str,
    ) -> None:
        """Bind bridge replay for one device boot to its host-only save policy.

        Save policy and session ID are intentionally absent from the device wire
        protocol. Persisting this small context before starting device work lets
        a newly connected core resolve bridge-spooled frames without silently
        changing SAVE_NONE or SAVE_LAST into SAVE_ALL.
        """

        if len(device_id) != 16 or len(boot_id) != 16:
            raise ValueError("device_id and boot_id must encode exactly 16 bytes")
        normalized_session = self._normalize_session_id(session_id)
        try:
            policy = SavePolicy(save_policy)
        except ValueError as error:
            raise ValueError("save_policy is invalid") from error
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO delivery_policy_contexts (
                    device_id, boot_id, session_id, save_policy
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id, boot_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    save_policy=excluded.save_policy
                """,
                (device_id, boot_id, normalized_session, policy.value),
            )
            # Only the latest boot contexts are useful for bounded bridge replay.
            connection.execute(
                """
                DELETE FROM delivery_policy_contexts
                WHERE rowid NOT IN (
                    SELECT rowid FROM delivery_policy_contexts
                    ORDER BY rowid DESC LIMIT 256
                )
                """
            )

    def commit_replayed_delivery(self, delivery: BridgeCaptureDelivery) -> CoreCommitResult:
        """Resolve a bridge-spooled frame using its pre-registered host policy."""

        encode_bridge_capture_delivery(delivery)
        capture = decode_capture_data(decode_frame(delivery.inner_frame).payload)
        with self._connect() as connection:
            # Reserve the writer before reading session state. Finalization and
            # the replay decision therefore cannot cross between transactions.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT 1 FROM capture_resolution_tombstones
                WHERE device_id=? AND boot_id=? AND capture_id=?
                """,
                (capture.device_id, capture.boot_id, capture.capture_id),
            ).fetchone()
            context = connection.execute(
                """
                SELECT session_id, save_policy FROM delivery_policy_contexts
                WHERE device_id=? AND boot_id=?
                """,
                (capture.device_id, capture.boot_id),
            ).fetchone()
            terminal = (
                None
                if context is None
                else connection.execute(
                    """
                    SELECT state, summary_json FROM acquisition_sessions
                    WHERE session_id=?
                    """,
                    (str(context[0]),),
                ).fetchone()
            )
            if existing is not None:
                # commit_delivery returns the durable prior decision without
                # applying its default policy, so ACK retries stay idempotent.
                return self.commit_delivery(delivery, _connection=connection)
            if context is None:
                raise RuntimeError(
                    "replayed capture has no registered save-policy context; "
                    "bridge spool must remain pending"
                )
            policy = SavePolicy(str(context[1]))
            if terminal is not None and str(terminal[0]) not in {"RUNNING", "STOPPING"}:
                return self._commit_terminal_replay(
                    delivery,
                    capture=capture,
                    session_id=str(context[0]),
                    save_policy=policy,
                    summary=dict(json.loads(str(terminal[1]))),
                    _connection=connection,
                )
            return self.commit_delivery(
                delivery,
                save_policy=policy,
                session_id=str(context[0]),
                _connection=connection,
            )

    def _commit_terminal_replay(
        self,
        delivery: BridgeCaptureDelivery,
        *,
        capture,
        session_id: str,
        save_policy: SavePolicy,
        summary: Mapping[str, object],
        _connection: sqlite3.Connection | None = None,
    ) -> CoreCommitResult:
        """Atomically absorb a late bridge frame into an already closed run."""

        frame = decode_frame(delivery.inner_frame)
        inner_crc = crc32_iso_hdlc(delivery.inner_frame)
        inner_sha = hashlib.sha256(delivery.inner_frame).digest()
        receipt = self._receipt(
            delivery,
            device_id=capture.device_id,
            boot_id=capture.boot_id,
            capture_id=capture.capture_id,
            inner_frame_crc32=inner_crc,
        )
        connection_scope = (
            self._connect() if _connection is None else nullcontext(_connection)
        )
        with connection_scope as connection:
            if _connection is None:
                connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT inner_frame_crc32, inner_frame_sha256, resolution
                FROM capture_resolution_tombstones
                WHERE device_id=? AND boot_id=? AND capture_id=?
                """,
                (capture.device_id, capture.boot_id, capture.capture_id),
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != inner_crc or bytes(existing[1]) != inner_sha:
                    raise StorageConflictError(
                        "capture identity already exists with a different frame"
                    )
                return CoreCommitResult(
                    receipt,
                    False,
                    CaptureResolution(str(existing[2])),
                )

            if save_policy is SavePolicy.SAVE_LAST:
                # A late frame is newer than the frame frozen at shutdown. Keep
                # exactly one archive row and reclassify the superseded decision.
                connection.execute(
                    """
                    DELETE FROM capture_events WHERE capture_row_id IN (
                        SELECT row_id FROM captures WHERE session_id=?
                    )
                    """,
                    (session_id,),
                )
                connection.execute("DELETE FROM captures WHERE session_id=?", (session_id,))
                connection.execute(
                    """
                    UPDATE capture_resolution_tombstones SET resolution=?
                    WHERE session_id=?
                    """,
                    (CaptureResolution.DISCARDED_BY_POLICY.value, session_id),
                )

            if save_policy is SavePolicy.SAVE_NONE:
                resolution = CaptureResolution.DISCARDED_BY_POLICY
            else:
                self._archive_delivery(
                    connection,
                    delivery,
                    frame,
                    capture,
                    inner_crc,
                    forced_session_id=session_id,
                )
                resolution = CaptureResolution.RAW_ARCHIVED

            connection.execute(
                """
                INSERT INTO capture_resolution_tombstones (
                    device_id, boot_id, capture_id, inner_frame_crc32,
                    inner_frame_sha256, resolution, session_id, resolved_utc_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture.device_id,
                    capture.boot_id,
                    capture.capture_id,
                    inner_crc,
                    inner_sha,
                    resolution.value,
                    session_id,
                    delivery.stored_utc_ns,
                ),
            )
            connection.execute(
                """
                INSERT INTO session_delivery_stats (
                    session_id, acquired_count, last_capture_id
                ) VALUES (?, 1, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    acquired_count=acquired_count + 1,
                    last_capture_id=excluded.last_capture_id
                """,
                (session_id, capture.capture_id),
            )
            self._prune_resolutions(connection)
            connection.execute(
                """
                DELETE FROM configuration_contexts
                WHERE profile_sha256=? AND device_config_crc32=? AND request_id=?
                """,
                (
                    capture.profile_sha256,
                    capture.device_config_crc32,
                    capture.request_id,
                ),
            )
            self._finalize_session_summary_in_connection(
                connection,
                dict(summary),
                save_policy,
            )
        return CoreCommitResult(receipt, True, resolution)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open one transaction scope and deterministically release its handle."""

        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            # sqlite3.Connection.__exit__ commits or rolls back but does not
            # close. The outer finally is required for bounded long-run handles.
            with connection:
                yield connection
        finally:
            connection.close()

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

    @staticmethod
    def _normalize_session_id(session_id: str | None) -> str:
        if not session_id:
            return ""
        try:
            raw = bytes.fromhex(session_id)
        except ValueError as error:
            raise ValueError("session_id must be hexadecimal text") from error
        if len(raw) != 16:
            raise ValueError("session_id must encode exactly 16 bytes")
        return raw.hex()

    @staticmethod
    def _configuration_json(capture) -> str:
        return json.dumps(
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

    def _archive_delivery(
        self,
        connection: sqlite3.Connection,
        delivery: BridgeCaptureDelivery,
        frame,
        capture,
        inner_crc: int,
        *,
        forced_session_id: str = "",
    ) -> bool:
        """Insert one immutable capture using the context bound to its request."""

        configuration = self._configuration_json(capture)
        context = connection.execute(
            """
            SELECT requested_config_json, encoded_config_json,
                   readback_config_json, actual_config_json, run_plan_json
            FROM configuration_contexts
            WHERE profile_sha256=? AND device_config_crc32=? AND request_id=?
            """,
            (capture.profile_sha256, capture.device_config_crc32, capture.request_id),
        ).fetchone()
        context_values = tuple(context) if context is not None else (
            "{}", configuration, "{}", "{}", "{}"
        )
        run_plan = json.loads(context_values[4])
        session_id = forced_session_id or self._normalize_session_id(
            run_plan.get("session_id", "")
        )
        existing = connection.execute(
            """
            SELECT inner_frame_crc32, wire_frame_blob FROM captures
            WHERE device_id=? AND boot_id=? AND capture_id=?
            """,
            (capture.device_id, capture.boot_id, capture.capture_id),
        ).fetchone()
        if existing is not None:
            if int(existing[0]) != inner_crc or bytes(existing[1]) != delivery.inner_frame:
                raise StorageConflictError(
                    "capture identity already exists with a different frame"
                )
            return False

        sample_bytes = capture.sample_count * 2
        sample_blob = frame.payload[-sample_bytes:] if sample_bytes else b""
        adc_clipping = any(
            sample in (0, (1 << capture.adc_bits) - 1) for sample in capture.samples
        )
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
                transport_crc32, stored_utc_ns, session_id
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                session_id,
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
        return True

    @staticmethod
    def _prune_resolutions(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM capture_resolution_tombstones
            WHERE row_id NOT IN (
                SELECT row_id FROM capture_resolution_tombstones
                ORDER BY row_id DESC LIMIT 4096
            )
            """
        )

    def commit_delivery(
        self,
        delivery: BridgeCaptureDelivery,
        *,
        save_policy: SavePolicy | str = SavePolicy.SAVE_ALL,
        session_id: str | None = None,
        _connection: sqlite3.Connection | None = None,
    ) -> CoreCommitResult:
        """Commit one terminal processing decision before acknowledging spool."""

        try:
            policy = SavePolicy(save_policy)
        except ValueError as error:
            raise ValueError("save_policy is invalid") from error
        normalized_session = self._normalize_session_id(session_id)
        if policy is not SavePolicy.SAVE_ALL and not normalized_session:
            raise ValueError("SAVE_NONE and SAVE_LAST require a session_id")

        # Reusing the protocol encoder keeps core validation byte-identical to
        # bridge validation and ensures even discarded frames are complete.
        encode_bridge_capture_delivery(delivery)
        frame = decode_frame(delivery.inner_frame)
        capture = decode_capture_data(frame.payload)
        inner_crc = crc32_iso_hdlc(delivery.inner_frame)
        inner_sha = hashlib.sha256(delivery.inner_frame).digest()
        receipt = self._receipt(
            delivery,
            device_id=capture.device_id,
            boot_id=capture.boot_id,
            capture_id=capture.capture_id,
            inner_frame_crc32=inner_crc,
        )

        inserted = False
        resolution = CaptureResolution.RAW_ARCHIVED
        connection_scope = (
            self._connect() if _connection is None else nullcontext(_connection)
        )
        with connection_scope as connection:
            if _connection is None:
                connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT inner_frame_crc32, inner_frame_sha256, resolution
                FROM capture_resolution_tombstones
                WHERE device_id=? AND boot_id=? AND capture_id=?
                """,
                (capture.device_id, capture.boot_id, capture.capture_id),
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != inner_crc or bytes(existing[1]) != inner_sha:
                    raise StorageConflictError(
                        "capture identity already exists with a different frame"
                    )
                resolution = CaptureResolution(str(existing[2]))
            else:
                if policy is SavePolicy.SAVE_ALL:
                    inserted = self._archive_delivery(
                        connection,
                        delivery,
                        frame,
                        capture,
                        inner_crc,
                        forced_session_id=normalized_session,
                    )
                    resolution = CaptureResolution.RAW_ARCHIVED
                elif policy is SavePolicy.SAVE_LAST:
                    previous_row = connection.execute(
                        "SELECT inner_frame_blob FROM session_latest_captures WHERE session_id=?",
                        (normalized_session,),
                    ).fetchone()
                    connection.execute(
                        """
                        INSERT INTO session_latest_captures (
                            session_id, connection_id, spool_record_id,
                            source_connection_id, source_first_stream_offset,
                            source_last_stream_offset, stored_utc_ns, inner_frame_blob
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id) DO UPDATE SET
                            connection_id=excluded.connection_id,
                            spool_record_id=excluded.spool_record_id,
                            source_connection_id=excluded.source_connection_id,
                            source_first_stream_offset=excluded.source_first_stream_offset,
                            source_last_stream_offset=excluded.source_last_stream_offset,
                            stored_utc_ns=excluded.stored_utc_ns,
                            inner_frame_blob=excluded.inner_frame_blob
                        """,
                        (
                            normalized_session,
                            delivery.connection_id,
                            delivery.spool_record_id,
                            delivery.source_connection_id,
                            delivery.source_first_stream_offset,
                            delivery.source_last_stream_offset,
                            delivery.stored_utc_ns,
                            delivery.inner_frame,
                        ),
                    )
                    inserted = True
                    resolution = CaptureResolution.ROLLING_LATEST
                    if previous_row is not None:
                        previous = decode_capture_data(
                            decode_frame(bytes(previous_row[0])).payload
                        )
                        previous_key = (
                            previous.profile_sha256,
                            previous.device_config_crc32,
                            previous.request_id,
                        )
                        current_key = (
                            capture.profile_sha256,
                            capture.device_config_crc32,
                            capture.request_id,
                        )
                        if previous_key != current_key:
                            connection.execute(
                                """
                                DELETE FROM configuration_contexts
                                WHERE profile_sha256=? AND device_config_crc32=?
                                  AND request_id=?
                                """,
                                previous_key,
                            )
                else:
                    inserted = True
                    resolution = CaptureResolution.DISCARDED_BY_POLICY
                connection.execute(
                    """
                    INSERT INTO capture_resolution_tombstones (
                        device_id, boot_id, capture_id, inner_frame_crc32,
                        inner_frame_sha256, resolution, session_id, resolved_utc_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture.device_id,
                        capture.boot_id,
                        capture.capture_id,
                        inner_crc,
                        inner_sha,
                        resolution.value,
                        normalized_session,
                        delivery.stored_utc_ns,
                    ),
                )
                if normalized_session:
                    connection.execute(
                        """
                        INSERT INTO session_delivery_stats (
                            session_id, acquired_count, last_capture_id
                        ) VALUES (?, 1, ?)
                        ON CONFLICT(session_id) DO UPDATE SET
                            acquired_count=acquired_count + 1,
                            last_capture_id=excluded.last_capture_id
                        """,
                        (normalized_session, capture.capture_id),
                    )
                self._prune_resolutions(connection)
            if resolution is not CaptureResolution.ROLLING_LATEST:
                # Context rows are staging data; archives already contain their
                # own immutable copies and SAVE_NONE intentionally keeps none.
                connection.execute(
                    """
                    DELETE FROM configuration_contexts
                    WHERE profile_sha256=? AND device_config_crc32=? AND request_id=?
                    """,
                    (
                        capture.profile_sha256,
                        capture.device_config_crc32,
                        capture.request_id,
                    ),
                )

        return CoreCommitResult(receipt, inserted, resolution)

    def latest_capture_count(self, session_id: str) -> int:
        normalized = self._normalize_session_id(session_id)
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM session_latest_captures WHERE session_id=?",
                    (normalized,),
                ).fetchone()[0]
            )

    def resolution_count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM capture_resolution_tombstones"
                ).fetchone()[0]
            )

    def finalize_latest_capture(self, session_id: str) -> bytes | None:
        """Atomically move one session's rolling frame into the archive."""

        normalized = self._normalize_session_id(session_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._finalize_latest_capture_in_connection(connection, normalized)

    def _finalize_latest_capture_in_connection(
        self,
        connection: sqlite3.Connection,
        normalized_session: str,
    ) -> bytes | None:
        row = connection.execute(
                """
                SELECT connection_id, spool_record_id, source_connection_id,
                       source_first_stream_offset, source_last_stream_offset,
                       stored_utc_ns, inner_frame_blob
                FROM session_latest_captures WHERE session_id=?
                """,
                (normalized_session,),
            ).fetchone()
        if row is None:
            return None
        delivery = BridgeCaptureDelivery(
            connection_id=int(row[0]),
            spool_record_id=int(row[1]),
            source_connection_id=int(row[2]),
            source_first_stream_offset=int(row[3]),
            source_last_stream_offset=int(row[4]),
            stored_utc_ns=int(row[5]),
            inner_frame=bytes(row[6]),
        )
        frame = decode_frame(delivery.inner_frame)
        capture = decode_capture_data(frame.payload)
        inner_crc = crc32_iso_hdlc(delivery.inner_frame)
        self._archive_delivery(
            connection,
            delivery,
            frame,
            capture,
            inner_crc,
            forced_session_id=normalized_session,
        )
        connection.execute(
                """
                DELETE FROM configuration_contexts
                WHERE profile_sha256=? AND device_config_crc32=? AND request_id=?
                """,
                (
                    capture.profile_sha256,
                    capture.device_config_crc32,
                    capture.request_id,
                ),
            )
        connection.execute(
            "DELETE FROM session_latest_captures WHERE session_id=?",
            (normalized_session,),
        )
        connection.execute(
                """
                UPDATE capture_resolution_tombstones SET resolution=?
                WHERE device_id=? AND boot_id=? AND capture_id=?
                """,
                (
                    CaptureResolution.RAW_ARCHIVED.value,
                    capture.device_id,
                    capture.boot_id,
                    capture.capture_id,
                ),
            )
        return capture.capture_id

    @staticmethod
    def _upsert_session_summary(
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        canonical: str,
    ) -> None:
        updated_utc_ns = int(
            payload.get("finished_utc_ns") or payload.get("started_utc_ns") or 0
        )
        connection.execute(
            """
            INSERT INTO acquisition_sessions (
                session_id, state, save_policy, summary_json, updated_utc_ns
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                state=excluded.state,
                save_policy=excluded.save_policy,
                summary_json=excluded.summary_json,
                updated_utc_ns=excluded.updated_utc_ns
            """,
            (
                payload["session_id"],
                payload["state"],
                payload["save_policy"],
                canonical,
                updated_utc_ns,
            ),
        )

    def save_session_summary(self, summary: Mapping[str, object]) -> None:
        """Persist bounded run accounting without storing another waveform copy."""

        session_id = self._normalize_session_id(str(summary.get("session_id", "")))
        state = str(summary.get("state", ""))
        try:
            policy = SavePolicy(str(summary.get("save_policy", "")))
        except ValueError as error:
            raise ValueError("session summary save_policy is invalid") from error
        if not state:
            raise ValueError("session summary state is required")
        payload = dict(summary)
        payload["session_id"] = session_id
        canonical = self._canonical_json(payload)
        with self._connect() as connection:
            self._upsert_session_summary(connection, payload, canonical)

    def finalize_session_summary(
        self, summary: Mapping[str, object]
    ) -> dict[str, object]:
        """Atomically freeze SAVE_LAST data and persist one terminal summary."""

        session_id = self._normalize_session_id(str(summary.get("session_id", "")))
        state = str(summary.get("state", ""))
        if state in {"", "RUNNING", "STOPPING"}:
            raise ValueError("final session summary requires a terminal state")
        try:
            policy = SavePolicy(str(summary.get("save_policy", "")))
        except ValueError as error:
            raise ValueError("session summary save_policy is invalid") from error
        payload = dict(summary)
        payload["session_id"] = session_id
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._finalize_session_summary_in_connection(
                connection,
                payload,
                policy,
            )

    def _finalize_session_summary_in_connection(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, object],
        policy: SavePolicy,
    ) -> dict[str, object]:
        """Finalize accounting inside a caller-owned SQLite transaction."""

        session_id = self._normalize_session_id(str(payload.get("session_id", "")))
        payload["session_id"] = session_id
        stats = connection.execute(
            """
            SELECT acquired_count, last_capture_id FROM session_delivery_stats
            WHERE session_id=?
            """,
            (session_id,),
        ).fetchone()
        resolution_rows = connection.execute(
            """
            SELECT capture_id FROM capture_resolution_tombstones
            WHERE session_id=? ORDER BY row_id
            """,
            (session_id,),
        ).fetchall()
        acquired = int(stats[0]) if stats is not None else len(resolution_rows)
        payload["acquired_count"] = acquired
        if "capture_count" in payload:
            payload["capture_count"] = acquired
        last_capture_id = (
            bytes(stats[1]) if stats is not None and stats[1] is not None
            else bytes(resolution_rows[-1][0]) if resolution_rows
            else None
        )
        if last_capture_id is not None:
            payload["last_capture_id"] = last_capture_id.hex()

        if policy is SavePolicy.SAVE_LAST:
            self._finalize_latest_capture_in_connection(connection, session_id)

        archived_rows = connection.execute(
            "SELECT capture_id FROM captures WHERE session_id=? ORDER BY row_id",
            (session_id,),
        ).fetchall()
        saved = len(archived_rows)
        payload["saved_count"] = saved
        payload["discarded_by_policy_count"] = max(0, acquired - saved)
        payload["last_saved_capture_id"] = (
            bytes(archived_rows[-1][0]).hex() if archived_rows else None
        )
        canonical = self._canonical_json(payload)
        self._upsert_session_summary(connection, payload, canonical)
        return payload

    def get_session_summary(self, session_id: str) -> dict[str, object]:
        normalized = self._normalize_session_id(session_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT summary_json FROM acquisition_sessions WHERE session_id=?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise KeyError(normalized)
        return dict(json.loads(str(row[0])))

    def reconcile_interrupted_sessions(self) -> int:
        """Close sessions abandoned by a prior core process without resuming IO."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, summary_json FROM acquisition_sessions
                WHERE state IN ('RUNNING', 'STOPPING')
                """
            ).fetchall()
        for session_id, raw_summary in rows:
            summary = dict(json.loads(str(raw_summary)))
            summary["state"] = "INTERRUPTED"
            summary["terminal_reason"] = "CORE_RESTART"
            self.finalize_session_summary(summary)
        return len(rows)

    def capture_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0])

    def list_captures(
        self,
        *,
        after_row_id: int = 0,
        limit: int = 50,
        session_id: str | None = None,
    ) -> tuple[tuple[CaptureSummary, ...], int | None]:
        """Read one stable page of metadata without waveform or frame BLOBs."""

        if after_row_id < 0:
            raise ValueError("after_row_id must not be negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be in 1..100")
        normalized_session_id: str | None = None
        if session_id is not None:
            try:
                session_bytes = bytes.fromhex(session_id)
            except ValueError as error:
                raise ValueError("session_id must be hexadecimal") from error
            if len(session_bytes) != 16:
                raise ValueError("session_id must encode exactly 16 bytes")
            normalized_session_id = session_bytes.hex()
        with self._connect() as connection:
            if normalized_session_id is None:
                rows = connection.execute(
                    """
                    SELECT row_id, capture_id, device_id, boot_id, capture_sequence,
                           sample_count, stored_utc_ns, session_id
                    FROM captures
                    WHERE row_id > ?
                    ORDER BY row_id
                    LIMIT ?
                    """,
                    (after_row_id, limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT row_id, capture_id, device_id, boot_id, capture_sequence,
                           sample_count, stored_utc_ns, session_id
                    FROM captures
                    WHERE row_id > ? AND session_id = ?
                    ORDER BY row_id
                    LIMIT ?
                    """,
                    (after_row_id, normalized_session_id, limit + 1),
                ).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        items = tuple(
            CaptureSummary(
                row_id=int(row[0]),
                capture_id=bytes(row[1]).hex(),
                device_id=bytes(row[2]).hex(),
                boot_id=bytes(row[3]).hex(),
                capture_sequence=int(row[4]),
                sample_count=int(row[5]),
                stored_utc_ns=int(row[6]),
                session_id=str(row[7]) or None,
            )
            for row in page
        )
        next_cursor = int(page[-1][0]) if has_more else None
        return items, next_cursor

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
