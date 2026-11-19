# SPDX-License-Identifier: GPL-3.0-or-later
"""Lite edition limits."""

import bpy
import numpy as np
from helpers import add_cube, check_colors, lite_only, make_atlas, reset, select_only

from hueatlas import core
from hueatlas.meshio import MeshData


@lite_only
def test_paid_operators_not_registered():
    for name in ("HUEATLAS_OT_export_pack", "HUEATLAS_OT_gradient_project", "HUEATLAS_OT_theme_add",
                 "HUEATLAS_OT_repair_uvs"):
        assert not hasattr(bpy.types, name), name


@lite_only
def test_lite_limits():
    reset()
    atlas = make_atlas(["#E63946", "#F1FAEE", "#A8DADC", "#457B9D"], cell=16, cols=4)
    with core.suspended():
        atlas.padding_px = 5
        atlas.padding_mode = "MIPSAFE"
    assert core.compute_layout(atlas).gutter == 2, "lite gutter is fixed at 2 px"
    assert bpy.ops.hueatlas.atlas_add() == {"CANCELLED"}
    assert bpy.ops.hueatlas.swatch_add(kind="GRADIENT") == {"CANCELLED"}

    cube = add_cube()
    select_only([cube])
    bpy.ops.hueatlas.assign_objects(swatch_uid=atlas.swatches[1].uid)
    uv = MeshData(cube.data).uv.copy()

    atlas.active_swatch_index = 1
    assert bpy.ops.hueatlas.swatch_move(direction="DOWN") == {"CANCELLED"}
    atlas.columns = 2
    assert atlas.columns == 4 and "HueAtlas Lite" in atlas.status, atlas.status
    assert np.array_equal(MeshData(cube.data).uv, uv)
    assert bpy.ops.hueatlas.swatch_remove() == {"CANCELLED"}

    n = len(atlas.swatches)
    assert bpy.ops.hueatlas.swatch_add(kind="FLAT") == {"FINISHED"}
    assert len(atlas.swatches) == n + 1 and atlas.active_swatch_index == n
    assert np.array_equal(MeshData(cube.data).uv, uv)
    check_colors(atlas, [cube])

    atlas.active_swatch_index = n
    assert bpy.ops.hueatlas.swatch_remove() == {"FINISHED"}
    mat = core.build_material(atlas)
    assert "HueAtlas ORM" not in mat.node_tree.nodes
