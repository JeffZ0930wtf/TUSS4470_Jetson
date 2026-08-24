from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from usac_runtime.config import ConfigurationError, load_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def write_config(self, root: Path, port: str = "COM7") -> Path:
        path = root / "runtime.toml"
        path.write_text(
            "\n".join(
                [
                    "[serial]",
                    f'port = "{port}"',
                    "baudrate = 115200",
                    "timeout_ms = 2000",
                    "",
                    "[storage]",
                    'data_dir = "var/data"',
                    'spool_dir = "var/spool"',
                    'sqlite_path = "var/core/captures.sqlite3"',
                ]
            ),
            encoding="utf-8",
        )
        return path

    def test_loads_relative_paths_from_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = load_runtime_config(self.write_config(root), environ={})

            self.assertEqual(config.serial.port, "COM7")
            self.assertEqual(config.serial.baudrate, 115200)
            self.assertEqual(config.serial.timeout_ms, 2000)
            self.assertEqual(config.storage.data_dir, (root / "var/data").resolve())
            self.assertEqual(config.storage.spool_dir, (root / "var/spool").resolve())
            self.assertEqual(
                config.storage.sqlite_path,
                (root / "var/core/captures.sqlite3").resolve(),
            )

    def test_environment_overrides_are_platform_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(root)

            windows = load_runtime_config(
                config_path,
                environ={"USAC_SERIAL_PORT": "COM19"},
            )
            linux = load_runtime_config(
                config_path,
                environ={"USAC_SERIAL_PORT": "/dev/ttyACM3"},
            )

            self.assertEqual(windows.serial.port, "COM19")
            self.assertEqual(linux.serial.port, "/dev/ttyACM3")

    def test_storage_environment_overrides_resolve_from_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(root)
            override = root / "external-data"

            config = load_runtime_config(
                config_path,
                environ={"USAC_DATA_DIR": str(override)},
            )

            self.assertEqual(config.storage.data_dir, override.resolve())

    def test_rejects_blank_serial_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            with self.assertRaisesRegex(ConfigurationError, "serial.port"):
                load_runtime_config(self.write_config(root, port="   "), environ={})


if __name__ == "__main__":
    unittest.main()
