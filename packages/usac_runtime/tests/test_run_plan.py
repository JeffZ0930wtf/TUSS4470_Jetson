from __future__ import annotations

from pathlib import Path

import pytest

from usac_runtime.parameter_service import ConfigState, ParameterService
from usac_runtime.run_plan import RunPlanError, RunPlanV1, SweepPlan, compile_run_steps


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "protocol/schema/tuss4470-parameters-v1.yaml"


@pytest.fixture
def service() -> ParameterService:
    return ParameterService.from_schema_file(SCHEMA_PATH, smclk_hz=24_000_000)


def test_default_run_plan_is_one_software_capture(service: ParameterService) -> None:
    plan = RunPlanV1()

    steps = compile_run_steps(service, service.new_draft(), plan)

    assert plan.to_dict() == {
        "loops": 1,
        "start_delay_ms": 0,
        "loop_delay_ms": 0,
        "trigger_source": "SOFTWARE",
        "sync_timeout_ms": 0,
        "sweep": None,
    }
    assert len(steps) == 1
    assert steps[0].snapshot.state is ConfigState.VALIDATED
    assert steps[0].sweep_index is None
    assert steps[0].loop_index == 0


def test_sweep_expands_each_safe_value_then_each_loop(service: ParameterService) -> None:
    plan = RunPlanV1(
        loops=2,
        sweep=SweepPlan("BURST_PULSE", (1, 2, 3)),
    )

    steps = compile_run_steps(service, service.new_draft(), plan)

    assert [(step.sweep_index, step.loop_index) for step in steps] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
        (2, 0),
        (2, 1),
    ]
    assert [step.snapshot.requested["BURST_PULSE"] for step in steps] == [1, 1, 2, 2, 3, 3]
    assert all(step.compiled.sample_count == 2048 for step in steps)


def test_run_plan_rejects_invalid_sync_and_unbounded_local_expansion(
    service: ParameterService,
) -> None:
    with pytest.raises(RunPlanError, match="Sync Timeout"):
        compile_run_steps(
            service,
            service.new_draft(),
            RunPlanV1(trigger_source="EXTERNAL_SYNC_SLAVE", sync_timeout_ms=0),
        )
    with pytest.raises(RunPlanError, match="lease"):
        compile_run_steps(service, service.new_draft(), RunPlanV1(loops=0))


@pytest.mark.parametrize(
    ("sweep", "message"),
    [
        (SweepPlan("CMD_TRIGGER", (False, True)), "not sweepable"),
        (SweepPlan("PRE_DRIVER_MODE", (False, True)), "not sweepable"),
        (SweepPlan("BURST_PULSE", (1, 0)), "cannot be applied"),
        (SweepPlan("BURST_PULSE", tuple(range(257))), "256"),
    ],
)
def test_sweep_rejects_state_controls_unsafe_values_and_too_many_points(
    service: ParameterService,
    sweep: SweepPlan,
    message: str,
) -> None:
    with pytest.raises(RunPlanError, match=message):
        compile_run_steps(service, service.new_draft(), RunPlanV1(sweep=sweep))
