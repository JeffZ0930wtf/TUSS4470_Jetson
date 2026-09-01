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
    register_pairs: tuple[tuple[int, int], ...]
    sample_interval_ticks: int
    burst_period_ticks: int


class DeviceClient(Protocol):
    """High-level transport boundary implemented by bridge/device sessions."""

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

    def snapshot(self) -> ConfigurationSnapshot:
        with self._lock:
            return self._snapshot

    def update_draft(self, changes: dict[str, object]) -> ConfigurationSnapshot:
        with self._lock:
            self._snapshot = self._service.update_draft(self._snapshot, changes)
            return self._snapshot

    def preview_changes(self, changes: dict[str, object]) -> ValidationResult:
        """Validate proposed semantic changes without mutating shared state."""

        with self._lock:
            target = self._service.update_draft(self._snapshot, changes)
            return self._service.validate(target)

    def applied_etag(self) -> str:
        """Return the HTTP entity tag for the device-confirmed configuration."""

        with self._lock:
            digest = (
                self._applied_config.profile_sha256.hex()
                if self._applied_config is not None
                else "0" * 64
            )
            return f'"{digest}"'

    def apply_changes(self, changes: dict[str, object]) -> ConfigurationSnapshot:
        """Validate and apply changes without publishing an intermediate draft."""

        with self._lock:
            target = self._service.update_draft(self._snapshot, changes)
            result = self._service.validate(target)
            if result.errors or result.compiled is None:
                raise ConfigValidationError(result.errors)
            return self._apply_validated(result.snapshot, result.compiled)

    def validated_target(self) -> AcquisitionConfigV2:
        """Compile the current draft without causing a device side effect."""

        with self._lock:
            result = self._service.validate(self._snapshot)
            if result.errors or result.compiled is None:
                raise ConfigValidationError(result.errors)
            return result.compiled

    def apply_draft(self) -> ConfigurationSnapshot:
        """Validate, apply, and publish APPLIED only after exact readback."""

        with self._lock:
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
            register_readback=readback.register_pairs,
            sample_interval_ticks=readback.sample_interval_ticks,
            burst_period_ticks=readback.burst_period_ticks,
        )
        self._applied_config = config
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
            return self._client.capabilities()

    def status(self) -> object:
        with self._lock:
            return self._client.status()

    def start_periodic(self, schedule: PeriodicSchedule) -> None:
        with self._lock:
            self._require_applied_identity(
                schedule.profile_sha256.hex(),
                schedule.device_config_crc32,
            )
            self._client.start_periodic(schedule)

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal:
        with self._lock:
            return self._client.renew_periodic(renewal)

    def stop_periodic(self, schedule_id: bytes) -> None:
        with self._lock:
            self._client.stop_periodic(schedule_id)

    def poll_captures(self) -> tuple[object, ...]:
        with self._lock:
            return self._client.poll_captures()

    def _require_applied_identity(
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
    ) -> tuple[object, ...]:
        """Execute a finite plan atomically and restore its APPLIED baseline."""

        with self._lock:
            if self._snapshot.state is not ConfigState.APPLIED or self._applied_config is None:
                raise ConfigConflictError("no APPLIED configuration is available")
            baseline_snapshot = self._snapshot
            baseline_config = self._applied_config
            steps = compile_run_steps(self._service, baseline_snapshot, plan)
            captures: list[object] = []
            if plan.start_delay_ms:
                sleep(plan.start_delay_ms / 1_000)
            try:
                for step in steps:
                    if self._applied_config != step.compiled:
                        self._apply_validated(step.snapshot, step.compiled)
                    captures.append(
                        self._client.capture_once(
                            config=step.compiled,
                            trigger_source=plan.trigger_source,
                            sync_timeout_ms=plan.sync_timeout_ms,
                        )
                    )
                    if plan.loop_delay_ms and step.loop_index + 1 < plan.loops:
                        sleep(plan.loop_delay_ms / 1_000)
            finally:
                if self._applied_config != baseline_config:
                    baseline = self._service.validate(baseline_snapshot)
                    if baseline.errors or baseline.compiled is None:
                        raise ConfigValidationError(baseline.errors)
                    self._apply_validated(baseline.snapshot, baseline.compiled)
            return tuple(captures)
