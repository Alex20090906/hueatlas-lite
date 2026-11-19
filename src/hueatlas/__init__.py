# SPDX-License-Identifier: GPL-3.0-or-later
"""HueAtlas: palette atlas texturing that exports clean to game engines.

Copyright (C) 2026 Swatchworks. Licensed under GPL-3.0-or-later.
"""

import bpy

from . import edition, handlers, ops, props, ui


class HUEATLAS_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"{edition.PRODUCT}: palette atlas texturing for game engines")
        layout.label(text="Open the sidebar (N) in the 3D Viewport or UV Editor, tab 'HueAtlas'.")


def register():
    edition.claim_registration()
    props.register()
    bpy.utils.register_class(HUEATLAS_AP_preferences)
    ops.register()
    if edition.PAID:
        edition.paid_module().register()
    ui.register()
    handlers.register()


def unregister():
    handlers.unregister()
    ui.unregister()
    if edition.PAID:
        edition.paid_module().unregister()
    ops.unregister()
    if "bl_rna" in HUEATLAS_AP_preferences.__dict__:
        bpy.utils.unregister_class(HUEATLAS_AP_preferences)
    props.unregister()
    edition.release_registration()
