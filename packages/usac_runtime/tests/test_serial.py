from __future__ import annotations

import unittest

from usac_runtime.config import SerialConfig
from usac_runtime.serial import SerialConnection, SerialTransport


class FakeConnection:
    def read(self, size: int) -> bytes:
        return b""[:size]

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        return None


class FakeTransport:
    def open(self, settings: SerialConfig) -> SerialConnection:
        del settings
        return FakeConnection()


class SerialInterfaceTests(unittest.TestCase):
    def test_transport_contract_accepts_platform_adapters(self) -> None:
        transport = FakeTransport()

        self.assertIsInstance(transport, SerialTransport)
        self.assertIsInstance(
            transport.open(SerialConfig(port="COM7")),
            SerialConnection,
        )


if __name__ == "__main__":
    unittest.main()
