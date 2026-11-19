# SPDX-License-Identifier: GPL-3.0-or-later
"""Atlas generator: exact colours, gutters, power-of-two size, colour space."""

import os

import bpy
from helpers import load_from_disk, make_atlas, reset

from hueatlas import core, layout as L, png, raster

HEXES = ["#FF8000", "#00FF00", "#0000FF", "#FFFFFF", "#000000"]


def test_generate_flat_atlas():
    reset()
    atlas = make_atlas(HEXES, cell=16, cols=4)
    assert bpy.ops.hueatlas.atlas_generate() == {"FINISHED"}
    path = core.image_file(atlas, "Albedo")
    assert os.path.isfile(path), path
    arr = load_from_disk(path)
    h, w = arr.shape[:2]
    assert L.is_pow2(w) and L.is_pow2(h), (w, h)
    layout = core.compute_layout(atlas)
    for sw in atlas.swatches:
        box = layout.boxes[sw.uid]
        want = raster.to_u8(sw.color)
        assert (arr[int(box.cy), int(box.cx), :3] == want).all()
        block = arr[int(box.y0):int(box.y1), int(box.x0):int(box.x1), :3]
        assert (block == want).all(), f"gutter of {sw.name} not edge-extended"
    assert atlas.image.colorspace_settings.name == "sRGB"
    assert (png.read(path) == arr).all(), "our PNG reader disagrees with Blender"


def test_material_wiring_and_filter():
    reset()
    atlas = make_atlas(HEXES)
    mat = core.build_material(atlas)
    tex = mat.node_tree.nodes["HueAtlas Albedo"]
    assert tex.image == atlas.image
    assert tex.interpolation == "Closest"
    assert tex.extension == "EXTEND"
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Base Color"].is_linked


def test_live_colour_edit_updates_file():
    reset()
    atlas = make_atlas(HEXES)
    atlas.swatches[0].color = (0.0, 0.0, 0.0)
    arr = load_from_disk(core.image_file(atlas, "Albedo"))
    box = core.compute_layout(atlas).boxes[atlas.swatches[0].uid]
    assert tuple(arr[int(box.cy), int(box.cx), :3]) == (0, 0, 0)
