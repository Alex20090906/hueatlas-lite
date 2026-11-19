# SPDX-License-Identifier: GPL-3.0-or-later
"""Performance on a 100k-face mesh, and golden image hashes."""

import hashlib
import json
import os
import time

import bpy
from helpers import PAID, make_atlas, reset, select_only

from hueatlas import core, png, raster
from hueatlas import layout as L
from hueatlas.meshio import MeshData

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden.json")


def test_100k_faces_under_two_seconds():
    reset()
    atlas = make_atlas(["#FF8000", "#00FF00", "#0000FF", "#FFFFFF"], cell=16, cols=4)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=317, y_subdivisions=317, size=10)
    obj = bpy.context.active_object
    assert len(obj.data.polygons) >= 100_000, len(obj.data.polygons)
    select_only([obj])
    layout = core.sync(bpy.context.scene, atlas)
    t0 = time.perf_counter()
    core.assign_flat([obj], atlas, atlas.swatches[2].uid, layout, selected_only=False)
    t_assign = time.perf_counter() - t0
    assert t_assign < 2.0, f"assign took {t_assign:.2f}s"
    if PAID:
        t0 = time.perf_counter()
        atlas.columns = 3
        t_remap = time.perf_counter() - t0
        assert atlas.status == "", atlas.status
        assert t_remap < 2.0, f"remap took {t_remap:.2f}s"
        md = MeshData(obj.data)
        assert abs(md.uv[0, 0] - core.compute_layout(atlas).uv_center(atlas.swatches[2].uid)[0]) < 1e-6
    print(f"    assign {t_assign:.3f}s")


CASES = {
    "flat8_fixed": (L.Params(cell_px=16, columns=4), ["#E63946", "#F1FAEE", "#A8DADC", "#457B9D",
                                                      "#1D3557", "#FFB703", "#2A9D8F", "#6D597A"], []),
    "flat5_mip3": (L.Params(cell_px=16, columns=4, padding_mode=L.MIPSAFE, mip_level=3),
                   ["#FF8000", "#00FF00", "#0000FF", "#FFFFFF", "#000000"], []),
    "gradient_oklab": (L.Params(cell_px=16, columns=8),
                       ["#202020"], [("#000000", "#FF8800", "#FFFFFF")]),
}


def _render(params, flats, grads, space):
    slots, looks = [], {}
    uid = 1
    for hex_value in flats:
        slots.append(L.Slot(uid))
        looks[uid] = raster.Look(color=raster.parse_hex(hex_value), roughness=0.3 + 0.05 * uid,
                                 metallic=(uid % 2) * 1.0)
        uid += 1
    for stops in grads:
        slots.append(L.Slot(uid, L.GRADIENT, 6))
        n = len(stops) - 1
        looks[uid] = raster.Look(kind=L.GRADIENT, stops=[(i / n, raster.parse_hex(h)) for i, h in enumerate(stops)])
        uid += 1
    layout = L.compute(params, slots)
    out = {}
    for channel in ("albedo", "orm"):
        data = png.encode(raster.render(layout, looks, channel, space))
        out[channel] = hashlib.sha256(data).hexdigest()
    return out


def test_golden_images():
    got = {}
    for name, (params, flats, grads) in CASES.items():
        space = raster.OKLAB if "oklab" in name else raster.SRGB
        got[name] = _render(params, flats, grads, space)
    if os.environ.get("HUEATLAS_UPDATE_GOLDEN") == "1" or not os.path.isfile(GOLDEN):
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=2, sort_keys=True)
        print("    golden hashes written")
        return
    with open(GOLDEN, encoding="utf-8") as fh:
        want = json.load(fh)
    assert got == want, f"pixel output changed:\n{got}\n!=\n{want}"
