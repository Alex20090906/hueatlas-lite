# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar panels. The same panels appear in the 3D Viewport and the
UV/Image Editor (tab "HueAtlas"), so the tool is easy to find in both."""

import bpy
from bpy.types import UIList

from . import core, edition
from . import layout as L


class HUEATLAS_UL_atlases(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        layout.prop(item, "name", text="", emboss=False, icon="COLOR")


class HUEATLAS_UL_swatches(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        chips = row.row(align=True)
        chips.scale_x = 0.6
        if edition.PAID and item.kind == "GRADIENT" and len(item.stops) >= 2:
            ordered = sorted(item.stops, key=lambda s: s.position)
            chips.prop(ordered[0], "color", text="")
            chips.prop(ordered[-1], "color", text="")
        else:
            chips.prop(item, "color", text="")
        row.prop(item, "name", text="", emboss=False)
        if item.kind == "GRADIENT":
            row.label(text="", icon="IPO_LINEAR")
        if edition.PAID and item.emission_strength > 0:
            row.label(text="", icon="LIGHT")


class HUEATLAS_UL_stops(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        sub = row.row()
        sub.scale_x = 0.6
        sub.prop(item, "color", text="")
        row.prop(item, "position", text="", slider=True)


class HUEATLAS_UL_themes(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        layout.prop(item, "name", text="", emboss=False, icon="COLOR")


class HUEATLAS_UL_audit(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=item.code, icon="ERROR")
        where = f"{item.object_name} #{item.face_index}" if item.face_index >= 0 else item.mesh_name
        row.label(text=where)
        op = row.operator("hueatlas.audit_select", text="", icon="RESTRICT_SELECT_OFF")
        op.index = index


# -- panels -------------------------------------------------------------------------


class _Base:
    bl_region_type = "UI"
    bl_category = "HueAtlas"


class HUEATLAS_PT_atlas(_Base):
    bl_label = "Atlas"

    def draw_header(self, context):
        self.layout.label(text="", icon="COLOR")

    def draw(self, context):
        layout = self.layout
        s = context.scene.hueatlas
        if edition.PAID:
            row = layout.row()
            row.template_list("HUEATLAS_UL_atlases", "", s, "atlases", s, "active_atlas_index", rows=2)
            col = row.column(align=True)
            col.operator("hueatlas.atlas_add", text="", icon="ADD")
            col.operator("hueatlas.atlas_remove", text="", icon="REMOVE")
        atlas = core.active_atlas(context.scene)
        if atlas is None:
            layout.operator("hueatlas.atlas_add", icon="ADD")
            return
        if not edition.PAID:
            layout.prop(atlas, "name")
        col = layout.column(align=True)
        col.template_ID(atlas, "image", open="image.open")
        col.prop(atlas, "output_dir")

        col = layout.column(align=True)
        col.prop(atlas, "cell_px")
        col.prop(atlas, "columns")
        if edition.PAID:
            col.prop(atlas, "padding_mode", text="Padding")
            if atlas.padding_mode == "MIPSAFE":
                col.prop(atlas, "mip_level")
            else:
                col.prop(atlas, "padding_px")
            box = layout.box()
            box.prop(atlas, "use_region")
            if atlas.use_region:
                grid = box.grid_flow(columns=2, align=True)
                grid.prop(atlas, "region_x")
                grid.prop(atlas, "region_y")
                grid.prop(atlas, "region_w")
                grid.prop(atlas, "region_h")
            layout.prop(atlas, "interpolation")
        else:
            col.label(text="Gutter: 2 px")
        layout.prop(atlas, "filter_mode")

        try:
            lay = core.compute_layout(atlas, reload=False)
            info = f"{lay.width}x{lay.height} px, {len(atlas.swatches)}/{lay.capacity()} cells, clean mip {lay.clean_mip_level()}"
            layout.label(text=info, icon="INFO")
        except L.LayoutError as exc:
            layout.label(text=str(exc), icon="ERROR")
        if atlas.status:
            box = layout.box()
            for line in _wrap(atlas.status, 46):
                box.label(text=line)
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("hueatlas.atlas_generate", icon="FILE_REFRESH")
        row.operator("hueatlas.material_build", icon="MATERIAL")
        if edition.PAID:
            layout.operator("hueatlas.repair_uvs", icon="UV_SYNC_SELECT")


def _wrap(text, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(line)
    return lines


class HUEATLAS_PT_swatches(_Base):
    bl_label = "Swatches"

    @classmethod
    def poll(cls, context):
        return core.active_atlas(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        atlas = core.active_atlas(context.scene)
        row = layout.row()
        row.template_list("HUEATLAS_UL_swatches", "", atlas, "swatches", atlas, "active_swatch_index", rows=6)
        col = row.column(align=True)
        col.operator("hueatlas.swatch_add", text="", icon="ADD").kind = "FLAT"
        if edition.PAID:
            col.operator("hueatlas.swatch_add", text="", icon="IPO_LINEAR").kind = "GRADIENT"
        col.operator("hueatlas.swatch_remove", text="", icon="REMOVE")
        if edition.PAID:
            col.separator()
            col.operator("hueatlas.swatch_move", text="", icon="TRIA_UP").direction = "UP"
            col.operator("hueatlas.swatch_move", text="", icon="TRIA_DOWN").direction = "DOWN"
        row = layout.row(align=True)
        row.operator("hueatlas.palette_import", text="Import", icon="IMPORT")
        row.operator("hueatlas.palette_export", text="Export", icon="EXPORT")

        sw = core.active_swatch(atlas)
        if sw is None:
            return
        box = layout.box()
        box.prop(sw, "name")
        if edition.PAID:
            box.prop(sw, "kind", expand=True)
        if edition.PAID and sw.kind == "GRADIENT":
            box.prop(sw, "span")
            row = box.row()
            row.template_list("HUEATLAS_UL_stops", "", sw, "stops", sw, "active_stop_index", rows=3)
            c = row.column(align=True)
            c.operator("hueatlas.stop_add", text="", icon="ADD")
            c.operator("hueatlas.stop_remove", text="", icon="REMOVE")
        else:
            box.prop(sw, "color")
        if edition.PAID:
            sub = box.column(align=True)
            sub.prop(sw, "roughness", slider=True)
            sub.prop(sw, "metallic", slider=True)
            sub.prop(sw, "emission_color")
            sub.prop(sw, "emission_strength")


class HUEATLAS_PT_assign(_Base):
    bl_label = "Assign"

    @classmethod
    def poll(cls, context):
        return core.active_atlas(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.2
        if context.mode == "EDIT_MESH":
            col.operator("hueatlas.assign_faces", icon="FACESEL")
            col.operator("hueatlas.pick_from_face", icon="EYEDROPPER")
        else:
            col.operator("hueatlas.assign_objects", icon="OBJECT_DATA")
        col.operator("hueatlas.select_by_swatch", icon="RESTRICT_SELECT_OFF")
        s = context.scene.hueatlas
        if edition.PAID:
            box = layout.box()
            box.label(text="Gradient projection", icon="IPO_LINEAR")
            row = box.row(align=True)
            row.prop(s, "gradient_axis", expand=True)
            box.prop(s, "gradient_space")
            box.prop(s, "gradient_flip")
            box.operator("hueatlas.gradient_project", icon="IPO_LINEAR")


class HUEATLAS_PT_themes(_Base):
    bl_label = "Themes"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return edition.PAID and core.active_atlas(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        atlas = core.active_atlas(context.scene)
        row = layout.row()
        row.template_list("HUEATLAS_UL_themes", "", atlas, "themes", atlas, "active_theme_index", rows=3)
        col = row.column(align=True)
        col.operator("hueatlas.theme_add", text="", icon="ADD")
        col.operator("hueatlas.theme_remove", text="", icon="REMOVE")
        row = layout.row(align=True)
        row.operator("hueatlas.theme_apply", icon="CHECKMARK")
        row.operator("hueatlas.theme_capture", icon="FILE_TICK")
        layout.operator("hueatlas.theme_export", icon="EXPORT")


class HUEATLAS_PT_export(_Base):
    bl_label = "Engine Export"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return core.active_atlas(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        if not edition.PAID:
            layout.label(text="glTF: File > Export > glTF 2.0", icon="INFO")
            return
        atlas = core.active_atlas(context.scene)
        col = layout.column(align=True)
        col.prop(atlas, "export_godot")
        col.prop(atlas, "export_unity")
        col.prop(atlas, "export_unreal")
        layout.prop(atlas, "export_dir")
        if atlas.export_godot:
            box = layout.box()
            box.prop(atlas, "godot_prefix")
            box.prop(atlas, "godot_material")
        layout.operator("hueatlas.export_pack", icon="EXPORT")
        layout.label(text="glTF: File > Export > glTF 2.0", icon="INFO")


class HUEATLAS_PT_audit(_Base):
    bl_label = "Audit"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return core.active_atlas(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        s = context.scene.hueatlas
        layout.operator("hueatlas.audit", icon="VIEWZOOM")
        if s.audit_summary:
            layout.label(text=s.audit_summary)
        if len(s.audit_items):
            layout.template_list("HUEATLAS_UL_audit", "", s, "audit_items", s, "audit_index", rows=4)


# -- registration ------------------------------------------------------------------------

LISTS = (HUEATLAS_UL_atlases, HUEATLAS_UL_swatches, HUEATLAS_UL_stops, HUEATLAS_UL_themes, HUEATLAS_UL_audit)
PANELS = (HUEATLAS_PT_atlas, HUEATLAS_PT_swatches, HUEATLAS_PT_assign, HUEATLAS_PT_themes,
          HUEATLAS_PT_export, HUEATLAS_PT_audit)
SPACES = (("VIEW_3D", "view3d"), ("IMAGE_EDITOR", "image"))

_registered = []


def _make(base, space, suffix):
    name = f"{base.__name__}_{suffix}"
    return type(name, (base, bpy.types.Panel), {"bl_idname": name, "bl_space_type": space})


def register():
    for cls in LISTS:
        bpy.utils.register_class(cls)
        _registered.append(cls)
    for space, suffix in SPACES:
        for base in PANELS:
            cls = _make(base, space, suffix)
            bpy.utils.register_class(cls)
            _registered.append(cls)


def unregister():
    while _registered:
        bpy.utils.unregister_class(_registered.pop())
