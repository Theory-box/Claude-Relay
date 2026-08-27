# Node Editor — Progress

## Phase 0 — read-only node view  [SHIPPED, awaiting hardware test]
First slice of the merged-canvas idea. Read-only; no editing yet.
- New overlay canvas `cnode` (2D, always on top, pointer-events:none) — cards render in
  ALL sim modes (2D/GPU/micro), since the base 2D canvas is covered by cgl/cwgpu.
- `drawNodeGraph()` draws one card per `G.objs` material to the RIGHT of the sim box
  (world x > S.W+64), in shared world space using the existing camera
  (`S.dpr*view.z` scale, `S.dpr*view.ox/oy` translate) — so cards pan/zoom with the scene.
- Card: header (Attributes category hue) + name + geometry-out socket (teal); full LOD
  also shows colour swatch, radius, stiffness, behaviour flags (break/bond/space/solid/
  pinned), affinity, curl. Screen-constant border width (1.4/z); socket/fill/text scale.
- LOD by zoom: z>=0.45 full · 0.2-0.45 compact (header+title) · <0.2 coloured dot.
- Toggle: toolbar "nodes" button (next to microscope). Default OFF. Toggling ON calls
  `fitNodesView()` which frames the union of the sim box + the card column so both are
  visible immediately (verified math: 5 mats -> z 0.72 both on screen; 20 mats -> z 0.22).
- Drawn in the frame loop after the sim render; cleared when off. No data-model change,
  no interaction, no wires. Throwaway-friendly.

What this proves (Phase 0 exit test — for hardware): cards render in world space, share
the camera, stay legible / LOD sensibly, and do NOT interfere with sim tools (the overlay
is pointer-transparent, cards sit outside the sim box).

Risks (blind, no GPU/browser here): visual/legibility tuning; fitNodesView with unusual
viewport sizes; whether the always-on-top transparent cnode has any perf cost when idle.

## Next: Phase 1 — graph skeleton + eval (scene->output graph rebuilds the scene live).

## Phase 1 — graph skeleton + evaluator + reversible gate  [SHIPPED, awaiting hardware test]
Turns the Phase-0 cards into a live graph that actually drives the sim.
- Graph state `NG={bypass,_rects}` + `evalGraph()` (walks Output <- materials -> live stats)
  + `ngBypass()` + `ngHitTest()`. (Phase 2 grows NG into real nodes/wires/positions.)
- Each material card now emits a teal geometry-out socket; bezier wires flow into a new
  **Output · scene** node (distinct amber header) that shows live evaluated stats
  (materials / strands / nodes). Wires stack as a multi-input on the Output's left edge.
- Selected material (S.selected) highlights (amber border) in the graph — live link to
  app state.
- Reversible gate: clicking the Output node toggles NG.bypass. Bypassed = wires draw cut
  (grey dashed) + the sim step is skipped (frozen) in BOTH CPU and GPU paths; reconnect
  resumes. Region hit-test added at the top of the cvs pointerdown handler (only when
  nodeView is on and the click lands on the Output rect); clicks inside the sim box fall
  through to the sim tools untouched.
- Gates: stepFrame() early-returns when bypassed; the frame-loop physics block is wrapped
  in `if(!ngBypass())`. Node-verified: off->steps run, on->0 steps. Non-bypassed path is
  byte-identical to before (no regression).
- No serialization yet (the graph is still auto-derived from G.objs each draw; positions
  are computed, not authored) - deferred to Phase 2 when nodes become hand-placeable.

Proves (Phase 1 exit test): a scene->Output graph reproduces the scene (Output stats match
+ update live as you edit via the panel), and the Output connection actually drives whether
the scene simulates. Coexists with the panel (panel still authoritative).

Risks (blind): the click-to-bypass hit region + the frozen-frame render gating; whether
bypass interacts cleanly with GPU mode (step skipped, last frame held).

## Next: Phase 2 — interaction (Shift+A add menu, node drag, real wiring, per-material
## connect/disconnect) - the phase where the graph becomes hand-authored.

## Refactor — data-driven node core  [SHIPPED, behaviour-preserving, awaiting eyes-on]
No new feature. Rebuilds Phase-0/1's tangled drawNodeGraph on a registry so Phase 2 (and
every node after) is a data edit, not surgery. Verified: ships identical behaviour.
- `NGCFG` — every layout/style/LOD constant in one object (single-edit restyle/retune).
- `NODE_TYPES` — node types are DATA. Each entry: category, header/bg/border colours,
  round/headH, socket defs (inputs/outputs, with multi flag), title(n), accent(n), tag,
  and a per-type drawBody(cx,n,x,y,w). Adding a node = one entry. Currently: material,
  output. The catalog (02-node-catalog.md) maps directly onto new entries.
- Separated concerns, each independently editable:
  - model: `NG={nodes,wires,bypass}` + `ngSync()` (reconciles nodes/wires with the scene;
    keeps the output node, adds/removes material nodes, rebuilds wires; nodes carry
    `auto:true` so Phase 2 can pin user-moved ones and skip them in layout).
  - layout: `ngLayout()` (positions + per-LOD heights + socket anchors) — positions only,
    Phase-2-ready to skip non-auto nodes.
  - render: `ngDrawNode()` (generic frame: rect/header/title/tag/sockets + per-type
    drawBody) + `ngDrawWires()` (generic, groups by target for multi-input stacking).
  - hit-test: `ngPick(gx,gy)` (generic node pick) + `ngHitTest` (action: output->bypass).
  - eval: `evalGraph()` walks Output<-wires.
- Behaviour parity checks (blind, no browser): JS + 11 shaders valid; step gates +
  pointerdown still bind ngBypass/ngHitTest; all card/stat/flag/hint strings + LOD
  thresholds + colours reproduced; model logic unit-tested (mock G/S -> 1 output + N
  material nodes, N wires all->output, selection flag, eval stats, bypass zeroing, orphan
  removal). One deliberate, near-invisible change: wires now draw behind nodes (was: over
  material cards, under output) - cleaner z-order, emanate from the same socket points.

## Next: Phase 2 — interaction (Shift+A add menu, node drag with auto-pin, real wiring)
## now slots onto NODE_TYPES + the separated model/layout/render/hit-test.

## Phase 2b — per-material wiring (click socket to connect/disconnect)  [SHIPPED, blind]
Right-sized for a 2-type graph: with only material->Output wires, wiring = click a
material's output socket to connect/disconnect it. Full noodle-drag between arbitrary
sockets waits for the add-menu phase (meaningful once there are intermediate nodes).
- Model: material node carries `connected` (default true). ngSync derives wires only from
  connected materials and calls ngApplyActive().
- ngApplyActive(): sets `o._ngOff` on each object from its node's connected state; on change,
  repacks the GPU (gpuResync) so the exclusion takes effect there too. Change-detected so
  idle frames never repack.
- Effect (real, both modes): a disconnected material is skipped by every physics + render
  loop via `o._ngOff` guards - integrate, constraints (length + bend), collide, 2D render
  (both passes), and GPU buildScene (both pack sites). It freezes and vanishes from the sim;
  Output's material count drops; its node dims to 0.42 and its wire disappears. Click the
  socket again to reconnect (CPU resumes instantly; GPU repacks).
- SAFETY PROPERTY (why this was safe to ship blind): `_ngOff` defaults falsy, so every guard
  is a no-op until a material is explicitly disconnected. Normal use (nothing disconnected)
  runs byte-identical to before - the feature cannot regress the baseline sim.
- Verified: JS + 11 shaders valid; guard audit (8 guards, all _ngOff-gated); unit test of
  connect/disconnect/reconnect (flags, eval count, wire count, GPU-repack-on-change-only,
  idempotence). BLIND on feel/GPU-repack timing.

## Next: full noodle-drag wiring + Shift+A add menu (needs intermediate node types first).
