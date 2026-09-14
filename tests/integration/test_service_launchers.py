from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JETSON_SCRIPT = ROOT / "scripts" / "start-jetson.sh"
WINDOWS_SCRIPT = ROOT / "scripts" / "start-jetson.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
BASH = shutil.which("bash") or Path(r"C:\Program Files\Git\bin\bash.exe")


def _bash_path(path: Path) -> str:
    """Translate a Windows drive path for the Git Bash test process."""

    resolved = path.resolve().as_posix()
    if os.name == "nt" and len(resolved) > 2 and resolved[1] == ":":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def _run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )


class _HealthHandler(BaseHTTPRequestHandler):
    device_requests = 0

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/api/v1/health":
            document = {"status": "ok"}
        elif self.path == "/api/v1/device":
            type(self).device_requests += 1
            document = {
                "connected": True,
                "health": "NORMAL",
                "activity": "IDLE",
                "backend": "BRIDGE",
                "status": {"vdrv_ready": 1},
            }
        else:
            self.send_error(404)
            return
        payload = json.dumps(document).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class ServiceLauncherTests(unittest.TestCase):
    def test_jetson_launcher_requires_explicit_7v_confirmation(self) -> None:
        result = _run([str(BASH), _bash_path(JETSON_SCRIPT)])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-external-vpwr-7v", result.stderr)

    def test_windows_launcher_requires_explicit_7v_confirmation(self) -> None:
        self.assertIsNotNone(POWERSHELL)
        result = _run(
            [
                str(POWERSHELL),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WINDOWS_SCRIPT),
                "-NoBrowser",
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ExternalVpwr7VConfirmed", result.stderr)

    def test_jetson_launcher_starts_compose_and_waits_for_device(self) -> None:
        # Keep the Git Bash fixture path ASCII-only; the Windows user profile
        # contains non-ASCII characters that MSYS may decode with a legacy codepage.
        with tempfile.TemporaryDirectory(prefix=".launcher-test-", dir=ROOT) as directory:
            temporary = Path(directory)
            command_log = temporary / "docker.log"
            docker = temporary / "docker"
            curl = temporary / "curl"
            serial = temporary / "ttyACM-test"
            serial.touch()
            docker.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$FAKE_DOCKER_LOG"\n'
                "exit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            curl.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                '  *api/v1/health*) printf \'%s\\n\' \'{"status":"ok"}\' ;;\n'
                '  *api/v1/device*) printf \'%s\\n\' \'{"connected":true,"health":"NORMAL","activity":"IDLE","status":{"vdrv_ready":1}}\' ;;\n'
                "  *) exit 22 ;;\n"
                "esac\n",
                encoding="utf-8",
                newline="\n",
            )
            os.chmod(docker, 0o755)
            os.chmod(curl, 0o755)
            env = os.environ.copy()
            env.update(
                {
                    "FAKE_DOCKER_LOG": _bash_path(command_log),
                    "USAC_DOCKER_BIN": _bash_path(docker),
                    "USAC_CURL_BIN": _bash_path(curl),
                    "USAC_SERIAL_DEVICE": _bash_path(serial),
                    "USAC_CORE_DATA_DIR": _bash_path(temporary / "core"),
                    "USAC_BRIDGE_SPOOL_DIR": _bash_path(temporary / "spool"),
                    "USAC_LAUNCHER_LOG_DIR": _bash_path(temporary / "launcher"),
                    "USAC_READY_TIMEOUT_SECONDS": "2",
                    "USAC_READY_POLL_SECONDS": "0.01",
                }
            )
            env.pop("DISPLAY", None)
            env.pop("WAYLAND_DISPLAY", None)

            result = _run(
                [str(BASH), _bash_path(JETSON_SCRIPT), "--confirm-external-vpwr-7v"],
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            commands = command_log.read_text(encoding="utf-8").splitlines()
            starts = [line for line in commands if " up -d --no-build" in line]
            self.assertEqual(len(starts), 1)
            self.assertIn("http://127.0.0.1:8000/", result.stdout)
            self.assertIn("device ready", result.stdout.lower())

    def test_windows_launcher_reuses_a_healthy_existing_tunnel(self) -> None:
        self.assertIsNotNone(POWERSHELL)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            ssh_log = temporary / "ssh.log"
            fake_ssh = temporary / "ssh.cmd"
            identity = temporary / "test-key"
            identity.touch()
            fake_ssh.write_text(
                "@echo off\r\n"
                "echo %*>>\"%FAKE_SSH_LOG%\"\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
            _HealthHandler.device_requests = 0
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = os.environ.copy()
                env["FAKE_SSH_LOG"] = str(ssh_log)
                result = _run(
                    [
                        str(POWERSHELL),
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(WINDOWS_SCRIPT),
                        "-ExternalVpwr7VConfirmed",
                        "-NoBrowser",
                        "-SshExecutable",
                        str(fake_ssh),
                        "-IdentityFile",
                        str(identity),
                        "-LocalPort",
                        str(server.server_port),
                    ],
                    env=env,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = ssh_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 1)
            self.assertIn("./scripts/start-jetson.sh --confirm-external-vpwr-7v", calls[0])
            self.assertNotIn(" -N ", calls[0])
            self.assertIn("existing SSH tunnel", result.stdout)
            self.assertGreater(_HealthHandler.device_requests, 0)

    def test_jetson_launcher_records_compose_start_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".launcher-test-", dir=ROOT) as directory:
            temporary = Path(directory)
            docker = temporary / "docker"
            curl = temporary / "curl"
            serial = temporary / "ttyACM-test"
            serial.touch()
            docker.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                '  *" up -d --no-build"*) exit 17 ;;\n'
                '  *" logs "*) printf \'compose failed before readiness\\n\' ;;\n'
                "  *) exit 0 ;;\n"
                "esac\n",
                encoding="utf-8",
                newline="\n",
            )
            curl.write_text("#!/bin/sh\nexit 22\n", encoding="utf-8", newline="\n")
            os.chmod(docker, 0o755)
            os.chmod(curl, 0o755)
            launcher_logs = temporary / "launcher"
            env = os.environ.copy()
            env.update(
                {
                    "USAC_DOCKER_BIN": _bash_path(docker),
                    "USAC_CURL_BIN": _bash_path(curl),
                    "USAC_SERIAL_DEVICE": _bash_path(serial),
                    "USAC_CORE_DATA_DIR": _bash_path(temporary / "core"),
                    "USAC_BRIDGE_SPOOL_DIR": _bash_path(temporary / "spool"),
                    "USAC_LAUNCHER_LOG_DIR": _bash_path(launcher_logs),
                }
            )

            result = _run(
                [str(BASH), _bash_path(JETSON_SCRIPT), "--confirm-external-vpwr-7v"],
                env=env,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Diagnostic log:", result.stderr)
            logs = list(launcher_logs.glob("start-failure-*.log"))
            self.assertEqual(len(logs), 1)
            self.assertIn("compose failed before readiness", logs[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
