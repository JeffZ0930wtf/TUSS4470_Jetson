from __future__ import annotations

import pytest

from usac_runtime.m3_capture import M3CaptureProgress
from usac_runtime.m3_cli import _print_progress, main
from usac_runtime.m3_loopback_cli import main as loopback_main


def test_m3_cli_refuses_usb_only_invocation_before_opening_serial() -> None:
    with pytest.raises(SystemExit, match="external-vpwr-7v"):
        main(["--port", "COM9", "--output-dir", "ignored"])


def test_m3_cli_requires_the_physical_resistor_loopback_confirmation() -> None:
    with pytest.raises(SystemExit, match="loopback-pin40-2k2-pin38"):
        main(
            [
                "--port",
                "COM9",
                "--output-dir",
                "ignored",
                "--confirm-external-vpwr-7v",
            ]
        )


def test_m3_loopback_cli_refuses_without_both_hardware_confirmations() -> None:
    with pytest.raises(SystemExit, match="external-vpwr-7v"):
        loopback_main(["--port", "COM9"])
    with pytest.raises(SystemExit, match="loopback-pin40-2k2-pin38"):
        loopback_main(["--port", "COM9", "--confirm-external-vpwr-7v"])


def test_m3_cli_writes_progress_only_to_stderr(capsys) -> None:
    _print_progress(M3CaptureProgress("capture_data_receiving", 36, 4324))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "M3 progress: stage=capture_data_receiving "
        "received_bytes=36 expected_bytes=4324\n"
    )


def test_m3_cli_prints_zero_received_bytes(capsys) -> None:
    _print_progress(M3CaptureProgress("capture_once_sent"))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "M3 progress: stage=capture_once_sent received_bytes=0\n"
