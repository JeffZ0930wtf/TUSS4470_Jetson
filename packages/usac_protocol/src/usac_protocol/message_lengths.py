"""Direction and exact payload-length policy for every USAC message type.

Keeping these checks separate lets host and streaming parsers reject impossible
frames before allocating or waiting for an attacker-controlled length.
"""

from __future__ import annotations

from .frame import Flags, MessageType


def _even_range(length: int, minimum: int, maximum: int) -> bool:
    return minimum <= length <= maximum and (length - minimum) % 2 == 0


def flags_are_valid_for_message(message_type: MessageType, flags: int) -> bool:
    response_flags = (int(Flags.RESPONSE), int(Flags.RESPONSE | Flags.WARNING))
    async_flags = (int(Flags.ASYNC), int(Flags.ASYNC | Flags.WARNING))
    if message_type in (MessageType.ACK, MessageType.ERROR, MessageType.REQUEST_ATTACHED):
        return flags in response_flags
    if message_type in (
        MessageType.BRIDGE_DIAGNOSTIC,
        MessageType.BRIDGE_CAPTURE_DELIVERY,
        MessageType.BRIDGE_SPOOL_STATUS,
    ):
        return flags in async_flags
    if message_type is MessageType.CAPTURE_DATA:
        return flags in response_flags + async_flags
    if message_type in (
        MessageType.SET_CONFIG,
        MessageType.CAPTURE_ONCE,
        MessageType.START_PERIODIC,
        MessageType.STOP,
        MessageType.WRITE_REGISTER,
        MessageType.RESET_DEVICE,
        MessageType.CORE_CHALLENGE,
    ):
        return flags == 0
    return flags == 0 or flags in response_flags


def payload_length_is_valid(message_type: MessageType, flags: int, length: int) -> bool:
    response = bool(flags & Flags.RESPONSE)
    if message_type is MessageType.HELLO:
        return length == (64 if response else 20)
    if message_type is MessageType.GET_CAPABILITIES:
        return length == (24 if response else 0)
    if message_type is MessageType.GET_CONFIG:
        return _even_range(length, 52, 72) if response else length == 0
    if message_type is MessageType.SET_CONFIG:
        return not response and _even_range(length, 100, 120)
    if message_type is MessageType.CAPTURE_ONCE:
        return not response and length == 60
    if message_type is MessageType.START_PERIODIC:
        return not response and length == 80
    if message_type is MessageType.STOP:
        return not response and length == 32
    if message_type is MessageType.GET_STATUS:
        return length == (100 if response else 0)
    if message_type is MessageType.READ_REGISTER:
        return length == 4
    if message_type is MessageType.WRITE_REGISTER:
        return not response and length == 20
    if message_type is MessageType.RESET_DEVICE:
        return not response and length == 20
    if message_type is MessageType.RENEW_PERIODIC_LEASE:
        return length == 40
    if message_type is MessageType.CAPTURE_DATA:
        return 188 <= length <= 4576
    if message_type is MessageType.BRIDGE_HELLO:
        return length == (16 if response else 112)
    if message_type is MessageType.BRIDGE_HEARTBEAT:
        return length == 24
    if message_type is MessageType.CORE_CHALLENGE:
        return not response and length == 44
    if message_type is MessageType.BRIDGE_DIAGNOSTIC:
        return 64 <= length <= 128
    if message_type is MessageType.BRIDGE_CAPTURE_DELIVERY:
        return 264 <= length <= 4708
    if message_type is MessageType.CAPTURE_COMMITTED:
        return length == (24 if response else 68)
    if message_type is MessageType.BRIDGE_SPOOL_STATUS:
        return length == 64
    if message_type is MessageType.REQUEST_ATTACHED:
        return length == 26
    if message_type is MessageType.ACK:
        return length == 24
    if message_type is MessageType.ERROR:
        return 29 <= length <= 92
    return False
