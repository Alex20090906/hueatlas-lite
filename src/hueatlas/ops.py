# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators available in both editions."""

import json
import os

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import core, edition
from . import layout as L
from .meshio import MeshData


def _atlas_or_report(op, context):
    atlas = core.active_atlas(context.scene)
    if atlas is None:
        op.report({"WARNING"}, "Create a palette atlas first")
    return atlas


def _sync_or_report(op, scene, atlas, **kw):
    try:
        return core.sync(scene, atlas, **kw)
    except core.SYNC_ERRORS as exc:
        atlas.status = str(exc)
        op.report({"ERROR"}, str(exc))
        return None


class HUEATLAS_OT_atlas_add(bpy.types.Operator):
    bl_idname = "hueatlas.atlas_add"
    bl_label = "New Palette Atlas"
    bl_description = "Create a palette atlas with a starter set of swatches"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="Palette")
    defaults: BoolProperty(name="Starter swatches", default=True)

    def execute(self, context):
        s = context.scene.hueatlas
        if not edition.PAID and len(s.atlases) >= 1:
            edition.require_paid(self, "More than one atlas per file")
            return {"CANCELLED"}
        atlas = core.create_atlas(context.scene, self.name, defaults=self.defaults)
        if _sync_or_report(self, context.scene, atlas) is None:
            return {"CANCELLED"}
        core.build_material(atlas)
        return {"FINISHED"}


class HUEATLAS_OT_atlas_remove(bpy.types.Operator):
    bl_idname = "hueatlas.atlas_remove"
    bl_label = "Remove Atlas"
    bl_description = "Remove the active atlas from the list (images, material and faces are kept)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.hueatlas
        if not s.atlases:
            return {"CANCELLED"}
        s.atlases.remove(s.active_atlas_index)
        s.active_atlas_index = max(0, min(s.active_atlas_index, len(s.atlases) - 1))
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class HUEATLAS_OT_atlas_generate(bpy.types.Operator):
    bl_idname = "hueatlas.atlas_generate"
    bl_label = "Generate / Update"
    bl_description = "Write the atlas images and bring every assigned face in line with the layout"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        atlas = _atlas_or_report(self, context)
        if atlas is None:
            return {"CANCELLED"}
        layout = _sync_or_report(self, context.scene, atlas, scan=True)
        if layout is None:
            return {"CANCELLED"}
        core.ensure_material(atlas)
        if layout.params.region is not None:
            where = f"region of {atlas.image.name}"
        else:
            where = core.image_file(atlas, "Albedo") or "packed in the .blend (save the file to write PNGs)"
        self.report({"INFO"}, f"Atlas {layout.width}x{layout.height}: {where}")
        return {"FINISHED"}


class HUEATLAS_OT_material_build(bpy.types.Operator):
    bl_idname = "hueatlas.material_build"
    bl_label = "Build Material"
    bl_description = "Rebuild the atlas material node tree from scratch (glTF-ready wiring)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        atlas = _atlas_or_report(self, context)
        if atlas is None:
            return {"CANCELLED"}
        if atlas.image is None and _sync_or_report(self, context.scene, atlas) is None:
            return {"CANCELLED"}
        mat = core.build_material(atlas)
        self.report({"INFO"}, f"Material '{mat.name}' rebuilt")
        return {"FINISHED"}


class HUEATLAS_OT_swatch_add(bpy.types.Operator):
    bl_idname = "hueatlas.swatch_add"
    bl_label = "Add Swatch"
    bl_description = "Add a swatch after the active one"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(items=[("FLAT", "Flat", ""), ("GRADIENT", "Gradient", "")], default="FLAT")
    append: BoolProperty(name="Append at end", default=False)

    def execute(self, context):
        scene = context.scene
        atlas = _atlas_or_report(self, context)
        if atlas is None:
            return {"CANCELLED"}
        if self.kind == "GRADIENT" and not edition.require_paid(self, "Gradient swatches"):
            return {"CANCELLED"}
        if core.lite_append_blocked(scene, atlas, 1):
            self.report({"WARNING"}, "The atlas is full and growing it would move used cells: "
                                     f"{edition.LITE_MESSAGE}")
            return {"CANCELLED"}
        index = None
        if edition.PAID and not self.append and len(atlas.swatches):
            index = atlas.active_swatch_index + 1
        name = "Gradient" if self.kind == "GRADIENT" else f"Swatch {len(atlas.swatches) + 1}"
        sw = core.add_swatch(scene, atlas, name=name, kind=self.kind, index=index)
        uid = sw.uid
        if _sync_or_report(self, scene, atlas) is None:
            with core.suspended():
                atlas.swatches.remove(core.swatch_index(atlas, uid))
                atlas.active_swatch_index = max(0, len(atlas.swatches) - 1)
            core.sync_safe(scene, atlas)
            return {"CANCELLED"}
        return {"FINISHED"}


class HUEATLAS_OT_swatch_remove(bpy.types.Operator):
    bl_idname = "hueatlas.swatch_remove"
    bl_label = "Remove Swatch"
    bl_description = "Remove the active swatch. Faces that used it move to a fallback swatch"
    bl_options = {"REGISTER", "UNDO"}

    fallback_uid: IntProperty(name="Fallback swatch id", default=0,
                              description="0 picks the neighbouring swatch")

    def execute(self, context):
        scene = context.scene
        atlas = _atlas_or_report(self, context)
        if atlas is None or not len(atlas.swatches):
            return {"CANCELLED"}
        if len(atlas.swatches) == 1:
            self.report({"WARNING"}, "An atlas needs at least one swatch")
            return {"CANCELLED"}
        index = atlas.active_swatch_index
        sw = atlas.swatches[index]
        uid = sw.uid
        remaining = [s for s in atlas.swatches if s.uid != uid]
        try:
            new_layout = L.compute(core.params_of(atlas), core.slots_of(atlas, remaining))
        except L.LayoutError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        used = core.assigned_uids()

        if not edition.PAID:
            moved = L.moved_uids(core.load_snapshot(atlas), new_layout)
            if uid in used or (used & moved):
                edition.require_paid(self, "Removing a swatch that faces use, or one that moves used cells")
                return {"CANCELLED"}

        fallback = self.fallback_uid
        if fallback == uid or core.swatch_index(atlas, fallback) < 0:
            neighbour = index - 1 if index > 0 else index + 1
            fallback = atlas.swatches[neighbour].uid
        saved = core.capture_swatch(sw)
        with core.suspended():
            atlas.swatches.remove(index)
            atlas.active_swatch_index = max(0, min(index, len(atlas.swatches) - 1))
        try:
            core.sync(scene, atlas, rename={uid: fallback} if uid in used else None)
        except core.SYNC_ERRORS as exc:
            core.restore_swatch(scene, atlas, saved, index)
            core.sync_safe(scene, atlas)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if uid in used:
            self.report({"INFO"}, f"Faces moved to '{core.swatch_by_uid(atlas, fallback).name}'")
        return {"FINISHED"}


class HUEATLAS_OT_swatch_move(bpy.types.Operator):
    bl_idname = "hueatlas.swatch_move"
    bl_label = "Move Swatch"
    bl_description = "Reorder the active swatch. Assigned faces keep their colour"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])
    to_index: IntProperty(default=-1, options={"SKIP_SAVE"})

    def execute(self, context):
        if not edition.require_paid(self, "Reordering swatches"):
            return {"CANCELLED"}
        atlas = _atlas_or_report(self, context)
        if atlas is None:
            return {"CANCELLED"}
        i = atlas.active_swatch_index
        if self.to_index >= 0:
            j = min(self.to_index, len(atlas.swatches) - 1)
        else:
            j = i - 1 if self.direction == "UP" else i + 1
        if j < 0 or j >= len(atlas.swatches) or j == i:
            return {"CANCELLED"}
        with core.suspended():
            atlas.swatches.move(i, j)
            atlas.active_swatch_index = j
        if _sync_or_report(self, context.scene, atlas) is None:
            with core.suspended():
                atlas.swatches.move(j, i)
                atlas.active_swatch_index = i
            core.sync_safe(context.scene, atlas)
            return {"CANCELLED"}
        return {"FINISHED"}


def _active_uid(atlas, uid):
    if uid > 0 and core.swatch_index(atlas, uid) >= 0:
        return uid
    sw = core.active_swatch(atlas)
    return sw.uid if sw is not None else 0


def _assign(op, context, mode):
    scene = context.scene
    atlas = _atlas_or_report(op, context)
    if atlas is None:
        return {"CANCELLED"}
    uid = _active_uid(atlas, op.swatch_uid)
    if not uid:
        op.report({"WARNING"}, "The atlas has no swatches")
        return {"CANCELLED"}
    layout = _sync_or_report(op, scene, atlas)
    if layout is None:
        return {"CANCELLED"}
    objects = core.target_objects(context, mode)
    if not objects:
        op.report({"WARNING"}, "No mesh objects to assign to")
        return {"CANCELLED"}
    selected_only = mode == "EDIT"
    if edition.PAID and layout.kinds.get(uid) == L.GRADIENT:
        from .paid import gradient

        s = scene.hueatlas
        rv3d = getattr(context, "region_data", None)
        view = rv3d.view_matrix if rv3d is not None else None
        count = gradient.project(objects, atlas, uid, layout, s.gradient_axis, s.gradient_space,
                                 s.gradient_flip, view, selected_only=selected_only)
    else:
        count = core.assign_flat(objects, atlas, uid, layout, selected_only=selected_only)
    if not count:
        op.report({"WARNING"}, "Nothing selected")
        return {"CANCELLED"}
    op.report({"INFO"}, f"Assigned {count} faces to '{core.swatch_by_uid(atlas, uid).name}'")
    return {"FINISHED"}


class HUEATLAS_OT_assign_faces(bpy.types.Operator):
    bl_idname = "hueatlas.assign_faces"
    bl_label = "Assign to Selected Faces"
    bl_description = "Give the selected faces the active swatch (Edit Mode)"
    bl_options = {"REGISTER", "UNDO"}

    swatch_uid: IntProperty(default=0, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        return _assign(self, context, "EDIT")


class HUEATLAS_OT_assign_objects(bpy.types.Operator):
    bl_idname = "hueatlas.assign_objects"
    bl_label = "Assign to Selected Objects"
    bl_description = "Give every face of the selected objects the active swatch"
    bl_options = {"REGISTER", "UNDO"}

    swatch_uid: IntProperty(default=0, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        return _assign(self, context, "OBJECT")


class HUEATLAS_OT_select_by_swatch(bpy.types.Operator):
    bl_idname = "hueatlas.select_by_swatch"
    bl_label = "Select by Swatch"
    bl_description = "Select faces (Edit Mode) or objects (Object Mode) that use the active swatch"
    bl_options = {"REGISTER", "UNDO"}

    extend: BoolProperty(name="Extend", default=False)

    def execute(self, context):
        atlas = _atlas_or_report(self, context)
        sw = core.active_swatch(atlas)
        if sw is None:
            return {"CANCELLED"}
        if context.mode == "EDIT_MESH":
            count = core.faces_with_uid(core.target_objects(context, "EDIT"), sw.uid, self.extend)
            self.report({"INFO"}, f"{count} faces use '{sw.name}'")
            return {"FINISHED"}
        count = 0
        for obj in context.view_layer.objects:
            if obj.type != "MESH" or not obj.visible_get():
                continue
            md = MeshData(obj.data)
            hit = bool((md.uids == sw.uid).any()) if md.has_attr else False
            if hit or not self.extend:
                obj.select_set(hit)
            count += int(hit)
        self.report({"INFO"}, f"{count} objects use '{sw.name}'")
        return {"FINISHED"}


class HUEATLAS_OT_pick_from_face(bpy.types.Operator):
    bl_idname = "hueatlas.pick_from_face"
    bl_label = "Pick from Active Face"
    bl_description = "Make the swatch of the active face the active swatch"

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and context.edit_object is not None

    def execute(self, context):
        s = context.scene.hueatlas
        md = MeshData(context.edit_object.data)
        if md.active_face < 0 or not md.has_attr:
            self.report({"WARNING"}, "No active face with a swatch")
            return {"CANCELLED"}
        uid = int(md.uids[md.active_face])
        for ai, atlas in enumerate(s.atlases):
            i = core.swatch_index(atlas, uid)
            if i >= 0:
                s.active_atlas_index = ai
                atlas.active_swatch_index = i
                self.report({"INFO"}, f"Picked '{atlas.swatches[i].name}'")
                return {"FINISHED"}
        self.report({"WARNING"}, "The active face has no swatch")
        return {"CANCELLED"}


class HUEATLAS_OT_palette_import(bpy.types.Operator, ImportHelper):
    bl_idname = "hueatlas.palette_import"
    bl_label = "Import Palette"
    bl_description = "Import swatches from GIMP .gpl, a hex list, or HueAtlas .json"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.gpl;*.json;*.hex;*.txt", options={"HIDDEN"})
    new_atlas: BoolProperty(name="Into a new atlas", default=False)

    def execute(self, context):
        s = context.scene.hueatlas
        if self.new_atlas and len(s.atlases) and not edition.require_paid(self, "More than one atlas"):
            return {"CANCELLED"}
        try:
            atlas, count = core.import_palette(context.scene, self.filepath, self.new_atlas)
        except (OSError, ValueError, core.LiteBlocked) as exc:
            self.report({"ERROR"}, f"Could not import the palette: {exc}")
            return {"CANCELLED"}
        if _sync_or_report(self, context.scene, atlas) is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {count} swatches")
        return {"FINISHED"}


class HUEATLAS_OT_palette_export(bpy.types.Operator, ExportHelper):
    bl_idname = "hueatlas.palette_export"
    bl_label = "Export Palette"
    bl_description = "Save the active atlas palette as HueAtlas JSON"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        atlas = _atlas_or_report(self, context)
        if atlas is None:
            return {"CANCELLED"}
        try:
            with open(self.filepath, "w", encoding="utf-8") as fh:
                json.dump(core.palette_to_json(atlas), fh, indent=2)
        except OSError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Saved {self.filepath}")
        return {"FINISHED"}


class HUEATLAS_OT_audit(bpy.types.Operator):
    bl_idname = "hueatlas.audit"
    bl_label = "Run Audit"
    bl_description = "Check every mesh that uses the atlas before you export"

    report_path: StringProperty(name="JSON report", subtype="FILE_PATH", default="",
                                options={"SKIP_SAVE"})

    def execute(self, context):
        atlas = _atlas_or_report(self, context)
        if atlas is None:
            return {"CANCELLED"}
        try:
            issues = core.audit(context.scene, atlas)
        except L.LayoutError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        s = context.scene.hueatlas
        s.audit_items.clear()
        for issue in issues[:1000]:
            item = s.audit_items.add()
            item.code = issue["code"]
            item.object_name = issue["object"]
            item.mesh_name = issue["mesh"]
            item.face_index = issue["face"]
            item.message = issue["message"]
        counts = {}
        for issue in issues:
            counts[issue["code"]] = counts.get(issue["code"], 0) + 1
        s.audit_summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "No issues found"
        if self.report_path:
            path = bpy.path.abspath(self.report_path)
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"atlas": atlas.name, "edition": edition.EDITION, "issues": issues}, fh, indent=2)
        self.report({"INFO"} if not issues else {"WARNING"}, s.audit_summary)
        return {"FINISHED"}


class HUEATLAS_OT_audit_select(bpy.types.Operator):
    bl_idname = "hueatlas.audit_select"
    bl_label = "Select Issue"
    bl_description = "Select the face this issue points at"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    def execute(self, context):
        s = context.scene.hueatlas
        if not (0 <= self.index < len(s.audit_items)):
            return {"CANCELLED"}
        item = s.audit_items[self.index]
        obj = context.scene.objects.get(item.object_name)
        if obj is None or item.face_index < 0:
            self.report({"INFO"}, item.message)
            return {"CANCELLED"}
        if obj.name not in context.view_layer.objects or obj.hide_viewport or not obj.visible_get():
            self.report({"WARNING"}, f"'{obj.name}' is hidden, disabled in viewports or in an excluded "
                                     "collection. Show it first.")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        for f in bm.faces:
            f.select_set(False)
        if item.face_index < len(bm.faces):
            face = bm.faces[item.face_index]
            face.select_set(True)
            bm.faces.active = face
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        s.audit_index = self.index
        return {"FINISHED"}


classes = (
    HUEATLAS_OT_atlas_add,
    HUEATLAS_OT_atlas_remove,
    HUEATLAS_OT_atlas_generate,
    HUEATLAS_OT_material_build,
    HUEATLAS_OT_swatch_add,
    HUEATLAS_OT_swatch_remove,
    HUEATLAS_OT_swatch_move,
    HUEATLAS_OT_assign_faces,
    HUEATLAS_OT_assign_objects,
    HUEATLAS_OT_select_by_swatch,
    HUEATLAS_OT_pick_from_face,
    HUEATLAS_OT_palette_import,
    HUEATLAS_OT_palette_export,
    HUEATLAS_OT_audit,
    HUEATLAS_OT_audit_select,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        if "bl_rna" in cls.__dict__:
            bpy.utils.unregister_class(cls)
