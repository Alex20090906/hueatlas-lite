# SPDX-License-Identifier: GPL-3.0-or-later
"""Core logic shared by operators, UI and tests.

sync() is the single entry point after any change. It computes the layout,
writes the images first (so a disk error changes nothing else), then records
a new layout revision and moves every face whose stored revision is stale
(full version). Because each face records the revision its UVs were written
for, remapping is idempotent: running sync twice, after an undo, or after a
failed write never moves a face twice.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager

import bpy
import numpy as np

from . import edition, png, raster
from . import layout as L
from .meshio import ATTR, MeshData, editable_meshes, ensure_material_slot, material_indices

# A balanced starter palette for low-poly kits: darks, lights, warm, cool.
DEFAULT_COLORS = [
    ("Ink", "#2B2D42"),
    ("Paper", "#EDF2F4"),
    ("Brick", "#C8553D"),
    ("Amber", "#F28F3B"),
    ("Sand", "#F6D186"),
    ("Moss", "#588157"),
    ("Lagoon", "#2A9D8F"),
    ("Sky", "#4D96D9"),
]

NEW_SWATCH_COLORS = [
    "#E76F51", "#F4A261", "#E9C46A", "#8AB17D", "#2A9D8F", "#264653",
    "#6D597A", "#B56576", "#EAAC8B", "#9A8C98", "#4A4E69", "#C9ADA7",
]

HISTORY_LIMIT = 48
OWNER_KEY = "hueatlas_owner"
ROLE_KEY = "hueatlas_role"
LOSSY_FORMATS = {"JPEG", "JPEG2000", "WEBP"}


class LiteBlocked(Exception):
    """The lite edition (no remap) kept a layout because the change would move assigned cells."""


SYNC_ERRORS = (L.LayoutError, LiteBlocked, OSError, RuntimeError)


# -- update suspension ----------------------------------------------------------

_suspend_depth = 0


def updates_suspended() -> bool:
    return _suspend_depth > 0


@contextmanager
def suspended():
    global _suspend_depth
    _suspend_depth += 1
    try:
        yield
    finally:
        _suspend_depth -= 1


# -- access helpers --------------------------------------------------------------


def active_atlas(scene):
    s = scene.hueatlas
    if 0 <= s.active_atlas_index < len(s.atlases):
        return s.atlases[s.active_atlas_index]
    return None


def active_swatch(atlas):
    if atlas is None:
        return None
    if 0 <= atlas.active_swatch_index < len(atlas.swatches):
        return atlas.swatches[atlas.active_swatch_index]
    return None


def swatch_index(atlas, uid: int) -> int:
    for i, sw in enumerate(atlas.swatches):
        if sw.uid == uid:
            return i
    return -1


def swatch_by_uid(atlas, uid: int):
    i = swatch_index(atlas, uid)
    return atlas.swatches[i] if i >= 0 else None


def atlas_uids(atlas) -> set:
    return {sw.uid for sw in atlas.swatches}


def all_atlases():
    for scene in bpy.data.scenes:
        if hasattr(scene, "hueatlas"):
            for atlas in scene.hueatlas.atlases:
                yield scene, atlas


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", text.strip())
    return cleaned.strip("._") or "Palette"


def unique_atlas_name(name: str, exclude=None) -> str:
    """A name whose file stem is unique (case-insensitive) across all scenes."""
    taken = {safe_name(a.name).casefold() for _s, a in all_atlases()
             if exclude is None or a.as_pointer() != exclude.as_pointer()}
    base, candidate, n = name, name, 1
    while safe_name(candidate).casefold() in taken:
        n += 1
        candidate = f"{base}.{n:03d}"
    return candidate


def file_uids_in_use() -> set:
    used = {sw.uid for _s, a in all_atlases() for sw in a.swatches}
    for me in editable_meshes():
        md = MeshData(me)
        used.update(int(u) for u in np.unique(md.uids) if u > 0)
    return used


def new_uid(scene, avoid=None) -> int:
    """A swatch id unique in the whole file (all scenes)."""
    top = 1
    for sc, a in all_atlases():
        top = max(top, sc.hueatlas.next_uid, *(sw.uid + 1 for sw in a.swatches))
    for sc in bpy.data.scenes:
        if hasattr(sc, "hueatlas"):
            top = max(top, sc.hueatlas.next_uid)
    avoid = avoid or set()
    while top in avoid:
        top += 1
    scene.hueatlas.next_uid = top + 1
    return top


def reserve_uid(scene, uid: int):
    s = scene.hueatlas
    if s.next_uid <= uid:
        s.next_uid = uid + 1


def ensure_key(atlas) -> str:
    if not atlas.key:
        n = 1
        keys = {a.key for _s, a in all_atlases()}
        while f"A{n}" in keys:
            n += 1
        with suspended():
            atlas.key = f"A{n}"
    return atlas.key


# -- creating data -------------------------------------------------------------------


def seed_stops(sw):
    with suspended():
        base = tuple(sw.color)
        dark = tuple(max(0.0, c * 0.35) for c in base)
        for pos, col in ((0.0, dark), (1.0, base)):
            st = sw.stops.add()
            st.position = pos
            st.color = col


def add_swatch(scene, atlas, *, name="Swatch", color=None, kind="FLAT", uid=None, index=None):
    with suspended():
        sw = atlas.swatches.add()
        if uid is not None:
            sw.uid = uid
            reserve_uid(scene, uid)
        else:
            sw.uid = new_uid(scene)
        sw.name = name
        if color is None:
            color = raster.parse_hex(NEW_SWATCH_COLORS[(len(atlas.swatches) - 1) % len(NEW_SWATCH_COLORS)])
        sw.color = tuple(color[:3])
        sw.kind = kind
        if kind == "GRADIENT" and len(sw.stops) == 0:
            seed_stops(sw)
        last = len(atlas.swatches) - 1
        if index is not None and 0 <= index < last:
            atlas.swatches.move(last, index)
            last = index
        atlas.active_swatch_index = last
    return atlas.swatches[last]


def create_atlas(scene, name="Palette", defaults=True):
    s = scene.hueatlas
    with suspended():
        atlas = s.atlases.add()
        atlas.name = unique_atlas_name(name, exclude=atlas)
        ensure_key(atlas)
        if defaults:
            for swatch_name, hex_value in DEFAULT_COLORS:
                add_swatch(scene, atlas, name=swatch_name, color=raster.parse_hex(hex_value))
        atlas.active_swatch_index = 0
        s.active_atlas_index = len(s.atlases) - 1
    return atlas


# -- layout --------------------------------------------------------------------------


def image_size(image, reload: bool = True) -> tuple:
    if image is None:
        return (0, 0)
    w, h = image.size[:]
    if reload and (w == 0 or h == 0) and image.source == "FILE":
        try:
            image.reload()
        except RuntimeError:
            pass
        w, h = image.size[:]
    return (int(w), int(h))


def params_of(atlas, reload: bool = True) -> L.Params:
    paid = edition.PAID
    mode = atlas.padding_mode if paid else L.FIXED
    padding = atlas.padding_px if paid else 2
    region = None
    size = None
    if paid and atlas.use_region:
        if atlas.image is None:
            raise L.LayoutError("Region mode needs an image. Pick one in the Image field.")
        size = image_size(atlas.image, reload)
        if size[0] == 0 or size[1] == 0:
            raise L.LayoutError("The region image has no pixels (is the file missing?)")
        region = (atlas.region_x, atlas.region_y, atlas.region_w, atlas.region_h)
    return L.Params(
        cell_px=atlas.cell_px,
        columns=atlas.columns,
        padding_mode=mode,
        padding_px=padding,
        mip_level=atlas.mip_level,
        region=region,
        image_size=size,
    )


def slots_of(atlas, swatches=None) -> list:
    paid = edition.PAID
    items = atlas.swatches if swatches is None else swatches
    return [
        L.Slot(sw.uid, sw.kind if (paid and sw.kind == "GRADIENT") else L.FLAT, sw.span)
        for sw in items
    ]


def compute_layout(atlas, reload: bool = True) -> L.Layout:
    return L.compute(params_of(atlas, reload), slots_of(atlas))


def check_region_target(atlas):
    img = atlas.image
    if img is None:
        return
    if img.is_float:
        raise L.LayoutError(
            "Region mode needs an 8-bit image. This one is 16-bit or float; save an 8-bit PNG copy and pick that."
        )
    if img.source == "FILE" and img.file_format in LOSSY_FORMATS:
        raise L.LayoutError(
            f"Region mode would re-compress this {img.file_format} file. Save it as PNG and pick the PNG."
        )


# -- looks & appearance --------------------------------------------------------------


def look_of(sw) -> raster.Look:
    return raster.Look(
        kind=sw.kind,
        color=tuple(sw.color),
        stops=[(st.position, tuple(st.color)) for st in sw.stops],
        roughness=sw.roughness,
        metallic=sw.metallic,
        emission=tuple(sw.emission_color),
        emission_strength=sw.emission_strength,
    )


def appearance_of(sw) -> dict:
    return {
        "color": raster.to_hex(sw.color),
        "stops": [[round(st.position, 6), raster.to_hex(st.color)] for st in sw.stops],
        "roughness": round(sw.roughness, 6),
        "metallic": round(sw.metallic, 6),
        "emission": raster.to_hex(sw.emission_color),
        "emission_strength": round(sw.emission_strength, 6),
    }


def look_from_appearance(kind: str, data: dict) -> raster.Look:
    return raster.Look(
        kind=kind,
        color=raster.parse_hex(data.get("color", "#CCCCCC")),
        stops=[(float(p), raster.parse_hex(h)) for p, h in data.get("stops", [])],
        roughness=float(data.get("roughness", 0.5)),
        metallic=float(data.get("metallic", 0.0)),
        emission=raster.parse_hex(data.get("emission", "#000000")),
        emission_strength=float(data.get("emission_strength", 0.0)),
    )


def apply_appearance(sw, data: dict):
    with suspended():
        sw.color = raster.parse_hex(data.get("color", raster.to_hex(sw.color)))
        stops = data.get("stops")
        if stops is not None:
            sw.stops.clear()
            for pos, hex_value in stops:
                st = sw.stops.add()
                st.position = float(pos)
                st.color = raster.parse_hex(hex_value)
        sw.roughness = float(data.get("roughness", sw.roughness))
        sw.metallic = float(data.get("metallic", sw.metallic))
        sw.emission_color = raster.parse_hex(data.get("emission", raster.to_hex(sw.emission_color)))
        sw.emission_strength = float(data.get("emission_strength", sw.emission_strength))


def looks_of(atlas, theme: dict | None = None) -> dict:
    looks = {}
    for sw in atlas.swatches:
        kind = sw.kind if edition.PAID else "FLAT"
        if theme and str(sw.uid) in theme:
            looks[sw.uid] = look_from_appearance(kind, theme[str(sw.uid)])
        else:
            look = look_of(sw)
            look.kind = kind
            looks[sw.uid] = look
    return looks


# -- snapshots and revisions ---------------------------------------------------------------


def load_snapshot(atlas):
    if not atlas.layout_snapshot:
        return None
    try:
        return json.loads(atlas.layout_snapshot)
    except ValueError:
        return None


def load_history(atlas) -> dict:
    try:
        raw = json.loads(atlas.layout_history or "{}")
    except ValueError:
        return {}
    return {int(k): v for k, v in raw.items()}


def _store_history(atlas, history: dict):
    keep = sorted(history)[-HISTORY_LIMIT:]
    atlas.layout_history = json.dumps({str(k): history[k] for k in keep}, separators=(",", ":"))


def record_layout(atlas, layout: L.Layout, moved: bool):
    """Store the snapshot. A layout that moved cells gets a new revision."""
    snap = L.snapshot(layout)
    history = load_history(atlas)
    if moved or atlas.layout_rev not in history:
        atlas.layout_rev = max([atlas.layout_rev] + list(history)) + 1 if moved else max(atlas.layout_rev, 1)
    entry = dict(history.get(atlas.layout_rev, {}))
    entry.update(snap["swatches"])
    history[atlas.layout_rev] = entry
    _store_history(atlas, history)
    atlas.layout_snapshot = json.dumps(snap, separators=(",", ":"))


def _revert_params(atlas, snap: dict):
    params = (snap or {}).get("params") or {}
    with suspended():
        if "cell_px" in params:
            atlas.cell_px = params["cell_px"]
        if "columns" in params:
            atlas.columns = params["columns"]


# -- files & images -----------------------------------------------------------------------


def resolve_dir(path: str):
    """Absolute folder for a Blender path, or None when it cannot be resolved yet."""
    if not path:
        path = "//"
    if path.startswith("//") and not bpy.data.filepath:
        return None
    return os.path.normpath(bpy.path.abspath(path))


def image_file(atlas, suffix: str):
    folder = resolve_dir(atlas.output_dir)
    if folder is None:
        return None
    return os.path.join(folder, f"{safe_name(atlas.name)}_{suffix}.png")


def _same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(bpy.path.abspath(a))) == os.path.normcase(os.path.normpath(b))


def owns_image(atlas, img, role: str) -> bool:
    if img is None or not atlas.key:
        return False
    return img.get(OWNER_KEY) == atlas.key and img.get(ROLE_KEY) == role


def _mark(img, atlas, role):
    img[OWNER_KEY] = ensure_key(atlas)
    img[ROLE_KEY] = role


def _owned_image(atlas, current, role):
    if owns_image(atlas, current, role):
        return current
    for img in bpy.data.images:
        if owns_image(atlas, img, role):
            return img
    return None


def set_colorspace(img, data: bool):
    cs = img.colorspace_settings
    if data:
        try:
            cs.is_data = True
        except (AttributeError, TypeError):
            pass
        return
    try:
        if cs.is_data:
            cs.is_data = False
        if cs.name != "sRGB":
            cs.name = "sRGB"
    except TypeError:
        pass


def store_image(atlas, current, role: str, rgba: np.ndarray, data: bool = False):
    """Write one of the atlas's own images and return it.

    Only images this atlas created are reused, remapped or removed; an image
    the user picked is never touched.
    """
    height, width = rgba.shape[:2]
    name = f"{safe_name(atlas.name)}_{role}"
    path = image_file(atlas, role)
    existing = _owned_image(atlas, current, role)
    if path:
        png.write(path, rgba)
        if existing is not None and existing.packed_file is None and _same_file(existing.filepath, path):
            img = existing
            img.reload()
        else:
            img = bpy.data.images.load(path, check_existing=True)
            img.reload()
            if existing is not None and existing != img:
                existing.user_remap(img)
                if existing.users == 0:
                    bpy.data.images.remove(existing)
        if bpy.data.filepath:
            try:
                img.filepath = bpy.path.relpath(path)
            except ValueError:
                pass
    else:
        img = existing
        if img is None or tuple(img.size[:]) != (width, height):
            fresh = bpy.data.images.new(name, width, height, alpha=True)
            if img is not None:
                img.user_remap(fresh)
                if img.users == 0:
                    bpy.data.images.remove(img)
            img = fresh
        img.pixels.foreach_set((rgba.astype(np.float32) / 255.0).ravel())
        img.update()
        try:
            img.pack()
        except RuntimeError:
            pass
    _mark(img, atlas, role)
    set_colorspace(img, data)
    return img


def read_pixels(img) -> np.ndarray:
    w, h = image_size(img)
    flat = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(flat)
    return np.clip(np.round(flat * 255.0), 0, 255).astype(np.uint8).reshape(h, w, 4)


def _write_region_image(atlas, layout, looks):
    img = atlas.image
    check_region_target(atlas)
    base = read_pixels(img)
    rgba = raster.render(layout, looks, "albedo", atlas.interpolation, base=base)
    src = bpy.path.abspath(img.filepath) if img.filepath else ""
    if src and img.packed_file is None and os.path.isfile(src):
        backup = src + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(src, backup)
    img.pixels.foreach_set((rgba.astype(np.float32) / 255.0).ravel())
    img.update()
    if img.packed_file is not None:
        img.pack()
    elif src:
        img.save()


def write_images(scene, atlas, layout: L.Layout, looks: dict | None = None):
    looks = looks if looks is not None else looks_of(atlas)
    if layout.params.region is not None:
        _write_region_image(atlas, layout, looks)
    else:
        rgba = raster.render(layout, looks, "albedo", atlas.interpolation)
        img = store_image(atlas, atlas.image, "Albedo", rgba)
        if atlas.image != img:
            atlas.image = img
    if edition.PAID:
        from .paid import pbr

        pbr.write_pbr_images(atlas, layout, looks)


# -- meshes --------------------------------------------------------------------------------


def scene_meshes(scene):
    """Unique, editable mesh datablocks used by objects in the scene."""
    seen = set()
    out = []
    for obj in scene.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        me = obj.data
        key = me.as_pointer()
        if key in seen or me.library is not None:
            continue
        seen.add(key)
        out.append((obj, me))
    return out


def assigned_uids(scene=None) -> set:
    """Swatch ids carried by faces anywhere in the file."""
    used = set()
    for me in editable_meshes():
        md = MeshData(me)
        if md.n_faces:
            used.update(int(u) for u in np.unique(md.uids) if u > 0)
    return used


def shared_with(atlas):
    """Another atlas (any scene) that writes the same files or uses the same material."""
    mine_file = image_file(atlas, "Albedo")
    for scene, other in all_atlases():
        if other.as_pointer() == atlas.as_pointer():
            continue
        if atlas.material is not None and other.material == atlas.material:
            return scene, other
        theirs = image_file(other, "Albedo")
        if mine_file and theirs and os.path.normcase(mine_file) == os.path.normcase(theirs):
            return scene, other
    return None


# -- sync -------------------------------------------------------------------------------------


def sync(scene, atlas, rename: dict | None = None, scan: bool = False) -> L.Layout:
    """Bring images, UVs and the snapshot in line with the atlas settings.

    rename maps removed swatch ids to the id that takes over their faces.
    scan=True also checks every mesh for faces written for an older layout
    revision (used after undo).
    """
    with suspended():
        ensure_key(atlas)
        layout = compute_layout(atlas)
        old = load_snapshot(atlas)
        moved = L.moved_uids(old, layout)
        if moved and not edition.PAID and assigned_uids() & moved:
            _revert_params(atlas, old)
            raise LiteBlocked(
                "Faces already use these swatches, so the layout was kept. "
                "Set Columns and Cell px before you assign faces."
            )
        looks = looks_of(atlas)
        write_images(scene, atlas, layout, looks)  # disk errors stop here, before any UV change
        history = load_history(atlas)
        record_layout(atlas, layout, moved=bool(moved))
        if edition.PAID and (moved or rename or scan):
            from .paid import remap

            history_with_current = dict(history)
            remap.remap_file(atlas, history_with_current, atlas.layout_rev,
                             L.snapshot(layout)["swatches"], rename or {})
        refresh_material(atlas, looks)
        other = shared_with(atlas)
        atlas.status = (
            f"Atlas '{other[1].name}' in scene '{other[0].name}' uses the same material or files. "
            "Edit only one of them, or rename one."
        ) if other else ""
    return layout


def sync_safe(scene, atlas, scan: bool = False):
    try:
        return sync(scene, atlas, scan=scan)
    except SYNC_ERRORS as exc:
        atlas.status = str(exc)
        return None


# -- material -----------------------------------------------------------------------------------


def use_linear_filter(atlas) -> bool:
    if atlas.filter_mode == "NEAREST":
        return False
    if atlas.filter_mode == "LINEAR":
        return True
    return bool(edition.PAID and atlas.padding_mode == L.MIPSAFE and atlas.mip_level >= 2)


def socket(node, *names):
    for name in names:
        sock = node.inputs.get(name)
        if sock is not None:
            return sock
    raise KeyError(f"{node.name} has none of {names}")


def principled(nt):
    for node in nt.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def image_node(nt, name, label, location, image, interpolation):
    node = nt.nodes.get(name)
    if node is None:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.name = name
        node.label = label
        node.location = location
    node.image = image
    node.interpolation = interpolation
    node.extension = "EXTEND"
    return node


def refresh_material(atlas, looks=None):
    """Update the atlas material in place: images, filtering, PBR links."""
    mat = atlas.material
    if mat is None or mat.node_tree is None:
        return
    nt = mat.node_tree
    bsdf = principled(nt)
    if bsdf is None:
        return
    interp = "Linear" if use_linear_filter(atlas) else "Closest"
    tex = image_node(nt, "HueAtlas Albedo", "Albedo", (-350, 250), atlas.image, interp)
    base = socket(bsdf, "Base Color")
    if not any(link.from_node == tex for link in base.links):
        nt.links.new(tex.outputs["Color"], base)
    if edition.PAID:
        from .paid import pbr

        pbr.refresh(nt, bsdf, atlas, interp, looks if looks is not None else looks_of(atlas))


def build_material(atlas):
    """Rebuild the atlas material from scratch (glTF-ready wiring)."""
    mat = atlas.material
    if mat is None:
        mat = bpy.data.materials.new(f"{safe_name(atlas.name)}_Mat")
        atlas.material = mat
    if hasattr(mat, "use_nodes") and not mat.use_nodes:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (150, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    refresh_material(atlas)
    return mat


def ensure_material(atlas):
    if atlas.material is None or atlas.material.node_tree is None or principled(atlas.material.node_tree) is None:
        return build_material(atlas)
    refresh_material(atlas)
    return atlas.material


# -- assigning ------------------------------------------------------------------------------------


def target_objects(context, mode: str):
    """Mesh objects to work on. mode is 'EDIT' (objects in Edit Mode) or 'OBJECT' (selected)."""
    if mode == "EDIT":
        objs = [o for o in context.objects_in_mode_unique_data if o.type == "MESH"]
    else:
        objs = [o for o in context.selected_objects if o.type == "MESH"]
    out, seen = [], set()
    for obj in objs:
        if obj.data.library is not None:
            continue
        key = obj.data.as_pointer()
        if key not in seen:
            seen.add(key)
            out.append(obj)
    return out


def assign_flat(objects, atlas, uid: int, layout: L.Layout, selected_only: bool) -> int:
    mat = ensure_material(atlas)
    center = np.array(layout.uv_center(uid), dtype=np.float32)
    total = 0
    for obj in objects:
        slot = ensure_material_slot(obj, mat)
        md = MeshData(obj.data, create=True)
        mask = md.select.copy() if selected_only else np.ones(md.n_faces, dtype=bool)
        count = int(mask.sum())
        if not count:
            continue
        md.uids[mask] = uid
        md.revs[mask] = atlas.layout_rev
        md.material[mask] = slot
        md.uv[md.loop_mask(mask)] = center
        md.write(uids=True, uv=True, material=True)
        total += count
    return total


def faces_with_uid(objects, uid: int, extend: bool) -> int:
    count = 0
    for obj in objects:
        md = MeshData(obj.data)
        hit = md.uids == uid
        md.select = (md.select | hit) if extend else hit
        md.write(uids=False, uv=False, select=True)
        count += int(hit.sum())
    return count


# -- audit --------------------------------------------------------------------------------------

AUDIT_PRIORITY = [
    "UNASSIGNED",
    "OUT_OF_ATLAS",
    "OUT_OF_REGION",
    "STRADDLE",
    "WRONG_SWATCH",
    "MIP_BLEED_RISK",
]

AUDIT_TEXT = {
    "UNASSIGNED": "Face uses the atlas material but has no swatch",
    "OUT_OF_ATLAS": "UVs leave the atlas or sit on an empty cell",
    "OUT_OF_REGION": "UVs leave the palette region",
    "STRADDLE": "UVs span more than one swatch cell",
    "WRONG_SWATCH": "UVs sit in another swatch's cell (Repair UVs fixes this)",
    "MIP_BLEED_RISK": "UVs reach into the gutter, so mip levels may bleed",
    "DATA_SRGB": "Data texture is not marked as non-colour data",
    "NON_POT": "Image size is not a power of two",
    "IMAGE_MISSING": "The atlas has no image yet. Click Generate / Update.",
}


def audit(scene, atlas) -> list:
    """Return issues as dicts: code, object, mesh, face, message."""
    issues = []
    layout = compute_layout(atlas)
    uids = atlas_uids(atlas)
    W, H = float(layout.width), float(layout.height)
    eps_uv = max(1e-6, 4.0 * 2.0 ** -23)
    eps_px = max(1e-4, max(W, H) * eps_uv)
    grid = layout.grid_rect()
    region = layout.params.region is not None
    paid_extra = None
    if edition.PAID:
        from .paid import audit_extra as paid_extra

    if atlas.image is None and not region:
        issues.append({"code": "IMAGE_MISSING", "object": "", "mesh": "", "face": -1,
                       "message": AUDIT_TEXT["IMAGE_MISSING"]})

    for obj, me in scene_meshes(scene):
        slots = material_indices(me, atlas.material) if atlas.material is not None else []
        md = MeshData(me)
        if md.n_faces == 0:
            continue
        uses = np.isin(md.material, slots) if slots else np.zeros(md.n_faces, dtype=bool)
        assigned = np.isin(md.uids, list(uids)) if uids else np.zeros(md.n_faces, dtype=bool)
        relevant = uses | assigned
        if not relevant.any():
            continue
        bounds = md.face_uv_bounds()
        px = bounds * np.array([W, H, W, H])
        codes = np.full(md.n_faces, "", dtype=object)

        outside01 = (bounds[:, 0] < -eps_uv) | (bounds[:, 1] < -eps_uv) | \
                    (bounds[:, 2] > 1 + eps_uv) | (bounds[:, 3] > 1 + eps_uv)
        outside_grid = (
            (px[:, 0] < grid.x0 - eps_px) | (px[:, 1] < grid.y0 - eps_px)
            | (px[:, 2] > grid.x1 + eps_px) | (px[:, 3] > grid.y1 + eps_px)
        )
        inside_grid = ~(
            (px[:, 2] <= grid.x0 + eps_px) | (px[:, 0] >= grid.x1 - eps_px)
            | (px[:, 3] <= grid.y0 + eps_px) | (px[:, 1] >= grid.y1 - eps_px)
        )
        unassigned = relevant & ~assigned
        if region:
            # Faces mapped to the painted part of a region texture are not palette faces.
            unassigned &= inside_grid
            relevant = relevant & (assigned | inside_grid)
        codes[unassigned] = "UNASSIGNED"

        free = codes == ""
        if region:
            codes[free & relevant & outside01] = "OUT_OF_ATLAS"
            free = codes == ""
            codes[free & relevant & outside_grid] = "OUT_OF_REGION"
        else:
            codes[free & relevant & (outside01 | outside_grid)] = "OUT_OF_ATLAS"

        for i in np.nonzero((codes == "") & relevant)[0]:
            # Shrink the box a hair so UVs that touch a cell edge stay inside that cell.
            lo_uid = layout.uid_at(px[i, 0] + eps_px, px[i, 1] + eps_px)
            hi_uid = layout.uid_at(px[i, 2] - eps_px, px[i, 3] - eps_px)
            if lo_uid is None or hi_uid is None:
                codes[i] = "OUT_OF_ATLAS"
            elif lo_uid != hi_uid:
                codes[i] = "STRADDLE"
            elif lo_uid != int(md.uids[i]):
                codes[i] = "WRONG_SWATCH"
            elif paid_extra is not None and paid_extra.mip_bleed_risk(layout, lo_uid, px[i], eps_px):
                codes[i] = "MIP_BLEED_RISK"

        for i in np.nonzero(codes != "")[0]:
            code = codes[i]
            issues.append({
                "code": code,
                "object": obj.name,
                "mesh": me.name,
                "face": int(i),
                "message": AUDIT_TEXT[code],
            })

    if paid_extra is not None:
        issues.extend(paid_extra.image_issues(atlas, layout))
    order = {code: i for i, code in enumerate(AUDIT_PRIORITY)}
    issues.sort(key=lambda it: (it["object"], order.get(it["code"], 99), it["face"]))
    return issues


# -- palette files ------------------------------------------------------------------------------


def palette_to_json(atlas) -> dict:
    return {
        "format": "hueatlas-palette",
        "version": 1,
        "name": atlas.name,
        "layout": {
            "cell_px": atlas.cell_px,
            "columns": atlas.columns,
            "padding_mode": atlas.padding_mode,
            "padding_px": atlas.padding_px,
            "mip_level": atlas.mip_level,
            "interpolation": atlas.interpolation,
        },
        "swatches": [
            {"uid": sw.uid, "name": sw.name, "kind": sw.kind, "span": sw.span, **appearance_of(sw)}
            for sw in atlas.swatches
        ],
    }


_HEX6 = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_HEX3 = re.compile(r"^#([0-9A-Fa-f]{3})$")


def parse_palette_text(text: str) -> list:
    """Parse GIMP .gpl or a hex list into [(name, rgb)]."""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    out = []
    if lines and lines[0].strip().upper().startswith("GIMP PALETTE"):
        for line in lines[1:]:
            s = line.strip()
            if not s or s.startswith("#") or ":" in s.split()[0]:
                continue
            parts = s.split(None, 3)
            if len(parts) < 3:
                continue
            try:
                rgb = tuple(min(255, max(0, int(p))) / 255.0 for p in parts[:3])
            except ValueError:
                continue
            name = parts[3].strip() if len(parts) > 3 else f"Color {len(out) + 1}"
            out.append((name, rgb))
        return out
    for token in re.split(r"[\s,;]+", text):
        token = token.strip()
        if _HEX6.match(token) or _HEX3.match(token):
            out.append((f"Color {len(out) + 1}", raster.parse_hex(token)))
    return out


def read_palette_file(path: str) -> dict:
    """Parse a palette file into {'name', 'layout', 'swatches': [...]} without touching the scene."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    stem = os.path.splitext(os.path.basename(path))[0]
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        if data.get("format") != "hueatlas-palette":
            raise ValueError("Not a HueAtlas palette file")
        return {"name": data.get("name") or stem, "layout": data.get("layout", {}),
                "swatches": data.get("swatches", []), "json": True}
    entries = [{"name": n, "color": raster.to_hex(c), "kind": "FLAT"} for n, c in parse_palette_text(text)]
    if not entries:
        raise ValueError("No colours found. Use GIMP .gpl, #RRGGBB hex values or HueAtlas .json")
    return {"name": stem, "layout": {}, "swatches": entries, "json": False}


def lite_append_blocked(scene, atlas, count: int) -> bool:
    """Would appending `count` flat swatches move cells that faces use?"""
    if edition.PAID or count <= 0:
        return False
    old = load_snapshot(atlas)
    if not old:
        return False
    slots = slots_of(atlas) + [L.Slot(-(i + 1)) for i in range(count)]
    try:
        layout = L.compute(params_of(atlas), slots)
    except L.LayoutError:
        return True
    moved = L.moved_uids(old, layout)
    return bool(moved and (assigned_uids() & moved))


def import_palette(scene, path: str, new_atlas: bool = False):
    """Import .gpl, a hex list or HueAtlas JSON. Returns (atlas, count)."""
    data = read_palette_file(path)
    s = scene.hueatlas
    target = None if (new_atlas or len(s.atlases) == 0) else active_atlas(scene)
    if target is not None and lite_append_blocked(scene, target, len(data["swatches"])):
        raise LiteBlocked(
            "Importing this many swatches would move cells that faces use. "
            "Add fewer swatches, or use a new file."
        )
    atlas = target or create_atlas(scene, name=data["name"], defaults=False)
    count = 0
    with suspended():
        lay = data["layout"]
        if data["json"] and len(atlas.swatches) == 0:
            atlas.cell_px = int(lay.get("cell_px", atlas.cell_px))
            atlas.columns = int(lay.get("columns", atlas.columns))
            if edition.PAID:
                atlas.padding_mode = lay.get("padding_mode", atlas.padding_mode)
                atlas.padding_px = int(lay.get("padding_px", atlas.padding_px))
                atlas.mip_level = int(lay.get("mip_level", atlas.mip_level))
                atlas.interpolation = lay.get("interpolation", atlas.interpolation)
        used = file_uids_in_use() if data["json"] else set()
        for entry in data["swatches"]:
            uid = int(entry.get("uid", 0) or 0)
            if uid <= 0 or uid in used:
                uid = None
            kind = entry.get("kind", "FLAT")
            if kind not in {"FLAT", "GRADIENT"}:
                kind = "FLAT"
            sw = add_swatch(scene, atlas, name=entry.get("name", "Swatch"),
                            color=raster.parse_hex(entry.get("color", "#CCCCCC")), kind=kind, uid=uid)
            used.add(sw.uid)
            if "span" in entry:
                sw.span = int(entry["span"])
            if data["json"]:
                apply_appearance(sw, entry)
            if sw.kind == "GRADIENT" and len(sw.stops) == 0:
                seed_stops(sw)
            count += 1
    return atlas, count


# -- swatch snapshots for rollback ------------------------------------------------------------


def capture_swatch(sw) -> dict:
    return {"uid": sw.uid, "name": sw.name, "kind": sw.kind, "span": sw.span, **appearance_of(sw)}


def restore_swatch(scene, atlas, data: dict, index: int):
    with suspended():
        sw = add_swatch(scene, atlas, name=data["name"], color=raster.parse_hex(data["color"]),
                        kind=data["kind"], uid=data["uid"], index=index)
        sw.span = data["span"]
        apply_appearance(sw, data)
    return sw
