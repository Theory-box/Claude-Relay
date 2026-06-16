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

## v0.0.7 — fix pan/zoom jitter; wheel mapping
- Reported: panning/clicking made the canvas zoom in/out and jitter; zoom itself fine.
- Likely cause: wheel handler mapped ALL scroll to zoom; on a trackpad a two-finger
  pan is a stream of small wheel events -> read as rapid zoom (jitter).
- Fix: Ctrl/pinch + wheel = zoom-to-cursor (smooth, exp factor); plain wheel = pan
  (translate by deltaX/deltaY). Pointer drag-to-pan unchanged.
- Added #diag readout (zoom %, dpr, scroll-event count) for live diagnosis.
- Extended the sync guard to also defer reconcile while panning. Lightened the grid.

## v0.0.8 — thumbnails + open + app context menu (batched)
- Image thumbnails: thumb_data Rust cmd returns a base64 data URL (hand-rolled
  base64, no deps; 8MB cap; png/jpg/jpeg/gif/webp/bmp/svg). CSP is null so data:
  URLs load fine. Frontend caches data URLs by name (thumbCache) + PIXI.Assets
  caches textures, so reconcile() is cheap. Image cards show the picture (fit to
  240x180) with a frame; non-images keep the label card.
- Double-click a card -> open_item (cmd /C start "" path) opens with default app.
- Right-click a card -> HTML app menu: Open / Open folder (explorer) / Remove from
  canvas (removes item+card, file left in folder). Hit-test via getBounds in screen
  space; menu hidden on outside click / wheel. Right mouse button is excluded from
  pan/drag so it only opens the menu.
- NOTE: this is the APP menu, not the real Windows shell context menu. The shell
  IContextMenu (Win32 COM) is intentionally deferred to its own step (highest risk).
- Wheel mapping unchanged from 0.0.7 (plain scroll pans, Ctrl+scroll zooms).

## v0.0.9 — shell thumbnails (all file types) + folder sync (batched)
- Shell thumbnails: shell_thumb() (Win32 COM) IShellItemImageFactory::GetImage @256px
  -> HBITMAP -> GetDIBits (BGRA, top-down) -> RGBA (force alpha=255 when all-zero) ->
  image crate PNG -> base64 data URL. cfg(windows) with a non-windows stub. New deps
  (windows 0.61, image 0.25) under [target.'cfg(windows)'.dependencies] (already in tree
  via tauri). thumb_data now calls shell_thumb for ANY file; fixes "large images don't
  load" (no more 8MB base64 cap) and gives icons/thumbnails for every type.
- Frontend: applyThumb() factored out; every card requests a thumbnail (label card is the
  fallback shown until/if the thumb arrives). Card now shows a caption + the thumbnail.
- Folder sync: list_canvas() returns [{name,mtime}]. The MAIN window polls every 3s:
  adds new files (placed on a grid), removes deleted ones (both via persist->sync), and
  on mtime change busts thumbCache + emits 'thumb-changed' so all windows refresh that
  thumbnail. Non-main windows get structural changes through the existing layout sync.
- Known: poll add/drop dedupe by name (cardForName) to avoid duplicates; a tiny race
  window remains if a drop lands exactly between a poll snapshot and processing.

## v0.0.10 — Trash Can + Delete-to-trash + native "Open with"
- Trash Can: a special draggable canvas object (__trash, NOT a file item). Persisted
  position in layout as { items, trash } (loadLayout back-compat: old array => items).
  Cannot be deleted; right-click => Open Trash Can folder / Clear Trash Can (2nd-click
  confirm => clear_trash permanently deletes the subfolder contents).
- Delete: menu "Delete" and dragging a card onto the Trash Can both call trash_item,
  which moves the file to Desktop Canvas/Trash Can/ (rename, copy+rm fallback, collision
  -safe via unique_dest). Card removed + persist (syncs). The drag-onto-target overlap
  test (rectsOverlap on getBounds) is the reusable mechanism for drag-onto-folder later.
- Native shell verb: run_verb() = ShellExecuteW; menu "Open with..." uses verb "openas"
  (native Windows dialog). Cheap way to leverage Windows without IContextMenu. Added
  Win32_UI_WindowsAndMessaging feature for SW_SHOWNORMAL.
- Right-click menu is now built dynamically per target (file vs trash).
- DECISION on native right-click: full Explorer menu (IContextMenu + TrackPopupMenu over
  the webview) is the high-risk piece and stays deferred; we keep our own menu and pull
  in native actions via shell verbs as needed.
- list_canvas already skips dirs, so the "Trash Can" subfolder never shows as an item.

## v0.0.11 — folders + navigation (every folder is a canvas)
- Backend now PATH-AWARE: all file ops take a `rel` folder path under Desktop Canvas
  (safe_rel rejects ..). New/changed cmds: list_dir(rel)->[{name,mtime,dir}],
  add_dropped_file(rel,path), make_folder(rel,name), move_into(rel,name,folder),
  trash_item(rel,name) [-> root Trash Can], open_item(rel,name), open_folder(rel),
  shell_verb(rel,name,verb), thumb_data(rel,name). list_dir hides root "Trash Can".
- Per-folder layouts: save_layout/load_layout now take a `key` (the rel path) and store
  app_data_dir/layouts/<sanitized>.json. NOTE: old single layout.json is not migrated,
  so existing arrangements reset once (files are safe; positions re-grid).
- Frontend: cwd state; loadView() rebuilds from saved positions + live disk listing
  (disk authoritative for existence/dir-ness, layout for positions). Folder cards get a
  folder icon (shell thumb of the dir) + a small folder glyph; double-click enters them.
  Address bar (#bar) with Up, clickable breadcrumbs, and +Folder (inline name input).
- Drag-onto-target generalized: file onto a folder card -> move_into; file onto Trash ->
  trash. Each window navigates independently; sync events ('layout-changed','thumb-changed')
  are now KEYED by folder so only same-folder windows react. Each window polls its own cwd.
- Trash Can shown only at root. Fixed "Open with" by adding CoInitializeEx in run_verb.

## v0.0.12 — browse the whole filesystem (absolute paths)
- Backend now absolute-path based: cwd is a full path. list_dir(dir) lists any folder;
  dir="" => This PC (drives via GetLogicalDrives, feature Win32_Storage_FileSystem).
  All file ops take `dir` (absolute) instead of a Desktop-Canvas-relative `rel`.
  New places() cmd returns quick links: Desktop Canvas (home/start), Home, Desktop,
  Downloads, Documents, This PC, + drives.
- Layouts/metadata still central (app_data_dir/layouts keyed by the absolute path),
  so real folders (Downloads, etc.) stay clean. NOTE: keying changed again => previous
  positions reset once more; now stable (keyed by absolute path).
- Frontend: absolute joinPath/parentOf, breadcrumbs start at "This PC" then drive then
  segments. Address bar gains a Places dropdown and a "Go to..." path box (type/paste).
  Trash Can shows only at the Desktop Canvas home. Dropping while at This PC is blocked
  (no folder). Default landing = Desktop Canvas home.
- trash_item from any folder still moves into the Desktop Canvas/Trash Can (one app trash;
  real Recycle Bin integration could come later via IFileOperation).

## v0.0.13 — placement engine v1 (carry/preview + 3 modes)
- Design doc: desktop-canvas/ENGINE.md (pure resolve() contract, primitives, roadmap).
- Engine primitives (pure JS): intersects, mtv (min translation vector), nearestFree
  (spiral search). rectOf(card) reads world-space AABB from card.hitArea.
- Carry/preview interaction: drag an existing card & RELEASE -> it detaches and floats
  on the cursor showing the live effect; left-click commits, right-click cancels (reverts
  from a snapshot captured at grab). Click without moving past 5px = not a carry (so
  double-click open/navigate still works). Confirm intercepted via window-capture
  pointerdown; mode keys + Escape-cancel via capture keydown (so quit doesn't fire mid-carry).
- Modes (cycle T; 1/2/3): Free (overlap ok, = stack-on-purpose), Fit (nearestFree near
  cursor), Push (neighbors displaced by mtv, bounded 6-pass relaxation incl light
  other-other separation). Recomputed from the snapshot each frame so pushed items return.
- Drop targets take precedence on the cursor rect: hover a folder/Trash -> green highlight
  + "move into/delete" instead of placement, in any mode. Trash node carryable (free only).
- poll/layout-changed suppressed during carry (reloadPending applied on commit/cancel).
- Scope: applies to MOVING existing items. OS imports still place immediately (carry for
  fresh imports is a possible follow-up). No grid snapping yet (next: snap() + guides).

## v0.0.14 — drag semantics split + folder-move confirm
- Existing canvas items: plain click-drag, commits IMMEDIATELY on release (no sticky/second-click).
  Engine preview (Free/Fit/Push) still applies live during the drag; Esc cancels mid-drag (revert).
- Sticky float (release -> rides cursor -> left-click confirm / right-click cancel) is now ONLY for
  files dragged IN from Explorer. Single-file import enters float; right-click cancel deletes the
  freshly-copied file (delete_file cmd) so nothing is left behind. Multi-file import still placed at once.
- Moving a file/folder INTO a folder now shows a confirm dialog ("Move X into Y?" Move/Cancel) before
  acting, for both move and import sources. Cancel: move -> revert to snapshot; import -> return to float.
  Trash drops are not gated (per request). Dialog: HTML modal, Enter=Move / Esc=Cancel.
- Added `confirming` flag; poll/layout-changed/grab/pan all suppressed while a dialog is open.
- Backend: added delete_file(dir,name) (permanent remove of a file) + registered in handler.
