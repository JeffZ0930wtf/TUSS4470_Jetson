from __future__ import annotations

from pathlib import Path

import pytest

from usac_runtime.parameter_service import (
    ConfigState,
    ParameterService,
    ValidationCode,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"


@pytest.fixture
def service() -> ParameterService:
    return ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)


def test_registry_view_is_the_single_client_parameter_source(service: ParameterService) -> None:
    registry = service.registry_view()

    assert registry["schema_name"] == "tuss4470-parameters-v1"
    assert registry["schema_version"] == 1
    # 32 TUSS4470 register fields plus 15 acquisition/run fields.
    assert len(registry["fields"]) == 47
    by_name = {field["name"]: field for field in registry["fields"]}
    assert by_name["BPF_Q_SEL"]["group"] == "BPF_CONFIG_2"
    assert by_name["BPF_Q_SEL"]["values"] == ["q4", "q5", "q2", "q3"]
    assert by_name["requested_sample_rate_hz"]["minimum"] == 25_000
    assert by_name["requested_sample_rate_hz"]["maximum"] == 200_000
    assert by_name["sample_count"]["read_only"] is True


def test_default_draft_compiles_to_the_d10x4_baseline(service: ParameterService) -> None:
    draft = service.new_draft()
    result = service.validate(draft)

    assert draft.state is ConfigState.DRAFT
    assert result.snapshot.state is ConfigState.VALIDATED
    assert result.errors == ()
    assert result.compiled is not None
    assert result.compiled.sample_interval_ticks == 120
    assert result.compiled.burst_period_ticks == 50
    assert result.compiled.sample_count == 2048
    assert result.snapshot.actual["sample_rate_hz"] == pytest.approx(200_000)
    assert result.snapshot.actual["record_ms"] == pytest.approx(10.24)
    assert result.snapshot.actual["burst_frequency_hz"] == pytest.approx(480_000)


def test_frequency_and_sampling_requests_quantize_to_integer_ticks_without_interpolation(
    service: ParameterService,
) -> None:
    draft = service.update_draft(
        service.new_draft(),
        {
            "requested_burst_frequency_hz": 479_400,
            "requested_sample_rate_hz": 199_000,
        },
    )
    result = service.validate(draft)

    assert result.errors == ()
    assert result.compiled is not None
    assert result.compiled.burst_period_ticks == 50
    assert result.compiled.sample_interval_ticks == 121
    assert result.compiled.sample_count == 2048
    assert result.snapshot.requested["requested_burst_frequency_hz"] == 479_400
    assert result.snapshot.requested["requested_sample_rate_hz"] == 199_000
    assert result.snapshot.actual["burst_frequency_hz"] == pytest.approx(480_000)
    assert result.snapshot.actual["sample_rate_hz"] == pytest.approx(24_000_000 / 121)
    assert result.snapshot.actual["record_ms"] == pytest.approx(2048 * 121 / 24_000)


@pytest.mark.parametrize(
    ("change", "field", "code"),
    [
        ({"BURST_PULSE": 0}, "BURST_PULSE", ValidationCode.UNSAFE_CONFIG),
        (
            {"PRE_DRIVER_MODE": True},
            "PRE_DRIVER_MODE",
            ValidationCode.UNSUPPORTED_HARDWARE_PROFILE,
        ),
        ({"VOUT_SCALE_SEL": "5.0_v"}, "VOUT_SCALE_SEL", ValidationCode.UNSAFE_CONFIG),
        ({"VDRV_CURRENT_LEVEL": "20_ma"}, "VDRV_CURRENT_LEVEL", ValidationCode.UNSAFE_CONFIG),
    ],
)
def test_datasheet_legal_but_unsafe_values_remain_draft_with_field_error(
    service: ParameterService,
    change: dict[str, object],
    field: str,
    code: ValidationCode,
) -> None:
    draft = service.update_draft(service.new_draft(), change)
    result = service.validate(draft)

    assert draft.state is ConfigState.DRAFT
    assert result.snapshot.state is ConfigState.DRAFT
    assert result.snapshot.requested[field] == change[field]
    assert result.compiled is None
    assert [(error.field, error.code) for error in result.errors] == [(field, code)]


def test_applied_requires_exact_register_and_timing_readback(service: ParameterService) -> None:
    validated = service.validate(service.new_draft()).snapshot
    compiled = service.validate(service.new_draft()).compiled
    assert compiled is not None

    applied = service.mark_applied(
        validated,
        register_readback=compiled.register_pairs,
        sample_interval_ticks=compiled.sample_interval_ticks,
        burst_period_ticks=compiled.burst_period_ticks,
    )

    assert applied.state is ConfigState.APPLIED
    assert applied.readback["register_pairs"] == [list(pair) for pair in compiled.register_pairs]

    bad_readback = tuple(
        (address, value ^ 0x01 if address == 0x10 else value)
        for address, value in compiled.register_pairs
    )
    with pytest.raises(ValueError, match="readback"):
        service.mark_applied(
            validated,
            register_readback=bad_readback,
            sample_interval_ticks=compiled.sample_interval_ticks,
            burst_period_ticks=compiled.burst_period_ticks,
        )
