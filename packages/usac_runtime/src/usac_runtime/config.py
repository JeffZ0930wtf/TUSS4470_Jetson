"""Cross-platform runtime configuration loaded from TOML and USAC_* overrides.

Serial names and storage paths remain opaque so business code does not branch
on Windows drive letters or Linux device spellings.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when the runtime configuration is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class SerialConfig:
    port: str
    baudrate: int = 115_200
    timeout_ms: int = 2_000


@dataclass(frozen=True, slots=True)
class StorageConfig:
    data_dir: Path
    spool_dir: Path
    sqlite_path: Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    serial: SerialConfig
    storage: StorageConfig


def _required_table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise ConfigurationError(f"missing [{name}] table")
    return value


def _required_text(table: Mapping[str, object], name: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_integer(table: Mapping[str, object], name: str) -> int:
    value = table.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def _resolved_path(raw_value: str, base_directory: Path) -> Path:
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = base_directory / candidate
    return candidate.resolve()


def load_runtime_config(
    path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Load a platform-neutral runtime configuration from TOML and environment."""

    config_path = Path(path).resolve()
    environment = os.environ if environ is None else environ
    with config_path.open("rb") as stream:
        document = tomllib.load(stream)

    serial_table = _required_table(document, "serial")
    storage_table = _required_table(document, "storage")
    configured_port = serial_table.get("port")
    if not isinstance(configured_port, str) or not configured_port.strip():
        raise ConfigurationError("serial.port must be a non-empty string")
    serial_port = environment.get("USAC_SERIAL_PORT", configured_port).strip()
    if not serial_port:
        raise ConfigurationError("serial.port must be a non-empty string")

    base_directory = config_path.parent

    def storage_path(field: str, environment_name: str) -> Path:
        raw_value = environment.get(
            environment_name,
            _required_text(storage_table, field),
        )
        if not raw_value.strip():
            raise ConfigurationError(f"storage.{field} must be a non-empty string")
        return _resolved_path(raw_value.strip(), base_directory)

    return RuntimeConfig(
        serial=SerialConfig(
            port=serial_port,
            baudrate=_positive_integer(serial_table, "baudrate"),
            timeout_ms=_positive_integer(serial_table, "timeout_ms"),
        ),
        storage=StorageConfig(
            data_dir=storage_path("data_dir", "USAC_DATA_DIR"),
            spool_dir=storage_path("spool_dir", "USAC_SPOOL_DIR"),
            sqlite_path=storage_path("sqlite_path", "USAC_SQLITE_PATH"),
        ),
    )
