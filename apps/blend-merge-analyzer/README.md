# blend-merge-analyzer

Standalone desktop app that analyzes object names in a heavy Revit-exported `.blend`,
discovers naming patterns automatically, lets you build grouping lists interactively
(word cloud → dynamic Venn lists), and collapses each group into one object via
headless Blender on Execute. The app never merges on its own — every merge is a
manual per-list action.

Sibling of `blend-compat-scanner`; reuses its Blender discovery/download layer.

See **DESIGN.md** for the full spec, data findings, and architecture.

Status: design locked, implementation not started.
