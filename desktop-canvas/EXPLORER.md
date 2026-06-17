# Explorer / Folder-tree view

Button: "explorer" right of the address bar (#explorerBtn); toggles. Escape exits.

## Vision (user)
Activating animates the canvas shrinking toward screen center (zoom-out feel); the current folder lands
at center with its connecting folders / file structure spread around it as a hierarchy tree; clicking a
folder zooms into it (its canvas/contents); double-click a folder navigates to it.

## STAGE 1 (v0.0.48) — DONE
- Rust folder_tree(path) -> { ancestors:[{path,name}] (immediate parent first, up to 6), current:{path,name},
  children:[{path,name}] (subfolders only, sorted, capped 60) }.
- Frontend: explorerOn mode. enterExplorer hides cards+grid, builds an explorerLayer (PIXI Container in
  world) of folder nodes: current centered (0,0), ancestors stacked above (96px steps), child folders in a
  row below (y=150, 196px spacing), connected by lines. camTween frames the tree (zoom-out feel).
- Double-click a node -> exitExplorer + navigate(path). Escape or button -> exit (reframe canvas).
- Pan = middle-drag, zoom = wheel (reused). Box-select + context menu suppressed while in explorer.
  navTo auto-exits explorer if a toolbar/crumb nav happens.

## TODO (later stages)
- The literal "canvas shrinks toward center" animation (currently a camera zoom-out tween approximation).
- Click a folder node to ZOOM INTO it showing its contents (canvas-in-canvas), vs double-click to navigate.
- Deeper tree (grandchildren), better layout (radial/force, avoid overlap on many children), pan-to-fit.
- Show file leaves (not just folders) / thumbnails; collapse-expand nodes.
- Scroll/perf for very large trees (cap + lazy expand).
