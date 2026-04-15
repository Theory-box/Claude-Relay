# Blender Scene Audit Addon — Session Notes

## Branch
`blender-audit-offtopic`

## File
`addons/quick_commands_addon_v8.py`

## Status
Implementation complete. **Not yet tested in Blender.** Test next session.

## What Was Built
A Scene Audit panel added to the existing Quick Commands addon (Blender 4.4).
Located in: View3D > Sidebar > Quick Cmds > Scene Audit

### Audit Checks (all toggleable)
| Check | Scope | Notes |
|---|---|---|
| Missing Materials | MESH | no slots, or any slot with material=None |
| Objects with Modifiers | All | any object with len(modifiers) > 0 |
| Lights | LIGHT | lists all lights in scene |
| Unapplied Scale | MESH | any axis != 1.0 (tol 1e-5), shows scale as suffix |
| No UV Maps | MESH | len(uv_layers) == 0 |
| High Poly | MESH | face count > threshold (default 5000, configurable inline) |

### Key Classes
- `SceneAuditResult` — PropertyGroup with `object_name` + `extra_info` (for scale/face count suffix)
- `SceneAuditProps` — all options, results collections, UI state bools; registered as `scene.scene_audit`
- `SCENEAUDIT_OT_run_audit` — scans scene, populates result lists
- `SCENEAUDIT_OT_select_object` — deselects all (via view_layer iteration), selects target object
- `SCENEAUDIT_PT_panel` — collapsible options + Run Audit button + per-category result sections

### Things to Verify When Testing
- All 6 checks fire correctly
- Clicking result buttons selects the right object
- High poly threshold field enables/disables correctly with the toggle
- Scale suffix displays properly (e.g. `MyObj  (2.000, 1.000, 1.000)`)
- Face count suffix displays properly (e.g. `MyObj  12,345 faces`)
- Re-running audit clears stale results

## Suggested Next Additions (if expanding later)
- Unapplied Rotation
- Render Hidden objects (`hide_render=True`)
- Ngon detection (faces with >4 verts)
- Objects outside any collection
