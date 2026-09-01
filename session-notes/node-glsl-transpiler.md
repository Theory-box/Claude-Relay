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

## v0.3 — kill recompile-on-edit + expand node coverage (headless-validated 4.4.3)
Rewrote node_transpiler.py; updated material_shader.py + engine.py.

RECOMPILE KILL:
- Every unlinked input default (Mapping Scale/Loc/Rot, Mix factor, colours) and
  RGB/Value nodes are now emitted as `uP_N` UNIFORMS (node_transpiler.Param),
  not baked literals. Engine reads live values from the node tree each draw and
  sets the uniforms → dragging a slider updates a uniform, NO recompile.
- `topo_signature(mat)` = structure only (node types/names + operation enums +
  links + image assignments + ColorRamp stops), excludes tweakable values.
  material_shader.get_program reuses the compiled program while the signature is
  unchanged; recompiles only on structural change. engine.view_update now calls
  material_shader.mark_dirty (a structure re-check flag), not invalidate.
- Verified: value edit → identical GLSL + identical signature (no recompile);
  structural edit (vector_type / operation) → signature changes.

GLSL TYPE TRACKING: added _var_type/_param_type + type-aware _coerce so a
float/vec-producing node (Math, Value, SeparateXYZ) feeding a colour input is
up-cast to vec4 correctly (was a latent type-mismatch risk).

EXPANDED COVERAGE (all emit expected GLSL, tested in tests/test_coverage.py):
  MATH (add/sub/mul/div/pow/min/max/trig/…, use_clamp), VECT_MATH (add/sub/mul/
  cross/dot/distance/length/normalize/reflect/project/scale/…), MAP_RANGE
  (linear+clamp), CLAMP (minmax/range), HUE_SAT, GAMMA, BRIGHTCONTRAST, INVERT,
  SEPARATE/COMBINE (Color/RGB/XYZ), VALTORGB/ColorRamp (linear/constant/ease),
  RGB, VALUE, MIX_RGB blend types (mix/add/mul/sub/screen/divide/darken/lighten/
  difference), MIX(RGBA). Unsupported still → magenta + note.
- IMPORTANT 4.4 gotcha: handler dispatch is `_n_<node.type.lower()>` and some
  type strings differ from the idname — HUE_SAT (not hue_saturation), SEPXYZ,
  COMBXYZ, SEPRGB, COMBRGB, VALTORGB, BRIGHTCONTRAST, UVMAP. Handlers named to match.

### Tests (all pass on 4.4.3)
- test_transpiler_spike.py: mapping uniformized; scale 2→4 leaves GLSL + signature
  identical (recompile killed); structural edit changes signature; mix; no-nodes.
- test_coverage.py: ~18 node types emit expected tokens, all balanced, none
  unsupported; Math operation change alters signature.
- test_wiring_headless.py: addon register/unregister clean; frag structurally
  valid; samplers match; unsupported degrades safely.

## Remaining limitations / next actions
1. ColorRamp stops + Math/Mix OPERATION enums are structural (change → recompile).
   Mapping/Mix/colour VALUES are uniforms (no recompile). Could uniformize ramp
   stops too (fiddly; arity varies) — deferred.
2. Mapping rotation is Z-only (UV plane). Noise/Voronoi/Musgrave not yet ported
   (need Blender's exact GLSL for matching output). Bump/Normal need derivatives.
3. Per-material shader compile still happens on first use / structural edit; a
   warm shader precompile pass could hide the first-frame hitch.
4. Verbose coerced GLSL (correct; compiler folds it).
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

## v0.3.1 — fixes from first GPU session (headless-validated 4.4.3)
- MATERIALS NOT SHOWING: custom engine wasn't in the material panels' COMPAT_ENGINES.
  Added engine._register_panels(): adds 'VERTEX_LIT' to every panel Workbench uses
  (incl. EEVEE_MATERIAL_PT_context_material = the material selector) + the node
  'surface' panel. Removed on unregister. (test_panels_and_leak.py)
- "CHUGGIER EACH RE-ENTER" leak: free() only stopped GI, leaving module-level GPU
  objects (main/shadow shaders, shadow map, tex cache, per-material programs) to
  accumulate stale-context objects across rendered-mode re-enters. Now free()
  releases instance resources + _release_gpu_caches() clears the shared GPU caches
  (lazily rebuilt next draw); unregister() also releases. Best-effort — needs GPU
  confirmation that re-enter no longer degrades.

## REQUESTED NEXT (not started): shading modes + SSAO
- Shading mode enum: Per-Vertex (Gouraud, current) vs Per-Pixel (rasterized/Phong:
  vert passes world normal+pos, lighting loop moves to fragment). Shader restructure.
- SSAO: offscreen pass (color+depth[+normal]) → AO shader → composite. Multi-pass.
  Both are visual-only (untestable headless) → build + user GPU-confirms.
