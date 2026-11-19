# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep atlas images and UVs consistent after undo and redo.

Memfile undo restores swatches, settings and mesh UVs but not image pixels
on disk or in memory; Edit Mode undo restores mesh UVs but not the atlas
settings. After either, re-sync every atlas: images are rewritten from the
restored swatches, and faces stored for an older layout revision are moved
to the current one (full version).
"""

import bpy
from bpy.app.handlers import persistent


@persistent
def _after_undo(*_args):
    from . import core

    if core.updates_suspended():
        return
    for scene, atlas in list(core.all_atlases()):
        core.sync_safe(scene, atlas, scan=True)


_HANDLERS = (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post)


def register():
    for lst in _HANDLERS:
        if _after_undo not in lst:
            lst.append(_after_undo)


def unregister():
    for lst in _HANDLERS:
        while _after_undo in lst:
            lst.remove(_after_undo)
