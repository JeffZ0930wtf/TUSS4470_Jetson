"""First-version loops, delay, sweep, and synchronization plan model.

This module expands only finite plans. Infinite operation is deliberately left
to the firmware-backed periodic lease path so a host failure cannot leave an
unbounded local loop issuing new Burst commands.
"""

from __future__ import annotations

from dataclasses import dataclass

from usac_protocol.config_v2 import AcquisitionConfigV2

from .parameter_service import ConfigurationSnapshot, ParameterService


class RunPlanError(ValueError):
    """A plan cannot be executed within the first-version safety contract."""


@dataclass(frozen=True, slots=True)
class SweepPlan:
    field: str
    values: tuple[object, ...]

    def to_dict(self) -> dict[str, object]:
        return {"field": self.field, "values": list(self.values)}


@dataclass(frozen=True, slots=True)
class RunPlanV1:
    loops: int = 1
    start_delay_ms: int = 0
    loop_delay_ms: int = 0
    sweep: SweepPlan | None = None
    trigger_source: str = "SOFTWARE"
    sync_timeout_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "loops": self.loops,
            "start_delay_ms": self.start_delay_ms,
            "loop_delay_ms": self.loop_delay_ms,
            "trigger_source": self.trigger_source,
            "sync_timeout_ms": self.sync_timeout_ms,
            "sweep": None if self.sweep is None else self.sweep.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RunStep:
    sweep_index: int | None
    loop_index: int
    snapshot: ConfigurationSnapshot
    compiled: AcquisitionConfigV2


def _bounded_integer(name: str, value: object, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise RunPlanError(f"{name} must be an integer in 0..{maximum}")
    return value


def _validate_plan(plan: RunPlanV1) -> None:
    loops = _bounded_integer("Loops", plan.loops, 0xFFFFFFFF)
    _bounded_integer("Start Delay", plan.start_delay_ms, 3_600_000)
    _bounded_integer("Loop Delay", plan.loop_delay_ms, 3_600_000)
    if loops == 0:
        raise RunPlanError("Loops=0 requires the firmware periodic lease path")
    if plan.trigger_source not in {
        "SOFTWARE",
        "EXTERNAL_SYNC_SLAVE",
        "EXTERNAL_SYNC_MASTER",
    }:
        raise RunPlanError("Trigger Source is invalid")
    if plan.trigger_source == "EXTERNAL_SYNC_SLAVE":
        if not 1 <= plan.sync_timeout_ms <= 60_000:
            raise RunPlanError("Sync Timeout must be in 1..60000 ms for Slave")
    elif plan.sync_timeout_ms != 0:
        raise RunPlanError("Sync Timeout must be zero outside Slave mode")


def _validated_target(
    service: ParameterService,
    snapshot: ConfigurationSnapshot,
    *,
    description: str,
) -> tuple[ConfigurationSnapshot, AcquisitionConfigV2]:
    result = service.validate(snapshot)
    if result.errors or result.compiled is None:
        detail = ", ".join(f"{error.field}:{error.code.value}" for error in result.errors)
        raise RunPlanError(f"{description} cannot be applied: {detail}")
    return result.snapshot, result.compiled


def compile_run_steps(
    service: ParameterService,
    baseline: ConfigurationSnapshot,
    plan: RunPlanV1,
) -> tuple[RunStep, ...]:
    """Validate and deterministically expand a finite plan without device IO."""

    _validate_plan(plan)
    targets: list[tuple[int | None, ConfigurationSnapshot, AcquisitionConfigV2]] = []
    if plan.sweep is None:
        snapshot, compiled = _validated_target(service, baseline, description="baseline")
        targets.append((None, snapshot, compiled))
    else:
        sweep = plan.sweep
        if not 1 <= len(sweep.values) <= 256:
            raise RunPlanError("Sweep must contain 1..256 discrete points")
        if sweep.field in service.schema.register_fields:
            sweepable = service.schema.register_fields[sweep.field].sweepable
        elif sweep.field in service.schema.nonregister_fields:
            sweepable = bool(service.schema.nonregister_fields[sweep.field]["sweepable"])
        else:
            raise RunPlanError(f"unknown Sweep field {sweep.field}")
        if not sweepable:
            raise RunPlanError(f"{sweep.field} is not sweepable")

        for index, value in enumerate(sweep.values):
            try:
                draft = service.update_draft(baseline, {sweep.field: value})
            except ValueError as error:
                raise RunPlanError(f"Sweep point {index} is invalid: {error}") from error
            snapshot, compiled = _validated_target(
                service,
                draft,
                description=f"Sweep point {index}",
            )
            targets.append((index, snapshot, compiled))

    return tuple(
        RunStep(sweep_index, loop_index, snapshot, compiled)
        for sweep_index, snapshot, compiled in targets
        for loop_index in range(plan.loops)
    )
