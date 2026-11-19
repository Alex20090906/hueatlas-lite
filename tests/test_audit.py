# SPDX-License-Identifier: GPL-3.0-or-later
"""Atlas audit."""

import json
import os

import bpy
from helpers import PAID, add_cube, make_atlas, reset, select_only

from hueatlas import core
from hueatlas.meshio import MeshData


def test_audit_codes():
    folder = reset()
    atlas = make_atlas(["#FF8000", "#00FF00", "#0000FF", "#FFFFFF"], cell=16, cols=4)
    cube = add_cube()
    select_only([cube])
    bpy.ops.hueatlas.assign_objects(swatch_uid=atlas.swatches[0].uid)
    layout = core.compute_layout(atlas)
    md = MeshData(cube.data)
    c0 = layout.uv_center(atlas.swatches[0].uid)
    c1 = layout.uv_center(atlas.swatches[1].uid)
    s0, n0 = int(md.loop_start[0]), int(md.loop_total[0])
    md.uv[s0:s0 + n0] = [c0, c1, c1, c0][:n0]
    md.uids[1] = 0
    s2, n2 = int(md.loop_start[2]), int(md.loop_total[2])
    md.uv[s2:s2 + n2, 0] = 1.3
    md.write(uids=True, uv=True)
    if PAID:
        atlas.orm_image.colorspace_settings.name = "sRGB"

    report = os.path.join(folder, "audit.json")
    assert bpy.ops.hueatlas.audit(report_path=report) == {"FINISHED"}
    with open(report, encoding="utf-8") as fh:
        issues = json.load(fh)["issues"]
    got = sorted((i["code"], i["face"]) for i in issues)
    want = [("OUT_OF_ATLAS", 2), ("STRADDLE", 0), ("UNASSIGNED", 1)]
    if PAID:
        want.append(("DATA_SRGB", -1))
    assert got == sorted(want), got
    s = bpy.context.scene.hueatlas
    assert len(s.audit_items) == len(want)
    idx = next(i for i, it in enumerate(s.audit_items) if it.code == "STRADDLE")
    assert bpy.ops.hueatlas.audit_select(index=idx) == {"FINISHED"}
    assert bpy.context.mode == "EDIT_MESH"
    bpy.ops.object.mode_set(mode="OBJECT")
    sel = MeshData(cube.data).select
    assert sel[0] and sel.sum() == 1


def test_clean_scene_has_no_issues():
    reset()
    make_atlas(["#FF8000", "#00FF00"])
    cube = add_cube()
    select_only([cube])
    bpy.ops.hueatlas.assign_objects()
    bpy.ops.hueatlas.audit()
    assert bpy.context.scene.hueatlas.audit_summary == "No issues found", bpy.context.scene.hueatlas.audit_summary
