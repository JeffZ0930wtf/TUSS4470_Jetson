"""Cross-platform USB CDC bridge service with durable capture delivery."""

from __future__ import annotations

import argparse
import socket
import time
from collections.abc import Sequence
from pathlib import Path

from usac_runtime.bridge_session import new_sqlite_integer_id, proxy_bridge_session
from usac_runtime.config import RuntimeConfig, load_runtime_config
from usac_runtime.reconnect import retry_connection, supervise_sessions
from usac_runtime.spool import CaptureSpool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TUSS4470 USB CDC bridge service")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--core-host", default="127.0.0.1")
    parser.add_argument("--core-port", type=int, default=8765)
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--reconnect-attempts", type=int, default=3)
    parser.add_argument("--reconnect-delay-s", type=float, default=0.1)
    parser.add_argument("--confirm-external-vpwr-7v", action="store_true")
    return parser


def _spool(config_path: Path) -> tuple[CaptureSpool, RuntimeConfig]:
    config = load_runtime_config(config_path)
    return CaptureSpool(config.storage.spool_dir / "bridge-spool.sqlite3"), config


def _serve(args: argparse.Namespace) -> int:
    """Keep one physical bridge service alive across USB/TCP session loss."""

    if not args.confirm_external_vpwr_7v:
        raise SystemExit("refusing bridge service without confirmed external VPWR 7 V")
    spool, config = _spool(args.config)
    try:
        import serial
    except ImportError as error:
        raise SystemExit("pyserial is required for bridge service") from error

    def run_one_session() -> None:
        # A fresh Serial object is important on Windows: after an S3 reset the
        # old handle may remain unusable even when the same COM name reappears.
        serial_connection = serial.Serial()
        serial_connection.port = config.serial.port
        serial_connection.baudrate = config.serial.baudrate
        serial_connection.timeout = min(args.timeout_s, 0.1)
        serial_connection.write_timeout = args.timeout_s
        serial_connection.dtr = False
        core_connection: socket.socket | None = None
        try:
            retry_connection(
                serial_connection.open,
                attempts=args.reconnect_attempts,
                initial_delay_s=args.reconnect_delay_s,
            )
            serial_connection.dtr = False
            time.sleep(0.150)
            serial_connection.reset_input_buffer()
            serial_connection.reset_output_buffer()
            serial_connection.dtr = True
            core_connection = retry_connection(
                lambda: socket.create_connection(
                    (args.core_host, args.core_port), timeout=args.timeout_s
                ),
                attempts=args.reconnect_attempts,
                initial_delay_s=args.reconnect_delay_s,
            )
            proxy_bridge_session(
                core_connection=core_connection,
                serial_connection=serial_connection,
                spool=spool,
                connection_id=new_sqlite_integer_id(),
                source_connection_id=new_sqlite_integer_id(),
                commit_timeout_s=args.timeout_s,
            )
        finally:
            if serial_connection.is_open:
                serial_connection.dtr = False
                time.sleep(0.100)
                serial_connection.close()
            if core_connection is not None:
                try:
                    core_connection.close()
                except OSError:
                    pass

    # Only transport sessions are restarted.  The failed command is never
    # retained or replayed; durable pending captures are recovered by spool ID.
    supervise_sessions(
        run_one_session,
        reconnect_delay_s=args.reconnect_delay_s,
        should_stop=lambda: False,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    if args.reconnect_attempts < 1 or args.reconnect_delay_s < 0:
        raise SystemExit("reconnect attempts must be positive and delay non-negative")
    return _serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
