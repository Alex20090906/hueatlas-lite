# Changelog

## Lite 1.0.1 (unreleased)

- The Lite edition no longer shows "Not available in HueAtlas Lite" messages.
  Options Lite does not have (gradient swatches, reordering swatches, a second
  atlas, importing into a new atlas) are no longer offered at all.
- Lite still never moves a cell that faces use. When a change would do that
  (Columns, Cell px, removing a used swatch, growing a full atlas), it keeps
  the layout and says why in plain words.
- README and user guide: the Unreal 5 pack is a texture set with import notes;
  it is not yet tested in Unreal.

## 1.0.0 (unreleased)

First release.

- Palette atlas generator: exact colours, edge-extended gutters, power-of-two
  images, deterministic PNG output.
- Assign to faces (Edit Mode, multi-object) and objects; select by swatch;
  pick from face.
- Palette import (GIMP .gpl, hex lists, HueAtlas JSON) and JSON export.
- glTF-ready material wiring.
- Audit with click-to-select results.
- Full version: edit-safe remap, gradient swatches with sRGB/OKLab blending
  and axis projection, mip-safe padding, region mode, ORM and emission data
  atlas, themes, Godot/Unity/Unreal engine pack, extra audit checks,
  Repair UVs.
