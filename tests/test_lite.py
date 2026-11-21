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
                 "HUEATLAS_OT_repair_uvs", "HUEATLAS_OT_swatch_move"):
        assert not hasattr(bpy.types, name), name


@lite_only
def test_lite_shows_no_upgrade_text():
    """extensions.blender.org declined Lite 1.0.0 for lock messages; none may come back."""
    import os
    import hueatlas

    root = os.path.dirname(hueatlas.__file__)
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    text = fh.read()
                for bad in ("Not available in", "LITE_MESSAGE", "require_paid"):
                    assert bad not in text, f"{name}: {bad}"
    props = bpy.ops.hueatlas.palette_import.get_rna_type().properties
    assert "new_atlas" not in props.keys()
    kinds = bpy.ops.hueatlas.swatch_add.get_rna_type().properties["kind"].enum_items.keys()
    assert list(kinds) == ["FLAT"], list(kinds)


@lite_only
def test_lite_limits():
    reset()
    atlas = make_atlas(["#E63946", "#F1FAEE", "#A8DADC", "#457B9D"], cell=16, cols=4)
    with core.suspended():
        atlas.padding_px = 5
        atlas.padding_mode = "MIPSAFE"
    assert core.compute_layout(atlas).gutter == 2, "lite gutter is fixed at 2 px"
    assert not bpy.ops.hueatlas.atlas_add.poll(), "one atlas per file in lite"
    n_atlases = len(bpy.context.scene.hueatlas.atlases)

    cube = add_cube()
    select_only([cube])
    bpy.ops.hueatlas.assign_objects(swatch_uid=atlas.swatches[1].uid)
    uv = MeshData(cube.data).uv.copy()

    atlas.active_swatch_index = 1
    atlas.columns = 2
    assert atlas.columns == 4 and "layout was kept" in atlas.status, atlas.status
    assert "Lite" not in atlas.status, atlas.status
    assert len(bpy.context.scene.hueatlas.atlases) == n_atlases
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
