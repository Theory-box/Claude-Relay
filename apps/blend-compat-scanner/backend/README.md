# backend — Relay engine

The local process that drives Blender for the UI. No Blender-Python here; it
launches short-lived headless `blender -b` subprocesses that exit on their own,
and cleans up every temp file it makes.

## Run it (dev)
```bash
python3 server.py 8765        # serves the UI at http://localhost:8765
```
`blenders.json` maps version → Blender executable (dev override). In the shipped
app this is auto-populated by scanning your installs and the app-managed folder.

## API
- `POST /api/scan`  `{path}` → `{detected, source, issues[], blenders{}}` — opens the
  file in the detected source Blender, returns issues in the UI's exact shape.
- `POST /api/convert` `{path, selected[], source_blender, target_blender, out}` →
  runs the two staged passes (source fixes + keep-node rebuild), writes `out`,
  returns `{out, source_fixed, rebuilt, kept}`. Never touches the input file.

## Pieces
- `engine.py` — orchestration: version detection from the .blend header, Blender
  discovery, scan, two-stage convert, cleanup.
- `scan_ui.py` — runs in source Blender; emits UI-format issues (reuses the tested
  scanner traversal + fixer registry, so nothing is duplicated).
- `convert_source.py` / `convert_target.py` — the two convert passes, selection-
  driven by the same issue IDs the UI stages.

## Packaging into a clickable app
Wrap this with **Tauri** (small installer, OS web view) or **Electron**: the web
view loads `ui/relay-ui.html`, this engine runs as the bundled sidecar. The UI
auto-detects the backend (falls back to demo data when served statically). Blender
builds are fetched on first run into the app folder if a needed version isn't
already installed.
