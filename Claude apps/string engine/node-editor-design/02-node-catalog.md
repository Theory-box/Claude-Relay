# String Engine — Node Catalog

Aggressive-but-smart breakdown. Format per node:
`Name  [category]  in: <sockets>  out: <sockets>  params: <inline widgets>`
Socket types: (geo)=geometry teal · (val)=value/field grey · (beh)=behaviour blue.
Params are inline widgets on the node; any param can instead be DRIVEN by a (val) wire.

Menu categories: **Generators · Modifiers · Attributes · Simulation · Utility · Input**.
(Category = where it sits in Shift+A. Wire type = what it emits. They differ: Collision
is an Attribute in the geometry flow but sits under Simulation in the menu.)

---

## Generators  (make geometry from nothing)

- **Draw**            out: (geo)   params: density (segs/unit), unit px, closed?
  The freehand pencil. Already exists as a tool; here it is a generator whose stroke is
  stored and re-resampled live from the density param (the existing picker).
- **Primitive**      out: (geo)   params: shape {ring,box,grid,line,arc}, size, segments
  Procedural strand shapes. Replaces built-in scene primitives.
- **Import**         out: (geo)   params: file / scene id
  Loads a saved JSON scene or geometry as a strand-set.

## Modifiers  (geometry -> geometry, shape/topology)

- **Transform**      in:(geo) out:(geo)   params: move xy, rotate, scale
- **Array**          in:(geo) out:(geo)   params: count, offset xy, rotate step, radial?
  The duplicate node. count can be a (val) wire -> driven arrays.
- **Merge / Join**   in:(geo, multi) out:(geo)
  Multi-input (Blender Join Geometry): several geometry wires combine into one set,
  identities preserved. The confluence before Output.
- **Resample**       in:(geo) out:(geo)   params: segs/unit
  Re-space a strand's nodes (from the drawing work). Density as a modifier.
- **Grow / Expand**  in:(geo) out:(geo)   params: rate, limit
  Topology growth (adds nodes over time). CPU; bakes/updates on rebuild.

## Attributes  (geometry -> geometry, stamp per-strand props)

- **Material**       in:(geo) out:(geo)   params: colour, radius, stiffness, curl,
  solid?, fixed?
  The core "material node." Replaces the per-object material editor. Layering: later
  Material writes replace matching fields.
- **Collision**      in:(geo) out:(geo)   params: enable, auto-space, space mult,
  padding, [CPU: contact-damp, xpbd]
  Stamps "these strands collide, with this spacing." contact-damp/xpbd shown greyed on
  GPU (already handled in-engine).
- **Damping**        in:(geo) out:(geo)   params: amount
  Local when on geo; the SAME node on Output = global. Combine: add/stack.
- **Breaking**       in:(geo) out:(geo)   params: enable, stretch (x rest), abs-angle +
  limit, rel-angle + limit, **speed** (brkSpeed)
  All break modes in one node. Speed mode is the new stabiliser. Combine: max.
- **Bonding**        in:(geo) out:(geo)   params: enable, + per-connection rows
  (snap, break, merge, blend, strength, harden curve, weak/strong pull+range)
  Endpoint bonding. The per-connected-type profiles become add/removable connection rows
  ("when my end meets a <group> end -> these thresholds"). weld lives here too.

## Simulation  (Behaviour wire -> Output; configure solver, not geometry)

- **Affinity**       in:(geo A, geo B) out:(beh)   params: attract, repel, polarity
  Two inputs identify two groups; emits ONE pairwise rule. Multiple Affinity nodes =
  multiple table rows. Never merge-then-affinity (see 00 sec 3).
- **Motion (Temp)**  out:(beh)   params: amount (temp), [optional] region
  Thermal jitter as a force field. Global by default; region-scoped later.
- **Attract**        in:(geo?) out:(beh)   params: strength, falloff (tol)
  Global or geo-anchored pull.
- **Repel**          in:(geo?) out:(beh)   params: strength, falloff
- *(deferred forces, same wire): Gravity (radial/linear), Vortex, Noise field, Drag.*

## Utility  (value/field maths & organisation)

- **Math**           in:(val,val) out:(val)   params: op {add,sub,mul,div,min,max,pow...}
- **Map Range**      in:(val) out:(val)       params: from/to lo/hi, clamp?
- **Combine/Separate XY** for vector-ish params (offsets).
- **Switch**         in:(val, A, B) out:(A|B) — Blender Menu/Index Switch; toggles graph
  branches. Useful for demo-preset variants.
- **Reroute**        in:(any) out:(any)       — noodle tidy (Blender reroute). 1 in, many out.
- **Frame**          — labelled background box grouping nodes (organisation only).
- **Group**          — collapse a selection into a reusable node (Ctrl+G), with
  group-input/output. Deferred to a later phase but design sockets group-ready.

## Input  (provide data/fields)

- **Value**          out:(val)   params: number, int/float
  The float/int input that drives many params. The workhorse.
- **Time**           out:(val)   — frame / seconds, for animated params.
- **Random**         out:(val)   params: seed, min, max  — per-strand or per-eval.
- **Attribute read** out:(val field)   params: which {position, speed, id, age}
  Blender-style field inputs: "speed" enables e.g. colour-by-speed or speed-driven
  breaking without a global. Diamond socket.

## The Output node  (exactly one; the scene)

- in: **Geometry** (single) · **Behaviours** (multi: forces + affinity rules)
- params (solver): speed/substeps, quality/iters, domain (W/H, padding, wall pad, depth),
  global damping, bond timer/energy/cap, engine (CPU/GPU — the existing dropdown).
- params (look, optional or panel): fill, outline, gloss, shade, shadow, bg.
- Whatever geometry reaches Output IS the simulated scene. Unplug a branch to disable it.

---

## Aggression notes (where we split vs bundle)

- **Split**: Breaking's modes stay in ONE node (they are facets of one idea) but Damping
  is pulled OUT of Collision into its own node (user's request: dampen a string, merge,
  then dampen all). Collision and Damping were coupled in the solver; the node model
  decouples them.
- **Split**: Material vs Collision vs Bonding vs Breaking — today one `G.objs` record;
  four attribute nodes now. This is the core win.
- **Bundle**: Bonding keeps its per-connection profile rows inside one node rather than a
  node-per-connection — connections are dense and per-pair nodes would explode.
- **Bundle**: all break modes in one Breaking node (stretch/angle/speed are one concept:
  "when does this tear").
- **Retire**: gStiff/gThick/gGrow/gCurl globals -> just an Attribute node after Merge.
