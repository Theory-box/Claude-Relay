# Blender version converter / compatibility scanner — session notes

**Branch:** `feature/blender-converter` (off `main`)
**App:** `apps/blend-compat-scanner/`
**Blender targets tested:** 4.4.3 (source) and 4.2.23 LTS (target), local x64 builds.

## Goal
Real client pain: work happens in 4.4/4.5, client opens in 4.2, things silently
break on their end. Want a tool that says exactly WHAT breaks and WHERE, plus
suggested fixes where a fix exists. Diagnosis is the priority; auto-repair is
secondary and risky.

## Key facts established (empirically, from the binaries — not docs)
- Blender runs headless in the container and **evaluates geometry nodes on CPU**
  (verified: subsurf cube -> 26 verts). So exact output-diffing across versions
  is possible here — reconstruction correctness is testable, not guesswork.
- When an older Blender opens an unknown node: `bl_idname` -> `'NodeUndefined'`,
  `type` -> `'CUSTOM'`, but the node **name is preserved**. This is what makes
  detect-mode reliable.
- **4.4 -> 4.2 break surface (complete, node-level):**
  - 21 missing nodes (19 geometry/function + 2 shader: MetallicBSDF, GaborTex).
  - 7 changed-socket nodes (e.g. ToolSelection output rename, Subdiv +Limit
    Surface, Principled +Diffuse Roughness).
  - Non-node critical: Grease Pencil v3 (4.3+) not openable in 4.2.
- Within 4.x it's NOT a format break (4.2 opens 4.4 files); breakage is only
  from features added in 4.3/4.4/4.5. The 5.0 boundary IS a format break
  (5.x invalid to <4.5) — different problem, handled by the LTS-bridge, out of
  scope for the node scanner.

## What exists now (this session)
- `blend_compat_scanner.py` — walks GN modifiers, materials, worlds, compositor,
  nested groups (cycle-safe). Predict mode (in source, uses DB) + Detect mode
  (in target, finds Undefined). Report-only; never edits/deletes. Tested both
  modes against a synthetic broken.blend — all 6 planted breaks found with
  correct locations.
- `compat_db_4.4_to_4.2.json` — the annotated DB (missing/changed/non-node).
- `tools/gen_compat_db.py` — regenerates the DB for ANY two versions from their
  binaries. Deterministic; its output IS the committed DB.

## Fix-strategy taxonomy (advisory; each is output-diff verifiable)
safe-drop (gizmos/warning/name) | reconstruct (int-math, matrix-det, obj/coll
input, metallic bsdf) | bake (import obj/ply/stl) | manual (for-each zone, hash,
gabor, grease-pencil convert).

## Next steps (not started)
1. Generate DBs for 4.5 -> 4.2 and 4.5 -> 4.4 (just needs a 4.5 build).
2. Add the socket-change semantics to the report (e.g. ToolSelection rename
   needs a link remap, not just a "may shift" note).
3. Prototype the first `reconstruct` fixers (int-math, obj/coll input) and
   VERIFY each by output-diff in both versions before trusting them.
4. Optional in-Blender add-on: panel that jump-selects each broken node.

## Notes
- Do NOT merge to main without explicit user say-so.
- Auto-repair stays off until each fixer is output-diff verified — a wrong fix
  silently corrupts, which is worse than a flagged break.

## Update — non-node coverage added
Extended the pipeline + scanner beyond nodes (user asked about world/HDRI/env/render):
- `gen_compat_db.py` now also diffs settings structs (World, SceneEEVEE, RenderSettings,
  Material, Object, lights, Mesh, Curves) and type enums (modifier/constraint/lightprobe/
  object). DB gains `settings_lost` and `types_new`.
- **4.4->4.2 non-node result:** only 3 settings lost (EEVEE `use_fast_gi`, 2 compositor
  denoise-quality). World/WorldLighting IDENTICAL across versions (HDRI/env safe). No new
  object/modifier/constraint/lightprobe types. So real risk for this pair = nodes + GP v3.
- Scanner gained `check_settings()` (predict-mode only; props absent in target so it's
  skipped there). Flags a lost setting ONLY when it's set away from default. Tested: a file
  with `use_fast_gi=True` is flagged; detect-mode in 4.2 skips cleanly.
- Known gap: changed DEFAULT values (prop exists in both) not detected — needs value-level
  diff, not existence diff. Candidate for next pass.

## Update — value fidelity + value-aware diffing
User (correctly) wanted node VALUES preserved, not just node types. Tested:
- Undefined node in target (4.2) KEEPS name + all input sockets + values + links.
  (Metallic BSDF -> Undefined still exposed Roughness=0.777 and its link.)
- LOST on break: type identity + non-socket properties (enums).
- A SAVE in 4.2 is destructive: reopening in 4.4 stays Undefined (type not
  restored). => round-trip through 4.2 loses data. DECISION: reconstruct in the
  SOURCE version (4.4) before saving the downgraded copy; target-side is fallback.
- Scanner now reports actual values per breaking node in BOTH modes.
- Signature capture now includes socket default_values; `diff_sockets()` detects
  added/removed/retyped sockets AND changed defaults (closes the earlier gap).
  (No default changes 4.2<->4.4, but retype/default logic is in for other pairs.)

User confirmed: they're in 4.4 (not 4.5) - no 4.5 work needed. Want the app
GENERALIZED to catch everything (incl. grease pencil) even though live pain is
~6 nodes. Prefer not to test yet; may later send a complex 4.4 scene to validate.

## Next candidates
- First real reconstruct fixers, built in SOURCE version, value-preserving,
  each verified by output-diff: start with safe-drop (gizmos/warning) + the two
  input nodes (Object/Collection) + Integer Math.
- 'bake' path for Import OBJ/PLY/STL (realize to mesh).
- Optional in-Blender add-on panel (jump-select broken nodes).

## Update — BLACKBODY BUG FOUND (user was right) + subtype class + lights gap
User insisted blackbody breaks 4.4->4.2 (lights go pink, must replace node).
Investigated empirically:
- Blackbody node EXISTS in both; math identical (BB6000 -> [1.0887,0.9783,0.9531]
  in both). So not a missing-node or compute change.
- REAL cause: the Temperature input socket bl_idname changed
  NodeSocketFloat (4.2) -> NodeSocketFloatColorTemperature (4.4). 4.2 lacks that
  subtype, so on load the socket degrades to a bare NodeSocket with NO
  default_value -> the 6000 is dropped -> light reverts -> pink. Replacing the
  node fixes it (fresh socket). Verified via the 'no default_value' traceback.
- My signature only captured coarse socket TYPE ('VALUE') so it MISSED this.
  Fix: signature now captures socket bl_idname; diff_sockets detects
  in/out_subtype_changed. Now catches 3 nodes: ShaderNodeBlackbody,
  ShaderNodeVolumePrincipled (both Temperature), GeometryNodePoints (Position:
  NodeSocketVector -> NodeSocketVectorTranslation).
- SECOND gap: collect_nodes() did NOT walk LIGHT node trees (user's exact case!).
  Added bpy.data.lights. Scanner now flags blackbody-in-light with value LOST +
  shows the at-risk value (Temperature currently 6000.0).
- changed count 7 -> 10.

Round-trip reconciliation (user asked): shared features round-trip 4.4->4.2->4.4
LOSSLESSLY (user's intuition correct). Exceptions: (a) 4.4-only nodes go
Undefined and are PERMANENTLY lost once 4.2 saves (verified: Metallic BSDF stays
undefined back in 4.4); (b) subtype sockets lose that value. So earlier blanket
"4.2 save is destructive" was too broad — it's only the missing nodes + subtype
sockets.

Lesson: coarse signatures miss subtype-level breaks. Node-tree host coverage must
include: materials, lights, worlds, scene compositor, GN modifiers, node_groups.
Consider auditing other specialised socket subtypes for future pairs.

## Update — SYSTEMATIC schema audit (stop guessing classes)
User: worried more breakage classes are hidden; wants fundamental introspection
of what nodes are MADE OF, not ad-hoc discovery. Did full RNA schema dump of every
node in both versions and diffed every component.

New classes found systematically:
- prop_added (5): node gains a property in 4.4, lost on downgrade. e.g.
  ShaderNodeVolumeScatter.phase, FunctionNodeValueToString.data_type,
  GeometryNodeInputNormal.legacy_corner_normals, ResampleCurve.keep_last_segment,
  ToolSetSelection.selection_type.
- enum_values_added (16): a shared property's ENUM gained values in 4.4 (INT16_2D
  data type; GREASEPENCIL component; LAYER domain). Breaks only if a node USES the
  new value. NOTE: INT16_2D is internal-only (not settable via UI) - enum_items in
  RNA is a superset of settable items - so scanner's value-conditional check avoids
  false positives. GREASEPENCIL/LAYER are real user values.
- Zero: prop_removed, prop_type_changed, enum_removed, default_changed. Clean.

Folded into pipeline: sig() now also captures nprops() (non-socket props + enum
items + subtype + default). build() computes db["prop_changed"]. Scanner analyse()
checks prop_changed per node: flags added-prop set!=default, and enum value in the
source-only set. Tested: VolumeScatter phase=FOURNIER_FORAND flagged correctly.

Node schema coverage now: type, sockets(name/type/subtype/default), props(enum
items/subtype/default). Hosts walked: GN mods, materials, lights, worlds,
compositor, nested groups.

## Remaining fundamental surface to audit (next)
- node sub-structures: ColorRamp elements, CurveMapping, node-GROUP INTERFACE
  sockets (same subtype risk as node sockets - HIGH priority to check).
- non-node datablock properties at depth: modifiers (props not just types),
  constraints, physics, particles, mesh/curve attribute layers.
- zone state items (sim/repeat).

## Update — socket-type universe, interfaces, modifiers, constraints
Continued systematic audit beyond the node's own schema:
- SOCKET-TYPE universe: only 3 types are 4.4-only: NodeSocketFloatColorTemperature,
  NodeSocketFloatFrequency, NodeSocketStringFilePath. All node-internal — the
  interface API REJECTS them (TypeError), so group interfaces carry NO new drop
  risk. Built-in-node uses already caught. Added generic interface-socket check to
  scanner (check_interfaces) for future pairs. DB gains socket_types_new.
- MODIFIERS: no new types; 3 minor prop additions (Bevel edge/vertex_weight;
  NodesModifier bake_target/node_warnings/panel; GP simplify panel).
- CONSTRAINTS: no new types; ActionConstraint gained slotted-actions fields
  (action_slot etc.) -> 4.4 animation system. Added 'slotted_actions' non-node
  warning. DB gains datablock_changes (mods+cons).
- gen_compat_db.py now emits socket_types + mods + cons; build() computes
  socket_types_new + datablock_changes. Fully reproducible.

Audit map now COMPLETE for: node types, node sockets (name/type/subtype/default),
node props (added/enum-values/subtype/default), socket-type universe, group
interface sockets, settings structs, type enums, modifier props, constraint props,
GP v3, slotted actions.

Genuinely remaining (lower impact): node sub-structures (ColorRamp/CurveMapping),
zone state items (sim/repeat), mesh/curve attribute layers, physics/particles,
full animation-data (actions/slots).

## Update — sub-structures / attributes / zones audited (all ~clean)
- Node sub-structures (ColorRamp, ColorRampElement, CurveMapping, CurveMap,
  CurveMapPoint): ZERO changes 4.2<->4.4. Stable.
- Attribute layers: only internal INT16_2D added; no new user-facing data types or
  domains. No real risk (value-conditional check covers it).
- Zone state items (SimulationStateItem, RepeatItem, IndexSwitchItem): stable.
  GeometryNodeSimulationOutput gained minor props (color_tag, location_absolute,
  warning_propagation) - low impact. NOTE: node-prop audit via instantiation skips
  zone-OUTPUT nodes (can't instantiate standalone); direct bl_rna introspection
  catches them. Minor gap, minor props.
- Deferred by user: physics, particles, animation-data.

DIAGNOSIS BASE = SOLID. Next: REPAIR PHASE.

## Update — REPAIR PHASE started (scaffolding + first verified fixers)
Architecture: all fixers run in SOURCE (4.4), carry values + relink, report-honest
(fixed / flagged / None). Never overwrite input. New folder apps/blend-compat-scanner/repair/.

Verification bar (repair/verify.py regression harness): fixer output must be
IDENTICAL to original by evaluation, AND saved file opens in target with 0 undefined.

Fixers landed (both verified):
- safe-drop (SetGeometryName + Gizmo* + Warning): remove node, reconnect geometry
  passthrough. Geometry byte-identical.
- reconstruct FunctionNodeIntegerMath -> ShaderNodeMath(+round): EXACT-equal for all
  16 supported ops across signed input pairs. GCD/LCM flagged (no Math equiv), left
  in place. DIVIDE family uses Math DIVIDE + TRUNC/ROUND/FLOOR/CEIL. NEGATE = *-1.

End-to-end apply_repair test PASSED: file with SetGeometryName + IntegerMath(ADD) +
IntegerMath(GCD) -> fixed 2, flagged 1; reconstructed attribute r=10 verified
IDENTICAL when reopened in 4.2; only remaining break is the honestly-flagged GCD.

Files: repair/fixers.py (registry), repair/apply_repair.py (headless apply),
repair/verify.py (regression harness), repair/README.md.

## Next fixers (same bar)
- Object/Collection Input -> group-input socket.
- Matrix Determinant -> component arithmetic.
- Import OBJ/PLY/STL -> bake to mesh.
- Blackbody / Volume Principled temperature -> TWO-STAGE (manifest in source,
  re-apply in target). The user's real pain; tackle after these.

## Update — BLACKBODY FIXER DONE (user's #1 pain solved)
Tested the clean approaches thoroughly:
- Link-driven temperature (Value node -> Temperature): CRASHES 4.2 on load (a link
  into the missing-subtype socket segfaults, unlike a default which degrades). REJECTED.
- BAKE approach (WINNER): evaluate the constant blackbody colour in 4.4, replace the
  node with a plain RGB (shader trees) / Color (geometry trees) node of that colour.
  Single-stage, source-side. Tree-aware. Linked/animated temp -> flagged.
Verified: colour-identical across 1500/4000/6500/10000K in harness; full integration
(light w/ blackbody -> apply_repair -> open 4.2) = 0 issues, NO crash, correct colour,
0 blackbody, 0 undefined. blackbody_color() stores FULL precision (rounding caused a
1e-5 harness mismatch, fixed).
Trade-off: temperature baked to a colour (not re-editable as temp in 4.2) - correct for
downgrade-to-send. Registered ShaderNodeBlackbody -> fix_blackbody.

Fixers now: safe-drop, IntegerMath, Blackbody. All pass repair/verify.py.

## Next
- Volume Principled temperature (same subtype, different node - own approach).
- Object/Collection Input -> group-input socket.
- Matrix Determinant -> component arithmetic.
- Import OBJ/PLY/STL -> bake to mesh.

## Update — BLACKBODY: keep the node (user/client preference), not bake
User: client thinks in blackbody, wants the NODE kept, not converted to RGB.
Built the two-stage keep-node approach (the user's manual fix, automated):
- Confirmed the temperature is genuinely lost in the 4.2 file (degraded socket
  stores nothing; readable=False). A LINK into the socket crashes 4.2 on load.
  So value must be re-applied by rebuilding a fresh node IN the target.
- repair/blackbody_keep.py: --stage extract (source, manifest of temps keyed by
  MATERIAL/LIGHT/WORLD/NODEGROUP::name::node) / --stage apply (target, rebuild
  fresh native blackbody + temp + reconnect).
- repair/keep_blackbody_run.py: one-command orchestrator (runs 4.4 extract then
  4.2 rebuild via subprocess).
- VERIFIED end-to-end: source with light bb=6000 + material bb=4000 -> client
  reopens 4.2 -> both REAL native blackbody nodes, correct temps, linked. 
- Made keep-node the DEFAULT: removed ShaderNodeBlackbody from bake FIXERS;
  fix_blackbody kept as opt-in BAKE_ALTERNATIVE. apply_repair now points blackbody
  nodes to keep_blackbody_run.py.
- Test-setup lesson (again): orphan datablocks (unused material) get purged on
  save - anchor to an object in tests.

Minor known scanner nit: in DETECT mode (running in 4.2), a fixed native blackbody
still matches the 'changed' DB by bl_idname so it shows as '1 socket-changed'
(informational, not a real break). Predict-mode value-loss check is the meaningful
one. Could refine detect-mode later.

Fixers: safe-drop, IntegerMath (default apply_repair); Blackbody keep-node (two-stage
tool) + bake (opt-in). All harness checks pass.

## Update — generalized subtype value-loss keeper (blackbody + volume principled)
- Verified which subtype-changed sockets ACTUALLY lose values in 4.2:
  * Blackbody Temperature: LOST. Volume Principled Temperature: LOST.
  * Points Position (NodeSocketVector->NodeSocketVectorTranslation): NOT lost
    (VectorTranslation exists in 4.2). FALSE ALARM.
- Scanner refined: value-loss now only flagged when the new subtype is in
  socket_types_new (truly missing). Points no longer flagged as value-loss.
- Generalized the keep tool: repair/subtype_keep.py (DB-driven: at-risk =
  in_subtype_changed whose subtype in socket_types_new) + repair/keep_nodes_run.py
  orchestrator. Uses a general rebuild_node() that preserves ALL readable sockets,
  links, and node properties, applying manifest overrides for the lost sockets.
- Removed the old blackbody-specific blackbody_keep.py / keep_blackbody_run.py.
- fixers: NEEDS_TWO_STAGE = {Blackbody, VolumePrincipled}; blackbody bake stays as
  opt-in BAKE_ALTERNATIVE. apply_repair points these to keep_nodes_run.py.
- VERIFIED end-to-end (one command): combined file (light BB 6000 + material BB 4000
  + Volume Principled Temp 5500/Density 0.4) -> client 4.2 reopen -> all real native
  nodes, correct values, VP density preserved.

Fixers now: safe-drop, IntegerMath (apply_repair); subtype-keep for Blackbody +
Volume Principled (keep_nodes_run.py two-stage); blackbody bake (opt-in).

## Update — Matrix Determinant fixer + honest flagging of the rest
- Matrix Determinant: 4.2 has SeparateMatrix (16 elements) but not MatrixDeterminant.
  Reconstruct via SeparateMatrix + Math cofactor expansion (4x4). VERIFIED in harness
  vs native determinant for random matrices. Registered.
- Object/Collection Input + Import OBJ/PLY/STL: clean fixes hit a real wall (4.2 has
  no way to inline a constant object reference; would need group-interface changes +
  modifier-level values, fragile esp. nested). DECISION: flag with GUIDANCE, not
  fragile auto-fix. apply_repair now reports the referenced object/collection name
  and import file path so the manual fix is trivial. (Held the verification bar:
  don't ship fixers that can't be cleanly verified.)
- Fixer phase substantially complete. Auto-fixed+verified: safe-drop, IntegerMath,
  MatrixDeterminant, subtype-keep (Blackbody/VolumePrincipled). Flagged-with-guidance:
  Object/Collection Input, Import, Foreach zone, Hash, FindInString, GP conversions.

## Update — file safety + apply-modifier escape hatch
- ORIGINAL FILE SAFETY: engine.convert now copies the source to a temp working copy
  and runs all stages on the COPY. The original is only ever READ, never opened for
  writing. Verified: after a convert (incl. applying a modifier), the original still
  has its modifier + base geometry, md5 unchanged.
- APPLY-MODIFIER option: for a manual (unfixable) issue living inside a GN modifier,
  offer applying that object's modifier (bakes evaluated geometry into the mesh,
  removes the modifier + its nodes). Verified: 8-vert cube w/ subdivide+InputObject
  modifier -> apply -> 4.2 opens with 98 verts, 0 undefined nodes.
  * scan_ui: manual GN-modifier issues get obj/mod/can_apply (parsed from
    "Object 'X' > GN modifier 'Y'").
  * convert_source: --apply list; applies those modifiers FIRST (temp_override +
    modifier_apply), then node-fixes the rest.
  * engine/server: apply_modifiers plumbed through convert.
  * UI: can_apply issues offer "Apply modifier (bake)" + "Acknowledge"; staged apply
    shows "will apply" queued state (amber); applying resolves all issues in that
    obj::mod; convert gating counts staged fixes + APPLY.size.
- Only OFFERED for GN modifiers with a detected unfixable error (not clean mods, not
  non-GN mods). Acknowledge remains an alternative.

## Update — app runtime fix + texture/image checks
- CRITICAL FIX: server.py UI path wasn't bundle-aware -> in the packaged exe the
  WebView2 window loaded but the server returned ERR_EMPTY_RESPONSE (UI file not
  found). Now uses sys._MEIPASS when frozen + serves a visible error instead of an
  empty response. (This was the "127.0.0.1 didn't send any data" bug.)
- NEW CHECK — images:
  * External unpacked textures (source FILE, filepath, packed_file None) -> FIX: pack
    (img.pack() works; verified). The classic "forgot to pack textures" case.
  * Generated images (source GENERATED, unpacked) -> MANUAL warning. Verified the hard
    truth: generated-image edits do NOT survive .blend save (0.9->0.0 on reload) and
    img.pack() silently no-ops on generated. So Relay can't fix/recover them; it warns
    to save them to a file in Blender. Honest, not fake.
  * scan_ui adds these; convert_source packs staged external images (packed=N);
    UI shows 'Pack' + 'Acknowledge(ignore)' for textures, manual warning for generated.

## Update — real-file validation (Livano North Hills, 525MB) + purge-unused
- REAL FILE TEST: scanned a 525MB production .blend (Blender 4.4). Found the user's
  blackbody light (auto-fixed), 4 gizmos (safe-drop), and — critically — the "CT
  Cabinet Door" geo-node modifier (For-Each zones, unfixable) which the user always
  applies by hand. VALIDATED the apply-modifier fix on it:
  * Broken (modifier intact) opened in 4.2: 18v, 6 undefined nodes, DOORS ABSENT.
  * Fixed (apply-modifier) opened in 4.2: 96v, 0 undefined, modifier gone, DOORS PRESENT.
  Exactly reproduces the user's problem and confirms the fix solves it.
- SCANNER ACCURACY FIX (surfaced by the real file): added-socket changes were
  flagged for EVERY node of a changed type (112 phantom Principled BSDF flags from
  the added Diffuse Roughness socket). Now compares each added socket to the node's
  real default (cached reference node) and only flags linked/non-default ones.
  130 -> 17 accurate issues. Also fixed greedy modifier-name parse for nested groups.
- PURGE-UNUSED: user wants unused data removed after fixing (e.g. the node graph left
  orphaned after applying a modifier). Added --purge to convert_source (orphans_purge),
  plumbed purge_unused through engine/server, UI toggle "Remove unused data after
  fixing" (default on). Verified: apply cabinet modifier + purge -> purged=5 orphans,
  clean 96v 4.2 file.

## Update — third-party scene test (Blender 4.5 official splash) + accuracy fixes
- Downloaded the official Blender 4.5 splash (401MB, real scene I didn't design against),
  opened in 4.4 (0 undefined — no 4.5-only nodes), converted 4.4->4.2.
- REAL breakage: only 3 FunctionNodeIntegerMath (in GN-collision_primitive groups).
  Scanner caught all 3; converter fixed them; converted 4.2 output = 0 undefined nodes.
- RIGOROUS MISS CHECK: node types present in 4.4 but not creatable in 4.2 =
  [IntegerMath (flagged), CompositorNodeCurveRGB/HueCorrect/HueSat]. The 3 compositor
  ones were a TEST ARTIFACT (created them in wrong tree type); they DO exist in 4.2,
  and the scanner walks the compositor tree. So NO genuine misses.
- ACCURACY FIX (surfaced by this test): non_node_warnings (Grease Pencil v3, Slotted
  Actions) were firing UNCONDITIONALLY on every file. Now file-aware:
  * GP v3 only flags if the file has grease pencil objects/datablocks (splash had none).
  * Slotted Actions only flags MULTI-slot layered actions. Verified single-slot
    animation survives 4.4->4.2 intact (z=5.0 preserved), so those aren't flagged.
  This also removed a false GP flag from the Livano scan.

## Update — COMPOSITOR COVERAGE GAP found + fixed (user asked to check)
- User asked whether compositor nodes convert properly. Investigation found a real gap:
  * NODE TYPES: 102 in both 4.4 and 4.2, 0 missing -> no compositor node goes undefined. Good.
  * BUT gen_compat_db.py only instantiated nodes in GEOMETRY + SHADER trees, never a
    CompositorNodeTree -> compositor node SOCKET/PROPERTY diffs were NEVER computed.
    The "0 compositor changes" was "never checked", not "clean".
- FIX: gen_compat_db now also enumerates compositor nodes (scene.node_tree) and the
  diff loop includes "compositor". Regenerated the DB. Real compositor changes found:
  * CompositorNodeGlare: reworked in 4.4 -> 12 new input sockets + 2 outputs (props ->
    sockets). Settings lost/revert in 4.2.
  * CompositorNodeColorBalance: whitepoint/temp/tint sockets + WHITEPOINT mode.
  * Denoise(quality), OutputFile(save_as_render), Translate(interp modes), Viewer.
- scan_ui ref_default also fixed to instantiate CompositorNode in a CompositorNodeTree
  (was using geo tree -> would've silently not-flagged compositor changes).
- VERIFIED on the 4.5 splash: its Glare (Maximum=10.0, non-default) is now flagged
  (acknowledge). Was completely invisible before.

## Update — full node-tree coverage sweep (all categories audited)
Complete inventory audit across ALL node-tree contexts (geometry, material/world/light
shader, compositor, texture) in both binaries:
- MISSING nodes: 21 total (4 Function, 15 Geometry, 2 Shader) — ALL covered by DB, 0 gaps.
- World/light shader nodes: DO instantiate in a material tree, so they were never
  skipped by the generator (verified, no gap).
- Compositor: fixed previous turn (Glare rework etc.).
- TEXTURE nodes (37 types): generator enumerated 0 of them. Added TextureNodeTree
  enumeration to gen_compat_db + "texture" to the diff loop. Result: 0 missing, 0
  changed, 0 prop changes -> legacy texture nodes are genuinely UNCHANGED 4.2<->4.4
  (now verified, not skipped).
- Scanner: collect_nodes now also walks bpy.data.textures node trees; scan_ui
  ref_default handles all 4 tree types (shader/compositor/texture/geometry). Future
  version pairs with texture changes will be caught.
Splash re-scan consistent (9 issues); repair harness ALL PASS.

## Update — modifier/constraint coverage (non-node surface, per user: skip physics/rig)
- Audited modifiers + constraints:
  * TYPES: types_new empty + no new modifier/constraint classes -> none go undefined. Clean.
  * PROPERTIES (datablock_changes, real 4.4 additions): BevelModifier edge_weight/
    vertex_weight (custom attr weight sources), NodesModifier bake_target, ActionConstraint
    action_slot (slotted actions). Scanner did NOT check any of these -> gap.
- Added modifier/constraint checker to scan_ui: walks every object's modifiers+constraints,
  flags 4.4-only types (break/manual) and 4.4-only options actually in use (acknowledge,
  compared to a reference default; skips UI/internal + read-only/collection props).
- VERIFIED: Bevel with custom edge_weight attr + ActionConstraint with a slot both flagged;
  computed action_suitable_slots correctly NOT flagged. Splash unchanged (9), harness ALL PASS.
- (Per user request, physics/particles and rig/drivers deferred.)

## Update — GENERALIZED to any version pair (user's vision)
- The insight: gen_compat_db is already the general probe (enumerates a version's full
  internal surface, diffs two builds). Only wiring was needed to make it on-demand.
- gen_compat_db: exposed generate(src_bl, tgt_bl, labels, out) callable.
- engine.get_db(source, target): uses bundled DB if present, else cached, else GENERATES
  it from the two builds (blender_manage.ensure downloads any missing version). Cached in
  Relay/dbs/. scan()/convert() are now target-aware (pair-specific DB); server passes
  target_version. tools/ bundled into the PyInstaller app.
- DEMONSTRATED on a version never touched: downloaded Blender 3.6.23, auto-generated the
  4.4->3.6 map (79 missing / 58 changed vs 21/11 for 4.2 — the whole rotation/matrix node
  family + Kuwahara etc. added since 3.6). Same splash file scanned: 9 issues vs 4.2, 3015
  vs 3.6. Zero 3.6-specific code. Map auto-cached.
- So DIAGNOSIS is fully general for any pair. FIXES: safe-drop, subtype-keep, apply-modifier,
  texture-pack are DB-driven/general; reconstruct fixers (IntegerMath, MatrixDeterminant)
  are node-specific. Even with no fix, any pair gets a full accurate diagnosis.

## Update — Is Viewport check + Remove-modifier fix option
- GeometryNodeIsViewport ("Is Viewport"): EXISTS in both 4.4 and 4.2 (also
  GeometryNodeViewportTransform). Converts fine, no break. User's render/viewport
  switching preserved.
- NEW FIX OPTION — Remove modifier: for a broken GN modifier, in addition to
  "Apply modifier (bake)" the user can now choose "Remove modifier" (delete it
  entirely). convert_source --remove; engine/server plumb remove_modifiers; UI adds
  a "Remove modifier" button + "will remove" state (mutually exclusive with apply).
  Verified: removing the cabinet modifier -> object back to base 8 verts, modifier gone.
