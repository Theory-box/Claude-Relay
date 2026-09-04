# Shader Node Coverage Map & Porting Plan

Goal: a Workbench-style engine that shows **live node-graph edits** (no baking),
feeding clean texture/albedo info to an AI relighter. Exactness is a bonus, not a
requirement — but where we port Blender's own GLSL we get it for free.

Strategy: the transpiler walks the graph from the surface's Base Colour and emits
GLSL. Node math comes from **Eevee's `gpu_shader_material_*.glsl`** (ported, exact)
or hand-written (for simple ops). Every node is validated on the **CPU GL harness**
(`tests/gl_harness.py`, Mesa llvmpipe) — compiles + checks pixel output.

Status legend: ✅ done+verified · 🟡 partial/approx · ⏳ todo · 🚫 out of scope (flat preview)

## What the user actually edits (their stated workflow) — ALL ✅ already
Brighten skybox → Bright/Contrast ✅ · rescale floor UVs → Mapping ✅ ·
darken a wall → Bright/Contrast / Mix / Hue-Sat ✅ · show the texture → Image ✅.
(Requires the **Live Material Nodes** toggle ON.)

---

## CONVERTER
- ✅ Math (all ops), Vector Math (core ops), Map Range (linear), Clamp,
  Mix (color, all 19 blend modes), Separate/Combine Color·RGB·XYZ, Color Ramp
- ⏳ RGB to BW (luminance) — trivial
- ⏳ Float Curve / RGB Curves / Vector Curves — sample the curve → bake LUT into a
  uniform array (or a 1D texture); medium
- ⏳ Blackbody (temp→RGB), Wavelength (nm→RGB) — small LUT/polynomial ports
- 🚫 Shader to RGB (needs full lighting eval)

## COLOR
- ✅ Bright/Contrast, Gamma, Hue/Saturation/Value, Invert, Mix Color
- ⏳ Light Falloff (mostly a passthrough for our purposes)

## VECTOR
- ✅ Mapping (POINT; Z-rotation)
- ⏳ Mapping full XYZ rotation + TEXTURE/NORMAL vector types — small
- ⏳ Vector Rotate, Vector Transform — small ports
- 🚫 Bump, Normal, Normal Map, Displacement, Vector Displacement
  (need real geometry-normal perturbation / tessellation)

## INPUT
- ✅ Texture Coordinate (UV), UV Map, RGB, Value
- 🟡 Tex Coord other outputs (Generated/Object/Normal/Camera/Window/Reflection)
  currently approximated as UV — need world/object pos + normal (we already pass
  vWpos/vNrm in Workbench/Phong) → medium, unlocks skybox mapping
- ⏳ Attribute, Color Attribute, Vertex Color (read a named mesh attribute → bind
  as a vertex attribute) — medium, ties into the GN-attribute idea
- 🟡 Fresnel, Layer Weight (view-dependent; doable with normal + view dir) — medium
- 🚫 Geometry, Object/Particle/Point Info, Tangent, Wireframe, Bevel, AO node,
  Light Path (either need scene data we don't pass, or are ray/screen-space)

## TEXTURE  (port from Eevee GLSL — the big breadth win)
- ✅ Image Texture (unconnected Vector → mesh UV, fixed)
- ⏳ **Noise** — port `gpu_shader_material_tex_noise.glsl` (+ hash + base noise +
  fractal). FOUNDATION: pulls in the shared hash/noise files everything else uses.
- ✅ **Voronoi** — F1 (Distance/Color/Position), 3D Euclidean, exact hash (F2/edge/other metrics todo)
- ⏳ **Wave** — `_tex_wave.glsl` (depends on noise/fractal)
- ✅ Checker, Gradient (all types), White Noise, Wave (bands/rings x sin/saw/tri), Brick · ⏳ Musgrave, Magic
- ⏳ Environment Texture + Sky Texture — equirectangular/sky mapping; relevant to
  "skybox" if it's a World/Environment setup rather than a plain image on a mesh
- 🚫 Point Density, IES (volumetric / light data)

## SHADER (BSDF)
- ✅ Principled / Diffuse / Emission → read the Base Colour / Colour input
- ✅ Non-traceable surfaces (Mix Shader, node groups, …) → fall back to base texture
- 🚫 Glass/Glossy/Refraction/SSS/etc. as closures (light transport, not colour) —
  we only ever read their colour inputs

---

## Porting order (one at a time, each harness-verified)
1. **Noise foundation**: hash + base noise + fractal + Noise node.  ← START HERE
2. Voronoi, Wave (reuse the foundation).
3. Tex Coord Generated/Object/Normal + Fresnel/Layer Weight (unlocks skybox + more).
4. RGB to BW, Blackbody, Wavelength, Vector Rotate/Transform (quick wins).
5. Curves (Float/RGB/Vector) via baked LUT.
6. Musgrave, Brick, Checker, Gradient, Magic, White Noise.
7. Environment/Sky (if the client's skybox needs it).
8. Attribute/Color Attribute/Vertex Color.

Each port: fetch Blender's `.glsl` (+ deps) → adapt (`float3`→`vec3`, drop
out-param/`g_data` conventions) → add to HELPERS → wire the handler to call it →
harness test (compiles + output sane). GPL note: Blender's GLSL is GPL-2.0-or-later;
this addon is GPL, so that's fine.
