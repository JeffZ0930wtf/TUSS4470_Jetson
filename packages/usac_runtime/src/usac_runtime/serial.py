"""Structural serial boundaries for LaunchPad USB CDC access.

pyserial is kept behind these protocols so Windows COM names and Jetson
/dev/ttyACM paths do not leak into protocol or application logic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import SerialConfig


@runtime_checkable
class SerialConnection(Protocol):
    """Minimal open byte-stream connection owned and closed by its caller."""
    def read(self, size: int) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


@runtime_checkable
class SerialTransport(Protocol):
    """Factory boundary that applies platform-specific serial settings."""
    def open(self, settings: SerialConfig) -> SerialConnection: ...
