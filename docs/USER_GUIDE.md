# HueAtlas user guide

HueAtlas textures whole low-poly kits with one material and one small palette
image. Every face remembers which swatch it uses, so you can reorder, insert,
delete or resize swatches without any face changing colour, and the result
exports cleanly to Godot, Unity, Unreal and glTF.

Open the sidebar with **N** in the 3D Viewport or the UV/Image Editor and pick
the **HueAtlas** tab.

## 1. Create an atlas

1. Save your .blend first. Atlas images are written next to it (the default
   folder is `//textures/`). In an unsaved file they are packed into the .blend
   until you save.
2. Click **New Palette Atlas**. You get eight starter swatches and an image
   such as `Palette_Albedo.png`.
3. Set **Cell px** (pixels per swatch) and **Columns**. The info line shows
   the image size, how many cells are used, and the highest clean mip level.

## 2. Edit swatches

- **+** adds a flat swatch after the active one. **−** removes the active
  swatch; faces that used it move to the neighbouring swatch (full version).
- Click a colour chip to change the colour. The image updates immediately.
- **Import** reads GIMP `.gpl`, a list of hex colours (`#RRGGBB`, one per line
  or comma separated), or a HueAtlas `.json`. **Export** writes `.json`, so you
  can reuse a palette across kits.

Full version:

- **Gradient swatches** (ramp icon): 2–8 colour stops across several cells
  (**Span**). Choose **sRGB** or **OKLab** blending for the atlas.
- **Roughness, Metallic, Emission** per swatch. These go into an ORM image
  (R = AO, G = roughness, B = metallic) and an emission image that line up
  with the colour atlas.
- **Up/Down arrows** reorder swatches. Assigned faces follow their swatch.

## 3. Assign

- **Edit Mode:** select faces, then **Assign to Selected Faces**. Works on
  several objects in Edit Mode at once.
- **Object Mode:** select objects, then **Assign to Selected Objects** (all
  faces).
- **Select by Swatch** selects faces (Edit Mode) or objects (Object Mode) that
  use the active swatch. **Pick from Active Face** makes the active face's
  swatch the active swatch.
- The atlas material is added to the mesh automatically.

Gradient projection (full version): pick a gradient swatch, choose the axis
(X/Y/Z) and space (Global, Local or View), then assign or click **Project
Gradient**. The range is measured over everything selected, so one ramp runs
continuously across several objects.

## 4. Layout options (full version)

- **Padding: Mip-safe** aligns cells and gutters to a 2^L pixel grid so the
  colours stay clean up to mip level L. This lets engines keep linear
  filtering with mipmaps: no shimmer at distance, smooth gradients.
- **Region** keeps the palette inside a rectangle (x, y, width, height in
  pixels, y from the bottom) of an existing image, such as a corner of a
  hand-painted texture. Only that rectangle is rewritten; a `.bak` copy of the
  original file is kept on the first write.
- **Repair UVs** snaps every assigned face back into its own cell, for example
  after manual UV edits.

## 5. Themes (full version)

A theme is a saved set of swatch colours. **+** saves the current colours as a
new theme. **Set Active** loads a theme (images change, UVs never do). **Save
to Theme** overwrites the active theme. **Export Theme Images** writes one image
set per theme into `<export folder>/themes/`, ready for material variants in
your engine.

## 6. Export

- **glTF / GLB:** use File > Export > glTF 2.0. The HueAtlas material is wired
  the way Blender's glTF exporter expects (ORM through Separate Color, emission
  strength through `KHR_materials_emissive_strength`).
- **Engine pack (full version):** tick Godot 4, Unity 6 URP and/or Unreal 5,
  pick a folder and click **Export Engine Pack**.
  - Godot: `<name>.tres` (ORMMaterial3D or StandardMaterial3D), the PNGs and
    `.png.import` files that ask for Lossless compression and mipmaps. Copy the
    folder to the `res://` path you set (or export straight into it: re-exports
    keep Godot's uids). On an imported .glb: Advanced Import Settings >
    Materials > Use External, pointing at the .tres. Linear atlases use
    anisotropic trilinear filtering (texture_filter 5) and the material is
    double-sided like the glTF export.
  - Unity: Albedo, MetallicSmoothness (R = metallic, A = smoothness) and
    Emission (only when a swatch emits), plus `README_Unity.txt` with the
    import settings for your atlas: Compression None on every map, and
    Point filtering without mipmaps for Nearest atlases, or Bilinear with
    mipmaps and **Aniso Level 8** for linear (Mip-safe) atlases. Build a URP
    Lit material as the README says (Smoothness slider **1**) and use it in
    place of the material Unity creates from an FBX (Model > Materials >
    Remapped Materials). The glTF route (glTFast 6.21) is tested too: set
    the one import option the README names (Anisotropic Filter Level 8 for
    linear atlases, Generate Mip Maps off for Nearest atlases). glTFast
    ignores emission strengths above 1, so for exact glow use the README's
    URP Lit material on the imported model.
  - Unreal: BaseColor, ORM and Emissive textures plus a README.

## 7. Audit

**Run Audit** checks every mesh that uses the atlas. Click the arrow on a row
to select that face.

| Code | Meaning |
|---|---|
| UNASSIGNED | Face uses the atlas material but has no swatch |
| OUT_OF_ATLAS | UVs leave the image or sit on an empty cell |
| STRADDLE | UVs span more than one cell (colour will bleed) |
| WRONG_SWATCH | UVs sit in another swatch's cell (Repair UVs fixes this) |
| OUT_OF_REGION | UVs leave the palette region (full) |
| MIP_BLEED_RISK | UVs reach into the gutter (full) |
| DATA_SRGB | ORM image is marked sRGB instead of Non-Color (full) |
| NON_POT | Image size is not a power of two (full) |

## Tips

- Engines: keep palette textures **uncompressed or lossless**. VRAM
  compression smears small swatches.
- Nearest filtering is the default. Switch the atlas to Mip-safe level 2 or
  more to use linear filtering with mipmaps.
- Unity URP: set the material's **Smoothness slider to 1.0**. URP multiplies
  the MetallicSmoothness alpha by it.
- Unity, linear atlases: set **Aniso Level 8** on the textures (glTF route:
  Anisotropic Filter Level 8 on the .glb) and keep Quality > Anisotropic
  Textures at Per Texture or Forced On. Under Per Texture, Level 1 lets
  gradients seen far away along their length at a grazing angle pick up a
  tint from the neighbouring swatch row much sooner.
- Unity: set the URP Lit material's **Render Face to Both** unless the
  Blender material has Backface Culling on, or single-sided faces vanish
  from behind.
- HueAtlas writes palette UVs to the mesh's **render** UV map (the camera icon
  in the UV Maps list), the one materials and exporters use.
- Each face stores its swatch id (`hueatlas_swatch`) and the layout revision
  its UVs were written for (`hueatlas_rev`). These face attributes survive
  modifiers that keep face data and are ignored by exporters.
- Undo and redo re-sync the atlas images automatically.

## Limits

- The Image field is for Region mode. Picking an image without Region does
  not change it; the atlas keeps writing its own image.
- Region mode works on 8-bit lossless images (PNG, TGA, BMP, TIFF). It refuses
  16-bit/float images and JPEG/WebP, because rewriting them would change pixels
  outside the region.
- One material carries one emission strength. Very weak emitters next to a
  very strong one lose precision in the 8-bit emission image.
- Material slots linked to the object (not the mesh) override the atlas
  material; HueAtlas assigns through mesh material slots.
- Layout changes on meshes with hundreds of thousands of faces are fastest in
  Object Mode.
