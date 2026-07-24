# Spec — Selection & the "objects are materials" reframe

Branch `feature/chemistry`. Status: **design only, nothing built.**
Supersedes the first draft (which proposed per-atom overrides — dropped, see §3).

Background reasoning: `philosophy-and-direction.md`.

---

## 1. Why the Blender model doesn't port

Blender's modes navigate a **stable authored hierarchy** — an object exists until you delete
it, so "tab into this object and edit its parts" is well-defined. Here the hierarchy is
**emergent and changes every few seconds**:

- A "string" (connected piece) has **no persistent identity** — it's derived from connectivity
  and recomputed on every bond/break. You can't attach a setting to "string #3"; after one
  merge there is no string #3.
- A connected strand can **span several materials**. With merge blend 0 (the normal setting)
  each half keeps its original one.
- Tab-into-edit assumes the container you entered still exists a second later. It may have
  merged with a neighbour or split in two.

**Conclusion: no modes.** Everything is directly selectable; granularity comes from *how* you
select.

## 2. Objects are materials

An object stops being a container and becomes a **settings set** — a material, describing a
*part type*. Atoms (nodes, segments) reference one.

- Many strands may share a material.
- One strand may carry several (normal, not an edge case).
- A material's geometry need not be contiguous or nearby.

Everything that felt like a special case dissolves:

| Situation | Under the material model |
|---|---|
| Strand spans two objects | A strand with two materials on it. Normal. |
| Merge with blend 0 | Each half keeps its material. Nothing to decide. |
| Break | Both halves keep their materials. Nothing to decide. |
| Object with scattered pieces | Expected — a material isn't a container. |

## 3. Settings live ONLY on the material

**No per-atom overrides.** Editing anything while a strand is selected edits *that material*,
and therefore every strand made of it — like editing a substance, not an instance.

Selecting a red strand and changing stiffness changes **all red**. Selection is
**pure navigation**: a way to find a material by pointing at it instead of hunting the list.
The edit is identical either way.

This is a large simplification. It removes: the override resolver, its hot-loop cost, sparse
override storage, mixed-state fields, and the extra save/load + capture/restore plumbing.
Nothing about how settings are stored changes from today.

**Escape hatch:** an explicit **"make this its own material"** action, which forks a copy and
reassigns the selected geometry. Divergence becomes deliberate and visible in the list, rather
than an invisible override.

## 4. Endpoint settings are part of the material

The one thing that genuinely can't be a single shared value is the connector type — a string
whose two ends want different partners is the whole point of per-endpoint types.

Resolution: **a material describes a part, including a separate rule set per endpoint slot.**
Not "this node is overridden", but "this part has an end A and an end B, and here are A's rules
and B's rules." Every strand of that material behaves identically, so it stays purely
material-level with no per-atom storage.

Slots are **vertex order** (first / last for a two-ended string), which is stable and authorable
in Blender.

This is Winfree's tile with labeled edges: the part is the program, and the program lives in the
material.

**Y-junctions fall out.** A Y is three strings fused at a centre, each its own material — so each
arm gets its own binding rules automatically, because each arm is a different part type. No
special branched primitive, and consistent with designing one level below the target phenomenon.

## 5. Selection

### Terms
- **stretch** — a maximal contiguous run of same-material segments within one connected piece.
  The thing you point at.
- **piece** — everything physically connected (already computed as `G.piece`).
- **endpoint** — a degree-1 node; the unit endpoint slots attach to.

### Interaction
| Action | Result |
|---|---|
| Hover | Highlight the **stretch** under the cursor; near a free end, highlight that **endpoint**. |
| Click | Select it → panel shows that material (and, for an endpoint, that slot's rules). |
| Double-click | **Grow to linked** — the whole connected piece. |
| Click a material in the list | Select all its geometry, scene-wide. |

Prefer the endpoint when the cursor is within roughly the node's drawn radius of a degree-1
node; otherwise the stretch. Needs a visual tell so it isn't a guess.

### Tools
- **Select linked** (double-click)
- **Select similar → in linked geometry** — every stretch of this material within the piece
- **Select similar → scene-wide** — same as clicking the material in the list
- **Box select**

Multi-select still matters for *navigation* (and for a future "make its own material" on a
batch), but it is no longer required for tip typing — slots are per material, so you set a tip
rule once, not fifty times. **This removes multi-select from the critical path.**

## 6. CRITICAL — how selections must be stored

Checked against the code:

- **Node indices are stable.** `G.nodes` is only ever appended (`addGraphObject`, `dupNode`);
  never spliced.
- **Segment indices are NOT stable.** `removeDead` does `G.segs.splice(i,1)`; `mergeEnds` and
  `cutLine` do `G.segs.filter(...)`. Both reindex everything after the removal point.

**Store selections as node indices, never segment indices.** A stored segment index silently
becomes a *different segment* after any break or merge — a silent, nasty bug class. A selected
stretch is stored as its node set; segments are re-derived on use (a segment is in the selection
when both endpoints are).

### Staleness
- `mergeEnds` orphans one of the two fused nodes (survives in `G.nodes` with no segments).
- A break can split a selected stretch in two.

Rules: prune degree-0 nodes from selections each frame; if a selection empties, fall back to the
material so the panel still shows something coherent; if a stretch splits, keep both halves.

Because settings live on the material, **staleness is now cosmetic** — a stale selection can
highlight the wrong geometry but can never mis-apply an edit. Much lower stakes than the
override design.

## 7. Conflicts with the existing UI

Most of the original list dissolved with overrides. What remains:

1. **`S.selected` is a single object index**, used by `selectObject`, `selObj`,
   `renderObjectList`, the Connect tab, and the render highlight (~line 885). Keep it as
   "active material" and add a separate `S.sel` for geometry selection rather than overloading it.
2. **Hover picking needs spatial acceleration.** Nearest-segment-to-cursor can't be a linear scan
   over thousands of segments per mousemove. `collide()` already builds a bucket grid each frame —
   reuse that structure.
3. **Connector type is per-object** (`objType(o) = o.ids[0] || o.name`), profiles at
   `o.endType[targetType]`. Endpoint slots change this to per-slot rule sets; sketch in
   `2026-07-23-chemistry-design.md`.
4. **Move tool vs a select tool.** Move already handles drag/pan; double-click selects, so no new
   mode is needed for the common case.

Notably **not** conflicts any more: the object editor's `o.*` writes, `captureSettings`/
`restoreSettings`, and `saveScene`/`importJSON` — all unchanged, because settings still live
exactly where they live today.

## 8. Build order

1. **Picking + hover highlight** (stretch and endpoint). Purely additive, disturbs nothing.
2. **Click / double-click / shift-click selection** + render styling for selected vs hovered.
3. **Panel routing** — clicking geometry focuses its material; clicking an endpoint focuses that
   slot.
4. **Endpoint slots** — per-slot rule sets in the material, replacing the single shared
   connector type.
5. **Select-similar / box-select**; **"make its own material"** action.

Steps 1–2 are self-contained and testable without touching the current editor.

## 9. Open questions

- **Does "material" become the user-facing word?** Accurate and matches the mental model, but
  every label and doc currently says "object". Cheap to rename now, expensive later.
- **Slot naming.** Auto (end A / end B / arm 1-3) vs user-renamable. Auto is probably enough to
  start.
- **Dimming unselected geometry.** Deferred — the useful half is making it un-grabbable so a
  stray click can't yank a passing strand mid-sim, but this is icing, not needed yet.
