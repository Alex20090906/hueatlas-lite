# SPDX-License-Identifier: GPL-3.0-or-later
"""Atlas layout math.

Pure Python with no bpy import, so it can be unit tested anywhere.

Pixel coordinates follow Blender's image convention: x grows to the right,
y grows upward, and (0, 0) is the bottom-left corner of the image. The swatch
grid fills row by row from the top-left corner of its area, which is how
people read a palette image.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FLAT = "FLAT"
GRADIENT = "GRADIENT"
FIXED = "FIXED"
MIPSAFE = "MIPSAFE"

MAX_MIP_LEVEL = 6


class LayoutError(ValueError):
    """The requested layout cannot be built."""


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) * 0.5

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) * 0.5

    def scaled(self, sx: float, sy: float) -> "Rect":
        return Rect(self.x0 * sx, self.y0 * sy, self.x1 * sx, self.y1 * sy)

    def as_list(self) -> list:
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass(frozen=True)
class Slot:
    """One swatch as the layout sees it."""

    uid: int
    kind: str = FLAT
    span: int = 1


@dataclass(frozen=True)
class Params:
    cell_px: int = 16
    columns: int = 8
    padding_mode: str = FIXED
    padding_px: int = 2
    mip_level: int = 2
    region: tuple | None = None
    image_size: tuple | None = None

    def as_dict(self) -> dict:
        return {
            "cell_px": int(self.cell_px),
            "columns": int(self.columns),
            "padding_mode": self.padding_mode,
            "padding_px": int(self.padding_px),
            "mip_level": int(self.mip_level),
            "region": list(self.region) if self.region is not None else None,
            "image_size": list(self.image_size) if self.image_size is not None else None,
        }


def next_pow2(n: int) -> int:
    n = max(1, int(n))
    return 1 << (n - 1).bit_length()


def is_pow2(n: int) -> bool:
    n = int(n)
    return n > 0 and (n & (n - 1)) == 0


def round_up(n: int, m: int) -> int:
    return ((int(n) + m - 1) // m) * m


def pow2_valuation(n: int) -> int:
    """Largest k with 2**k dividing n. Zero is divisible by everything."""
    n = abs(int(n))
    if n == 0:
        return 64
    k = 0
    while n % 2 == 0:
        n //= 2
        k += 1
    return k


@dataclass
class Layout:
    params: Params
    width: int
    height: int
    pitch: int
    gutter: int
    columns: int
    rows: int
    area: Rect
    origin: tuple  # (x of the left edge, y of the top edge) of the grid
    boxes: dict = field(default_factory=dict)
    inners: dict = field(default_factory=dict)
    kinds: dict = field(default_factory=dict)
    cells: dict = field(default_factory=dict)  # (row, col) -> uid

    # -- UV helpers -------------------------------------------------------

    def to_uv(self, rect: Rect) -> Rect:
        return rect.scaled(1.0 / self.width, 1.0 / self.height)

    def uv_box(self, uid: int) -> Rect:
        return self.to_uv(self.boxes[uid])

    def uv_inner(self, uid: int) -> Rect:
        return self.to_uv(self.inners[uid])

    def uv_center(self, uid: int) -> tuple:
        r = self.inners[uid]
        return (r.cx / self.width, r.cy / self.height)

    # -- geometry ---------------------------------------------------------

    def grid_rect(self) -> Rect:
        gx, gy_top = self.origin
        return Rect(gx, gy_top - self.rows * self.pitch, gx + self.columns * self.pitch, gy_top)

    def capacity(self) -> int:
        return self.rows * self.columns

    def cell_index(self, px: float, py: float) -> tuple:
        gx, gy_top = self.origin
        col = int((px - gx) // self.pitch)
        row = int((gy_top - py) // self.pitch)
        return row, col

    def uid_at(self, px: float, py: float):
        return self.cells.get(self.cell_index(px, py))

    def clean_mip_level(self) -> int:
        """Highest mip level at which every swatch still samples clean.

        A swatch is clean at level k when its box is aligned to the 2**k
        texel grid and is at least one level-k texel wide. Gradients also
        need gutters of at least 2**k pixels so the end colours do not pick
        up the neighbour.
        """
        gx, gy_top = self.origin
        k = min(
            pow2_valuation(gx),
            pow2_valuation(gy_top),
            pow2_valuation(self.pitch),
            self.pitch.bit_length() - 1,
            pow2_valuation(self.width),
            pow2_valuation(self.height),
        )
        if any(kind == GRADIENT for kind in self.kinds.values()):
            k = min(k, (self.gutter.bit_length() - 1) if self.gutter > 0 else 0)
        return max(0, k)


def compute(params: Params, slots) -> Layout:
    """Place the swatches and return their pixel rectangles."""
    cols = int(params.columns)
    if cols < 1:
        raise LayoutError("The atlas needs at least one column")

    if params.padding_mode == MIPSAFE:
        level = max(0, min(int(params.mip_level), MAX_MIP_LEVEL))
        unit = 1 << level
        pitch = round_up(max(int(params.cell_px), 2 * unit), unit)
        gutter = unit
    else:
        unit = 1
        pitch = int(params.cell_px)
        gutter = int(params.padding_px)
        if pitch < 1:
            raise LayoutError("Cell size must be at least 1 px")
        if gutter < 0:
            raise LayoutError("Padding cannot be negative")
        if 2 * gutter >= pitch:
            raise LayoutError(
                f"Padding of {gutter} px leaves no room inside {pitch} px cells. "
                "Lower the padding or raise the cell size."
            )

    placements = []
    row = col = 0
    seen = set()
    for slot in slots:
        if slot.uid in seen:
            raise LayoutError(f"Swatch id {slot.uid} is used twice")
        seen.add(slot.uid)
        span = 1 if slot.kind != GRADIENT else max(1, int(slot.span))
        if span > cols:
            raise LayoutError(
                f"A gradient spans {span} cells but the atlas has only {cols} columns"
            )
        if slot.kind == GRADIENT and span * pitch - 2 * gutter < 2:
            raise LayoutError(
                "A gradient is too short for its padding. Raise its span or the cell size."
            )
        if col + span > cols:
            row += 1
            col = 0
        placements.append((slot, row, col, span))
        col += span

    rows = (max(p[1] for p in placements) + 1) if placements else 1
    grid_w = cols * pitch
    grid_h = rows * pitch

    if params.region is not None:
        if params.image_size is None:
            raise LayoutError("Region mode needs the size of the target image")
        width, height = (int(v) for v in params.image_size)
        if width <= 0 or height <= 0:
            raise LayoutError("The target image has no pixels")
        rx, ry, rw, rh = (int(v) for v in params.region)
        if rw <= 0 or rh <= 0:
            raise LayoutError("The region must have a positive width and height")
        if rx < 0 or ry < 0 or rx + rw > width or ry + rh > height:
            raise LayoutError(f"The region lies outside the {width}x{height} image")
        ox = round_up(rx, unit)
        oy_top = ((ry + rh) // unit) * unit
        if ox + grid_w > rx + rw or oy_top - grid_h < ry:
            raise LayoutError(
                f"The palette needs {grid_w}x{grid_h} px but the region is {rw}x{rh} px. "
                "Enlarge the region, use fewer columns or smaller cells."
            )
        area = Rect(rx, ry, rx + rw, ry + rh)
    else:
        width = next_pow2(grid_w)
        height = max(width, next_pow2(grid_h))
        ox, oy_top = 0, height
        area = Rect(0, 0, width, height)

    layout = Layout(
        params=params,
        width=width,
        height=height,
        pitch=pitch,
        gutter=gutter,
        columns=cols,
        rows=rows,
        area=area,
        origin=(ox, oy_top),
    )
    for slot, r, c, span in placements:
        x0 = ox + c * pitch
        y1 = oy_top - r * pitch
        box = Rect(x0, y1 - pitch, x0 + span * pitch, y1)
        inner = Rect(box.x0 + gutter, box.y0 + gutter, box.x1 - gutter, box.y1 - gutter)
        layout.boxes[slot.uid] = box
        layout.inners[slot.uid] = inner
        layout.kinds[slot.uid] = slot.kind if slot.kind == GRADIENT else FLAT
        for k in range(span):
            layout.cells[(r, c + k)] = slot.uid
    return layout


# -- snapshots ---------------------------------------------------------------
#
# After each successful update the add-on stores where every swatch sat, in
# normalized UV space. When the layout changes, faces are moved from their
# old rectangle to the new one by swatch id. That is what keeps colours
# stable when the palette is edited.


def snapshot(layout: Layout) -> dict:
    swatches = {}
    for uid in layout.boxes:
        inner = layout.uv_inner(uid)
        swatches[str(uid)] = {
            "kind": layout.kinds[uid],
            "inner": inner.as_list(),
            "center": list(layout.uv_center(uid)),
        }
    return {
        "version": 1,
        "params": layout.params.as_dict(),
        "size": [layout.width, layout.height],
        "swatches": swatches,
    }


def moved_uids(old: dict | None, new: Layout, tol: float = 1e-9) -> set:
    """Swatch ids whose UV rectangle differs between a snapshot and a layout."""
    if not old:
        return set()
    out = set()
    new_snap = snapshot(new)["swatches"]
    for key, entry in old.get("swatches", {}).items():
        other = new_snap.get(key)
        if other is None:
            continue
        if other["kind"] != entry["kind"]:
            out.add(int(key))
            continue
        a = entry["inner"] + entry["center"]
        b = other["inner"] + other["center"]
        if any(abs(x - y) > tol for x, y in zip(a, b)):
            out.add(int(key))
    return out
