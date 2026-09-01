"""Per-device command serialization and configuration/capture binding.

The executor is the only host-side object allowed to call a device client.
Holding one lock across validate, write/readback, ARM, and capture prevents a
second interface from inserting another configuration into that transaction.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from usac_protocol.config_v2 import AcquisitionConfigV2

from .parameter_service import (
    ConfigState,
    ConfigurationSnapshot,
    FieldValidationError,
    ParameterService,
)


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
            readback = self._client.apply_config(result.compiled)
            applied = self._service.mark_applied(
                result.snapshot,
                register_readback=readback.register_pairs,
                sample_interval_ticks=readback.sample_interval_ticks,
                burst_period_ticks=readback.burst_period_ticks,
            )
            self._applied_config = result.compiled
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
