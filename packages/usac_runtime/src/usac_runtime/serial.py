from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import SerialConfig


@runtime_checkable
class SerialConnection(Protocol):
    def read(self, size: int) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


@runtime_checkable
class SerialTransport(Protocol):
    def open(self, settings: SerialConfig) -> SerialConnection: ...
