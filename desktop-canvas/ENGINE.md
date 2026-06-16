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
- Folders are ordinary collidable nodes (Fit avoids them, Push shoves them).
  Dropping INTO a folder is a deliberate Free-mode action: only in Free does a
  cursor-rect overlap with a folder show the "move into" highlight + confirm.
- The Trash Can is droppable in any mode (delete is not a layout concern): a
  cursor-rect overlap shows the "delete" highlight regardless of mode.
- Hotkeys cycle the mode mid-carry (T cycles; 1/2/3 = Free/Fit/Push). The bottom
  bar shows the current mode + keys. Remappable once preferences land.

## Roadmap
1. (v0.0.13) engine core + carry/preview + 3 modes.  [done]
2. (v0.0.15) folders collide; drop-into-folder is a Free-mode action.  [done]
3. (v0.0.16) de-overlap on open (separateOnce relaxation); collision-driven
   animated SORT (ease toward sorted-grid slots + live separation that fades so
   slots win); Tidy-up + Sort menu on empty-space right-click.  [done]
   Grid snapping intentionally skipped — collision spacing replaces it.
4. NEXT: richer push settling; multi-select align / distribute.
5. containers: folders/rows/columns/stacks that auto-arrange children.

## Sort (collision-driven)
sort(items, key) -> sorted order -> target slots in a row-major grid sized to the
biggest card (so the resting grid is overlap-free by construction). Animate each
card easing toward its slot; for the first ~2/3 of frames also run separateOnce()
so cards crossing paths jostle; separation then stops and the easing converges
cleanly onto the slots. O(n^2) per frame (fine for normal folders; cap/skip for
huge ones). Same primitive (mtv) as Push and the open-time relax.

## Seams already in place
- snap() slots in before collision resolution and only adds guides.
- multi-node ops are just a different `operation` into the same resolve contract.
- containers are nodes with a layout rule; children targets are derived.
