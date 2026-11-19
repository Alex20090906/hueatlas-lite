# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure layout math (no scene needed)."""

from hueatlas import layout as L


def test_square_pow2_atlas():
    lay = L.compute(L.Params(cell_px=16, columns=4), [L.Slot(i) for i in range(1, 6)])
    assert (lay.width, lay.height) == (64, 64)
    assert lay.rows == 2 and lay.capacity() == 8
    # Row 0 sits at the top of the image.
    assert lay.boxes[1] == L.Rect(0, 48, 16, 64)
    assert lay.boxes[5] == L.Rect(0, 32, 16, 48)
    assert lay.inners[1] == L.Rect(2, 50, 14, 62)


def test_gradient_wraps_to_next_row():
    slots = [L.Slot(1), L.Slot(2), L.Slot(3, L.GRADIENT, 3)]
    lay = L.compute(L.Params(cell_px=16, columns=4), slots)
    assert lay.boxes[3] == L.Rect(0, 32, 48, 48)
    assert lay.cells[(1, 0)] == lay.cells[(1, 2)] == 3


def test_mipsafe_pitch_and_clean_level():
    lay = L.compute(L.Params(cell_px=10, columns=4, padding_mode=L.MIPSAFE, mip_level=3), [L.Slot(1)])
    assert lay.pitch == 16 and lay.gutter == 8
    assert lay.clean_mip_level() == 4
    grad = L.compute(L.Params(cell_px=16, columns=4, padding_mode=L.MIPSAFE, mip_level=2),
                     [L.Slot(1, L.GRADIENT, 4)])
    assert grad.clean_mip_level() == 2


def test_region_alignment_and_fit():
    params = L.Params(cell_px=16, columns=4, padding_mode=L.MIPSAFE, mip_level=3,
                      region=(130, 3, 120, 120), image_size=(256, 256))
    lay = L.compute(params, [L.Slot(1), L.Slot(2)])
    assert lay.origin == (136, 120)
    try:
        L.compute(L.Params(cell_px=64, columns=4, region=(0, 0, 100, 100), image_size=(256, 256)),
                  [L.Slot(1)])
    except L.LayoutError:
        pass
    else:
        raise AssertionError("region too small should fail")


def test_errors():
    for params, slots in [
        (L.Params(cell_px=4, padding_px=2), [L.Slot(1)]),
        (L.Params(columns=2), [L.Slot(1, L.GRADIENT, 3)]),
        (L.Params(), [L.Slot(1), L.Slot(1)]),
    ]:
        try:
            L.compute(params, slots)
        except L.LayoutError:
            continue
        raise AssertionError(f"expected LayoutError for {params}")


def test_snapshot_detects_moves():
    a = L.compute(L.Params(cell_px=16, columns=4), [L.Slot(1), L.Slot(2)])
    b = L.compute(L.Params(cell_px=16, columns=4), [L.Slot(2), L.Slot(1)])
    assert L.moved_uids(L.snapshot(a), a) == set()
    assert L.moved_uids(L.snapshot(a), b) == {1, 2}
