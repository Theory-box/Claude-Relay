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
