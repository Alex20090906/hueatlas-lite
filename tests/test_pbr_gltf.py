# SPDX-License-Identifier: GPL-3.0-or-later
"""PBR data atlas and a glTF round trip (full version)."""

import json
import os

import bpy
import numpy as np
from helpers import add_cube, assign_mask, face_centroids, image_array, make_atlas, paid_only, reset, sample

from hueatlas import core


@paid_only
def test_orm_and_gltf_round_trip():
    folder = reset()
    scene = bpy.context.scene
    atlas = make_atlas(["#C0C0C0", "#202020"], cell=16, cols=4)
    a, b = atlas.swatches[0], atlas.swatches[1]
    a.roughness, a.metallic = 0.25, 1.0
    b.roughness, b.metallic = 0.8, 0.0
    b.emission_color = (1.0, 0.0, 0.0)
    b.emission_strength = 3.0
    layout = core.sync(scene, atlas)
    orm = image_array(atlas.orm_image)
    box = layout.boxes[a.uid]
    px = orm[int(box.cy), int(box.cx)]
    assert px[0] == 255 and abs(int(px[1]) - 64) <= 1 and px[2] == 255, px
    assert atlas.orm_image.colorspace_settings.name == "Non-Color"
    assert atlas.emission_image is not None

    core.build_material(atlas)
    cube = add_cube()
    assign_mask(cube, atlas, a.uid, [0, 1, 2])
    assign_mask(cube, atlas, b.uid, [3, 4, 5])

    out = os.path.join(folder, "gltf", "kit.gltf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    assert bpy.ops.export_scene.gltf(filepath=out, export_format="GLTF_SEPARATE", use_selection=False) == {"FINISHED"}
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    mats = [m for m in doc["materials"] if m["name"] == atlas.material.name]
    assert mats, [m["name"] for m in doc["materials"]]
    mat = mats[0]
    pbr = mat["pbrMetallicRoughness"]
    assert "baseColorTexture" in pbr and "metallicRoughnessTexture" in pbr, pbr
    assert "emissiveTexture" in mat, mat
    assert mat.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength") == 3.0, mat
    samplers = doc.get("samplers", [])
    print(f"    glTF samplers for Closest interpolation: {samplers}")

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    assert bpy.ops.import_scene.gltf(filepath=out) == {"FINISHED"}
    imported = next(o for o in bpy.context.scene.objects if o.type == "MESH")
    imat = imported.data.materials[0]
    tex = next(n for n in imat.node_tree.nodes if n.type == "TEX_IMAGE" and n.outputs["Color"].is_linked
               and any(l.to_socket.name == "Base Color" for l in n.outputs["Color"].links))
    arr_in = image_array(tex.image)
    arr_src = image_array(atlas.image)
    for c in face_centroids(imported.data):
        got = sample(arr_in, *c)[:3]
        want = sample(arr_src, *c)[:3]
        assert (got == want).all(), (got, want, c)


@paid_only
def test_material_has_pbr_wiring():
    reset()
    atlas = make_atlas(["#C0C0C0"])
    atlas.swatches[0].emission_strength = 2.0
    atlas.swatches[0].emission_color = (0.0, 1.0, 0.0)
    mat = core.build_material(atlas)
    nodes = mat.node_tree.nodes
    assert nodes["HueAtlas ORM"].image == atlas.orm_image
    assert any(n.bl_idname == "ShaderNodeSeparateColor" for n in nodes)
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Roughness"].is_linked and bsdf.inputs["Metallic"].is_linked
    assert bsdf.inputs["Emission Color"].is_linked
    assert np.isclose(bsdf.inputs["Emission Strength"].default_value, 2.0)
