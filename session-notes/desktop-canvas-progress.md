# Desktop Canvas — Progress

Branch: feature/desktop-canvas
Code: desktop-canvas/
Stack: Tauri v2 (Rust + WebView2), PixiJS planned for canvas. Windows-only.

## Current increment
1. Pipeline + bottom-most window proof:
   - Borderless, fullscreen, skipTaskbar, always-below-other-windows.
   - On-screen Quit + Esc; Task Manager as fallback.
   - CI (windows-latest) builds release exe, uploads as artifact.
   - Claude fetches artifact zip and relays in chat; user runs it.

## Build/delivery model
- CI compiles on free GitHub windows-latest runner (Claude can't build Windows on Linux).
- Manual zip relay: Claude downloads artifact via API, presents in chat.
- No auto-update, no public hosting, no proxy. Repo stays private.

## Next
- Confirm zip runs and sits as bottom-most desktop layer.
- Then: canvas (PixiJS pan/zoom), folder load as grid w/ shell thumbnails, etc.
- Later: hide/restore real desktop icons, multi-monitor independent cameras, tray.

## Notes
- Tauri v2 has native set_always_on_bottom (no Win32 needed for basic Model B).
- Full design decisions live in Claude's R&D planning doc (to be committed here).

## Increment 2a (canvas, single screen) — v0.0.2
- PixiJS v7 vendored locally (offline). Infinite-feel dot grid.
- Pan (drag empty space), zoom-to-cursor (wheel), draggable sample cards.
- On-screen error readout (frontend runtime debug aid; logging plugin TBD).
- Rust unchanged from 0.0.1. Next pass (2b): spawn a window per monitor (3),
  each its own independent camera.

## Increment 2b (multi-monitor) — v0.0.3
- On launch, enumerate monitors; main window covers monitor 0, a window per
  remaining monitor (screen-N), all borderless / skipTaskbar / always-on-bottom.
- Physical position+size per monitor (DPI-safe across mixed-scale screens).
- Each window = own webview = own independent PixiJS camera (independent nav).
- Extra windows built on a worker thread (avoids the documented Windows
  build-in-handler deadlock).
- NOTE: each screen currently independent with identical starting scene; shared-
  vs-separate content toggle deferred to the data-layer increment.
- WATCH: 3 WebView2 instances => higher RAM; revisit for "lightweight" later.

## v0.0.4 — work-area sizing fix
- Windows now sized/positioned to each monitor's work_area() (excludes taskbar)
  instead of full monitor size, so the taskbar no longer covers the canvas.

## v0.0.5 — data layer step 1 (drop -> copy -> persist)
- New Rust commands: add_dropped_file (copies a dropped file into Desktop Canvas,
  handles name collisions), save_layout / load_layout (JSON at app_data_dir).
- canvas_dir() ensures <Desktop>/Desktop Canvas exists (desktop_dir w/ home fallback).
- Frontend: OS drop wired via current webview onDragDropEvent (fallbacks: webview
  getCurrentWebview, then tauri://drag-drop event). Drop -> copy -> labeled card at
  drop point (physical pos / devicePixelRatio). Layout persisted; cards reload on start.
- Removed the demo sample cards; canvas starts empty (grid only) + persisted items.
- Default drop action = COPY (Copy/Move/Reference prompt deferred). No image
  thumbnails yet (next: render real images via convertFileSrc + assetProtocol).
- Docs added to branch: desktop-canvas/PLANNING.md, desktop-canvas/DEVELOPMENT.md.

## v0.0.6 — live cross-window sync
- Each monitor window is an independent webview with its own copy of the canvas,
  so a drop/move only changed the originating screen until restart.
- Fix: after any change, persist() saves layout.json then emits a 'layout-changed'
  Tauri event to all windows; every window listens and reconcile()s (destroy cards,
  reload from file, rebuild). Guarded so a window mid-drag defers its reload to drag end.
- Open design question (not yet decided): all monitors currently render the SAME
  canvas (same layout.json) with independent cameras. Long-term "every folder is a
  canvas" may mean per-screen/per-folder canvases instead. Revisit with folder nav.
