# Node → GLSL Transpiler — session notes

**Branch:** `feature/node-glsl-transpiler` (off `feature/blender-vertex-lighting`, main merged)
**Blender target:** 4.4 (tested against a downloaded 4.4.3 build, headless)
**Goal:** live, un-baked material preview — show procedural / mix / UV-distortion
materials in the viewport by transpiling the shader node graph to GLSL, instead
of Workbench-style single-texture display or the old bake-to-PNG approach
(`node_preview_live`, feature/node-preview).

## Direction decision (this session)
- Discovered existing work before building:
  - `vertex_lit_renderer` (feature/blender-vertex-lighting) — real custom
    RenderEngine: Gouraud per-vertex lighting, 8 lights, shadow map, progressive
    GI, texture cache. BUT shades from ONE base texture (`_find_base_texture`),
    so it has Workbench's blind spot for node graphs.
  - `node_preview_live` (feature/node-preview) — the BAKE approach the user wants
    to move away from (spawns headless Cycles/EEVEE → PNG → shows on mesh).
  - `goal_node_compiler` — UNRELATED: compiles node graph → OpenGOAL Lisp (.gc)
    for gameplay entities. Not a shader tool. Not reusable here.
- Chosen approach: build the transpiler as a module INSIDE vertex_lit_renderer,
  emitting *surface base colour* GLSL that feeds the engine's existing lighting
  ("transpile ingredients; the engine cooks them"). Avoids reimplementing Eevee.

## v0.1 — spike (DONE + tested headless on 4.4.3)
`addons/vertex_lit_renderer/node_transpiler.py`
- `transpile_material(mat)` walks back from Output→(Principled Base Color |
  Emission Color), topo-emits GLSL into `vec4 computeBaseColor(vec2 vUV)`.
- Supported node subset: TEX_COORD(.UV), MAPPING(POINT: scale/loc/Z-rot),
  TEX_IMAGE(.Color/.Alpha), MIX_RGB + new MIX(RGBA), unconnected→default_value.
  Unsupported nodes degrade to magenta (visible, non-fatal).
- Returns `.glsl`, `.samplers` (uniform_name+image for the engine to bind),
  `.ok`, `.notes`.
- Pure-Python (bpy data API only, no gpu import) → fully testable headless.

### Test: `tests/test_transpiler_spike.py` — ALL CHECKS PASSED on 4.4.3
- Case A: TexCoord.UV → Mapping(scale 2, loc .1) → Image → Base Color.
  Verified the image is sampled with the MAPPED coords, i.e. UV distortion is
  applied in-shader → **live, no bake**. Mapping scale/loc baked into the GLSL.
- Case C: changing Mapping scale 2→4 changes the emitted GLSL (distortion tracked).
- Case B: adding a Mix node emits `mix(img, red, fac)` (mix shows live).
- Case D: node-less material → flat `diffuse_color`.
- GPU compile of the emitted GLSL is NOT testable headless
  ("GPU functions for drawing are not available in background mode") — shader
  COMPILE + visual output must be confirmed on the user's GPU.

## v0.2 — wired into the engine (opt-in, headless-validated)
`material_shader.py` + edits to `engine.py`, `props.py`, `ui.py`.
- NEW `material_shader.py`: build_material_frag(mat) assembles a full fragment
  (MAIN_VERT shared + declared uTx_ samplers + computeBaseColor + main that does
  `outColor = vLight * base`). get_program(mat) compiles + caches per material;
  compile is wrapped in try/except → on failure the entry is `failed` and the
  engine falls back to the legacy single-texture path for that material.
  invalidate(name) drops a material's program (called on Material update).
- engine.py: extracted `_apply_frame_uniforms()` (shared by legacy + per-material
  shaders, since all frame/light/shadow uniforms live in MAIN_VERT). Draw loop
  now: if `use_live_nodes` and the object's material compiles, bind that
  material's program (frame uniforms set once per shader per frame via an
  id()-set), bind its samplers (image resolved per-draw via _get_gpu_tex so image
  edits refresh without recompiling), draw; else legacy path unchanged.
- props.py: `use_live_nodes` BoolProperty, **default OFF** (zero regression when
  off). ui.py: "Materials" box with the toggle.
- Material-update invalidates that material's program → graph edits recompile.

### Validated headless on 4.4.3 (`tests/test_wiring_headless.py`, ALL PASS)
- Addon register()/unregister() clean with all edits; VertexLitEngine registered;
  toggle present and defaults OFF.
- build_material_frag: main()+computeBaseColor+outColor present, braces/parens
  balanced, declared samplers == used samplers, unsupported node (Noise) degrades
  to a structurally-valid magenta frag and is reported in notes.
- NOT testable headless (no GPU context): the actual GLSL COMPILE
  (`gpu.types.GPUShader`) and the visual result. Fallback-on-compile-fail exists
  precisely because compile can only be judged on the user's GPU.

## USER GPU TEST (next):
1. Load branch `feature/node-glsl-transpiler`, enable the addon, set engine to
   Vertex Lit, tick Render ▸ Materials ▸ "Live Material Nodes".
2. On a UV-mapped object: add Mapping between Tex Coord and Image, change Scale →
   texture should tile/shift live. Add a Mix (image ↔ colour) → should blend live.
3. Watch the console for "[VertexLit]" and any GPUShader compile errors. If a
   material shows its base texture instead of the graph, its shader failed to
   compile (fallback) — grab the console error.

## Remaining limitations / next actions
1. Mapping params baked as literals → recompiles on edit. Promote scale/loc/rot
   to uniforms (avoids recompile-on-slider). TOP follow-up.
2. **Mapping params are baked as literals** → shader recompiles on every slider
   edit. Follow-up: promote scale/loc/rotation to uniforms so edits don't recompile.
3. Coerce helper round-trips scalars/vectors through vec4 → verbose (but correct)
   GLSL. Cosmetic cleanup; GLSL compiler folds it.
4. Rotation is Z-only (UV plane) for the spike; add full XYZ if needed.
5. Node coverage to grow tier by tier: Math, Vector Math, ColorRamp, Map Range,
   Separate/Combine, RGB/Value, Hue/Sat, Checker/Gradient/Wave/Brick, Noise/
   Voronoi (port Blender's GLSL for exact output). BSDF stays "read its inputs",
   never rendered as a closure.

## Not started (deferred by user: "foundations first")
- Per-object shading overrides.
- Geometry-Nodes attributes → engine inputs (read mesh.attributes, bind as vertex
  attrs to drive colour/lighting).
