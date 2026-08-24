from __future__ import annotations

from pathlib import Path

from usac_protocol.parameters import ParameterSchema
from usac_protocol.config_v2 import D10X4_REGISTER_PAIRS


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"

EXPECTED_DEVICE_FIELDS = {
    "BPF_HPF_FREQ",
    "BPF_BYPASS",
    "BPF_FC_TRIM_FRC",
    "BPF_FC_TRIM",
    "BPF_Q_SEL",
    "LOGAMP_INT_ADJ",
    "LOGAMP_SLOPE_ADJ",
    "LOGAMP_FRC",
    "LNA_GAIN",
    "VOUT_SCALE_SEL",
    "LOGAMP_DIS_LAST_GM",
    "LOGAMP_DIS_FIRST_GM",
    "IO_MODE",
    "DRV_PLS_FLT_DT",
    "VDRV_VOLTAGE_LEVEL",
    "VDRV_CURRENT_LEVEL",
    "VDRV_HI_Z",
    "DIS_VDRV_REG_LSTN",
    "ECHO_INT_THR_SEL",
    "ECHO_INT_CMP_EN",
    "ZC_CMP_HYST",
    "ZC_CMP_STG_SEL",
    "ZC_CMP_IN_SEL",
    "ZC_EN_ECHO_INT",
    "ZC_CMP_EN",
    "BURST_PULSE",
    "PRE_DRIVER_MODE",
    "HALF_BRG_MODE",
    "CMD_TRIGGER",
    "VDRV_TRIGGER",
    "STDBY_MODE_EN",
    "SLEEP_MODE_EN",
}

EXPECTED_NONREGISTER_FIELDS = {
    "requested_burst_frequency_hz",
    "burst_period_ticks",
    "requested_sample_rate_hz",
    "requested_record_ms",
    "sample_interval_ticks",
    "sample_count",
    "pretrigger_count",
    "out3_enabled",
    "out4_enabled",
    "loops",
    "start_delay_ms",
    "loop_delay_ms",
    "sweep",
    "trigger_source",
    "sync_timeout_ms",
}


def test_schema_covers_all_device_and_acquisition_fields() -> None:
    schema = ParameterSchema.load(SCHEMA_PATH)

    assert set(schema.register_fields) == EXPECTED_DEVICE_FIELDS
    assert set(schema.nonregister_fields) == EXPECTED_NONREGISTER_FIELDS


def test_register_masks_cover_exact_write_masks_without_overlap() -> None:
    schema = ParameterSchema.load(SCHEMA_PATH)

    assert schema.combined_masks() == {
        0x10: 0xFF,
        0x11: 0x3F,
        0x12: 0xFF,
        0x13: 0xC7,
        0x14: 0x1F,
        0x16: 0x7F,
        0x17: 0x1F,
        0x18: 0xFF,
        0x1A: 0xFF,
        0x1B: 0xC3,
    }


def test_every_register_field_round_trips_all_enum_or_boundary_values() -> None:
    schema = ParameterSchema.load(SCHEMA_PATH)

    for field in schema.register_fields.values():
        for semantic_value in field.test_values:
            encoded = schema.encode_field(field.name, semantic_value, register_value=0)
            assert schema.decode_field(field.name, encoded) == semantic_value


def test_schema_marks_hardware_and_state_restricted_controls() -> None:
    schema = ParameterSchema.load(SCHEMA_PATH)

    assert schema.register_fields["PRE_DRIVER_MODE"].safety == "hardware_restricted"
    assert schema.register_fields["BURST_PULSE"].safety == "burst_guarded"
    assert schema.register_fields["CMD_TRIGGER"].sweepable is False
    assert schema.register_fields["SLEEP_MODE_EN"].mutable_states == ("IDLE",)


def test_field_defaults_compile_to_d10x4_running_register_image() -> None:
    schema = ParameterSchema.load(SCHEMA_PATH)
    registers = {address: 0 for address in schema.register_write_masks}

    for field in schema.register_fields.values():
        registers[field.address] = schema.encode_field(
            field.name, field.default, register_value=registers[field.address]
        )

    assert tuple(registers.items()) == D10X4_REGISTER_PAIRS


def test_gui_physical_value_conversions_are_machine_readable() -> None:
    schema = ParameterSchema.load(SCHEMA_PATH)

    bpf = schema.register_fields["BPF_HPF_FREQ"].metadata["display_table_khz"]
    assert bpf["46"] == 472.03
    slope = schema.register_fields["LOGAMP_SLOPE_ADJ"].metadata["display_table_v_per_v"]
    assert slope["0"] == {"3.3_v": 3.0, "5.0_v": 4.56}
    assert schema.register_fields["VDRV_VOLTAGE_LEVEL"].metadata["formula"] == (
        "vdrv_volts = code + 5"
    )
    assert schema.register_fields["ECHO_INT_THR_SEL"].metadata["formula"] == {
        "3.3_v": "threshold_v = 0.04 * code + 0.4",
        "5.0_v": "threshold_v = 0.06 * code + 0.6",
    }
