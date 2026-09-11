from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path

import pytest

from usac_runtime.bridge_cli import _parser, main
from usac_runtime.bridge_session import new_sqlite_integer_id


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "runtime.toml"
    path.write_text(
        "\n".join(
            [
                "[serial]",
                'port = "COM9"',
                "baudrate = 115200",
                "timeout_ms = 2000",
                "",
                "[storage]",
                f'data_dir = "{(tmp_path / "data").as_posix()}"',
                f'spool_dir = "{(tmp_path / "spool").as_posix()}"',
                f'sqlite_path = "{(tmp_path / "core.sqlite3").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_bridge_service_arguments_are_top_level() -> None:
    args = _parser().parse_args(
        [
            "--config",
            "runtime.toml",
            "--core-host",
            "core",
            "--core-port",
            "8765",
            "--confirm-external-vpwr-7v",
        ]
    )

    assert args.config == Path("runtime.toml")
    assert args.core_host == "core"
    assert args.core_port == 8765
    assert args.confirm_external_vpwr_7v is True


@pytest.mark.parametrize("removed_mode", ["capture", "replay"])
def test_bridge_rejects_removed_one_shot_modes(removed_mode: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([removed_mode, "--config", "runtime.toml"])


def test_bridge_cli_module_invokes_main() -> None:
    """The Compose entrypoint must execute, not only import definitions."""

    result = subprocess.run(
        [sys.executable, "-m", "usac_runtime.bridge_cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "TUSS4470 USB CDC bridge service" in result.stdout


def test_bridge_refuses_startup_before_importing_serial_without_power_confirmation(
    tmp_path: Path, monkeypatch,
) -> None:
    config = _config(tmp_path)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "serial":
            raise AssertionError("serial must not be imported before the power gate")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SystemExit, match="external VPWR"):
        main(["--config", str(config)])


@pytest.mark.parametrize(
    "random_value, expected", [(0, 1), ((1 << 63) - 1, (1 << 63) - 1)]
)
def test_connection_id_stays_in_positive_sqlite_range(
    random_value: int, expected: int, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "usac_runtime.bridge_session.secrets.randbits", lambda bits: random_value
    )

    assert new_sqlite_integer_id() == expected
