from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/usac-protocol-v1.json"


def test_protocol_schema_defines_header_crc_and_first_m1_messages() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["byte_order"] == "little"
    assert [field["name"] for field in schema["header"]] == [
        "magic",
        "protocol_version",
        "message_type",
        "flags",
        "sequence",
        "payload_length",
    ]
    assert schema["crc32"]["coverage"] == "protocol_version_through_payload"
    messages = {item["name"]: item for item in schema["messages"]}
    assert {
        "HELLO",
        "GET_CONFIG",
        "SET_CONFIG",
        "CAPTURE_ONCE",
        "RUN_IO2_LOOPBACK_TEST",
        "CAPTURE_DATA",
        "BRIDGE_CAPTURE_DELIVERY",
        "CAPTURE_COMMITTED",
        "ACK",
        "ERROR",
    } <= messages.keys()
    assert messages["HELLO"]["request_length"] == 20
    assert messages["CAPTURE_ONCE"]["request_length"] == 60
    assert messages["RUN_IO2_LOOPBACK_TEST"]["request_length"] == 56
    assert messages["RUN_IO2_LOOPBACK_TEST"]["response_length"] == 86
    assert messages["CAPTURE_DATA"]["payload_schema_version"] == 1
    assert schema["capture_quality_flags"]["TIMING_UNCALIBRATED"] == 0x20


def test_protocol_schema_expands_config_capture_fields_and_error_codes() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert [field["name"] for field in schema["acquisition_config_v2"]["fields"]] == [
        "profile_schema_version",
        "sample_interval_ticks",
        "sample_count",
        "pretrigger_count",
        "adc_bits",
        "aux_flags",
        "vref_mv",
        "burst_period_ticks",
        "register_count",
        "reserved",
        "register_pairs",
        "profile_sha256",
        "device_config_crc32",
    ]
    messages = {item["name"]: item for item in schema["messages"]}
    capture_names = [field["name"] for field in messages["CAPTURE_DATA"]["fixed_header_fields"]]
    assert capture_names[0:4] == [
        "payload_schema_version",
        "fixed_header_length",
        "request_id",
        "schedule_id",
    ]
    assert capture_names[-2:] == ["reserved", "sample_bytes"]
    error_codes = {item["name"]: item["value"] for item in schema["error_codes"]}
    assert error_codes["OK"] == 0
    assert error_codes["UNSAFE_CONFIG"] == 25
    assert error_codes["UNSUPPORTED_HARDWARE_PROFILE"] == 27
    assert error_codes["IO2_LOOPBACK_FAILED"] == 28
