# Desktop Canvas — Development Guide

Handoff notes so the user or another AI can continue. Windows-only.

## What it is
An always-on, infinite spatial canvas that replaces the Windows desktop:
a PureRef-style reference board fused with file-explorer capability.
North star: every folder is a canvas; navigation = the filesystem.
Full design rationale is in PLANNING.md.

## Stack
- Shell: Tauri v2 (Rust backend + Windows WebView2).
- Frontend: static HTML + vendored PixiJS v7 (dist/pixi.min.js), no bundler/Node.
- One borderless window per monitor, sized to each monitor's work_area
  (excludes taskbar), skipTaskbar, always_on_bottom. Each window = its own
  webview = its own independent PixiJS camera.
- Persistence (current): JSON layout at the OS app_data_dir (layout.json).
  Files dropped in are copied into <Desktop>\Desktop Canvas.
  (Plan: move to a central SQLite store keyed by folder; see PLANNING.md.)

## Build & deliver pipeline (no local toolchain for the user)
- Code lives on branch feature/desktop-canvas, in desktop-canvas/.
- Pushing triggers .github/workflows/desktop-canvas-build.yml on a free
  GitHub-hosted windows-latest runner. It runs `cargo build --release` in
  desktop-canvas/src-tauri and uploads desktop-canvas.exe as the artifact
  "desktop-canvas-windows" (a zip).
- The exe is portable (frontend embedded); needs WebView2 (preinstalled on
  Win10/11). No installer yet.
- Delivery model: the AI downloads the artifact zip (GitHub Actions API) and
  hands it to the user in chat. User runs/updates from the zip. No auto-update,
  no public hosting, no proxy — repo stays private. (A small in-app/companion
  "update from zip" tool is planned.)
- A full build is ~4-6 min (no cargo cache yet; adding caching is a TODO).
- NOTE: the build token is NOT stored in the repo. It needs `workflow` scope to
  push workflow files. Keep credentials out of the repo.

## Verified Tauri v2 facts (saves rediscovery)
- Native always-below: WebviewWindow.set_always_on_bottom(true). No Win32 needed
  for basic "behind everything" (Model B).
- Monitors: window.available_monitors() -> Vec<Monitor>; Monitor.work_area()
  -> &PhysicalRect{position,size} (use this, not .size(), to respect taskbar).
- set_position/set_size accept PhysicalPosition/PhysicalSize directly.
- Create windows in setup; build extra windows on a worker thread to avoid the
  documented Windows build-in-handler deadlock.
- OS file drops: browser onDrop does NOT fire. Use the current webview's
  onDragDropEvent (or the tauri://drag-drop event). Payload: { paths, position }
  in PHYSICAL pixels (divide by devicePixelRatio for CSS coords).
- withGlobalTauri:true exposes window.__TAURI__.{core,event,webviewWindow,...}.
- Custom #[tauri::command]s are callable from JS without ACL permissions; the
  permission system gates core/plugin commands. core:default capability set,
  windows ["*"].

## Increment history
- 0.0.1 pipeline + bottom-most window proof.
- 0.0.2 PixiJS canvas: pan / zoom-to-cursor / draggable cards (single screen).
- 0.0.3 a canvas window per monitor (independent cameras).
- 0.0.4 size windows to monitor work area (taskbar no longer covers canvas).
- 0.0.5 data layer step 1: drop a file -> copy into Desktop Canvas folder ->
  labeled card at drop point -> position persisted across restarts (NO image
  thumbnails yet).

## Next steps (planned order)
- 0.0.6 render real images (PixiJS sprite via convertFileSrc + assetProtocol
  scope) instead of a label card; generic icon for non-images.
- Then: Windows shell thumbnails for any file type (IShellItemImageFactory via
  the windows crate) to match Explorer.
- Then: Copy/Move/Reference prompt on drop; references as .lnk shortcuts.
- Then: open file/folder on double-click; folder navigation (back/up) =
  "every folder is a canvas"; central SQLite store; tray icon; scale/rotate
  handles; list view; deletion-safety verbs; etc. See PLANNING.md.

## Debugging
- The frontend shows a red error bar (top of screen) on any JS error — ask the
  user to screenshot it. A proper logging/diagnostics export is still a TODO.
