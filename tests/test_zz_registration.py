# SPDX-License-Identifier: GPL-3.0-or-later
"""Unregister and register again; data in the scene must survive. Runs last."""

import sys

import bpy
from helpers import make_atlas, reset


def test_reregister_keeps_data():
    reset()
    make_atlas(["#123456", "#654321"])
    addon = sys.modules["hueatlas"]
    addon.unregister()
    assert not hasattr(bpy.types.Scene, "hueatlas")
    addon.register()
    s = bpy.context.scene.hueatlas
    assert len(s.atlases) == 1 and len(s.atlases[0].swatches) == 2
    assert s.atlases[0].swatches[0].name == "S0"
