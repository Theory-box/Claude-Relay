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
| **Blackbody** (preferred: keep the node) | two-stage rebuild | the pink-lights bug. `keep_blackbody_run.py` extracts each temperature in the source, then rebuilds each Blackbody as a fresh **native** node in the target with that temperature — so the client still sees a real Blackbody, not an RGB. Verified: light (6000K) + material (4000K) both come back correct on the client's 4.2 reopen. |
| Blackbody (alternative: bake) | bake → RGB / Color node | `fixers.fix_blackbody`, opt-in. Evaluates the constant temperature to its exact colour and replaces the node (tree-aware). Verified colour-identical across temperatures. Use only if replacing the node with a colour is acceptable. |

> Why two-stage for keep-node: the temperature is genuinely gone in the target file
> (the degraded socket stores nothing), and a *link* into that socket crashes the
> target on load — so the value must be re-applied by rebuilding a fresh node in the
> target. `keep_blackbody_run.py` orchestrates both Blender versions in one command:
>
> ```bash
> python3 repair/keep_blackbody_run.py \
>   --source-blender /path/to/4.4/blender --target-blender /path/to/4.2/blender \
>   --in scene.blend --out scene_for_4.2.blend
> ```

## Next fixers (planned, same verification bar)
- Object / Collection Input → group-input socket (reconstruct)
- Matrix Determinant → component arithmetic (reconstruct)
- Import OBJ/PLY/STL → realize geometry into stored mesh (bake)
- Volume Principled temperature (same subtype class; different node — not a pure
  temperature→colour bake, so needs its own approach).
