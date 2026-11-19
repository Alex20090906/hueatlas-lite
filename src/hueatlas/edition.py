# SPDX-License-Identifier: GPL-3.0-or-later
"""Which edition is running (full or lite) and how the two coexist.

The full edition ships the `paid` sub-package; the lite build leaves it out.
Detection uses find_spec, so nothing is imported at module load time.
"""

import importlib.util
import os

import bpy

_BASE = __package__

PAID = importlib.util.find_spec(_BASE + ".paid") is not None
if os.environ.get("HUEATLAS_FORCE_LITE") == "1":
    PAID = False

EDITION = "full" if PAID else "lite"
PRODUCT = "HueAtlas" if PAID else "HueAtlas Lite"

LITE_MESSAGE = "Not available in HueAtlas Lite"


def paid_module():
    """Import the paid package on demand (only valid when PAID is True)."""
    return importlib.import_module(_BASE + ".paid")


def require_paid(op=None, what: str = "") -> bool:
    if PAID:
        return True
    if op is not None:
        op.report({"WARNING"}, f"{what}: {LITE_MESSAGE}" if what else LITE_MESSAGE)
    return False


def claim_registration():
    """Refuse to register while the other edition's classes are registered.

    The check reads the registered Scene.hueatlas RNA property, which
    survives file loads (unlike bpy.app.driver_namespace).
    """
    from . import props

    owner = props.registered_owner()
    if owner and owner != props.owner_tag(_BASE):
        raise RuntimeError(
            "Another HueAtlas edition is enabled. Disable it in Preferences > Add-ons, then enable this one."
        )


def release_registration():
    """Kept for symmetry; registration state lives on the RNA types."""
