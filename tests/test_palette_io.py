# SPDX-License-Identifier: GPL-3.0-or-later
"""Palette import and export: GIMP .gpl, hex lists, HueAtlas JSON."""

import json
import os

import bpy
from helpers import PAID, reset

from hueatlas import core, raster

GPL = """GIMP Palette
Name: Test
Columns: 4
#
255   0   0\tRed
  0 255   0\tGreen
  0   0 255\tBlue
255 255   0\tYellow
  0 255 255\tCyan
255   0 255\tMagenta
 12  34  56\tNavy
200 100  50\tRust
  1   2   3\tAlmost black
254 253 252\tAlmost white
128 128 128\tGrey
 64 128 192\tSteel
"""


def test_import_gpl_exact():
    folder = reset()
    path = os.path.join(folder, "test.gpl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(GPL)
    assert bpy.ops.hueatlas.palette_import(filepath=path) == {"FINISHED"}
    atlas = core.active_atlas(bpy.context.scene)
    assert len(atlas.swatches) == 12
    lines = [ln for ln in GPL.splitlines()[4:] if ln.strip()]
    for sw, line in zip(atlas.swatches, lines):
        want = [int(v) for v in line.split()[:3]]
        assert list(raster.to_u8(sw.color)) == want, (sw.name, list(raster.to_u8(sw.color)), want)
    assert atlas.swatches[8].name == "Almost black"


def test_import_hex_list():
    folder = reset()
    path = os.path.join(folder, "colors.hex")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#112233, 445566\n#ABC\n")
    bpy.ops.hueatlas.palette_import(filepath=path)
    atlas = core.active_atlas(bpy.context.scene)
    assert [raster.to_hex(sw.color) for sw in atlas.swatches] == ["#112233", "#445566", "#AABBCC"]


def test_json_round_trip():
    folder = reset()
    bpy.ops.hueatlas.atlas_add()
    atlas = core.active_atlas(bpy.context.scene)
    sw = atlas.swatches[2]
    sw.roughness = 0.25
    sw.metallic = 1.0
    sw.emission_color = (1.0, 0.0, 0.0)
    sw.emission_strength = 3.0
    if PAID:
        bpy.ops.hueatlas.swatch_add(kind="GRADIENT")
    before = core.palette_to_json(atlas)["swatches"]
    path = os.path.join(folder, "pal.json")
    assert bpy.ops.hueatlas.palette_export(filepath=path) == {"FINISHED"}
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["format"] == "hueatlas-palette"
    bpy.ops.hueatlas.atlas_remove()
    assert len(bpy.context.scene.hueatlas.atlases) == 0
    assert bpy.ops.hueatlas.palette_import(filepath=path) == {"FINISHED"}
    again = core.active_atlas(bpy.context.scene)
    after = core.palette_to_json(again)["swatches"]
    assert after == before, f"\n{before}\n!=\n{after}"
