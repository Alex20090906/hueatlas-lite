# SPDX-License-Identifier: GPL-3.0-or-later
"""Data stored in the .blend: Scene.hueatlas.

All properties are read and written as RNA attributes (never with
item["name"]), because Blender 5.0 changed how ID properties work.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _owner_atlas(item):
    scene = item.id_data
    if not isinstance(scene, bpy.types.Scene):
        return scene, None
    ptr = item.as_pointer()
    for atlas in scene.hueatlas.atlases:
        if atlas.as_pointer() == ptr:
            return scene, atlas
        for sw in atlas.swatches:
            if sw.as_pointer() == ptr:
                return scene, atlas
            for st in sw.stops:
                if st.as_pointer() == ptr:
                    return scene, atlas
    return scene, None


def _on_change(self, _context):
    from . import core

    if core.updates_suspended():
        return
    scene, atlas = _owner_atlas(self)
    if atlas is not None:
        core.sync_safe(scene, atlas)


def _on_kind(self, context):
    from . import core

    if self.kind == "GRADIENT" and len(self.stops) == 0:
        core.seed_stops(self)
    _on_change(self, context)


def _on_image(self, context):
    from . import core

    if core.updates_suspended():
        return
    scene, atlas = _owner_atlas(self)
    if atlas is None:
        return
    if atlas.use_region or atlas.image is None or core.owns_image(atlas, atlas.image, "Albedo"):
        core.sync_safe(scene, atlas)
    else:
        atlas.status = (
            "This image is not managed by HueAtlas. Turn on Region to place the palette inside it; "
            "Generate / Update without Region writes the atlas's own image."
        )


def _on_name(self, context):
    from . import core

    if core.updates_suspended():
        return
    scene, atlas = _owner_atlas(self)
    if atlas is None:
        return
    unique = core.unique_atlas_name(self.name, exclude=atlas)
    if unique != self.name:
        with core.suspended():
            self.name = unique
    core.sync_safe(scene, atlas)


KIND_ITEMS = [
    ("FLAT", "Flat", "One solid colour", "SNAP_FACE", 0),
    ("GRADIENT", "Gradient", "A colour ramp across several cells", "IPO_LINEAR", 1),
]


class HUEATLAS_PG_stop(PropertyGroup):
    position: FloatProperty(name="Position", min=0.0, max=1.0, default=0.0, update=_on_change)
    color: FloatVectorProperty(
        name="Color", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(0.5, 0.5, 0.5), update=_on_change,
    )


class HUEATLAS_PG_swatch(PropertyGroup):
    uid: IntProperty(name="ID", default=0, description="Stable id stored on faces")
    name: StringProperty(name="Name", default="Swatch")
    kind: EnumProperty(name="Kind", items=KIND_ITEMS, default="FLAT", update=_on_kind)
    color: FloatVectorProperty(
        name="Color", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(0.8, 0.8, 0.8), update=_on_change,
    )
    stops: CollectionProperty(type=HUEATLAS_PG_stop)
    active_stop_index: IntProperty(default=0)
    span: IntProperty(
        name="Span", description="How many cells the gradient covers", default=4,
        min=1, max=64, update=_on_change,
    )
    roughness: FloatProperty(name="Roughness", min=0.0, max=1.0, default=0.5, update=_on_change)
    metallic: FloatProperty(name="Metallic", min=0.0, max=1.0, default=0.0, update=_on_change)
    emission_color: FloatVectorProperty(
        name="Emission", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0), update=_on_change,
    )
    emission_strength: FloatProperty(
        name="Strength", min=0.0, soft_max=20.0, default=0.0, update=_on_change,
    )


class HUEATLAS_PG_theme(PropertyGroup):
    name: StringProperty(name="Name", default="Theme")
    data: StringProperty(name="Data", default="{}", options={"HIDDEN"})


class HUEATLAS_PG_audit_item(PropertyGroup):
    code: StringProperty()
    object_name: StringProperty()
    mesh_name: StringProperty()
    face_index: IntProperty(default=-1)
    message: StringProperty()


class HUEATLAS_PG_atlas(PropertyGroup):
    name: StringProperty(name="Name", default="Palette", update=_on_name)
    key: StringProperty(default="", options={"HIDDEN"}, description="Stable id that marks this atlas's images")
    image: PointerProperty(
        type=bpy.types.Image, name="Image", update=_on_image,
        description="The atlas image. Pick your own image only together with Region",
    )
    orm_image: PointerProperty(type=bpy.types.Image, name="ORM Image")
    emission_image: PointerProperty(type=bpy.types.Image, name="Emission Image")
    material: PointerProperty(type=bpy.types.Material, name="Material")
    output_dir: StringProperty(
        name="Folder", subtype="DIR_PATH", default="//textures/",
        description="Where atlas images are written. '//' means next to the .blend",
    )
    cell_px: IntProperty(
        name="Cell px", default=16, min=1, max=1024, update=_on_change,
        description="Size of one swatch cell in pixels",
    )
    columns: IntProperty(name="Columns", default=8, min=1, max=256, update=_on_change)
    padding_mode: EnumProperty(
        name="Padding",
        items=[
            ("FIXED", "Fixed", "A fixed gutter in pixels"),
            ("MIPSAFE", "Mip-safe", "Gutters and cells aligned so mip levels stay clean"),
        ],
        default="FIXED",
        update=_on_change,
    )
    padding_px: IntProperty(name="Gutter px", default=2, min=0, max=64, update=_on_change)
    mip_level: IntProperty(
        name="Clean mip level", default=2, min=0, max=6, update=_on_change,
        description="Mip level that must stay free of colour bleeding",
    )
    use_region: BoolProperty(
        name="Region", default=False, update=_on_change,
        description="Keep the palette inside a rectangle of an existing 8-bit image",
    )
    region_x: IntProperty(name="X", default=0, min=0, update=_on_change)
    region_y: IntProperty(name="Y", default=0, min=0, update=_on_change)
    region_w: IntProperty(name="Width", default=128, min=1, update=_on_change)
    region_h: IntProperty(name="Height", default=128, min=1, update=_on_change)
    interpolation: EnumProperty(
        name="Gradient space",
        items=[
            ("SRGB", "sRGB", "Blend the stored colour values directly"),
            ("OKLAB", "OKLab", "Perceptually even blending"),
        ],
        default="SRGB",
        update=_on_change,
    )
    filter_mode: EnumProperty(
        name="Filter",
        items=[
            ("AUTO", "Auto", "Nearest unless the atlas is mip-safe to level 2 or more"),
            ("NEAREST", "Nearest", "Closest texel, no mipmaps"),
            ("LINEAR", "Linear + mipmaps", "Smooth filtering with mipmaps"),
        ],
        default="AUTO",
        update=_on_change,
    )
    swatches: CollectionProperty(type=HUEATLAS_PG_swatch)
    active_swatch_index: IntProperty(default=0)
    themes: CollectionProperty(type=HUEATLAS_PG_theme)
    active_theme_index: IntProperty(default=0)
    layout_snapshot: StringProperty(default="", options={"HIDDEN"})
    layout_history: StringProperty(default="{}", options={"HIDDEN"})
    layout_rev: IntProperty(default=0, options={"HIDDEN"})
    status: StringProperty(default="")

    export_dir: StringProperty(name="Folder", subtype="DIR_PATH", default="//engine/")
    export_godot: BoolProperty(name="Godot 4", default=True)
    export_unity: BoolProperty(name="Unity 6 URP", default=False)
    export_unreal: BoolProperty(name="Unreal 5", default=False)
    godot_prefix: StringProperty(name="res:// path", default="res://art/palette/")
    godot_material: EnumProperty(
        name="Godot material",
        items=[
            ("ORM", "ORMMaterial3D", "One ORM texture"),
            ("STANDARD", "StandardMaterial3D", "Roughness and metallic read from ORM channels"),
        ],
        default="ORM",
    )


class HUEATLAS_PG_settings(PropertyGroup):
    atlases: CollectionProperty(type=HUEATLAS_PG_atlas)
    active_atlas_index: IntProperty(default=0)
    next_uid: IntProperty(default=1, options={"HIDDEN"})
    audit_items: CollectionProperty(type=HUEATLAS_PG_audit_item)
    audit_index: IntProperty(default=0)
    audit_summary: StringProperty(default="")
    gradient_axis: EnumProperty(
        name="Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="Z",
    )
    gradient_space: EnumProperty(
        name="Space",
        items=[
            ("GLOBAL", "Global", "World coordinates"),
            ("LOCAL", "Local", "Object coordinates"),
            ("VIEW", "View", "Screen axes of the current view"),
        ],
        default="GLOBAL",
    )
    gradient_flip: BoolProperty(name="Flip", default=False)


classes = (
    HUEATLAS_PG_stop,
    HUEATLAS_PG_swatch,
    HUEATLAS_PG_theme,
    HUEATLAS_PG_audit_item,
    HUEATLAS_PG_atlas,
    HUEATLAS_PG_settings,
)


def owner_tag(package: str) -> str:
    """Description of Scene.hueatlas; it records which edition registered it."""
    return f"HueAtlas data ({package})"


def registered_owner():
    prop = bpy.types.Scene.bl_rna.properties.get("hueatlas")
    return None if prop is None else prop.description


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hueatlas = PointerProperty(type=HUEATLAS_PG_settings, description=owner_tag(__package__))


def unregister():
    if registered_owner() == owner_tag(__package__):
        del bpy.types.Scene.hueatlas
    for cls in reversed(classes):
        if "bl_rna" in cls.__dict__:
            bpy.utils.unregister_class(cls)
