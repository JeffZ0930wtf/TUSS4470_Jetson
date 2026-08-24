"""Binary protocol primitives shared by bridge, core, simulator, and tests."""

from .frame import Flags, Frame, MessageType, decode_frame, encode_frame

__all__ = ["Flags", "Frame", "MessageType", "decode_frame", "encode_frame"]
