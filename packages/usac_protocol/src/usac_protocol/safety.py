"""Project safety policy layered on top of data-sheet-valid configuration.

A value can be representable yet unsafe for the currently assembled BOOSTXL
direct-drive hardware; this module enforces that narrower application boundary.
"""

from __future__ import annotations

from .config_v2 import AcquisitionConfigV2


BOOSTXL_DIRECT_WRITE_MASKS = {
    0x10: 0xFF,
    0x11: 0x3F,
    0x12: 0xFF,
    0x13: 0xC7,
    0x14: 0x1F,
    0x16: 0x7F,
    0x17: 0x1F,
    0x18: 0xFF,
    0x1A: 0xFF,
    0x1B: 0xC3,
}


def validate_boostxl_direct_applied_config(config: AcquisitionConfigV2) -> None:
    """Validate the currently approved 7 V VPWR / internal 5 V VDRV topology."""

    registers = dict(config.register_pairs)
    if set(registers) != set(BOOSTXL_DIRECT_WRITE_MASKS):
        raise ValueError("APPLIED config must contain the complete 10-register image")
    for address, write_mask in BOOSTXL_DIRECT_WRITE_MASKS.items():
        if registers[address] & ~write_mask:
            raise ValueError(f"register 0x{address:02X} sets a reserved bit")
    if config.sample_count != 2048:
        raise ValueError("APPLIED config must capture exactly 2048 real samples")
    # The four GUI presets are conveniences, not the device limit. M5 permits
    # every integer divider in this range so the stored samples always remain
    # real ADC points while requested rates are represented by actual ticks.
    if not 120 <= config.sample_interval_ticks <= 960:
        raise ValueError("sample_interval_ticks is outside the approved range")

    burst = registers[0x1A]
    if burst & 0x3F == 0:
        raise ValueError("continuous Burst cannot become APPLIED")
    if burst & 0x40:
        raise ValueError("pre-driver mode requires another hardware profile")

    if registers[0x13] & 0x04:
        raise ValueError("5 V VOUT exceeds the approved 3.3 V ADC path")

    vdrv = registers[0x16]
    if vdrv & 0x10:
        raise ValueError("20 mA VDRV is outside the approved hardware profile")
    if vdrv & 0x0F:
        raise ValueError("VDRV above 5 V is outside the approved hardware profile")
    if vdrv & 0x20:
        raise ValueError("external or Hi-Z VDRV requires another hardware profile")

    tof = registers[0x1B]
    if tof & (0x01 | 0x40 | 0x80):
        raise ValueError("trigger, standby, or sleep bit cannot enter stable APPLIED config")
