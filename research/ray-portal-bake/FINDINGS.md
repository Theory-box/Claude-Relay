# Ray Portal UV Baking — Research Findings

Status: **mechanism verified end-to-end (Cycles CPU, Blender 4.4.0).**
Goal: render a mesh's real, fully-lit shaded surface into UV/texture space, live
in the Cycles viewport — a "realtime bake / lightmap" — using the Ray Portal
BSDF instead of the classic Bake operator.

This is the technique behind bbbn19's "Blender 5.0 Ray Portal Baking" video
(https://www.youtube.com/watch?v=DLMI6NX08VE, demo: https://bbbn19.gumroad.com/l/npekxf).
Everything below was reproduced and confirmed independently with headless render
tests; see `prototypes/`.

---

## 1. The node

- Node: **Ray Portal BSDF** — `bl_idname = "ShaderNodeBsdfRayPortal"`.
- Available since Blender 4.2 (Cycles only). Present in 4.4.0.
- Inputs: `Color` (RGBA), `Position` (Vector), `Direction` (Vector), `Weight`.
- Output: `BSDF` (Shader).
- Behaviour: acts like a Transparent BSDF, but a ray that enters it is
  teleported to `Position` and continues in `Direction`. If Position/Direction
  are left at the incoming values it is a plain passthrough. EEVEE has no
  equivalent.

Official manual:
https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/ray_portal.html
(The manual explicitly lists "a camera feed on a screen" — i.e. replacing ray
position and direction — as a use case. That is exactly the bake mechanism.)

---

## 2. The baking mechanism

A camera renders a **flat plane laid out in UV space** (the 0..1 square). That
plane carries a Ray Portal material that, for every point, **redirects the ray
back onto the corresponding point of the real 3D mesh**. The redirected ray hits
the real, lit surface and returns its shaded colour — so the render is the real
surface read out into UV layout.

Two pieces of geometry are involved:

- **Real mesh** — stays in the scene at its true location, with its real
  material and the scene lighting. This is what actually gets sampled.
- **Flat copy** — the same mesh flattened into UV space (each vertex moved to
  its UV coordinate). It carries, as attributes captured *before* flattening,
  each point's original 3D position and normal. Its material is the portal.

Camera ray → hits the flat copy at UV (u,v) → portal teleports it to that
point's real 3D position, pointing into the surface → hits the real mesh → shades
it (with lighting) → colour returns to the UV pixel.

---

## 3. Verified recipe

Portal material on the flat copy:

```
Attribute("orig_pos") ─┐
                       ├─ (VectorMath ADD) ── Position ┐
Attribute("orig_nrm") ─┴─ (Scale ε ~0.02) ┘            ├── Ray Portal BSDF ── Material Output
Attribute("orig_nrm") ── (Scale -1) ────────  Direction ┘
```

- **Position** = `orig_pos + orig_nrm * ε` (start just above the real surface;
  ε ≈ 0.01–0.02).
- **Direction** = `-orig_nrm` (point into the surface).
- `orig_pos` / `orig_nrm` are `FLOAT_VECTOR` point attributes on the flat copy,
  set to the real mesh's per-point position/normal before flattening.

Scene:
- Real mesh present and lit; **must remain visible to the post-portal ray**.
- Flat copy positioned so the **camera frames only it** (see gotcha #1).
- Orthographic camera framing the 0..1 UV square (ortho_scale 1, centred on
  (0.5, 0.5), looking straight down the flat copy).
- Neutral colour management (Standard / None) if you want raw values.
- Cycles. Real-time = Cycles viewport progressive rendering.

---

## 4. Tests run (all passed)

All in `prototypes/`, rendered headless with `--python`, Cycles CPU, Blender 4.4.

1. **Mechanism** (`portal_stage1b.py`) — portal plane at the origin, red emission
   target moved off to x=10 (nothing behind the portal). Portal region rendered
   red, surrounding rendered black → the portal genuinely samples a *different*
   surface, not a passthrough.
2. **UV mapping** (`portal_bake.py`) — real plane with emission = a 3D position
   gradient (R=(x+1)/2, G=(y+1)/2). Baked image corners read
   BL≈(0,0), BR≈(1,0), TL≈(0,1), TR≈(1,1) → the 3D surface is correctly laid out
   in UV space. (Absolute values are sRGB-encoded; the gradient direction is the
   proof.)
3. **Lighting** (`portal_lit.py`) — real plane, diffuse white, one point light
   near the +x+y corner. Baked luminance: far corner 0.27, near-light corner
   1.00, the two equidistant corners ≈0.41 each → real lighting is baked into UV.
4. **Curved surface** (`portal_curved.py`) — domed plane (varying normals),
   using per-point `orig_nrm` for the offset and direction. Coverage 1.00 (no
   black holes) and the gradient still reads out → per-point normals handle
   non-flat geometry.

---

## 5. Gotchas discovered

1. **Do NOT hide the real mesh with `visible_camera = False`.** After the portal,
   the continuing ray is still treated as a camera/primary ray, so that flag hides
   the target from the portal too → pure black. Instead, separate the flat copy in
   Z (e.g. +2–3 units) so the ortho camera frames only the flat copy while the
   real mesh stays fully visible to rays.
2. **Curved surfaces need the per-point normal** for both the ε offset and the
   Direction; a constant normal only works for a flat plane.
3. **Cycles only.** No EEVEE equivalent.
4. **Noise.** The manual warns light sampling through portals is inefficient;
   lit bakes are noisier and need more samples / denoising to converge.
5. **Per-corner UVs & seams.** The prototypes use per-vertex UVs on
   single-island meshes. Real meshes have per-*corner* UVs and seams, so a
   production version must split the mesh by UV islands (Split Edges by seams)
   before flattening, and read UVs per face-corner, not per vertex.

---

## 6. Limitations vs. the existing Node Preview add-on

- Node Preview: copies a *material* onto a generic plane, renders it in a
  background process (fast, non-blocking, engine-agnostic, great for tiling
  procedural swatches). No real lighting; shader outputs faked via base colour.
- Ray Portal bake: renders the *real object's real surface* with real lighting
  and mixed shaders into that object's own UVs, live, in-scene. Cycles-only,
  heavier, and it's a scene setup rather than a background render.

They are complementary: procedural tiling swatches → Node Preview; lit
material / lightmap on a specific mesh → Ray Portal bake.

---

## 7. Addon design plan (next step)

Proposed "Ray Portal Bake" operator / panel:

1. Take the selected object (needs a UV map).
2. Duplicate it (linked material, real material kept intact).
3. On the duplicate, build a Geometry Nodes setup:
   - Capture Attribute: position → `orig_pos`, normal → `orig_nrm` (before any
     flatten).
   - Split Edges by seams (so UV islands separate).
   - Set Position ← UV Map (flatten to UV space).
   - Offset the flat copy clear of the original (e.g. +Z) so the camera sees only it.
4. Assign the portal material (Position = orig_pos + orig_nrm·ε, Direction =
   −orig_nrm). Could be a shipped node group so it's almost script-free.
5. Add an orthographic camera framing 0..1, neutral colour management.
6. Two modes:
   - **Live look-dev**: just leave it set up; the Cycles viewport shows the live
     UV bake. Optionally feed the result to Node Preview's image datablock.
   - **Capture**: render the flat copy to an image (file-backed, packable — reuse
     Node Preview's Save-to-File path).
7. Cleanup operator to remove the duplicate/camera when done.

Open questions to resolve while building:
- Cleanest way to do the per-island UV flatten robustly (GN vs. bmesh).
- Whether to reuse Node Preview's background-worker capture or render in-scene.
- Handling multiple materials / multiple UV maps on one object.
- Denoising / sample defaults for acceptable live noise.

---

## 8. References

- Ray Portal BSDF manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/ray_portal.html
- bbbn19 "Blender 5.0 Ray Portal Baking": https://www.youtube.com/watch?v=DLMI6NX08VE
  (demo/projects: https://bbbn19.gumroad.com/l/npekxf , http://gumroad.com/bbbn19)
- Mesh→UV flatten with Geometry Nodes:
  https://b3d.interplanety.org/en/transforming-mesh-to-its-uv-map-with-geometry-nodes-in-blender/
