from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _resolve_uv_executable(
    *,
    repository_root: Path | None = None,
    platform_name: str | None = None,
    path_lookup=None,
) -> Path:
    """Locate uv using the platform bootstrap's supported tool locations."""

    root = repository_root or ROOT
    active_platform = platform_name or os.name
    lookup = path_lookup or shutil.which
    bundled_windows_uv = root / ".tools/uv/uv.exe"
    if active_platform == "nt" and bundled_windows_uv.is_file():
        return bundled_windows_uv

    uv_on_path = lookup("uv")
    if uv_on_path:
        return Path(uv_on_path)

    bundled_linux_uv = root / ".tools/uv/uv"
    if active_platform != "nt" and bundled_linux_uv.is_file():
        return bundled_linux_uv

    raise AssertionError(
        "uv was not found; bootstrap the repository tool or install uv on PATH"
    )


class ProjectLayoutTests(unittest.TestCase):
    def test_uv_resolution_uses_repository_tool_on_linux_when_path_is_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository_root = Path(directory)
            bundled_uv = repository_root / ".tools/uv/uv"
            bundled_uv.parent.mkdir(parents=True)
            bundled_uv.write_bytes(b"test uv executable")

            resolved = _resolve_uv_executable(
                repository_root=repository_root,
                platform_name="posix",
                path_lookup=lambda executable: None,
            )

        self.assertEqual(resolved, bundled_uv)

    def test_uv_resolution_uses_path_on_linux(self) -> None:
        resolved = _resolve_uv_executable(
            platform_name="posix",
            path_lookup=lambda executable: "/usr/local/bin/uv"
            if executable == "uv"
            else None,
        )

        self.assertEqual(resolved, Path("/usr/local/bin/uv"))

    def test_active_firmware_has_no_milestone_component_identities(self) -> None:
        firmware_root = ROOT / "firmware"
        active_files = [
            path
            for directory in ("src", "include", "tests")
            for path in (firmware_root / directory).glob("*")
            if path.is_file()
        ]
        token = re.compile(r"(?i)(?<![a-z0-9])m[0-6](?![a-z0-9])")
        offenders = []
        for path in active_files:
            relative = path.relative_to(ROOT).as_posix()
            if token.search(relative) or token.search(path.read_text(encoding="utf-8")):
                offenders.append(relative)

        self.assertEqual(offenders, [])

        identifier_v1 = re.compile(
            r"\b(?:usac|g_usac|capture|configure|start|test)_[A-Za-z0-9_]*V1[A-Za-z0-9_]*\b"
        )
        version_named_identifiers = [
            path.relative_to(ROOT).as_posix()
            for path in active_files
            if identifier_v1.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(version_named_identifiers, [])

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

    def test_release_metadata_is_v1_0_0(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        local_package = next(
            package
            for package in lock["package"]
            if package["name"] == "tuss4470-acquisition"
        )

        self.assertEqual(metadata["project"]["version"], "1.0.0")
        self.assertEqual(local_package["version"], "1.0.0")
        self.assertEqual(local_package["source"], {"editable": "."})
        self.assertEqual(
            metadata["project"]["description"],
            "Cross-platform TUSS4470 ultrasonic acquisition and raw-data service",
        )

    def test_required_v1_files_exist(self) -> None:
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
            "requirements-container.lock.txt",
            "docs/deployment/windows.md",
            "docs/deployment/jetson.md",
            "firmware/src/main.c",
            "scripts/build-firmware.ps1",
            "scripts/flash-firmware.ps1",
            "scripts/test-firmware-safety.ps1",
            "scripts/test-firmware-acquisition-static.ps1",
            "scripts/test-firmware-loopback-safety.ps1",
            "scripts/test-firmware-timer-ownership.ps1",
            "scripts/test-firmware-app.ps1",
            "scripts/test-firmware-burst-plan.ps1",
            "scripts/test-firmware-capture-schedule.ps1",
            "scripts/verify-jetson-hil.py",
            "scripts/check-env.ps1",
            "scripts/check-env.sh",
            "scripts/bootstrap-dev.ps1",
            "scripts/bootstrap-dev.sh",
            "scripts/test-all.ps1",
            "scripts/test-all.sh",
            "docs/adr/0001-cross-platform-toolchain.md",
            "docs/adr/0003-msp430-clock-and-tuss4470-spi.md",
            "docs/adr/0006-adc-dma-timer-trigger.md",
            "docs/release/v1.0.0-acceptance.md",
            "docs/release/v1.0.0-known-limitations.md",
            "docs/archive/pre-v1/README.md",
        ]

        missing = [path for path in required if not (ROOT / path).is_file()]
        self.assertEqual(missing, [])

    def test_completed_milestone_documents_are_archived(self) -> None:
        retired_active_paths = [
            "docs/verification/M6/summary.md",
            "docs/m3-capture-transport-design.md",
            "docs/m3-host-capture-diagnostics-design.md",
            "docs/adr/0003-m2-clock-and-spi-bringup.md",
            "docs/adr/0006-m3-adc-timer-trigger.md",
            "docs/adr/0007-m3-adc-dma-software-trigger-diagnostic.md",
        ]

        self.assertEqual(
            [path for path in retired_active_paths if (ROOT / path).exists()],
            [],
        )

    def test_retired_firmware_wrappers_are_absent(self) -> None:
        retired = [
            "firmware/Makefile",
            "scripts/build-firmware-m2.ps1",
            "scripts/build-firmware-m3.ps1",
            "scripts/build-firmware-m3-adc-dma-diagnostic.ps1",
            "scripts/build-firmware-m3-small-ram-diagnostic.ps1",
            "scripts/build-firmware-m3-startup-diagnostic.ps1",
            "scripts/build-firmware-m5.ps1",
            "scripts/flash-firmware-m2.ps1",
            "scripts/flash-firmware-m3.ps1",
            "scripts/flash-firmware-m3-adc-dma-diagnostic.ps1",
            "scripts/flash-firmware-m3-small-ram-diagnostic.ps1",
            "scripts/flash-firmware-m3-startup-diagnostic.ps1",
            "scripts/flash-firmware-m5.ps1",
            "scripts/test-m2-safety.ps1",
            "scripts/test-m3-acquisition-static.ps1",
            "scripts/test-m3-adc-dma-diagnostic-static.ps1",
            "scripts/test-m3-loopback-safety.ps1",
            "scripts/test-m5-timer-ownership.ps1",
            "scripts/test-firmware-m5-app.ps1",
            "scripts/test-firmware-m5-burst-plan.ps1",
            "scripts/test-firmware-m5-schedule.ps1",
            "scripts/verify-m6-jetson-hil.py",
        ]

        present = [path for path in retired if (ROOT / path).exists()]
        self.assertEqual(present, [])

    def test_release_firmware_builder_has_one_production_target(self) -> None:
        builder = (ROOT / "scripts/build-firmware.ps1").read_text(encoding="utf-8")

        self.assertIn("firmware\\build\\release", builder)
        self.assertIn("$imageName = 'tuss4470-acquisition-fw-0.2.0.2'", builder)
        self.assertIn('"$imageName.elf"', builder)
        self.assertIn("-DUSAC_ENABLE_LOOPBACK", builder)
        self.assertIn("-DUSAC_ENABLE_ACQUISITION", builder)
        self.assertNotIn("param(", builder)
        self.assertNotIn("Diagnostic", builder)

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
        self.assertIn("COPY requirements-container.lock.txt ./", dockerfile)
        self.assertIn("pip install --no-cache-dir --require-hashes", dockerfile)
        self.assertNotIn("pip install --no-cache-dir .", dockerfile)
        self.assertIn("PYTHONPATH=/opt/usac/packages/usac_protocol/src", dockerfile)
        self.assertIn("packages/usac_protocol/src", dockerfile)
        self.assertIn("usac_runtime.core_server", dockerfile)
        self.assertIn('org.opencontainers.image.version="$VERSION"', dockerfile)
        self.assertIn('org.opencontainers.image.revision="$VCS_REF"', dockerfile)
        self.assertIn(".venv", dockerignore)
        self.assertIn(".tools", dockerignore)

    def test_container_lock_is_exact_export_of_uv_lock(self) -> None:
        uv = _resolve_uv_executable()
        expected = ROOT / "requirements-container.lock.txt"
        self.assertTrue(expected.is_file())

        with tempfile.TemporaryDirectory() as directory:
            regenerated = Path(directory) / "requirements.txt"
            environment = os.environ.copy()
            environment["UV_CACHE_DIR"] = str(ROOT / ".tools/uv-cache")
            environment["UV_PYTHON_INSTALL_DIR"] = str(ROOT / ".tools/uv-python")
            subprocess.run(
                [
                    str(uv),
                    "export",
                    "--frozen",
                    "--no-dev",
                    "--no-emit-project",
                    "--no-header",
                    "--format",
                    "requirements.txt",
                    "--output-file",
                    str(regenerated),
                ],
                cwd=ROOT,
                check=True,
                env=environment,
            )
            self.assertEqual(regenerated.read_bytes(), expected.read_bytes())

    def test_host_automation_matches_the_platform_split(self) -> None:
        windows_test = (ROOT / "scripts/test-all.ps1").read_text(encoding="utf-8")
        jetson_test = (ROOT / "scripts/test-all.sh").read_text(encoding="utf-8")

        self.assertIn(".venv", windows_test)
        self.assertIn("build-firmware.ps1", windows_test)
        self.assertNotIn("docker ", windows_test.lower())
        self.assertIn(".venv", jetson_test)
        self.assertIn("linux/arm64", jetson_test)
        self.assertIn("linux/amd64", jetson_test)
        self.assertIn("candidate_sha", jetson_test)
        self.assertIn("candidate12", jetson_test)
        self.assertIn("1.0.0-rc-${candidate12}-arm64", jetson_test)
        self.assertIn("1.0.0-rc-${candidate12}-amd64.tar", jetson_test)
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

    def test_windows_test_entrypoint_includes_v1_firmware_gate(self) -> None:
        windows_test = (ROOT / "scripts/test-all.ps1").read_text(encoding="utf-8")

        required_steps = [
            "build-firmware.ps1",
            "test-firmware-unit.ps1",
            "test-ti-usb-stack-build.ps1",
            "test-firmware-safety.ps1",
            "test-firmware-loopback-safety.ps1",
            "test-firmware-acquisition-static.ps1",
            "test-firmware-timer-ownership.ps1",
            "test-firmware-burst-plan.ps1",
            "test-firmware-capture-schedule.ps1",
            "test-firmware-app.ps1",
        ]
        for step in required_steps:
            self.assertIn(step, windows_test)

        self.assertEqual(windows_test.count("build-firmware.ps1"), 1)

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

    def test_c_vector_checker_is_part_of_jetson_test_entrypoint(self) -> None:
        jetson_test = (ROOT / "scripts/test-all.sh").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "tests/c/test_protocol_vectors.c").is_file())
        self.assertTrue((ROOT / "scripts/test-c-vectors.sh").is_file())
        self.assertIn("test-c-vectors.sh", jetson_test)

    def test_v1_core_container_uses_external_data_and_loopback_ports(self) -> None:
        compose = (ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "deploy/Dockerfile.core").read_text(encoding="utf-8")

        self.assertIn("${USAC_CORE_IMAGE:-tuss4470-acquisition-core:1.0.0}", compose)
        self.assertIn("127.0.0.1:8765:8765", compose)
        self.assertIn("127.0.0.1:8000:8000", compose)
        self.assertIn("USAC_CORE_DATA_DIR", compose)
        self.assertIn("--host-database-path", compose)
        self.assertIn(
            "${USAC_CORE_DATA_DIR:-D:/Desktop/TUSS4470_data/core}/acquisition.sqlite3",
            compose,
        )
        self.assertIn("/var/lib/usac/database", compose)
        self.assertIn("usac_runtime.core_server", compose + dockerfile)
        self.assertIn("--backend\n      - bridge", compose)
        self.assertNotRegex(compose + dockerfile, r"usac_runtime\.m[0-6]")

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
        self.assertIn("${USAC_CORE_IMAGE:-tuss4470-acquisition-core:1.0.0}", compose)
        self.assertIn('entrypoint: ["python", "-m", "usac_runtime.bridge_cli"]', compose)
        self.assertNotIn("      - serve\n", compose)
        self.assertIn("--backend\n      - bridge", compose)

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
