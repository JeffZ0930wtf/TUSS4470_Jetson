"""Per-device command serialization and configuration/capture binding.

The executor is the only host-side object allowed to call a device client.
Holding one lock across validate, write/readback, ARM, and capture prevents a
second interface from inserting another configuration into that transaction.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable
from typing import Protocol

from usac_protocol.bridge_messages import BridgeCaptureDelivery, CaptureCommittedRequest
from usac_protocol.config_v2 import AcquisitionConfigV2

from .parameter_service import (
    ConfigState,
    ConfigurationSnapshot,
    FieldValidationError,
    ParameterService,
    ValidationResult,
)
from .periodic_lease import LeaseRenewal, PeriodicSchedule
from .run_plan import RunPlanV1, compile_run_steps


@dataclass(frozen=True, slots=True)
class DeviceReadback:
    """Complete canonical GET_CONFIG result returned after SET_CONFIG."""

    config: AcquisitionConfigV2

    @property
    def register_pairs(self) -> tuple[tuple[int, int], ...]:
        return self.config.register_pairs

    @property
    def sample_interval_ticks(self) -> int:
        return self.config.sample_interval_ticks

    @property
    def burst_period_ticks(self) -> int:
        return self.config.burst_period_ticks


@dataclass(frozen=True, slots=True)
class ExecutedCapture:
    """One capture paired with the exact RunStep active at acquisition time."""

    capture: object
    sweep_index: int | None
    loop_index: int
    snapshot: ConfigurationSnapshot


class DeviceClient(Protocol):
    """High-level transport boundary implemented by bridge/device sessions."""

    hello: object
    boot_id: bytes | None
    device_id: bytes | None

    def apply_config(self, config: AcquisitionConfigV2) -> DeviceReadback: ...

    def capture_once(
        self,
        *,
        config: AcquisitionConfigV2,
        trigger_source: str,
        sync_timeout_ms: int,
    ) -> object: ...

    def capabilities(self) -> object: ...

    def status(self) -> object: ...

    def start_periodic(self, schedule: PeriodicSchedule) -> None: ...

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal: ...

    def stop_periodic(self, schedule_id: bytes) -> None: ...

    def poll_captures(self) -> tuple[object, ...]: ...

    def capture_delivery(self, capture_id: bytes) -> BridgeCaptureDelivery | None: ...

    def capture_wire_frame(self, capture_id: bytes) -> bytes: ...

    def confirm_capture(self, receipt: CaptureCommittedRequest) -> None: ...

    def release_capture(self, capture_id: bytes) -> None: ...


class ConfigValidationError(ValueError):
    def __init__(self, errors: tuple[FieldValidationError, ...]) -> None:
        self.errors = errors
        super().__init__("configuration did not pass semantic and hardware validation")


class ConfigConflictError(RuntimeError):
    """The caller expected a different APPLIED configuration."""


class SingleDeviceExecutor:
    """Serialize all side-effecting operations for one physical device."""

    def __init__(self, service: ParameterService, client: DeviceClient) -> None:
        self._service = service
        self._client = client
        self._lock = threading.RLock()
        self._snapshot = service.new_draft()
        self._applied_config: AcquisitionConfigV2 | None = None
        self._session_generation = int(getattr(client, "session_generation", 0))

    def _refresh_session_unlocked(self) -> None:
        """Invalidate APPLIED state when bridge publishes a new HELLO session."""

        generation = int(getattr(self._client, "session_generation", 0))
        if generation == self._session_generation:
            return
        # Preserve the operator's semantic choices as a draft, but require a
        # new SET_CONFIG/readback before any Burst after USB or TCP recovery.
        self._snapshot = self._service.update_draft(self._snapshot, {})
        self._applied_config = None
        self._session_generation = generation

    def snapshot(self) -> ConfigurationSnapshot:
        with self._lock:
            self._refresh_session_unlocked()
            return self._snapshot

    def update_draft(self, changes: dict[str, object]) -> ConfigurationSnapshot:
        with self._lock:
            self._refresh_session_unlocked()
            self._snapshot = self._service.update_draft(self._snapshot, changes)
            return self._snapshot

    def preview_changes(self, changes: dict[str, object]) -> ValidationResult:
        """Validate proposed semantic changes without mutating shared state."""

        with self._lock:
            self._refresh_session_unlocked()
            target = self._service.update_draft(self._snapshot, changes)
            return self._service.validate(target)

    def applied_etag(self) -> str:
        """Return the HTTP entity tag for the device-confirmed configuration."""

        with self._lock:
            self._refresh_session_unlocked()
            digest = (
                self._applied_config.profile_sha256.hex()
                if self._applied_config is not None
                else "0" * 64
            )
            return f'"{digest}"'

    def apply_changes(self, changes: dict[str, object]) -> ConfigurationSnapshot:
        """Validate and apply changes without publishing an intermediate draft."""

        with self._lock:
            self._refresh_session_unlocked()
            target = self._service.update_draft(self._snapshot, changes)
            result = self._service.validate(target)
            if result.errors or result.compiled is None:
                raise ConfigValidationError(result.errors)
            return self._apply_validated(result.snapshot, result.compiled)

    def validated_target(self) -> AcquisitionConfigV2:
        """Compile the current draft without causing a device side effect."""

        with self._lock:
            self._refresh_session_unlocked()
            result = self._service.validate(self._snapshot)
            if result.errors or result.compiled is None:
                raise ConfigValidationError(result.errors)
            return result.compiled

    def apply_draft(self) -> ConfigurationSnapshot:
        """Validate, apply, and publish APPLIED only after exact readback."""

        with self._lock:
            self._refresh_session_unlocked()
            result = self._service.validate(self._snapshot)
            if result.errors or result.compiled is None:
                raise ConfigValidationError(result.errors)
            return self._apply_validated(result.snapshot, result.compiled)

    def _apply_validated(
        self,
        snapshot: ConfigurationSnapshot,
        config: AcquisitionConfigV2,
    ) -> ConfigurationSnapshot:
        """Publish a configuration only after the device returns exact readback."""

        readback = self._client.apply_config(config)
        applied = self._service.mark_applied(
            snapshot,
            config_readback=readback.config,
        )
        self._applied_config = config
        self._session_generation = int(getattr(self._client, "session_generation", 0))
        self._snapshot = applied
        return applied

    @staticmethod
    def _validate_trigger(trigger_source: str, sync_timeout_ms: int) -> None:
        if trigger_source not in {
            "SOFTWARE",
            "EXTERNAL_SYNC_SLAVE",
            "EXTERNAL_SYNC_MASTER",
        }:
            raise ValueError("trigger_source is invalid")
        if trigger_source == "EXTERNAL_SYNC_SLAVE":
            if not 1 <= sync_timeout_ms <= 60_000:
                raise ValueError("slave sync_timeout_ms must be in 1..60000")
        elif sync_timeout_ms != 0:
            raise ValueError("sync_timeout_ms must be zero outside slave mode")

    def capture_once(
        self,
        *,
        expected_profile_sha256: str,
        expected_device_config_crc32: int,
        trigger_source: str,
        sync_timeout_ms: int,
    ) -> object:
        """Run one capture only when the caller is bound to current APPLIED state."""

        with self._lock:
            self._refresh_session_unlocked()
            if self._snapshot.state is not ConfigState.APPLIED or self._applied_config is None:
                raise ConfigConflictError("no APPLIED configuration is available")
            if self._applied_config.profile_sha256.hex() != expected_profile_sha256:
                raise ConfigConflictError("expected profile does not match APPLIED profile")
            if self._applied_config.device_config_crc32 != expected_device_config_crc32:
                raise ConfigConflictError("expected configuration CRC does not match APPLIED profile")
            self._validate_trigger(trigger_source, sync_timeout_ms)
            return self._client.capture_once(
                config=self._applied_config,
                trigger_source=trigger_source,
                sync_timeout_ms=sync_timeout_ms,
            )

    def capabilities(self) -> object:
        with self._lock:
            self._refresh_session_unlocked()
            return self._client.capabilities()

    def status(self) -> object:
        with self._lock:
            self._refresh_session_unlocked()
            return self._client.status()

    def start_periodic(self, schedule: PeriodicSchedule) -> None:
        with self._lock:
            self._refresh_session_unlocked()
            self._require_applied_identity_unlocked(
                schedule.profile_sha256.hex(),
                schedule.device_config_crc32,
            )
            self._client.start_periodic(schedule)

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
        with self._lock:
            self._refresh_session_unlocked()
            return self._client.renew_periodic(renewal)

    def stop_periodic(self, schedule_id: bytes) -> None:
        with self._lock:
            self._refresh_session_unlocked()
            self._client.stop_periodic(schedule_id)

    def poll_captures(
        self,
        *,
        on_capture: Callable[[object], object] | None = None,
    ) -> tuple[object, ...]:
        """Poll and, when requested, commit deliveries under the device lock.

        Bridge capture confirmation reads from the same TCP byte stream as
        status and renewal responses. Keeping the callback inside this lock
        prevents another API thread from consuming that confirmation.
        """

        with self._lock:
            self._refresh_session_unlocked()
            captures = self._client.poll_captures()
            if on_capture is not None:
                for capture in captures:
                    on_capture(capture)
            return captures

    def require_applied_identity(
        self,
        profile_sha256: str,
        device_config_crc32: int,
    ) -> None:
        with self._lock:
            self._refresh_session_unlocked()
            self._require_applied_identity_unlocked(
                profile_sha256,
                device_config_crc32,
            )

    def _require_applied_identity_unlocked(
        self,
        profile_sha256: str,
        device_config_crc32: int,
    ) -> None:
        if self._snapshot.state is not ConfigState.APPLIED or self._applied_config is None:
            raise ConfigConflictError("no APPLIED configuration is available")
        if self._applied_config.profile_sha256.hex() != profile_sha256:
            raise ConfigConflictError("expected profile does not match APPLIED profile")
        if self._applied_config.device_config_crc32 != device_config_crc32:
            raise ConfigConflictError("expected configuration CRC does not match APPLIED profile")

    def execute_run_plan(
        self,
        plan: RunPlanV1,
        *,
        sleep: Callable[[float], None],
        cancelled: Callable[[], bool] = lambda: False,
        on_capture: Callable[[ExecutedCapture], None] | None = None,
    ) -> tuple[ExecutedCapture, ...]:
        """Execute a finite plan atomically and restore its APPLIED baseline."""

        with self._lock:
            self._refresh_session_unlocked()
            if self._snapshot.state is not ConfigState.APPLIED or self._applied_config is None:
                raise ConfigConflictError("no APPLIED configuration is available")
            baseline_snapshot = self._snapshot
            baseline_config = self._applied_config
            steps = compile_run_steps(self._service, baseline_snapshot, plan)
            # Background Sweep persistence already receives each result through
            # on_capture. Do not duplicate that unbounded history in RAM.
            captures: list[ExecutedCapture] | None = [] if on_capture is None else None
            if plan.start_delay_ms:
                sleep(plan.start_delay_ms / 1_000)
            try:
                for step in steps:
                    if cancelled():
                        raise RuntimeError("run plan was stopped")
                    if self._applied_config != step.compiled:
                        capture_snapshot = self._apply_validated(step.snapshot, step.compiled)
                    else:
                        # Persist the current APPLIED snapshot, not the plan's
                        # pre-I/O VALIDATED draft. This binds each stored frame
                        # to the exact register/timer values read back before it.
                        capture_snapshot = self._snapshot
                    result = ExecutedCapture(
                        capture=self._client.capture_once(
                            config=step.compiled,
                            trigger_source=plan.trigger_source,
                            sync_timeout_ms=plan.sync_timeout_ms,
                        ),
                        sweep_index=step.sweep_index,
                        loop_index=step.loop_index,
                        snapshot=capture_snapshot,
                    )
                    if captures is not None:
                        captures.append(result)
                    if on_capture is not None:
                        on_capture(result)
                    if plan.loop_delay_ms and step.loop_index + 1 < plan.loops:
                        sleep(plan.loop_delay_ms / 1_000)
            finally:
                if self._applied_config != baseline_config:
                    baseline = self._service.validate(baseline_snapshot)
                    if baseline.errors or baseline.compiled is None:
                        raise ConfigValidationError(baseline.errors)
                    self._apply_validated(baseline.snapshot, baseline.compiled)
            return () if captures is None else tuple(captures)
