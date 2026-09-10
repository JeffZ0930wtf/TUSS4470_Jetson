from __future__ import annotations

import unittest
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


class ProjectLayoutTests(unittest.TestCase):
    def test_v1_public_commands_are_neutral_and_complete(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            metadata["project"]["scripts"],
            {
                "usac-core": "usac_runtime.core_server:main",
                "usac-bridge": "usac_runtime.bridge_cli:main",
                "usac-cli": "usac_runtime.client_cli:main",
                "usac-export": "usac_runtime.export_cli:main",
            },
        )

    def test_required_m0_files_exist(self) -> None:
        required = [
            "README.md",
            ".dockerignore",
            ".gitattributes",
            ".python-version",
            "pyproject.toml",
            "uv.lock",
            "config/windows.example.toml",
            "config/jetson.example.toml",
            "config/test.example.toml",
            "deploy/Dockerfile.core",
            "deploy/compose.yaml",
            "deploy/compose.jetson.yaml",
            "deploy/README-jetson.md",
            "firmware/Makefile",
            "firmware/src/main.c",
            "scripts/build-firmware.ps1",
            "scripts/check-env.ps1",
            "scripts/check-env.sh",
            "scripts/bootstrap-dev.ps1",
            "scripts/bootstrap-dev.sh",
            "scripts/test-all.ps1",
            "scripts/test-all.sh",
            "docs/adr/0001-cross-platform-toolchain.md",
        ]

        missing = [path for path in required if not (ROOT / path).is_file()]
        self.assertEqual(missing, [])

    def test_runtime_directories_are_not_hard_coded_to_windows_drive(self) -> None:
        package_root = ROOT / "packages/usac_runtime/src"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in package_root.rglob("*.py")
        )

        self.assertNotIn("D:\\\\", source)
        self.assertNotIn("C:\\\\", source)

    def test_development_environment_is_repository_local_and_reproducible(self) -> None:
        python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        windows_bootstrap = (ROOT / "scripts/bootstrap-dev.ps1").read_text(
            encoding="utf-8"
        )
        linux_bootstrap = (ROOT / "scripts/bootstrap-dev.sh").read_text(
            encoding="utf-8"
        )

        self.assertEqual(python_version, "3.12")
        self.assertIn("uv sync --frozen --extra dev", windows_bootstrap)
        self.assertIn("uv sync --frozen --extra dev", linux_bootstrap)
        self.assertIn("UV_PYTHON_INSTALL_DIR", windows_bootstrap)
        self.assertIn("UV_CACHE_DIR", windows_bootstrap)
        self.assertIn(".venv", windows_bootstrap)
        self.assertIn(".venv", linux_bootstrap)
        self.assertIn(".tools", windows_bootstrap)
        self.assertIn(".tools", linux_bootstrap)

    def test_container_base_is_digest_pinned_and_registry_is_reachable(self) -> None:
        dockerfile = (ROOT / "deploy/Dockerfile.core").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn("public.ecr.aws/docker/library/python:3.12-slim@sha256:", dockerfile)
        self.assertIn("RUN python -m pip install --no-cache-dir .", dockerfile)
        self.assertIn("packages/usac_protocol/src", dockerfile)
        self.assertIn("usac_runtime.m5_server", dockerfile)
        self.assertIn(".venv", dockerignore)
        self.assertIn(".tools", dockerignore)

    def test_host_automation_matches_the_platform_split(self) -> None:
        windows_test = (ROOT / "scripts/test-all.ps1").read_text(encoding="utf-8")
        jetson_test = (ROOT / "scripts/test-all.sh").read_text(encoding="utf-8")

        self.assertIn(".venv", windows_test)
        self.assertIn("build-firmware.ps1", windows_test)
        self.assertNotIn("docker ", windows_test.lower())
        self.assertIn(".venv", jetson_test)
        self.assertIn("linux/arm64", jetson_test)
        self.assertIn("linux/amd64", jetson_test)
        self.assertIn("m1-arm64", jetson_test)
        self.assertNotIn("make -C firmware", jetson_test)
        arm64_run = "docker run --rm --platform linux/arm64 --entrypoint python"
        amd64_export = "docker buildx build --platform linux/amd64"
        protocol_smoke = "usac_protocol.frame"
        self.assertIn(arm64_run, jetson_test)
        self.assertIn(protocol_smoke, jetson_test)
        self.assertLess(jetson_test.index(arm64_run), jetson_test.index(amd64_export))

    def test_windows_test_entrypoint_creates_pytest_build_parent(self) -> None:
        windows_test = (ROOT / "scripts/test-all.ps1").read_text(encoding="utf-8")

        create_parent = 'New-Item -ItemType Directory -Path $pytestParent -Force'
        pytest_call = " -m pytest --basetemp $pytestBaseTemp"
        self.assertIn("$pytestParent = Split-Path -Parent $pytestBaseTemp", windows_test)
        self.assertIn(create_parent, windows_test)
        self.assertLess(windows_test.index(create_parent), windows_test.index(pytest_call))

    def test_windows_test_entrypoint_builds_m3_diagnostic_before_audit(self) -> None:
        windows_test = (ROOT / "scripts/test-all.ps1").read_text(encoding="utf-8")

        build = "build-firmware-m3-adc-dma-diagnostic.ps1"
        audit = "test-m3-adc-dma-diagnostic-static.ps1"
        self.assertIn(build, windows_test)
        self.assertIn(audit, windows_test)
        self.assertLess(windows_test.index(build), windows_test.index(audit))

    def test_windows_test_entrypoint_includes_m5_firmware_gate(self) -> None:
        windows_test = (ROOT / "scripts/test-all.ps1").read_text(encoding="utf-8")

        required_steps = [
            "build-firmware-m5.ps1",
            "test-firmware-m5-burst-plan.ps1",
            "test-firmware-m5-schedule.ps1",
            "test-firmware-m5-app.ps1",
        ]
        for step in required_steps:
            self.assertIn(step, windows_test)

        self.assertLess(
            windows_test.index("build-firmware-m5.ps1"),
            windows_test.index("test-firmware-m5-app.ps1"),
        )

    def test_m0_firmware_never_configures_a_burst(self) -> None:
        source = (ROOT / "firmware/src/main.c").read_text(encoding="utf-8")

        self.assertIn("P2OUT |= BIT5", source)
        self.assertNotIn("TUSS", source)
        self.assertNotIn("BURST", source.upper())

    def test_environment_checks_report_versions_and_platform_prerequisites(self) -> None:
        windows_check = (ROOT / "scripts/check-env.ps1").read_text(encoding="utf-8")
        jetson_check = (ROOT / "scripts/check-env.sh").read_text(encoding="utf-8")

        self.assertIn("Version", windows_check)
        self.assertIn("Required", windows_check)
        self.assertIn(".tools", windows_check)
        self.assertIn("usb-cdc-device", windows_check)
        self.assertIn("docker compose version", jetson_check)
        self.assertIn("docker buildx version", jetson_check)
        self.assertIn("uv --version", jetson_check)

    def test_shell_scripts_are_lf_only_for_linux_execution(self) -> None:
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", attributes)

        files_with_crlf = [
            str(path.relative_to(ROOT))
            for path in (ROOT / "scripts").glob("*.sh")
            if b"\r\n" in path.read_bytes()
        ]
        self.assertEqual(files_with_crlf, [])

    def test_m1_c_vector_checker_is_part_of_jetson_test_entrypoint(self) -> None:
        jetson_test = (ROOT / "scripts/test-all.sh").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "tests/c/test_protocol_vectors.c").is_file())
        self.assertTrue((ROOT / "scripts/test-c-vectors.sh").is_file())
        self.assertIn("test-c-vectors.sh", jetson_test)

    def test_m5_core_container_uses_external_data_and_loopback_ports(self) -> None:
        compose = (ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "deploy/Dockerfile.core").read_text(encoding="utf-8")

        self.assertIn("tuss4470-acquisition-core:m5", compose)
        self.assertIn("127.0.0.1:8765:8765", compose)
        self.assertIn("127.0.0.1:8000:8000", compose)
        self.assertIn("USAC_CORE_DATA_DIR", compose)
        self.assertIn("--host-database-path", compose)
        self.assertIn(
            "${USAC_CORE_DATA_DIR:-D:/Desktop/TUSS4470_data/core}/acquisition.sqlite3",
            compose,
        )
        self.assertIn("/var/lib/usac/database", compose)
        self.assertIn("usac_runtime.m5_server", compose + dockerfile)
        self.assertNotIn("usac-core-m1:ready", compose + dockerfile)

    def test_jetson_compose_maps_device_and_separate_host_storage(self) -> None:
        compose = (ROOT / "deploy/compose.jetson.yaml").read_text(encoding="utf-8")

        self.assertIn("/var/lib/tuss4470/core", compose)
        self.assertIn("--host-database-path", compose)
        self.assertIn(
            "${USAC_CORE_DATA_DIR:-/var/lib/tuss4470/core}/acquisition.sqlite3",
            compose,
        )
        self.assertIn("/var/lib/tuss4470/bridge/spool", compose)
        self.assertIn("/var/lib/usac/database", compose)
        self.assertIn("/var/lib/usac/spool", compose)
        self.assertIn("/dev/tuss4470", compose)
        self.assertIn("--core-host\n      - core", compose)
        self.assertIn("--core-port\n      - \"8765\"", compose)

    def test_runtime_examples_use_the_approved_external_data_roots(self) -> None:
        windows = (ROOT / "config/windows.example.toml").read_text(encoding="utf-8")
        jetson = (ROOT / "config/jetson.example.toml").read_text(encoding="utf-8")

        self.assertIn("D:/Desktop/TUSS4470_data/core/acquisition.sqlite3", windows)
        self.assertIn("D:/Desktop/TUSS4470_data/bridge/spool", windows)
        self.assertIn("/var/lib/usac/database/acquisition.sqlite3", jetson)
        self.assertIn("/var/lib/usac/spool", jetson)
        self.assertNotIn("TUSS4470_software", windows + jetson)

    def test_protocol_hex_vectors_are_not_treated_as_firmware_outputs(self) -> None:
        ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("!protocol/vectors/*.hex", ignore_rules)


if __name__ == "__main__":
    unittest.main()
