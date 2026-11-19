# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal, deterministic RGBA8 PNG writer and reader (no bpy).

Writing the files ourselves keeps the bytes exact and identical between
Blender versions, which the golden-file tests rely on.
"""

from __future__ import annotations

import os
import struct
import zlib

import numpy as np

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def encode(rgba_bottom_up: np.ndarray) -> bytes:
    arr = np.ascontiguousarray(rgba_bottom_up, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError("Expected an (height, width, 4) uint8 array")
    height, width = arr.shape[:2]
    top_down = arr[::-1]
    raw = np.empty((height, 1 + width * 4), dtype=np.uint8)
    raw[:, 0] = 0  # filter type: none
    raw[:, 1:] = top_down.reshape(height, width * 4)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        _SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw.tobytes(), 9))
        + _chunk(b"IEND", b"")
    )


def write(path: str, rgba_bottom_up: np.ndarray) -> str:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    data = encode(rgba_bottom_up)
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def read(path: str) -> np.ndarray:
    """Read an 8-bit RGBA or RGB PNG (any filter). Returns bottom-up RGBA."""
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(_SIGNATURE):
        raise ValueError(f"{path} is not a PNG")
    pos = len(_SIGNATURE)
    idat = b""
    width = height = color_type = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or color_type not in (2, 6) or interlace:
                raise ValueError("Only 8-bit, non-interlaced RGB/RGBA PNGs are supported")
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(height, stride + 1)
    out = np.zeros((height, stride), dtype=np.int32)
    for y in range(height):
        ftype = raw[y, 0]
        line = raw[y, 1:].astype(np.int32)
        prev = out[y - 1] if y else np.zeros(stride, np.int32)
        if ftype == 0:
            cur = line
        elif ftype == 1:
            cur = line.copy()
            for x in range(channels, stride):
                cur[x] = (cur[x] + cur[x - channels]) & 0xFF
        elif ftype == 2:
            cur = (line + prev) & 0xFF
        elif ftype == 3:
            cur = line.copy()
            for x in range(stride):
                left = cur[x - channels] if x >= channels else 0
                cur[x] = (cur[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            cur = line.copy()
            for x in range(stride):
                a = cur[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (cur[x] + pred) & 0xFF
        else:
            raise ValueError(f"Unknown PNG filter {ftype}")
        out[y] = cur
    img = out.astype(np.uint8).reshape(height, width, channels)
    if channels == 3:
        img = np.concatenate([img, np.full((height, width, 1), 255, np.uint8)], axis=2)
    return img[::-1].copy()
