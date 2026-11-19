# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit-safe remap: palette edits never change a face's colour."""

import random

import bpy
import numpy as np
from helpers import add_cube, add_strip, assign_mask, check_colors, make_atlas, paid_only, reset

from hueatlas import core
from hueatlas.meshio import MeshData

HEXES = ["#E63946", "#F1FAEE", "#A8DADC", "#457B9D", "#1D3557", "#FFB703"]


def _scene_with_faces():
    atlas = make_atlas(HEXES, cell=16, cols=4)
    a = add_cube("A")
    b1 = add_cube("B1", location=(3, 0, 0))
    b2 = bpy.data.objects.new("B2", b1.data)
    bpy.context.scene.collection.objects.link(b2)
    c = add_strip(8, "C")
    uids = [sw.uid for sw in atlas.swatches]
    expected = {}
    for obj in (a, b1, c):
        n = len(obj.data.polygons)
        exp = np.zeros(n, dtype=np.int64)
        for k, uid in enumerate(uids):
            faces = [f for f in range(n) if f % len(uids) == k]
            if faces:
                assign_mask(obj, atlas, uid, faces)
                exp[faces] = uid
        expected[obj.data.name] = exp
    return atlas, [a, b1, b2, c], expected


def _activate(atlas, uid):
    atlas.active_swatch_index = core.swatch_index(atlas, uid)


@paid_only
def test_remap_sequence():
    reset()
    atlas, objs, expected = _scene_with_faces()
    check_colors(atlas, objs, expected)
    uids = [sw.uid for sw in atlas.swatches]

    _activate(atlas, uids[5])
    assert bpy.ops.hueatlas.swatch_move(to_index=0) == {"FINISHED"}
    check_colors(atlas, objs, expected)

    _activate(atlas, uids[2])
    assert bpy.ops.hueatlas.swatch_remove(fallback_uid=uids[1]) == {"FINISHED"}
    for exp in expected.values():
        exp[exp == uids[2]] = uids[1]
    check_colors(atlas, objs, expected)

    atlas.active_swatch_index = 2
    assert bpy.ops.hueatlas.swatch_add(kind="FLAT") == {"FINISHED"}
    assert atlas.active_swatch_index == 3
    check_colors(atlas, objs, expected)

    atlas.columns = 3
    assert atlas.status == "", atlas.status
    check_colors(atlas, objs, expected)
    atlas.cell_px = 8
    assert atlas.status == "", atlas.status
    check_colors(atlas, objs, expected)
    b1, b2 = objs[1], objs[2]
    assert b1.data == b2.data


@paid_only
def test_remap_fuzz():
    reset()
    atlas, objs, expected = _scene_with_faces()
    scene = bpy.context.scene
    rng = random.Random(7)
    for step in range(200):
        n = len(atlas.swatches)
        op = rng.choice(["move", "columns", "cell", "add", "remove", "padding", "mipsafe", "colour"])
        if op == "move" and n > 1:
            atlas.active_swatch_index = rng.randrange(n)
            bpy.ops.hueatlas.swatch_move(to_index=rng.randrange(n))
        elif op == "columns":
            atlas.columns = rng.randint(2, 8)
        elif op == "cell":
            atlas.cell_px = rng.choice([8, 12, 16, 20, 32])
        elif op == "add" and n < 24:
            atlas.active_swatch_index = rng.randrange(n)
            bpy.ops.hueatlas.swatch_add(kind="FLAT")
        elif op == "remove" and n > 3:
            i = rng.randrange(n)
            uid = atlas.swatches[i].uid
            others = [sw.uid for sw in atlas.swatches if sw.uid != uid]
            fb = rng.choice(others)
            atlas.active_swatch_index = i
            bpy.ops.hueatlas.swatch_remove(fallback_uid=fb)
            for exp in expected.values():
                exp[exp == uid] = fb
        elif op == "padding":
            atlas.padding_mode = "FIXED"
            atlas.padding_px = rng.randint(0, 3)
        elif op == "mipsafe":
            atlas.padding_mode = "MIPSAFE"
            atlas.mip_level = rng.randint(0, 3)
        elif op == "colour":
            sw = atlas.swatches[rng.randrange(n)]
            sw.color = (rng.random(), rng.random(), rng.random())
        if atlas.status:
            # An invalid combination (e.g. padding too big) is refused; restore a sane state.
            with core.suspended():
                atlas.padding_mode = "FIXED"
                atlas.padding_px = 2
                atlas.cell_px = 16
            core.sync(scene, atlas)
        try:
            check_colors(atlas, objs, expected)
        except AssertionError as exc:
            raise AssertionError(f"step {step} ({op}): {exc}") from None


@paid_only
def test_repair_uvs():
    reset()
    atlas, objs, expected = _scene_with_faces()
    md = MeshData(objs[0].data)
    md.uv[:] = 0.999
    md.write(uids=False, uv=True)
    assert bpy.ops.hueatlas.repair_uvs() == {"FINISHED"}
    check_colors(atlas, objs, expected)
