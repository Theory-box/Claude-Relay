# String Engine — Node Editor Build Plan

Phased so the two hardest unknowns get proven cheaply before committing to the full
catalog. Each phase is shippable and testable on your hardware. All on
feature/node-editor; the current settings panel stays live throughout.

The two real risks to retire first:
1. **Merged-canvas rendering + hit-testing** — does the graph share the camera cleanly
   and does region-based input routing feel right?
2. **Graph -> scene evaluation** — can a graph produce the same scene the current code
   builds, live?

## Phase 0 — Read-only node VIEW  (proof of canvas)
Render the CURRENT scene's objects/materials as static node cards floating beside the sim
box. No editing, no wires that do anything. Purely: draw cards in world space, pan/zoom
with the camera, LOD to dots when zoomed out.
- Proves: shared camera, world-space card rendering, legibility/LOD, the "scene + graph
  in one view" feel.
- Cost: low. No data-model change. Throwaway-friendly.
- Exit test: pan/zoom feels natural; cards stay readable; no interference with sim tools.

## Phase 1 — Graph skeleton + eval  (proof of pipeline)
Minimal real graph: an **Import/Scene** generator -> **Output**. A tiny evaluator walks
the graph and calls the existing scene-build path. Editing a node param rebuilds
(bake-on-edit). Serialize graph to/from the scene JSON.
- Nodes: Import(or Current-Scene), Output. Wire type: geometry only.
- Proves: nodes -> `buildScene()`-equivalent; the bake seam; save/load.
- Coexists with the panel (panel still authoritative; graph mirrors).
- Exit test: a graph of {scene -> output} reproduces today's scene, and a param change
  rebuilds correctly in both CPU and GPU modes.

## Phase 2 — Interaction  (make it editable)
Add-menu (Shift+A + search), node drag/move, socket wiring (drag-to-connect,
link-drag-search), delete, box-select. Region hit-testing finalised.
- Proves: the full authoring loop on the geometry wire.
- Exit test: build the phase-1 graph by hand from an empty canvas.

## Phase 3 — First real nodes across all 3 wires  (proof of model)
Material (attribute) + Merge (multi-input) + Motion/Temp (behaviour) + Value/Math (field).
Now geometry, behaviour, and value wires all exist; layering + live-eval both exercised.
- Proves: the three-stream model end to end; attribute layering; per-frame behaviour eval;
  a Value node driving a param.
- Exit test: two Draw/Primitive -> Material each -> Merge -> Output, with a Motion force
  and a Value node driving a radius, matches hand-built equivalents; forces update live.

## Phase 4 — Breadth  (fill the catalog)
Remaining generators (Draw, Primitive), modifiers (Transform, Array, Resample, Grow),
attributes (Collision, Damping, Breaking, Bonding), behaviours (Attract, Repel, Affinity).
Affinity gets special care (two-input group-rule model). Demo scenes ported to graph
presets — the correctness test for expressiveness.
- Exit test: every current demo scene rebuildable as a graph preset with identical sim.

## Phase 5 — Polish & convergence
Node groups (Ctrl+G) + reroute + frames; link-cut gesture; collapse; labels/colours;
LOD tuning. Then evaluate retiring/hiding the settings panel. Add deferred force nodes
(gravity radial/linear, vortex, noise, drag) once the force wire is proven — these are
"free" additions on the Behaviour wire and are the original motivation for the arc.

## Sequencing rationale
- 0 and 1 are the cheap de-riskers; if either feels wrong we learn it for almost nothing.
- 3 is the real go/no-go: if the three-wire model feels clean with Material+Merge+Force
  +Value, the rest is repetition. If it feels wrong, we adjust the model before breadth.
- The panel staying live the whole time means the engine is never broken by this work —
  the graph is additive until Phase 5.

## Open questions to settle as we go
- Groups: do materials default to their own group, or to material-identity? (affects
  affinity). Lean: material-identity default, overridable via a Group attribute.
- Render/look params: on the Output node, a dedicated Look node, or left in the panel?
  Lean: panel for v1, Look node optional later.
- Field depth: how far to take Blender-style per-strand fields (speed/id/position) in v1
  vs later. Lean: ship Value+Math+Time first; attribute-read fields in Phase 4/5.
- Parallel research (candidate for the second AI): vanilla-JS node-canvas patterns
  (bezier noodle routing, socket hit-testing, undo/redo for graph edits, graph eval
  ordering / topological sort with cycles guard).
