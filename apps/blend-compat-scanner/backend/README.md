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

## The clickable app
`relay_app.py` opens the UI in a native window (pywebview) with the engine running
on a local port behind it. Closing the window exits everything; Blender never
lingers (tasks are short-lived `blender -b` subprocesses), and every temp file is
cleaned up. The native file picker (`Api.pick_blend`) provides the real .blend path.

Blender builds are auto-managed (`blender_manage.py`): the engine uses versions you
already have installed and downloads a portable build only for a target version you
don't have, into the app-data folder.

## Building the executable — no toolchain needed
GitHub Actions builds it for Windows / macOS / Linux with PyInstaller (pure Python,
so no Rust/Node). Run the **Build Relay** workflow from the Actions tab (or push a
`v*` tag to also cut a release); download the `Relay-windows` etc. artifact.

Locally (optional):
```bash
pip install -r apps/blend-compat-scanner/backend/requirements.txt
pyinstaller relay.spec            # -> dist/Relay(.exe)
```
The Blender-side scripts + compat DB ship as bundled data so the engine can point
Blender at them at runtime.
