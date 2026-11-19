# HueAtlas

Palette atlas texturing for low-poly game kits, built to export cleanly to
Godot, Unity, Unreal and glTF.

Texture a whole kit with one material and one small palette image. Each face
stores which swatch it uses, so the palette can change without breaking your
UVs.

**HueAtlas Lite** (this repository's free edition) includes:

- palette atlas generator with exact colours and edge-extended 2 px gutters
- assign to faces (Edit Mode, multi-object) or whole objects
- select by swatch, pick from face
- import GIMP `.gpl`, hex lists and HueAtlas JSON; export JSON
- an albedo material that exports to glTF as is
- a basic audit (unassigned faces, UVs outside the atlas, UVs spanning cells)

**HueAtlas** (full version) adds:

- **edit-safe palette**: reorder, insert, delete, change columns or cell size,
  and every face keeps its colour
- **gradient swatches** with 2–8 stops (sRGB or OKLab) and axis projection
- **mip-safe padding**: clean up to the mip level you choose, so engines can
  keep linear filtering with mipmaps
- **region mode**: put the palette in a corner of an existing texture
- **PBR data atlas**: roughness, metallic and emission per swatch in an ORM and
  an emission image, wired for Blender's glTF exporter
- **themes**: colour variants that share one layout
- **engine pack**: Godot 4 `.tres` + `.import` files, Unity URP and Unreal
  texture sets with import notes, no custom shaders
- extra audit checks (mip bleed, region, colour space, power of two)

Get the full version: https://superhivemarket.com/products/hueatlas

## Install

Blender 4.2 or newer (tested on 4.2 LTS, 4.5 LTS, 5.2 LTS and 5.3). Download
`hueatlas_lite-1.0.0.zip` from
[Releases](https://github.com/Alex20090906/hueatlas-lite/releases/latest) (do not
unzip it), then in Blender: Edit > Preferences >
Get Extensions > ▾ > Install from Disk. Open the sidebar (N) and pick the
**HueAtlas** tab. See [the user guide](docs/USER_GUIDE.md).

## Tests

HueAtlas has a headless test suite (layout math, exact pixel colours, remap
fuzzing, a glTF round trip, mip levels, region mode, engine files, audit):

```
blender --background --factory-startup --python-exit-code 1 --python tests/run_all.py
blender --background --factory-startup --python-exit-code 1 --python tests/run_all.py -- --lite
```

## How it was made

HueAtlas was written with AI assistance (Claude Code). Every feature has an
automated test.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
