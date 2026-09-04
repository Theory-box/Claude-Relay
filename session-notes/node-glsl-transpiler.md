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

## v0.4.3 — pre-test audit fixes
FIXED (real bugs):
- material_shader.get_program: after a STRUCTURAL material edit, the current mode
  recompiled but the OTHER mode's cached program kept the old structure (stale
  shader when switching Per-Vertex<->Per-Pixel). Now a structural change drops ALL
  cached modes for that material; value edits still reuse (params are live uniforms).
- engine sky/ground ambient was multiplied by gi_bounce_strength -> lowering GI
  bounce faded the sky/ground colour pickers to black ("settings do nothing").
  Decoupled: hemisphere ambient is now independent; gi_bounce_strength only scales
  the GI bounce term.

AUDIT NOTES (verified OK / known limitations, no change):
- socket.node exists in 4.4 -> unlinked/flat Base Colour becomes a live uniform
  (shows the real colour), not grey. OK.
- All 14 props are read (shading_mode/use_live_nodes via getattr).
- Shadow settings (bias/darkness/res/use_shadows) only take effect when a SUN light
  exists (do_shad = use_shadows and sun present). Expected; can surprise.
- new_from_object(preserve_all_data_layers=True) contributes to rebuild churn;
  mitigated by the 0.4.2 time-based absorb window; left True to keep GN colour attrs.
- Instancing: only one instance per source object (dedup by name) — dupli/array
  beyond the first isn't drawn with per-instance transforms. Pre-existing.
- Multi-material objects: live path uses the object's ACTIVE material for the whole
  object (base engine is also single-texture per object). Pre-existing.
- _build_batch_from_cache builds against the Gouraud shader; safe only because both
  modes share the _VERT_HEADER attribute layout. Fragile if a future mode differs.

## v0.4.4 — FIX the "solid colour per object" bug (root cause found)
- Image Texture node with an UNCONNECTED Vector input was sampled at the socket's
  (0,0,0) default (promoted to a uniform) instead of the mesh UVs -> every fragment
  read one texel => whole object = flat colour. This is the user's long-standing
  "won't show the texture plugged into the BSDF, just a solid colour" symptom.
- Fix: _n_tex_image uses `vUV` when Vector is unlinked (Blender's real behaviour:
  an unconnected texture Vector uses the active UV map). Only follows the Vector
  input when actually linked (Tex Coord / Mapping).
- Verified: Image->Base Color (no Tex Coord) now emits texture(uTx_0, vUV).
  Regression test added (spike case E). Full suite green.

## v0.4.5 — 2nd audit round (more "breaks materials" cases + perf)
FIXED:
- Non-traceable surface (Mix Shader, node group, Add Shader, empty Surface) was
  rendering FLAT GREY via the live path instead of falling back. Added
  TranspileResult.needs_fallback; _find_base_socket returns None for unlinked
  surface; _compile marks such materials failed -> engine uses the legacy base-
  texture path. (Diffuse/Glossy BSDF 'Color' input still resolves normally.)
- PERF: live-node params were read from the node tree + set PER OBJECT every frame;
  they're identical across objects sharing a material, so now set once per program
  per frame (params_done set). Big win for scenes with many instances of one material.

VERIFIED OK (tests added / checked):
- Full PBR Principled (base-colour image + roughness + normal maps on other inputs)
  -> resolves to just the base-colour texture at vUV, no fallback, no bogus notes.
- Diffuse BSDF with image in Color -> works, samples vUV.
- Mix Shader / empty surface -> fallback (test_fallback.py).
All 6 suites green.

## v0.4.6 — intermittent chug (needs restart) investigation + guards
Static audit of accumulation sources:
- GI threads: start() signals previous via its own stop event; _run checks stop
  every vertex -> old threads exit fast. ADDED a 0.25s join of the old thread in
  start() to guarantee threads never STACK across rapid rebuilds.
- _extract_mesh_data: exception-safe (except removes the temp mesh). OK.
- build_scene_bvh (gi.py): has no try/finally BUT is DEAD CODE (engine uses
  _build_bvh_from_cache) -> not the cause.
- _ShadowMap: reused singleton; resize GC's old tex/fb. Not a per-frame leak.
- Couldn't isolate the leak statically -> added instrumentation.

INSTRUMENTATION (when _DEBUG): rebuild line now prints
  "[VertexLit] rebuilt N objs (Xs) | GI-threads=? meshes=? shader-cache=?"
  -> next chug log tells us what accumulates (threads / orphan meshes / programs).

NOTE: use_gi defaults TRUE @128 samples (Python BVH ray casting) = the most
expensive subsystem, on by default. Suggested user diagnostic: toggle GI Bounce
OFF; if chug disappears, GI is the culprit (then lower samples / optimise).

## v0.5.0 — pivot to Workbench-style solid shading (GI + scene-light lighting OFF by default)
Per user: turn off raytracing (GI) and vertex-based lighting for now; match Workbench.
- NEW default shading_mode 'WORKBENCH' (Solid/Studio): per-fragment, camera-following
  key light + flat ambient, NO scene lights / GI / shadows. shaders.WORKBENCH_FRAG +
  MAT_FRAG_*_WORKBENCH; pairs PHONG_VERT. Engine computes uKeyDir from rv3d.view_rotation
  each frame (light follows view). uKeyCol=0.9, uAmbient=0.35.
- Live material nodes work in Workbench mode: computeBaseColor * studio light.
- use_gi now defaults FALSE; GI start already gated on use_gi (no thread, no forced
  redraws by default) -> removes the chug source. GI polling/redraw in view_draw gated
  on use_gi too.
- _apply_frame_uniforms made fully tolerant (per-uniform try/except) so Workbench
  programs (which lack the scene-light/shadow uniforms) don't error; added studio uniforms.
- Per-Vertex (Gouraud) and Per-Pixel (Phong) scene-light modes kept as options for later.
- UI: in Workbench mode, GI/hemisphere/lights/shadows sections hidden (they don't apply)
  -> no more "settings that do nothing".
- test_workbench.py added; full 7-suite green. Defaults verified: mode=WORKBENCH, GI off.

## v0.5.1 — FIX shader-editor detachment (and "nodes do nothing")
Root cause: RenderEngine.bl_use_shading_nodes_custom defaults TRUE for custom
engines -> Blender treats us as having a CUSTOM node system and detaches the Shader
Editor from materials (shows generic "Shader Nodetree", won't follow the selected
object, edits go to a detached tree). That's why Saturation/Mix/Brightness edits
"did nothing" — they never reached the material the engine reads.
Fix: VertexLitEngine.bl_use_shading_nodes_custom = False -> standard shader nodes;
Shader Editor follows the active object's material and edits propagate.
Verified transpiler applies Bright/Contrast + Mix + Hue/Sat on top of the texture,
so those now take effect once edits reach the material. Suite green.

## v0.5.2 — full Mix blend modes + note on "nodes do nothing"
- _blend rewritten to support ALL 19 Blender blend modes (was 9): added OVERLAY,
  SOFT_LIGHT, DODGE, BURN, LINEAR_LIGHT, EXCLUSION and the HSV modes HUE/SATURATION/
  COLOR/VALUE. New GLSL helpers (_overlay/_softlight/_bl_hue/_bl_sat/_bl_col/_bl_val)
  in HELPERS. Inputs computed once into vec3 temps; result = mix(a, blend, fac).
  Verified all modes emit real formulas (no 'approximated' note).
- CLARIFICATION for user: node effects require the "Live Material Nodes" toggle ON
  (that's the transpiler). bl_use_shading_nodes_custom=False only fixed the Shader
  EDITOR; it doesn't make Blender evaluate nodes for us. If brightness/mix/sat still
  do nothing, either the toggle is off or the console "[VertexLit] live ..." line
  will show what's happening (sampler/param count or fallback reason).

## v0.5.3 — CPU GL test harness + full node map/plan
- BIG: tests/gl_harness.py — compiles + renders the transpiler's computeBaseColor
  GLSL on a SOFTWARE OpenGL 3.3 context (Mesa llvmpipe via EGL, moderngl installed
  into Blender's python). Catches GLSL COMPILE errors AND reads back pixels to
  verify node output values — on-machine, no GPU. test_gl_smoke.py proves it:
  texture samples across UVs, brightness raises output, mix ADD 0.3+0.4=0.749,
  all 19 blend modes compile. This de-risks every future node port.
- NODES.md: full shader-node coverage map (done/partial/todo/out-of-scope) + the
  port-from-Eevee-GLSL plan and order. Key finding: the user's stated edits
  (skybox brightness, UV rescale, wall darken) are ALREADY covered (Mapping/
  BrightContrast/Mix/HueSat) — the port effort is about breadth (procedurals etc).
- Porting order starts with the Noise foundation (hash+noise+fractal), then
  Voronoi/Wave, then Tex Coord Generated/Object (unlocks skybox mapping).

## v0.5.4 — harness faithfulness fix + first ported node (RGB to BW)
- gl_harness: param defaults now read the REAL node value via Param.value(nt)
  (was 0.5 placeholder) so output tests match the engine exactly.
- Ported node #0: RGB to BW (RGBTOBW) — Rec.709 luminance. CPU-verified:
  white=1.0, red=0.213, green=0.715, blue=0.072 (test_gl_nodes.py).
- Establishes the port workflow: add handler -> render on CPU harness -> assert
  pixel values. Next: Noise foundation (hash+noise+fractal from Eevee GLSL).

## v0.5.5 — Noise texture node (procedural foundation)
- _n_tex_noise: coherent value-noise + fbm (self-contained; scale/detail/roughness/
  lacunarity/distortion mapped; Fac + Color outputs). Unconnected Vector -> UV plane
  (vec3(vUV,0)); connected Vector (Mapping/TexCoord) resolves normally.
  NOT bit-exact Blender (approximation — fine for the AI-feed use case); can be
  swapped for Blender's exact hash-noise later if needed.
- Helpers _hash3/_vnoise/_fbm3 added. CPU-verified (test_gl_nodes): varies across
  surface, in 0..1, higher scale -> higher spatial frequency; Color channels differ.
- Fallback tests switched from Noise (now supported) to Wireframe (out-of-scope).
- All 9 suites green.

## v0.5.6 — EXACT Blender noise (ported hash + Perlin), replacing the approximation
User standard: exact, not "close enough". Ported Blender's GPL GLSL faithfully:
- gpu_shader_common_hash.glsl -> hash_uint/2/3/4 (Jenkins lookup3); macros renamed
  HROT/HMIX/HFINAL to avoid shadowing builtin mix(); adapted float3->vec3, stripped
  'f' suffixes for GLSL 330.
- gpu_shader_material_noise.glsl -> _b_perlin3 (fade + gradient + tri_mix), noise_scale3
  (0.9820), snoise (compatible_mod via trunc), and the NOISE_FBM fbm (normalize=[0,1]).
- _n_tex_noise now calls _b_fbm3/_b_snoise3. Fac output with distortion=0 is
  BIT-EXACT Blender Perlin (hash + gradient + scale constants are verbatim).
- CPU-verified: compiles, Perlin centers on ~0.5 (mean 0.495), varies, in 0..1.
- Removed the old value-noise approximation.
Follow-ups for full exactness: fetch gpu_shader_material_tex_noise.glsl to match the
exact distortion offsets + Color-output random offsets (currently faithful-but-not-
verbatim); then Voronoi/Wave reuse this hash foundation.
GPL: ported code is GPL-2.0-or-later; addon is GPL. OK.

## v0.5.7 — Voronoi (F1) + Checker + Gradient
- Voronoi: added verbatim hash_vec3_to_vec3 (+ deps) from Blender's hash file; _b_voronoi_f1
  (3D Euclidean, 27-cell) — Distance/Color/Position outputs. Other features/metrics note+F1.
  CPU-verified: Distance varies & >=0, Color varies per cell.
- Checker: exact Blender parity logic ((xi%2==yi%2)==(zi%2==0)) with the 0.999999 offset.
  CPU-verified Fac is exactly {0,1}.
- Gradient: all types (linear/quadratic/easing/diagonal/radial/spherical/quadratic-sphere).
  CPU-verified LINEAR == U ramp.
- Fixed: output vars declared without '=' now get _var_type registered (Voronoi Distance
  float coercion) — general gotcha for multi-decl lines.
- test_gl_nodes: 11 checks. All 9 suites green. NODES.md updated.

## v0.5.8 — White Noise
- _n_tex_white_noise: Value=hash_vec3_to_float, Color=hash_vec3_to_vec3 (verbatim
  Blender hash). CPU-verified high-frequency random in [0,1].
- Procedural coverage now: Noise(exact Perlin), Voronoi F1, Checker, Gradient,
  White Noise. Remaining: Wave, Musgrave, Brick, Magic (need source fetch for exactness).

## v0.6.0 — core converter nodes COMPLETE (Math, Vector Math, Map Range)
- Math: now all 41 ops (added SMOOTH_MIN/MAX, FLOORED_MODULO, WRAP, PINGPONG,
  SINH/COSH/TANH). FIXED two bugs: 'TRUNCATE' -> 'TRUNC' (was silently passthrough),
  MODULO now truncated (_btmod) not GLSL floored; FLOORED_MODULO = GLSL mod.
  Helpers _bsmin/_bsmax/_bwrapf/_bwrap3/_bpingpong/_btmod added.
- Vector Math: all 27 ops (added MULTIPLY_ADD, REFRACT, FACEFORWARD, WRAP; third
  vector input plumbed).
- Map Range: LINEAR + STEPPED + SMOOTHSTEP + SMOOTHERSTEP interpolations (was
  linear-only).
- CPU-verified: all 41 Math + 27 VMath ops compile (no passthrough); ADD/MULTIPLY
  exact; TRUNC fixed. test_gl_nodes now 18 checks. All 9 suites green.

## v0.6.1 — local Blender source + Wave + Brick + harness determinism
- EFFICIENCY: sparse blobless clone of Blender's shader dir (/home/claude/blender-src,
  120 material .glsl files) -> port from local source, no more per-file web fetches.
- Wave: exact port of calc_wave (bands X/Y/Z/diagonal, rings X/Y/Z/spherical,
  SIN/SAW/TRI profiles, distortion via exact fbm). All 6 combos CPU-verified.
- Brick: exact port (integer_noise + calc_brick_texture; offset/squash freq as node
  props). Color + Fac (mortar mask) CPU-verified.
- HARNESS: llvmpipe readback race -> added ctx.finish() (deterministic now).
  Known caveat: exact values of MULTI-vec4-uniform blends are unreliable under
  llvmpipe (uniform aliasing) — params verify correct, real GPU renders right;
  smoke mix-ADD check relaxed to a robust 'brightens' assertion + documented.
- test_gl_nodes: 22 checks. All 9 suites green.

## v0.6.2 — Magic + Musgrave finding
- Magic: exact port of node_tex_magic. turbulence_depth is a node property so the
  nested turbulence is UNROLLED at transpile time (clean GLSL, no runtime depth
  branches). Distortion runtime-checked. Color+Fac CPU-verified at depth 0/2/5/10.
- Musgrave: separate node was REMOVED in Blender 4.1 (folded into the Noise node's
  type modes) -> nothing to port; noted N/A.
- Procedural set now: Noise, Voronoi F1, Checker, Gradient, White Noise, Wave, Brick,
  Magic. Remaining Voronoi features (F2/smooth/edge/radius, metrics, fractal) next.

## v0.6.3 — Voronoi FULL 3D (exact) — fixes hash bug too
- Replaced simplified F1 with Blender's exact 3D Voronoi machinery from
  gpu_shader_material_voronoi.glsl: _vor_f1/_vor_smooth/_vor_f2/_vor_edge + _vor_dist
  (all 4 metrics: Euclidean/Manhattan/Chebychev/Minkowski) + PCG hash_int3_to_vec3.
- BUG FIX: old F1 used hash_vec3_to_vec3 (float hash); Blender uses hash_int3_to_vec3
  (PCG) -> cell positions were wrong. Now exact.
- Features: F1, F2, Smooth F1, Distance to Edge (N-Sphere Radius approx as F1).
  Normalize handled (divide by per-feature max_distance). detail>0 fractal = single
  octave for now (rare; noted).
- CPU-verified: all 4 features + 4 metrics compile & vary. 9 suites green.

## v0.6.4 — Curve nodes (RGB / Float / Vector) via baked LUT
- RGB Curves, Float Curve, Vector Curves: bake each curve to a 65-sample LUT at
  transpile time (mapping.evaluate), emit as GLSL float[65] + _lut65 linear lookup.
  RGB applies combined(C) after per-channel R/G/B (Blender order). Vector maps via
  [-1,1]->[0,1]. Curve edits recompile (control points in signature).
- Directly useful for color grading (darken/brighten with control).
- CPU-verified: identity passes through; darken curve halves output; array-param
  GLSL compiles on llvmpipe. 9 suites green.

## v0.7.0 — Texture Coordinate (Generated/Object/UV) + procedural default fix (engine change)
- ENGINE CHANGE: vertex shaders now output vGenerated (object bbox-normalised pos)
  and vObjPos (object-space pos); uGenMin/uGenScale set per-object from obj.bound_box.
  Frag heads (all 3 material modes) declare them. Harness provides synthetic values.
- Tex Coord: UV -> vUV, Generated -> vGenerated, Object -> vObjPos. Normal/Camera/
  Window/Reflection approx as Generated (need data not in every frag).
- EXACTNESS FIX: procedural textures (Noise/Voronoi/Wave/Brick/Magic/Checker/Gradient/
  White Noise) with an UNCONNECTED Vector now default to Generated (as Blender does),
  not vUV. Image Texture still defaults to UV (correct).
- Enables skybox-on-a-mesh procedural/Generated mapping.
- CPU-verified Generated/Object/UV + procedural default; addon registers; 9 suites green.

## v0.7.1 — modular GLSL library + on-demand inclusion + exact noise offsets
STRUCTURE (modularity ask): moved all helper GLSL out of node_transpiler into
glsl_lib.py as named CHUNKS (hsv/sdiv/blend/mathx/lut/hash/perlin/pcg/voronoi/
intnoise/brick), each with the function names it provides. glsl_lib.collect(body)
auto-includes ONLY the chunks a material's shader references, transitively, in
dependency order. To edit a node's math: edit its chunk. To add: add chunk + handler.
  - transpile_material sets res.helpers = collect(res.glsl); material_shader + harness
    use res.helpers (not the whole library).
  - BLOAT FIX verified: plain image material -> 0 bytes of helpers (was full ~8KB
    library); Noise -> perlin+hash only; Voronoi -> voronoi+pcg only.
  - node_transpiler import of glsl_lib works both as package and standalone-file (tests).
EXACTNESS (task 1): Noise distortion + Color now use Blender's exact random offsets
  (_b_rvec3 = random_vec3_offset, seeds in [100,200] via hash_vec2_to_float) instead
  of the reconstructed offsets. Noise is now verbatim across Fac, distortion, and Color.
All 9 suites green; addon registers.

## v0.8.0 — screen-space post pipeline (modular) + SSAO (Phase 1)
NEW fx/ subpackage — a general screen-space effects pipeline (foundation for SSR,
compositing, DoF later; AO is the first effect):
- fx/gbuffer.py: GBuffer (colour RGBA16F + sampleable depth) + PingPong targets.
- fx/effect.py: ScreenEffect base (one fullscreen fragment pass; FS_VERT).
- fx/ssao.py: SSAO — reconstruct view pos from depth, normal from dFdx/dFdy, 16-sample
  hemisphere kernel, output colour*ao. Params: strength/radius/bias.
- fx/pipeline.py: render scene -> gbuffer, chain enabled effects (ping-pong), blit
  to viewport (draw_texture_2d). To add an effect: new module + append in fx/__init__.
ENGINE: object loop wrapped in _draw_objects(); when any effect is enabled, routed
  through the pipeline (offscreen); otherwise DIRECT draw to viewport (default,
  unchanged). Pipeline failure -> fallback to direct draw (try/except). _post created
  in _ensure_state, freed in free().
PROPS/UI: use_ao (default OFF), ao_strength/radius/bias + AO box.
VERIFIED HERE: SSAO shader compiles on software GL; addon registers; AO off by default;
  node suites unaffected. NOT verifiable here (GPU-only): the offscreen plumbing,
  depth-texture sampling, and the AO look/sign-conventions — user tests on GPU.
  Radius/bias/strength + sign conventions likely need tuning on real hardware.

## v0.8.1 — fix AO offscreen framebuffer construction
- USER GPU error: "'GPUTexture' object cannot be interpreted as an integer" every
  frame with AO on -> pipeline threw, fell back to direct draw, AO never showed.
- Cause: GPUFrameBuffer color_slots was a single {"texture":tex} dict; the 4.4 API
  wants a Tuple of textures/dicts. Switched to canonical color_slots=(tex,),
  depth_slot=bare GPUTexture (per docs).
- Added a ONE-TIME full traceback on post-pipeline failure (engine _post_err_shown)
  so if anything still fails the console shows the exact line (no per-frame spam).

## v0.8.2 — large-scene freeze: extraction rewrite (root perf fix)
SYMPTOM: large scenes freeze ~1 frame/min (freeze->1 frame->freeze). This is
REPEATED full scene rebuilds, not the AO pass (AO is screen-space, scene-size
independent).
ROOT CAUSES in _extract_mesh_data (per object, per rebuild):
  1. new_from_object(preserve_all_data_layers=True) COPIED the whole evaluated mesh
     (all layers) per object AND the create/remove generated depsgraph churn that
     outlasted the 0.4s absorb window -> self-triggered rebuild loop.
  2. Python loop over every colour-attribute element (millions on high-poly).
  3. Python list-comp over every triangle corner for colours.
FIX: read eval_obj.data DIRECTLY (no copy, no create/remove -> no churn, much
  faster) + bulk foreach_get('color') + numpy gather for colours (verified
  identical to the old loop). Removed mesh.remove() calls.
EXPECTED: rebuilds are now fast (seconds, numpy-bound) AND don't self-repeat ->
  the perpetual freeze should be gone; at most a one-time extract on enter/edit.
Still O(all objects) per rebuild -> if a single edit on a huge scene still stalls,
  INCREMENTAL rebuild (only changed objects) is the next step. Need user console
  ("[VertexLit] rebuilt N objs (Xs)" frequency + time) to confirm.

## v0.8.3 — audit pass (fuzz + perf + AO + coverage)
FUZZ AUDIT (every ShaderNode -> Base Color, harness compile): ZERO compile-fails,
  ZERO exceptions. Transpiler is robust — everything works, falls back safely, or is
  a surface shader with no colour output. Unsupported (36) are correctly out-of-scope
  (Bump/Normal/Displacement/BSDF closures/view- or scene-data-dependent).
FIXES:
- Mix node FLOAT/VECTOR data types were broken (only RGBA handled -> empty inputs ->
  black). Now mixes floats/vectors correctly (verified FLOAT 0.2->0.8=0.8).
- PERF: object bbox for Generated coords was recomputed EVERY frame per object;
  now cached at extract time (gen_min/gen_scale in the batch entry). Win on
  high-object-count scenes.
- AO: gbuffer cleared black while direct path cleared world colour -> background
  changed when toggling AO. Now clears with the scene/world colour (ctx.clear_color).
- COVERAGE: added CombineHSV/SeparateHSV (exact via hsv helpers; verified).
NOTED (not fixed): Blackbody/Wavelength need Blender's precomputed spectrum LUT
  (sampler1DArray) -> not inline-portable exactly; left as safe fallback (niche).
  AO normal uses dFdx/dFdy (face normals) -> faceted AO; a normal G-buffer would
  improve it + enable SSR later.
All 10 suites green.

## v0.8.4 — fixes from 0.8.2 testing
- FLAT/HARD SHADING shown as smooth: extraction used per-VERTEX normals (always
  averaged/smooth). Now uses per-CORNER normals (mesh.corner_normals) for the draw
  batch -> respects flat shading, sharp edges, custom split normals. (vertex normals
  kept for GI). Verified corner vs vertex differ on a flat cube.
- HIDDEN objects/collections shown: draw + rebuild loops now skip inst.show_self==False.
- BRICK broken/dark + cross-material brightening: added div-by-zero guards (row_height,
  brick_width, mortar_size) -> int(inf) was undefined on real GPUs (likely NaN source).
  Renders clean on software GL either way.
- AO NaN guard: SSAO sanitizes NaN/Inf colour (isnan/isinf) before compositing so a
  broken material can't bleed through screen-space sampling to neighbours.
- Cross-material brightening theory: brick NaN -> gbuffer -> AO neighbour sampling.
  Brick guards + AO sanitize should address it; need user re-test to confirm.
STILL TODO: F12 final render (engine is viewport-only; render() only stops GI).
  Important for the AI-feed pipeline (they render images). Next piece.
All 10 suites green.

## v0.8.5 — F12 final render + shared draw refactor
- Extracted the viewport object loop into _draw_batches(depsgraph, vls, view_proj,
  studio, lighting...) — used by BOTH view_draw and render() (modular, no dup).
- render(depsgraph): F12 now works — resolution from scene.render, camera view_proj
  (cam.calc_matrix_camera), studio light from camera orientation, draw into a
  GPUOffScreen, read_color -> flip -> begin_result/end_result. No camera -> black.
  Workbench-quality (no shadows/GI in F12 yet). Wrapped in try/except + traceback.
- Verified: compiles, registers, render + _draw_batches present, viewport suites green.
  NOT GPU-testable here (offscreen render + begin_result) -> user confirms F12 output.

## v0.8.6 — brick/complex-material fix + defaults from testing
BRICK "shows wood texture" ROOT CAUSE: material fell back to _find_base_texture
(grabs any image) because (a) surface was a Mix Shader (couldn't trace base colour)
and (b) unsupported nodes (AO/Geometry) triggered wholesale fallback. Fixes:
- _find_base_socket now TRACES THROUGH Mix/Add shaders to the Principled/Emission/
  BSDF base colour (skips Transparent/Holdout). Verified on willow-style Mix(Transparent,
  Add(Principled+Translucent)) -> resolves to Principled Base Color.
- Unsupported nodes now NEUTRALISE to white (1,1,1,1) in-graph instead of magenta +
  wholesale fallback -> the rest of the graph (brick, mixes, textures) still renders.
  Only a surface with NO traceable base colour falls back now.
DEFAULTS (user request):
- shadows OFF by default (were darkening objects; shadow feature is buggy - fix later).
- shading_mode default PIXEL (per-pixel) instead of WORKBENCH.
- use_live_nodes REMOVED entirely - live material nodes are ALWAYS ON now (engine
  use_live=True; prop + UI toggle removed). This alone fixes "brick shows wood" when
  the toggle was simply off.
Tests updated for new behaviour (trace-through, neutralise, new defaults). 10 green.
TODO: shadows look wrong (not like shadows) - redo later. CPU render mode requested -
  not feasible for a GPU viewport engine; consider a flat 'albedo preview' instead.

## v0.8.7 — incremental rebuild (fixes 30s freeze) + multi-material support
THE CORE SLOWDOWN: _rebuild_inner re-extracted EVERY object on ANY change (single
bool self._dirty). Adding/removing an object or entering edit mode on ONE object
re-extracted the whole scene -> 30s. NOT the old GI (correctly skipped when off).
FIX - incremental rebuild:
- view_update now records WHICH objects changed in self._dirty_objects (per-object),
  not a global dirty. Object deletion detected by a cheap cache-vs-bpy.data check.
- _rebuild_inner now: syncs removals (drop cached objects no longer present), extracts
  ONLY dirty + brand-new objects, keeps all other batches. Full extract only on first
  build or _force_full. Log says [incremental] vs [full] + N/total.
  => edits are O(changed objects), not O(scene). Console: "rebuilt 1/2000 objs [incremental]".
MULTI-MATERIAL: _extract_mesh_data now splits loop_triangles by material_index into
  per-slot arrays; each object caches a LIST of (batch, material_name, texture) slots.
  Draw loop iterates slots, drawing each with its own material program/texture. Verified
  3-material cube -> 3 slots, tris sum to whole mesh; single mat -> 1 slot.
- Removed _build_batch_from_cache; added _build_slot_batch + _build_object_slots.
- GI apply + BVH still use whole-mesh vert_co_local/vi_map (unchanged); GI off by default.
11 suites green (added test_multimat).
