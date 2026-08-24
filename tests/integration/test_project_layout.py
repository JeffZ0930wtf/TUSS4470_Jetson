from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProjectLayoutTests(unittest.TestCase):
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
        self.assertIn(".venv", windows_bootstrap)
        self.assertIn(".venv", linux_bootstrap)
        self.assertIn(".tools", windows_bootstrap)
        self.assertIn(".tools", linux_bootstrap)

    def test_container_base_is_digest_pinned_and_registry_is_reachable(self) -> None:
        dockerfile = (ROOT / "deploy/Dockerfile.core").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn("public.ecr.aws/docker/library/python:3.12-slim@sha256:", dockerfile)
        self.assertNotIn("RUN python -m pip install", dockerfile)
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
        self.assertNotIn("make -C firmware", jetson_test)

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


if __name__ == "__main__":
    unittest.main()
