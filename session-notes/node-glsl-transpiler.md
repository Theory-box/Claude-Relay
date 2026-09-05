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

## v0.8.8 — Vector Rotate + type-aware neutralize (coordinate-collapse class fix)
USER FINDING: brick broke when a Vector Rotate fed its coords; removing it fixed brick.
ROOT CAUSE: Vector Rotate was UNSUPPORTED -> neutralised to WHITE (1,1,1). For a
VECTOR/coordinate node white is a constant -> collapses the whole coord chain ->
downstream texture shows one colour. Silent + hard to diagnose (user's exact point).
FIXES:
- Implemented Vector Rotate (node type is VECTOR_ROTATE, not VECT_ROTATE): axis-angle,
  X/Y/Z axis, Euler XYZ, center + invert. Exact port of rotate_around_axis + euler mat3.
  New glsl_lib chunk 'vecrot'. Verified angle 0 = identity, 90deg transforms.
- TYPE-AWARE NEUTRALIZE (_neutral_for): unsupported node's neutral now matches its
  OUTPUT type: VECTOR -> pass through a vector input (identity) so coords survive, else
  vGenerated; VALUE -> 1.0; RGBA -> white. Was: always white.
AUDIT (every vector-output node): NONE collapse to a constant now. Handled(10) /
  pass-through(Bump/Displacement/Normal/VectorTransform/Bevel) / vGenerated-default
  (ObjectInfo/NewGeometry/etc.). The coordinate-collapse class is gone.
11 suites green (+vrot check).

## v0.8.9 — progressive (non-blocking) material shader compilation
COMPLAINT: 20s "getting scene ready" freeze vs instant Workbench. Cause: the FIRST
frame compiled EVERY visible material's GLSL shader synchronously (GPU driver compile
~100-300ms each) before anything drew. Workbench uses one pre-compiled shader.
FIX - budgeted progressive compile:
- material_shader.get_program(mat, mode, may_compile=False) PEEKS (returns cached-or-
  None, never blocks on a GPU compile).
- Draw loop: peek first; only actually compile a material's shader if within this
  frame's ~40ms time budget, else draw it with the fast base-texture path and set
  self._mat_pending. Scene shows instantly; materials "pop in" over the next frames.
- view_draw tags a redraw while _mat_pending -> keeps upgrading until caught up.
So no up-front freeze: first frame ~instant (Workbench-like base textures), full
node materials fill in progressively. Geometry extraction (numpy, already fast +
incremental) is the only remaining first-load cost and is inherent.
11 suites green.

## v0.9.0 — progressive geometry streaming (no first-load freeze)
The "how do game engines do it" answer: persistent GPU buffers (we have via incremental
rebuild) + stream work over frames (never block). Added the last piece:
- _rebuild_inner now extracts at most ~40ms of meshes per frame; remaining objects go
  back into _dirty_objects and are extracted next frame(s). self._geo_pending keeps
  view_draw redrawing until the scene is fully loaded. Objects pop in progressively.
- GI (off by default) only starts once streaming completes.
- Console: "loaded 40/2000 objs (0.04s) [full] (+1960 streaming)".
Now the full pipeline is non-blocking: incremental rebuild (only changed objects) +
progressive geometry (stream in) + progressive shader compile (~40ms/frame). No 20-30s
freezes; entering the mode / big edits build up over ~1s instead of hanging.
Rejected the "second Blender instance" idea: huge IPC/sync complexity for what a
per-frame budget solves.
STILL OPEN: intermittent Mix/Brick "whole material darkens, fiddle-to-fix" bug — needs
the user's actual node graph to reproduce + read the generated GLSL (non-deterministic
= likely a specific value issue; can't pinpoint blind).
7 spot-checked suites green.

## v0.9.1 — load speed: kill wasted per-object work; multicore analysis
PROFILED extraction (why "simple" objects feel slow): a CUBE extracts in 0.17ms (fine);
a 16k-vert mesh is ~27ms. So slow objects are just dense. Breakdown: Blender foreach_get
on loop_triangles vertices(4ms)+loops(3ms) + per-corner numpy expansion(~6ms) dominate.
BIGGEST WASTE FOUND: shadow batch was built for EVERY object even though shadows are OFF
by default, and it used a PYTHON list-comp over every triangle = 6.6ms/dense-object on
data nobody draws.
FIXES:
- Skip shadow batch entirely when shadows off (default) -> ~7ms/dense-object saved.
- Shadow batch (when on) uses numpy reshape (0ms) not a python loop.
- Drop vi_map.tolist() per object (keep numpy); GI/shadow consumers handle numpy.
- Scheduling: while geometry is STREAMING, shader compile yields (0 budget) so the two
  budgets don't stack (~80ms->~40ms/frame during load); materials compile once geo done.
MULTICORE (user asked): limited fit. The dominant cost is Blender's foreach_get mesh
reads + GPU batch upload, both MAIN-THREAD ONLY (bpy data + GPU context aren't thread
safe). The parallelisable part (numpy expansion ~6ms) is already fast C. A worker-thread
pipeline could overlap read+process for ~1.3-1.5x at real complexity/risk -> deferred.
Bigger levers: the shadow skip (done) + mesh density (dense meshes are inherently slower
to upload). Incremental rebuild already means each mesh extracts ONCE.
Suites green.

## v0.9.2 — technical-debt / perf audit
FIXED (real):
1. CONTINUOUS IDLE REDRAWS when shadows OFF (default): _rebuild set _shadow_dirty=True,
   but it's only cleared in the shadow pass, which never runs when shadows are off ->
   _gi_active stayed True -> viewport redrew forever at max FPS pinning the GPU while
   idle. Fix: clear _shadow_dirty when shadows off; _gi_active only counts shadow_dirty
   when do_shad. Now idles like Workbench.
2. topo_signature per-object per-frame while editing: the draw loop peeked get_program
   per SLOT per OBJECT; for a dirty material the peek runs topo_signature (walks all
   nodes+links). A dirty material on N objects -> N sig computes/frame. Fix: resolve each
   material's program at most ONCE per frame (frame_progs dict).
NOTED (debt / future, not fixed):
- Per-frame frame-uniforms scale with material count: each unique shader gets ~48
  uniforms/frame (Workbench = 1 shader). Fundamental to per-material shaders; proper fix
  is a shared UBO (GPUUniformBuf + std140 block) -> deferred (bigger refactor). Matters
  for material-heavy scenes.
- Minor bounded leaks: _prog_cache/_tex_cache keep entries for deleted materials/images
  until re-enter (cleared by _release_gpu_caches on unregister). Low priority.
- GI (gi.py 317 lines) + shadow system are large chunks for off-by-default experimental
  features. No per-frame cost when off (verified) but real complexity debt; candidates
  for extraction/removal if they stay unused.
- Many bare `except Exception: pass` (defensive) can mask real errors; `except
  (ValueError, Exception)` is redundant (cosmetic).
No dead functions found. 11 suites green.

## v0.9.3 — general realtime updates + live edit mode
GENERALISED view_update (no more case-by-case):
- One rule: ANY is_updated_geometry on a mesh object -> re-extract THAT object. Covers
  modifier add/remove/toggle, geo-nodes, new objects, etc. automatically.
- Mesh-datablock geom updates -> mark cached objects sharing it (linked dupes/edit).
- Transforms -> matrix read live in draw (no re-extract), only shadows re-render.
- Materials -> mark_dirty (shader peek at draw); Images -> tex invalidate; deletions synced.
- Processes ALL updates in the depsgraph (removed the early `return` that only caught the
  FIRST change -> batch edits on many objects now all update).
REMOVED obsolete churn-era THROTTLING: the 0.4s post-rebuild "absorb window" + drain_cycles
  ignored every update for 0.4s after a rebuild -> laggy/missed updates while editing. Gone
  now that extraction reads eval_obj.data (no datablock churn to absorb). Updates are immediate.
LIVE EDIT MODE: view_draw re-extracts ONLY context.edit_object each frame (its eval mesh
  reflects the live edit cage) via a direct fast path (no full-scene sync) + forces redraw
  -> geometry edits show in real time. Bounded to one object; stops on leaving edit mode.
Removed dead _view_update_OLD (62 lines). Suites green.
CAVEAT (user to test): edit-mode re-extract is per-frame for the edited object; a very
  dense edited mesh (~16k+ verts = ~27ms) will edit at ~15-30fps. Fine for typical meshes.

## v0.9.4 — raw-memory extraction (ctypes) — ~2.2x faster, no build
PROTOTYPED + MEASURED the ctypes raw-memory read vs foreach_get (user's ask before
committing to a compiled route):
- Core geometry (positions+uvs+tri indices): foreach 11.6ms vs RAW 2.4ms = ~5x, bit-exact.
- Full _extract_mesh_data: 24ms -> 10.7ms = ~2.2x.
HOW: Blender stores mesh data as contiguous CustomData attribute arrays. mesh.attributes
  ['position'/'.corner_vert'/UVMap].data[0].as_pointer() + mesh.loop_triangles[0].as_pointer()
  give the raw addresses; np.ctypeslib.as_array reads them with ZERO copy. Eliminates the
  slow loop_triangles.foreach_get('vertices'/'loops') (~7ms). Pure Python, NO compiled
  extension, NO cross-platform build.
SAFETY: every raw read has a foreach_get FALLBACK (returns None on any layout surprise ->
  slow path). So a future Blender that changes the layout stays CORRECT, just slower.
  Stored arrays (vert_co_local) are .copy()'d so they never alias freed Blender memory.
ALSO: single-material fast path — was masking+copying every corner array 4x even for 1
  material; now one slot with no masking (big chunk of the remaining time). Dead code removed.
Regression test test_extract_raw.py (raw == foreach, missing-attr -> None). 12 suites green.
CONCLUSION: the ctypes route gets ~2.2x with no build burden; a full compiled extension
  would add fragility + per-platform builds for little extra (GPU upload still main-thread,
  can't reuse Blender's cached batches). Not pursuing compiled unless this proves insufficient.

## v0.9.5 — audit before test: fix broken edit-mode live update
AUDIT (pre-test) findings:
- Extraction edge cases (empty/no-uv/byte-color/float-point-color/subsurf/loose-verts):
  ALL robust, no exceptions (raw path + foreach fallbacks + None on empty). GOOD.
- Depsgraph update coverage: ADD object / ADD+TOGGLE+CHANGE modifier all fire
  is_updated_geometry on the mesh object -> view_update catches them (re-extract).
  MOVE fires transform only -> correctly NOT re-extracted (live matrix). GOOD.
- BUG FOUND: live edit mode was BROKEN. In edit mode the EVALUATED mesh is empty
  (0 verts) and obj.data is stale — the live geometry lives only in the edit BMesh.
  So _extract_mesh_data returned None and the edit-mode feature did nothing.
  FIX: write the edit BMesh to a reused temp mesh (bm.to_mesh, ~0.5ms) and extract from
  that. Verified it reflects live vertex edits. _extract_mesh_data gained a `mesh=`
  override; self._edit_tmp persistent temp mesh, freed on teardown; mat_slot falls back
  to obj.active_material.
12 suites green (+test_extract_raw).

## v0.9.6 — persistent extraction cache (fast re-entry into rendered view)
PROBLEM (user): leaving+re-entering rendered view re-extracted the WHOLE scene, because
the mesh cache + batches lived on the engine INSTANCE, which Blender destroys on view exit.
FIX: persist the CPU extraction DATA at module level (_PERSIST_MESH) + a cheap per-object
geometry signature (_PERSIST_SIG). Across engine instances:
- Re-entry reuses the stored extraction data (the SLOW part) and only rebuilds the GPU
  batches fresh (fast, ~1-2ms/obj, and always valid in the current context — we do NOT
  persist GPU batches to avoid stale-context crashes).
- A cheap signature (vert/poly count + modifier state + 3 sampled vertex positions) detects
  changes made while we weren't watching (e.g. edited in Solid mode) -> re-extract only those.
- Unchanged objects are reused (verified: same sig=reuse; modifier or vertex edit=re-extract).
- Cleared on unregister (_release_gpu_caches) since GPU context is gone then.
Console now reports "loaded N/M objs [full] (K reused)". Re-entry with no changes reuses
everything -> just fast batch rebuild, no extraction.
9 suites green.

## v0.9.7 — persist GPU BATCHES too (0.9.6 still rebuilt them -> visible reload)
0.9.6 persisted DATA but rebuilt every batch on re-entry -> streamed in visibly ("reloads
most objects"). Now persist the GPU batches (_PERSIST_BATCH/_SHADOW) as well:
- Re-entry: verify sigs ONCE, mark only CHANGED objects dirty; unchanged objects keep
  their persisted batch and draw immediately -> no work, instant.
- SIG HARDENED: use the ORIGINAL mesh name (obj.data.name), not the temp evaluated mesh
  name (which can change across evaluations and would break reuse).
- SELF-HEAL: batch.draw wrapped in try/except; if a persisted batch is stale (GPU context
  changed on re-entry), the draw raises -> drop it + mark dirty -> re-extract next frame.
  So worst case == the old behaviour (no crash, just re-extract), best case == instant.
- Persist cleared on unregister.
DIAGNOSTIC: on re-entry, NO "re-extracted" console line (or small N) = batches reused
  (instant). "re-extracted 200/200" = batches were stale in this GPU context -> self-healed.
10 suites green. Need user's console on re-entry to confirm batches survive their context.

## v0.10.0 — REMOVE old vertex lighting + GI (roadmap item 1/7)
User roadmap: (1) remove vertex lighting/GI [DONE], (2) matcaps, (3) sun+rasterised
shadows rewrite, (4) outline fx, (5) AO object exclusion, (6) transparency, (7) mask/
depth/ID passes.
REMOVED:
- Per-Vertex (Gouraud) shading mode entirely (MAIN_VERT/MAIN_FRAG, MAT_FRAG_*_VERTEX).
  Shading modes now: WORKBENCH (Solid studio) + PIXEL (per-pixel lit, default).
- The whole GI system: gi.py (317 lines, ProgressiveGI thread), BVH build, per-vertex
  bounce colours (bounceColor attr, uBounceStrength), _apply_gi_update, and the GI redraw
  timer (_gi_redraw_timer/_gi_active/_last_draw_time). Redraws now driven purely by
  tag_redraw (streaming/edit/materials) + a one-shot shadow redraw.
- GI props (use_gi/gi_samples/gi_rays_per_pass/gi_thread_pause/gi_bounce_strength) + UI.
- extraction: vert_no_local + mat_diffuse (GI-only) dropped; vert_co_local kept (shadows).
KEPT: rasterised shadow MAP (that's item 3 to fix, not vertex-based), hemisphere ambient,
  energy_scale, per-pixel Phong lighting. ~400 lines lighter (3600->3192). 12 suites green.

## v0.10.1-0.10.3 — outline + AO exclusion + transparency (roadmap 4,5,6/7)
- 0.10.1 OUTLINE (fx/outline.py): depth-edge silhouette (object->background + view-space
  depth discontinuity); width + sensitivity + colour; slots into fx chain after AO.
- 0.10.2 AO EXCLUSION: per-object Object.vlr_ao_exclude prop + UI. Pipeline renders a
  separate AO-depth of only non-excluded occluders when any object is flagged; SSAO
  samples that (uDepth override) so flagged objects don't cast/receive AO. No cost when
  none flagged.
- 0.10.3 TRANSPARENCY: transpiler folds Principled Alpha input into base-colour alpha
  (verified 0.4->0.4, 1.0->opaque). Draw loop is now two-pass: opaque (depth write) then
  transparent (materials with blend_method=='BLEND') sorted back-to-front, alpha-blended,
  depth-write off. Frags already output base.a.
All GPU-side (visual) -> user tests. 13 checks + 12 suites green.

## v0.10.4 — transparency detection fix + Workbench-style (object-ID) outline
- TRANSPARENCY FIX: Blender 4.2+ moved the control — new materials default blend_method
  ='HASHED'; the alpha-BLEND control is now surface_render_method=='BLENDED'. Was only
  checking blend_method=='BLEND' -> never detected. Now checks surface_render_method
  =='BLENDED' OR blend_method=='BLEND'. (User sets material Render Method = Blended.)
- OUTLINE REWRITE to match Workbench: read the actual workbench_effect_outline_frag —
  it samples a per-object ID buffer; opacity = 1 - fraction of 4 neighbours whose id ==
  centre id. Replaced the depth-based silhouette with this: new ID_VERT/ID_FRAG flat-
  colour shader, pipeline renders an object-ID buffer (each object a unique colour) when
  outline on, Outline effect samples it with the exact Workbench edge formula. Now every
  object is outlined (incl. touching same-depth), thin + soft at corners like Workbench.
  Removed outline_threshold (unused).
Suites green; ID + outline shaders compile.

## v0.10.6 — render GPU context + outline alpha/exclusion + AO quality
- RENDER (F12) FIX: added bl_use_gpu_context=True to VertexLitEngine. render() draws with
  the gpu module, which needs a GPU context Blender only provides when this flag is set;
  without it every GPU call in render() failed ("GPU functions not available"). Likely the
  reason F12 never worked. (Can't test headless -> user confirms.)
- OUTLINE ALPHA: outline_color is now RGBA (size 4); shader multiplies edge opacity by the
  alpha (uLineAlpha) so outline opacity is adjustable.
- OUTLINE EXCLUSION: Object.vlr_outline_exclude; excluded objects render the reserved id
  (1,1,1) into the id buffer; the outline shader treats reserved-id pixels as never-outlined
  and reserved neighbours as "same" -> no outline on/around excluded objects.
- AO QUALITY: ao_samples enum (16/32/64); SSAO kernel expanded to 64, loops uSamples and
  normalises by it. Fixed a GLSL name clash (loop count N vs normal N -> NS).
UI: AO quality dropdown + AO/outline exclude toggles for the active object. Suites green.

## v0.10.7 — NODE GROUPS supported (fixes "plank gen"/brick materials)
Root cause of intermittent brick/plank materials: node GROUP was unhandled -> neutralised
(white passthrough), and because the graph signature was built from Blender's unsorted
node/link iteration, the signature was unstable -> the same material recompiled every frame
with a varying number of neutralised-group notes.

Fixes:
- GROUP tracing: _n_group inlines the group's tree. The Group Output input matching the
  requested output is followed inward; Group Input references resolve to the enclosing
  instance's EXTERNAL inputs via a _group_stack. Nested groups supported.
- Nested-group aliasing/recursion fix: a group's external input is resolved in the PARENT
  context (pop the current frame first) — otherwise two groups sharing an interface socket
  identifier (e.g. both "Socket_0") aliased and recursed forever (was the MemoryError).
- Per-instance cache key: emit_node cache key now includes the group-stack ids so a group
  instanced multiple times resolves per instance.
- Param tree binding: Param gained tree_name; params created inside a group read their live
  value from bpy.data.node_groups[tree_name] instead of the material tree (previously the
  node lookup failed -> uniform defaulted to 0, e.g. Invert Fac 1->0 silently dropped the op).
- Signature: _tree_sig recurses into group trees (editing a group now recompiles) AND sorts
  node/link parts -> deterministic, so no more per-frame recompile churn.
- Samplers already stored the image datablock directly, so group-internal image textures bind.
New: tests/test_group.py (GPU-verified passthrough / invert / nested). 13 suites green.

## v0.10.8 — Reroute nodes + group-input types (fixes plank Width/Length/scale)
Diagnosed from user's real Plank Gen: the ONLY unhandled node was NodeReroute. Length/Width
route through long reroute chains into Brick Texture's Brick Width (socket 8) / Row Height
(socket 9); every reroute was neutralised to a constant, so Width/Length did nothing and
plank proportions ("scaling") were wrong.

Fixes:
- _n_reroute: pure passthrough (returns emit_node of its single input, no coercion) so the
  value keeps its source type. Coercing per hop stacked conversions down a chain -> (((x).x).x).x.
- Group input natural type: the GROUP_INPUT resolver was hardcoding want="vec4", turning a
  float group input (e.g. Length) into a vec4 uniform. Now uses the external socket's natural
  type via _socket_glsl(); Length/Width come through as distinct float uniforms.
- Vector Math SCALE already reads its factor by socket name ("Scale"), so scaling itself was
  never wrong — it was the frozen Brick Width/Row Height. No change needed there.
New: tests/test_reroute.py — structural proof (Length/Width become distinct float uniforms,
feed the brick, bind live, no coercion artifact, compiles). 14 suites green.
Note: the gl_harness llvmpipe multi-vec4-uniform caveat makes pixel-exact brick diffs flaky,
so validation is structural, not pixel-based.

## v0.10.9 — Cavity (Workbench curvature: ridge+valley) + as_pointer cache fix
CAVITY effect (fx/cavity.py) — Blender Workbench-style screen-space curvature:
- New view-space NORMAL prepass: shaders.py NORMAL_VERT/FRAG (encode view normal *0.5+0.5);
  engine _get_normal_shader + normals_cb draws all geometry when cavity on; pipeline
  _ensure_normal + normal pass -> ctx['normal_tex']. View normals via uViewMat3 (view 3x3) *
  per-object normal matrix.
- Curvature = (nUp.y-nDown.y)+(nRight.x-nLeft.x); >0 convex -> ridge (brighten), <0 concave ->
  valley (darken); factor=clamp(1+curv*strength,0,4)*colour. Uses the object-id buffer to skip
  inter-object boundaries (id pass now runs for outline OR cavity).
- props: use_cavity, cavity_ridge, cavity_valley; UI cavity box; effect order SSAO->Cavity->Outline.
- cavity.run always draws (passthrough factor 1 if no normal buffer) so it can never black out.

CRITICAL FIX — emit_node cache used id(out_socket); Blender socket wrappers are ephemeral, so a
GC'd wrapper's address gets reused and id() collides -> a group's Width could resolve to Length
(uP_8,uP_8) non-deterministically (hash-seed/GC dependent). Now keys on as_pointer() (stable C
pointer) for both sockets and group-stack nodes. Verified stable across PYTHONHASHSEED 0-7.
14 suites green. (Discovered via flaky test_reroute — a real bug, not a test artifact.)

## v0.10.10 — Cavity World/Screen split + world ridge + backface-cull toggle
Matching Blender's two overlayable cavity types:
- Renamed UI "Ambient Occlusion" -> "Cavity World" (SSAO); its strength relabelled "Valley",
  radius "Distance", samples "Quality". Internal props keep ao_* names.
- Renamed UI "Cavity" -> "Cavity Screen" (the curvature effect from v0.10.9) — unchanged logic.
- NEW world-space RIDGE (ao_ridge) added to the SSAO shader alongside the untouched valley:
  per sample, reconstruct the neighbour's view position, dir=neighbour-P; dot(dir,N)<0 means the
  surface curves away (convex) -> brighten. Applied as colour *= ao * (1 + edg*uRidge). uRidge=0
  reproduces the old valley-only output exactly (background samples skipped to avoid halos).
- BACKFACE CULLING toggle (backface_cull, default True, global). view_draw/render set self._cull
  ('BACK' or 'NONE'); main draw + all prepasses (ao-occluder, id, normal) follow it. UI toggle in
  the Shading box. 14 suites green.

## v0.10.11 — glass over film-transparent + AO exclusion masking
GLASS / FILM TRANSPARENT: with render.film_transparent on, glass showed the checker instead of
what's behind it because ALPHA blending dropped the framebuffer alpha below 1.
- Transparent pass now uses color_mask_set(1,1,1,0): blends COLOUR but leaves the alpha channel
  as the opaque pass wrote it (1 behind objects) -> glass-over-opaque stays opaque; glass-over-
  empty stays transparent. F12 render() clears to alpha 0 when film_transparent so empty film is
  actually transparent and the alpha channel is meaningful.
AO EXCLUSION MASK: an excluded object received AO from geometry BEHIND it (looked see-through)
because SSAO bound uDepth to the occluder depth for the CENTRE pixel too.
- SSAO now binds uDepth=main (visible) depth for the centre P/N and uAoDepth=occluder depth for
  the samples. New exclusion mask: if the visible surface is IN FRONT of the occluder depth
  (z < aoZ), the pixel is an excluded object -> return colour unchanged (no AO). No exclusion ->
  uAoDepth==uDepth, mask never fires. view_pos(sampler2D,uv) now takes the depth tex.
14 suites green. (Opaque materials with alpha<1 + OPAQUE blend still write their alpha; force-to-1
deferred as a rare edge case.)

## v0.11.0 — WORKBENCH 2.0 rebrand + panel overhaul + view modes + background + key light
Big UX/feature refactor (internal engine id stays 'VERTEX_LIT').
- RENAME: engine bl_label + addon name -> "Workbench 2.0".
- REMOVED: shading_mode selector (always PIXEL now; Solid-Studio mode gone from use, WORKBENCH_FRAG
  kept as dead code). Lights + Shadows panels removed (props kept hidden for wiring).
- COLLAPSIBLE PANELS (classic sub-panel classes; layout.panel() absent in 4.4): Lighting / View Mode
  / Background / Shading, with Outline + Cavity World + Cavity Screen as header-checkbox sub-panels
  nested under Shading.
- CAMERA KEY LIGHT: folded into vlr_light as an additive headlamp (uKeyDir view-following, uKeyCol,
  uKeyIntensity). key_intensity slider under Shading. Replaces the old studio mode's key light.
- VIEW MODES (Blender "Color"): Textured (materials, default) | Solid (flat colour) | Random (per-
  object hashed colour) | Attribute (vertex colours) | Normal (N*0.5+0.5). Non-textured modes bypass
  the material programs via a shared VIEWMODE_FRAG (PHONG_VERT) lit by the same hemisphere+key; engine
  _draw_viewmode + _obj_random_color(name).
- BACKGROUND: world hemisphere gradient (world-space, gradient by view-ray world +Z) or flat colour;
  BG_VERT/BG_FRAG fullscreen pass drawn first in _draw_batches (skipped when film_transparent).
  background_mode + background_color props.
New tests/test_workbench2.py (props/panels/shaders/random). 15 suites green.

## v0.11.1 — Random view mode fix + viewport transparency revert
- RANDOM view mode: uGenMin/uGenScale are optimised out of VIEWMODE_FRAG (it never uses
  vGenerated), so the shared per-object try/except in _draw_viewmode threw on uGenMin and
  SKIPPED uObjColor -> random colour never set. Now each uniform is set independently (sf()).
  Solid/Attribute/Normal were unaffected (no per-object uniform).
- Transparency: color_mask alpha-off is now applied ONLY for film-transparent F12 renders.
  The viewport uses plain ALPHA again (its known-good glass behaviour). GPU test confirmed the
  ALPHA blend itself composites objects-behind correctly, so this rules out color_mask as the
  cause of a viewport "glass fades to nothing" report (likely scene-specific — awaiting details).

## v0.11.2 — F12 render fixes + FXAA + Attribute selection
F12 RENDER: was upside-down, ignored effects, wrong hemisphere colours.
- Removed the erroneous np.flipud (read_color is bottom-up, Blender's rect is bottom-up too).
- Hemisphere sky/ground now read from vls (were hardcoded).
- render() now routes through the SAME post pipeline as the viewport when effects are enabled:
  extracted _make_post_ctx(depsgraph, vls, view_proj, view_mat3, proj, w, h, wc, studio, ls_mat,
  sky, ground, bstr, lights) -> (draw_scene, post_ctx), shared by view_draw + render(). F12 now
  shows AO / cavity / outline / FXAA. (film_transparent+effects clear-alpha still a corner case.)
- ANTI-ALIASING: new fx/fxaa.py (FXAA post pass, runs last), aa_method enum (OFF/FXAA, default
  FXAA), in a new collapsible "Settings" sub-panel.
- ATTRIBUTE VIEW SELECTION: view_attribute StringProperty (prop_search over the active mesh's
  color_attributes). _extract_mesh_data(attr_name=...) reads the chosen attribute (blank = active);
  changing it sets engine._FORCE_REEXTRACT which view_draw consumes to drop caches + full re-extract.
15 suites green. (F12 upside-down/effects need on-GPU confirmation.)

## v0.11.3 — F12 animated camera + SSAA + Depth view + Random per-material
- F12 CAMERA: use cam.evaluated_get(depsgraph) for view + calc_matrix_camera + cam_pos + key dir,
  so the ANIMATED camera at the current frame is used (fixes "zoomed in / wrong frame").
- SUPERSAMPLING (SSAA): supersampling enum (1/1.5/2x) in Settings. Pipeline renders gbuffer + all
  prepasses + effects at ss*res and downsamples on the final draw_texture_2d blit; ctx texel uses
  the supersampled res. any_enabled() true when ss>1 so it runs even with no other effect.
- DEPTH view mode: VIEWMODE_FRAG mode 5 -> greyscale by distance(vWpos,uCamPos) mapped between
  depth_min (white) and depth_max (black); depth_min/depth_max props + UI when Depth selected.
- RANDOM per-object vs per-material: random_mode enum. OBJECT -> uObjColor per object (hash name);
  MATERIAL -> uObjColor per slot (hash material name) so shared materials match and multi-material
  objects get one colour per slot.
15 suites green. (F12 camera + SSAA need on-GPU confirmation.)

## v0.11.4 — F12 "4 quadrants" fix (offscreen blit -> direct texture read)
Root cause of the quadrant/low-res F12 render: routing F12 through the post pipeline ended in
draw_texture_2d, which is built for a viewport REGION and misplaces the image inside a GPUOffScreen.
- Pipeline.render(..., blit=True): when blit=False it returns (final_tex, sw, sh) instead of blitting.
- F12 now reads that texture directly via a temp GPUFrameBuffer.read_color, then _area_resize()
  downscales sw x sh -> w x h for supersampling (cumulative-sum area average; correct for any ratio,
  verified 2x + 1.5x). Viewport path unchanged (still blits to the region).
- Active camera: scene.camera is already the active camera; F12 uses the evaluated one (v0.11.3).
15 suites green. (Needs on-GPU confirmation but the blit path is removed for offscreen.)

## v0.11.5 — F12 render depsgraph (Is Viewport) + viewport colour management
- IS VIEWPORT / render geometry: F12 was reusing the viewport's cached convex-hull batches, so
  "Is Viewport" geometry-node branches rendered the preview geo. render() now clears all caches
  and re-extracts fresh from the RENDER depsgraph (Is Viewport=False -> full geo), fully (loops
  _rebuild until _geo_pending clears; _force_full only on the first pass so it converges).
- COLOUR MANAGEMENT: viewport now renders through the pipeline to a texture and blits it via
  self.bind_display_space_shader(scene) / draw_texture_2d / unbind_display_space_shader(), applying
  the scene view transform / look / exposure / gamma — so the viewport matches the F12 render
  (which Blender colour-manages). Always routes through the pipeline now (no separate direct path
  except as an exception fallback). Verified bind/unbind_display_space_shader are real RenderEngine
  RNA functions. draw_texture_2d imported in engine.
15 suites green. (Colour-management match + Is Viewport need on-GPU confirmation.)

## v0.11.6 — Instant material bake to image + render-freeze safety cap
- BAKE: bake.py — rasterise the mesh in UV SPACE (BAKE_VERT: gl_Position = texCoord*2-1) and run
  the transpiled computeBaseColor per texel into a GPUOffScreen, one GPU pass, no ray tracing.
  material_shader.build_bake_frag(mat) assembles head+samplers+params+helpers+computeBaseColor with
  a main that outputs the albedo. Operator vertex_lit.bake_material bakes the active object's active
  material -> a packed Blender image "<mat>_baked" (bake_resolution 512/1024/2048/4096). Bake sub-
  panel under Settings. Reuses _extract_mesh_data slots for geometry; binds params + image samplers.
  tests/test_bake.py (assembly + GPU compile). Shader compile verified; the actual bake needs a real
  GPU (Blender gpu module can't draw in --background).
- RENDER FREEZE: put a 120s wall-clock cap on the F12 full-reextract loop so it can't hang forever
  (proper fix deferred — on the list with glass). 16 suites green.
KNOWN ISSUES LIST: (1) glass compositing over objects; (2) F12 render freeze on very dense geo.

## v0.11.7 — Bake attribute fix ("Unknown attribute 'normal'")
The bake frag only computes base colour, so the GLSL compiler strips unused vertex inputs
(vNrm->normal always; vColor/position too for a UV-only graph). batch_for_shader then errored
when handed an attribute the compiled shader lacked. Fix: query shader.attrs_info_get() and build
the bake batch with ONLY the attributes the shader actually kept (texCoord always included as it
drives gl_Position). 16 suites green. Actual bake still needs on-GPU confirmation.

## v0.11.8 — Bake empty-image debugging (viewport + UV guard + diagnostics)
Bake produced a fully transparent image (nothing rasterised). Added:
- gpu.state.viewport_set(0,0,res,res) inside the offscreen bind (offscreen bind doesn't always set
  the GL viewport -> triangles land nowhere).
- UV guard: raise a clear error if the mesh has no active UV map (all-zero UVs collapse every tri
  to a point -> empty bake).
- Console diagnostic line (slots/verts/uv-range/params/samplers) to pinpoint if still empty.
Can't run the actual bake headless (Blender gpu can't draw in --background) -> user confirms.

## v0.11.9 — Bake reworked: material on a flat 0-1 UV plane (not object UVs)
Per user: don't bake to the object's UVs — evaluate the material as if on a default unwrapped
plane. bake.py now draws ONE fullscreen triangle (PLANE_BAKE_VERT: uv = pos*0.5+0.5; Generated/
Object synthesised for a unit plane) and runs computeBaseColor(uv) per texel into a GPUOffScreen.
No mesh, no UV extraction, no _extract_mesh_data. Only vertex attribute is 'pos' (always used), so
the attribute-optimisation mismatch that plagued the UV bake can't happen. Operator just needs the
active object's active material. test_bake updated. 16 suites green. (Still needs on-GPU confirm.)

## v0.11.10 — Principled Alpha slider works without Render Method = Blended
User: image-alpha leaf works, but the Principled Alpha slider did nothing (default material).
Cause: the alpha WAS folded correctly (n_bc.a *= uP), but the engine only alpha-blends materials
whose Render Method is BLENDED (or legacy BLEND). A default material is DITHERED -> drawn opaque ->
alpha ignored. (The leaf works because that material is set to Blended.)
Fix: TranspileResult.has_alpha=True when the Alpha fold fires (Alpha set/linked); stored on the
program. is_transp now also true when has_alpha and the material isn't explicitly Opaque (handles
both surface_render_method 4.2+ and legacy blend_method). So the Alpha slider alpha-blends without
having to switch Render Method. Verified has_alpha False@1.0 / True@0.5. 16 suites green.

## v0.11.11 — Share batches across linked duplicates (identical geometry)
User: linked-duplicate objects load one by one though they share geometry.
- True instances (geo-nodes/particles/collection) were ALREADY shared (dedup by inst.object name
  in `current`, drawn per-instance). Linked duplicates (Alt+D, same mesh data, different object
  names) were extracted + uploaded separately because the cache keys on object name.
- Added _share_sig(obj, mesh, view_attr) = _geo_sig (mesh data name + counts + modifiers + sampled
  verts) + material assignment + active colour attribute. Extraction loop keeps self._geo_share
  {ssig -> (data, slots, shadow)}: an object whose ssig is already present REUSES the same GPU
  batch (no re-extract/upload) and is drawn per-instance with its own matrix. Reuses are instant so
  they don't consume the extraction budget -> N linked dups = 1 extraction + N-1 instant reuses.
  Position-dependent geo-nodes get different sampled verts -> different sig -> not wrongly merged.
  Only same-mesh-data objects share (data name in the key). Cleared on full rebuild. 16 suites green.

## v0.11.12 — Transparency decided at draw time (fixes finicky glass + opaque-as-transparent)
The v0.11.10 has_alpha flag was baked into the compiled program, but the Alpha value is a tweakable
not in the topo signature -> changing Alpha didn't recompile -> stale flag. Symptoms: opaque object
stuck in the alpha-blend pass (no depth write -> inverted-face sorting artifact); alpha only "took"
after a structural edit forced a recompile.
Fix: _material_transparent(mat) decides transparency from the material's CURRENT state at draw time
(Blended->yes, Opaque->no, else Principled Alpha linked or <1). Cached once per frame (frame_transp).
No recompile needed -> tweaking Alpha is instant; truly opaque materials stay opaque. has_alpha flag
left in place but no longer used for routing. Verified incl. 0.5->1.0 flips to opaque with no
recompile. 16 suites green.

## v0.11.13 — Directional sun (no object) + stackable lighting intensities
Objectless sun: Height (elevation) + Angle (azimuth) -> dir; Sun intensity (0=off) + colour.
- _compute_sun(vls) -> (dir_to_sun, colour, intensity, hemi_intensity); set on self._sun each frame
  (view_draw + render); uniforms uSunDir/uSunColor/uSunIntensity/uHemiIntensity set in
  _apply_frame_uniforms. vlr_light: hemisphere*uHemiIntensity + sun (max(dot(N,sunDir),0)*intensity)
  + key light + scene lights -> all stack. Hemisphere gains hemi_intensity (0=off).
- Cost: one dot product per fragment, no geometry/passes -> free on dense geo (fragment-bound).
- UI Lighting panel: Sky/Ground intensity + colours, then Sun intensity/colour/Height/Angle.
- Matcaps slot (its own intensity) still pending. 16 suites green.

## v0.11.14 — Sun shadows (directional shadow map, objectless sun)
Retargeted the old (buggy, object-tied) shadow system to the objectless sun + made it shadow the
SUN ONLY so ambient/hemisphere fills the shadow (not the whole lighting darkened).
- Shader: vlr_shadow rewritten -> 3x3 PCF, returns lit fraction 0..1 (soft edges). Forward-declared
  so vlr_light can call it. vlr_light applies it to the sun term only. Mains no longer multiply all
  lighting by shadow. uShadowDark -> uShadowSoft (PCF spread).
- Engine: _build_light_space_dir(sun_dir,center,radius) (ortho from the sun direction, not a light
  object). do_shad = use_shadows AND sun_intensity>0. self._sun computed before the shadow logic.
  Shadow pass builds position-only shadow batches lazily (enabling shadows after load works).
  _shadow_dirty re-flagged on enable + sun-direction change (+ existing geometry-change path).
- Props: use_shadows "Sun Shadows", shadow_resolution 1024/2048/4096, shadow_bias, shadow_softness.
  Removed shadow_darkness. UI: shadow controls under the Sun in the Lighting panel.
- Cost: one shadow-map render pass (position-only) + a PCF lookup per fragment. F12 shadows still
  off (viewport only for now). 16 suites green.

## v0.11.15 — Fix sun shadows not showing + move Key Light to Lighting
- SHADOW BUG: the viewport always routes through the post pipeline (since colour management,
  v0.11.5), and _make_post_ctx's _draw_objects hardcoded do_shad=False + dummy depth. So the shadow
  map rendered but was never sampled -> no shadows, no errors. Fixed: _make_post_ctx now takes
  do_shad/s_bias/s_soft/shad_tex and forwards them to _draw_batches; viewport call passes the real
  shadow params. (Fallback direct-draw path already passed them.) F12 still off (defaults).
- Moved Key Light intensity from the Shading panel to the Lighting panel (with hemisphere + sun),
  so all stackable lights live together. 16 suites green.

## v0.11.16 — Shadow quality (normal-offset + slope bias) + Lighting sub-panels
- SHADOW ACNE/BANDING: added normal-offset shadows — vlr_shadow(wPos, N) pushes the sample off the
  surface along N by uShadowTexelWorld*(1.5+3*slope) (auto-scaled to shadow texel world size =
  2*radius*1.6/res), plus slope-scaled depth bias (uShadowBias*(1+4*slope)). Removes self-shadow
  banding without the detachment a big constant bias caused. Default bias lowered 0.0015 -> 0.0004
  (normal-offset does the work now). uShadowTexelWorld uniform set per frame.
- UI: Lighting is now a container (Key Light value input) with collapsible sub-panels Sky/Ground
  and Sun (sun params + shadow controls under Sun). 16 suites green.

## v0.11.17 — Shadow quality: view-fitted shadow map + Shadow Distance (the real fix)
Root cause of low-quality shadows: the shadow map covered the WHOLE scene bounds, so texels were
huge (worse the bigger the scene) -> blocky shadows + a big normal-offset (scaled by texel size) ->
detachment/banding. 4096 didn't help because the map was spread too thin.
Fix — _build_light_space_fit(sun_dir, view_proj, cam_pos, shadow_distance, res, scene_radius):
- Fits the ortho to the CAMERA view frustum clamped to shadow_distance (the "min/max distance"), via
  the frustum's bounding sphere (rotation-stable). Texel size auto-drops (measured ~9x smaller on a
  100u scene -> ~9x sharper) and the normal-offset (texel-scaled) shrinks with it -> clean contact.
- Texel-snapping the sphere centre in light space -> no frame-to-frame shimmer.
- Near plane extended toward the sun by scene_radius so off-frustum casters still cast in.
- Returns texel_world for uShadowTexelWorld (normal offset now correctly small).
- Re-renders the shadow map only when the fit MATRIX changes (view/sun/distance) via _prev_ls_key;
  static view -> cached, orbit -> re-fit. Replaces the old sun-only dirty trigger.
- New prop shadow_distance (default 25) + UI under Sun shadows.
Known: single map (no cascades) so beyond shadow_distance = no shadows; F12 shadows still off. 16 green.

## v0.11.18 — Per-view-mode effect memory + screen-space normal + depth auto-contrast
- PER-VIEW-MODE MEMORY: view_mode update callback (_view_mode_update) saves each mode's effect
  toggles (use_ao/use_cavity/use_outline/use_shadows/aa_method) to a JSON prop (vm_memory) keyed by
  mode, restoring on switch. Depth & Normal first-visit -> all effects OFF (pure passes). Remembers
  if you turn one on. Verified the save/restore/remember cycle.
- DEPTH/NORMAL raw output: skip bind_display_space_shader for these modes so they're not tonemapped
  (pure depth greyscale / normal-map colours).
- NORMAL space: normal_space enum World/Screen; VIEWMODE_FRAG transforms N by uViewMat3 (view 3x3,
  set on self._view_mat3 each frame) for screen-space -> looks like a normal map.
- DEPTH auto-contrast: depth_auto bool (default on) -> range auto-fit from the scene bounds' near/far
  distance to the camera (nearest black, farthest white); manual min/max when off.
- UI: normal_space under Normal; depth_auto + (greyed manual range) under Depth.
DEFERRED (moderate, next session): per-object sun-shadow cast/receive/both dropdown; per-object AO
send/receive/both (receive needs object-ID masking in screen-space). 16 suites green.
