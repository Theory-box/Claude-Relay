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
