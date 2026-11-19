# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and write the per-face data HueAtlas needs, in Object or Edit Mode.

Object Mode uses foreach_get/foreach_set with numpy. Edit Mode goes through
bmesh.from_edit_mesh and never keeps BMesh references beyond one call, which
keeps undo safe. Both paths expose the same arrays, so every algorithm is
written once against plain numpy data.

Two INT face attributes are stored:
- hueatlas_swatch: the swatch id the face uses
- hueatlas_rev: the layout revision the face's UVs were written for

UVs always go to the render-active UV map, the one materials and exporters use.
"""

from __future__ import annotations

import bmesh
import bpy
import numpy as np

ATTR = "hueatlas_swatch"
REV = "hueatlas_rev"
UV_NAME = "UVMap"


def render_uv_name(mesh):
    """Name of the UV map used for rendering and export (None if the mesh has none)."""
    layers = mesh.uv_layers
    for layer in layers:
        if layer.active_render:
            return layer.name
    if layers.active is not None:
        return layers.active.name
    return layers[0].name if len(layers) else None


def has_hueatlas_data(mesh) -> bool:
    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        return bm.faces.layers.int.get(ATTR) is not None
    attr = mesh.attributes.get(ATTR)
    return attr is not None and attr.domain == "FACE" and attr.data_type == "INT"


class MeshData:
    """A snapshot of one mesh's faces, loops and render UVs."""

    def __init__(self, mesh, create: bool = False):
        self.mesh = mesh
        self.edit = bool(mesh.is_editmode)
        self.has_attr = False
        self.has_uv = False
        if self.edit:
            self._read_bmesh(create)
        else:
            self._read_mesh(create)
        self.loop_face = np.repeat(np.arange(self.n_faces, dtype=np.int64), self.loop_total)

    # -- reading -------------------------------------------------------------

    @staticmethod
    def _int_attr(me, name, create):
        attr = me.attributes.get(name)
        if attr is not None and (attr.domain != "FACE" or attr.data_type != "INT"):
            if not create:
                return None
            me.attributes.remove(attr)
            attr = None
        if attr is None and create:
            attr = me.attributes.new(name, "INT", "FACE")
        return attr

    def _read_mesh(self, create: bool):
        me = self.mesh
        self._int_attr(me, ATTR, create)
        self._int_attr(me, REV, create)
        if create and len(me.uv_layers) == 0:
            me.uv_layers.new(name=UV_NAME)
        self.uv_name = render_uv_name(me)

        n_faces = len(me.polygons)
        n_loops = len(me.loops)
        self.n_faces, self.n_loops = n_faces, n_loops
        tmp = np.zeros(n_faces, dtype=np.int32)
        me.polygons.foreach_get("loop_start", tmp)
        self.loop_start = tmp.astype(np.int64)
        me.polygons.foreach_get("loop_total", tmp)
        self.loop_total = tmp.astype(np.int64)
        self.material = np.zeros(n_faces, dtype=np.int32)
        me.polygons.foreach_get("material_index", self.material)
        self.select = np.zeros(n_faces, dtype=bool)
        me.polygons.foreach_get("select", self.select)

        self.uids = np.zeros(n_faces, dtype=np.int32)
        self.revs = np.zeros(n_faces, dtype=np.int32)
        attr = self._int_attr(me, ATTR, False)
        if attr is not None:
            attr.data.foreach_get("value", self.uids)
            self.has_attr = True
        rev = self._int_attr(me, REV, False)
        if rev is not None:
            rev.data.foreach_get("value", self.revs)

        self.uv = np.zeros((n_loops, 2), dtype=np.float32)
        if self.uv_name is not None:
            flat = np.zeros(n_loops * 2, dtype=np.float32)
            me.uv_layers[self.uv_name].uv.foreach_get("vector", flat)
            self.uv[:] = flat.reshape(-1, 2)
            self.has_uv = True

        self.loop_vert = np.zeros(n_loops, dtype=np.int32)
        me.loops.foreach_get("vertex_index", self.loop_vert)
        co = np.zeros(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        self.co = co.reshape(-1, 3)
        self.active_face = me.polygons.active if n_faces else -1

    def _bm_layers(self, bm, create):
        ilay = bm.faces.layers.int.get(ATTR)
        rlay = bm.faces.layers.int.get(REV)
        if create:
            if ilay is None:
                ilay = bm.faces.layers.int.new(ATTR)
            if rlay is None:
                rlay = bm.faces.layers.int.new(REV)
        name = render_uv_name(self.mesh)
        uvl = bm.loops.layers.uv.get(name) if name else None
        if uvl is None:
            uvl = bm.loops.layers.uv.active
        if uvl is None and create:
            uvl = bm.loops.layers.uv.new(UV_NAME)
        return ilay, rlay, uvl

    def _read_bmesh(self, create: bool):
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        bm.faces.index_update()
        ilay, rlay, uvl = self._bm_layers(bm, create)
        self.uv_name = uvl.name if uvl is not None else None
        self.has_attr = ilay is not None
        self.has_uv = uvl is not None

        faces = bm.faces
        n_faces = len(faces)
        totals = np.fromiter((len(f.loops) for f in faces), dtype=np.int64, count=n_faces)
        starts = np.zeros(n_faces, dtype=np.int64)
        if n_faces:
            starts[1:] = np.cumsum(totals)[:-1]
        n_loops = int(totals.sum())
        self.n_faces, self.n_loops = n_faces, n_loops
        self.loop_start, self.loop_total = starts, totals
        self.material = np.fromiter((f.material_index for f in faces), dtype=np.int32, count=n_faces)
        self.select = np.fromiter((f.select for f in faces), dtype=bool, count=n_faces)
        self.uids = (np.fromiter((f[ilay] for f in faces), dtype=np.int32, count=n_faces)
                     if ilay is not None else np.zeros(n_faces, dtype=np.int32))
        self.revs = (np.fromiter((f[rlay] for f in faces), dtype=np.int32, count=n_faces)
                     if rlay is not None else np.zeros(n_faces, dtype=np.int32))
        self.loop_vert = np.fromiter((l.vert.index for f in faces for l in f.loops),
                                     dtype=np.int32, count=n_loops)
        if uvl is not None:
            flat = np.fromiter((c for f in faces for l in f.loops for c in l[uvl].uv),
                               dtype=np.float32, count=n_loops * 2)
            self.uv = flat.reshape(-1, 2)
        else:
            self.uv = np.zeros((n_loops, 2), dtype=np.float32)
        self.co = np.array([v.co[:] for v in bm.verts], dtype=np.float32).reshape(-1, 3)
        active = bm.faces.active
        self.active_face = active.index if active is not None else -1

    # -- helpers ---------------------------------------------------------------

    def loop_mask(self, face_mask: np.ndarray) -> np.ndarray:
        return np.repeat(face_mask, self.loop_total)

    def loop_uids(self) -> np.ndarray:
        return self.uids[self.loop_face]

    def face_uv_bounds(self):
        """Per-face (min_u, min_v, max_u, max_v)."""
        if self.n_faces == 0:
            return np.zeros((0, 4), dtype=np.float64)
        starts = self.loop_start
        mins = np.minimum.reduceat(self.uv, starts, axis=0)
        maxs = np.maximum.reduceat(self.uv, starts, axis=0)
        return np.concatenate([mins, maxs], axis=1).astype(np.float64)

    def loop_coords(self) -> np.ndarray:
        return self.co[self.loop_vert]

    # -- writing ---------------------------------------------------------------

    def write(self, uids: bool = True, uv: bool = True, material: bool = False, select: bool = False):
        """Write arrays back. Writing uids also writes the revision array."""
        if self.edit:
            self._write_bmesh(uids, uv, material, select)
        else:
            self._write_mesh(uids, uv, material, select)

    def _write_mesh(self, uids, uv, material, select):
        me = self.mesh
        if uids:
            self._int_attr(me, ATTR, True).data.foreach_set("value", self.uids.astype(np.int32))
            self._int_attr(me, REV, True).data.foreach_set("value", self.revs.astype(np.int32))
        if uv:
            if len(me.uv_layers) == 0:
                me.uv_layers.new(name=UV_NAME)
            name = render_uv_name(me)
            me.uv_layers[name].uv.foreach_set("vector", np.ascontiguousarray(self.uv, dtype=np.float32).ravel())
        if material:
            me.polygons.foreach_set("material_index", self.material.astype(np.int32))
        if select:
            me.polygons.foreach_set("select", self.select)
        me.update()

    def _write_bmesh(self, uids, uv, material, select):
        me = self.mesh
        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        ilay, rlay, uvl = self._bm_layers(bm, create=uids or uv)
        k = 0
        for i, f in enumerate(bm.faces):
            if uids:
                f[ilay] = int(self.uids[i])
                f[rlay] = int(self.revs[i])
            if material:
                f.material_index = int(self.material[i])
            if select:
                f.select_set(bool(self.select[i]))
            if uv:
                for loop in f.loops:
                    loop[uvl].uv = (float(self.uv[k, 0]), float(self.uv[k, 1]))
                    k += 1
        if select:
            bm.select_flush_mode()
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)


def editable_meshes():
    """Every local mesh datablock in the file that carries HueAtlas data."""
    for me in bpy.data.meshes:
        if me.library is not None or me.users == 0:
            continue
        if has_hueatlas_data(me):
            yield me


def ensure_material_slot(obj, material) -> int:
    """Index of `material` in the object's mesh materials, appending it if needed."""
    me = obj.data
    for i, mat in enumerate(me.materials):
        if mat == material:
            return i
    me.materials.append(material)
    return len(me.materials) - 1


def material_indices(mesh, material) -> list:
    return [i for i, mat in enumerate(mesh.materials) if mat == material]
