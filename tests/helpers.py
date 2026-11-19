# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared test helpers (run inside Blender)."""

import os
import tempfile

import bmesh
import bpy
import numpy as np

from hueatlas import core, edition, raster
from hueatlas.meshio import MeshData

PAID = edition.PAID


def paid_only(fn):
    fn.paid_only = True
    return fn


def lite_only(fn):
    fn.lite_only = True
    return fn


def reset() -> str:
    """Empty the scene and save to a fresh temp folder so '//' paths resolve."""
    if bpy.context.view_layer.objects.active is not None and bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for item in list(coll):
            coll.remove(item)
    s = bpy.context.scene.hueatlas
    s.atlases.clear()
    s.next_uid = 1
    s.audit_items.clear()
    s.audit_summary = ""
    folder = tempfile.mkdtemp(prefix="hueatlas_test_")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(folder, "test.blend"))
    return folder


def make_atlas(hexes, cell=16, cols=4, name="Pal", **props):
    scene = bpy.context.scene
    atlas = core.create_atlas(scene, name, defaults=False)
    with core.suspended():
        atlas.cell_px = cell
        atlas.columns = cols
        for key, value in props.items():
            setattr(atlas, key, value)
    for i, hex_value in enumerate(hexes):
        core.add_swatch(scene, atlas, name=f"S{i}", color=raster.parse_hex(hex_value))
    core.sync(scene, atlas)
    return atlas


def add_cube(name="Cube", location=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_strip(n=10, name="Strip"):
    """n unit quads in a row along +X."""
    verts, faces = [], []
    for i in range(n + 1):
        verts += [(float(i), 0.0, 0.0), (float(i), 1.0, 0.0)]
    for i in range(n):
        a = 2 * i
        faces.append((a, a + 2, a + 3, a + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def set_face_selection(obj, indices):
    me = obj.data
    sel = np.zeros(len(me.polygons), dtype=bool)
    sel[list(indices)] = True
    me.polygons.foreach_set("select", sel)
    me.update()


def select_only(objects, active=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objects[0] if objects else None)


def edit_select_faces(obj, indices, active=None):
    """In Edit Mode, select exactly the given faces of obj."""
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(obj.data)
    bm.select_mode = {"FACE"}
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f.select_set(False)
    for i in indices:
        bm.faces[i].select_set(True)
    if active is not None:
        bm.faces.active = bm.faces[active]
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def face_centroids(me) -> np.ndarray:
    md = MeshData(me)
    sums = np.add.reduceat(md.uv.astype(np.float64), md.loop_start, axis=0)
    return sums / md.loop_total[:, None]


def sample(arr, u, v):
    h, w = arr.shape[:2]
    x = min(max(int(u * w), 0), w - 1)
    y = min(max(int(v * h), 0), h - 1)
    return arr[y, x]


def image_array(img) -> np.ndarray:
    return core.read_pixels(img)


def load_from_disk(path) -> np.ndarray:
    img = bpy.data.images.load(path, check_existing=False)
    try:
        return core.read_pixels(img)
    finally:
        bpy.data.images.remove(img)


def assign_mask(obj, atlas, uid, faces):
    """Assign the given faces of obj (Object Mode) to swatch uid."""
    layout = core.sync(bpy.context.scene, atlas)
    set_face_selection(obj, faces)
    core.assign_flat([obj], atlas, uid, layout, selected_only=True)


def check_colors(atlas, objects, expected_uid=None):
    """Every assigned face samples its own swatch colour (exact for flat swatches)."""
    arr = image_array(atlas.image)
    seen = set()
    for obj in objects:
        me = obj.data
        if me.as_pointer() in seen:
            continue
        seen.add(me.as_pointer())
        md = MeshData(me)
        cents = face_centroids(me)
        for f in range(md.n_faces):
            uid = int(md.uids[f])
            if uid == 0:
                continue
            if expected_uid is not None:
                exp = expected_uid[me.name][f]
                assert uid == exp, f"{me.name} face {f}: uid {uid} != expected {exp}"
            sw = core.swatch_by_uid(atlas, uid)
            assert sw is not None, f"{me.name} face {f}: uid {uid} has no swatch"
            got = sample(arr, *cents[f])[:3]
            want = raster.to_u8(sw.color)
            assert (got == want).all(), f"{me.name} face {f} (uid {uid}): sampled {got}, want {want}"
