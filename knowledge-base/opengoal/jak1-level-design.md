# Jak 1 Level Design — Living Knowledge Base
> First iteration — based on a single level (Village 1 / Sandover Village).
> Treat everything here as a hypothesis to test against more levels, not established fact.
> Updated as more levels are analyzed.

---

## How to Analyze a Level Geometrically

### What you need
- A level GLB file from OpenGOAL's decompiler output
- Location: `<opengoal_install>/active/jak1/data/decompiler_out/jak1/glb_out/`
- Python with `trimesh`, `numpy`, `matplotlib`, `scipy`

### Memory warning
Background GLBs can be 40-60MB+ and contain 60M+ vertices when loaded naively.
**Do not** `concatenate` all meshes at once — you will OOM.
Instead: iterate mesh-by-mesh, extract only what you need (sampled verts, floor verts), discard the rest.

```python
import trimesh, numpy as np, gc, warnings
warnings.filterwarnings('ignore')

scene = trimesh.load(path, force='scene', process=False, skip_materials=True)

floor_points = []
all_samples = []
SAMPLE_RATE = 8  # tune based on file size

for name, geom in scene.geometry.items():
    if not hasattr(geom, 'vertices') or len(geom.vertices) == 0:
        continue
    verts = np.array(geom.vertices)
    faces = np.array(geom.faces) if hasattr(geom, 'faces') else np.array([])

    all_samples.append(verts[::SAMPLE_RATE])

    if len(faces) > 0:
        v0, v1, v2 = verts[faces[:,0]], verts[faces[:,1]], verts[faces[:,2]]
        normals = np.cross(v1-v0, v2-v0)
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        norms = np.where(norms==0, 1, norms)
        normals /= norms
        up_mask = normals[:,1] > 0.6  # tune: higher = stricter "flat" requirement
        if up_mask.sum() > 0:
            fidx = np.unique(faces[up_mask])
            floor_points.append(verts[fidx][::2])

    del verts; gc.collect()

all_samples = np.vstack(all_samples)
floor_verts = np.vstack(floor_points) if floor_points else np.array([])
```

### Core metrics to extract

**1. Bounds & scale**
```python
size = all_samples.max(axis=0) - all_samples.min(axis=0)
# size[0]=X width, size[1]=Y height, size[2]=Z depth
height_width_ratio = size[1] / max(size[0], size[2])
```

**2. Height layer distribution** — how is walkable geometry distributed vertically?
```python
fy = floor_verts[:,1]
# divide into N bands, count verts in each
# look for: where is the mass? how many layers have significant presence?
```

**3. Linearity via PCA on XZ floor**
```python
xz = floor_verts[:,[0,2]]
cov = np.cov((xz - xz.mean(axis=0)).T)
eigvals, _ = np.linalg.eigh(cov)
eigvals = eigvals[::-1]
linearity = eigvals[0] / eigvals.sum()
# >0.8 = highly linear, 0.6-0.8 = directed, <0.6 = open/branching
```

**4. Platform cluster detection**
```python
from scipy.ndimage import label as ndlabel
# rasterize floor XZ onto a grid, connected-component label it
# cluster count, sizes, and distribution tell you a lot about space fragmentation
```

**5. Zone height variance**
```python
# divide level into NxN spatial zones
# for each zone: count verts, mean height, height std, height range
# low std = flat safe ground, high std = walls/cliffs/boundary
```

### Visualizations worth generating
- **Top-down scatter** (XZ): all geo in blue, walkable in green — gives you the map shape
- **Height heatmap** (XZ grid, color = max Y): shows elevation landscape
- **Density heatmap** (XZ grid, color = vert count): shows traffic/design intent zones
- **Side elevation** (X vs Y): shows the vertical silhouette
- **Height histogram**: distribution of walkable Y values — reveals the "floors" of the level
- **Cluster map**: each connected walkable zone colored differently

---

## What We've Observed So Far

> **Source:** Village 1 (Sandover Village) background GLB only.
> One level is not enough to generalize. These are starting hypotheses.

### Village 1 — Raw Numbers
| Metric | Value |
|---|---|
| Footprint (XZ) | 14,166 x 7,291 units |
| Height range (Y) | 418 units |
| Height/width ratio | 0.029 (very flat relative to footprint) |
| Walkable verts in bottom 2 height bands | ~86% |
| Walkable verts in 3rd height band | ~13% |
| PCA linearity score | 0.634 (moderately linear) |
| Platform clusters (50u resolution) | 274 raw, 37 significant |
| Dominant cluster size | ~1000 x 1350 units |
| Central zone height std | 19.3 (very flat) |
| Peripheral zone height std | 65–107 (walls/cliffs) |

### Hypotheses about Jak 1 design pillars
These came from the Village 1 data. **Test against other levels before trusting them.**

**Legibility over complexity**
Almost all walkable surface lives in a narrow height range. The geometry makes it visually obvious what is floor and what is boundary. Likely intentional for a 2001 audience new to 3D platformers — but we need more levels to confirm this isn't just a village-specific choice.

**Height as punctuation**
The ~13% of verts in the elevated band (rooftops, cliff paths) is where power cells live. Elevation seems to signal reward, not default traversal. Hypothesis: Jak 1 uses height as a destination, not a medium.

**Hub density vs spoke sparsity**
One massive low-variance cluster dominates the center. Peripheral zones are sparse with high height variance. This suggests the hub is a "safe social space" — low demand, high legibility — while challenge lives in the spokes. Needs validation on levels like Misty Island or Snowy Mountain.

**Directed flow disguised as openness**
63.4% linearity is higher than you'd expect from a "free roam village." The geometry is guiding you even when you think you're wandering. This might be a consistent Jak 1 technique — using world shape for implicit navigation without waypoints.

**Boundary via sparseness**
Peripheral geometry has almost no walkable verts but extreme height variance. Suggests cliffs/walls are used as natural level boundaries rather than invisible walls. The *absence* of walkable geometry communicates "don't go here."

---

## Open Questions
- Do more linear levels (Fire Canyon, Lava Tube) show >0.8 linearity scores?
- Does verticality score increase meaningfully in Snowy Mountain or Forbidden Forest?
- Is the hub density pattern unique to Village 1 or repeated in Volcanic Crater?
- What does the cluster map look like for a level with deliberate multi-path design (Misty Island)?
- Can we detect chokepoints by finding grid cells that connect two otherwise disconnected clusters?
- How do enemy spawn positions correlate with the density/openness maps?
- The `village1cam-lod0.glb` file had 50k verts but only 2 faces — unclear what this represents. Worth investigating.

---

## Files Analyzed
| File | Level | Date | Notes |
|---|---|---|---|
| village1-background.glb | Sandover Village | 2026-04-06 | First analysis. Background geo only. |

---

## What to Analyze Next
Suggested sequence to build a comparison dataset:
1. `firecanyon.glb` — expected: high linearity, low verticality
2. `misty.glb` — expected: multi-cluster, moderate linearity
3. `snowy.glb` — expected: high verticality score
4. `robforest.glb` — expected: dense canopy, enclosed areas
5. `volcanic.glb` — expected: second hub, compare structure to village1
