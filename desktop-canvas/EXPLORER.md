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

## STAGE 2 (v0.0.49) — DONE
Recursive lazy RADIAL tree that grows in real time. Each node animates out from its parent (grow 0->1,
scale+position lerp); lines redrawn each frame. Expansion is VIEWPORT-GATED: stepExplorer (own ticker)
expands one visible, fully-grown, unexpanded node per ~8 frames -> tree grows outward and continues as you
pan (nodeVisible check on cx/cy). Children placed in parent's angular sector; adaptive radius
R=max(190+depth*16, 210*k/span) capped 1600 to avoid sibling overlap; child sub-sector = span/k*0.82.
Root current folder centered, sector [-0.15pi,1.15pi] (down+sides, avoids the upward ancestor chain which
stays as a non-expanding vertical chain). list_dir reused for lazy children; results cached in treeCache
(animation always replays). Toggle button / Esc -> exitExplorer(true) restores the saved prior camera
("go back to where you were"); double-click a node -> exitExplorer(false)+navigate (new folder reframes).
Space-bar search filters nodes (explorerSearch dims non-matches via con.alpha).

## TODO (later stages)
- CROSS-BRANCH overlap still possible on bushy/deep trees (only sibling overlap is handled). Needs a real
  collision/force pass or tidy-radial layout. KNOWN tuning area.
- No pruning of off-screen nodes yet (they persist + lines redrawn every frame) -> perf cap for huge trees.
- The literal "canvas shrinks toward center" animation (currently a camera zoom-out tween approximation).
- Click a folder node to ZOOM INTO it showing its contents (canvas-in-canvas), vs double-click to navigate.
- Deeper tree (grandchildren), better layout (radial/force, avoid overlap on many children), pan-to-fit.
- Show file leaves (not just folders) / thumbnails; collapse-expand nodes.
- Scroll/perf for very large trees (cap + lazy expand).
