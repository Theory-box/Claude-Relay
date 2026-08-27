# String Engine — Settings Audit & Node Translation

Full inventory of every current setting, and where each lands in the node model.
Source of truth: string-engine.html at merge daa5dc2. Columns:
- **Wire/where**: G = geometry-attribute (stamped, flows with geometry) · B = behaviour
  (force/rule into Output) · O = Output/solver setting · V = view/render (may stay in
  panel or live on Output) · X = retired/subsumed.
- **Combine**: how stacked instances layer (add / replace / max / n-a).

## A. Global state — the `S` object

| setting | meaning | node home | wire | combine | notes |
|---|---|---|---|---|---|
| temp | thermal jitter / "motion" | **Motion (Temperature) force** | B | add | a force field: random per-node impulse |
| damp | global velocity damping | **Damping** node on Output (or on geo = local) | O/G | add | same node local vs global by placement |
| speed | substeps per frame | Output (solver) | O | n-a | integer; sim quality/speed |
| iters | constraint / collision quality | Output (solver) | O | n-a | drives GPU collision iters too |
| wallPad | strand stand-off from walls | Output (domain) | O | n-a | |
| pad | domain inner padding | Output (domain) | O | n-a | |
| depth | 3D-slab thickness (z) | Output (domain) | O | n-a | also feeds render DoF |
| weld | free-end weld distance | **Bonding** node (or Output) | O/G | max | CPU welding; distinct from bond snap |
| attract | global pull | **Attract force** | B | add | |
| repel | global push | **Repel force** | B | add | |
| tol | attract/repel falloff tol | Attract/Repel force param | B | n-a | |
| contactDamp | collision smoothing (CPU only) | **Collision** node | G/O | add | dead on GPU (already greyed) |
| xpbd | XPBD contact correction (CPU only) | **Collision** node | G/O | add | dead on GPU (already greyed) |
| brkSpeed | speed-based breaking | **Breaking** node (speed mode) | G | max | new; strands only |
| bonding | bonding master kill-switch | **Bonding** node enable / Output | O | n-a | |
| bondSnap | bond form distance (x rest) | Bonding node (default profile) | G | n-a | per-object profile overrides |
| bondBrk | bond break distance (x rest) | Bonding node (default profile) | G | n-a | |
| bondCure | merge time default | Bonding node | G | n-a | |
| bondBlend | material blend on bond | Bonding node | G | n-a | 0 = chimera |
| bondTimer | continuous / cumulative | Bonding node | O | n-a | enum |
| bondEnergy | energy absorbed on break | Bonding node | O | add | |
| maxBondEvents | per-frame bond cap | Bonding node / Output | O | n-a | perf guard |
| chunk, bondChunk | CPU batching flags | (internal) | X | n-a | solver detail; likely no node |
| gStiff | global stiffness modifier | **Stiffness** attr after merge | G | add | subsumed by layering |
| gThick | global thickness modifier | **Thickness/Radius** attr after merge | G | add | baked into GPU radius |
| gCurl | global curl modifier | **Curl** attr after merge | G | add | |
| gGrow | global grow modifier | **Grow** modifier after merge | G | add | CPU topology |
| weave | weave amount | Material/Curl attr | G | add | |
| strandFill | fill opacity | Look (Output/view) | V | replace | |
| outlineW, outlineA | outline width/opacity | Look | V | replace | |
| gloss, shade, shadow | 2D shading | Look | V | replace | |
| shadeSmooth | smooth shading toggle | Look | V | replace | |
| bg | background colour | Look / Output | V | replace | |
| cleanView, showHeat | debug/heat overlays | View panel | V | n-a | stays UI, not graph |
| snapViz | bonding reach overlay | View panel | V | n-a | |
| view | render mode enum | View panel | V | n-a | |
| unitPx | world px per unit | Output / global const | O | n-a | drawing density basis |
| drawSegsPerUnit | draw density | **Draw** node param | G | n-a | already a live picker |
| scene, W, H, dpr, pad, running, selected, cdRamping, cdRamp0, frame | runtime/session | (internal) | X | n-a | not settings |

## B. Micro-view render params — the `mp` object

ref, ab, rim, iblur, noise, nscale, mblur, dof, focus, grain, field, vignette,
autofocus, bg. These are the microscope post-process. All **View (V)** — they belong on
a **Look/Microscope node on Output**, or simply stay in the current View panel. Not
scene-graph. Recommend: leave in panel for v1; optionally a "Microscope Look" node later.

## C. Per-object material — `OBJDEF`

| prop | meaning | node home | wire | notes |
|---|---|---|---|---|
| r | radius | **Material** node | G | core |
| stiff | stiffness | Material node | G | core |
| curl | rest curl | Material node (or Curl attr) | G | |
| grow | growth rate | **Grow** modifier | G | topology (CPU) |
| color | colour | Material node | G | |
| solid | solid fill flag | Material node | G | |
| fixed | pinned/anchored | Material node (or Pin attr) | G | |
| affinity | affinity strength | feeds **Affinity** node | B | per-group strength |
| polarity | attract/repel sign | feeds Affinity node | B | |
| autoSpace | auto spacing | **Collision** node | G | |
| spaceMult | spacing multiplier | Collision node | G | |
| breakable | breaking master | **Breaking** node enable | G | |
| brkStretch | stretch breaking | Breaking node | G | |
| brkAbs, bendAbsLim | absolute-angle break + limit | Breaking node | G | |
| brkRel, bendRelLim | relative-angle break + limit | Breaking node | G | |
| bondOn | endpoint bonding on | **Bonding** node enable (per geo) | G | |
| endType{} | per-connected-type profiles | Bonding node (connection rows) | G | see D |

## D. Bond end-profiles — `ENDDEF` (per object, per connected type)

wStr / wRange (weak pull + range), sStr / sRange (strong grip + range), snap, brk,
merge, blend, bStr (birth stability), hardenPow (harden curve). All live on the
**Bonding** node as a per-connection sub-panel: "when THIS material's end meets a
<type> end, use these thresholds." In nodes, "type" becomes the **group** of whatever is
wired/painted — see affinity/groups note below.

## E. Affinity / relationships

inter{} (pairwise matrix by type), interSelf, group ids. -> **Affinity** node(s),
Behaviour wire. Two geometry inputs identify the two groups; node sets attract/repel
(with polarity). Groups: today keyed by material *type*; in nodes a group is assignable
so two copies of one material can differ. Default group = material identity; override on
the Affinity node or a small **Group** attribute node.

## F. Forces (today implicit in the solver)

temp (motion), attract, repel — currently globals; become **force nodes** (Behaviour).
Future force nodes (deferred by user): radial gravity, linear gravity, vortex, noise
field, drag. All share the Behaviour wire and sum on the Output node.

## G. Translation summary — the node set this audit implies

Generators: Draw, Primitive, Import.
Modifiers: Transform, Array, Merge, Resample, Grow.
Attributes: Material, Collision, Damping, Breaking, Bonding.
Behaviours: Affinity, Motion(Temp), Attract, Repel (+future gravity/vortex/noise/drag).
Utility/Input: Value, Math, Map Range, Time, Random, Attribute-read, Reroute, Group.
Output: the sim node (geometry in, behaviours in, solver + domain + look settings).

Retired/subsumed by the model: gStiff/gThick/gGrow/gCurl (become attributes after merge),
chunk/bondChunk (solver internals). View/render params stay in the panel for v1.
