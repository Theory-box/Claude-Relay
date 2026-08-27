# String Engine — Node Editor: Vision & Data Model

Status: design / research (feature/node-editor). No implementation yet.
Companion docs: 01 settings audit · 02 node catalog · 03 canvas & interaction · 04 build plan.

## 1. Why nodes, specifically for THIS engine

The engine today fuses three concepts into one record. A `G.objs` entry ("object")
is simultaneously:
- a **material** (colour, radius, stiffness, curl),
- a **behaviour bundle** (collision, affinity, breaking, bonding),
- and is attached to **geometry** (the nodes+segs painted with it).

That conflation is the reason the settings UI is a pile of global sliders plus
per-object toggles with no clean seam. The single most valuable thing the node graph
does is **split those three apart**:

- **Geometry** — the strands themselves (nodes+segs), independent of what they are.
- **Material / attributes** — properties stamped onto geometry.
- **Simulation config** — forces and relationships that act on geometry but are not
  part of it.

Everything else (menus, wires, canvas) is in service of making that separation
visible and editable. Get the separation right and the rest follows.

Second reason it fits: the engine is *already* a dataflow — geometry + per-thing
properties + global forces -> solver -> render. A node graph just exposes the pipeline
that is currently hardcoded. This is not a foreign paradigm bolted on; it is the
existing one made editable.

## 2. The three wire types (the load-bearing decision)

What flows through the wires determines everything. Modelled on Blender, which settled
(after prototyping both a single-geometry-socket design and a fields design) on TWO
parallel flows: a geometry data-flow and a field/function-flow. We adopt three:

### A. Geometry  (teal socket · solid noodle)
A **strand-set**: some nodes+segs, tagged with identity. One socket type for all
geometry regardless of shape (ring, line, drawn blob) — Blender deliberately uses a
single geometry socket rather than per-type sockets, because after a few nodes you
only transform/merge and no longer care about the sub-type. We follow that.

- Generators OUTPUT geometry.
- Modifiers take geometry IN, geometry OUT (transform, array, merge, resample).
- Attribute nodes take geometry IN, geometry OUT, and **stamp per-strand properties**
  (material, collision, damping, breaking, bonding) — exactly Blender's
  "Set Material" / "Store Named Attribute" pattern.
- The **Output** node consumes geometry: whatever reaches it IS the scene.

### B. Value / Field  (grey socket · dashed noodle when it carries a field)
A number, or a per-strand **field** (a function evaluated per element, not a value).
This is Blender's field concept: a field connected to two nodes can yield different
results in each, because it is evaluated in the consumer's context. Sockets are
"diamond with a hole" = accept a literal OR a wired field; a plain slider on the node
is just the literal default. Inputs (Value, Time, Random, per-strand attributes like
speed/position) and Math nodes live here. This is the piece that turns a slider ON a
node into a socket you can DRIVE — the source of most of the expressive power.

### C. Behaviour  (blue socket · solid noodle)
A solver contribution that is not geometry: a **force field** (motion/thermal, attract,
repel, later gravity/vortex/noise) or an **affinity rule** (a pairwise relationship).
Behaviour nodes flow into the Output node's multi-input Behaviours socket, the way
shaders flow into Blender's Material Output. They configure the sim; they do not
transform geometry.

> Menu categories (how you FIND a node) are orthogonal to wire types (what a node
> emits). "Collision" lives under the Simulation menu category for discoverability, but
> as data it is an *attribute* node in the geometry flow. Keep the two ideas separate.

## 3. The affinity knot, resolved

The confusion ("red adverse to blue, then feed red+blue into another affinity against
red -> red adverse to red, blue double-adverse...") comes from treating a *relationship*
like *geometry*. Red<->blue is not a thing you can bundle and pass downstream; it is one
row in a table.

Rule: **an affinity node points at two groups and writes ONE pairwise rule** (attract /
repel, with polarity). It does NOT output merged geometry. "red vs blue" and "red vs
green" are two separate affinity nodes = two separate table rows. They never interact or
double-count, because neither produces geometry the other consumes.

The one genuinely undefined case is "a group versus a member of itself" — which is
exactly what feeding a merged (red+blue) bundle back in against red creates. You avoid
it structurally by pointing affinity at **distinct groups**, never at bundles that
contain each other. Two inputs per node stays clean. (If affinity ever becomes dense —
many mutual pairs — a single matrix "hub" node with an N x N grid is the compact
fallback, but per-pair nodes are clearer and are the default.)

This is why affinity is a **Behaviour** node, not a geometry node: it declares a rule.
Same family as forces. That is what the "Simulation" category really is — nodes that
configure the solver rather than transform geometry.

## 4. Merged infinite canvas

The node graph does not get a separate window. The existing canvas becomes an infinite
plane:

- The **sim lives in its bounded box** (world units, as today — `S.W`/`S.H`, wall pad).
- **Nodes live in the space around the box.**
- The existing **pan/zoom camera** (`view.ox/oy/z`) is shared: pan down to the graph,
  pan up to the scene, or zoom out to see both.

Bonus that falls out for free: **hit-testing by region.** A pointer inside the sim box
routes to the existing sim tools (draw/grab/pan); outside the box it routes to graph
interaction (select/wire/pan). No mode toggle — spatial separation gives the interaction
split. The only new work is the graph's own draw + wire routing + add-menu; navigation
is already built.

Coexistence: the graph runs ALONGSIDE the current settings panel at first. The panel is
the safety net and the quick-poke path while the graph matures; we hide or retire it only
if/when the graph fully supersedes it.

## 5. Evaluation model

Two speeds, both already present in the engine as "rebuild vs re-pack":

- **Bake on graph-edit** — geometry and static attributes. Editing the graph (add node,
  rewire, change a baked param) triggers a rebuild, analogous to today's `buildScene()`.
- **Evaluate live per-frame** — behaviours (forces are dynamic fields; affinity is read
  each step). These route into the running solver every frame, like today's per-frame
  param pack.

The graph evaluator's job is to route each change to the correct speed. The engine
already makes this split internally, so the graph is wiring into an existing seam, not
inventing one.

**Layering, not overriding.** Stacked attribute nodes accumulate (Blender stacks
Set-Position the same way — last relevant write wins, or an explicit combine). Each
attribute defines its combine op: damping ADDs/stacks; a colour REPLACES; a limit might
take MAX. The global `gStiff/gThick/gGrow` modifiers of today become simply an attribute
node placed AFTER a merge (affecting everything) — the node model subsumes them, so those
globals can retire.

## 6. What this replaces vs coexists with

- Demo scenes become **node-graph presets** (also a correctness test: if every demo can
  be rebuilt as a graph, the vocabulary is expressive enough).
- The paint/tool UI stays for quick edits; the graph builds the scene. Coexist first.
- The per-object material editor becomes the **Material node**; global sliders become
  either Output-node settings or dedicated nodes (see 01 audit for the full mapping).
