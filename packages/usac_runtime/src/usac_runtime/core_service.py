"""Small single-device TCP service for the M4 container core."""

from __future__ import annotations

import argparse
import socket
from collections.abc import Sequence
from pathlib import Path

from usac_runtime.core_store import CaptureStore
from usac_runtime.delivery import handle_core_delivery


def open_listener(host: str, port: int) -> socket.socket:
    """Create the configured core listener; callers own its lifetime."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(1)
    return listener


def serve_connections(
    listener: socket.socket,
    store: CaptureStore,
    *,
    connection_limit: int | None = None,
) -> None:
    """Serve one delivery per connection, serially, until stopped or limited."""

    served = 0
    try:
        while connection_limit is None or served < connection_limit:
            connection, _ = listener.accept()
            with connection:
                handle_core_delivery(connection, store)
            served += 1
    finally:
        listener.close()


def _positive_limit(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("connection limit must be positive")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4 transactional capture core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--connection-limit", type=_positive_limit)
    args = parser.parse_args(argv)
    store = CaptureStore(args.sqlite)
    listener = open_listener(args.host, args.port)
    serve_connections(listener, store, connection_limit=args.connection_limit)
    return 0
