# UI Restructure — Session Notes
Last updated: 2026-04-09 (Opus 4.6 — full Selected Object panel)

## Branch: `feature/ui-restructure`
## Latest commit: 1f53ba2

## Status: READY FOR BLENDER TEST

---

## Selected Object Panel — Complete Feature Map

The panel now mirrors or exceeds every context-sensitive feature from
all other panels. Select any object → see everything you can do with it.

### ACTOR_ (enemies, NPCs, props, pickups, platforms)
- Entity label + category tag
- NavMesh: link/unlink, triangle count, fallback sphere radius
- Platform settings: sync period/phase/ease/wrap, path info, notice-dist
- Prop info: idle-only notice
- Path warnings: needs_path, needs_pathb
- Crate type display
- Full waypoint list: select/delete each, add at cursor
- Path B support (swamp-bat): separate list + add

### CAMERA_ (game cameras)
- Mode selector: Fixed / Side-Scroll / Orbit (toggle buttons)
- Blend time: +/- 0.5s nudge
- FOV: +/- 5° nudge (shows "default" when 0)
- Standoff: anchor status + add/select
- Orbit: pivot status + add/select
- Look-At target: add/clear/select
- Rotation quaternion + no-rotation warning
- Linked trigger volumes list + add volume

### VOL_ (trigger volumes)
- Linked target display + jump-to
- Unlink button
- Context-aware link: if a linkable target is also selected, shows Link button

### SPAWN_ (player spawn points)
- Camera anchor status + add/select

### CHECKPOINT_ (checkpoint empties)
- Camera anchor status + add/select
- Volume link status + add/unlink

### AMBIENT_ (sound emitters)
- Sound name, mode, radius (read-only display)

### *_CAM (camera anchors)
- Parent object link + jump-to

### NAVMESH_ / og_navmesh meshes
- Reverse actor lookup: which actors reference this mesh + jump-to each
- Triangle count

### ANY MESH (including VOL_, NAVMESH_, and plain geometry)
- Visibility: set_invisible, enable_custom_weights, copy_eye_draws, copy_mod_draws
- Collision: set_collision toggle → material, event, mode, edge/entity/LOS/camera flags
- Light Baking: samples prop + bake button (shows selected mesh count)
- NavMesh Tag: mark/unmark as navmesh geometry

### Universal (all objects)
- Frame in viewport button
- Delete button

---

## Operators Now Surfaced in Selected Object Panel

og.link_navmesh, og.unlink_navmesh, og.mark_navmesh, og.unmark_navmesh,
og.set_cam_prop, og.nudge_cam_float, og.spawn_cam_align, og.spawn_cam_pivot,
og.spawn_cam_look_at, og.spawn_cam_anchor, og.spawn_volume_autolink,
og.link_volume, og.unlink_volume, og.add_waypoint, og.delete_waypoint,
og.bake_lighting, og.select_and_frame, og.delete_object

---

## Dead code to clean up before merge

- `_entity_enum_for_cats()` — replaced by `_build_cat_enum`

---

## Blender Testing Checklist

### Selected Object panel
- [ ] Hidden when nothing selected
- [ ] Select any mesh → shows Visibility, Collision, Light Bake, NavMesh Tag
- [ ] Select ACTOR_babak → NavMesh section + waypoints + warnings
- [ ] Select ACTOR_plat → full platform settings (sync, period, phase)
- [ ] Select ACTOR_swamp-bat → Path A and Path B sections
- [ ] Select CAMERA_ → mode buttons, blend, FOV, anchor/pivot, look-at, volumes
- [ ] Select VOL_ → link display, unlink, context-aware link
- [ ] Select SPAWN_ → camera status + add
- [ ] Select CHECKPOINT_ → camera + volume status
- [ ] Select AMBIENT_ → sound info
- [ ] Select *_CAM → parent link
- [ ] Select NAVMESH_ mesh → actor reverse lookup + triangle count
- [ ] Collision toggle: expanding shows material/event/mode/flags
- [ ] Light bake: samples + bake button works
- [ ] Mark/Unmark navmesh works
- [ ] Frame and Delete buttons work everywhere

### Existing panels (regression check)
- [ ] All spawn sub-panels still work for placing
- [ ] Camera panel list view still works
- [ ] Triggers panel list view still works
- [ ] Waypoints panel still appears (though now redundant with Selected Object)
- [ ] Export produces correct output
