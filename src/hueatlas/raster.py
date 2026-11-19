# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn a layout plus swatch looks into pixel arrays.

Pure numpy, no bpy. Arrays are uint8 with shape (height, width, 4) and row 0
at the bottom, the same order as bpy.types.Image.pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .layout import GRADIENT, Layout

SRGB = "SRGB"
OKLAB = "OKLAB"

BACKGROUND_ALBEDO = (128, 128, 128, 255)
BACKGROUND_ORM = (255, 128, 0, 255)
BACKGROUND_EMISSION = (0, 0, 0, 255)


@dataclass
class Look:
    """Everything that decides how one swatch is painted."""

    kind: str = "FLAT"
    color: tuple = (0.8, 0.8, 0.8)
    stops: list = field(default_factory=list)  # [(position, (r, g, b))], sRGB 0..1
    roughness: float = 0.5
    metallic: float = 0.0
    emission: tuple = (0.0, 0.0, 0.0)
    emission_strength: float = 0.0

    def emits(self) -> bool:
        return self.emission_strength > 0.0 and max(self.emission) > 0.0


# -- colour helpers ------------------------------------------------------------


def to_u8(values) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    return np.clip(np.round(arr * 255.0), 0, 255).astype(np.uint8)


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_M2_INV = np.linalg.inv(_M2)
_M1_INV = np.linalg.inv(_M1)


def linear_to_oklab(rgb):
    lms = np.asarray(rgb, dtype=np.float64) @ _M1.T
    return np.cbrt(lms) @ _M2.T


def oklab_to_linear(lab):
    lms = np.asarray(lab, dtype=np.float64) @ _M2_INV.T
    return (lms**3) @ _M1_INV.T


def gradient_colors(stops, t, space: str = SRGB) -> np.ndarray:
    """Sample a multi-stop gradient. Returns sRGB floats with shape (n, 3)."""
    t = np.asarray(t, dtype=np.float64)
    ordered = sorted(stops, key=lambda s: s[0])
    if not ordered:
        return np.full((t.size, 3), 0.5)
    pos = np.array([s[0] for s in ordered], dtype=np.float64)
    cols = np.array([s[1] for s in ordered], dtype=np.float64).reshape(-1, 3)
    if len(ordered) == 1:
        return np.repeat(cols, t.size, axis=0)
    if space == OKLAB:
        cols = linear_to_oklab(srgb_to_linear(cols))
    out = np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], axis=1)
    if space == OKLAB:
        out = linear_to_srgb(oklab_to_linear(out))
    return np.clip(out, 0.0, 1.0)


def parse_hex(text: str) -> tuple:
    s = text.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"Not a hex colour: {text!r}")
    return tuple(int(s[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def to_hex(rgb) -> str:
    r, g, b = (int(v) for v in to_u8(rgb[:3]))
    return f"#{r:02X}{g:02X}{b:02X}"


# -- painting -------------------------------------------------------------------


def blank(width: int, height: int, rgba) -> np.ndarray:
    arr = np.empty((height, width, 4), dtype=np.uint8)
    arr[:] = rgba
    return arr


def _box_slices(box):
    return slice(int(box.y0), int(box.y1)), slice(int(box.x0), int(box.x1))


def _gradient_row(layout: Layout, uid: int, look: Look, space: str) -> np.ndarray:
    box = layout.boxes[uid]
    inner = layout.inners[uid]
    xs = np.arange(int(box.x0), int(box.x1), dtype=np.float64) + 0.5
    span = max(inner.w, 1e-9)
    t = np.clip((xs - inner.x0) / span, 0.0, 1.0)
    return gradient_colors(look.stops, t, space)


def paint_albedo(target: np.ndarray, layout: Layout, looks: dict, space: str = SRGB) -> np.ndarray:
    for uid, box in layout.boxes.items():
        look = looks[uid]
        ys, xs = _box_slices(box)
        if layout.kinds[uid] == GRADIENT and look.stops:
            row = to_u8(_gradient_row(layout, uid, look, space))
            rgba = np.concatenate([row, np.full((row.shape[0], 1), 255, np.uint8)], axis=1)
            target[ys, xs] = rgba[None, :, :]
        else:
            target[ys, xs, :3] = to_u8(look.color[:3])
            target[ys, xs, 3] = 255
    return target


def paint_orm(target: np.ndarray, layout: Layout, looks: dict) -> np.ndarray:
    """R = ambient occlusion (always 1), G = roughness, B = metallic."""
    for uid, box in layout.boxes.items():
        look = looks[uid]
        ys, xs = _box_slices(box)
        target[ys, xs] = (255, to_u8(look.roughness), to_u8(look.metallic), 255)
    return target


def max_emission_strength(looks: dict) -> float:
    strengths = [look.emission_strength for look in looks.values() if look.emits()]
    return max(strengths) if strengths else 0.0


def paint_emission(target: np.ndarray, layout: Layout, looks: dict, top: float | None = None) -> np.ndarray:
    """sRGB emission colour, scaled so the brightest swatch uses the full range.

    One material carries one emission strength, so per-swatch strengths are
    folded into the image relative to `top` (by default the strongest swatch).
    Very weak swatches next to a very strong one lose precision in 8 bits.
    """
    if top is None:
        top = max_emission_strength(looks)
    for uid, box in layout.boxes.items():
        look = looks[uid]
        ys, xs = _box_slices(box)
        if top > 0.0 and look.emits():
            lin = srgb_to_linear(look.emission[:3]) * (look.emission_strength / top)
            target[ys, xs, :3] = to_u8(linear_to_srgb(lin))
        else:
            target[ys, xs, :3] = 0
        target[ys, xs, 3] = 255
    return target


def paint_metallic_smoothness(target: np.ndarray, layout: Layout, looks: dict) -> np.ndarray:
    """Unity URP/HDRP style: R = metallic, G = occlusion (1), B = 0, A = smoothness."""
    for uid, box in layout.boxes.items():
        look = looks[uid]
        ys, xs = _box_slices(box)
        target[ys, xs] = (to_u8(look.metallic), 255, 0, to_u8(1.0 - look.roughness))
    return target


def render(layout: Layout, looks: dict, channel: str, space: str = SRGB, base=None,
           emission_top: float | None = None) -> np.ndarray:
    """Render one channel image. `base` is reused outside the grid (region mode)."""
    if base is not None:
        target = np.array(base, dtype=np.uint8, copy=True)
    else:
        background = {
            "albedo": BACKGROUND_ALBEDO,
            "orm": BACKGROUND_ORM,
            "emission": BACKGROUND_EMISSION,
            "metal_smooth": (0, 255, 0, 128),
        }[channel]
        target = blank(layout.width, layout.height, background)
    if channel == "albedo":
        return paint_albedo(target, layout, looks, space)
    if channel == "orm":
        return paint_orm(target, layout, looks)
    if channel == "emission":
        return paint_emission(target, layout, looks, emission_top)
    if channel == "metal_smooth":
        return paint_metallic_smoothness(target, layout, looks)
    raise ValueError(channel)


def box_mip(arr: np.ndarray, levels: int) -> np.ndarray:
    """Box-filter an image down `levels` times (2x2 average per level)."""
    out = arr.astype(np.float64)
    for _ in range(levels):
        h, w = out.shape[0] // 2, out.shape[1] // 2
        out = out[: h * 2, : w * 2].reshape(h, 2, w, 2, -1).mean(axis=(1, 3))
    return out
