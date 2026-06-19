# Desktop Canvas — TODO & Optimization Notes

_Last updated v0.0.87. main stays clean; work on feature/desktop-canvas._

## Recently shipped (don't rebuild)
- Core: per-monitor bottom canvas, pan/zoom/drag, drop-to-card, thumbnails, trash, folders + nav + address bar, placement engine, selection + box-select, saved spaces, search, copy/cut/paste/shortcut, back/forward, split panes + session restore, native drag-out, portals, zip/extract.
- Rename; basic web window; smooth zoom + pan/icon momentum; image viewer right-click (partial).
- Background images: folder cycle, fit/fill, orientation filter, opacity, crossfade, screen-size downscale, parallax (cursor-driven).
- Toolbar distance-fade; "Add" submenu; render-on-demand; PDF viewer + DPI export/drag-out + image-editor pan/zoom.
- SpaceMouse Compact pan/zoom with Preferences (speed/deadzone/invert), active-window targeting.
- Sort a selection into a drawn area (overflow downward).
- Viewport culling of off-screen cards.
- Diagnostics: perf overlay + 45s perf log (fps/jank/heap/texCache/DOM/long-tasks + Long-Animation-Frame attribution).

## Performance / optimization (audit) — ordered by value, all "no visual sacrifice" unless noted
1. **Don't wake the render loop on plain pointermove.** `wake` is bound to `pointermove`, so moving the mouse renders the scene continuously even though nothing on the canvas changes on hover (the only highlight `hl` appears during a drag). Drags/pans/zooms/animations/SpaceMouse already keep the ticker awake on their own (carry/camTween/panVel set `__act`). Removing `pointermove` from the wake list lets the canvas idle while you just move the cursor — likely the single biggest idle-CPU/GPU win. (~100 wasted renders/sec seen in logs.)
2. **Free thumbnail textures + bound the thumb cache (memory leak).** `loadTexture` caches every thumbnail in PIXI's global TextureCache by data-URL and `card.destroy({children:true})` never frees the texture/baseTexture; `thumbCache` keeps every data-URL string forever. Long sessions with lots of navigation grow RAM/VRAM → GC stalls. Fix: destroy textures on card teardown (or LRU-cap the cache) and bound/clear `thumbCache` on navigation. Directly addresses "gets heavier over time."
3. **Toolbar fade: stop the per-frame layout read + redundant writes.** `setBarFade` calls `getBoundingClientRect` every mouse-move frame (forced layout) and writes `#bar` opacity every frame even when unchanged. Cache the bar rect (recompute on resize) and only write opacity when it changes by a threshold.
4. **Throttle the per-frame `diag.textContent` rebuild + `drawSelection`.** Both run every ticker frame; the diag string allocates each frame (GC churn) and selection graphics are redrawn even when nothing moved. Update diag ~4x/sec or on-change; redraw selection only on selection/camera change. (Much smaller once #1 lands, since the ticker won't run during plain hover.)
5. **Perf overlay non-persistent.** It currently saves to PREFS and restarts on launch; an always-on rAF + 250ms timer per window. Make it always start off so it can't be left on and silently tax every session.
6. **Grid as a TilingSprite.** The default dot grid is ~2,600 tessellated circles in one Graphics, redrawn every awake frame when no background image is set. A 1-tile TilingSprite is ~2 triangles and also makes the grid effectively infinite (currently bounded to ±1600). Visual result identical.
7. **Background image via temp-file asset URL instead of base64 data-URL over IPC.** `bg_image` returns a multi-hundred-KB base64 string that's decoded on the main thread each cycle x3 monitors. Writing the downscaled JPEG to temp and loading it via the asset protocol avoids the base64 + IPC payload and the per-cycle main-thread cost.
8. **Consolidate the window `pointermove` listeners** (wake, parallax, bar-fade, perf-ptr, spacemouse) into one dispatcher to cut per-event dispatch overhead. Minor.
9. **PIXI tweaks:** `powerPreference:'high-performance'`; keep `antialias:true` (no visual sacrifice goal). Consider only redrawing selection/diag on change.

## Feature backlog
- Backgrounds Pass 2: custom grid/background colors; per-monitor independent images.
- Image viewer right-click: add Rename / Delete / Properties (needs body-level dialogs above the viewer).
- Web: save a site as a shortcut card that opens a web panel; live web nodes.
- Bigger: Image->PDF builder; fun widgets (chess, sticky notes, calculator, clock, paint); minimap; shared top bar for split panes; texture streaming / LOD for huge images.
- Medium: viewer/editor windows that span all monitors (currently clipped to one); drag-out copy/move prompt; "gather" move mode.
- Smaller: undo/redo; native copy-progress dialog (IFileOperation); bookmark tabs; confirm-before-trash-drop.
- SpaceMouse extras: twist as alternate zoom; the two buttons -> frame-all / reset; device hot-plug re-detect.

## Deferred
- RAR creation (no built-in Windows archiver).
