# Split panes — status & resume notes

Status as of v0.0.38: **re-attempted with root cause fixed** (see below). Earlier status was
paused/reverted at v0.0.34.

## ROOT CAUSE of the blank 2nd pane (found via v0.0.37 probe)
The v0.0.37 diagnostic mounted a bare 2nd PIXI app in a half pane: its grid rendered fine, so
**two PIXI apps DO coexist in WebView2** — the worst-case branch is off the table. The real bug:
the canvas centers `world` using `app.screen` captured at construction. v0.0.32's doSplit created
the 2nd pane at FULL-window size, ran makeCanvas (which centered world at full/2 and set
hitArea=full), THEN relayout shrank the pane to half — leaving world centered OUTSIDE the visible
half = blank. v0.0.33 resized the renderer but never re-centered world, so still blank.

## THE FIX (v0.0.38)
makeCanvas now returns a `self` api with `self.resize()` that does renderer.resize(paneRect) AND
translates world by half the size delta (`world.x += (newW - oldW)/2`, same for y) so the centered
world-point stays centered after any pane size change; it also refreshes `app.stage.hitArea`.
PM.relayout() calls `p.resize()` on every pane after setting rects (and wireDiv drag → relayout).
Ported from v0.0.32: PM (panes/focused/split/ratio/divider), draggable divider, click-to-focus
(`.pane.focused` ring), keyboard guarded by `pm.focused !== self`, single manager-level OS-drop
router by position (per-instance wireDrop only runs when there's no pane manager). Split toggle is
in the empty-area right-click menu ("Split → side by side" / "Unsplit (single view)"). The canvas was rolled back to the v0.0.31
instanced foundation. The splitting attempt (v0.0.32 / v0.0.33) is preserved in git history
and can be cherry-picked or referenced when we resume.

## Goal
Blender-style in-window area splitting: hover a pane edge → cursor changes → drag inward to
split the canvas into independent panes, each showing its own space. Right-click the divider
between two panes → merge them, choosing which side survives. Live-resizing dividers.

## Staged plan
- **Stage 1 — instanceable canvas (DONE, kept, v0.0.31).** The whole canvas is a
  `makeCanvas(root)` factory; per-pane state is closure-local; per-pane DOM is cloned from
  `<template id="paneTpl">`; element lookups are root-scoped via `$('#id')`; PIXI app uses
  `resizeTo: root`. Renders a single full-window pane identical to v0.0.30. **This is the base
  we are on now.**
- **Stage 2 — pane manager (ATTEMPTED, reverted).** Split tree / layout, draggable dividers,
  focused-pane + keyboard routing, OS-drop routing to the pane under the drop, split/close.
- **Stage 3 — gesture + merge.** Edge-hover drag-to-split, right-click-divider merge w/ side
  choice, recursive splits, stacked (top/bottom) splits.

## What v0.0.32 (Stage 2a) added, and v0.0.33 tried to fix
v0.0.32 introduced a top-level pane manager `PM` (panes[], focused, split bool, ratio, one
divider), side-by-side split via the right-click-empty menu, click-to-focus with keyboard
routed to the focused pane and zoom to the hovered pane, and a single manager-level OS-drop
listener routing by drop position. `makeCanvas(root, opts)` returned a `self` api and took
`opts.initPath` / `opts.pm`.

## The blocking bug (NOT yet solved)
The **second pane renders blank** — no grid, no visible content (and reportedly no usable
toolbar/navigation). v0.0.33 hypothesized the cause was PIXI `resizeTo` only reacting to
*window* resizes (never to the pane *element* being resized by `relayout`), so the split
pane's renderer kept full-window size while its box was a half and the world-centered content
fell outside the clipped area. v0.0.33 added an explicit `self.resize()` (renderer.resize to
the element size, refresh `stage.hitArea`) called from `relayout`.

**Result: v0.0.33 did NOT fix it — same blank second pane.** So the resize theory was at best
incomplete.

## Leading hypotheses to check when resuming (in rough priority)
1. **Does `makeCanvas` throw on the 2nd instance?** Check the global red `#err` bar when
   splitting. If it fires, the second pane's DOM/canvas never finishes building — that alone
   explains "blank, no grid, no toolbar." Likely suspects: something assumed single-instance
   (a duplicate-id collision despite root-scoping, a listener/handle, or an `await` in the
   async init rejecting for the cloned pane).
2. **Does the cloned `<template>` actually populate the 2nd pane's root?** Verify the 2nd pane
   has its own `#bar`, `#hud`, canvas, etc. (inspect, or temporarily give the 2nd pane a bright
   background). If the toolbar is genuinely absent, the clone/DOM path is the problem, not
   rendering.
3. **Two PIXI Applications in one webview / WebView2.** Confirm a 2nd `PIXI.Application` mounts
   and renders at all (e.g., mount two trivially before wiring everything). WebView2 + PIXI v7
   multi-app is unverified in this environment.
4. **Renderer sizing/timing** (the v0.0.33 angle) — element-size vs window-size; whether the
   2nd renderer ever gets a non-zero size at the right moment; whether `world.x/y` centering
   uses a stale `app.screen`.

## Suggested resume approach
Build the smallest possible probe first: on split, mount a 2nd `makeCanvas` whose ONLY job is
to draw a full-rect colored background + the grid, with the global error bar visible. Confirm
two live PIXI canvases coexist and render before re-adding focus/keyboard/drop routing and
dividers. Add one mechanism per build (the project's proven pattern).

## Relevant commits (feature/desktop-canvas)
- `bec057b` v0.0.31 — instanceable `makeCanvas` foundation (current base).
- `711055e` v0.0.32 — Stage 2a pane manager + split (blank 2nd pane bug).
- `19e6dfd` v0.0.33 — per-pane renderer resize attempt (did not fix).

To revisit the split code: `git show 711055e:desktop-canvas/dist/index.html` (or diff
`bec057b..19e6dfd`).
