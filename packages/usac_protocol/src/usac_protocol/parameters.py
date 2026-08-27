"""Loads and validates the first-party semantic TUSS4470 parameter registry.

The registry is the shared source for field names, masks, units, and legal
values; clients must not maintain independent GUI or API option tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RegisterField:
    name: str
    address: int
    mask: int
    shift: int
    encoding: dict[str, Any]
    default: object
    sweepable: bool
    mutable_states: tuple[str, ...]
    safety: str
    readback: str
    metadata: dict[str, Any]

    @property
    def test_values(self) -> tuple[object, ...]:
        kind = self.encoding["kind"]
        if kind == "bool":
            return (False, True)
        if kind == "enum":
            return tuple(item["value"] for item in self.encoding["values"])
        if kind == "uint":
            minimum = self.encoding["min"]
            maximum = self.encoding["max"]
            return (minimum,) if minimum == maximum else (minimum, maximum)
        raise ValueError(f"unsupported encoding kind {kind!r}")

    def encode(self, semantic_value: object) -> int:
        kind = self.encoding["kind"]
        if kind == "bool":
            if not isinstance(semantic_value, bool):
                raise ValueError(f"{self.name} requires a boolean")
            return int(semantic_value)
        if kind == "uint":
            if not isinstance(semantic_value, int) or isinstance(semantic_value, bool):
                raise ValueError(f"{self.name} requires an integer")
            if not self.encoding["min"] <= semantic_value <= self.encoding["max"]:
                raise ValueError(f"{self.name} is outside its legal range")
            return semantic_value
        if kind == "enum":
            for item in self.encoding["values"]:
                if item["value"] == semantic_value:
                    return item["code"]
            raise ValueError(f"{self.name} has an unknown enum value")
        raise ValueError(f"unsupported encoding kind {kind!r}")

    def decode(self, code: int) -> object:
        kind = self.encoding["kind"]
        if kind == "bool":
            if code not in (0, 1):
                raise ValueError(f"{self.name} has an invalid boolean code")
            return bool(code)
        if kind == "uint":
            if not self.encoding["min"] <= code <= self.encoding["max"]:
                raise ValueError(f"{self.name} has an out-of-range register code")
            return code
        if kind == "enum":
            for item in self.encoding["values"]:
                if item["code"] == code:
                    return item["value"]
            raise ValueError(f"{self.name} has an unknown register code")
        raise ValueError(f"unsupported encoding kind {kind!r}")


@dataclass(frozen=True, slots=True)
class ParameterSchema:
    register_fields: dict[str, RegisterField]
    nonregister_fields: dict[str, dict[str, Any]]
    register_write_masks: dict[int, int]

    @classmethod
    def load(cls, path: Path) -> ParameterSchema:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema_name") != "tuss4470-parameters-v1":
            raise ValueError("unexpected parameter schema name")
        if document.get("schema_version") != 1:
            raise ValueError("unsupported parameter schema version")
        registers = {item["address"]: item["write_mask"] for item in document["registers"]}
        fields: dict[str, RegisterField] = {}
        for item in document["register_fields"]:
            core_keys = {
                "name",
                "address",
                "mask",
                "shift",
                "encoding",
                "default",
                "sweepable",
                "mutable_states",
                "safety",
                "readback",
            }
            field = RegisterField(
                name=item["name"],
                address=item["address"],
                mask=item["mask"],
                shift=item["shift"],
                encoding=item["encoding"],
                default=item["default"],
                sweepable=item["sweepable"],
                mutable_states=tuple(item["mutable_states"]),
                safety=item["safety"],
                readback=item["readback"],
                metadata={key: value for key, value in item.items() if key not in core_keys},
            )
            if field.name in fields:
                raise ValueError(f"duplicate parameter {field.name}")
            fields[field.name] = field
        nonregister = {item["name"]: item for item in document["nonregister_fields"]}
        schema = cls(fields, nonregister, registers)
        schema.combined_masks()
        return schema

    def combined_masks(self) -> dict[int, int]:
        combined = {address: 0 for address in self.register_write_masks}
        for field in self.register_fields.values():
            if field.address not in combined:
                raise ValueError(f"field {field.name} uses an undeclared register")
            if combined[field.address] & field.mask:
                raise ValueError(f"field {field.name} overlaps another field")
            width_mask = field.mask >> field.shift
            if field.mask != width_mask << field.shift:
                raise ValueError(f"field {field.name} mask is not aligned to shift")
            combined[field.address] |= field.mask
        if combined != self.register_write_masks:
            raise ValueError("field masks do not exactly cover register write masks")
        return combined

    def encode_field(self, name: str, semantic_value: object, *, register_value: int) -> int:
        field = self.register_fields[name]
        code = field.encode(semantic_value)
        width_mask = field.mask >> field.shift
        if code & ~width_mask:
            raise ValueError(f"{name} does not fit its register field")
        return (register_value & ~field.mask) | ((code << field.shift) & field.mask)

    def decode_field(self, name: str, register_value: int) -> object:
        field = self.register_fields[name]
        return field.decode((register_value & field.mask) >> field.shift)
