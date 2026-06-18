# Desktop Canvas — TODO

Windows-only desktop-replacement: infinite spatial canvas fused with a filesystem browser.
AI writes all code; built on GitHub CI, delivered as a bare exe. Branch: feature/desktop-canvas.

---

## Done

### Core canvas & files (v0.0.1–0.0.43)
- Per-monitor always-on-bottom window; pan / zoom-to-cursor / drag.
- OS drop → copy + card + persisted layout; cross-window sync; shell thumbnails.
- Folders + navigation + address bar + Back/Forward; drives view at top.
- Placement engine: carry/preview, Free vs Push, collision sort, padding.
- Trash Can (app-local) + confirms; reload-storm fix; SAFE_MODE.
- Selection + box-select + multi-move; Saved Spaces (persisted bookmarks).
- Search (Space) + Ctrl+F; copy / cut / paste; copy-as-shortcut (.lnk).
- Folder-shortcut (.lnk to folder) navigates in-canvas.
- Native drag-OUT to other apps (single + multi) via SHDoDragDrop.
- Split panes + per-monitor session restore; per-pane coord + zoom isolation.

### Viewers & editing
- Floating image viewer (movable/resizable, arrow paging, zoom/pan) (v0.0.45).
- Text files: New Text File + floating editor (Save/Ctrl+S/Esc, Ctrl+scroll font) (v0.0.47).
- Name truncation, error-bar ×, Properties panel, in-app open by default (v0.0.54).
- MULTI-INSTANCE viewers + editors with focused-overlay keyboard routing (v0.0.58).

### Portals (v0.0.55–0.0.57)
- Bidirectional shortcuts; two-token placement; click-teleport; drag-reposition; delete pair.
- Square tile + portal disc; spawn-in-view; show-as-you-place; broken portals auto-remove.

### Archives (v0.0.57)
- Zip (Compress-Archive) on file/folder/multi-select; Extract here (Expand-Archive) on .zip.

---

## Backlog

### Next build (decided)
- RENAME files / folders (in-place rename; in_root-guarded; refresh layout key).

### Settings / Preferences window  (NEW — phased)
- Button top-right, right of "Go to", labelled "Settings". Global settings persisted to
  app_data/settings.json (load/save like portals); applied on launch + live on change, all panes/windows.
- BACKGROUND IMAGE (replaces the grid). Implement as a screen-fixed DOM layer behind the
  transparent Pixi canvas (NOT in the world — does not pan/zoom). Phases:
  - P1: single chosen image on all screens. Scale-to-fit vs scale-to-fill (object-fit
    contain/cover — never stretch; fill expands beyond border + crops). Transparency slider
    fading image → default background (0 = default bg).
  - P2: GRID settings (point spacing, point color, background color) for grid mode.
  - P3: crossfade between images (two stacked layers, opacity transition).
  - P4: folder select → cycle every X seconds, random order; landscape-only vs portrait-only filter.
    Single shared image across all screens first (simplest).
  - P5: per-monitor random image; avoid showing the same image on two monitors (needs
    cross-window coordination via a shared command/store — windows are separate processes).
  - P6: per-monitor folder selection.
  - P7: PARALLAX — slight bg pan on mouse-move (depth effect). Cheap (CSS transform only);
    image scaled with overscan (~1.05–1.08x) so panning never reveals edges.
  - Split-screen panes share one background (same process — easy; preferred).

### Image viewer / text editor right-click  (NEW)
- Right-click inside the image viewer (and text editor): "drag/move out to another app"
  (reuse SHDoDragDrop), Properties, and file-type-appropriate actions (open with, etc.).

### Embedded web browser  (NEW — feasibility noted, future)
- Use Tauri's built-in WebView2 child webviews (Chromium core, same engine as Brave/Chrome) —
  embeddable with NO default toolbar (we supply our own chrome). Brave itself can't be embedded
  (only launched externally); WebView2 gives the same engine.
- Little web viewer with our own toolbar (back/fwd/url) = very feasible (like the image viewer).
- Sites saved as shortcut cards (store URL) → click opens a web panel. Trivial.
- "Pages as nodes": live web content is a separate native layer ABOVE the Pixi canvas — it
  repositions on pan and can set a zoom factor, but won't truly scale/integrate like a sprite.
  Cheaper pattern: node shows a snapshot/thumbnail card; clicking "wakes" it into a live webview.
- Watch memory: each live webview is a real browser instance — cap concurrent live nodes,
  snapshot inactive ones. (CEF/other engines = too heavy; WebView2 is the right tool.)

### Other bigger features
- IMAGE → PDF builder window (drag images, grid = page order, reorder, Process → draggable PDF).
- PDF VIEWER (floating, page/zoom/pan like image viewer).
- FUN WIDGETS / SUB-APPS (chess vs computer first; sticky notes, calculator, clock, paint, visualizer).
- TEXTURE STREAMING / LOD for images (display-res + mipmaps; then zoom-driven full-res + culling).
- SHARED TOP MENU BAR for split panes (focused-pane-driven).
- MINIMAP overlay with a draggable viewport rectangle.

### Medium
- VIEWER/EDITOR windows span all monitors (currently each floating window is clipped to its
  own monitor's window; make them carry across screens — needs a separate top-level OS window
  not bound to one monitor).
- SORT/RELAX scoped to selection (fall back to everything if nothing selected).
- DRAG-OUT copy/move prompt when dropping onto another canvas/window.
- "GATHER" move mode: selected items cluster around the dragged item.

### Smaller / parked
- Static bottom-left Trash icon.
- Undo / redo for item placement + movement.
- Native Windows copy-progress dialog (IFileOperation on a worker thread, non-freezing).
- Gate open-relax so intentional Free-mode stacks aren't auto-separated.
- Confirm before dropping onto Trash.
- Bookmark TABS (alongside Saved Spaces).
- Perf: spatial-hash / inscribed-circle broad phase; thumbnail cache + lazy/visible-first load.

### Deferred (blocked)
- RAR creation — Windows has no built-in archiver; would need a bundled tool.

---

## Notes
- Real Windows Recycle Bin integration (today: app-local Trash Can folder).
- Explorer / folder-tree view was built (v0.0.48–52) then removed v0.0.53 as not useful;
  physics sandbox preserved at prototypes/explorer-physics-sim.html, notes in EXPLORER.md.
