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

## v0.4.0 — per-pixel (Phong) shading mode (headless-validated 4.4.3)
- shaders.py refactored: lighting extracted into LIGHT_CHUNK (LIGHT_UNIFORMS +
  vlr_light() + vlr_shadow()), used from the vertex stage (Gouraud) or fragment
  stage (Phong) so each program declares the light uniforms exactly once.
  - MAIN_VERT (Gouraud) now calls vlr_light/vlr_shadow -> vLight (unchanged look).
  - PHONG_VERT passes vWpos/vNrm/vColor/vBounce/vUV; PHONG_FRAG lights per-fragment
    (per-fragment shadow lookup too -> smoother shadow edges).
  - MAT_FRAG_HEAD/MAIN_{VERTEX,PIXEL}: material (live-node) frags for each mode.
- props.shading_mode enum VERTEX|PIXEL (default VERTEX). ui: Shading box.
- engine: _get_main_shader(mode) caches one program per mode; draw loop reads
  vls.shading_mode, selects base + material program by mode; material_shader
  cache keyed by (mat.name, mode) so switching mode compiles once and reuses.
- _release_gpu_caches clears the per-mode shader dict.
- Tests: test_shading_modes.py (base + material frags per mode, no duplicate
  light uniforms across stages, mode changes the fragment). Full suite (5) green.
- NOT GPU-tested here: the actual per-pixel look. User confirms on GPU.

## USER GPU TEST (v0.4.0):
1. Render ▸ Shading ▸ switch Per-Vertex <-> Per-Pixel. Per-Pixel should show
   sharper specular-free diffuse falloff on large faces (no Gouraud banding) and
   cleaner shadow edges. Works with Live Material Nodes on and off.
2. Confirm re-entering rendered mode repeatedly stays smooth (v0.3.1 leak fix).
3. Confirm the Material Properties tab shows the material again (v0.3.1 panels fix).

## v0.4.1 — fixes from 2nd GPU session (perf leak + material tab + live-node safety)
PERF (the "gets slow, persists after leaving, worse on re-enter, had to quit"):
- Root cause: _gi_redraw_timer forces every VIEW_3D to redraw @20fps while
  _gi_active is True, and _gi_active is only reset inside view_draw. Leaving
  rendered mode while GI runs left it stuck True -> timer hammered redraws forever
  (persisted after leaving; a 2nd engine on re-enter made it worse).
  Also: v0.3.1's free() cleared ALL shader/program caches -> full recompile on
  every re-entry = the brutal re-enter slowdown.
- Fixes: (a) view_draw stamps _last_draw_time; timer only tags redraws if a draw
  was seen in the last 0.5s -> self-heals even if free() isn't called (VALIDATED:
  stale timestamp => timer does not tag). (b) free() sets _gi_active=False + stops
  GI + drops instance refs, and NO LONGER clears the shared shader caches (the
  viewport GPU context persists across enter/leave, so they stay valid).

MATERIAL TAB MISSING (add/remove material slots gone):
- Code was correct (EEVEE_MATERIAL_PT_context_material.poll = (ob or mat) and
  engine in COMPAT_ENGINES; we add VERTEX_LIT to it — verified). The user's tab
  stayed empty almost certainly because installing a zip over a running addon
  keeps the OLD module loaded. Resolution is a clean reinstall + restart, not a
  code change. (No code change needed; confirmed via poll introspection.)

LIVE NODES "breaks materials":
- Graceful degradation: material_shader._compile now marks a material failed
  (engine uses the working base-texture path) if the transpiler hit ANY
  unsupported node in the base-colour path — so live nodes never renders magenta;
  it only enhances fully-supported graphs. (VALIDATED headless: Noise->BaseColor
  => failed + reason.)
- Added console diagnostic: "[VertexLit] material 'X' (MODE): <reason/compile
  error>" so a GPU-side compile failure is visible. NEED FROM USER: that console
  line when the toggle is on, to fix any compile-but-renders-wrong case.

OPEN / NEED USER INPUT:
- Which Render-panel settings "do nothing" (likely GI/shadow settings that need a
  Sun light / GI enabled to show effect). Ask user to specify.
- Live-node visual bug on user GPU if materials are fully-supported yet still wrong
  -> need the console line + a description (black? wrong colour?).

## v0.4.2 — rebuild-loop chug + solid-color diagnosis (from 3rd GPU session log)
CONSOLE showed a REBUILD LOOP: "rebuilt 7 objs (0.9s) / GI started / GI sample 4 /
rebuilt 7 objs / GI started ..." repeating -> GI never converges -> perpetual
forced-redraw storm (also flooded 'SpaceNodeEditor tree_type 2' warnings) =
persistent chug. Root: something re-sets _dirty every ~1s; prime suspect is
Material update events (from live-preview editing and/or new_from_object churn
with preserve_all_data_layers) forcing a full geometry re-extract.
Fixes:
- TIME-BASED ABSORB: view_update ignores all depsgraph updates for 0.4s after a
  rebuild (self._rebuild_time), robustly soaking post-extract churn regardless of
  event count (the fixed 4-cycle drain could expire mid-churn).
- LIVE MATERIAL EDIT != REBUILD: when use_live_nodes is on, a Material update only
  marks the per-material shader dirty (recompiles the small shader) + tags redraw;
  NO full geometry rebuild / GI restart.
- _DEBUG prints "[VertexLit] rebuild <- <reason>" at each _dirty site so the next
  console log names the loop trigger definitively if anything still loops.

SOLID-COLOR-INSTEAD-OF-TEXTURE (live nodes on): added per-compile diagnostic
"[VertexLit] live 'Mat' (MODE): N sampler(s), M param(s) notes=[...]". 0 samplers
on a textured-looking material => the image is NOT in the Base Color path the
transpiler follows (base colour is flat, or the texture is wired to another input;
note non-live _find_base_texture grabs ANY image node, hence the mismatch).
NEED FROM USER: new console log + one material's node graph (is the image plugged
into Principled Base Color, and through what nodes?).
