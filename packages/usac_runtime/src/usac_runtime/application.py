"""Shared M5 application service used by REST, CLI, and browser clients.

Interface adapters call this object instead of reaching into the parameter
schema, device simulator, serial transport, or executor independently. This
keeps semantic validation and configuration identity consistent everywhere.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Protocol

from .device_executor import SingleDeviceExecutor
from .parameter_service import ConfigurationSnapshot, ParameterService, ValidationResult


class ApplicationDevice(Protocol):
    def capabilities(self) -> object: ...

    def status(self) -> object: ...


class ConfigurationEtagConflict(RuntimeError):
    """The caller based a mutation on an obsolete APPLIED configuration."""


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
    ) -> None:
        self._service = service
        self._executor = executor
        self._device = device

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
        return {
            "capabilities": _json_value(self._device.capabilities()),
            "status": _json_value(self._device.status()),
        }

    def schema(self) -> dict[str, object]:
        return self._service.registry_view()

    def etag(self) -> str:
        return self._executor.applied_etag()

    def config(self) -> dict[str, object]:
        return self._snapshot(self._executor.snapshot())

    def validate_config(self, changes: dict[str, object]) -> dict[str, object]:
        return self._validation(self._executor.preview_changes(changes))

    def apply_config(
        self,
        changes: dict[str, object],
        *,
        expected_etag: str,
    ) -> dict[str, object]:
        if expected_etag != self.etag():
            raise ConfigurationEtagConflict("If-Match does not match current config")
        return self._snapshot(self._executor.apply_changes(changes))
