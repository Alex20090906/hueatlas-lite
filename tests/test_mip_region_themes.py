# SPDX-License-Identifier: GPL-3.0-or-later
"""Mip-safe padding, region mode and themes (full version)."""

import hashlib
import os

import bpy
import numpy as np
from helpers import add_cube, assign_mask, image_array, load_from_disk, make_atlas, paid_only, reset

from hueatlas import core, png, raster
from hueatlas.meshio import MeshData

EIGHT = ["#E63946", "#F1FAEE", "#A8DADC", "#457B9D", "#1D3557", "#FFB703", "#2A9D8F", "#6D597A"]


@paid_only
def test_mipsafe_levels_stay_clean():
    reset()
    atlas = make_atlas(EIGHT, cell=16, cols=4, padding_mode="MIPSAFE", mip_level=3)
    layout = core.compute_layout(atlas)
    assert layout.clean_mip_level() >= 3
    arr = image_array(atlas.image)
    h, w = arr.shape[:2]
    for level in (1, 2, 3):
        mip = raster.box_mip(arr, level)
        mh, mw = mip.shape[:2]
        for sw in atlas.swatches:
            u, v = layout.uv_center(sw.uid)
            texel = mip[min(int(v * mh), mh - 1), min(int(u * mw), mw - 1), :3]
            want = raster.to_u8(sw.color).astype(float)
            assert np.abs(texel - want).max() <= 1.0, (level, sw.name, texel, want)
    mip = raster.box_mip(arr, 5)
    mh, mw = mip.shape[:2]
    dirty = 0
    for sw in atlas.swatches:
        u, v = layout.uv_center(sw.uid)
        texel = mip[min(int(v * mh), mh - 1), min(int(u * mw), mw - 1), :3]
        dirty += int(np.abs(texel - raster.to_u8(sw.color)).max() > 1.0)
    assert dirty > 0, "the test must be able to detect bleeding"


@paid_only
def test_region_mode_keeps_outside_pixels():
    folder = reset()
    rng = np.random.default_rng(3)
    noise = rng.integers(0, 256, size=(256, 256, 4), dtype=np.uint8)
    noise[..., 3] = 255
    path = png.write(os.path.join(folder, "painted.png"), noise)
    img = bpy.data.images.load(path)
    atlas = core.create_atlas(bpy.context.scene, "Kit", defaults=False)
    with core.suspended():
        atlas.image = img
        atlas.use_region = True
        atlas.region_x, atlas.region_y, atlas.region_w, atlas.region_h = 128, 0, 128, 128
        atlas.cell_px, atlas.columns = 16, 4
    for hex_value in EIGHT[:5]:
        core.add_swatch(bpy.context.scene, atlas, color=raster.parse_hex(hex_value))
    core.sync(bpy.context.scene, atlas)
    cube = add_cube()
    assign_mask(cube, atlas, atlas.swatches[1].uid, range(6))

    after = load_from_disk(path)
    mask = np.ones((256, 256), dtype=bool)
    mask[0:128, 128:256] = False
    assert hashlib.sha256(after[mask].tobytes()).digest() == hashlib.sha256(noise[mask].tobytes()).digest()
    uv = MeshData(cube.data).uv
    assert (uv[:, 0] >= 0.5).all() and (uv[:, 0] <= 1.0).all()
    assert (uv[:, 1] >= 0.0).all() and (uv[:, 1] <= 0.5).all()
    assert os.path.isfile(path + ".bak")


@paid_only
def test_themes_share_layout():
    from hueatlas.paid import themes

    folder = reset()
    scene = bpy.context.scene
    atlas = make_atlas(EIGHT[:4], cell=16, cols=4)
    cube = add_cube()
    assign_mask(cube, atlas, atlas.swatches[2].uid, range(6))
    uv_before = MeshData(cube.data).uv.copy()
    themes.add(atlas, "Day")
    with core.suspended():
        for sw in atlas.swatches:
            sw.color = tuple(1.0 - c for c in sw.color)
    core.sync(scene, atlas)
    themes.add(atlas, "Night")
    atlas.active_theme_index = 0
    assert bpy.ops.hueatlas.theme_apply() == {"FINISHED"}
    assert np.array_equal(MeshData(cube.data).uv, uv_before)
    files = themes.export(atlas, os.path.join(folder, "themes"))
    albedos = [f for f in files if f.endswith("_Albedo.png")]
    assert len(albedos) == 2
    day, night = (png.read(p) for p in albedos)
    layout = core.compute_layout(atlas)
    outside = np.ones(day.shape[:2], dtype=bool)
    for box in layout.boxes.values():
        outside[int(box.y0):int(box.y1), int(box.x0):int(box.x1)] = False
    assert np.array_equal(day[outside], night[outside]), "background structure differs"
    day_theme = themes.theme_data(atlas.themes[0])
    night_theme = themes.theme_data(atlas.themes[1])
    for sw in atlas.swatches:
        box = layout.boxes[sw.uid]
        y, x = int(box.cy), int(box.cx)
        assert raster.to_hex(day[y, x, :3] / 255.0) == day_theme[str(sw.uid)]["color"]
        assert raster.to_hex(night[y, x, :3] / 255.0) == night_theme[str(sw.uid)]["color"]
