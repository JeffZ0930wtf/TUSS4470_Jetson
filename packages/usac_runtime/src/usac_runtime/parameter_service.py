"""Semantic TUSS4470 configuration service shared by every host interface.

The service turns the machine-readable registry into client metadata and a
single DRAFT -> VALIDATED -> APPLIED state model.  It deliberately does not
open the serial port: the device executor performs the eventual atomic write
and supplies the readback used by :meth:`mark_applied`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from usac_protocol.config_v2 import AcquisitionConfigV2
from usac_protocol.parameters import ParameterSchema, RegisterField
from usac_protocol.safety import validate_boostxl_direct_applied_config


class ConfigState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"


class ValidationCode(str, Enum):
    INVALID_VALUE = "INVALID_VALUE"
    UNSAFE_CONFIG = "UNSAFE_CONFIG"
    UNSUPPORTED_HARDWARE_PROFILE = "UNSUPPORTED_HARDWARE_PROFILE"


@dataclass(frozen=True, slots=True)
class FieldValidationError:
    field: str
    code: ValidationCode
    message: str


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    state: ConfigState
    requested: dict[str, object]
    actual: dict[str, object]
    readback: dict[str, object]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    snapshot: ConfigurationSnapshot
    errors: tuple[FieldValidationError, ...]
    compiled: AcquisitionConfigV2 | None


class ParameterService:
    """Own semantic validation, tick quantization, and register compilation."""

    def __init__(self, schema: ParameterSchema, *, smclk_hz: int) -> None:
        if smclk_hz <= 0:
            raise ValueError("smclk_hz must be positive")
        self.schema = schema
        self.smclk_hz = smclk_hz

    @classmethod
    def from_schema_file(cls, path: Path, *, smclk_hz: int) -> ParameterService:
        return cls(ParameterSchema.load(path), smclk_hz=smclk_hz)

    def registry_view(self) -> dict[str, object]:
        """Return the common client field catalogue without hard-coded UI lists."""

        fields: list[dict[str, object]] = []
        for field in self.schema.register_fields.values():
            item: dict[str, object] = {
                "name": field.name,
                "group": self.schema.register_names[field.address],
                "unit": field.metadata.get("unit", "register_code"),
                "default": field.default,
                "sweepable": field.sweepable,
                "safety": field.safety,
                "read_only": False,
            }
            kind = field.encoding["kind"]
            item["kind"] = kind
            if kind == "enum":
                item["values"] = [entry["value"] for entry in field.encoding["values"]]
            elif kind == "uint":
                item["minimum"] = field.encoding["min"]
                item["maximum"] = field.encoding["max"]
            fields.append(item)

        for field in self.schema.nonregister_fields.values():
            item = {
                **field,
                "group": self._nonregister_group(field["name"]),
                "minimum": field.get("min"),
                "maximum": field.get("max"),
                "read_only": field.get("access") == "read_only",
            }
            fields.append(item)
        return {
            "schema_name": self.schema.schema_name,
            "schema_version": self.schema.schema_version,
            "fields": fields,
        }

    @staticmethod
    def _nonregister_group(name: str) -> str:
        if name in {"loops", "start_delay_ms", "loop_delay_ms", "sweep", "trigger_source", "sync_timeout_ms"}:
            return "RUN_PLAN"
        return "ACQUISITION"

    def new_draft(self) -> ConfigurationSnapshot:
        requested: dict[str, object] = {
            name: field.default for name, field in self.schema.register_fields.items()
        }
        for name, field in self.schema.nonregister_fields.items():
            if field["kind"] == "constant":
                requested[name] = field["value"]
            elif "default" in field:
                requested[name] = field["default"]
        return self._draft_snapshot(requested)

    def update_draft(
        self,
        snapshot: ConfigurationSnapshot,
        changes: Mapping[str, object],
    ) -> ConfigurationSnapshot:
        requested = dict(snapshot.requested)
        unknown = set(changes) - set(self.schema.register_fields) - set(self.schema.nonregister_fields)
        if unknown:
            raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")

        sampling_drivers = {
            "requested_sample_rate_hz",
            "requested_record_ms",
            "sample_interval_ticks",
        } & set(changes)
        if len(sampling_drivers) > 1:
            raise ValueError("change only one sampling-rate, Record, or sample-tick input at a time")
        frequency_drivers = {"requested_burst_frequency_hz", "burst_period_ticks"} & set(changes)
        if len(frequency_drivers) > 1:
            raise ValueError("change only one frequency or burst-tick input at a time")

        for name, value in changes.items():
            self._validate_datasheet_value(name, value)
            requested[name] = value

        if "requested_sample_rate_hz" in changes:
            requested["sample_interval_ticks"] = round(
                self.smclk_hz / int(requested["requested_sample_rate_hz"])
            )
        elif "requested_record_ms" in changes:
            requested["sample_interval_ticks"] = round(
                float(requested["requested_record_ms"])
                * self.smclk_hz
                / (int(requested["sample_count"]) * 1000)
            )
        if "sample_interval_ticks" in changes or sampling_drivers:
            ticks = int(requested["sample_interval_ticks"])
            self._validate_datasheet_value("sample_interval_ticks", ticks)
            if "requested_sample_rate_hz" not in changes:
                requested["requested_sample_rate_hz"] = round(self.smclk_hz / ticks)
            if "requested_record_ms" not in changes:
                requested["requested_record_ms"] = (
                    int(requested["sample_count"]) * ticks * 1000 / self.smclk_hz
                )

        if "requested_burst_frequency_hz" in changes:
            requested["burst_period_ticks"] = round(
                self.smclk_hz / int(requested["requested_burst_frequency_hz"])
            )
        if frequency_drivers:
            ticks = int(requested["burst_period_ticks"])
            self._validate_datasheet_value("burst_period_ticks", ticks)
            if "requested_burst_frequency_hz" not in changes:
                requested["requested_burst_frequency_hz"] = round(self.smclk_hz / ticks)

        return self._draft_snapshot(requested)

    def _validate_datasheet_value(self, name: str, value: object) -> None:
        if name in self.schema.register_fields:
            self.schema.register_fields[name].encode(value)
            return
        field = self.schema.nonregister_fields[name]
        if field.get("access") == "read_only":
            raise ValueError(f"{name} is read-only")
        kind = field["kind"]
        if kind == "bool" and not isinstance(value, bool):
            raise ValueError(f"{name} requires a boolean")
        if kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} requires an integer")
            if not field["min"] <= value <= field["max"]:
                raise ValueError(f"{name} is outside its legal range")
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} requires a number")
            if not field["min"] <= value <= field["max"]:
                raise ValueError(f"{name} is outside its legal range")
        elif kind == "enum" and value not in field["values"]:
            raise ValueError(f"{name} has an unknown enum value")
        elif kind == "object" and not isinstance(value, dict):
            raise ValueError(f"{name} requires an object")

    def _draft_snapshot(self, requested: dict[str, object]) -> ConfigurationSnapshot:
        return ConfigurationSnapshot(
            state=ConfigState.DRAFT,
            requested=requested,
            actual=self._actual_values(requested),
            readback={},
        )

    def _actual_values(self, requested: Mapping[str, object]) -> dict[str, object]:
        sample_ticks = int(requested["sample_interval_ticks"])
        burst_ticks = int(requested["burst_period_ticks"])
        sample_count = int(requested["sample_count"])
        return {
            "sample_rate_hz": self.smclk_hz / sample_ticks,
            "record_ms": sample_count * sample_ticks * 1000 / self.smclk_hz,
            "burst_frequency_hz": self.smclk_hz / burst_ticks,
            "smclk_hz": self.smclk_hz,
        }

    def _compile(self, requested: Mapping[str, object]) -> AcquisitionConfigV2:
        registers = {address: 0 for address in self.schema.register_write_masks}
        for name, field in self.schema.register_fields.items():
            registers[field.address] = self.schema.encode_field(
                name,
                requested[name],
                register_value=registers[field.address],
            )
        aux_flags = int(bool(requested["out3_enabled"])) | (
            int(bool(requested["out4_enabled"])) << 1
        )
        return AcquisitionConfigV2.create(
            sample_interval_ticks=int(requested["sample_interval_ticks"]),
            sample_count=int(requested["sample_count"]),
            pretrigger_count=int(requested["pretrigger_count"]),
            adc_bits=12,
            aux_flags=aux_flags,
            vref_mv=3300,
            burst_period_ticks=int(requested["burst_period_ticks"]),
            register_pairs=tuple(registers.items()),
        )

    def _safety_errors(self, requested: Mapping[str, object]) -> tuple[FieldValidationError, ...]:
        checks = (
            ("BURST_PULSE", requested["BURST_PULSE"] == 0, ValidationCode.UNSAFE_CONFIG, "continuous Burst is prohibited"),
            ("PRE_DRIVER_MODE", requested["PRE_DRIVER_MODE"] is True, ValidationCode.UNSUPPORTED_HARDWARE_PROFILE, "pre-driver requires an external-driver hardware profile"),
            ("VOUT_SCALE_SEL", requested["VOUT_SCALE_SEL"] == "5.0_v", ValidationCode.UNSAFE_CONFIG, "5 V VOUT exceeds the 3.3 V ADC path"),
            ("VDRV_CURRENT_LEVEL", requested["VDRV_CURRENT_LEVEL"] == "20_ma", ValidationCode.UNSAFE_CONFIG, "20 mA VDRV is not approved for this profile"),
            ("VDRV_VOLTAGE_LEVEL", requested["VDRV_VOLTAGE_LEVEL"] != 0, ValidationCode.UNSAFE_CONFIG, "only internal 5 V VDRV is approved"),
            ("VDRV_HI_Z", requested["VDRV_HI_Z"] is True, ValidationCode.UNSAFE_CONFIG, "stable APPLIED configuration must leave VDRV enabled"),
            ("CMD_TRIGGER", requested["CMD_TRIGGER"] is True, ValidationCode.UNSAFE_CONFIG, "CMD_TRIGGER is state-machine controlled"),
            ("STDBY_MODE_EN", requested["STDBY_MODE_EN"] is True, ValidationCode.UNSAFE_CONFIG, "standby is a state transition, not a stable profile bit"),
            ("SLEEP_MODE_EN", requested["SLEEP_MODE_EN"] is True, ValidationCode.UNSAFE_CONFIG, "sleep is a state transition, not a stable profile bit"),
        )
        return tuple(
            FieldValidationError(field, code, message)
            for field, failed, code, message in checks
            if failed
        )

    def validate(self, snapshot: ConfigurationSnapshot) -> ValidationResult:
        errors = self._safety_errors(snapshot.requested)
        if errors:
            return ValidationResult(replace(snapshot, state=ConfigState.DRAFT), errors, None)
        compiled = self._compile(snapshot.requested)
        validate_boostxl_direct_applied_config(compiled)
        actual = {
            **self._actual_values(snapshot.requested),
            "register_pairs": [list(pair) for pair in compiled.register_pairs],
            "profile_sha256": compiled.profile_sha256.hex(),
            "device_config_crc32": compiled.device_config_crc32,
        }
        validated = replace(snapshot, state=ConfigState.VALIDATED, actual=actual, readback={})
        return ValidationResult(validated, (), compiled)

    def mark_applied(
        self,
        snapshot: ConfigurationSnapshot,
        *,
        config_readback: AcquisitionConfigV2,
    ) -> ConfigurationSnapshot:
        if snapshot.state is not ConfigState.VALIDATED:
            raise ValueError("only a VALIDATED configuration can become APPLIED")
        compiled = self._compile(snapshot.requested)
        if config_readback != compiled:
            raise ValueError("configuration readback does not match the validated target")
        register_values = dict(config_readback.register_pairs)
        semantic_fields = {
            name: self.schema.decode_field(name, register_values[field.address])
            for name, field in self.schema.register_fields.items()
        }
        semantic_fields.update(
            {
                "requested_burst_frequency_hz": round(
                    self.smclk_hz / config_readback.burst_period_ticks
                ),
                "burst_period_ticks": config_readback.burst_period_ticks,
                "requested_sample_rate_hz": round(
                    self.smclk_hz / config_readback.sample_interval_ticks
                ),
                "requested_record_ms": (
                    config_readback.sample_count
                    * config_readback.sample_interval_ticks
                    * 1000
                    / self.smclk_hz
                ),
                "sample_interval_ticks": config_readback.sample_interval_ticks,
                "sample_count": config_readback.sample_count,
                "pretrigger_count": config_readback.pretrigger_count,
                "out3_enabled": bool(config_readback.aux_flags & 0x01),
                "out4_enabled": bool(config_readback.aux_flags & 0x02),
            }
        )
        return replace(
            snapshot,
            state=ConfigState.APPLIED,
            readback={
                "register_pairs": [list(pair) for pair in config_readback.register_pairs],
                "sample_interval_ticks": config_readback.sample_interval_ticks,
                "burst_period_ticks": config_readback.burst_period_ticks,
                "fields": semantic_fields,
                "host_only_fields": [
                    "loops",
                    "start_delay_ms",
                    "loop_delay_ms",
                    "sweep",
                    "trigger_source",
                    "sync_timeout_ms",
                ],
            },
        )
