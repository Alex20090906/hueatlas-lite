# SPDX-License-Identifier: GPL-3.0-or-later
"""Gradient swatches and linear projection (full version)."""

import bpy
import numpy as np
from helpers import add_strip, face_centroids, image_array, make_atlas, paid_only, reset, sample, select_only

from hueatlas import core
from hueatlas.meshio import MeshData


@paid_only
def test_gradient_projection_along_x():
    reset()
    atlas = make_atlas(["#808080"], cell=16, cols=4)
    sw = core.add_swatch(bpy.context.scene, atlas, name="Ramp", kind="GRADIENT")
    with core.suspended():
        sw.span = 4
        sw.stops[0].color = (0.0, 0.0, 0.0)
        sw.stops[1].color = (1.0, 1.0, 1.0)
    layout = core.sync(bpy.context.scene, atlas)
    assert layout.boxes[sw.uid].w == 64
    obj = add_strip(10)
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    r = bpy.ops.hueatlas.gradient_project(axis="X", space="GLOBAL", swatch_uid=sw.uid)
    assert r == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")

    md = MeshData(obj.data)
    xs = md.loop_coords()[:, 0]
    us = md.uv[:, 0]
    order = np.argsort(xs, kind="stable")
    assert (np.diff(us[order]) >= -1e-7).all(), "u must grow with x"
    for x in np.unique(xs):
        assert np.ptp(us[xs == x]) < 1e-7
    inner = layout.uv_inner(sw.uid)
    assert abs(us.min() - inner.x0) < 1e-4 and abs(us.max() - inner.x1) < 1e-4
    arr = image_array(atlas.image)
    lum = [int(sample(arr, *c)[:3].astype(int).sum()) for c in face_centroids(obj.data)]
    order_faces = np.argsort([np.mean(xs[md.loop_mask(np.arange(md.n_faces) == f)]) for f in range(md.n_faces)])
    lum_sorted = [lum[f] for f in order_faces]
    assert all(b > a for a, b in zip(lum_sorted, lum_sorted[1:])), lum_sorted


@paid_only
def test_oklab_midpoint_differs_from_srgb():
    from hueatlas import raster

    stops = [(0.0, (1.0, 0.0, 0.0)), (1.0, (0.0, 0.0, 1.0))]
    a = raster.gradient_colors(stops, [0.5], raster.SRGB)[0]
    b = raster.gradient_colors(stops, [0.5], raster.OKLAB)[0]
    assert np.allclose(a, [0.5, 0.0, 0.5])
    assert not np.allclose(a, b, atol=0.02)
    ends = raster.gradient_colors(stops, [0.0, 1.0], raster.OKLAB)
    assert np.allclose(ends, [[1, 0, 0], [0, 0, 1]], atol=1e-6)
