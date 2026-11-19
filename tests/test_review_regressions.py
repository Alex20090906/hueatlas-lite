# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for issues found in the adversarial review."""

import json
import os

import bpy
import numpy as np
from helpers import (
    PAID, add_cube, add_strip, assign_mask, check_colors, face_centroids, image_array, lite_only, make_atlas,
    paid_only, reset, sample, select_only,
)

from hueatlas import core, edition, png, props, raster
from hueatlas.meshio import MeshData

FOUR = ["#E63946", "#F1FAEE", "#A8DADC", "#457B9D"]


def _user_image(folder, name="painted.png", size=64):
    arr = np.zeros((size, size, 4), np.uint8)
    arr[..., 0] = 200
    arr[..., 3] = 255
    path = png.write(os.path.join(folder, name), arr)
    img = bpy.data.images.load(path)
    mat = bpy.data.materials.new("Trim")
    if hasattr(mat, "use_nodes") and not mat.use_nodes:
        mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    return img, mat, node


def test_picking_foreign_image_never_deletes_it():
    folder = reset()
    atlas = make_atlas(FOUR)
    img, mat, node = _user_image(folder)
    atlas.image = img
    assert img.name in bpy.data.images, "user image was deleted"
    assert node.image == img, "user material was repointed"
    assert "not managed by HueAtlas" in atlas.status
    assert bpy.ops.hueatlas.atlas_generate() == {"FINISHED"}
    assert img.name in bpy.data.images and node.image == img
    assert atlas.image != img and core.owns_image(atlas, atlas.image, "Albedo")


@paid_only
def test_region_off_keeps_user_image():
    folder = reset()
    img, mat, node = _user_image(folder, size=128)
    atlas = make_atlas(FOUR)
    with core.suspended():
        atlas.use_region = True
        atlas.region_x, atlas.region_y, atlas.region_w, atlas.region_h = 64, 64, 64, 64
    atlas.image = img
    assert atlas.status == "", atlas.status
    atlas.use_region = False
    assert img.name in bpy.data.images and node.image == img
    assert atlas.image != img


@paid_only
def test_region_refuses_float_image():
    reset()
    img = bpy.data.images.new("hdr", 128, 128, float_buffer=True)
    atlas = make_atlas(FOUR)
    with core.suspended():
        atlas.use_region = True
        atlas.region_w = atlas.region_h = 64
    atlas.image = img
    assert "8-bit" in atlas.status, atlas.status


def test_atlas_names_never_share_files():
    folder = reset()
    s = bpy.context.scene.hueatlas
    a = core.create_atlas(bpy.context.scene, "Kit A")
    core.sync(bpy.context.scene, a)
    if not PAID:
        assert core.unique_atlas_name("kit_a") != "kit_a"
        return
    b = core.create_atlas(bpy.context.scene, "Kit_A")
    core.sync(bpy.context.scene, b)
    assert core.image_file(a, "Albedo").lower() != core.image_file(b, "Albedo").lower()
    assert a.image != b.image
    path = os.path.join(folder, "pal.json")
    s.active_atlas_index = 0
    bpy.ops.hueatlas.palette_export(filepath=path)
    bpy.ops.hueatlas.palette_import(filepath=path, new_atlas=True)
    names = [x.name for x in s.atlases]
    stems = {core.safe_name(n).casefold() for n in names}
    assert len(stems) == len(names), names


@lite_only
def test_lite_import_and_remove_never_wedge():
    folder = reset()
    atlas = make_atlas(FOUR * 2, cell=16, cols=4)
    cube = add_cube()
    select_only([cube])
    bpy.ops.hueatlas.assign_objects(swatch_uid=atlas.swatches[0].uid)
    path = os.path.join(folder, "many.hex")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(f"#{i:02X}{i:02X}{i:02X}" for i in range(64)))
    n = len(atlas.swatches)
    try:
        result = bpy.ops.hueatlas.palette_import(filepath=path)
    except RuntimeError:  # error reports raise in background mode
        result = {"CANCELLED"}
    assert result == {"CANCELLED"}
    assert len(atlas.swatches) == n
    atlas.swatches[0].color = (0.0, 0.0, 1.0)
    assert atlas.status == "", atlas.status
    check_colors(atlas, [cube])


@paid_only
def test_remap_reaches_other_scenes():
    reset()
    atlas = make_atlas(FOUR)
    cube = add_cube()
    assign_mask(cube, atlas, atlas.swatches[0].uid, range(6))
    level = bpy.data.scenes.new("Level")
    for coll in list(cube.users_collection):
        coll.objects.unlink(cube)
    level.collection.objects.link(cube)
    atlas.active_swatch_index = 0
    assert bpy.ops.hueatlas.swatch_move(to_index=3) == {"FINISHED"}
    check_colors(atlas, [cube])
    bpy.data.scenes.remove(level)


def test_imported_uids_avoid_faces_of_removed_atlas():
    folder = reset()
    atlas = make_atlas(FOUR)
    rock = add_cube("Rock")
    assign_mask(rock, atlas, atlas.swatches[0].uid, range(6))
    path = os.path.join(folder, "pal.json")
    bpy.ops.hueatlas.palette_export(filepath=path)
    bpy.ops.hueatlas.atlas_remove()
    bpy.ops.hueatlas.palette_import(filepath=path)
    fresh = core.active_atlas(bpy.context.scene)
    rock_uids = set(np.unique(MeshData(rock.data).uids).tolist())
    assert not (rock_uids & core.atlas_uids(fresh)), (rock_uids, core.atlas_uids(fresh))


@paid_only
def test_failed_write_does_not_double_remap():
    folder = reset()
    scene = bpy.context.scene
    atlas = make_atlas(FOUR)
    sw = core.add_swatch(scene, atlas, name="Ramp", kind="GRADIENT")
    with core.suspended():
        sw.span = 3
    guid = sw.uid  # collection items move in memory; keep the id, not the reference
    layout = core.sync(scene, atlas)
    strip = add_strip(10)
    from hueatlas.paid import gradient

    gradient.project([strip], atlas, sw.uid, layout, "X", "GLOBAL", selected_only=False)
    before = MeshData(strip.data).uv.copy()
    textures = os.path.join(folder, "textures")
    os.rename(textures, textures + "_moved")
    with open(textures, "w") as fh:
        fh.write("blocker")
    atlas.active_swatch_index = core.swatch_index(atlas, sw.uid)
    order = [x.uid for x in atlas.swatches]
    try:
        result = bpy.ops.hueatlas.swatch_move(to_index=0)
    except RuntimeError:  # error reports raise in background mode
        result = {"CANCELLED"}
    assert result == {"CANCELLED"}
    assert [x.uid for x in atlas.swatches] == order, "swatch order not rolled back"
    assert np.array_equal(MeshData(strip.data).uv, before), "UVs moved although the write failed"
    os.remove(textures)
    os.rename(textures + "_moved", textures)
    assert bpy.ops.hueatlas.swatch_move(to_index=0) == {"FINISHED"}
    assert bpy.ops.hueatlas.atlas_generate() == {"FINISHED"}
    inner = core.compute_layout(atlas).uv_inner(guid)
    u = MeshData(strip.data).uv[:, 0]
    assert abs(u.min() - inner.x0) < 1e-4 and abs(u.max() - inner.x1) < 1e-4, (u.min(), u.max(), inner)


@paid_only
def test_paid_remove_validates_before_removing():
    reset()
    atlas = make_atlas(FOUR, cell=16, cols=4)
    with core.suspended():
        atlas.padding_px = 8
    n = len(atlas.swatches)
    atlas.active_swatch_index = 1
    try:
        result = bpy.ops.hueatlas.swatch_remove()
    except RuntimeError:
        result = {"CANCELLED"}
    assert result == {"CANCELLED"} and len(atlas.swatches) == n


def test_writes_render_uv_map():
    reset()
    atlas = make_atlas(FOUR)
    cube = add_cube()
    me = cube.data
    me.uv_layers.new(name="Lightmap")
    me.uv_layers.active = me.uv_layers["Lightmap"]
    me.uv_layers["UVMap"].active_render = True
    select_only([cube])
    bpy.ops.hueatlas.assign_objects(swatch_uid=atlas.swatches[1].uid)
    flat = np.zeros(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].uv.foreach_get("vector", flat)
    centre = core.compute_layout(atlas).uv_center(atlas.swatches[1].uid)
    assert np.allclose(flat.reshape(-1, 2), centre), "palette UVs must go to the render UV map"


@paid_only
def test_kind_toggle_seeds_stops():
    reset()
    atlas = make_atlas(FOUR)
    sw = atlas.swatches[0]
    sw.kind = "GRADIENT"
    assert len(sw.stops) == 2
    assert raster.to_hex(sw.stops[1].color) == raster.to_hex(sw.color)


def test_gpl_with_bom_and_strict_hex():
    folder = reset()
    path = os.path.join(folder, "bom.gpl")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write("GIMP Palette\nName: x\n#\n255 0 0 Red\n0 255 0 Green\n")
    bpy.ops.hueatlas.palette_import(filepath=path)
    atlas = core.active_atlas(bpy.context.scene)
    assert [raster.to_hex(sw.color) for sw in atlas.swatches] == ["#FF0000", "#00FF00"]
    assert core.parse_palette_text("Bed #112233 255") == [("Color 1", raster.parse_hex("#112233"))]


@paid_only
def test_generate_rewires_material():
    reset()
    bpy.ops.hueatlas.atlas_add()
    atlas = core.active_atlas(bpy.context.scene)
    atlas.swatches[2].emission_color = (1.0, 0.5, 0.0)
    atlas.swatches[2].emission_strength = 5.0
    bpy.ops.hueatlas.atlas_generate()
    nt = atlas.material.node_tree
    bsdf = core.principled(nt)
    assert bsdf.inputs["Emission Color"].is_linked
    assert abs(bsdf.inputs["Emission Strength"].default_value - 5.0) < 1e-6
    atlas.filter_mode = "LINEAR"
    assert nt.nodes["HueAtlas Albedo"].interpolation == "Linear"
    assert nt.nodes["HueAtlas ORM"].interpolation == "Linear"


@paid_only
def test_theme_export_shares_emission_scale():
    from hueatlas.paid import themes

    folder = reset()
    atlas = make_atlas(FOUR)
    lamp = atlas.swatches[0]
    lamp.emission_color = (1.0, 0.8, 0.2)
    lamp.emission_strength = 2.0
    themes.add(atlas, "Day")
    lamp.emission_strength = 8.0
    themes.add(atlas, "Night")
    files = themes.export(atlas, os.path.join(folder, "t"))
    meta = json.load(open(next(f for f in files if f.endswith("_themes.json")), encoding="utf-8"))
    assert meta["emission_strength"] == 8.0
    day = png.read(next(f for f in files if f.endswith("_Day_Emission.png")))
    night = png.read(next(f for f in files if f.endswith("_Night_Emission.png")))
    box = core.compute_layout(atlas).boxes[lamp.uid]
    y, x = int(box.cy), int(box.cx)
    assert night[y, x, 0] > day[y, x, 0], (day[y, x], night[y, x])


@paid_only
def test_undo_handler_fixes_stale_faces():
    from hueatlas import handlers

    reset()
    atlas = make_atlas(FOUR)
    cube = add_cube()
    assign_mask(cube, atlas, atlas.swatches[0].uid, range(6))
    md = MeshData(cube.data)
    old_uv, old_rev = md.uv.copy(), md.revs.copy()
    atlas.columns = 2  # moves cells, bumps the revision
    md = MeshData(cube.data)
    md.uv[:] = old_uv  # what an Edit Mode undo restores
    md.revs[:] = old_rev
    md.write(uids=True, uv=True)
    handlers._after_undo()
    check_colors(atlas, [cube])


@paid_only
def test_region_audit_ignores_painted_faces():
    folder = reset()
    img, _mat, _node = _user_image(folder, size=256)
    atlas = make_atlas(FOUR)
    with core.suspended():
        atlas.use_region = True
        atlas.region_x, atlas.region_y, atlas.region_w, atlas.region_h = 128, 0, 128, 128
        atlas.image = img
    core.sync(bpy.context.scene, atlas)
    painted = add_cube("Painted")
    painted.data.materials.append(atlas.material)
    md = MeshData(painted.data, create=True)
    md.uv[:] = (0.2, 0.8)
    md.write(uids=True, uv=True)
    issues = core.audit(bpy.context.scene, atlas)
    assert not [i for i in issues if i["object"] == "Painted"], issues


def test_edition_guard_refuses_other_owner():
    prop = bpy.types.Scene.bl_rna.properties["hueatlas"]
    original = prop.description
    assert original == props.owner_tag(edition._BASE)
    assert props.registered_owner() == original
    edition.claim_registration()  # same owner: fine
