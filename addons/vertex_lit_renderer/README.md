# Vertex Lit Renderer — v0.1

A Blender 4.4 render engine addon implementing **Gouraud shading** (per-vertex diffuse lighting).
Designed for look-dev before export to retro / old game engines (PS1, N64, Quake, GoldSrc, etc.).

---

## What it does

- Lighting (Lambert diffuse + ambient) is computed **per vertex** in the vertex shader and interpolated across faces — the characteristic smooth-gradient look of 5th/6th-gen console and early PC game engines.
- Single **shadow map** from the first Sun light, also sampled per-vertex (gives blocky shadow transitions matching the vertex density of your mesh).
- Up to **8 lights** (Point, Sun, Spot all supported).
- **Vertex color attributes** are respected as base color; falls back to material diffuse color → white.
- Viewport-only. No F12 render (v0.1).

---

## Installation

1. Zip the `vertex_lit_renderer/` folder → `vertex_lit_renderer.zip`
2. Blender → Edit → Preferences → Add-ons → Install → select the zip
3. Enable **Vertex Lit Renderer**

---

## Usage

1. Open **Properties → Render Properties**
2. Set **Render Engine → Vertex Lit**
3. The viewport immediately switches to Gouraud shading
4. Tweak **Vertex Lit Settings** (same panel):

| Setting | Purpose |
|---|---|
| Ambient Color / Strength | Fill light on surfaces facing away from lights |
| Light Energy Scale | Global multiplier on all Blender light energies. Start at 0.01 and increase until highlights look right |
| Shadows | Requires a **Sun** light. Point/Spot lights cast no shadows in v0.1 |
| Shadow Resolution | 512 / 1024 / 2048 – higher = sharper but slower per-frame |
| Shadow Bias | Increase slightly if you see shadow acne (dark speckles on lit surfaces) |
| Shadow Darkness | 0 = pitch black shadows, 1 = no shadow effect |

---

## Tips

- **Energy Scale tuning**: Blender lights are in physical units (watts). For a scene with a 100 W point light, `energy_scale = 0.01` gives a shader contribution of `1.0`. For outdoor sun scenes, try `0.1`.
- **Vertex density matters**: Vertex lighting looks better with denser meshes. Add a Subdivision modifier (non-applied) to smooth out gradients if needed.
- **Vertex colors**: Paint vertex colors on your mesh — the renderer multiplies them with the computed lighting, matching how game engines blend baked and runtime lighting.
- **Shadow mesh density**: Shadows are per-vertex, so a large flat plane with only 4 vertices will have very coarse shadow transitions. Subdivide the receiver mesh for better shadow quality.

---

## Known Limitations (v0.1)

- Viewport only — no offline F12 render output
- Single shadow caster (first Sun light)
- Point/Spot shadow casting not yet implemented
- CORNER-domain vertex colour attributes not yet supported (use POINT domain)
- No specular term (matches most PS1/N64 material models)
- Rebuilds GPU batches on every scene change — performance may degrade in scenes with many objects (>200 meshes). Optimization planned for v0.2.

---

## Roadmap

- v0.2: Batch caching optimisation, CORNER-domain vertex colours
- v0.3: Specular term (optional, Blinn-Phong at vertex)
- v0.4: F12 render to image
- v0.5: Point/Spot shadow support (cube maps)
