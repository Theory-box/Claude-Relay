# blend-merge-analyzer

Standalone desktop app that reads the object names in a heavy Revit-exported `.blend`,
discovers the naming patterns on its own, and lets you interactively group, **merge**,
and **delete** objects — collapsing hundreds of thousands of objects down to a workable
count. The app never merges on its own; every merge or delete is a button you press,
and nothing runs until Execute. The original file is never modified unless you turn off
"save as copy" (which asks first).

See **DESIGN.md** for the full interaction spec and data findings.

## Run it — pick one

**A. One-click (no build):** requires Python 3.9+ already installed.
- Windows: double-click `Run-MergeAnalyzer-Windows.bat`
- macOS: double-click `Run-MergeAnalyzer-Mac.command` (first time: right-click → Open)

The launcher installs two small Python packages the first time, then opens the app window.

**B. One `.exe` (no Python):** built automatically by GitHub Actions
(`.github/workflows/merge-analyzer-build.yml`). Download `MergeAnalyzer.exe` from the
build artifacts (or a tagged release) and double-click. Mac gets a `MergeAnalyzer` binary the same way.

## How it works

- Reads the `.blend` **header** to detect its Blender version (no Blender needed).
- Runs your installed **Blender headless** to extract every object name to JSON — fast,
  data-only, no window. Pick which Blender build to use from the dropdown; missing
  versions can be fetched as portable downloads.
- All analysis and grouping happen in the app (instant, no Blender).
- **Execute** hands the plan to headless Blender: it make-single-users to collapse
  linked-duplicate "instances", joins each merge group to one object, deletes delete
  groups, and saves a **copy**. **Execute & open** does the same, then opens the result
  in Blender so you can inspect it.

## Structure

```
backend/   relay_app.py (shell) · server.py (API) · engine.py (headless Blender orchestration)
           analyze.py (name analysis) · blender_manage.py (Blender discovery/download)
ui/        merge-analyzer.html   — the entire UI, one self-contained file
tools/     make_test_scene.py    — builds a synthetic test scene inside Blender
```

Verified headless on Blender 4.4.3 against a 1,000-object synthetic scene: merge,
delete, instance-collapse, and large-group batching all produce exact object counts
with zero Blender errors.
