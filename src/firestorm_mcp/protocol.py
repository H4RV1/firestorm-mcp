"""LEAP byte-counted LLSD: accept binary/notation, send compatible notation."""
from __future__ import annotations

import base64
import datetime
import re
import uuid
from typing import BinaryIO

import llsd

MAX_FRAME = 128 * 1024 * 1024
MAX_DECODE_FRAME = 16 * 1024 * 1024


class FrameDecodeError(ValueError):
    """An entire framed message was consumed; the next frame remains readable."""
    def __init__(self, message, body):
        super().__init__(message)
        self.body = body


def duplicate_block_offset(body: bytes, error: Exception):
    """Locate the exact adjacent 4 KiB duplicate from Firestorm's APR pipe bug.

    The viewer documents EAGAIN reporting zero written after writing a chunk.
    Search near the parser failure first; never repair approximate matches.
    """
    match = re.search(r"at byte (\d+)", str(error))
    point = int(match[1]) if match else len(body)
    ranges = [(max(4096, point - 8192), min(len(body) - 4096 + 1, point + 4096))]
    if len(body) <= 2 * 1024 * 1024:
        ranges.append((4096, len(body) - 4096 + 1))
    for start, end in ranges:
        for offset in range(start, end):
            if body[offset:offset + 32] == body[offset - 4096:offset - 4064]:
                if body[offset:offset + 4096] == body[offset - 4096:offset]:
                    return offset
    return None


def read_exact(stream: BinaryIO, size: int) -> bytes:
    parts = []
    while size:
        chunk = stream.read(size)
        if not chunk:
            raise EOFError("Viewer closed the LEAP stream")
        parts.append(chunk)
        size -= len(chunk)
    return b"".join(parts)


def read_frame(stream: BinaryIO) -> dict:
    prefix = bytearray()
    while True:
        char = read_exact(stream, 1)
        if char == b":":
            break
        if not char.isdigit() or len(prefix) >= 9:
            raise ValueError("Invalid LEAP frame length")
        prefix += char
    if not prefix or not 0 < int(prefix) <= MAX_FRAME:
        raise ValueError(f"LEAP frame length outside bounds: {prefix.decode('ascii')}")
    size = int(prefix)
    if size > MAX_DECODE_FRAME:
        # Only a valid length prefix is recoverable. Never scan arbitrary payload
        # bytes for a guessed boundary, which could correlate a reply incorrectly.
        remaining = size
        while remaining:
            count = min(remaining, 65536)
            read_exact(stream, count)
            remaining -= count
        raise FrameDecodeError("Oversized viewer reply consumed without decoding; result is unknown", b"")
    body = read_exact(stream, size)
    repaired = 0
    while True:
        try:
            result = llsd.parse(body)
            break
        except llsd.LLSDParseError as exc:
            offset = duplicate_block_offset(body, exc) if repaired < 8 else None
            if offset is None:
                raise FrameDecodeError(str(exc), body) from exc
            # The duplicate displaced the last 4096 bytes outside the announced
            # frame length. Drop ONLY the exact duplicate, then read that tail.
            body = body[:offset] + body[offset + 4096:] + read_exact(stream, 4096)
            repaired += 1
    if not isinstance(result, dict) or "pump" not in result or "data" not in result:
        raise FrameDecodeError("Expected a LEAP pump/data envelope", body)
    if repaired:
        result["_leap_repaired_duplicate_blocks"] = repaired
    return result


def encode_frame(pump: str, data: dict) -> bytes:
    body = llsd.format_notation({"pump": pump, "data": data})
    if len(body) > MAX_FRAME:
        raise ValueError("LEAP frame too large")
    return str(len(body)).encode("ascii") + b":" + body


def json_default(value):
    if isinstance(value, (uuid.UUID, datetime.datetime, datetime.date)):
        return str(value)
    if isinstance(value, bytes):
        return {"$binary_base64": base64.b64encode(value).decode("ascii")}
    raise TypeError(f"Cannot encode {type(value).__name__}")


def decode_typed(value):
    """Opt-in LLSD typed values for the generic API, recursively."""
    if isinstance(value, dict):
        if set(value) == {"$uuid"}:
            return uuid.UUID(value["$uuid"])
        if set(value) == {"$binary_base64"}:
            return llsd.binary(base64.b64decode(value["$binary_base64"], validate=True))
        if set(value) == {"$uri"}:
            return llsd.uri(value["$uri"])
        return {key: decode_typed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_typed(item) for item in value]
    return value
