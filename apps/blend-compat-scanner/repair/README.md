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
| Matrix Determinant | reconstruct → SeparateMatrix + Math cofactor expansion | verified numerically vs the native determinant for random 4×4 matrices. Needs a matrix source (unlinked input → flagged). |
| **Blackbody / Volume Principled** (preferred: keep the node) | two-stage rebuild | the pink-lights bug and its siblings — the socket subtype (`NodeSocketFloatColorTemperature`) is missing in the target so the value drops. `keep_nodes_run.py` extracts each at-risk value in the source, then rebuilds each node as a fresh **native** node in the target, preserving its other sockets/links. Verified: light BB (6000K) + material BB (4000K) + Volume Principled (Temp 5500K, Density 0.4 preserved) all come back correct on the client's 4.2 reopen. |
| Blackbody (alternative: bake) | bake → RGB / Color node | `fixers.fix_blackbody`, opt-in. Evaluates the constant temperature to its exact colour and replaces the node (tree-aware). Verified colour-identical across temperatures. Use only if replacing the node with a colour is acceptable. |

> Why two-stage: the value is genuinely gone in the target file (the degraded socket
> stores nothing), and a *link* into that socket crashes the target on load — so the
> value must be re-applied by rebuilding a fresh node in the target. Which nodes/
> sockets qualify is read from the compat DB (subtype changes whose subtype is in
> `socket_types_new`), so it generalises to any such node. One command orchestrates
> both Blender versions:
>
> ```bash
> python3 repair/keep_nodes_run.py \
>   --source-blender /path/to/4.4/blender --target-blender /path/to/4.2/blender \
>   --in scene.blend --out scene_for_4.2.blend
> ```

## Flagged with guidance (intentionally not auto-fixed)
Some nodes have no clean, safe reconstruction and are reported with actionable
detail instead of a fragile auto-fix:

| node | why manual | guidance given |
|------|-----------|----------------|
| Object / Collection Input | inlining an object/collection in the target needs a group-input socket + a modifier-level value (fragile, worse in nested groups) | names the referenced object/collection to recreate as a group input |
| Import OBJ/PLY/STL | injecting constant geometry hits the same "no inline object reference" wall | reports the file path to re-import or realize |
| For-Each zone, Hash, Find-in-String, Grease-Pencil conversions | genuinely no target equivalent | flagged for manual handling |

## Next fixers (planned, same verification bar)
- Object / Collection Input → group-input socket (reconstruct)
- Matrix Determinant → component arithmetic (reconstruct)
- Import OBJ/PLY/STL → realize geometry into stored mesh (bake)
