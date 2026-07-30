# repair/ — value-preserving fixers

Reconstructs breaking nodes so a file survives an older Blender. All fixers run in
the **source** version (full fidelity), carry input values, relink, and never
touch anything they don't understand. Diagnose first with the scanner; then:

```bash
blender-4.4 -b myfile.blend --python repair/apply_repair.py -- --out myfile_for_4.2.blend
```

`apply_repair` reports what it **fixed** vs **flagged** for manual handling, and
saves a copy (never overwrites the input).

## Verification standard
A fixer is only added to the registry after `repair/verify.py` confirms its output
is identical to the original by evaluation, and the saved file opens in the target
with no undefined nodes. Run the regression harness any time:

```bash
blender-4.4 -b --python repair/verify.py
```

## Fixers so far (all verified)
| node | strategy | notes |
|------|----------|-------|
| Set Geometry Name, Gizmo*, Warning | safe-drop | removed; geometry passthrough reconnected. Output identical. |
| Integer Math | reconstruct → Math node(s) | exact-equal for all 16 supported ops across signed inputs. GCD/LCM flagged (no Math equivalent). |
| **Blackbody** | bake → RGB / Color node | the pink-lights bug. Evaluates the constant temperature to its exact colour and replaces the node (tree-aware: RGB in shader trees, Color in geometry trees). Verified colour-identical across temperatures; repaired light file opens in 4.2 with zero issues. A **linked/animated** temperature can't bake to a constant → flagged. NB: a *link* into the raw temperature socket crashes 4.2 on load, so baking (not re-linking) is the safe fix. |

## Next fixers (planned, same verification bar)
- Object / Collection Input → group-input socket (reconstruct)
- Matrix Determinant → component arithmetic (reconstruct)
- Import OBJ/PLY/STL → realize geometry into stored mesh (bake)
- Volume Principled temperature (same subtype class; different node — not a pure
  temperature→colour bake, so needs its own approach).
