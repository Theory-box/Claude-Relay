# Spec — Selection model & the "objects are materials" reframe

Branch `feature/chemistry`. Status: **design only, nothing built.** Written for review before
touching UI code, because this conflicts with the existing object-centric editor in several
places (§7).

Background reasoning is in `philosophy-and-direction.md`; this is the concrete plan.

---

## 1. Why the Blender model doesn't port

Blender's modes exist to navigate a **stable authored hierarchy**: an object exists until you
delete it, so "tab into this object and edit its parts" is well-defined.

Here the hierarchy is **emergent and changes every few seconds**. Strands merge and split
constantly. Concretely, three things break the metaphor:

- A "string" (connected piece) has **no persistent identity** — it's derived from connectivity
  and recomputed on every bond/break. You can't attach a setting to "string #3"; after one
  merge there is no string #3.
- A single connected strand can **span several objects**. With merge blend 0 (the user's normal
  setting) each half keeps its original object. So `string ⊂ object` is false in the common case.
- Tab-into-edit assumes the container you entered still exists a second later. It might have
  merged with a neighbour or split in two.

**Conclusion: drop modes.** Everything is directly selectable; granularity comes from *how* you
select, not from which mode you're in.

## 2. The reframe: objects are materials

An "object" stops being a container and becomes a **settings set** — closer to a material.
Atoms (nodes and segments) reference one.

- Many strands may share a material.
- One strand may carry several materials (this is normal, not an edge case).
- A material's geometry need not be contiguous or even nearby.

Everything that felt like a special case dissolves:

| Situation | Under the material model |
|---|---|
| Strand spans two objects | A strand with two materials on it. Normal. |
| Merge with blend 0 | Each half keeps its own material. Nothing to decide. |
| Break | Both halves keep their materials. Nothing to decide. |
| Object with scattered pieces | Expected — a material isn't a container. |

## 3. Where settings live

Two layers, one rule:

```
value(atom, key) = atom.ov?.[key]  ??  material(atom)[key]
```

- **Material** provides the default (this is today's `G.objs[i]`, essentially unchanged).
- **Per-atom override** (`ov`) wins where present, and is **sparse** — almost always absent, so
  we're not storing 500 copies of every field.

This answers the earlier "does object mode override or stack?" question: there is no
mode-dependence, just override-beats-default.

**Hot-loop cost.** `constraints`, `collide`, `endpointForces` read these every frame, so the
resolve must stay cheap. Because overrides are sparse it's a single truthiness test:

```js
function mval(a,k){const o=a.ov;return (o&&o[k]!==undefined)?o[k]:G.objs[a.obj][k];}
```

Worth benchmarking against the current direct `G.objs[s.obj].r` before rolling it through the
hot paths; if it measures badly, denormalise (write resolved values onto the atom when an
override is set) rather than resolving per frame.

**Merge inheritance falls out for free.** Two strands fuse, each half's atoms keep what they
carried → a chimera, which is correct. No inheritance rule needed. The existing `blend` slider
stays as the *opt-in* averaging behaviour it already is.

## 4. Selection

### Terms
- **atom** — a node or segment.
- **stretch** — a maximal contiguous run of same-material segments *within* one connected piece.
  This is the thing you point at.
- **piece** — everything physically connected (already computed as `G.piece`).
- **endpoint** — a degree-1 node. The unit per-endpoint types need.

### Interaction
| Action | Result |
|---|---|
| Hover | Highlight the **stretch** under the cursor; if the cursor is near a free end, highlight that **endpoint** instead. |
| Click | Select the hovered stretch (or endpoint). |
| Double-click | **Grow to linked** — the whole connected piece. |
| Shift-click | Add / remove from selection. |
| Drag on empty space (select tool) | Box select. |
| Click a material in the list | Select all geometry of that material, scene-wide. |

Endpoint-vs-stretch: prefer the endpoint when the cursor is within roughly the node's drawn
radius of a degree-1 node; otherwise the stretch. Needs a visual tell so it's not a guess.

### Selection tools (the ones the user asked for)
- **Select linked** — grow to the connected piece (double-click).
- **Select similar → in linked geometry** — every stretch of this material within the piece.
- **Select similar → scene-wide** — every stretch of this material anywhere (this is what
  clicking the material list does).
- **Select all endpoints** of the current selection — the bulk path for tip typing.

### Multi-select is required, not a nicety
Setting a tip type on fifty strand-ends one click at a time is unusable. Box-select and
"select all endpoints of this material" should ship *with* per-endpoint types, not after.

## 5. CRITICAL — how selections must be stored

Checked against the code:

- **Node indices are stable.** `G.nodes` is only ever appended (`addGraphObject`, `dupNode`).
  Never spliced.
- **Segment indices are NOT stable.** `removeDead` does `G.segs.splice(i,1)`; `mergeEnds` and
  `cutLine` do `G.segs.filter(...)`. Both reindex everything after the removal point.

**Therefore: store selections as node indices, never as segment indices.** A stored segment
index silently becomes a *different segment* after any break or merge — a nasty, silent class
of bug.

A selected stretch is stored as its **node set**; the segments are re-derived on use
(a segment is in the selection when both endpoints are). Cheap and always correct.

### Staleness
Even node indices can go stale in meaning:
- `mergeEnds` orphans one of the two fused nodes (it survives in `G.nodes` with no segments).
- A break can split a selected stretch in two.

Rules:
- Prune orphaned nodes (degree 0) from selections each frame — cheap.
- If a selection empties, **fall back to the material** rather than clearing silently, so the
  panel keeps showing something coherent.
- If a selected stretch splits, keep both halves selected. No prompt, no surprise.

## 6. Panel behaviour

The panel shows whatever is selected:

- **Material selected** (from the list) → today's editor, unchanged.
- **Stretch selected** → the same fields, but edits write **per-atom overrides** on that
  stretch. Fields matching the material show normally; fields overridden show as modified
  (and want a "revert to material" affordance).
- **Mixed selection** (spans materials, or mixed override values) → show mixed state rather
  than a lie. Blender's dashed/blank-field convention.
- **Endpoint selected** → tip type + its affinity rules (the per-endpoint types feature).

## 7. Conflicts with the existing UI (surface these before building)

1. **`S.selected` is a single object index.** Used by `selectObject`, `selObj`, `renderObjectList`,
   the whole Connect tab, and the render highlight (line ~885). A richer selection object has to
   coexist with it — cleanest is to keep `S.selected` as "active material" and add a separate
   `S.sel` for geometry selection, rather than overloading one variable.
2. **The object editor assumes an object.** Every control does `selObj()` then writes to `o.*`.
   Under overrides these need to route through a setter that knows whether it's editing a
   material or a stretch.
3. **`captureSettings`/`restoreSettings`** enumerate per-object fields explicitly and would need
   to carry per-atom overrides too, or Reset silently discards them.
4. **`saveScene`/`importJSON`** likewise — overrides must round-trip, otherwise saving loses
   exactly the per-endpoint work this whole feature exists to enable.
5. **Connector type is per-object** (`objType(o) = o.ids[0] || o.name`) and profiles live at
   `o.endType[targetType]`. Per-endpoint types change the lookup to be tip-based; see the design
   sketch in `2026-07-23-chemistry-design.md`.
6. **Hover picking needs spatial acceleration.** Nearest-segment-to-cursor over thousands of
   segments can't be a linear scan on every mousemove. `collide()` already builds a bucket grid
   each frame — reuse that structure rather than adding a second one.
7. **The Cut tool and a Select tool both want clicks.** Current toolbar is Move + Cut, and Move
   already handles drag/pan. Suggested: keep Move as default and let double-click select (as
   discussed), so no new mode is needed for the common case.

## 8. Suggested build order

1. **Picking + hover highlight** (stretch and endpoint), no editing yet. Purely additive, nothing
   else changes — safe to land and immediately useful.
2. **Click/double-click/shift-click selection** + render styling for selected vs hovered vs dimmed.
3. **Per-atom overrides** — resolver, sparse storage, capture/restore and save/load round-trip.
4. **Panel routing** — material vs stretch vs mixed.
5. **Per-endpoint types** on top, now that endpoints are selectable and multi-select exists.
6. **Select-similar / box-select** as the bulk tools.

Steps 1–2 are self-contained and testable without disturbing the current editor at all; the
disruptive part starts at 3.

## 9. Open questions

- **Does "material" become the user-facing word?** It's accurate and matches the mental model,
  but every existing label and the docs say "object". Renaming is cheap now, expensive later.
- **Overrides vs splitting materials.** Editing a stretch could instead *fork* a new material for
  it. Overrides are lighter and keep the strand's identity; forking makes the settings visible in
  the list. Probably overrides, with an explicit "make into its own material" action.
- **Dimming while running.** The user wants unselected geometry dimmed. The genuinely useful half
  is making it **unclickable**, so a stray click doesn't grab a passing strand mid-sim.
