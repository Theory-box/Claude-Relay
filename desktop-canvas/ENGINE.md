# Placement / Collision / Spacing Engine — Design

The layout brain of Desktop Canvas. Built so that anti-overlap (now), snapping,
pushing, aligning, distributing and auto-arranging containers (later) all share
one core instead of being bolted on.

## The one abstraction
A PURE function (no rendering, no state mutation, no Tauri):

    resolve(snapshot, operation, mode) -> { targets: id->{x,y}, valid, guides }

- snapshot: every node's current rectangle (the committed positions).
- operation: what the user is doing right now (carry node X to cursor P; later:
  "align these N", "tidy this folder").
- returns where things SHOULD be, plus any guide lines to draw.

Everything else just: feed it the live operation each frame, render `targets`
as a PREVIEW, and on commit copy targets into real positions (on cancel, discard).
That single shape covers carry-to-place, push, snap, align, distribute, auto-layout.

## Nodes
To the engine a node is only an AABB { id, x, y, w, h } plus flags:
- movable (default), pinned (e.g. the Trash Can — obstacle but never moved),
- later: container (a folder that arranges its own children via a layout rule).
It does not know or care whether a node is a file, folder, or note.

## Primitives (the real foundation)
- intersects(a,b)           - AABB overlap test.
- mtv(a,b)                  - minimum translation vector: smallest shove to
                              separate two boxes (push along the axis of least
                              overlap). Heart of PUSH.
- nearestFree(rect,obs,near)- closest position to `near` where rect hits nobody
                              (spiral search outward). Heart of FIT.
- snap(pos,world) [later]   - adjust to grid / neighbor edges / equal spacing,
                              returns adjusted pos + guide lines.

## Placement modes (configs over the primitives)
- Free  : target = cursor. No resolution. (also the deliberate "stack" mode)
- Fit   : target = nearestFree(cursor). Slides into the closest gap.
- Push  : target = cursor; overlapped neighbors displaced by mtv, cascading with
          a bounded iteration count so it can't loop forever.

Key trick: every frame recompute from the ORIGINAL snapshot, not last frame's
result. So pushed neighbors follow and RETURN as you move the held item away;
nothing drifts; cancel is just "discard the preview".

## Carry / preview interaction
State: Idle -> (drag an item, release) -> Floating(node, mode) -> left-click
commits / right-click cancels (reverts everything).
- Releasing the drag does NOT finalize; the item floats on the cursor showing the
  live effect, so a hard-won layout is never clobbered by accident.
- Drop targets take precedence: if the cursor rect overlaps a folder or the Trash
  Can, the preview shows "move into / delete" (highlight) instead of placement,
  in any mode.
- Hotkeys cycle the mode mid-carry (T cycles; 1/2/3 = Free/Fit/Push). The bottom
  bar shows the current mode + keys. Remappable once preferences land.

## Roadmap
1. (v0.0.13) engine core + carry/preview + 3 modes.  <-- current
2. grid + edge snapping with alignment guide lines (snap() pre-step).
3. richer push (better cascade/settling) and optional animation.
4. multi-select operations: align / distribute / tidy (same engine, multi-node op).
5. containers: folders/rows/columns/stacks that auto-arrange children.

## Seams already in place
- snap() slots in before collision resolution and only adds guides.
- multi-node ops are just a different `operation` into the same resolve contract.
- containers are nodes with a layout rule; children targets are derived.
