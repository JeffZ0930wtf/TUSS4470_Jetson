"""Launch the M5 REST/Web core with an explicit development backend.

The simulator backend is intentionally named and selected explicitly. It is
used for software and UI verification only and never claims hardware evidence.
The physical bridge backend is introduced behind the same application boundary.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from usac_protocol.simulator import SimulatedDevice

from .application import AcquisitionApplication
from .core_store import CaptureStore
from .device_executor import SingleDeviceExecutor
from .m5_api import create_api
from .parameter_service import ParameterService
from .simulated_device_client import SimulatedDeviceClient


def create_simulator_api(*, schema_path: Path, database_path: Path):
    """Build the complete host stack without opening serial or USB devices."""

    service = ParameterService.from_schema_file(schema_path, smclk_hz=24_000_000)
    device = SimulatedDeviceClient(SimulatedDevice())
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=CaptureStore(database_path),
    )
    return create_api(application)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M5 REST and Web acquisition core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("protocol/schema/tuss4470-parameters-v1.yaml"),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("runtime/core/captures.sqlite3"),
    )
    parser.add_argument("--backend", choices=("simulator",), default="simulator")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    api = create_simulator_api(
        schema_path=args.schema,
        database_path=args.database,
    )
    uvicorn.run(api, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
