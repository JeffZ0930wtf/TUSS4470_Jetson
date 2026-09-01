"""Core-owned renewal state for firmware-enforced periodic capture leases.

Only the core calls this controller. The bridge must never synthesize renewals;
if the core process stops calling :meth:`renew_if_due`, the device deadline is
allowed to expire and prevents any further Burst scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PeriodicSchedule:
    boot_id: bytes
    schedule_id: bytes
    profile_sha256: bytes
    device_config_crc32: int
    period_us: int
    capture_count: int
    lease_timeout_ms: int

    def validate(self) -> None:
        if len(self.boot_id) != 16 or self.boot_id == bytes(16):
            raise ValueError("boot_id must be a nonzero 16-byte value")
        if len(self.schedule_id) != 16 or self.schedule_id == bytes(16):
            raise ValueError("schedule_id must be a nonzero 16-byte value")
        if len(self.profile_sha256) != 32:
            raise ValueError("profile_sha256 must be 32 bytes")
        if not 100_000 <= self.period_us <= 0xFFFFFFFF:
            raise ValueError("period_us must respect the 10 Hz first-version limit")
        if not 0 <= self.capture_count <= 0xFFFFFFFF:
            raise ValueError("capture_count must be a u32")
        if not 1_000 <= self.lease_timeout_ms <= 10_000:
            raise ValueError("lease_timeout_ms must be in 1000..10000")


@dataclass(frozen=True, slots=True)
class LeaseRenewal:
    boot_id: bytes
    schedule_id: bytes
    lease_sequence: int
    lease_timeout_ms: int


class PeriodicDeviceClient(Protocol):
    def start_periodic(self, schedule: PeriodicSchedule) -> None: ...

    def renew_periodic(self, renewal: LeaseRenewal) -> LeaseRenewal: ...

    def stop_periodic(self, schedule_id: bytes) -> None: ...


class LeaseConflictError(RuntimeError):
    """A schedule or renewal response does not match the active lease."""


class PeriodicLeaseController:
    """Maintain one active schedule and monotonically increasing renewals."""

    def __init__(self, client: PeriodicDeviceClient) -> None:
        self._client = client
        self._schedule: PeriodicSchedule | None = None
        self._lease_sequence = 0
        self._next_renewal_ms = 0

    @property
    def active(self) -> bool:
        return self._schedule is not None

    @staticmethod
    def _renew_interval_ms(schedule: PeriodicSchedule) -> int:
        return min(schedule.lease_timeout_ms // 3, 1_000)

    def start(self, schedule: PeriodicSchedule, *, now_ms: int) -> None:
        schedule.validate()
        if self._schedule is not None:
            raise LeaseConflictError("a periodic schedule is already active")
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        self._client.start_periodic(schedule)
        self._schedule = schedule
        self._lease_sequence = 0
        self._next_renewal_ms = now_ms + self._renew_interval_ms(schedule)

    def renew_if_due(self, *, now_ms: int) -> bool:
        schedule = self._schedule
        if schedule is None or now_ms < self._next_renewal_ms:
            return False
        renewal = LeaseRenewal(
            boot_id=schedule.boot_id,
            schedule_id=schedule.schedule_id,
            lease_sequence=self._lease_sequence + 1,
            lease_timeout_ms=schedule.lease_timeout_ms,
        )
        response = self._client.renew_periodic(renewal)
        if response != renewal:
            # Stop local ownership immediately. Without more renewals the
            # firmware deadline is the fail-safe even if STOP cannot be sent.
            self._schedule = None
            raise LeaseConflictError("lease renewal response does not match the request")
        self._lease_sequence = renewal.lease_sequence
        self._next_renewal_ms = now_ms + self._renew_interval_ms(schedule)
        return True

    def stop(self) -> None:
        schedule = self._schedule
        if schedule is None:
            return
        self._schedule = None
        self._lease_sequence = 0
        self._next_renewal_ms = 0
        self._client.stop_periodic(schedule.schedule_id)
