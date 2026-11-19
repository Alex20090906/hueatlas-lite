# SPDX-License-Identifier: GPL-3.0-or-later
"""Assign, select and pick, in Object and Edit Mode."""

import bpy
import numpy as np
from helpers import (
    add_cube, edit_select_faces, face_centroids, image_array, make_atlas, reset, sample, select_only,
)

from hueatlas import core
from hueatlas.meshio import MeshData

HEXES = ["#FF8000", "#00FF00", "#0000FF", "#FFFFFF", "#000000"]


def test_assign_faces_edit_mode():
    reset()
    atlas = make_atlas(HEXES)
    green = atlas.swatches[1].uid
    obj = add_cube()
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    edit_select_faces(obj, [0, 1, 2], active=1)
    assert bpy.ops.hueatlas.assign_faces(swatch_uid=green) == {"FINISHED"}
    assert bpy.ops.hueatlas.pick_from_face() == {"FINISHED"}
    assert core.active_swatch(atlas).uid == green
    bpy.ops.object.mode_set(mode="OBJECT")

    md = MeshData(obj.data)
    assert (md.uids[:3] == green).all() and (md.uids[3:] == 0).all()
    inner = core.compute_layout(atlas).uv_inner(green)
    loops = md.loop_mask(md.uids == green)
    uv = md.uv[loops]
    assert (uv[:, 0] >= inner.x0 - 1e-6).all() and (uv[:, 0] <= inner.x1 + 1e-6).all()
    assert (uv[:, 1] >= inner.y0 - 1e-6).all() and (uv[:, 1] <= inner.y1 + 1e-6).all()
    arr = image_array(atlas.image)
    for c in face_centroids(obj.data)[:3]:
        assert tuple(sample(arr, *c)[:3]) == (0, 255, 0)
    assert obj.data.materials[0] == atlas.material


def test_assign_objects_shared_mesh_and_select():
    reset()
    atlas = make_atlas(HEXES)
    a = add_cube("A")
    b = bpy.data.objects.new("B", a.data)
    bpy.context.scene.collection.objects.link(b)
    c = add_cube("C", location=(3, 0, 0))
    select_only([a, b])
    blue = atlas.swatches[2].uid
    assert bpy.ops.hueatlas.assign_objects(swatch_uid=blue) == {"FINISHED"}
    assert (MeshData(a.data).uids == blue).all()
    assert len(a.data.materials) == 1, "shared mesh must be processed once"
    atlas.active_swatch_index = 2
    select_only([c])
    bpy.ops.hueatlas.select_by_swatch()
    assert a.select_get() and b.select_get() and not c.select_get()


def test_multi_object_edit_mode():
    reset()
    atlas = make_atlas(HEXES)
    a = add_cube("A")
    b = add_cube("B", location=(3, 0, 0))
    select_only([a, b], active=a)
    bpy.ops.object.mode_set(mode="EDIT")
    for obj in (a, b):
        edit_select_faces(obj, [4])
    orange = atlas.swatches[0].uid
    bpy.ops.hueatlas.assign_faces(swatch_uid=orange)
    bpy.ops.mesh.select_all(action="DESELECT")
    atlas.active_swatch_index = 0
    bpy.ops.hueatlas.select_by_swatch()
    bpy.ops.object.mode_set(mode="OBJECT")
    for obj in (a, b):
        md = MeshData(obj.data)
        assert md.uids[4] == orange and (np.delete(md.uids, 4) == 0).all()
        assert md.select[4] and md.select.sum() == 1
