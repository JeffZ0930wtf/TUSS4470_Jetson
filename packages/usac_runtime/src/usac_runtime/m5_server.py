"""Launch the M5 REST/Web core with an explicit development backend.

The simulator backend is intentionally named and selected explicitly. It is
used for software and UI verification only and never claims hardware evidence.
The physical bridge backend is introduced behind the same application boundary.
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Sequence

import uvicorn

from usac_protocol.simulator import SimulatedDevice

from .application import AcquisitionApplication
from .bridge_device_client import BridgeDeviceClient, ReconnectableBridgeDeviceClient
from .core_store import CaptureStore
from .device_executor import SingleDeviceExecutor
from .m5_api import create_api
from .parameter_service import ParameterService
from .simulated_device_client import SimulatedDeviceClient


_LOGGER = logging.getLogger(__name__)


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


def create_bridge_api(
    *,
    schema_path: Path,
    database_path: Path,
    connection: socket.socket,
    timeout_s: float,
):
    """Build the same application around one physical bridge connection."""

    service = ParameterService.from_schema_file(schema_path, smclk_hz=24_000_000)
    store = CaptureStore(database_path)
    device = ReconnectableBridgeDeviceClient(
        BridgeDeviceClient(connection, timeout_s=timeout_s, replay_store=store)
    )
    application = AcquisitionApplication(
        service,
        SingleDeviceExecutor(service, device),
        device,
        store=store,
    )
    api = create_api(application)
    # The process entry point owns the listener, while the API keeps one stable
    # device object whose underlying HELLO session can be replaced.
    api.state.bridge_device = device
    api.state.capture_store = store
    return api


def accept_replacement_bridge(
    listener,
    device: ReconnectableBridgeDeviceClient,
    *,
    client_factory: Callable[[socket.socket], BridgeDeviceClient],
) -> None:
    """Accept and fully initialize one bridge before publishing it to callers."""

    connection, _ = listener.accept()
    try:
        replacement = client_factory(connection)
    except Exception:
        connection.close()
        raise
    device.replace(replacement)


def _accept_replacement_bridges(
    listener: socket.socket,
    device: ReconnectableBridgeDeviceClient,
    *,
    client_factory: Callable[[socket.socket], BridgeDeviceClient],
) -> None:
    """Keep accepting fresh bridge sessions until the core listener closes."""

    while True:
        try:
            accept_replacement_bridge(
                listener,
                device,
                client_factory=client_factory,
            )
        except OSError:
            return
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as error:
            _LOGGER.warning("replacement bridge session rejected: %s", error)


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
    parser.add_argument("--backend", choices=("simulator", "bridge"), default="simulator")
    parser.add_argument("--bridge-host", default="0.0.0.0")
    parser.add_argument("--bridge-port", type=int, default=8765)
    parser.add_argument("--bridge-wait-s", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    if args.backend == "simulator":
        api = create_simulator_api(
            schema_path=args.schema,
            database_path=args.database,
        )
    else:
        if args.bridge_wait_s <= 0:
            raise SystemExit("--bridge-wait-s must be positive")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.bridge_host, args.bridge_port))
        listener.listen(1)
        listener.settimeout(args.bridge_wait_s)
        try:
            connection, _ = listener.accept()
        except TimeoutError as error:
            listener.close()
            raise SystemExit("timed out waiting for the configured bridge") from error
        api = create_bridge_api(
            schema_path=args.schema,
            database_path=args.database,
            connection=connection,
            timeout_s=args.bridge_wait_s,
        )
        device = api.state.bridge_device
        store = api.state.capture_store
        listener.settimeout(None)
        replacement_worker = threading.Thread(
            target=_accept_replacement_bridges,
            args=(listener, device),
            kwargs={
                "client_factory": lambda item: BridgeDeviceClient(
                    item,
                    timeout_s=args.bridge_wait_s,
                    replay_store=store,
                )
            },
            name="usac-core-bridge-acceptor",
            daemon=True,
        )
        replacement_worker.start()
    try:
        uvicorn.run(api, host=args.host, port=args.port)
    finally:
        if args.backend == "bridge":
            listener.close()
            device.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
