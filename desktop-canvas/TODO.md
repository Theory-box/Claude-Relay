# Desktop Canvas — TODO / Backlog

## Up next (requested, in order)
- [done v0.0.19] Un-restrict browsing; everything read-only except the Desktop Canvas folder.
- [done v0.0.19] Move "Tidy up" into the Sort submenu.
- [done v0.0.20] #4 Selection + box-select + multi-move (collisions + move-into-folder + trash).
- [ ] #5 Copy / Cut / Paste on item right-click (needs backend copy/move + a clipboard model;
      paste target must be writable).
- [ ] #6 Trash Can as a static screen icon (bottom-left), not a world object.

## Requested — batch 2 (newest)
- [ ] SPACE = search / find files in current folder. Wants a fast, easy in-folder finder
      (type-to-filter, jump to / highlight matches). Flagged as SOON / high priority.
- [ ] Fullscreen image viewer: open an image to full screen at full resolution; LEFT/RIGHT
      arrows step through the other images in the folder; Esc to exit.
- [ ] PDF viewing (in-app preview/reader).
- [ ] Selected-item Properties in the right-click menu (size, type, dates, path, dimensions...).
- [ ] Drag-OUT to other apps: dragging an item off the canvas/app puts it on the OS clipboard
      / starts an OS drag so it drops into other apps on release (e.g. pull an image straight
      into Blender). Needs native drag-source / clipboard support from the Tauri side.
- [ ] Move/copy items between DIFFERENT canvases (folders/spaces), including across windows:
      copy or move with a confirm for now.
- [done v0.0.22] Saved Spaces: bookmark folders via right-click empty -> Spaces > Save/Remove;
      Spaces dropdown in the bar; persisted to app-data spaces.json (survives exe updates).
      (Bookmark TABS still possible later.)


Running list of deferred work and ideas. Newest context at top of each section.

## Selection & active items (Blender-style) — requested, not started
- Click an item -> makes it the active/selected item (visible highlight).
- Shift-click -> add to selection. Ctrl-click -> remove from selection.
- Click-drag in empty space -> rubber-band box select.
- Ctrl-drag in empty space -> subtract from selection.
- Then: move / sort / delete / align operate on the whole selection.
- Needs an active-set data structure + highlight rendering + hit-testing that
  distinguishes "start box select" (empty) from "start move" (on item).

## Performance & collision (brainstorm)
- DONE v0.0.18: progressive chunked card build (40/frame) + time-budgeted relax
  after first paint (~14ms/frame) so big folders display fast instead of freezing.
- Broad-phase to kill O(n^2): bound each item with an inscribed CIRCLE for a cheap
  first-pass overlap test before the AABB/MTV step.
- Spatial hash / uniform grid so separation/push/sort only test nearby pairs (the
  real O(n^2) -> ~O(n) win for crowded folders).
- Distance fields — research idea for fast collision/repulsion queries.
- Thumbnail pipeline: cap concurrent thumb_data calls, cache thumbnails to disk,
  load visible-first / lazily. (Today every file requests a shell thumbnail at once.)
- Consider moving layout math to a Web Worker if it ever gets heavy.

## Bugs to watch (after v0.0.18)
- Intermittent "stops displaying folders/items, fixes when navigating elsewhere."
  Suspected the old reload-storm race; v0.0.17 added a load-generation token + loading
  guard that should fix it. CONFIRM it's gone; if not, investigate loadSeq aborts that
  leave a blank view.
- (When wider browsing is re-enabled) "can't open Documents — permission denied even as
  admin." Likely a known-folder / OneDrive redirect or ACL issue. Catch permission errors
  and show a friendly message instead of a blank canvas. Currently moot under SAFE_MODE.

## Placement / UX
- Padding between items during collision: DONE v0.0.18 (PAD=9). Tune to taste.
- Gate open-relax so INTENTIONAL Free-mode stacks are preserved (only auto-separate
  accidental/auto-placed overlaps, not hand-made stacks).
- Optional confirm before dropping onto the Trash Can (folders already confirm).
- OS-drop carry for MULTIPLE files (today multi-file imports place immediately;
  single-file imports get the sticky float).
- Rename files/folders.
- Real Windows Recycle Bin integration (today: app-local "Trash Can" folder).

## Engine roadmap (from ENGINE.md)
- Richer push settling (better cascade / optional animation).
- Multi-select align / distribute / tidy (needs selection first).
- Containers: folders/rows/columns/stacks that auto-arrange their children.

## Safety
- SAFE_MODE = true confines ALL file ops + browsing to the Desktop Canvas folder.
  Plan a deliberate, scoped re-enable of wider access later, ideally split read-only
  browsing from write/move/delete, with clear UI about what's allowed where.
