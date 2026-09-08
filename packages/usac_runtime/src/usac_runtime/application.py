"""Shared M5 application service used by REST, CLI, and browser clients.

Interface adapters call this object instead of reaching into the parameter
schema, device simulator, serial transport, or executor independently. This
keeps semantic validation and configuration identity consistent everywhere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
import threading
import time
from typing import Protocol
import uuid

from usac_protocol.bridge_messages import BridgeCaptureDelivery
from usac_protocol.capture_data import CaptureData

from .core_store import CaptureRecord, CaptureStore
from .device_executor import ConfigConflictError, ExecutedCapture, SingleDeviceExecutor
from .parameter_service import ConfigurationSnapshot, ParameterService, ValidationResult
from .periodic_lease import PeriodicLeaseController, PeriodicSchedule
from .run_plan import RunPlanV1, SweepPlan, compile_run_steps


class ApplicationDevice(Protocol):
    boot_id: bytes | None

    def capture_wire_frame(self, capture_id: bytes) -> bytes: ...


class ConfigurationEtagConflict(RuntimeError):
    """The caller based a mutation on an obsolete APPLIED configuration."""


class CaptureStorageUnavailable(RuntimeError):
    """Capture was refused before device IO because no durable store exists."""


class SessionConflict(RuntimeError):
    """A request conflicts with the one active device run session."""


@dataclass(slots=True)
class _PeriodicSession:
    session_id: bytes
    schedule: PeriodicSchedule
    state: str = "RUNNING"
    capture_count: int = 0
    capture_ids: deque[str] = field(default_factory=lambda: deque(maxlen=100))
    error: str | None = None
    started_utc_ns: int = field(default_factory=time.time_ns)
    finished_utc_ns: int | None = None
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    # A periodic frame can arrive inside a renewal call on this same worker.
    control_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    async_handler: object | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)


@dataclass(slots=True)
class _SweepSession:
    session_id: bytes
    plan: RunPlanV1
    state: str = "RUNNING"
    capture_count: int = 0
    capture_ids: deque[str] = field(default_factory=lambda: deque(maxlen=100))
    error: str | None = None
    started_utc_ns: int = field(default_factory=time.time_ns)
    finished_utc_ns: int | None = None
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    control_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)


def _json_value(value: object) -> object:
    """Convert typed protocol/domain values into stable JSON-compatible data."""

    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class AcquisitionApplication:
    """Own the interface-neutral first-version acquisition use cases."""

    def __init__(
        self,
        service: ParameterService,
        executor: SingleDeviceExecutor,
        device: ApplicationDevice,
        *,
        store: CaptureStore | None = None,
        session_history_limit: int = 100,
    ) -> None:
        if session_history_limit < 1:
            raise ValueError("session_history_limit must be positive")
        self._service = service
        self._executor = executor
        self._device = device
        self._store = store
        self._local_spool_record_id = 0
        self._session_lock = threading.Lock()
        self._session_history_limit = session_history_limit
        self._sessions: dict[bytes, _PeriodicSession | _SweepSession] = {}

    @staticmethod
    def _snapshot(snapshot: ConfigurationSnapshot) -> dict[str, object]:
        return {
            "state": snapshot.state.value,
            "requested": _json_value(snapshot.requested),
            "actual": _json_value(snapshot.actual),
            "readback": _json_value(snapshot.readback),
        }

    @staticmethod
    def _validation(result: ValidationResult) -> dict[str, object]:
        payload = AcquisitionApplication._snapshot(result.snapshot)
        payload["errors"] = [
            {
                "field": error.field,
                "code": error.code.value,
                "message": error.message,
            }
            for error in result.errors
        ]
        return payload

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def device(self) -> dict[str, object]:
        hello = self._device.hello
        return {
            "device_id": hello.device_id.hex(),
            "boot_id": hello.boot_id.hex(),
            "firmware": {
                "major": hello.fw_major,
                "minor": hello.fw_minor,
                "patch": hello.fw_patch,
                "build": hello.fw_build,
            },
            "capabilities": _json_value(self._executor.capabilities()),
            "status": _json_value(self._executor.status()),
        }

    def schema(self) -> dict[str, object]:
        return self._service.registry_view()

    def etag(self) -> str:
        return self._executor.applied_etag()

    def config(self) -> dict[str, object]:
        return self._snapshot(self._executor.snapshot())

    def validate_config(self, changes: dict[str, object]) -> dict[str, object]:
        return self._validation(self._executor.preview_changes(changes))

    def save_draft(self, changes: dict[str, object]) -> dict[str, object]:
        """Publish semantic edits for every interface without device I/O."""

        self._require_idle()
        return self._snapshot(self._executor.update_draft(changes))

    def apply_config(
        self,
        changes: dict[str, object],
        *,
        expected_etag: str,
    ) -> dict[str, object]:
        self._require_idle()
        if expected_etag != self.etag():
            raise ConfigurationEtagConflict("If-Match does not match current config")
        return self._snapshot(self._executor.apply_changes(changes))

    @staticmethod
    def _capture_payload(
        record: CaptureRecord,
        *,
        events: tuple[object, ...],
    ) -> dict[str, object]:
        return {
            "capture_id": record.capture_id.hex(),
            "device_id": record.device_id.hex(),
            "boot_id": record.boot_id.hex(),
            "request_id": record.request_id.hex(),
            "profile_sha256": record.profile_sha256.hex(),
            "device_config_crc32": record.device_config_crc32,
            "capture_sequence": record.capture_sequence,
            "sample_interval_ticks": record.sample_interval_ticks,
            "burst_period_ticks": record.burst_period_ticks,
            "sample_count": record.sample_count,
            "pretrigger_count": record.pretrigger_count,
            "quality_flags": record.quality_flags,
            "tuss_dev_stat": record.tuss_dev_stat,
            "transport_crc32": record.transport_crc32,
            "requested_config": record.requested_config,
            "encoded_config": record.encoded_config,
            "readback_config": record.readback_config,
            "actual_config": record.actual_config,
            "run_plan": record.run_plan,
            "adc_clipping": record.adc_clipping,
            "interpolated": False,
            "events": [_json_value(event) for event in events],
        }

    def _require_store(self) -> CaptureStore:
        if self._store is None:
            raise CaptureStorageUnavailable("capture storage is not configured")
        return self._store

    def _persist_capture(
        self,
        capture: CaptureData,
        *,
        run_plan: dict[str, object],
        snapshot: ConfigurationSnapshot | None = None,
    ) -> dict[str, object]:
        store = self._require_store()
        snapshot = snapshot or self._executor.snapshot()
        encoded = {
            "sample_interval_ticks": capture.sample_interval_ticks,
            "burst_period_ticks": capture.burst_period_ticks,
            "register_pairs": [list(pair) for pair in capture.register_pairs],
        }
        store.save_configuration_context(
            profile_sha256=capture.profile_sha256,
            device_config_crc32=capture.device_config_crc32,
            request_id=capture.request_id,
            requested=snapshot.requested,
            encoded=encoded,
            readback=snapshot.readback,
            actual=snapshot.actual,
            run_plan=run_plan,
        )
        wire_frame = self._device.capture_wire_frame(capture.capture_id)
        delivery = self._device.capture_delivery(capture.capture_id)
        if delivery is None:
            self._local_spool_record_id += 1
            delivery = BridgeCaptureDelivery(
                connection_id=1,
                spool_record_id=self._local_spool_record_id,
                source_connection_id=1,
                source_first_stream_offset=0,
                source_last_stream_offset=len(wire_frame) - 1,
                stored_utc_ns=time.time_ns(),
                inner_frame=wire_frame,
            )
        result = store.commit_delivery(delivery)
        self._device.confirm_capture(result.receipt)
        self._device.release_capture(capture.capture_id)
        return self.capture(capture.capture_id.hex())

    def capture_once(
        self,
        *,
        expected_profile_sha256: str,
        expected_device_config_crc32: int,
        trigger_source: str,
        sync_timeout_ms: int,
    ) -> dict[str, object]:
        """Capture once and report success only after the SQLite commit."""

        self._require_store()
        self._require_idle()
        capture = self._executor.capture_once(
            expected_profile_sha256=expected_profile_sha256,
            expected_device_config_crc32=expected_device_config_crc32,
            trigger_source=trigger_source,
            sync_timeout_ms=sync_timeout_ms,
        )
        if not isinstance(capture, CaptureData):
            raise TypeError("device client returned an unsupported capture object")
        return self._persist_capture(
            capture,
            run_plan={
                "loops": 1,
                "start_delay_ms": 0,
                "loop_delay_ms": 0,
                "trigger_source": trigger_source,
                "sync_timeout_ms": sync_timeout_ms,
                "sweep": None,
            },
        )

    def _require_idle(self) -> None:
        with self._session_lock:
            if any(
                session.state in {"RUNNING", "STOPPING"}
                for session in self._sessions.values()
            ):
                raise SessionConflict("the device already has an active run session")

    def _prune_finished_sessions_locked(self) -> None:
        """Keep a bounded recent cache while active sessions remain addressable."""

        finished = [
            identifier
            for identifier, session in self._sessions.items()
            if session.state not in {"RUNNING", "STOPPING"}
        ]
        # Make room for the session about to be inserted. An explicit count
        # avoids Python's surprising ``[:-0]`` behavior at a limit of one.
        prune_count = max(0, len(finished) - self._session_history_limit + 1)
        for identifier in finished[:prune_count]:
            del self._sessions[identifier]

    @staticmethod
    def _record_capture(
        session: _PeriodicSession | _SweepSession,
        capture_id: str,
    ) -> None:
        session.capture_count += 1
        session.capture_ids.append(capture_id)

    @staticmethod
    def _periodic_payload(session: _PeriodicSession) -> dict[str, object]:
        recent = list(session.capture_ids)
        return {
            "session_id": session.session_id.hex(),
            "kind": "PERIODIC",
            "state": session.state,
            "schedule_id": session.schedule.schedule_id.hex(),
            "period_us": session.schedule.period_us,
            "requested_capture_count": session.schedule.capture_count,
            "capture_count": session.capture_count,
            "last_capture_id": recent[-1] if recent else None,
            "recent_capture_ids": recent,
            "capture_ids": recent,
            "lease_timeout_ms": session.schedule.lease_timeout_ms,
            "error": session.error,
            "started_utc_ns": session.started_utc_ns,
            "finished_utc_ns": session.finished_utc_ns,
        }

    def _clear_async_capture_handler(self, handler) -> None:
        clear_handler = getattr(self._device, "clear_async_capture_handler", None)
        if callable(clear_handler):
            clear_handler(handler)

    @staticmethod
    def _periodic_run_plan(session: _PeriodicSession) -> dict[str, object]:
        return {
            "mode": "PERIODIC",
            "session_id": session.session_id.hex(),
            "schedule_id": session.schedule.schedule_id.hex(),
            "period_us": session.schedule.period_us,
            "capture_count": session.schedule.capture_count,
            "lease_timeout_ms": session.schedule.lease_timeout_ms,
        }

    @staticmethod
    def _sweep_payload(session: _SweepSession) -> dict[str, object]:
        recent = list(session.capture_ids)
        return {
            "session_id": session.session_id.hex(),
            "kind": "SWEEP",
            "state": session.state,
            "plan": session.plan.to_dict(),
            "capture_count": session.capture_count,
            "last_capture_id": recent[-1] if recent else None,
            "recent_capture_ids": recent,
            "capture_ids": recent,
            "error": session.error,
            "started_utc_ns": session.started_utc_ns,
            "finished_utc_ns": session.finished_utc_ns,
        }

    def start_periodic(
        self,
        *,
        expected_profile_sha256: str,
        expected_device_config_crc32: int,
        period_us: int,
        capture_count: int,
        lease_timeout_ms: int,
    ) -> dict[str, object]:
        """Start one firmware-leased schedule and a core-owned renewal worker."""

        self._require_store()
        try:
            profile_sha256 = bytes.fromhex(expected_profile_sha256)
        except ValueError as error:
            raise ValueError("expected_profile_sha256 must be hexadecimal") from error
        boot_id = self._device.boot_id
        if boot_id is None:
            raise RuntimeError("device HELLO boot session is unavailable")
        schedule = PeriodicSchedule(
            boot_id=boot_id,
            schedule_id=uuid.uuid4().bytes,
            profile_sha256=profile_sha256,
            device_config_crc32=expected_device_config_crc32,
            period_us=period_us,
            capture_count=capture_count,
            lease_timeout_ms=lease_timeout_ms,
        )
        schedule.validate()
        session = _PeriodicSession(uuid.uuid4().bytes, schedule)
        controller = PeriodicLeaseController(self._executor)
        snapshot = self._executor.snapshot()

        def persist_interleaved(capture: CaptureData) -> bool:
            if capture.schedule_id != schedule.schedule_id:
                return False
            stored = self._persist_capture(
                capture,
                run_plan=self._periodic_run_plan(session),
                snapshot=snapshot,
            )
            with session.control_lock:
                self._record_capture(session, str(stored["capture_id"]))
            return True

        session.async_handler = persist_interleaved
        install_handler = getattr(self._device, "set_async_capture_handler", None)
        if callable(install_handler):
            install_handler(persist_interleaved)
        with self._session_lock:
            if any(
                item.state in {"RUNNING", "STOPPING"}
                for item in self._sessions.values()
            ):
                self._clear_async_capture_handler(persist_interleaved)
                raise SessionConflict("the device already has an active run session")
            self._prune_finished_sessions_locked()
            try:
                controller.start(schedule, now_ms=time.monotonic_ns() // 1_000_000)
            except Exception:
                self._clear_async_capture_handler(persist_interleaved)
                raise
            self._sessions[session.session_id] = session
            session.thread = threading.Thread(
                target=self._periodic_worker,
                args=(session, controller, snapshot, persist_interleaved),
                name=f"usac-periodic-{session.session_id.hex()[:8]}",
                daemon=True,
            )
            session.thread.start()
        return self._periodic_payload(session)

    def start_sweep(
        self,
        *,
        expected_profile_sha256: str,
        expected_device_config_crc32: int,
        field_name: str,
        values: tuple[object, ...],
        loops: int,
        start_delay_ms: int,
        loop_delay_ms: int,
        trigger_source: str,
        sync_timeout_ms: int,
    ) -> dict[str, object]:
        """Validate a finite sweep, then run it without interleaved commands."""

        self._require_store()
        self._executor.require_applied_identity(
            expected_profile_sha256,
            expected_device_config_crc32,
        )
        plan = RunPlanV1(
            loops=loops,
            start_delay_ms=start_delay_ms,
            loop_delay_ms=loop_delay_ms,
            sweep=SweepPlan(field_name, values),
            trigger_source=trigger_source,
            sync_timeout_ms=sync_timeout_ms,
        )
        baseline = self._executor.snapshot()
        # Compile once before returning 202 so invalid plans are synchronous
        # client errors and never create a background session.
        compile_run_steps(self._service, baseline, plan)
        session = _SweepSession(uuid.uuid4().bytes, plan)
        with self._session_lock:
            if any(
                item.state in {"RUNNING", "STOPPING"}
                for item in self._sessions.values()
            ):
                raise SessionConflict("the device already has an active run session")
            self._prune_finished_sessions_locked()
            self._sessions[session.session_id] = session
            session.thread = threading.Thread(
                target=self._sweep_worker,
                args=(session,),
                name=f"usac-sweep-{session.session_id.hex()[:8]}",
                daemon=True,
            )
            session.thread.start()
        return self._sweep_payload(session)

    def _sweep_worker(self, session: _SweepSession) -> None:
        def persist(result: ExecutedCapture) -> None:
            if not isinstance(result.capture, CaptureData):
                raise TypeError("device returned an unsupported sweep capture")
            run_plan = session.plan.to_dict()
            run_plan["session_id"] = session.session_id.hex()
            run_plan["sweep_index"] = result.sweep_index
            run_plan["loop_index"] = result.loop_index
            stored = self._persist_capture(
                result.capture,
                run_plan=run_plan,
                snapshot=result.snapshot,
            )
            with session.control_lock:
                self._record_capture(session, str(stored["capture_id"]))

        try:
            self._executor.execute_run_plan(
                session.plan,
                sleep=session.stop_event.wait,
                cancelled=session.stop_event.is_set,
                on_capture=persist,
            )
        except RuntimeError as error:
            with session.control_lock:
                if session.stop_event.is_set():
                    session.state = "STOPPED"
                else:
                    session.state = "FAILED"
                    session.error = f"{type(error).__name__}: {error}"
                session.finished_utc_ns = time.time_ns()
            return
        except Exception as error:
            with session.control_lock:
                session.state = "FAILED"
                session.error = f"{type(error).__name__}: {error}"
                session.finished_utc_ns = time.time_ns()
            return
        with session.control_lock:
            session.state = "COMPLETED"
            session.finished_utc_ns = time.time_ns()

    def sweep(self, session_id: str) -> dict[str, object]:
        identifier = self._session_identifier(session_id)
        with self._session_lock:
            try:
                session = self._sessions[identifier]
            except KeyError as error:
                raise KeyError(f"unknown sweep {session_id}") from error
        if not isinstance(session, _SweepSession):
            raise KeyError(f"session {session_id} is not a sweep")
        with session.control_lock:
            return self._sweep_payload(session)

    def stop_sweep(self, session_id: str) -> dict[str, object]:
        identifier = self._session_identifier(session_id)
        with self._session_lock:
            try:
                session = self._sessions[identifier]
            except KeyError as error:
                raise KeyError(f"unknown sweep {session_id}") from error
        if not isinstance(session, _SweepSession):
            raise KeyError(f"session {session_id} is not a sweep")
        with session.control_lock:
            if session.state == "RUNNING":
                session.state = "STOPPING"
                session.stop_event.set()
            return self._sweep_payload(session)

    def _periodic_worker(
        self,
        session: _PeriodicSession,
        controller: PeriodicLeaseController,
        snapshot: ConfigurationSnapshot,
        async_handler,
    ) -> None:
        """Renew, drain, and durably commit periodic frames owned by core."""

        try:
            while not session.stop_event.wait(0.01):
                with session.control_lock:
                    if session.state != "RUNNING":
                        return
                    if (
                        session.schedule.capture_count
                        and session.capture_count >= session.schedule.capture_count
                    ):
                        controller.finish()
                        session.state = "COMPLETED"
                        session.finished_utc_ns = time.time_ns()
                        return
                # Never hold the session lock while waiting for device I/O.
                # A status request can receive an interleaved async capture
                # under the device lock and needs the session lock briefly to
                # record its committed ID; reversing that order deadlocks.
                controller.renew_if_due(
                    now_ms=time.monotonic_ns() // 1_000_000,
                )
                if session.stop_event.is_set():
                    return
                self._executor.poll_captures(on_capture=async_handler)
                if (
                    session.schedule.capture_count
                    and session.capture_count >= session.schedule.capture_count
                ):
                    with session.control_lock:
                        controller.finish()
                        session.state = "COMPLETED"
                        session.finished_utc_ns = time.time_ns()
                    return
        except Exception as error:  # preserve the error while lease/STOP makes IO safe
            with session.control_lock:
                stopped = session.stop_event.is_set()
                completed = bool(
                    not stopped
                    and session.schedule.capture_count
                    and session.capture_count >= session.schedule.capture_count
                )
                if completed:
                    # The final frame can arrive and be durably committed while
                    # a lease renewal is already in flight. Firmware then owns no
                    # schedule and correctly rejects that stale renewal. Once the
                    # requested finite count is committed, this is completion—not
                    # a reason to send STOP or report successful data as failed.
                    controller.finish()
                    session.state = "COMPLETED"
                    session.error = None
                    session.finished_utc_ns = time.time_ns()
                    return
            if not stopped:
                try:
                    controller.stop()
                except Exception:
                    pass
            with session.control_lock:
                session.state = "STOPPED" if stopped else "FAILED"
                session.error = None if stopped else f"{type(error).__name__}: {error}"
                session.finished_utc_ns = time.time_ns()
        finally:
            # STOP owns the handler until its ACK so a frame already in flight
            # cannot bypass session accounting after the worker observes the
            # stop event. All other exits release it here.
            with session.control_lock:
                stop_owns_handler = session.state == "STOPPING"
            if not stop_owns_handler:
                self._clear_async_capture_handler(async_handler)

    def stop_periodic(self, *, session_id: str, schedule_id: str) -> dict[str, object]:
        identifier = self._session_identifier(session_id)
        with self._session_lock:
            try:
                session = self._sessions[identifier]
            except KeyError as error:
                raise KeyError(f"unknown session {session_id}") from error
        if session.schedule.schedule_id.hex() != schedule_id:
            raise SessionConflict("schedule_id does not match the session")
        with session.control_lock:
            should_stop = session.state == "RUNNING"
            if should_stop:
                session.stop_event.set()
                session.state = "STOPPING"
        if should_stop:
            # Device I/O follows the same executor lock as renewal and capture
            # confirmation, but never runs while holding the session lock.
            try:
                self._executor.stop_periodic(session.schedule.schedule_id)
            except Exception as error:
                with session.control_lock:
                    session.state = "FAILED"
                    session.error = f"{type(error).__name__}: {error}"
                    session.finished_utc_ns = time.time_ns()
                raise
            else:
                with session.control_lock:
                    session.state = "STOPPED"
                    session.finished_utc_ns = time.time_ns()
            finally:
                self._clear_async_capture_handler(session.async_handler)
        with session.control_lock:
            return self._periodic_payload(session)

    @staticmethod
    def _session_identifier(session_id: str) -> bytes:
        try:
            identifier = bytes.fromhex(session_id)
        except ValueError as error:
            raise ValueError("session_id must be hexadecimal") from error
        if len(identifier) != 16:
            raise ValueError("session_id must encode exactly 16 bytes")
        return identifier

    def session(self, session_id: str) -> dict[str, object]:
        identifier = self._session_identifier(session_id)
        with self._session_lock:
            try:
                session = self._sessions[identifier]
            except KeyError as error:
                raise KeyError(f"unknown session {session_id}") from error
        with session.control_lock:
            if isinstance(session, _PeriodicSession):
                return self._periodic_payload(session)
            return self._sweep_payload(session)

    def capture(self, capture_id: str) -> dict[str, object]:
        store = self._require_store()
        identifier = bytes.fromhex(capture_id)
        if len(identifier) != 16:
            raise ValueError("capture_id must encode exactly 16 bytes")
        record = store.get_capture(identifier)
        return self._capture_payload(
            record,
            events=store.get_capture_events(identifier),
        )

    def captures(
        self,
        *,
        limit: int,
        cursor: str | None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Return a bounded, stable page without loading waveform BLOBs."""

        store = self._require_store()
        try:
            after_row_id = 0 if cursor is None else int(cursor)
        except ValueError as error:
            raise ValueError("cursor must be a decimal capture row id") from error
        if after_row_id < 0:
            raise ValueError("cursor must not be negative")
        items, next_cursor = store.list_captures(
            after_row_id=after_row_id,
            limit=limit,
            session_id=session_id,
        )
        return {
            "items": [_json_value(item) for item in items],
            "next_cursor": None if next_cursor is None else str(next_cursor),
        }

    def capture_samples(self, capture_id: str) -> bytes:
        store = self._require_store()
        identifier = bytes.fromhex(capture_id)
        if len(identifier) != 16:
            raise ValueError("capture_id must encode exactly 16 bytes")
        return store.get_capture(identifier).sample_blob
