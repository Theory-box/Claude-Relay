# Desktop Canvas — R&D Planning Doc

Status: Build phase. Increment 1 DONE + validated live (Jun 15 2026): CI build ->
zip relay -> runs. Borderless fullscreen, skipTaskbar, always-on-bottom all
working on the user's machine; clean quit; no glitches. Tray deferred. Currently
launches on primary monitor only (multi-monitor is a later increment).
Next: canvas (PixiJS pan/zoom + first item). Windows-only.
Working doc, updated as decisions land. Durable copy → repo once permitted.

---

## 1. Vision / North Star

A desktop-replacement app: an always-on, infinite spatial canvas that fuses a
PureRef-style reference board with file-explorer capability. Sits where the
wallpaper is; revealed by minimizing whatever's on top. Replaces the static
icon-grid desktop with something spatial and powerful.

**Unifying idea:** *every folder is a canvas, and navigation IS the filesystem.*
The app is a spatial shell over the file system. The always-behind window is the
"home" canvas. Clicking a folder navigates into it; that folder is itself a
canvas. Long-term horizon: grow into a full desktop + File Explorer replacement.
Designed toward that even though full replacement is not the first build.

Primary use case ("the blender"): gather files, folders, images, and notes that
are normally scattered everywhere into one spatial place — some copied in, some
referenced — to organize and work (notes, drawing over images, visual reference).

---

## 2. Locked Decisions

### Platform & window
- Windows only.
- Window model **B**: borderless full-screen, pinned to bottom of Z-order,
  hidden from taskbar, tray icon in the hidden-icons overflow, launch on login.
- Real desktop icons hidden; the canvas IS the desktop. Auto-restore real icons
  if the app exits (never leave a blank desktop). Handle explorer.exe restart.
- Reveal by minimizing other windows ("minimize anything in the way").

### Multi-monitor (3 screens)
- Separate canvas surface per monitor; each screen navigates independently
  (own pan/zoom/camera, own current folder, own nav history).
- Setting to toggle: shared canvas (each screen a camera into one space) vs.
  separate boards per screen.

### Interaction (PureRef-style)
- Drag empty = pan; scroll = zoom to cursor; drag item = move; selection handles
  = scale/rotate; right-click = context menu; double-click folder = navigate in;
  double-click file = open. Back / forward / up navigation.

### Data model (KEY)
- **Central app store** for all spatial/presentation metadata (item positions,
  scale, rotation, z-order, display mode, annotations, favorites, home, settings).
  Lives in AppData. Real folders stay clean — NO metadata files dropped into
  browsed folders.
- Keyed to folders robustly (NTFS file IDs + path reconciliation) so external
  renames/moves don't orphan layouts.
- Portability is an explicit opt-in **Export** (bundles files + layout).

### Files & items
- Accept ANY file type (like Explorer).
- **Icon view** = Windows shell thumbnail/icon for any file (universal, matches
  Explorer, picks up app-provided thumbnails e.g. .blend).
- **Expanded view** = our richer render for natively-supported types (full-res
  image w/ scale+rotate, editable text, PDF preview); fallback to large shell
  thumbnail + open-with for the rest (3D, .blend).
- Per-item toggle between icon / expanded. Folders default to icon view.

### Folder loading / layout
- Open a folder → ALL items shown as icons, auto-arranged in a grid by default.
- Rendering virtualized (only draw what's on screen) so large folders stay fast.
- User can move/scale/rotate any item freely; moved items keep custom positions,
  untouched items stay in the grid.
- An **Organize** tool re-arranges everything; grid-snapping options (on/off +
  grid size). New files drop into the next open grid slot.
- A **list view** is an alternate way to view the same folder (no separate tray;
  no drag-from-list-to-canvas).

### References / copy / move
- On drop, prompt each time: Copy / Move / Reference.
- Copy/Move → real files placed in the folder. Default is real files.
- Reference (explicit choice only) → a real Windows .lnk shortcut. No shortcuts
  created behind the user's back. (View-only/no-file references: dropped.)

### Notes & drawings
- App-layer **annotations** by default (sticky notes, labels, ink over images),
  stored centrally with the canvas — never written into the folder.
- Promote on demand: "Save as document" → real .md/.txt in folder; drawing
  "flatten/export" → real .png/.svg. Then it's a normal file item.
- Text tool v1: width-set block, wrap to width, font options (family/size/
  weight/color/align), content overflows downward past the block rather than
  clipping. Rich text (headings/lists/inline styles) is a later phase.
  [OPEN: overflow-spill vs grow-block-height — unconfirmed detail.]

### Deletion safety
- Three distinct verbs:
  1. Remove from canvas — unplace; file untouched (references never touch target).
  2. Move to Recycle Bin — default destructive action (recoverable, native).
  3. Delete permanently — separate, sterner confirm.
- Confirm prompts on anything destructive; extra warning when deleting a
  reference's target.

### Right-click
- For real file/folder items: invoke the actual Windows shell context menu via
  COM (IContextMenu) — surfaces real entries incl. installed extensions (7-Zip,
  WinRAR, Send To, Properties, Open With). We delegate, not reimplement.
- For canvas-native items (notes, drawings, portals, mixed multi-select): our
  own menu. Hybrid.

### Save/load canvases (reframed)
- Subsumed by "every folder is a canvas" + auto-saved central layout:
  loading a canvas = navigating to a folder; saving is automatic.
- Leftover quick-access features folded in: a **home** canvas the desktop opens
  to, and **favorites/bookmarks** for common boards.

---

## 3. Architecture (recommendation, in progress)

### Recommended stack
- **Shell: Tauri v2** — Rust backend + Windows WebView2 frontend.
- **Image canvas: PixiJS (WebGL)** — GPU sprites for many large images, smooth
  pan/zoom, low CPU.
- **UI chrome + text: DOM layer** over the WebGL canvas (native font rendering,
  wrapping, future rich text); lightweight frontend framework (Svelte/Solid or
  vanilla) for chrome. Tray/menus are native.
- Rationale: best fit for always-on (small footprint, ~30-50MB RAM, sub-0.5s
  start), capable canvas (mature web canvas ecosystem), fast UI iteration
  (web hot-reload). Confidence ~0.7 over the main alternative.

### Serious alternative: C# / .NET (WinUI 3 + Win2D or SkiaSharp)
- Proven for this exact desktop-shell behavior (Lively Wallpaper is WinUI 3/C#).
- Cleanest Win32/COM shell interop (CsWin32). Windows-only removes Tauri's
  portability edge. Flip to this if C#/.NET is the more comfortable/maintainable
  stack for whoever builds it. Canvas layer is more DIY than PixiJS.

### Ruled out
- **Electron** — too heavy for an always-on app (100-200MB RAM, bundled
  Chromium). Conflicts with the core requirement.
- **Pure native C++ (Direct2D/D3D)** — best runtime, but iteration/time-to-MVP
  too slow for the R&D pace; rich text + UI built from scratch.

### Layered architecture
1. **Native core (Rust):** OS integration — window/Z-order/WorkerW, desktop-icon
   hide/restore, shell thumbnails + cache, shell context-menu host, file ops
   (Recycle Bin via IFileOperation), .lnk read/write, folder watcher, multi-
   monitor/DPI, tray, autostart, single-instance. Exposes commands + a custom
   asset protocol.
2. **State/data layer:** central metadata store (SQLite in AppData) — folder
   layouts keyed by file-id/path, item transforms/display-mode/z-order,
   annotations, favorites/home, settings.
3. **Render/UI (WebView2 frontend, TS):** one PixiJS scene + camera per monitor;
   DOM overlay for text + chrome; interaction (pan/zoom/select/transform);
   virtualization; grid auto-arrange + Organize tool; list view.

### Key technical notes
- Big-image data does NOT cross JSON IPC. Register a custom asset protocol so the
  WebView loads files/thumbnails directly from disk as URLs (no pixel
  serialization). Removes the main Tauri data-path concern.
- Likely one WebView2 window per monitor, each pinned bottom on its monitor.
- WorkerW / bottom-most + WebView2: do SetWindowPos/SetParent on the HWND via the
  Rust `windows` crate. Precedent exists (webpage wallpapers). Some quirk risk.
- **Testability:** keep as much logic as possible OS-agnostic (layout/grid math,
  state reducers, data model) so it's unit-testable off-Windows; keep a thin
  Windows-only integration shell. Important because the Windows-native behavior
  can only be run/tested on a real Windows machine.

### Dev / test loop
- Cannot run or test Windows-native behavior in the Linux dev sandbox (no Windows
  VM; Win32/COM/WebView2/WorkerW don't run there). The actual run+test loop is on
  the user's Windows machine.
- Tauri dev server + hot-reload makes the frontend loop fast on Windows. Rust
  backend compiles are the slower part of the loop (bounded set of modules).

---

## 4. Open threads / later phases
- Text-block overflow detail (spill vs grow).
- Multi-select / marquee / group ops.
- Search across folders.
- Drawing tools scope.
- File conversions / productivity tooling.
- Zoom-to-fit, mini-map.
- Reference target-moved handling (.lnk break behavior).
- Home canvas definition (Desktop folder vs dedicated home).

---

## 5. Build phasing (draft)
- MVP: window + per-monitor canvas + pan/zoom + folder load as grid of shell-
  thumbnail icons + move items + central store + open files.
- Phase 2: references/copy/move + notes + .lnk + list view + favorites/home.
- Phase 3: shell context menu + deletion safety verbs + expanded image view +
  scale/rotate + Organize/snapping.
- Phase 4: drawing, rich text, search, conversions; polish; behind-icons mode.

---

## 6. Workflow: build / install / update / debug (no-console)

Constraint: user never opens a code editor or console. AI writes all code.

### Build & delivery (cloud CI — chosen, verified)
Core constraint: AI builds in a Linux sandbox and cannot compile/test Windows
Tauri apps there, so the Windows compile must happen elsewhere.
- CHOSEN: GitHub Actions on free GitHub-hosted `windows-latest` runners compiles
  on every push and publishes a ready-to-run app. VERIFIED LIVE (Jun 2026):
  auth + repo write confirmed against the repo; Windows runners are free (public
  repos unlimited; private repos free monthly quota then ~$0.01/min, Windows 2x).
  Setup = one YAML file; runners ship with Rust+Node preinstalled. User manages
  nothing; gets a finished app to download / auto-update.
- RESOLVED (Jun 2026): token now has `workflow` scope. Full pipeline verified
  end-to-end live — workflow pushed, free `windows-latest` runner ran to success
  (compiled + executed a Rust binary), ~67s total. Test branch deleted after.
- Delivery (CHOSEN — manual zip relay, no auto-update, fully private):
  CI builds the Windows app and uploads it as a workflow artifact (zip). AI
  downloads the artifact via API (token) and hands it to the user in chat via
  present_files. User downloads the zip and applies it with a small updater
  (in-app "Update from file" button or a tiny companion): select zip -> verify
  -> swap files -> relaunch (a helper handles the can't-overwrite-running-exe
  problem by closing, swapping, reopening).
  => repo stays fully private; no auto-update endpoint, no proxy, no public repo,
  no token baked into the app. The app never phones home; AI is the delivery
  channel.
  First install: one-time run of an installer/portable build; thereafter the
  zip-feed flow. Optional: sign/checksum the zip so a corrupt file can't apply.
- (Dropped: Tauri remote auto-updater, public-releases repo, and proxy options —
  superseded by manual relay.)
- FALLBACK (if cloud ever undesired): local automated build on user's Windows
  machine (setup app + updater app; build output captured to copyable logs;
  heavy one-time toolchain install).
- BONUS: AI cross-compile from Linux (cargo-xwin) -> zip; unsupported/
  unverifiable, not relied upon.
- Code signing: unsigned => one-time SmartScreen "run anyway"; optional self-sign.

### Debug / logs (one button)
- App logs continuously to a rolling file: Rust side (tracing) + frontend/canvas
  console piped to the same sink.
- "Copy diagnostics" button (tray menu): bundles recent logs + environment
  (Windows version, GPU, app version, monitor layout) to clipboard; user pastes
  to AI.
- Crashes: catch panics/errors, surface friendly "click to copy report" dialog,
  same bundle.
- Privacy: build in path/username redaction so pasted diagnostics are safe.

### Testing reality
- AI cannot run the app (Linux sandbox; no Windows VM).
- Mitigations: (1) CI catches all compile errors before any build reaches user;
  (2) OS-agnostic logic (grid/layout math, state, data model) has unit tests that
  run in CI; (3) user's one-click diagnostics close the runtime loop.
- Net: a few more round-trips than live testing, kept short by good logging.

### Things the user ever touches
- A download link (once), the app, a "copy diagnostics" button. Nothing else.

### Needs repo access (later, on user go-ahead)
- Actions workflow, Releases, updater endpoint, signing key. Not set up during
  R&D.
