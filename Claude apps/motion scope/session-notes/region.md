# Region-based stabilization (branch feature/region, from main)

Reuses the proven grid estimator (estimateShiftRobust: 5x4 cells, per-cell block-match +
sub-pixel, drop low-texture cells, MEDIAN). Region control = restrict which cells vote:
each cell stores its normalized centre (cnx,cny); when regions exist, only cells whose
centre falls inside a region contribute to the median. inRegions() tests up to MAXREG=4 boxes.
Regions imply stabilization (gpuStabEstimate/CPU gate: run if stabilize OR regions.length;
drawing a box auto-setStab(true)).

UI: "Draw region" button -> drag a box on the stage -> release adds it (mode exits). Add up to 4.
Clear removes all. Boxes drawn bright while drawing/in draw-mode, faint (.idle) otherwise.
Letterbox-aware click->normalized mapping (stageToNorm) + normalized->stage px (normRect).
Placement disabled in compare mode.

This SUPERSEDES the fragile per-point marker tracker (parked on feature/tracking, unmerged):
grid cells have far more texture to lock onto than 13x13 patches, and the median across cells
rejects outliers. Multiple boxes on co-moving content add more trustworthy voting cells = firmer.
Handles in-place oscillating objects too (fixed box over the object -> stabilizes to its motion).

TEST: Draw region -> box around a steady thing -> it should hold that area still, movement
elsewhere ignored. Multiple boxes on steady features = steadier. Not for objects that
translate out of their box.
