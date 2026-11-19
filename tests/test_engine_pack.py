# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine export pack (full version)."""

import os
import re
import shutil

import bpy
from helpers import image_array, make_atlas, paid_only, reset

from hueatlas import core, png


@paid_only
def test_engine_pack_files():
    folder = reset()
    atlas = make_atlas(["#C0C0C0", "#202020", "#FF0000"], cell=16, cols=4,
                       padding_mode="MIPSAFE", mip_level=2)
    a, b = atlas.swatches[0], atlas.swatches[1]
    a.roughness, a.metallic = 0.25, 1.0
    b.emission_color = (1.0, 0.5, 0.0)
    b.emission_strength = 4.0
    atlas.godot_prefix = "res://art/palette/"
    atlas.export_godot = atlas.export_unity = atlas.export_unreal = True
    assert bpy.ops.hueatlas.export_pack() == {"FINISHED"}
    root = os.path.join(folder, "engine")
    g, u, r = (os.path.join(root, d) for d in ("godot", "unity", "unreal"))
    for path in [
        os.path.join(g, "Pal_Albedo.png"), os.path.join(g, "Pal_ORM.png"), os.path.join(g, "Pal_Emission.png"),
        os.path.join(g, "Pal_Albedo.png.import"), os.path.join(g, "Pal.tres"),
        os.path.join(u, "Pal_Albedo.png"), os.path.join(u, "Pal_MetallicSmoothness.png"),
        os.path.join(r, "T_Pal_BaseColor.png"), os.path.join(r, "T_Pal_ORM.png"), os.path.join(r, "T_Pal_Emissive.png"),
    ]:
        assert os.path.isfile(path), path

    with open(os.path.join(g, "Pal.tres"), encoding="utf-8") as fh:
        tres = fh.read()
    assert tres.startswith('[gd_resource type="ORMMaterial3D"'), tres[:60]
    assert "format=3" in tres
    assert 'albedo_texture = ExtResource(' in tres and 'orm_texture = ExtResource(' in tres
    paths = [ln.split('path="')[1].split('"')[0] for ln in tres.splitlines() if ln.startswith("[ext_resource")]
    assert paths and all(p.startswith("res://art/palette/") for p in paths), paths
    assert "texture_filter = 5" in tres, "linear atlases use anisotropic trilinear (verified in Godot 4.7.2)"
    assert "cull_mode = 2" in tres, "match the double-sided glTF export"
    assert "emission_energy_multiplier = 4" in tres
    with open(os.path.join(g, "Pal_Albedo.png.import"), encoding="utf-8") as fh:
        imp = fh.read()
    assert "compress/mode=0" in imp and "mipmaps/generate=true" in imp
    with open(os.path.join(u, "README_Unity.txt"), encoding="utf-8") as fh:
        unity = fh.read()
    # Verified in Unity 6.3 URP 17.3: Aniso Level 1-2 tints far grazing gradients, 4+ is clean.
    assert "Filter Mode Bilinear, Aniso Level 8." in unity, unity
    assert "Anisotropic Textures" in unity and "Color Space" in unity
    assert "Intensity to 2.00" in unity and "Smoothness slider to 1.0" in unity
    assert "Generate Mipmap ON" in unity and "Pal_Emission.png: sRGB ON" in unity
    # glTF route, verified with glTFast 6.21: aniso 8 for linear atlases, emission strength ignored above 1
    assert "set Anisotropic Filter Level to 8" in unity and "x1 instead of x4" in unity
    assert "{" not in unity and "}" not in unity, "unfilled template field"

    layout = core.compute_layout(atlas)
    box = layout.boxes[a.uid]
    ms = png.read(os.path.join(u, "Pal_MetallicSmoothness.png"))
    px = ms[int(box.cy), int(box.cx)]
    assert px[0] == 255 and abs(int(px[3]) - 191) <= 1, px
    unreal_orm = png.read(os.path.join(r, "T_Pal_ORM.png"))
    assert (unreal_orm == png.read(os.path.join(g, "Pal_ORM.png"))).all()
    assert (unreal_orm == image_array(atlas.orm_image)).all()


@paid_only
def test_unity_readme_follows_atlas():
    """No emission step without emissive swatches (it would make the model glow); Point filter for nearest."""
    folder = reset()
    atlas = make_atlas(["#C0C0C0", "#202020"])
    assert not core.use_linear_filter(atlas)
    atlas.export_unity = True
    bpy.ops.hueatlas.export_pack()
    u = os.path.join(folder, "engine", "unity")
    with open(os.path.join(u, "README_Unity.txt"), encoding="utf-8") as fh:
        text = fh.read()
    assert not os.path.exists(os.path.join(u, "Pal_Emission.png"))
    assert "Emission: leave it off" in text and "Intensity to" not in text and "Emission.png" not in text
    assert "Generate Mipmap OFF" in text and "Filter Mode Point." in text and "Aniso Level" not in text
    assert "untick Generate Mip Maps" in text and "Anisotropic Filter Level" not in text
    assert "emissive_strength" not in text
    # Blender shows back faces by default, so the URP Lit material must too (verified in Unity 6.3).
    assert "Render Face = Both" in text
    core.ensure_material(atlas).use_backface_culling = True
    bpy.ops.hueatlas.export_pack()
    with open(os.path.join(u, "README_Unity.txt"), encoding="utf-8") as fh:
        assert "Render Face" not in fh.read()
    assert f"Max Size {core.compute_layout(atlas).width} or larger" in text
    assert "{" not in text and "}" not in text, "unfilled template field"


@paid_only
def test_godot_reexport_keeps_uids():
    folder = reset()
    atlas = make_atlas(["#C0C0C0", "#202020"])
    atlas.export_godot = True
    bpy.ops.hueatlas.export_pack()
    g = os.path.join(folder, "engine", "godot")
    imp = os.path.join(g, "Pal_Albedo.png.import")
    tres = os.path.join(g, "Pal.tres")
    # Simulate what Godot writes after importing.
    with open(imp, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace('type="CompressedTexture2D"\n', 'type="CompressedTexture2D"\nuid="uid://abc123albedo"\n'
                        'path="res://.godot/imported/Pal_Albedo.png-1.ctex"\n')
    with open(imp, "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(tres, encoding="utf-8") as fh:
        text = fh.read()
    header, rest = text.split("\n", 1)
    header = re.sub(r' uid="[^"]*"', "", header).replace("format=3]", 'format=3 uid="uid://xyz789mat"]')
    with open(tres, "w", encoding="utf-8") as fh:
        fh.write(header + "\n" + rest)
    for colour in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        atlas.swatches[0].color = colour
        bpy.ops.hueatlas.export_pack()
        with open(imp, encoding="utf-8") as fh:
            imp_text = fh.read()
        with open(tres, encoding="utf-8") as fh:
            tres_text = fh.read()
        assert imp_text.count("uid=") == 1 and 'uid="uid://abc123albedo"' in imp_text
        assert "compress/mode=0" in imp_text
        assert tres_text.splitlines()[0].endswith('format=3 uid="uid://xyz789mat"]'), tres_text.splitlines()[0]
        assert ('[ext_resource type="Texture2D" uid="uid://abc123albedo" '
                'path="res://art/palette/Pal_Albedo.png"') in tres_text


@paid_only
def test_godot_uids_are_stable_and_unique():
    from hueatlas.paid import engine_pack

    folder = reset()
    atlas = make_atlas(["#C0C0C0", "#202020"])
    atlas.swatches[1].emission_strength = 2.0
    atlas.swatches[1].emission_color = (1.0, 1.0, 0.0)
    atlas.export_godot = True
    g = os.path.join(folder, "engine", "godot")
    seen = []
    for _ in range(3):
        bpy.ops.hueatlas.export_pack()
        own = engine_pack.existing_uid(os.path.join(g, "Pal.tres"))
        tex = [engine_pack.existing_uid(os.path.join(g, f)) for f in
               ("Pal_Albedo.png.import", "Pal_ORM.png.import", "Pal_Emission.png.import")]
        assert own and all(tex) and own not in tex and len(set(tex)) == 3, (own, tex)
        assert all(re.fullmatch(r"uid://[a-y0-8]+", u) for u in tex + [own])
        seen.append((own, tuple(tex)))
    assert seen[0] == seen[1] == seen[2], "uids must not change between exports"
    # Copying a fresh export to a clean folder gives the same uids too.
    shutil.rmtree(g)
    bpy.ops.hueatlas.export_pack()
    assert engine_pack.existing_uid(os.path.join(g, "Pal.tres")) == seen[0][0]


@paid_only
def test_godot_standard_material_variant():
    folder = reset()
    atlas = make_atlas(["#C0C0C0"])
    atlas.godot_material = "STANDARD"
    atlas.export_godot = True
    bpy.ops.hueatlas.export_pack()
    with open(os.path.join(folder, "engine", "godot", "Pal.tres"), encoding="utf-8") as fh:
        tres = fh.read()
    assert tres.startswith('[gd_resource type="StandardMaterial3D"')
    assert "roughness_texture_channel = 1" in tres and "metallic_texture_channel = 2" in tres
    assert "texture_filter = 0" in tres
