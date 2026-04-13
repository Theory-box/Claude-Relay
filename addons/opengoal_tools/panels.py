# ---------------------------------------------------------------------------
# panels.py — OpenGOAL Level Tools
# All OG_PT_* panel classes and their draw helper functions.
# ---------------------------------------------------------------------------

import bpy
from bpy.types import Panel, Operator
from pathlib import Path
from .data import (
    ENTITY_DEFS, ENTITY_WIKI, ENTITY_ENUM_ITEMS, ENEMY_ENUM_ITEMS, VERTEX_EXPORT_TYPES,
    PROP_ENUM_ITEMS, NPC_ENUM_ITEMS, PICKUP_ENUM_ITEMS, PLATFORM_ENUM_ITEMS,
    CRATE_ITEMS, CRATE_PICKUP_ITEMS, ALL_SFX_ITEMS, SBK_SOUNDS, LEVEL_BANKS,
    LUMP_REFERENCE, ACTOR_LINK_DEFS, LUMP_TYPE_ITEMS,
    NAV_UNSAFE_TYPES, NEEDS_PATH_TYPES, IS_PROP_TYPES, ETYPE_AG,
    _lump_ref_for_etype, _actor_link_slots, _actor_has_links,
    _actor_links, _actor_get_link, AGGRO_TRIGGER_EVENTS,
    _parse_lump_row, _LUMP_HARDCODED_KEYS,
    GLOBAL_TPAGE_GROUPS,
)
from .collections import (
    _get_level_prop, _set_level_prop, _level_objects, _active_level_col,
    _all_level_collections, _classify_object, _col_path_for_entity,
    _recursive_col_objects, _ensure_sub_collection, _link_object_to_sub_collection,
    _COL_PATH_NAVMESHES, _COL_PATH_WAYPOINTS, _COL_PATH_EXPORT_AS,
    _COL_PATH_TRIGGERS, _COL_PATH_CAMERAS, _COL_PATH_SOUND_EMITTERS,
    _COL_PATH_SPAWNABLE_ENEMIES, _COL_PATH_GEO_SOLID,
)
from .export import (
    _nick, _iso, _lname, _ldir, _goal_src, _level_info, _game_gp,
    _levels_dir, _entity_gc,
    _actor_uses_waypoints, _actor_uses_navmesh,
    _actor_is_platform, _actor_is_launcher, _actor_is_spawner,
    _actor_is_enemy, _actor_supports_aggro_trigger,
    _vol_links, _vols_linking_to, _classify_target,
    _vol_get_link_to, _vol_has_link_to,
    collect_cameras, collect_aggro_triggers, log,
)
from .build import (
    _EXE, _BUILD_STATE, _PLAY_STATE, goalc_ok, kill_gk,
    _exe_root, _data_root, _data, _goalc, _gk, _user_dir,
)
from .properties import OGLumpRow, OG_UL_LumpRows
from .utils import (
    _is_linkable, _is_aggro_target, _vol_for_target,
    _ENEMY_CATS, _NPC_CATS, _PICKUP_CATS, _PROP_CATS,
    _draw_platform_settings, _header_sep, _draw_entity_sub,
    _draw_wiki_preview,
    _preview_collections, _load_previews, _unload_previews,
)
from . import model_preview as _mp

class OG_PT_Level(Panel):
    bl_label       = "⚙  Level"
    bl_idname      = "OG_PT_level"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        scene  = ctx.scene

        levels = _all_level_collections(scene)
        level_col = _active_level_col(scene)

        # ── No levels exist → show Add Level button only ─────────────────
        if not levels:
            layout.label(text="No levels in this file", icon="INFO")
            row = layout.row(align=True)
            row.operator("og.create_level", text="Add Level", icon="ADD")
            row.operator("og.assign_collection_as_level", text="Assign Existing", icon="OUTLINER_COLLECTION")
            return

        # ── Level selector dropdown + edit button ────────────────────────
        row = layout.row(align=True)
        row.prop(props, "active_level", text="")
        row.operator("og.edit_level", text="", icon="GREASEPENCIL")

        if level_col is None:
            return

        # ── Level info (compact) ──────────────────────────────────────────
        name = str(level_col.get("og_level_name", ""))
        base_id = int(level_col.get("og_base_id", 10000))
        if name:
            name_clean = name.lower().replace(" ", "-")
            if len(name_clean) > 10:
                warn = layout.row()
                warn.alert = True
                warn.label(text=f"Name too long ({len(name_clean)} chars, max 10)!", icon="ERROR")
            else:
                row = layout.row()
                row.enabled = False
                row.label(text=f"ID: {base_id}   ISO: {_iso(name)}   Nick: {_nick(name)}")

        layout.separator(factor=0.4)

        # Vis nick override
        vnick = str(level_col.get("og_vis_nick_override", ""))
        row_vn = layout.row(align=True)
        row_vn.enabled = False
        row_vn.label(text=f"Vis Nick Override: {vnick if vnick else '(auto)'}")


# ---------------------------------------------------------------------------
# Spawn > Level Flow  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_SpawnLevelFlow(Panel):
    bl_label       = "🗺  Level Flow"
    bl_idname      = "OG_PT_spawn_level_flow"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        scene  = ctx.scene

        # ── Dropdown + Add button ─────────────────────────────────────────
        row = layout.row(align=True)
        row.prop(props, "spawn_flow_type", text="")
        if props.spawn_flow_type == "SPAWN":
            row.operator("og.spawn_player",     text="Add", icon="ADD")
        else:
            row.operator("og.spawn_checkpoint", text="Add", icon="ADD")

        # ── Object lists ──────────────────────────────────────────────────
        lv_objs     = _level_objects(scene)
        spawns      = [o for o in lv_objs if o.name.startswith("SPAWN_")
                       and o.type == "EMPTY" and not o.name.endswith("_CAM")]
        checkpoints = [o for o in lv_objs if o.name.startswith("CHECKPOINT_")
                       and o.type == "EMPTY" and not o.name.endswith("_CAM")]

        if spawns or checkpoints:
            layout.separator(factor=0.4)

        if spawns:
            row = layout.row()
            icon = "TRIA_DOWN" if props.show_spawn_list else "TRIA_RIGHT"
            row.prop(props, "show_spawn_list",
                     text=f"Player Spawns ({len(spawns)})", icon=icon, emboss=False)
            if props.show_spawn_list:
                box = layout.box()
                for o in sorted(spawns, key=lambda x: x.name):
                    row = box.row(align=True)
                    row.label(text=o.name, icon="EMPTY_ARROWS")
                    cam_obj = scene.objects.get(o.name + "_CAM")
                    if cam_obj:
                        row.label(text="📷", icon="NONE")
                    else:
                        sub = row.row()
                        sub.alert = True
                        sub.label(text="no cam", icon="NONE")
                    op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                    op.obj_name = o.name
                    op = row.operator("og.delete_object", text="", icon="TRASH")
                    op.obj_name = o.name

        if checkpoints:
            row = layout.row()
            icon = "TRIA_DOWN" if props.show_checkpoint_list else "TRIA_RIGHT"
            row.prop(props, "show_checkpoint_list",
                     text=f"Checkpoints ({len(checkpoints)})", icon=icon, emboss=False)
            if props.show_checkpoint_list:
                box = layout.box()
                for o in sorted(checkpoints, key=lambda x: x.name):
                    row = box.row(align=True)
                    row.label(text=o.name, icon="EMPTY_SINGLE_ARROW")
                    vol_list = _vols_linking_to(scene, o.name)
                    if vol_list:
                        row.label(text=f"📦 {vol_list[0].name}")
                    else:
                        r = float(o.get("og_checkpoint_radius", 3.0))
                        sub = row.row()
                        sub.alert = True
                        sub.label(text=f"r={r:.1f}m")
                    cam_obj = scene.objects.get(o.name + "_CAM")
                    if cam_obj:
                        row.label(text="📷", icon="NONE")
                    op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                    op.obj_name = o.name
                    op = row.operator("og.delete_object", text="", icon="TRASH")
                    op.obj_name = o.name

        # ── Selected spawn/checkpoint context actions ─────────────────────
        sel = ctx.active_object
        if (sel and sel.type == "EMPTY"
                and (sel.name.startswith("SPAWN_") or sel.name.startswith("CHECKPOINT_"))
                and not sel.name.endswith("_CAM")):
            is_cp = sel.name.startswith("CHECKPOINT_")
            layout.separator(factor=0.3)
            sub = layout.column(align=True)
            cam_exists = bool(scene.objects.get(sel.name + "_CAM"))
            if not cam_exists:
                sub.operator("og.spawn_cam_anchor",
                             text=f"Add Camera for {sel.name}", icon="CAMERA_DATA")
            else:
                row = sub.row()
                row.enabled = False
                row.label(text=f"{sel.name}_CAM exists ✓", icon="CHECKMARK")
            if is_cp:
                vol_list_sel = _vols_linking_to(scene, sel.name)
                if vol_list_sel:
                    vol_linked = vol_list_sel[0]
                    row = sub.row()
                    row.enabled = False
                    row.label(text=f"{vol_linked.name} linked ✓", icon="MESH_CUBE")
                    sub.operator("og.unlink_volume", text="Unlink Volume", icon="X")
                else:
                    op = sub.operator("og.spawn_volume_autolink",
                                      text="Add Trigger Volume", icon="MESH_CUBE")
                    op.target_name = sel.name
                    sub.label(text="Or use Triggers panel to link existing", icon="INFO")


# ---------------------------------------------------------------------------
# Level > Level Manager  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_LevelManagerSub(Panel):
    bl_label       = "🗂  Level Manager"
    bl_idname      = "OG_PT_level_manager"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_level"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        scene  = ctx.scene
        levels = _all_level_collections(scene)
        active = _active_level_col(scene)

        if not levels:
            layout.label(text="No levels in this file")

        for col in levels:
            lname     = col.get("og_level_name", col.name)
            is_active = (active is not None and col.name == active.name)

            row = layout.row(align=True)
            # Checkbox appearance via toggle operator — depress=is_active gives filled look
            op = row.operator("og.set_active_level",
                              text=lname,
                              icon="CHECKBOX_HLT" if is_active else "CHECKBOX_DEHLT",
                              depress=is_active)
            op.col_name = col.name

        layout.separator(factor=0.4)
        row = layout.row(align=True)
        row.operator("og.create_level",               text="Add Level",       icon="ADD")
        row.operator("og.assign_collection_as_level", text="Assign Existing", icon="OUTLINER_COLLECTION")


# ---------------------------------------------------------------------------
# OPERATOR — Sort Level Objects
# ---------------------------------------------------------------------------

class OG_OT_SortLevelObjects(Operator):
    """Sort all loose objects in the active level into the correct sub-collections.

    'Loose' means either:
      - Directly in the level collection (no sub-collection), OR
      - In a sub-collection but the wrong one (e.g. a mesh in Spawnables)

    Classification rules:
      MESH, not VOL_          → Geometry / Solid
      VOL_                    → Triggers
      ACTOR_ empty            → Spawnables / (category)
      SPAWN_ / CHECKPOINT_    → Spawns
      *_wp_* / *_wpb_*        → Waypoints
      AMBIENT_                → Sound Emitters
      CAMERA_ (camera)        → Cameras
    Objects that can't be classified are left in place with a warning.
    """
    bl_idname   = "og.sort_level_objects"
    bl_label    = "Sort Collection Objects"
    bl_options  = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        scene     = ctx.scene
        level_col = _active_level_col(scene)
        if level_col is None:
            self.report({"ERROR"}, "No active level collection")
            return {"CANCELLED"}

        # Gather every object in the level (all sub-collections included)
        all_objs = _recursive_col_objects(level_col, exclude_no_export=False)

        moved   = []
        skipped = []

        for obj in all_objs:
            target_path = _classify_object(obj)
            if target_path is None:
                skipped.append(obj.name)
                continue

            # Find where the object currently lives within the level
            target_col = _ensure_sub_collection(level_col, *target_path)

            # Already in the right collection — skip
            if obj.name in target_col.objects:
                continue

            # Link into target
            target_col.objects.link(obj)

            # Unlink from scene root if present
            if obj.name in scene.collection.objects:
                scene.collection.objects.unlink(obj)

            # Unlink from every other collection except the target
            for col in bpy.data.collections:
                if col == target_col:
                    continue
                if obj.name in col.objects:
                    col.objects.unlink(obj)

            moved.append(f"{obj.name} → {'/'.join(target_path)}")
            log(f"[sort] {obj.name} → {target_path}")

        if moved:
            self.report({"INFO"}, f"Sorted {len(moved)} object(s)")
            for m in moved:
                log(f"  [sort] {m}")
        else:
            self.report({"INFO"}, "Everything already sorted")

        if skipped:
            self.report({"WARNING"}, f"Could not classify {len(skipped)} object(s): {', '.join(skipped[:5])}")

        return {"FINISHED"}


class OG_PT_CollectionProperties(Panel):
    bl_label       = "📂  Collections"
    bl_idname      = "OG_PT_collection_props"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_level"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        return _active_level_col(ctx.scene) is not None

    def draw(self, ctx):
        pass  # sub-panels draw the content


class OG_PT_DisableExport(Panel):
    bl_label       = "Disable Export"
    bl_idname      = "OG_PT_disable_export"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_collection_props"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        return _active_level_col(ctx.scene) is not None

    def draw(self, ctx):
        layout = self.layout
        level_col = _active_level_col(ctx.scene)
        if level_col is None:
            return

        children = sorted(level_col.children, key=lambda c: c.name)

        if not children:
            layout.label(text="No sub-collections")
        else:
            for col in children:
                layout.prop(col, "og_no_export", text=col.name)


class OG_PT_CleanSub(Panel):
    bl_label       = "🧹  Clean"
    bl_idname      = "OG_PT_clean_sub"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_collection_props"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        return _active_level_col(ctx.scene) is not None

    def draw(self, ctx):
        layout = self.layout
        layout.operator("og.sort_level_objects",
                        text="Sort Collection Objects",
                        icon="SORTSIZE")


# ---------------------------------------------------------------------------
# Level > Light Baking  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_LightBakingSub(Panel):
    bl_label       = "💡  Light Baking"
    bl_idname      = "OG_PT_lightbaking"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_level"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        col = layout.column(align=True)
        col.label(text="Cycles Bake Settings:", icon="LIGHT")
        col.prop(props, "lightbake_samples")

        layout.separator(factor=0.5)

        targets = [o for o in ctx.selected_objects if o.type == "MESH"]
        if targets:
            box = layout.box()
            box.label(text=f"{len(targets)} mesh(es) selected:", icon="OBJECT_DATA")
            for o in targets[:6]:
                box.label(text=f"  • {o.name}")
            if len(targets) > 6:
                box.label(text=f"  … and {len(targets) - 6} more")
        else:
            layout.label(text="Select mesh object(s) to bake", icon="INFO")

        layout.separator(factor=0.5)
        row = layout.row()
        row.enabled = len(targets) > 0
        row.scale_y = 1.6
        row.operator("og.bake_lighting", text="Bake Lighting → Vertex Color", icon="RENDER_STILL")
        layout.separator(factor=0.3)
        layout.label(text="Result stored in 'BakedLight' layer", icon="GROUP_VCOL")


# ---------------------------------------------------------------------------
# Level > Music  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_Music(Panel):
    bl_label       = "🎵  Music"
    bl_idname      = "OG_PT_music"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_level"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        box = layout.box()
        box.label(text="Level Music", icon="PLAY")
        box.prop(props, "music_bank", text="Music Bank")

        box2 = layout.box()
        box2.label(text="Sound Banks  (max 2)", icon="SPEAKER")
        b1 = props.sound_bank_1
        b2 = props.sound_bank_2
        col2 = box2.column(align=True)
        col2.prop(props, "sound_bank_1", text="Bank 1")
        col2.prop(props, "sound_bank_2", text="Bank 2")
        if b1 != "none" and b1 == b2:
            box2.label(text="⚠ Bank 1 and Bank 2 are the same", icon="ERROR")
        n_common = len(SBK_SOUNDS.get("common", []))
        n_level  = len(set(SBK_SOUNDS.get(b1, [])) | set(SBK_SOUNDS.get(b2, [])))
        box2.label(text=f"{n_common} common  +  {n_level} level  =  {n_common + n_level} available", icon="INFO")


# ===========================================================================
# SPAWN PANEL (parent)
# ===========================================================================

class OG_PT_Spawn(Panel):
    bl_label       = "➕  Spawn Objects"
    bl_idname      = "OG_PT_spawn"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        props = ctx.scene.og_props
        if props.tpage_limit_enabled:
            active = [g for g in (props.tpage_filter_1, props.tpage_filter_2) if g != "NONE"]
            if active:
                row = self.layout.row()
                row.label(text="🔍 Filtered: " + " + ".join(active), icon="FILTER")


# ---------------------------------------------------------------------------
# Tpage Limit Search — filter helper (used by all spawn sub-panels)
# ---------------------------------------------------------------------------

def _entity_passes_filter(etype, props):
    """Return True if this entity should be visible given the current tpage filter.

    Always-visible cases:
      • Filter disabled
      • Entity has no tpage_group field (no heap cost — pickups, most platforms, etc.)
      • Entity's group is in GLOBAL_TPAGE_GROUPS (Village1/2/3, Training — always resident)
      • Both filter dropdowns are NONE (filter on but nothing selected → no restriction)
    """
    if not props.tpage_limit_enabled:
        return True
    info  = ENTITY_DEFS.get(etype, {})
    grp   = info.get("tpage_group")   # None = no tpage concern
    if grp is None:
        return True
    if grp in GLOBAL_TPAGE_GROUPS:
        return True
    g1 = props.tpage_filter_1
    g2 = props.tpage_filter_2
    allowed = {g for g in (g1, g2) if g != "NONE"}
    if not allowed:
        return True                   # filter on, nothing selected → show all
    return grp in allowed


# ---------------------------------------------------------------------------
# Operator — select a search result (sets entity_search_selected)
# ---------------------------------------------------------------------------

class OG_OT_SearchSelectEntity(bpy.types.Operator):
    bl_idname      = "og.search_select_entity"
    bl_label       = "Select Entity"
    bl_description = "Select this entity as the spawn target"
    bl_options     = {"INTERNAL", "UNDO"}

    etype: bpy.props.StringProperty()

    def execute(self, ctx):
        ctx.scene.og_props.entity_search_selected = self.etype
        try:
            ctx.scene.og_props.entity_type = self.etype
        except Exception:
            pass
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Spawn > Quick Search  (sub-panel — always open, pinned to top)
# ---------------------------------------------------------------------------

class OG_PT_SpawnSearch(Panel):
    bl_label       = "Quick Search"
    bl_idname      = "OG_PT_spawn_search"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_order       = 0

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        # Search input
        row = layout.row(align=True)
        row.prop(props, "entity_search", icon="VIEWZOOM", text="")

        query = props.entity_search.strip().lower()

        if query:
            # Scrollable dropdown — Blender renders this as a floating popup list
            layout.prop(props, "entity_search_results", text="", icon="COLLAPSEMENU")

            # Spawn button — active when a real result is selected
            sel = props.entity_search_selected
            if sel and sel in ENTITY_DEFS:
                col = layout.column()
                col.scale_y = 1.4
                op = col.operator("og.spawn_entity",
                                  text=f"Spawn  {ENTITY_DEFS[sel]['label']}", icon="ADD")
                op.source_prop = "entity_search_selected"
            else:
                sub = layout.column()
                sub.enabled = False
                sub.operator("og.spawn_entity", text="Spawn", icon="ADD")
        else:
            layout.label(text="Type to search all spawnable objects…", icon="INFO")



# ---------------------------------------------------------------------------
# Spawn > Quick Search > Limit Search  (sub-panel — child of Quick Search)
# ---------------------------------------------------------------------------

class OG_PT_SpawnLimitSearch(Panel):
    bl_label       = "Limit Search"
    bl_idname      = "OG_PT_spawn_limit_search"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn_search"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw_header(self, ctx):
        props = ctx.scene.og_props
        self.layout.prop(props, "tpage_limit_enabled", text="")

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        col = layout.column(align=True)
        col.enabled = props.tpage_limit_enabled

        # Two dropdowns side by side
        row = col.row(align=True)
        # Grey out slot 2 if slot 1 is NONE (nothing to pair with yet)
        row.prop(props, "tpage_filter_1", text="")
        sub = row.row(align=True)
        sub.enabled = props.tpage_filter_1 != "NONE"
        sub.prop(props, "tpage_filter_2", text="")

        # Warn if same group selected in both slots
        if (props.tpage_filter_1 != "NONE"
                and props.tpage_filter_1 == props.tpage_filter_2):
            col.label(text="Both slots are the same group", icon="ERROR")


# ---------------------------------------------------------------------------
# Spawn > Enemies  (sub-panel, with inline navmesh)
# ---------------------------------------------------------------------------

class OG_PT_SpawnEnemies(Panel):
    bl_label       = "⚔  Enemies"
    bl_idname      = "OG_PT_spawn_enemies"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        # ---- Preview status (toggle is in addon preferences) ----
        _prefs = bpy.context.preferences.addons.get("opengoal_tools")
        preview_on = _prefs and _prefs.preferences.preview_models
        if preview_on:
            row = layout.row(align=True)
            row.label(text="Preview Models", icon="OUTLINER_OB_MESH")
            row.operator("og.clear_previews", text="", icon="TRASH")
            if not _mp.models_available():
                box = layout.box()
                box.label(text="No GLBs found", icon="ERROR")
                box.label(text="1. Set rip_levels: true in jak1_config.jsonc")
                box.label(text="2. Delete data/decompiler_out/jak1/")
                box.label(text="3. Re-run the extractor from scratch")
                probe = _mp.models_probe_path()
                display = ("..." + probe[-47:]) if len(probe) > 50 else probe
                box.label(text=f"Checking: {display}")

        layout.separator(factor=0.3)
        _draw_entity_sub(layout, ctx, _ENEMY_CATS, nav_inline=True, prop_name="enemy_type")


# ---------------------------------------------------------------------------
# Spawn > Platforms  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_SpawnPlatforms(Panel):
    bl_label       = "🟦  Platforms"
    bl_idname      = "OG_PT_spawn_platforms"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        scene  = ctx.scene

        # Spawn
        layout.label(text="Spawn", icon="ADD")
        layout.prop(props, "platform_type", text="")
        layout.operator("og.spawn_platform", text="Add Platform at Cursor", icon="ADD")
        layout.separator(factor=0.5)

        # Active platform settings
        sel = ctx.active_object
        is_platform_selected = (
            sel is not None
            and sel.name.startswith("ACTOR_")
            and "_wp_" not in sel.name
            and len(sel.name.split("_", 2)) >= 3
            and _actor_is_platform(sel.name.split("_", 2)[1])
        )
        if is_platform_selected:
            layout.label(text="Selected Platform Settings", icon="SETTINGS")
            _draw_platform_settings(layout, sel, scene)
            layout.separator(factor=0.5)

        # Scene platform list
        plats = sorted(
            [o for o in _level_objects(scene)
             if o.name.startswith("ACTOR_")
             and "_wp_" not in o.name
             and o.type == "EMPTY"
             and len(o.name.split("_", 2)) >= 3
             and _actor_is_platform(o.name.split("_", 2)[1])],
            key=lambda o: o.name
        )

        if not plats:
            box = layout.box()
            box.label(text="No platforms in scene", icon="INFO")
            return

        row = layout.row()
        icon = "TRIA_DOWN" if props.show_platform_list else "TRIA_RIGHT"
        row.prop(props, "show_platform_list",
                 text=f"Platforms ({len(plats)})", icon=icon, emboss=False)
        if not props.show_platform_list:
            return

        box = layout.box()
        for p in plats:
            etype = p.name.split("_", 2)[1]
            einfo = ENTITY_DEFS.get(etype, {})
            label = einfo.get("label", etype)
            is_active = (sel is not None and sel == p)
            row = box.row(align=True)
            if is_active:
                row.label(text=f"▶ {label}", icon="CUBE")
            else:
                row.label(text=label, icon="CUBE")
            row.label(text=p.name.split("_", 2)[2])
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = p.name
            op = row.operator("og.delete_object", text="", icon="TRASH")
            op.obj_name = p.name


# ---------------------------------------------------------------------------
# Spawn > Props & Objects  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_SpawnProps(Panel):
    bl_label       = "📦  Props & Objects"
    bl_idname      = "OG_PT_spawn_props"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        _draw_entity_sub(self.layout, ctx, _PROP_CATS, prop_name="prop_type")


# ---------------------------------------------------------------------------
# Spawn > NPCs  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_SpawnNPCs(Panel):
    bl_label       = "🧍  NPCs"
    bl_idname      = "OG_PT_spawn_npcs"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        _draw_entity_sub(self.layout, ctx, _NPC_CATS, prop_name="npc_type")


# ---------------------------------------------------------------------------
# Spawn > Pickups  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_SpawnPickups(Panel):
    bl_label       = "⭐  Pickups"
    bl_idname      = "OG_PT_spawn_pickups"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        _draw_entity_sub(self.layout, ctx, _PICKUP_CATS, prop_name="pickup_type")


# ---------------------------------------------------------------------------
# Spawn > Sound Emitters  (sub-panel)
# ---------------------------------------------------------------------------

class OG_PT_SpawnSounds(Panel):
    bl_label       = "🔊  Sound Emitters"
    bl_idname      = "OG_PT_spawn_sounds"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        col = layout.column(align=True)
        col.prop(props, "ambient_default_radius", text="Default Radius (m)")
        col.separator(factor=0.4)

        snd_display = props.sfx_sound.split("__")[0] if "__" in props.sfx_sound else props.sfx_sound
        pick_row = col.row(align=True)
        pick_row.scale_y = 1.2
        pick_row.operator("og.pick_sound", text=f"🔊  {snd_display}", icon="VIEWZOOM")

        col.separator(factor=0.4)
        row2 = col.row()
        row2.scale_y = 1.4
        row2.operator("og.add_sound_emitter", text="Add Emitter at Cursor", icon="ADD")

        emitters = [o for o in _level_objects(ctx.scene)
                    if o.name.startswith("AMBIENT_") and o.type == "EMPTY"
                    and o.get("og_sound_name")]
        if emitters:
            layout.separator(factor=0.3)
            sub = layout.box()
            sub.label(text=f"{len(emitters)} emitter(s) in scene:", icon="OUTLINER_OB_EMPTY")
            for o in emitters[:8]:
                row = sub.row(align=True)
                snd  = o.get("og_sound_name", "?")
                mode = o.get("og_sound_mode", "loop")
                icon = "PREVIEW_RANGE" if mode == "loop" else "PLAYER"
                row.label(text=f"{o.name}  →  {snd}  [{mode}]", icon=icon)
            if len(emitters) > 8:
                sub.label(text=f"… and {len(emitters) - 8} more")
        else:
            layout.label(text="No emitters placed yet", icon="INFO")


class OG_PT_SpawnWater(Panel):
    bl_label       = "💧  Water Volumes"
    bl_idname      = "OG_PT_spawn_water"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        col = layout.column(align=True)

        row = col.row()
        row.scale_y = 1.4
        row.operator("og.add_water_volume", text="Add Water Volume", icon="MOD_OCEAN")

        col.separator(factor=0.4)
        sub = col.row(); sub.enabled = False
        sub.label(text="Scale to cover water area (no rotation)", icon="INFO")

        # List existing water volumes
        water_meshes = [o for o in _level_objects(ctx.scene)
                        if o.type == "MESH" and o.name.startswith("WATER_")]
        if water_meshes:
            from mathutils import Vector
            layout.separator(factor=0.3)
            box = layout.box()
            box.label(text=f"{len(water_meshes)} volume(s):", icon="MESH_CUBE")
            for o in water_meshes:
                row = box.row(align=True)
                surface = float(o.get("og_water_surface", 0.0))
                bb = [o.matrix_world @ Vector(o.bound_box[i]) for i in range(8)]
                w = max(c.x for c in bb) - min(c.x for c in bb)
                d = max(c.y for c in bb) - min(c.y for c in bb)
                row.label(text=f"{o.name}  {w:.1f}×{d:.1f}m  surf={surface:.1f}m", icon="MOD_OCEAN")


# ===========================================================================
# SELECTED OBJECT  (standalone, poll-gated)
# ===========================================================================
# Shows context-sensitive settings for whatever OG-managed object is selected.
# Covers: actors (enemies, platforms, props, NPCs, pickups), sound emitters,
# spawns, checkpoints, trigger volumes, camera anchors, navmesh meshes.

def _og_managed_object(obj):
    """Return True if obj is any OpenGOAL-managed object or any mesh (for collision/bake)."""
    if obj is None:
        return False
    n = obj.name
    if any(n.startswith(p) for p in ("ACTOR_", "SPAWN_", "CHECKPOINT_",
                                      "AMBIENT_", "VOL_", "CAMERA_",
                                      "NAVMESH_")):
        return True
    if n.endswith("_CAM"):
        return True
    # Any mesh object gets collision/lightbake controls
    if obj.type == "MESH":
        return True
    return False


def _draw_selected_actor(layout, sel, scene):
    """Draw settings for a selected ACTOR_ object."""
    parts = sel.name.split("_", 2)
    if len(parts) < 3:
        layout.label(text=sel.name, icon="OBJECT_DATA")
        return
    etype = parts[1]
    einfo = ENTITY_DEFS.get(etype, {})
    label = einfo.get("label", etype)
    cat   = einfo.get("cat", "")

    # Header
    row = layout.row()
    row.label(text=label, icon="OBJECT_DATA")
    sub = row.row()
    sub.enabled = False
    sub.label(text=f"[{cat}]")

    # ── Enemy: Activation distance (idle-distance lump) ──────────────────
    # Per-instance override of the engine's 80m default. Below this distance
    # the enemy wakes up and starts noticing the player. Lower = stays asleep
    # longer. Reads og_idle_distance, emitted as 'idle-distance lump at build.
    if _actor_is_enemy(etype):
        box = layout.box()
        box.label(text="Activation", icon="RADIOBUT_ON")
        idle_d = float(sel.get("og_idle_distance", 80.0))
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-5m", icon="REMOVE")
        op.prop_name = "og_idle_distance"; op.delta = -5.0; op.val_min = 0.0
        row.label(text=f"Idle Distance: {idle_d:.0f}m")
        op = row.operator("og.nudge_float_prop", text="+5m", icon="ADD")
        op.prop_name = "og_idle_distance"; op.delta = 5.0; op.val_max = 500.0
        sub = box.row()
        sub.enabled = False
        sub.label(text="Player must be closer than this to wake the enemy", icon="INFO")

    # ── Nav-enemy: Trigger Behaviour (aggro / patrol / wait-for-cue) ─────
    # Lists every volume that links to this enemy. Each link has its own
    # behaviour dropdown. Only nav-enemies (those that respond to 'cue-chase)
    # get this UI; process-drawable enemies don't have the engine handler.
    if _actor_supports_aggro_trigger(etype):
        box = layout.box()
        box.label(text="Trigger Behaviour", icon="FORCE_FORCE")
        linked_vols = _vols_linking_to(scene, sel.name)
        if linked_vols:
            for v in linked_vols:
                # Find the link entry pointing to this enemy
                entry = _vol_get_link_to(v, sel.name)
                if not entry:
                    continue
                row = box.row(align=True)
                row.label(text=f"✓ {v.name}", icon="MESH_CUBE")
                row.prop(entry, "behaviour", text="")
                op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                op.obj_name = v.name
                op = row.operator("og.remove_vol_link", text="", icon="X")
                op.vol_name    = v.name
                op.target_name = sel.name
        else:
            sub = box.row()
            sub.enabled = False
            sub.label(text="No trigger volumes linked", icon="INFO")
        op = box.operator("og.spawn_aggro_trigger", text="Add Aggro Trigger", icon="ADD")
        op.target_name = sel.name

    # ── Nav-enemy: navmesh management ────────────────────────────────────
    if _actor_uses_navmesh(etype):
        box = layout.box()
        box.label(text="NavMesh", icon="MOD_MESHDEFORM")

        nm_name = sel.get("og_navmesh_link", "")
        nm_obj  = bpy.data.objects.get(nm_name) if nm_name else None

        if nm_obj:
            row = box.row(align=True)
            row.label(text=f"✓ {nm_obj.name}", icon="CHECKMARK")
            row.operator("og.unlink_navmesh", text="", icon="X")
            try:
                nm_obj.data.calc_loop_triangles()
                tc = len(nm_obj.data.loop_triangles)
                box.label(text=f"{tc} triangles", icon="MESH_DATA")
            except Exception:
                pass
        else:
            box.label(text="No mesh linked", icon="ERROR")
            # Only show Link button when a mesh is also selected
            sel_meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
            if sel_meshes:
                box.label(text=f"Will link to: {sel_meshes[0].name}", icon="INFO")
                box.operator("og.link_navmesh", text="Link NavMesh", icon="LINKED")
            else:
                box.label(text="Shift-select a mesh to link", icon="INFO")

        nav_r = float(sel.get("og_nav_radius", 6.0))
        box.label(text=f"Fallback sphere radius: {nav_r:.1f}m", icon="SPHERE")

    # ── Platform: sync, path, notice-dist ────────────────────────────────
    elif _actor_is_platform(etype):
        _draw_platform_settings(layout, sel, scene)

    # ── Prop ─────────────────────────────────────────────────────────────
    elif einfo.get("is_prop"):
        box = layout.box()
        box.label(text="Prop — idle animation only", icon="INFO")
        box.label(text="No AI or combat")

    # ── Path requirements ────────────────────────────────────────────────
    else:
        if einfo.get("needs_pathb"):
            box = layout.box()
            box.label(text="Needs 2 path sets", icon="INFO")
            box.label(text="Waypoints: _wp_00... and _wpb_00...")
        elif einfo.get("needs_path"):
            box = layout.box()
            box.label(text="Needs waypoints to patrol", icon="INFO")

    # ── Crate type ───────────────────────────────────────────────────────
    if etype == "crate":
        ct     = sel.get("og_crate_type",          "steel")
        pickup = sel.get("og_crate_pickup",         "money")
        amount = int(sel.get("og_crate_pickup_amount", 1))
        box = layout.box()
        # Build readable summary
        _PICKUP_LABELS = {uid: lbl for (uid, lbl, _, _, _) in CRATE_PICKUP_ITEMS}
        pickup_label = _PICKUP_LABELS.get(pickup, pickup)
        if pickup == "none":
            summary = f"{ct.capitalize()}  —  Empty"
        elif pickup == "buzzer":
            summary = f"{ct.capitalize()}  —  Scout Fly"
        else:
            summary = f"{ct.capitalize()}  —  {pickup_label} ×{amount}"
        box.label(text=summary, icon="PACKAGE")

    # ── Waypoints (full list + add/delete) ───────────────────────────────
    if _actor_uses_waypoints(etype):
        layout.separator(factor=0.3)
        prefix = sel.name + "_wp_"
        wps = sorted(
            [o for o in _level_objects(scene) if o.name.startswith(prefix) and o.type == "EMPTY"],
            key=lambda o: o.name
        )
        box = layout.box()
        box.label(text=f"Path  ({len(wps)} point{'s' if len(wps) != 1 else ''})", icon="ANIM")
        if wps:
            col = box.column(align=True)
            for wp in wps:
                row = col.row(align=True)
                row.label(text=wp.name, icon="EMPTY_AXIS")
                op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                op.obj_name = wp.name
                op = row.operator("og.delete_waypoint", text="", icon="X")
                op.wp_name = wp.name

        op = box.operator("og.add_waypoint", text="Add Waypoint at Cursor", icon="PLUS")
        op.enemy_name = sel.name
        op.pathb_mode = False

        if einfo.get("needs_path") and len(wps) < 1:
            box.label(text="⚠ Needs ≥ 1 waypoint or will crash", icon="ERROR")

        # Path B (swamp-bat)
        if einfo.get("needs_pathb"):
            prefixb = sel.name + "_wpb_"
            wpsb = sorted(
                [o for o in _level_objects(scene) if o.name.startswith(prefixb) and o.type == "EMPTY"],
                key=lambda o: o.name
            )
            box2 = layout.box()
            box2.label(text=f"Path B  ({len(wpsb)} points)", icon="ANIM")
            if wpsb:
                col2 = box2.column(align=True)
                for wp in wpsb:
                    row = col2.row(align=True)
                    row.label(text=wp.name, icon="EMPTY_AXIS")
                    op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                    op.obj_name = wp.name
                    op = row.operator("og.delete_waypoint", text="", icon="X")
                    op.wp_name = wp.name

            op = box2.operator("og.add_waypoint", text="Add Path B Waypoint", icon="PLUS")
            op.enemy_name = sel.name
            op.pathb_mode = True

            if len(wpsb) < 1:
                box2.label(text="⚠ swamp-bat crashes without Path B", icon="ERROR")


def _draw_selected_spawn(layout, sel, scene):
    """Draw settings for a SPAWN_ object."""
    layout.label(text=sel.name, icon="EMPTY_ARROWS")
    cam_obj = scene.objects.get(sel.name + "_CAM")
    if cam_obj:
        row = layout.row()
        row.label(text=f"✓ {cam_obj.name}", icon="CAMERA_DATA")
        op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
        op.obj_name = cam_obj.name
    else:
        layout.label(text="⚠ No camera anchor", icon="ERROR")
        layout.operator("og.spawn_cam_anchor", text="Add Camera", icon="CAMERA_DATA")


def _draw_selected_checkpoint(layout, sel, scene):
    """Draw settings for a CHECKPOINT_ object."""
    layout.label(text=sel.name, icon="EMPTY_SINGLE_ARROW")

    # Camera
    cam_obj = scene.objects.get(sel.name + "_CAM")
    if cam_obj:
        row = layout.row()
        row.label(text=f"✓ {cam_obj.name}", icon="CAMERA_DATA")
        op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
        op.obj_name = cam_obj.name
    else:
        layout.label(text="⚠ No camera anchor", icon="ERROR")
        layout.operator("og.spawn_cam_anchor", text="Add Camera", icon="CAMERA_DATA")

    # Volume link
    layout.separator(factor=0.3)
    vol_list = _vols_linking_to(scene, sel.name)
    if vol_list:
        vol_linked = vol_list[0]
        row = layout.row(align=True)
        row.label(text=f"✓ {vol_linked.name}", icon="MESH_CUBE")
        op = row.operator("og.remove_vol_link", text="", icon="X")
        op.vol_name = vol_linked.name
        op.target_name = sel.name
    else:
        r = float(sel.get("og_checkpoint_radius", 3.0))
        layout.label(text=f"⚠ No trigger volume (fallback r={r:.1f}m)", icon="ERROR")
        op = layout.operator("og.spawn_volume_autolink", text="Add Trigger Volume", icon="MESH_CUBE")
        op.target_name = sel.name


def _draw_selected_emitter(layout, sel):
    """Draw settings for an AMBIENT_ sound emitter."""
    snd  = sel.get("og_sound_name", "?")
    mode = sel.get("og_sound_mode", "loop")
    radius = float(sel.get("og_sound_radius", 15.0))

    layout.label(text=sel.name, icon="SPEAKER")

    box = layout.box()
    box.label(text=f"Sound: {snd}", icon="PLAY")
    box.label(text=f"Mode: {mode}", icon="PREVIEW_RANGE" if mode == "loop" else "PLAYER")
    box.label(text=f"Radius: {radius:.1f}m", icon="SPHERE")


def _draw_selected_volume(layout, sel, scene):
    """Draw settings for a VOL_ trigger volume.
    Lists every link entry; per-link UI varies by target type:
      camera/checkpoint links → just name + unlink button
      nav-enemy links → name + behaviour dropdown + unlink button
    """
    layout.label(text=sel.name, icon="MESH_CUBE")

    links = _vol_links(sel)
    n = len(links)

    box = layout.box()
    box.label(text=f"Links ({n})", icon="LINKED")

    if n == 0:
        box.label(text="Not linked", icon="INFO")
    else:
        col = box.column(align=True)
        for entry in links:
            tname = entry.target_name
            target = scene.objects.get(tname)
            kind = _classify_target(tname)
            row = col.row(align=True)
            if not target:
                row.alert = True
                row.label(text=f"⚠ missing: {tname}", icon="ERROR")
            else:
                # Icon by target type
                icon = "MESH_CUBE"
                if kind == "camera":
                    icon = "CAMERA_DATA"
                elif kind == "checkpoint":
                    icon = "EMPTY_SINGLE_ARROW"
                elif kind == "enemy":
                    icon = "OUTLINER_OB_ARMATURE"
                row.label(text=tname, icon=icon)
                # Behaviour dropdown — only for nav-enemy targets
                if kind == "enemy":
                    row.prop(entry, "behaviour", text="")
                # Jump-to button
                op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                op.obj_name = tname
            # Per-link unlink button
            op = row.operator("og.remove_vol_link", text="", icon="X")
            op.vol_name = sel.name
            op.target_name = tname

    # Add-link button: enabled when exactly one other linkable object selected
    sel_targets = [o for o in bpy.context.selected_objects
                   if _is_linkable(o) and o != sel]
    if len(sel_targets) == 1:
        op = box.operator("og.add_link_from_selection", text=f"Link → {sel_targets[0].name}", icon="LINKED")
        op.vol_name = sel.name
        op.target_name = sel_targets[0].name
    else:
        box.label(text="Shift-select a target then click Link →", icon="INFO")

    if n > 0:
        layout.operator("og.unlink_volume", text="Clear All Links", icon="X")


def _draw_selected_camera(layout, sel, scene):
    """Draw full settings for a CAMERA_ object."""
    layout.label(text=sel.name, icon="CAMERA_DATA")

    mode   = sel.get("og_cam_mode",   "fixed")
    interp = float(sel.get("og_cam_interp", 1.0))
    fov    = float(sel.get("og_cam_fov",    0.0))

    # ── Mode selector ────────────────────────────────────────────────────
    box = layout.box()
    box.label(text="Mode", icon="OUTLINER_DATA_CAMERA")
    mrow = box.row(align=True)
    for m, lbl in (("fixed","Fixed"),("standoff","Side-Scroll"),("orbit","Orbit")):
        op = mrow.operator("og.set_cam_prop", text=lbl, depress=(mode == m))
        op.cam_name = sel.name; op.prop_name = "og_cam_mode"; op.str_val = m

    # ── Blend time ───────────────────────────────────────────────────────
    brow = box.row(align=True)
    brow.label(text=f"Blend: {interp:.1f}s")
    op = brow.operator("og.nudge_cam_float", text="-")
    op.cam_name = sel.name; op.prop_name = "og_cam_interp"; op.delta = -0.5
    op = brow.operator("og.nudge_cam_float", text="+")
    op.cam_name = sel.name; op.prop_name = "og_cam_interp"; op.delta = 0.5

    # ── FOV ──────────────────────────────────────────────────────────────
    frow = box.row(align=True)
    frow.label(text=f"FOV: {'default' if fov <= 0 else f'{fov:.0f}°'}")
    op = frow.operator("og.nudge_cam_float", text="-")
    op.cam_name = sel.name; op.prop_name = "og_cam_fov"; op.delta = -5.0
    op = frow.operator("og.nudge_cam_float", text="+")
    op.cam_name = sel.name; op.prop_name = "og_cam_fov"; op.delta = 5.0

    # ── Mode-specific helpers ────────────────────────────────────────────
    if mode == "standoff":
        align_name = sel.name + "_ALIGN"
        has_align = bool(scene.objects.get(align_name))
        arow = box.row()
        if has_align:
            arow.label(text=f"Anchor: {align_name}", icon="CHECKMARK")
            op = arow.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = align_name
        else:
            arow.label(text="No anchor", icon="ERROR")
            arow.operator("og.spawn_cam_align", text="Add Anchor")

    elif mode == "orbit":
        pivot_name = sel.name + "_PIVOT"
        has_pivot = bool(scene.objects.get(pivot_name))
        prow = box.row()
        if has_pivot:
            prow.label(text=f"Pivot: {pivot_name}", icon="CHECKMARK")
            op = prow.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = pivot_name
        else:
            prow.label(text="No pivot", icon="ERROR")
            prow.operator("og.spawn_cam_pivot", text="Add Pivot")

    # ── Look-at target ───────────────────────────────────────────────────
    look_at_name = sel.get("og_cam_look_at", "").strip()
    look_obj = scene.objects.get(look_at_name) if look_at_name else None

    lbox = layout.box()
    lbox.label(text="Look-At", icon="PIVOT_CURSOR")
    if look_obj:
        lrow = lbox.row(align=True)
        lrow.label(text=f"Target: {look_at_name}", icon="CHECKMARK")
        op = lrow.operator("og.select_and_frame", text="", icon="VIEWZOOM")
        op.obj_name = look_at_name
        op = lbox.operator("og.set_cam_prop", text="Clear Look-At", icon="X")
        op.cam_name = sel.name; op.prop_name = "og_cam_look_at"; op.str_val = ""
        lbox.label(text="Camera ignores rotation — aims at target", icon="INFO")
    else:
        lbox.label(text="None (uses camera rotation)", icon="DOT")
        lbox.operator("og.spawn_cam_look_at", text="Add Look-At Target", icon="PIVOT_CURSOR")

    # ── Rotation info ────────────────────────────────────────────────────
    try:
        q = sel.matrix_world.to_quaternion()
        rbox = layout.box()
        rbox.label(text=f"Rot (wxyz): {q.w:.2f} {q.x:.2f} {q.y:.2f} {q.z:.2f}", icon="ORIENTATION_GIMBAL")
        if abs(q.w) > 0.99 and not look_obj:
            rbox.label(text="⚠ Camera has no rotation!", icon="ERROR")
            rbox.label(text="Rotate it to aim, then export.")
    except Exception:
        pass

    # ── Linked trigger volumes ───────────────────────────────────────────
    vols = _vols_linking_to(scene, sel.name)
    vbox = layout.box()
    vbox.label(text="Trigger Volumes", icon="MESH_CUBE")
    if vols:
        for v in vols:
            row = vbox.row(align=True)
            row.label(text=v.name, icon="CHECKMARK")
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = v.name
            op = row.operator("og.remove_vol_link", text="", icon="X")
            op.vol_name = v.name
            op.target_name = sel.name
    else:
        vbox.label(text="No trigger — always active", icon="INFO")
    op = vbox.operator("og.spawn_volume_autolink", text="Add Volume", icon="ADD")
    op.target_name = sel.name


def _draw_selected_cam_anchor(layout, sel, scene):
    """Draw settings for a camera anchor (*_CAM)."""
    layout.label(text=sel.name, icon="CAMERA_DATA")
    # Find parent
    parent_name = sel.name[:-4]  # strip _CAM
    parent = scene.objects.get(parent_name)
    if parent:
        row = layout.row(align=True)
        row.label(text=f"Anchored to: {parent_name}", icon="LINKED")
        op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
        op.obj_name = parent_name
    else:
        layout.label(text=f"⚠ Parent '{parent_name}' not found", icon="ERROR")


def _draw_selected_navmesh(layout, sel):
    """Draw info for a mesh that is linked as navmesh."""
    layout.label(text=sel.name, icon="MOD_MESHDEFORM")

    # Find which actors reference this mesh
    linked_actors = []
    for o in bpy.data.objects:
        if o.get("og_navmesh_link") == sel.name:
            linked_actors.append(o.name)

    if linked_actors:
        box = layout.box()
        box.label(text=f"Used by {len(linked_actors)} actor(s):", icon="LINKED")
        for name in linked_actors[:6]:
            row = box.row(align=True)
            row.label(text=f"  {name}")
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = name
        if len(linked_actors) > 6:
            box.label(text=f"  … and {len(linked_actors) - 6} more")
    else:
        layout.label(text="Not linked to any actor", icon="INFO")

    try:
        sel.data.calc_loop_triangles()
        tc = len(sel.data.loop_triangles)
        layout.label(text=f"{tc} triangles", icon="MESH_DATA")
    except Exception:
        pass


def _draw_selected_mesh_collision(layout, obj):
    """Draw collision properties for any mesh object."""
    box = layout.box()
    box.label(text="Collision", icon="MOD_PHYSICS")

    box.prop(obj, "set_collision")
    if obj.set_collision:
        col = box.column(align=True)
        col.prop(obj, "ignore")
        col.prop(obj, "collide_mode")
        col.prop(obj, "collide_material")
        col.prop(obj, "collide_event")
        r = col.row(align=True)
        r.prop(obj, "noedge");  r.prop(obj, "noentity")
        r2 = col.row(align=True)
        r2.prop(obj, "nolineofsight"); r2.prop(obj, "nocamera")


def _draw_selected_mesh_visibility(layout, obj):
    """Draw visibility and weight properties for any mesh object."""
    box = layout.box()
    box.label(text="Visibility & Weights", icon="HIDE_OFF")
    box.prop(obj, "set_invisible")
    box.prop(obj, "enable_custom_weights")
    box.prop(obj, "copy_eye_draws")
    box.prop(obj, "copy_mod_draws")


def _draw_selected_mesh_lightbake(layout, ctx):
    """Draw light bake controls for selected mesh(es)."""
    props = ctx.scene.og_props
    targets = [o for o in ctx.selected_objects if o.type == "MESH"]
    if not targets:
        return

    box = layout.box()
    box.label(text="Light Baking", icon="LIGHT")
    box.prop(props, "lightbake_samples")
    row = box.row()
    row.scale_y = 1.4
    row.operator("og.bake_lighting", text=f"Bake {len(targets)} mesh(es)", icon="RENDER_STILL")


def _draw_selected_mesh_navtag(layout, obj):
    """Draw navmesh mark/unmark controls for mesh objects."""
    is_tagged = obj.get("og_navmesh", False)
    box = layout.box()
    box.label(text="NavMesh Tag", icon="MOD_MESHDEFORM")
    if is_tagged:
        box.label(text="✓ Tagged as navmesh geometry", icon="CHECKMARK")
        box.operator("og.unmark_navmesh", text="Unmark as NavMesh", icon="X")
    else:
        box.label(text="Not tagged as navmesh", icon="DOT")
        box.operator("og.mark_navmesh", text="Mark as NavMesh", icon="CHECKMARK")


class OG_PT_SelectedObject(Panel):
    bl_label       = "🔍  Selected Object"
    bl_idname      = "OG_PT_selected_object"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"

    @classmethod
    def poll(cls, ctx):
        return True  # Always visible — draw handles empty/unmanaged selection

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        if sel is None:
            layout.label(text="Select an object to inspect", icon="INFO")
            return

        if not _og_managed_object(sel):
            layout.label(text=sel.name, icon="OBJECT_DATA")
            layout.label(text="Not an OpenGOAL-managed object", icon="INFO")
            return

        # Name + type hint — sub-panels carry all the detail
        name = sel.name
        if name.startswith("ACTOR_") and "_wp_" not in name:
            parts = name.split("_", 2)
            etype = parts[1] if len(parts) >= 3 else ""
            einfo = ENTITY_DEFS.get(etype, {})
            label = einfo.get("label", etype)
            cat   = einfo.get("cat", "")
            row = layout.row()
            row.label(text=label, icon="OBJECT_DATA")
            sub = row.row(); sub.enabled = False
            sub.label(text=f"[{cat}]")
        elif name.startswith("SPAWN_") and not name.endswith("_CAM"):
            layout.label(text=name, icon="EMPTY_ARROWS")
        elif name.startswith("CHECKPOINT_") and not name.endswith("_CAM"):
            layout.label(text=name, icon="EMPTY_SINGLE_ARROW")
        elif name.startswith("AMBIENT_"):
            layout.label(text=name, icon="SPEAKER")
        elif name.startswith("CAMERA_") and sel.type == "CAMERA":
            layout.label(text=name, icon="CAMERA_DATA")
        elif name.startswith("VOL_"):
            layout.label(text=name, icon="MESH_CUBE")
        elif name.endswith("_CAM"):
            layout.label(text=name, icon="CAMERA_DATA")
        elif sel.type == "MESH":
            layout.label(text=name, icon="MOD_MESHDEFORM" if (sel.get("og_navmesh") or name.startswith("NAVMESH_")) else "MESH_DATA")
        else:
            layout.label(text=name, icon="OBJECT_DATA")

        # Universal actions
        layout.separator(factor=0.3)
        row = layout.row(align=True)
        op = row.operator("og.select_and_frame", text="Frame", icon="VIEWZOOM")
        op.obj_name = name
        op = row.operator("og.delete_object", text="Delete", icon="TRASH")
        op.obj_name = name


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Operator — clear vertex-export assignment
# ---------------------------------------------------------------------------

class OG_OT_ClearVertexExport(bpy.types.Operator):
    bl_idname      = "og.clear_vertex_export"
    bl_label       = "Clear Export As"
    bl_description = "Remove the vertex-export entity assignment from this mesh"
    bl_options     = {"UNDO"}

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_vertex_export_etype"]  = ""
            o["og_vertex_export_search"] = ""
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Selected Object > Export As  (sub-panel — only on plain MESH objects)
# ---------------------------------------------------------------------------

class OG_PT_VertexExport(Panel):
    bl_label       = "Export As"
    bl_idname      = "OG_PT_vertex_export"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        o = ctx.active_object
        return (
            o is not None
            and o.type == "MESH"
            and not o.name.startswith(("ACTOR_", "VOL_", "NAVMESH_", "CPVOL_"))
            and not o.get("og_navmesh")
        )

    def draw(self, ctx):
        layout = self.layout
        o      = ctx.active_object

        assigned = str(o.get("og_vertex_export_etype", "")).strip()
        search   = str(o.get("og_vertex_export_search", "")).strip()

        # ── Current assignment ────────────────────────────────────────────
        if assigned and assigned in VERTEX_EXPORT_TYPES:
            info = VERTEX_EXPORT_TYPES[assigned]
            box  = layout.box()
            row  = box.row(align=True)
            row.label(text=f"{info['label']}  [{info.get('cat','')}]", icon="CHECKMARK")
            row.operator("og.clear_vertex_export", text="", icon="X")
            # Use evaluated mesh so the preview count reflects modifiers
            try:
                depsgraph = ctx.evaluated_depsgraph_get()
                o_eval    = o.evaluated_get(depsgraph)
                vcount    = len(o_eval.to_mesh().vertices)
                o_eval.to_mesh_clear()
            except Exception:
                vcount = len(o.data.vertices)
            box.label(text=f"{vcount} vert{'ex' if vcount == 1 else 'ices'} → {vcount} actor{'s' if vcount != 1 else ''} (post-modifiers)", icon="INFO")
        else:
            layout.label(text="No entity assigned", icon="INFO")

        layout.separator(factor=0.3)

        # ── Search bar ────────────────────────────────────────────────────
        row = layout.row(align=True)
        # Use a temporary scene prop for the search string (Object props
        # can't drive Blender search fields directly without a UIList).
        row.prop(ctx.scene.og_props, "entity_search", icon="VIEWZOOM", text="")

        query = ctx.scene.og_props.entity_search.strip().lower()

        if query:
            matches = [
                (etype, info)
                for etype, info in VERTEX_EXPORT_TYPES.items()
                if query in info["label"].lower() or query in etype.lower()
            ]
            matches.sort(key=lambda x: x[1]["label"].lower())

            if matches:
                box = layout.box()
                for etype, info in matches[:20]:
                    cat    = info.get("cat", "")
                    label  = info["label"]
                    is_sel = (etype == assigned)
                    row2   = box.row(align=True)
                    op = row2.operator(
                        "og.assign_vertex_export",
                        text=f"{'▶ ' if is_sel else ''}{label}  [{cat}]",
                        emboss=is_sel,
                    )
                    op.etype = etype
                if len(matches) > 20:
                    layout.label(text=f"… {len(matches) - 20} more", icon="INFO")
            else:
                layout.label(text="No results", icon="QUESTION")
        else:
            layout.label(text="Search to assign an entity type", icon="INFO")


# ---------------------------------------------------------------------------
# Operator — assign vertex-export entity type to active mesh
# ---------------------------------------------------------------------------

class OG_OT_AssignVertexExport(bpy.types.Operator):
    bl_idname      = "og.assign_vertex_export"
    bl_label       = "Assign Entity"
    bl_description = "Set this entity type as the vertex-export target for this mesh"
    bl_options     = {"UNDO"}

    etype: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_vertex_export_etype"]  = self.etype
            o["og_vertex_export_search"] = ""
            ctx.scene.og_props.entity_search = ""   # clear the shared search bar
            # Move into the Export As sub-collection so it stays organised
            _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_EXPORT_AS)
        return {"FINISHED"}


# Selected Object sub-panels  (mesh context, collapsible)
# ---------------------------------------------------------------------------

class OG_PT_SelectedCollision(Panel):
    bl_label       = "Collision"
    bl_idname      = "OG_PT_selected_collision"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel is not None and sel.type == "MESH"

    def draw(self, ctx):
        _draw_selected_mesh_collision(self.layout, ctx.active_object)
        self.layout.separator(factor=0.2)
        _draw_selected_mesh_visibility(self.layout, ctx.active_object)


class OG_PT_SelectedLightBaking(Panel):
    bl_label       = "Light Baking"
    bl_idname      = "OG_PT_selected_lightbaking"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel is not None and sel.type == "MESH"

    def draw(self, ctx):
        _draw_selected_mesh_lightbake(self.layout, ctx)


class OG_PT_SelectedNavMeshTag(Panel):
    bl_label       = "NavMesh"
    bl_idname      = "OG_PT_selected_navmesh_tag"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel is not None and sel.type == "MESH"

    def draw(self, ctx):
        _draw_selected_mesh_navtag(self.layout, ctx.active_object)


# ===========================================================================
# OBJECT-TYPE SUB-PANELS
# Each polls on the active object's name prefix/type so it only appears
# for the relevant object. All carry bl_parent_id="OG_PT_selected_object".
# ===========================================================================

# ── ACTOR sub-panels ────────────────────────────────────────────────────────

class OG_PT_ActorActivation(Panel):
    bl_label       = "Activation"
    bl_idname      = "OG_PT_actor_activation"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and _actor_is_enemy(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        idle_d = float(sel.get("og_idle_distance", 80.0))
        row = layout.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-5m", icon="REMOVE")
        op.prop_name = "og_idle_distance"; op.delta = -5.0; op.val_min = 0.0
        row.label(text=f"Idle Distance: {idle_d:.0f}m")
        op = row.operator("og.nudge_float_prop", text="+5m", icon="ADD")
        op.prop_name = "og_idle_distance"; op.delta = 5.0; op.val_max = 500.0
        sub = layout.row(); sub.enabled = False
        sub.label(text="Player must be closer than this to wake the enemy", icon="INFO")


class OG_PT_ActorTriggerBehaviour(Panel):
    bl_label       = "Trigger Behaviour"
    bl_idname      = "OG_PT_actor_trigger_behaviour"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and _actor_supports_aggro_trigger(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        scene  = ctx.scene
        linked_vols = _vols_linking_to(scene, sel.name)
        if linked_vols:
            for v in linked_vols:
                entry = _vol_get_link_to(v, sel.name)
                if not entry: continue
                row = layout.row(align=True)
                row.label(text=f"✓ {v.name}", icon="MESH_CUBE")
                row.prop(entry, "behaviour", text="")
                op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                op.obj_name = v.name
                op = row.operator("og.remove_vol_link", text="", icon="X")
                op.vol_name = v.name; op.target_name = sel.name
        else:
            sub = layout.row(); sub.enabled = False
            sub.label(text="No trigger volumes linked", icon="INFO")
        op = layout.operator("og.spawn_aggro_trigger", text="Add Aggro Trigger", icon="ADD")
        op.target_name = sel.name


class OG_PT_ActorNavMesh(Panel):
    bl_label       = "NavMesh"
    bl_idname      = "OG_PT_actor_navmesh"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and _actor_uses_navmesh(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        nm_name = sel.get("og_navmesh_link", "")
        nm_obj  = bpy.data.objects.get(nm_name) if nm_name else None
        if nm_obj:
            row = layout.row(align=True)
            row.label(text=f"✓ {nm_obj.name}", icon="CHECKMARK")
            row.operator("og.unlink_navmesh", text="", icon="X")
            try:
                nm_obj.data.calc_loop_triangles()
                tc = len(nm_obj.data.loop_triangles)
                layout.label(text=f"{tc} triangles", icon="MESH_DATA")
            except Exception:
                pass
        else:
            layout.label(text="No mesh linked", icon="ERROR")
            sel_meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
            if sel_meshes:
                layout.label(text=f"Will link to: {sel_meshes[0].name}", icon="INFO")
                layout.operator("og.link_navmesh", text="Link NavMesh", icon="LINKED")
            else:
                layout.label(text="Shift-select a mesh to link", icon="INFO")
        nav_r = float(sel.get("og_nav_radius", 6.0))
        layout.label(text=f"Fallback sphere radius: {nav_r:.1f}m", icon="SPHERE")


def _draw_actor_links(layout, obj, scene, etype):
    """Draw the Actor Links panel for an ACTOR_ empty.

    Shows each defined slot with:
    - Current linked target (name + jump-to button) or 'Not set'
    - A 'Link →' button when exactly one compatible ACTOR_ is shift-selected
    - An X (clear) button when a link is set
    """
    slots = _actor_link_slots(etype)
    if not slots:
        layout.label(text="No entity link slots for this actor type.", icon="INFO")
        return

    # Gather the currently shift-selected ACTOR_ empties (excluding this one)
    sel_actors = [
        o for o in bpy.context.selected_objects
        if o != obj
        and o.type == "EMPTY"
        and o.name.startswith("ACTOR_")
        and "_wp_" not in o.name
        and "_wpb_" not in o.name
    ]

    # Group slots by lump_key for display
    seen_keys = []
    for (lkey, sidx, label, accepted, required) in slots:
        if lkey not in seen_keys:
            seen_keys.append(lkey)

    for lkey in seen_keys:
        key_slots = [(sidx, lbl, acc, req) for (lk, sidx, lbl, acc, req) in slots if lk == lkey]

        box = layout.box()
        box.label(text=lkey, icon="LINKED")

        for (sidx, label, accepted, required) in key_slots:
            entry = _actor_get_link(obj, lkey, sidx)
            current_name = entry.target_name if entry else ""
            current_obj  = scene.objects.get(current_name) if current_name else None

            row = box.row(align=True)

            # Slot label
            req_mark = " *" if required else ""
            row.label(text=f"[{sidx}] {label}{req_mark}")

            if current_obj:
                # Linked — show name, jump-to, clear buttons
                row2 = box.row(align=True)
                row2.label(text=current_name, icon="CHECKMARK")
                op = row2.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                op.obj_name = current_name
                op = row2.operator("og.clear_actor_link", text="", icon="X")
                op.source_name = obj.name
                op.lump_key    = lkey
                op.slot_index  = sidx
            elif current_name:
                # Name stored but object missing from scene
                row2 = box.row(align=True)
                row2.alert = True
                row2.label(text=f"⚠ missing: {current_name}", icon="ERROR")
                op = row2.operator("og.clear_actor_link", text="", icon="X")
                op.source_name = obj.name
                op.lump_key    = lkey
                op.slot_index  = sidx
            else:
                # Not set
                row2 = box.row(align=True)
                row2.enabled = False
                req_text = "Required — not set" if required else "Optional — not set"
                row2.label(text=req_text, icon="ERROR" if required else "DOT")

            # Link button: visible when one compatible actor is shift-selected
            compatible = [
                o for o in sel_actors
                if accepted == ["any"] or
                   (len(o.name.split("_", 2)) >= 3 and o.name.split("_", 2)[1] in accepted)
            ]
            if len(compatible) == 1:
                tgt = compatible[0]
                op = box.operator("og.set_actor_link",
                                  text=f"Link → {tgt.name}", icon="LINKED")
                op.source_name = obj.name
                op.lump_key    = lkey
                op.slot_index  = sidx
                op.target_name = tgt.name
            elif len(sel_actors) > 0 and len(compatible) == 0:
                hint = box.row()
                hint.enabled = False
                hint.label(text=f"Selected actor not valid for this slot", icon="INFO")
                hint2 = box.row()
                hint2.enabled = False
                hint2.label(text=f"  Accepted: {', '.join(accepted)}")
            else:
                hint = box.row()
                hint.enabled = False
                hint.label(text="Shift-select target then click Link →", icon="INFO")


class OG_PT_ActorLinks(Panel):
    """Entity link slots — actor-to-actor references exported as alt-actor / water-actor etc."""
    bl_label       = "Entity Links"
    bl_idname      = "OG_PT_actor_links"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name:
            return False
        parts = sel.name.split("_", 2)
        return (len(parts) >= 3
                and parts[0] == "ACTOR"
                and _actor_has_links(parts[1]))

    def draw(self, ctx):
        sel   = ctx.active_object
        etype = sel.name.split("_", 2)[1]
        _draw_actor_links(self.layout, sel, ctx.scene, etype)


class OG_PT_ActorPlatform(Panel):
    bl_label       = "Platform Settings"
    bl_idname      = "OG_PT_actor_platform"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and _actor_is_platform(parts[1])

    def draw(self, ctx):
        _draw_platform_settings(self.layout, ctx.active_object, ctx.scene)


class OG_PT_ActorCrate(Panel):
    bl_label       = "Crate"
    bl_idname      = "OG_PT_actor_crate"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "crate"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        ct     = sel.get("og_crate_type",          "steel")
        pickup = sel.get("og_crate_pickup",         "money")
        amount = int(sel.get("og_crate_pickup_amount", 1))

        # ── Crate Type ───────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Crate Type", icon="PACKAGE")
        col = box.column(align=True)
        for (val, label, _, _, _) in CRATE_ITEMS:
            sub = col.row(align=True)
            # Wood is greyed out when a scout fly is inside
            sub.enabled = not (val == "wood" and pickup == "buzzer")
            icon = "RADIOBUT_ON" if ct == val else "RADIOBUT_OFF"
            op = sub.operator("og.set_crate_type", text=label, icon=icon)
            op.crate_type = val

        # Scout fly + wood warning
        if pickup == "buzzer" and ct == "wood":
            warn = box.box()
            warn.alert = True
            warn.label(text="Scout Fly needs Iron/Steel!", icon="ERROR")

        # ── Contents ─────────────────────────────────────────────────────
        box2 = layout.box()
        box2.label(text="Contents", icon="GHOST_ENABLED")
        col2 = box2.column(align=True)
        for (uid, label, _, ico, _) in CRATE_PICKUP_ITEMS:
            sub = col2.row(align=True)
            btn_icon = "RADIOBUT_ON" if pickup == uid else "RADIOBUT_OFF"
            op = sub.operator("og.set_crate_pickup", text=label, icon=btn_icon)
            op.pickup_id = uid

        # ── Amount stepper (only for orbs) ────────────────────────────────
        _supports_multi = {uid: sm for (uid, _, _, _, sm) in CRATE_PICKUP_ITEMS}
        if _supports_multi.get(pickup, False):
            row = box2.row(align=True)
            row.label(text="Amount:")
            op = row.operator("og.set_crate_amount", text="", icon="REMOVE")
            op.delta = -1
            row.label(text=str(amount))
            op2 = row.operator("og.set_crate_amount", text="", icon="ADD")
            op2.delta = 1
        elif pickup == "buzzer":
            box2.label(text="Amount: 1  (fixed)", icon="INFO")


class OG_PT_ActorDarkCrystal(Panel):
    bl_label       = "Dark Crystal Settings"
    bl_idname      = "OG_PT_actor_dark_crystal"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "dark-crystal"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        underwater = bool(sel.get("og_crystal_underwater", False))

        box = layout.box()
        box.label(text="Variant", icon="SPHERE")
        icon = "CHECKBOX_HLT" if underwater else "CHECKBOX_DEHLT"
        label = "Underwater variant ✓" if underwater else "Underwater variant"
        box.operator("og.toggle_crystal_underwater", text=label, icon=icon)
        sub = box.row(); sub.enabled = False
        if underwater:
            sub.label(text="mode=1: dark teal texture, submerged look", icon="INFO")
        else:
            sub.label(text="mode=0: standard cave crystal (default)", icon="INFO")


class OG_PT_ActorFuelCell(Panel):
    bl_label       = "Power Cell Settings"
    bl_idname      = "OG_PT_actor_fuel_cell"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "fuel-cell"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        skip_jump = bool(sel.get("og_cell_skip_jump", False))

        box = layout.box()
        box.label(text="Collection Options", icon="SPHERE")
        icon = "CHECKBOX_HLT" if skip_jump else "CHECKBOX_DEHLT"
        box.operator("og.toggle_cell_skip_jump", text="Skip Jump Animation", icon=icon)
        sub = box.row(); sub.enabled = False
        if skip_jump:
            sub.label(text="Cell collected instantly, no jump cutscene", icon="INFO")
        else:
            sub.label(text="Default: Jak jumps to collect the cell", icon="INFO")


class OG_PT_ActorLauncher(Panel):
    bl_label       = "Launcher Settings"
    bl_idname      = "OG_PT_actor_launcher"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and _actor_is_launcher(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        etype  = sel.name.split("_", 2)[1]

        # ── Spring Height ─────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Launch Height", icon="TRIA_UP")
        height = float(sel.get("og_spring_height", -1.0))
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-2m", icon="REMOVE")
        op.prop_name = "og_spring_height"; op.delta = -2.0; op.val_min = 0.0
        if height < 0:
            row.label(text="Default (~40m)")
        else:
            row.label(text=f"{height:.1f}m")
        op = row.operator("og.nudge_float_prop", text="+2m", icon="ADD")
        op.prop_name = "og_spring_height"; op.delta = 2.0; op.val_max = 200.0
        if height >= 0:
            op2 = box.operator("og.nudge_float_prop", text="Reset to Default", icon="LOOP_BACK")
            op2.prop_name = "og_spring_height"; op2.delta = -9999.0; op2.val_min = -1.0
        else:
            sub = box.row(); sub.enabled = False
            sub.label(text="Uses art default (~40m). Set above to override.", icon="INFO")

        # ── Springbox has no destination, launcher does ───────────────────────
        if etype == "launcher":
            box2 = layout.box()
            box2.label(text="Launch Destination (optional)", icon="EMPTY_AXIS")
            dest_name = sel.get("og_launcher_dest", "")
            dest_obj  = bpy.data.objects.get(dest_name) if dest_name else None

            sel_dests = [
                o for o in ctx.selected_objects
                if o != sel and o.type == "EMPTY" and o.name.startswith("DEST_")
            ]

            if dest_obj:
                row2 = box2.row(align=True)
                row2.label(text=f"✓ {dest_obj.name}", icon="CHECKMARK")
                op = row2.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                op.obj_name = dest_obj.name
                op = row2.operator("og.clear_launcher_dest", text="", icon="X")
                op.launcher_name = sel.name
            elif dest_name:
                row2 = box2.row(); row2.alert = True
                row2.label(text=f"⚠ missing: {dest_name}", icon="ERROR")
                op = row2.operator("og.clear_launcher_dest", text="", icon="X")
                op.launcher_name = sel.name
            else:
                sub = box2.row(); sub.enabled = False
                sub.label(text="Not set — Jak launches straight up", icon="INFO")

            if len(sel_dests) == 1:
                op = box2.operator("og.set_launcher_dest", text=f"Link → {sel_dests[0].name}", icon="LINKED")
                op.launcher_name = sel.name
                op.dest_name = sel_dests[0].name
            else:
                op = box2.operator("og.add_launcher_dest", text="Add Destination Empty at Cursor", icon="ADD")
                op.launcher_name = sel.name

            # Fly time
            box3 = layout.box()
            box3.label(text="Fly Time (optional)", icon="TIME")
            fly_time = float(sel.get("og_launcher_fly_time", -1.0))
            row3 = box3.row(align=True)
            op = row3.operator("og.nudge_float_prop", text="-0.2s", icon="REMOVE")
            op.prop_name = "og_launcher_fly_time"; op.delta = -0.2; op.val_min = 0.1
            if fly_time < 0:
                row3.label(text="Default")
            else:
                row3.label(text=f"{fly_time:.1f}s")
            op = row3.operator("og.nudge_float_prop", text="+0.2s", icon="ADD")
            op.prop_name = "og_launcher_fly_time"; op.delta = 0.2; op.val_max = 30.0
            if fly_time >= 0:
                op2 = box3.operator("og.nudge_float_prop", text="Reset to Default", icon="LOOP_BACK")
                op2.prop_name = "og_launcher_fly_time"; op2.delta = -9999.0; op2.val_min = -1.0
            else:
                sub = box3.row(); sub.enabled = False
                sub.label(text="Only needed when Destination is set.", icon="INFO")


class OG_PT_ActorSpawner(Panel):
    bl_label       = "Spawner Settings"
    bl_idname      = "OG_PT_actor_spawner"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and _actor_is_spawner(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        etype  = sel.name.split("_", 2)[1]

        box = layout.box()
        box.label(text="Spawn Count", icon="COMMUNITY")

        defaults = {
            "swamp-bat":      ("6", "2–8 bat slaves. Default 6."),
            "yeti":           ("path", "One yeti-slave per path point. Default = path count."),
            "villa-starfish": ("3", "Starfish children. Default 3. Max 8."),
            "swamp-rat-nest": ("3", "Rats active at once. Default 3. Max 4."),
        }
        default_str, hint = defaults.get(etype, ("auto", ""))

        count = int(sel.get("og_num_lurkers", -1))
        row = box.row(align=True)
        op = row.operator("og.nudge_int_prop", text="-1", icon="REMOVE")
        op.prop_name = "og_num_lurkers"; op.delta = -1; op.val_min = 1
        if count < 0:
            row.label(text=f"Default ({default_str})")
        else:
            row.label(text=f"{count}")
        op = row.operator("og.nudge_int_prop", text="+1", icon="ADD")
        op.prop_name = "og_num_lurkers"; op.delta = 1; op.val_max = 16

        if count >= 0:
            op2 = box.operator("og.nudge_int_prop", text="Reset to Default", icon="LOOP_BACK")
            op2.prop_name = "og_num_lurkers"; op2.delta = -999; op2.val_min = -1

        sub = box.row(); sub.enabled = False
        sub.label(text=hint, icon="INFO")


class OG_PT_ActorEcoDoor(Panel):
    bl_label       = "Eco Door Settings"
    bl_idname      = "OG_PT_actor_eco_door"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        ECO_DOOR_TYPES = {"eco-door", "jng-iris-door", "sidedoor", "rounddoor"}
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] in ECO_DOOR_TYPES

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # ── Open condition hint ───────────────────────────────────────────────
        from opengoal_tools.data import _actor_get_link
        has_state_actor = bool(_actor_get_link(sel, "state-actor", 0))
        hint = layout.box()
        if has_state_actor:
            hint.label(text="Button-controlled door", icon="LINKED")
            col = hint.column(align=True)
            col.enabled = False
            col.label(text="• Locked until linked button is pressed")
            col.label(text="• Opens when Jak walks close with blue eco")
            col.label(text="• Tip: enable One Way to skip blue eco requirement")
        else:
            hint.label(text="Opens when Jak is nearby AND one of:", icon="INFO")
            col = hint.column(align=True)
            col.enabled = False
            col.label(text="• Jak has blue eco")
            col.label(text="• Starts Open is enabled")
            col.label(text="• One-way flag + Jak on exit side")
            col.label(text="• Link a button via Actor Links → state-actor")

        # ── Behaviour flags ───────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Door Behaviour", icon="SETTINGS")

        auto_close  = bool(sel.get("og_door_auto_close",  False))
        one_way     = bool(sel.get("og_door_one_way",     False))
        starts_open = bool(sel.get("og_door_starts_open", False))

        row = box.row()
        icon = "CHECKBOX_HLT" if auto_close else "CHECKBOX_DEHLT"
        row.operator("og.toggle_door_flag", text="Auto Close",   icon=icon).flag = "auto_close"

        row2 = box.row()
        icon2 = "CHECKBOX_HLT" if one_way else "CHECKBOX_DEHLT"
        row2.operator("og.toggle_door_flag", text="One Way",     icon=icon2).flag = "one_way"

        row3 = box.row()
        icon3 = "CHECKBOX_HLT" if starts_open else "CHECKBOX_DEHLT"
        row3.operator("og.toggle_door_flag", text="Starts Open", icon=icon3).flag = "starts_open"

        sub = box.row(); sub.enabled = False
        if starts_open:
            sub.label(text="Door spawns already open (perm-complete set)", icon="CHECKMARK")
        elif auto_close and one_way:
            sub.label(text="Closes after Jak passes, one direction only", icon="INFO")
        elif auto_close:
            sub.label(text="Closes automatically after Jak passes", icon="INFO")
        elif one_way:
            sub.label(text="Can only be opened from one side", icon="INFO")
        else:
            sub.label(text="Default: needs blue eco or button link", icon="INFO")


class OG_PT_ActorWaterVol(Panel):
    bl_label       = "Water Volume Settings"
    bl_idname      = "OG_PT_actor_water_vol"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "water-vol"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # Scale warning — empties default to scale 1 = 2m box, must be scaled up
        sx, sy = abs(sel.scale.x), abs(sel.scale.y)
        if sx < 2.0 or sy < 2.0:
            warn = layout.box()
            warn.label(text="⚠  Scale empty to cover water area!", icon="ERROR")
            warn.label(text=f"Current: {sx*2:.1f}m × {sy*2:.1f}m  (Scale X/Y in 3D view)")

        # Surface height
        box = layout.box()
        box.label(text="Water Heights (world Y)", icon="MOD_OCEAN")

        water_y  = float(sel.get("og_water_surface", 0.0))
        wade_y   = float(sel.get("og_water_wade",    water_y - 0.5))
        swim_y   = float(sel.get("og_water_swim",    water_y - 1.0))
        bottom_y = float(sel.get("og_water_bottom",  water_y - 5.0))

        col = box.column(align=True)
        for label, prop, val in [
            ("Surface Y:",  "og_water_surface", water_y),
            ("Wade Y:",     "og_water_wade",    wade_y),
            ("Swim Y:",     "og_water_swim",    swim_y),
            ("Bottom Y:",   "og_water_bottom",  bottom_y),
        ]:
            row = col.row(align=True)
            row.label(text=label)
            op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
            op.prop_name = prop; op.delta = -0.5; op.val_min = -9999.0
            row.label(text=f"{val:.1f}m")
            op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
            op.prop_name = prop; op.delta = 0.5; op.val_max = 9999.0

        # Show computed depths relative to surface so user can sanity-check
        sub = box.column(align=True)
        sub.enabled = False
        sub.label(text=f"  Wade at: {water_y - wade_y:.2f}m below surface", icon="INFO")
        sub.label(text=f"  Swim at: {water_y - swim_y:.2f}m below surface")
        sub.label(text=f"  Kill floor: {water_y - bottom_y:.2f}m below surface")

        op = box.operator("og.sync_water_from_object", text="Sync Surface from Object Y", icon="OBJECT_ORIGIN")
        op.actor_name = sel.name


class OG_PT_WaterMesh(Panel):
    bl_label       = "💧  Water Volume Settings"
    bl_idname      = "OG_PT_water_mesh"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel and sel.type == "MESH" and sel.name.startswith("WATER_")

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # Sync button first — most common first action
        layout.operator("og.sync_water_from_mesh", text="Sync Heights from Mesh Top/Bottom",
                        icon="OBJECT_ORIGIN").mesh_name = sel.name

        box = layout.box()
        box.label(text="Water Heights (world Y)", icon="MOD_OCEAN")

        # surface and bottom are absolute world Y
        # wade and swim are DEPTHS below surface (small positive values like 0.5, 1.0)
        surface = float(sel.get("og_water_surface", sel.location.z))
        wade    = float(sel.get("og_water_wade",    0.5))
        swim    = float(sel.get("og_water_swim",    1.0))
        bottom  = float(sel.get("og_water_bottom",  surface - 5.0))

        col = box.column(align=True)

        # Surface Y — large nudge makes sense
        row = col.row(align=True)
        row.label(text="Surface Y:")
        op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
        op.prop_name = "og_water_surface"; op.delta = -0.5; op.val_min = -9999.0
        row.label(text=f"{surface:.2f}m")
        op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
        op.prop_name = "og_water_surface"; op.delta = 0.5; op.val_max = 9999.0

        # Wade depth — small nudge, stays positive
        row = col.row(align=True)
        row.label(text="Wade depth:")
        op = row.operator("og.nudge_float_prop", text="-0.1m", icon="REMOVE")
        op.prop_name = "og_water_wade"; op.delta = -0.1; op.val_min = 0.1
        row.label(text=f"{wade:.2f}m below")
        op = row.operator("og.nudge_float_prop", text="+0.1m", icon="ADD")
        op.prop_name = "og_water_wade"; op.delta = 0.1; op.val_max = 20.0

        # Swim depth
        row = col.row(align=True)
        row.label(text="Swim depth:")
        op = row.operator("og.nudge_float_prop", text="-0.1m", icon="REMOVE")
        op.prop_name = "og_water_swim"; op.delta = -0.1; op.val_min = 0.1
        row.label(text=f"{swim:.2f}m below")
        op = row.operator("og.nudge_float_prop", text="+0.1m", icon="ADD")
        op.prop_name = "og_water_swim"; op.delta = 0.1; op.val_max = 20.0

        # Bottom Y — absolute, same as surface
        row = col.row(align=True)
        row.label(text="Bottom Y:")
        op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
        op.prop_name = "og_water_bottom"; op.delta = -0.5; op.val_min = -9999.0
        row.label(text=f"{bottom:.2f}m")
        op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
        op.prop_name = "og_water_bottom"; op.delta = 0.5; op.val_max = 9999.0

        # Sanity readout
        sub = box.column(align=True)
        sub.enabled = False
        sub.label(text=f"  Wades at {wade:.2f}m below surface  (Y={surface-wade:.2f})", icon="INFO")
        sub.label(text=f"  Swims at {swim:.2f}m below surface  (Y={surface-swim:.2f})")
        sub.label(text=f"  Kill floor: Y={bottom:.2f}m")

        # Damage type
        box2 = layout.box()
        box2.label(text="Damage Type", icon="GHOST_ENABLED")
        attack = str(sel.get("og_water_attack", "drown"))
        row = box2.row(align=True)
        for opt in ["drown", "lava", "dark-eco-pool", "heat", "drown-death"]:
            r = row.row()
            r.enabled = (attack != opt)
            op = r.operator("og.set_water_attack", text=opt)
            op.mesh_name  = sel.name
            op.attack_val = opt


class OG_PT_ActorLauncherDoor(Panel):
    bl_label       = "Launcher Door Settings"
    bl_idname      = "OG_PT_actor_launcherdoor"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "launcherdoor"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        scene  = ctx.scene

        box = layout.box()
        box.label(text="Continue Point", icon="FORWARD")

        cp_name = sel.get("og_continue_name", "")

        level_name = str(_get_level_prop(scene, "og_level_name", "")).strip().lower().replace(" ", "-")
        cps = sorted([
            o for o in _level_objects(scene)
            if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")
        ], key=lambda o: o.name)
        spawns = sorted([
            o for o in _level_objects(scene)
            if o.name.startswith("SPAWN_") and o.type == "EMPTY" and not o.name.endswith("_CAM")
        ], key=lambda o: o.name)

        all_cps = [(o, f"{level_name}-{o.name[11:]}") for o in cps] + \
                  [(o, f"{level_name}-{o.name[6:]}") for o in spawns]

        if cp_name:
            row = box.row(align=True)
            row.label(text=f"✓ {cp_name}", icon="CHECKMARK")
            op = row.operator("og.clear_door_cp", text="", icon="X")
            op.actor_name = sel.name
        else:
            sub = box.row(); sub.enabled = False
            sub.label(text="Not set — door won't set a continue point", icon="INFO")

        if all_cps:
            box.label(text="Set from scene checkpoints/spawns:")
            col = box.column(align=True)
            for (cp_obj, name) in all_cps:
                row2 = col.row(align=True)
                is_active = (name == cp_name)
                icon = "CHECKMARK" if is_active else "DOT"
                op = row2.operator("og.set_door_cp", text=name, icon=icon)
                op.actor_name = sel.name
                op.cp_name = name
        else:
            sub = box.row(); sub.enabled = False
            sub.label(text="No checkpoints in scene — add a CHECKPOINT_ empty", icon="INFO")


class OG_PT_ActorSunIrisDoor(Panel):
    bl_label       = "Iris Door Settings"
    bl_idname      = "OG_PT_actor_sun_iris_door"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "sun-iris-door"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # ── Open method ───────────────────────────────────────────────────────
        hint = layout.box()
        hint.label(text="Opens when it receives a 'trigger event", icon="INFO")
        sub = hint.row(); sub.enabled = False
        sub.label(text="Use a Trigger Volume or basebutton linked to this door")

        # ── Proximity toggle ──────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Proximity", icon="DRIVER_DISTANCE")
        proximity = bool(sel.get("og_door_proximity", False))
        row = box.row()
        icon = "CHECKBOX_HLT" if proximity else "CHECKBOX_DEHLT"
        row.operator("og.toggle_door_flag", text="Open by Proximity", icon=icon).flag = "proximity"
        sub2 = box.row(); sub2.enabled = False
        if proximity:
            sub2.label(text="Also opens when Jak walks close", icon="CHECKMARK")
        else:
            sub2.label(text="Event-triggered only (default)", icon="INFO")

        # ── Timeout ───────────────────────────────────────────────────────────
        box2 = layout.box()
        box2.label(text="Auto-Close Timeout", icon="TIME")
        timeout = float(sel.get("og_door_timeout", 0.0))
        row2 = box2.row(align=True)
        op_m = row2.operator("og.nudge_float_prop", text="-1s", icon="REMOVE")
        op_m.prop_name = "og_door_timeout"; op_m.delta = -1.0; op_m.val_min = 0.0
        if timeout <= 0.0:
            row2.label(text="No timeout (stays open)")
        else:
            row2.label(text=f"Closes after {timeout:.1f}s")
        op_p = row2.operator("og.nudge_float_prop", text="+1s", icon="ADD")
        op_p.prop_name = "og_door_timeout"; op_p.delta = 1.0; op_p.val_max = 60.0
        if timeout > 0.0:
            op_r = box2.operator("og.nudge_float_prop", text="Reset (no timeout)", icon="LOOP_BACK")
            op_r.prop_name = "og_door_timeout"; op_r.delta = -999.0; op_r.val_min = 0.0


class OG_PT_ActorBaseButton(Panel):
    bl_label       = "Button Settings"
    bl_idname      = "OG_PT_actor_basebutton"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "basebutton"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # ── Info ──────────────────────────────────────────────────────────────
        hint = layout.box()
        hint.label(text="Flop-attack (ground pound) to press", icon="INFO")
        sub = hint.column(align=True); sub.enabled = False
        sub.label(text="To control an Eco Door:")
        sub.label(text="  Select the door → Actor Links → state-actor → this button")
        sub.label(text="The door locks until this button is pressed.")

        # ── Timeout ───────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Reset Timeout", icon="TIME")
        timeout = float(sel.get("og_button_timeout", 0.0))
        row = box.row(align=True)
        op_m = row.operator("og.nudge_float_prop", text="-1s", icon="REMOVE")
        op_m.prop_name = "og_button_timeout"; op_m.delta = -1.0; op_m.val_min = 0.0
        if timeout <= 0.0:
            row.label(text="Stays pressed permanently")
        else:
            row.label(text=f"Resets after {timeout:.1f}s")
        op_p = row.operator("og.nudge_float_prop", text="+1s", icon="ADD")
        op_p.prop_name = "og_button_timeout"; op_p.delta = 1.0; op_p.val_max = 60.0
        if timeout > 0.0:
            op_r = box.operator("og.nudge_float_prop", text="Reset (permanent)", icon="LOOP_BACK")
            op_r.prop_name = "og_button_timeout"; op_r.delta = -999.0; op_r.val_min = 0.0



class OG_PT_ActorPlatFlip(Panel):
    bl_label       = "Flip Platform Settings"
    bl_idname      = "OG_PT_actor_plat_flip"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "plat-flip"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        box = layout.box()
        box.label(text="Flip Timing", icon="TIME")

        delay_down = float(sel.get("og_flip_delay_down", 2.0))
        delay_up   = float(sel.get("og_flip_delay_up",   2.0))

        col = box.column(align=True)
        for label, prop, val in [
            ("Delay down (s):", "og_flip_delay_down", delay_down),
            ("Delay up   (s):", "og_flip_delay_up",   delay_up),
        ]:
            row = col.row(align=True)
            row.label(text=label)
            op = row.operator("og.nudge_float_prop", text="-0.5", icon="REMOVE")
            op.prop_name = prop; op.delta = -0.5; op.val_min = 0.1
            row.label(text=f"{val:.1f}s")
            op = row.operator("og.nudge_float_prop", text="+0.5", icon="ADD")
            op.prop_name = prop; op.delta = 0.5; op.val_max = 30.0

        sub = box.row(); sub.enabled = False
        sub.label(text="Time before flipping down / recovering up", icon="INFO")

        # Sync percent — phase offset so multiple flip platforms don't sync
        box2 = layout.box()
        box2.label(text="Phase Offset", icon="TIME")
        sync_pct = float(sel.get("og_flip_sync_pct", 0.0))
        row = box2.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-0.1", icon="REMOVE")
        op.prop_name = "og_flip_sync_pct"; op.delta = -0.1; op.val_min = 0.0
        row.label(text=f"{sync_pct:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.1", icon="ADD")
        op.prop_name = "og_flip_sync_pct"; op.delta = 0.1; op.val_max = 1.0
        sub2 = box2.row(); sub2.enabled = False
        sub2.label(text="0.0–1.0. Staggers multiple flip platforms.", icon="INFO")


class OG_PT_ActorOrbCache(Panel):
    bl_label       = "Orb Cache Settings"
    bl_idname      = "OG_PT_actor_orb_cache"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "orb-cache-top"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        box = layout.box()
        box.label(text="Orb Count", icon="SPHERE")
        count = int(sel.get("og_orb_count", 20))
        row = box.row(align=True)
        op = row.operator("og.nudge_int_prop", text="-5", icon="REMOVE")
        op.prop_name = "og_orb_count"; op.delta = -5; op.val_min = 1
        row.label(text=f"{count} orbs")
        op = row.operator("og.nudge_int_prop", text="+5", icon="ADD")
        op.prop_name = "og_orb_count"; op.delta = 5; op.val_max = 200
        sub = box.row(); sub.enabled = False
        sub.label(text="Default 20. Orbs release when cache is opened.", icon="INFO")


class OG_PT_ActorWhirlpool(Panel):
    bl_label       = "Whirlpool Settings"
    bl_idname      = "OG_PT_actor_whirlpool"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "whirlpool"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        box = layout.box()
        box.label(text="Rotation Speed", icon="FORCE_VORTEX")
        speed     = float(sel.get("og_whirl_speed", 0.3))
        variation = float(sel.get("og_whirl_var",   0.1))
        col = box.column(align=True)
        for label, prop, val in [
            ("Base speed:", "og_whirl_speed", speed),
            ("Variation:", "og_whirl_var",   variation),
        ]:
            row = col.row(align=True)
            row.label(text=label)
            op = row.operator("og.nudge_float_prop", text="-0.05", icon="REMOVE")
            op.prop_name = prop; op.delta = -0.05; op.val_min = 0.0
            row.label(text=f"{val:.2f}")
            op = row.operator("og.nudge_float_prop", text="+0.05", icon="ADD")
            op.prop_name = prop; op.delta = 0.05; op.val_max = 5.0
        sub = box.row(); sub.enabled = False
        sub.label(text="Internal units. Default ~0.3 / 0.1.", icon="INFO")


_ROPEBRIDGE_VARIANTS = [
    ("ropebridge-32",  "Rope Bridge 32m"),
    ("ropebridge-36",  "Rope Bridge 36m"),
    ("ropebridge-52",  "Rope Bridge 52m"),
    ("ropebridge-70",  "Rope Bridge 70m"),
    ("snow-bridge-36", "Snow Bridge 36m"),
    ("vil3-bridge-36", "Village3 Bridge 36m"),
]

class OG_PT_ActorRopeBridge(Panel):
    bl_label       = "Rope Bridge Settings"
    bl_idname      = "OG_PT_actor_ropebridge"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "ropebridge"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        cur    = sel.get("og_bridge_variant", "ropebridge-32")
        box    = layout.box()
        box.label(text="Bridge Variant (art-name)", icon="CURVE_PATH")
        col = box.column(align=True)
        for (val, label) in _ROPEBRIDGE_VARIANTS:
            row = col.row(align=True)
            icon = "RADIOBUT_ON" if cur == val else "RADIOBUT_OFF"
            op = row.operator("og.set_bridge_variant", text=label, icon=icon)
            op.variant = val


class OG_PT_ActorOrbitPlat(Panel):
    bl_label       = "Orbit Platform Settings"
    bl_idname      = "OG_PT_actor_orbit_plat"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "orbit-plat"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        scale   = float(sel.get("og_orbit_scale",   1.0))
        timeout = float(sel.get("og_orbit_timeout", 10.0))
        box = layout.box()
        box.label(text="Orbit Settings", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        col = box.column(align=True)
        for (lbl, prop, val, d, mn, mx) in [
            ("Scale:",   "og_orbit_scale",   scale,   0.1, 0.1, 10.0),
            ("Timeout:", "og_orbit_timeout", timeout, 1.0, 0.0, 60.0),
        ]:
            row = col.row(align=True)
            row.label(text=lbl)
            op = row.operator("og.nudge_float_prop", text=f"-{d}", icon="REMOVE")
            op.prop_name = prop; op.delta = -d; op.val_min = mn
            row.label(text=f"{val:.1f}")
            op = row.operator("og.nudge_float_prop", text=f"+{d}", icon="ADD")
            op.prop_name = prop; op.delta = d; op.val_max = mx
        sub = box.row(); sub.enabled = False
        sub.label(text="Requires Entity Link → center actor", icon="INFO")


class OG_PT_ActorSquarePlatform(Panel):
    bl_label       = "Square Platform Settings"
    bl_idname      = "OG_PT_actor_square_plat"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "square-platform"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        down_m = float(sel.get("og_sq_down", -2.0))
        up_m   = float(sel.get("og_sq_up",    4.0))
        box = layout.box()
        box.label(text="Travel Range", icon="MOVE_DOWN_VEC")
        col = box.column(align=True)
        for (lbl, prop, val) in [
            ("Down (m):", "og_sq_down", down_m),
            ("Up   (m):", "og_sq_up",   up_m),
        ]:
            row = col.row(align=True)
            row.label(text=lbl)
            op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
            op.prop_name = prop; op.delta = -0.5; op.val_min = -20.0
            row.label(text=f"{val:.1f}m")
            op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
            op.prop_name = prop; op.delta = 0.5; op.val_max = 20.0
        sub = box.row(); sub.enabled = False
        sub.label(text="Default: 2m down, 4m up", icon="INFO")


class OG_PT_ActorCaveFlamePots(Panel):
    bl_label       = "Flame Pots Settings"
    bl_idname      = "OG_PT_actor_caveflamepots"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "caveflamepots"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        shove    = float(sel.get("og_flame_shove",   2.0))
        period   = float(sel.get("og_flame_period",  4.0))
        phase    = float(sel.get("og_flame_phase",   0.0))
        pause    = float(sel.get("og_flame_pause",   2.0))

        box = layout.box()
        box.label(text="Launch Force", icon="TRIA_UP")
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
        op.prop_name = "og_flame_shove"; op.delta = -0.5; op.val_min = 0.0
        row.label(text=f"{shove:.1f}m")
        op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
        op.prop_name = "og_flame_shove"; op.delta = 0.5; op.val_max = 20.0

        box2 = layout.box()
        box2.label(text="Cycle Timing", icon="TIME")
        col = box2.column(align=True)
        for (lbl, prop, val, d) in [
            ("Period (s):", "og_flame_period", period, 0.5),
            ("Phase:",      "og_flame_phase",  phase,  0.1),
            ("Pause  (s):", "og_flame_pause",  pause,  0.5),
        ]:
            row = col.row(align=True)
            row.label(text=lbl)
            op = row.operator("og.nudge_float_prop", text=f"-{d}", icon="REMOVE")
            op.prop_name = prop; op.delta = -d; op.val_min = 0.0
            row.label(text=f"{val:.2f}")
            op = row.operator("og.nudge_float_prop", text=f"+{d}", icon="ADD")
            op.prop_name = prop; op.delta = d; op.val_max = 30.0
        sub = box2.row(); sub.enabled = False
        sub.label(text="Phase 0–1 staggers multiple pots", icon="INFO")


class OG_PT_ActorShover(Panel):
    bl_label       = "Shover Settings"
    bl_idname      = "OG_PT_actor_shover"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "shover"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        shove  = float(sel.get("og_shover_force",  3.0))
        rot    = float(sel.get("og_shover_rot",    0.0))
        box = layout.box()
        box.label(text="Shove Force", icon="TRIA_UP")
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
        op.prop_name = "og_shover_force"; op.delta = -0.5; op.val_min = 0.0
        row.label(text=f"{shove:.1f}m")
        op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
        op.prop_name = "og_shover_force"; op.delta = 0.5; op.val_max = 30.0

        box2 = layout.box()
        box2.label(text="Rotation Offset", icon="CON_ROTLIKE")
        row2 = box2.row(align=True)
        op = row2.operator("og.nudge_float_prop", text="-15°", icon="REMOVE")
        op.prop_name = "og_shover_rot"; op.delta = -15.0; op.val_min = -360.0
        row2.label(text=f"{rot:.0f}°")
        op = row2.operator("og.nudge_float_prop", text="+15°", icon="ADD")
        op.prop_name = "og_shover_rot"; op.delta = 15.0; op.val_max = 360.0


class OG_PT_ActorLavaMoving(Panel):
    bl_label       = "Movement Settings"
    bl_idname      = "OG_PT_actor_lava_moving"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    _TYPES = {"lavaballoon", "darkecobarrel"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] in cls._TYPES

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        etype  = sel.name.split("_", 2)[1]
        speed  = float(sel.get("og_move_speed", 3.0 if etype == "lavaballoon" else 15.0))

        box = layout.box()
        box.label(text="Speed", icon="DRIVER_DISTANCE")
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-1m/s", icon="REMOVE")
        op.prop_name = "og_move_speed"; op.delta = -1.0; op.val_min = 0.1
        row.label(text=f"{speed:.1f}m/s")
        op = row.operator("og.nudge_float_prop", text="+1m/s", icon="ADD")
        op.prop_name = "og_move_speed"; op.delta = 1.0; op.val_max = 60.0
        sub = box.row(); sub.enabled = False
        default = "~3m/s" if etype == "lavaballoon" else "~15m/s"
        sub.label(text=f"Default {default}. Needs waypoints.", icon="INFO")


class OG_PT_ActorWindTurbine(Panel):
    bl_label       = "Wind Turbine Settings"
    bl_idname      = "OG_PT_actor_windturbine"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "windturbine"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        particles = bool(sel.get("og_turbine_particles", False))
        box = layout.box()
        box.label(text="Particle Effects", icon="PARTICLES")
        icon = "CHECKBOX_HLT" if particles else "CHECKBOX_DEHLT"
        box.operator("og.toggle_turbine_particles", text="Enable Particles", icon=icon)
        sub = box.row(); sub.enabled = False
        sub.label(text="Default off. Adds wind particle effects.", icon="INFO")


class OG_PT_ActorCaveElevator(Panel):
    bl_label       = "Cave Elevator Settings"
    bl_idname      = "OG_PT_actor_cave_elevator"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "caveelevator"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        mode   = int(sel.get("og_elevator_mode", 0))
        rot    = float(sel.get("og_elevator_rot", 0.0))

        box = layout.box()
        box.label(text="Mode", icon="SETTINGS")
        col = box.column(align=True)
        for (val, label) in [(0, "Mode 0 (default)"), (1, "Mode 1 (alternate)")]:
            row = col.row()
            icon = "RADIOBUT_ON" if mode == val else "RADIOBUT_OFF"
            op = row.operator("og.set_elevator_mode", text=label, icon=icon)
            op.mode_val = val

        box2 = layout.box()
        box2.label(text="Rotation Offset", icon="CON_ROTLIKE")
        row2 = box2.row(align=True)
        op = row2.operator("og.nudge_float_prop", text="-15°", icon="REMOVE")
        op.prop_name = "og_elevator_rot"; op.delta = -15.0; op.val_min = -360.0
        row2.label(text=f"{rot:.0f}°")
        op = row2.operator("og.nudge_float_prop", text="+15°", icon="ADD")
        op.prop_name = "og_elevator_rot"; op.delta = 15.0; op.val_max = 360.0


class OG_PT_ActorMisBoneBridge(Panel):
    bl_label       = "Bone Bridge Settings"
    bl_idname      = "OG_PT_actor_mis_bone_bridge"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "mis-bone-bridge"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        anim   = int(sel.get("og_bone_bridge_anim", 0))

        box = layout.box()
        box.label(text="Animation Variant", icon="ARMATURE_DATA")
        col = box.column(align=True)
        for (val, label) in [
            (0, "0 — No particles (default)"),
            (1, "1 — Variant A"),
            (2, "2 — Variant B"),
            (3, "3 — Variant C"),
            (7, "7 — Variant D"),
        ]:
            row = col.row()
            icon = "RADIOBUT_ON" if anim == val else "RADIOBUT_OFF"
            op = row.operator("og.set_bone_bridge_anim", text=label, icon=icon)
            op.anim_val = val


class OG_PT_ActorBreakaway(Panel):
    bl_label       = "Breakaway Settings"
    bl_idname      = "OG_PT_actor_breakaway"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    _TYPES = {"breakaway-left", "breakaway-mid", "breakaway-right"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] in cls._TYPES

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        h1 = float(sel.get("og_breakaway_h1", 0.0))
        h2 = float(sel.get("og_breakaway_h2", 0.0))

        box = layout.box()
        box.label(text="Fall Height Offsets", icon="MOVE_DOWN_VEC")
        col = box.column(align=True)
        for (lbl, prop, val) in [
            ("H1:", "og_breakaway_h1", h1),
            ("H2:", "og_breakaway_h2", h2),
        ]:
            row = col.row(align=True)
            row.label(text=lbl)
            op = row.operator("og.nudge_float_prop", text="-0.5", icon="REMOVE")
            op.prop_name = prop; op.delta = -0.5; op.val_min = -20.0
            row.label(text=f"{val:.1f}")
            op = row.operator("og.nudge_float_prop", text="+0.5", icon="ADD")
            op.prop_name = prop; op.delta = 0.5; op.val_max = 20.0
        sub = box.row(); sub.enabled = False
        sub.label(text="Controls breakaway platform fall animation heights", icon="INFO")


class OG_PT_ActorSunkenFish(Panel):
    bl_label       = "Sunken Fish Settings"
    bl_idname      = "OG_PT_actor_sunkenfisha"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "sunkenfisha"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        count  = int(sel.get("og_fish_count", 1))
        box = layout.box()
        box.label(text="School Size", icon="COMMUNITY")
        row = box.row(align=True)
        op = row.operator("og.nudge_int_prop", text="-1", icon="REMOVE")
        op.prop_name = "og_fish_count"; op.delta = -1; op.val_min = 1
        row.label(text=f"{count} fish")
        op = row.operator("og.nudge_int_prop", text="+1", icon="ADD")
        op.prop_name = "og_fish_count"; op.delta = 1; op.val_max = 16
        sub = box.row(); sub.enabled = False
        sub.label(text="Spawns count−1 extra child fish. Default 1.", icon="INFO")


class OG_PT_ActorSharkey(Panel):
    bl_label       = "Sharkey Settings"
    bl_idname      = "OG_PT_actor_sharkey"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "sharkey"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        scale    = float(sel.get("og_shark_scale",    1.0))
        delay    = float(sel.get("og_shark_delay",    1.0))
        distance = float(sel.get("og_shark_distance", 30.0))
        speed    = float(sel.get("og_shark_speed",    12.0))

        box = layout.box()
        box.label(text="Shark Properties", icon="FORCE_FORCE")
        col = box.column(align=True)
        for (lbl, prop, val, d, mn, mx) in [
            ("Scale:",    "og_shark_scale",    scale,    0.1,  0.1, 5.0),
            ("Delay (s):", "og_shark_delay",   delay,    0.5,  0.0, 30.0),
            ("Range (m):", "og_shark_distance",distance, 5.0,  5.0, 200.0),
            ("Speed (m/s):", "og_shark_speed", speed,    1.0,  1.0, 50.0),
        ]:
            row = col.row(align=True)
            row.label(text=lbl)
            op = row.operator("og.nudge_float_prop", text=f"-{d}", icon="REMOVE")
            op.prop_name = prop; op.delta = -d; op.val_min = mn
            row.label(text=f"{val:.1f}")
            op = row.operator("og.nudge_float_prop", text=f"+{d}", icon="ADD")
            op.prop_name = prop; op.delta = d; op.val_max = mx

        sub = box.row(); sub.enabled = False
        sub.label(text="Needs water-height set via lump panel", icon="INFO")


_GAME_TASKS_COMMON = [
    ("none",                    "None"),
    ("jungle-eggtop",           "Jungle: Egg Top"),
    ("jungle-lurkercage",       "Jungle: Lurker Cage"),
    ("jungle-plant",            "Jungle: Plant Boss"),
    ("village1-yakow",          "Village: Yakow"),
    ("village1-mayor-money",    "Village: Mayor Orbs"),
    ("village1-uncle-money",    "Village: Uncle Orbs"),
    ("village1-oracle-money1",  "Village: Oracle 1"),
    ("village1-oracle-money2",  "Village: Oracle 2"),
    ("beach-ecorocks",          "Beach: Eco Rocks"),
    ("beach-volcanoes",         "Beach: Volcanoes"),
    ("beach-cannon",            "Beach: Cannon"),
    ("beach-buzzer",            "Beach: Scout Flies"),
    ("misty-muse",              "Misty: Muse"),
    ("misty-cannon",            "Misty: Cannon"),
    ("misty-bike",              "Misty: Bike"),
    ("misty-buzzer",            "Misty: Scout Flies"),
    ("swamp-billy",             "Swamp: Billy"),
    ("swamp-flutflut",          "Swamp: Flut Flut"),
    ("swamp-buzzer",            "Swamp: Scout Flies"),
    ("sunken-platforms",        "Sunken: Platforms"),
    ("sunken-pipe",             "Sunken: Pipe"),
    ("snow-zorbing",            "Snow: Zorbing"),
    ("snow-fort",               "Snow: Fort"),
    ("snow-buzzer",             "Snow: Scout Flies"),
    ("firecanyon-buzzer",       "Fire Canyon: Scout Flies"),
    ("ogre-boss",               "Ogre: Boss"),
    ("ogre-buzzer",             "Ogre: Scout Flies"),
    ("maincave-gnawers",        "Maincave: Gnawers"),
    ("maincave-darkecobarrel",  "Maincave: Dark Eco Barrel"),
    ("robocave-robot",          "Robocave: Robot"),
]


class OG_PT_ActorTaskGated(Panel):
    bl_label       = "Task Settings"
    bl_idname      = "OG_PT_actor_task_gated"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    _TYPES = {"oracle", "pontoon"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] in cls._TYPES

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        etype  = sel.name.split("_", 2)[1]
        cur    = sel.get("og_alt_task", "none")

        box = layout.box()
        if etype == "oracle":
            box.label(text="Second Orb Task (alt-task)", icon="SPHERE")
            sub = box.row(); sub.enabled = False
            sub.label(text="Set if oracle requires 2 orbs", icon="INFO")
        else:
            box.label(text="Sink Condition Task (alt-task)", icon="FORCE_FORCE")
            sub = box.row(); sub.enabled = False
            sub.label(text="Pontoon sinks when this task is complete", icon="INFO")

        col = box.column(align=True)
        for (val, label) in _GAME_TASKS_COMMON:
            row = col.row()
            icon = "RADIOBUT_ON" if cur == val else "RADIOBUT_OFF"
            op = row.operator("og.set_alt_task", text=label, icon=icon)
            op.task_name = val


class OG_PT_ActorVisibility(Panel):
    bl_label       = "Visibility"
    bl_idname      = "OG_PT_actor_visibility"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        if len(parts) < 3 or parts[0] != "ACTOR": return False
        return _actor_is_enemy(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        box = layout.box()
        box.label(text="Vis Distance", icon="HIDE_OFF")
        vis = float(sel.get("og_vis_dist", 200.0))
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-25m", icon="REMOVE")
        op.prop_name = "og_vis_dist"; op.delta = -25.0; op.val_min = 10.0
        row.label(text=f"{vis:.0f}m")
        op = row.operator("og.nudge_float_prop", text="+25m", icon="ADD")
        op.prop_name = "og_vis_dist"; op.delta = 25.0; op.val_max = 500.0
        sub = box.row(); sub.enabled = False
        sub.label(text="Default 200m. Reduce for distant background enemies.", icon="INFO")


class OG_PT_ActorWaypoints(Panel):
    bl_label       = "Waypoints"
    bl_idname      = "OG_PT_actor_waypoints"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or "_wp_" in sel.name: return False
        parts = sel.name.split("_", 2)
        return (len(parts) >= 3 and parts[0] == "ACTOR"
                and _actor_uses_waypoints(parts[1]))

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        scene  = ctx.scene
        parts  = sel.name.split("_", 2)
        etype  = parts[1]
        einfo  = ENTITY_DEFS.get(etype, {})

        prefix = sel.name + "_wp_"
        wps = sorted(
            [o for o in _level_objects(scene) if o.name.startswith(prefix) and o.type == "EMPTY"],
            key=lambda o: o.name
        )
        layout.label(text=f"Path  ({len(wps)} point{'s' if len(wps) != 1 else ''})", icon="ANIM")
        if wps:
            col = layout.column(align=True)
            for wp in wps:
                row = col.row(align=True)
                row.label(text=wp.name, icon="EMPTY_AXIS")
                op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM"); op.obj_name = wp.name
                op = row.operator("og.delete_waypoint",  text="", icon="X");        op.wp_name  = wp.name
        op = layout.operator("og.add_waypoint", text="Add Waypoint at Cursor", icon="PLUS")
        op.enemy_name = sel.name; op.pathb_mode = False
        if einfo.get("needs_path") and len(wps) < 1:
            layout.label(text="⚠ Needs ≥ 1 waypoint or will crash", icon="ERROR")

        if einfo.get("needs_pathb"):
            layout.separator(factor=0.5)
            prefixb = sel.name + "_wpb_"
            wpsb = sorted(
                [o for o in _level_objects(scene) if o.name.startswith(prefixb) and o.type == "EMPTY"],
                key=lambda o: o.name
            )
            layout.label(text=f"Path B  ({len(wpsb)} points)", icon="ANIM")
            if wpsb:
                col2 = layout.column(align=True)
                for wp in wpsb:
                    row = col2.row(align=True)
                    row.label(text=wp.name, icon="EMPTY_AXIS")
                    op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM"); op.obj_name = wp.name
                    op = row.operator("og.delete_waypoint",  text="", icon="X");        op.wp_name  = wp.name
            op = layout.operator("og.add_waypoint", text="Add Path B Waypoint", icon="PLUS")
            op.enemy_name = sel.name; op.pathb_mode = True
            if len(wpsb) < 1:
                layout.label(text="⚠ swamp-bat crashes without Path B", icon="ERROR")


# ── SPAWN sub-panel ─────────────────────────────────────────────────────────

class OG_PT_SpawnSettings(Panel):
    bl_label       = "Spawn Settings"
    bl_idname      = "OG_PT_spawn_settings"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.name.startswith("SPAWN_")
                and not sel.name.endswith("_CAM"))

    def draw(self, ctx):
        _draw_selected_spawn(self.layout, ctx.active_object, ctx.scene)


# ── CHECKPOINT sub-panel ────────────────────────────────────────────────────

class OG_PT_CheckpointSettings(Panel):
    bl_label       = "Checkpoint Settings"
    bl_idname      = "OG_PT_checkpoint_settings"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.name.startswith("CHECKPOINT_")
                and not sel.name.endswith("_CAM"))

    def draw(self, ctx):
        _draw_selected_checkpoint(self.layout, ctx.active_object, ctx.scene)


# ── AMBIENT sub-panel ───────────────────────────────────────────────────────

class OG_PT_AmbientEmitter(Panel):
    bl_label       = "Sound Emitter"
    bl_idname      = "OG_PT_ambient_emitter"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel is not None and sel.name.startswith("AMBIENT_")

    def draw(self, ctx):
        _draw_selected_emitter(self.layout, ctx.active_object)


# ── CAMERA sub-panels ───────────────────────────────────────────────────────

class OG_PT_CameraSettings(Panel):
    bl_label       = "Camera Settings"
    bl_idname      = "OG_PT_camera_settings"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.name.startswith("CAMERA_")
                and sel.type == "CAMERA")

    def draw(self, ctx):
        _draw_selected_camera(self.layout, ctx.active_object, ctx.scene)


class OG_PT_CamAnchorInfo(Panel):
    bl_label       = "Anchor Info"
    bl_idname      = "OG_PT_cam_anchor_info"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel is not None and sel.name.endswith("_CAM")

    def draw(self, ctx):
        _draw_selected_cam_anchor(self.layout, ctx.active_object, ctx.scene)


# ── VOLUME sub-panel ────────────────────────────────────────────────────────

class OG_PT_VolumeLinks(Panel):
    bl_label       = "Volume Links"
    bl_idname      = "OG_PT_volume_links"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return sel is not None and sel.name.startswith("VOL_")

    def draw(self, ctx):
        _draw_selected_volume(self.layout, ctx.active_object, ctx.scene)


# ── NAVMESH INFO sub-panel ──────────────────────────────────────────────────

class OG_PT_NavmeshInfo(Panel):
    bl_label       = "Navmesh Info"
    bl_idname      = "OG_PT_navmesh_info"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.type == "MESH"
                and (sel.get("og_navmesh") or sel.name.startswith("NAVMESH_")))

    def draw(self, ctx):
        _draw_selected_navmesh(self.layout, ctx.active_object)


# ===========================================================================
# LUMP SUB-PANEL (actor empties only)
# ===========================================================================

def _draw_lump_panel(layout, obj):
    """Draw the Custom Lumps assisted-entry list for an ACTOR_ empty."""
    rows   = obj.og_lump_rows
    index  = obj.og_lump_rows_index

    # Column header labels
    hdr = layout.row(align=True)
    hdr.label(text="Key")
    hdr.label(text="Type")
    hdr.label(text="Value")

    # Scrollable UIList  — 5 rows visible, expandable
    layout.template_list(
        "OG_UL_LumpRows", "",
        obj, "og_lump_rows",
        obj, "og_lump_rows_index",
        rows=5,
    )

    # Add / Remove buttons
    row = layout.row(align=True)
    row.operator("og.add_lump_row",    text="Add",    icon="ADD")
    row.operator("og.remove_lump_row", text="Remove", icon="REMOVE")

    # Inline error detail for the currently selected row
    if rows and 0 <= index < len(rows):
        item = rows[index]
        _, err = _parse_lump_row(item.key, item.ltype, item.value)
        if err:
            box = layout.box()
            box.label(text=f"⚠ Row {index+1}: {err}", icon="ERROR")
        elif item.key.strip() in _LUMP_HARDCODED_KEYS:
            box = layout.box()
            box.label(text=f"'{item.key}' overrides addon default", icon="INFO")

    if not rows:
        sub = layout.row()
        sub.enabled = False
        sub.label(text="No custom lumps — click Add to start", icon="INFO")


class OG_PT_SelectedLumps(Panel):
    bl_label       = "Custom Lumps"
    bl_idname      = "OG_PT_selected_lumps"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.name.startswith("ACTOR_")
                and "_wp_" not in sel.name)

    def draw(self, ctx):
        _draw_lump_panel(self.layout, ctx.active_object)


# ===========================================================================
# LUMP REFERENCE SUB-PANEL
# ===========================================================================

class OG_OT_UseLumpRef(bpy.types.Operator):
    """Add a new lump row pre-filled with this reference entry's key and type."""
    bl_idname  = "og.use_lump_ref"
    bl_label   = "Use This"
    bl_options = {"REGISTER", "UNDO"}

    lump_key:   bpy.props.StringProperty()
    lump_ltype: bpy.props.StringProperty()

    def execute(self, ctx):
        obj = ctx.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object"); return {"CANCELLED"}
        row = obj.og_lump_rows.add()
        row.key   = self.lump_key
        row.ltype = self.lump_ltype
        obj.og_lump_rows_index = len(obj.og_lump_rows) - 1
        return {"FINISHED"}


def _draw_lump_ref_section(layout, title, entries, icon="DOT"):
    """Draw a collapsible read-only reference section."""
    if not entries:
        return
    box = layout.box()
    box.label(text=title, icon=icon)
    col = box.column(align=True)
    for key, ltype, desc in entries:
        row = col.row(align=True)
        row.label(text=key, icon="KEYFRAME")
        sub = row.row(align=True)
        sub.enabled = False
        sub.label(text=ltype)
        op = row.operator("og.use_lump_ref", text="", icon="ADD")
        op.lump_key   = key
        op.lump_ltype = ltype
        # Description as a greyed-out label on the next line
        desc_row = col.row()
        desc_row.enabled = False
        desc_row.label(text=f"  {desc}")
        col.separator(factor=0.3)


class OG_PT_SelectedLumpReference(Panel):
    bl_label       = "Lump Reference"
    bl_idname      = "OG_PT_selected_lump_reference"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_selected_object"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.name.startswith("ACTOR_")
                and "_wp_" not in sel.name)

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        parts  = sel.name.split("_", 2)
        if len(parts) < 3:
            layout.label(text="Unknown actor type", icon="ERROR")
            return
        etype = parts[1]
        einfo = ENTITY_DEFS.get(etype, {})
        label = einfo.get("label", etype)

        universal, actor_specific = _lump_ref_for_etype(etype)

        layout.label(text=f"Available lumps for: {label}", icon="INFO")
        layout.label(text="Click + to add a pre-filled row to Custom Lumps")
        layout.separator(factor=0.4)

        _draw_lump_ref_section(layout, "Universal (all actors)", universal, icon="WORLD")
        if actor_specific:
            _draw_lump_ref_section(layout, f"Specific to {label}", actor_specific, icon="OBJECT_DATA")
        else:
            sub = layout.row()
            sub.enabled = False
            sub.label(text=f"No additional lumps documented for {label}", icon="INFO")


# ===========================================================================
# WAYPOINTS (context-sensitive, unchanged)
# ===========================================================================

class OG_PT_Waypoints(Panel):
    bl_label       = "〰  Waypoints"
    bl_idname      = "OG_PT_waypoints"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("ACTOR_") or "_wp_" in sel.name:
            return False
        parts = sel.name.split("_", 2)
        if len(parts) < 3:
            return False
        return _actor_uses_waypoints(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        etype  = sel.name.split("_", 2)[1]
        einfo  = ENTITY_DEFS.get(etype, {})

        prefix = sel.name + "_wp_"
        wps = sorted(
            [o for o in bpy.data.objects if o.name.startswith(prefix) and o.type == "EMPTY"],
            key=lambda o: o.name
        )

        layout.label(text=f"Path  ({len(wps)} point{'s' if len(wps) != 1 else ''})", icon="ANIM")

        if wps:
            col = layout.column(align=True)
            for wp in wps:
                row = col.row(align=True)
                row.label(text=wp.name, icon="EMPTY_AXIS")
                op = row.operator("og.delete_waypoint", text="", icon="X")
                op.wp_name = wp.name
        else:
            layout.label(text="No waypoints yet", icon="INFO")

        op = layout.operator("og.add_waypoint", text="Add Waypoint at Cursor", icon="PLUS")
        op.enemy_name = sel.name
        op.pathb_mode = False

        if einfo.get("needs_path") and len(wps) < 1:
            layout.label(text="⚠ Needs ≥ 1 waypoint or will crash", icon="ERROR")

        if einfo.get("needs_pathb"):
            _header_sep(layout)
            prefixb = sel.name + "_wpb_"
            wpsb = sorted(
                [o for o in bpy.data.objects if o.name.startswith(prefixb) and o.type == "EMPTY"],
                key=lambda o: o.name
            )
            layout.label(text=f"Path B — slave bats  ({len(wpsb)} points)", icon="ANIM")
            if wpsb:
                col2 = layout.column(align=True)
                for wp in wpsb:
                    row = col2.row(align=True)
                    row.label(text=wp.name, icon="EMPTY_AXIS")
                    op2 = row.operator("og.delete_waypoint", text="", icon="X")
                    op2.wp_name = wp.name
            else:
                layout.label(text="No Path B waypoints yet", icon="INFO")

            op3 = layout.operator("og.add_waypoint", text="Add Path B Waypoint at Cursor", icon="PLUS")
            op3.enemy_name = sel.name
            op3.pathb_mode = True

            if len(wpsb) < 1:
                layout.label(text="⚠ swamp-bat crashes without Path B", icon="ERROR")


# ===========================================================================
# TRIGGERS (always visible, unchanged)
# ===========================================================================

class OG_PT_Triggers(Panel):
    bl_label       = "🔗  Triggers"
    bl_idname      = "OG_PT_triggers"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        scene  = ctx.scene
        sel    = ctx.active_object

        layout.operator("og.spawn_volume", text="Add Trigger Volume", icon="MESH_CUBE")
        layout.separator(factor=0.3)

        sel_vols    = [o for o in ctx.selected_objects if o.type == "MESH" and o.name.startswith("VOL_")]
        sel_targets = [o for o in ctx.selected_objects if _is_linkable(o)]
        active_vol  = sel if (sel and sel.type == "MESH" and sel.name.startswith("VOL_")) else (sel_vols[0] if sel_vols else None)

        if active_vol:
            box = layout.box()
            box.label(text=active_vol.name, icon="MESH_CUBE")
            links = _vol_links(active_vol)
            box.label(text=f"{len(links)} link{'s' if len(links) != 1 else ''}", icon="LINKED")
            if sel_targets:
                tgt = sel_targets[0]
                if tgt == active_vol:
                    pass  # active is itself, ignore
                elif _vol_has_link_to(active_vol, tgt.name):
                    row = box.row()
                    row.alert = True
                    row.label(text=f"Already linked to {tgt.name}", icon="INFO")
                elif (not _is_aggro_target(tgt)
                        and _vol_for_target(scene, tgt.name) is not None
                        and _vol_for_target(scene, tgt.name) != active_vol):
                    existing = _vol_for_target(scene, tgt.name)
                    row = box.row()
                    row.alert = True
                    row.label(text=f"{tgt.name} already linked to {existing.name}", icon="ERROR")
                else:
                    op = box.operator("og.add_link_from_selection", text=f"Link → {tgt.name}", icon="LINKED")
                    op.vol_name    = active_vol.name
                    op.target_name = tgt.name
            else:
                box.label(text="Shift-select a target to link", icon="INFO")
            layout.separator(factor=0.3)
        elif sel_targets and not sel_vols:
            box = layout.box()
            box.label(text=f"{sel_targets[0].name} selected", icon="INFO")
            box.label(text="Also select a VOL_ to link", icon="INFO")
            layout.separator(factor=0.3)

        vols = sorted([o for o in _level_objects(scene)
                       if o.type == "MESH" and o.name.startswith("VOL_")],
                      key=lambda o: o.name)
        if not vols:
            box = layout.box()
            box.label(text="No trigger volumes in scene", icon="INFO")
            return

        row = layout.row()
        icon = "TRIA_DOWN" if ctx.scene.og_props.show_volume_list else "TRIA_RIGHT"
        row.prop(ctx.scene.og_props, "show_volume_list",
                 text=f"Volumes ({len(vols)})", icon=icon, emboss=False)
        if not ctx.scene.og_props.show_volume_list:
            return

        box = layout.box()
        for v in vols:
            row = box.row(align=True)
            v_links = _vol_links(v)
            link_count = len(v_links)
            if link_count == 0:
                row.alert = True
                row.label(text=v.name, icon="MESH_CUBE")
                row.label(text="unlinked")
            else:
                # Show first link target inline; count if multiple
                first = v_links[0]
                exists = bool(scene.objects.get(first.target_name))
                if not exists:
                    row.alert = True
                    row.label(text=v.name, icon="ERROR")
                    row.label(text=f"→ {first.target_name} (DELETED)")
                else:
                    row.label(text=v.name, icon="CHECKMARK")
                    if link_count == 1:
                        row.label(text=f"→ {first.target_name}")
                    else:
                        row.label(text=f"→ {first.target_name} +{link_count-1}")
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = v.name
            op = row.operator("og.delete_object", text="", icon="TRASH")
            op.obj_name = v.name

        # Orphan check: any vol with at least one link entry pointing to a missing target
        orphan_count = 0
        for o in vols:
            for entry in _vol_links(o):
                if not scene.objects.get(entry.target_name):
                    orphan_count += 1
        if orphan_count:
            layout.separator(factor=0.3)
            row = layout.row()
            row.alert = True
            row.operator("og.clean_orphaned_links", text=f"Clean {orphan_count} Orphaned Link(s)", icon="ERROR")


# ===========================================================================
# CAMERA (unchanged)
# ===========================================================================

class OG_PT_Camera(Panel):
    bl_label       = "📷  Cameras"
    bl_idname      = "OG_PT_camera"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_parent_id   = "OG_PT_spawn"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        scene  = ctx.scene
        sel    = ctx.active_object

        row = layout.row(align=True)
        row.operator("og.spawn_camera", text="Add Camera", icon="CAMERA_DATA")
        if sel and sel.type == "CAMERA" and sel.name.startswith("CAMERA_"):
            op = row.operator("og.spawn_volume_autolink", text="Add Volume", icon="CUBE")
            op.target_name = sel.name
        else:
            row.operator("og.spawn_volume", text="Add Volume", icon="CUBE")

        layout.separator()

        if sel and sel.type == "CAMERA" and sel.name.startswith("CAMERA_"):
            self._draw_camera_props(layout, sel, scene)
        elif sel and sel.type == "MESH" and sel.name.startswith("VOL_"):
            self._draw_volume_props(layout, sel, scene)

        layout.separator()

        cam_objects = sorted(
            [o for o in _level_objects(scene) if o.name.startswith("CAMERA_") and o.type == "CAMERA"],
            key=lambda o: o.name,
        )
        if not cam_objects:
            box = layout.box()
            box.label(text="No cameras placed yet", icon="INFO")
            return

        row = layout.row()
        icon = "TRIA_DOWN" if ctx.scene.og_props.show_camera_list else "TRIA_RIGHT"
        row.prop(ctx.scene.og_props, "show_camera_list",
                 text=f"Cameras ({len(cam_objects)})", icon=icon, emboss=False)
        if not ctx.scene.og_props.show_camera_list:
            return

        vol_map = {}
        for o in _level_objects(scene):
            if o.type == "MESH" and o.name.startswith("VOL_"):
                for entry in _vol_links(o):
                    if _classify_target(entry.target_name) == "camera":
                        vol_map.setdefault(entry.target_name, []).append(o.name)

        for cam_obj in cam_objects:
            box = layout.box()
            row = box.row(align=True)
            row.label(text=cam_obj.name, icon="CAMERA_DATA")
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = cam_obj.name
            op = row.operator("og.delete_object", text="", icon="TRASH")
            op.obj_name = cam_obj.name

            mode   = cam_obj.get("og_cam_mode",   "fixed")
            interp = float(cam_obj.get("og_cam_interp", 1.0))
            fov    = float(cam_obj.get("og_cam_fov",    0.0))

            mrow = box.row(align=True)
            mrow.label(text="Mode:")
            for m, lbl in (("fixed","Fixed"),("standoff","Side-Scroll"),("orbit","Orbit")):
                op = mrow.operator("og.set_cam_prop", text=lbl, depress=(mode == m))
                op.cam_name = cam_obj.name; op.prop_name = "og_cam_mode"; op.str_val = m

            brow = box.row(align=True)
            brow.label(text=f"Blend: {interp:.1f}s")
            op = brow.operator("og.nudge_cam_float", text="-"); op.cam_name=cam_obj.name; op.prop_name="og_cam_interp"; op.delta=-0.5
            op = brow.operator("og.nudge_cam_float", text="+"); op.cam_name=cam_obj.name; op.prop_name="og_cam_interp"; op.delta=0.5
            frow = box.row(align=True)
            frow.label(text=f"FOV: {'default' if fov<=0 else f'{fov:.0f}°'}")
            op = frow.operator("og.nudge_cam_float", text="-"); op.cam_name=cam_obj.name; op.prop_name="og_cam_fov"; op.delta=-5.0
            op = frow.operator("og.nudge_cam_float", text="+"); op.cam_name=cam_obj.name; op.prop_name="og_cam_fov"; op.delta=5.0

            if mode == "standoff":
                align_name = cam_obj.name + "_ALIGN"
                has_align = bool(scene.objects.get(align_name))
                arow = box.row()
                if has_align:
                    arow.label(text=f"Anchor: {align_name}", icon="CHECKMARK")
                else:
                    arow.label(text="No anchor", icon="ERROR")
                    arow.operator("og.spawn_cam_align", text="Add Anchor")
            elif mode == "orbit":
                pivot_name = cam_obj.name + "_PIVOT"
                has_pivot = bool(scene.objects.get(pivot_name))
                prow = box.row()
                if has_pivot:
                    prow.label(text=f"Pivot: {pivot_name}", icon="CHECKMARK")
                else:
                    prow.label(text="No pivot", icon="ERROR")
                    prow.operator("og.spawn_cam_pivot", text="Add Pivot")

            linked_vols = vol_map.get(cam_obj.name, [])
            vrow = box.row(align=True)
            if linked_vols:
                vrow.label(text=f"Trigger: {', '.join(linked_vols)}", icon="CHECKMARK")
                op = vrow.operator("og.spawn_volume_autolink", text="", icon="ADD")
                op.target_name = cam_obj.name
            else:
                vrow.label(text="No trigger — always active", icon="INFO")
                op = vrow.operator("og.spawn_volume_autolink", text="Add Volume", icon="ADD")
                op.target_name = cam_obj.name

    def _draw_camera_props(self, layout, cam, scene):
        box = layout.box()
        box.label(text=f"Selected: {cam.name}", icon="CAMERA_DATA")
        box.label(text="Numpad-0 to look through camera", icon="INFO")
        try:
            q = cam.matrix_world.to_quaternion()
            row = box.row()
            row.label(text=f"Rot (wxyz): {q.w:.2f} {q.x:.2f} {q.y:.2f} {q.z:.2f}")
            if abs(q.w) > 0.99:
                box.label(text="⚠ Camera has no rotation!", icon="ERROR")
                box.label(text="Rotate it to aim, then export.")
        except Exception:
            pass
        mode = cam.get("og_cam_mode", "fixed")
        if mode == "standoff" and not scene.objects.get(cam.name + "_ALIGN"):
            box.operator("og.spawn_cam_align", text="Add Player Anchor")
        if mode == "orbit" and not scene.objects.get(cam.name + "_PIVOT"):
            box.operator("og.spawn_cam_pivot", text="Add Orbit Pivot")
        look_at_name = cam.get("og_cam_look_at", "").strip()
        look_obj = scene.objects.get(look_at_name) if look_at_name else None
        lbox = layout.box()
        lrow = lbox.row()
        if look_obj:
            lrow.label(text=f"Look at: {look_at_name}", icon="CHECKMARK")
            lrow2 = lbox.row()
            op = lrow2.operator("og.set_cam_prop", text="Clear", icon="X")
            op.cam_name = cam.name; op.prop_name = "og_cam_look_at"; op.str_val = ""
            lbox.label(text="Camera ignores its rotation — aims at target", icon="INFO")
        else:
            lrow.label(text="No Look-At target  (uses camera rotation)", icon="DOT")
            lbox.operator("og.spawn_cam_look_at", text="Add Look-At Target", icon="PIVOT_CURSOR")

    def _draw_volume_props(self, layout, vol, scene):
        box = layout.box()
        box.label(text=f"Selected: {vol.name}", icon="MESH_CUBE")
        links = _vol_links(vol)
        if len(links) == 0:
            box.label(text="No links", icon="ERROR")
            box.label(text="Use Triggers panel to link", icon="INFO")
            return
        for entry in links:
            row = box.row(align=True)
            row.label(text=entry.target_name, icon="LINKED")
            if _classify_target(entry.target_name) == "enemy":
                row.prop(entry, "behaviour", text="")
            op = row.operator("og.remove_vol_link", text="", icon="X")
            op.vol_name    = vol.name
            op.target_name = entry.target_name


class OG_PT_BuildPlay(Panel):
    bl_label       = "▶  Build & Play"
    bl_idname      = "OG_PT_build_play"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"

    def draw(self, ctx):
        layout = self.layout
        gk_ok  = _gk().exists()
        gc_ok  = _goalc().exists()
        gp_ok  = _game_gp().exists()

        if not (gk_ok and gc_ok and gp_ok):
            box = layout.box()
            box.label(text="Missing paths — open Developer Tools", icon="ERROR")
            layout.separator(factor=0.3)

        col = layout.column(align=True)
        col.scale_y = 1.8
        col.operator("og.export_build",  text="⚙  Export & Compile",        icon="EXPORT")
        col.scale_y = 1.4
        col.operator("og.geo_rebuild",   text="🔄  Quick Geo Rebuild",       icon="FILE_REFRESH")
        col.scale_y = 1.8
        col.operator("og.play",          text="▶  Launch Game (Debug)",      icon="PLAY")



# ── Developer Tools ───────────────────────────────────────────────────────────

class OG_OT_ReloadAddon(Operator):
    """Hot-reload the OpenGOAL addon from disk — clears all Python module caches.
    Use this after updating the .py file instead of restarting Blender."""
    bl_idname = "og.reload_addon"
    bl_label  = "Reload Addon"
    bl_description = "Reload the OpenGOAL addon from disk without restarting Blender"

    def execute(self, ctx):
        import importlib, sys
        # Find our module name in sys.modules
        mod_name = None
        for name, mod in list(sys.modules.items()):
            if hasattr(mod, "__file__") and mod.__file__ and "opengoal_tools" in mod.__file__:
                mod_name = name
                break
        if mod_name is None:
            self.report({"ERROR"}, "Could not find opengoal_tools in sys.modules")
            return {"CANCELLED"}
        try:
            # Unregister current version
            unregister()
            # Force reload from disk — bypasses all caches
            mod = sys.modules[mod_name]
            importlib.reload(mod)
            # Re-register the freshly loaded version
            mod.register()
            self.report({"INFO"}, f"Reloaded {mod_name} from disk ✓")
        except Exception as e:
            self.report({"ERROR"}, f"Reload failed: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class OG_OT_CleanLevelFiles(Operator):
    """Delete generated files for the current level so the next build writes them fresh.
    Removes: obs.gc, .jsonc, .glb, .gd — forces a clean compile without stale cached data."""
    bl_idname = "og.clean_level_files"
    bl_label  = "Clean Level Files"
    bl_description = "Delete generated level files to force a clean rebuild (obs.gc, jsonc, glb, gd)"

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "No level name set")
            return {"CANCELLED"}

        deleted = []
        skipped = []

        # goal_src obs.gc — the one that causes stale compile errors
        obs_gc = _goal_src() / "levels" / name / f"{name}-obs.gc"
        # custom_assets files
        assets = _ldir(name)
        targets = [
            obs_gc,
            assets / f"{name}.jsonc",
            assets / f"{name}.glb",
            assets / f"{_nick(name)}.gd",
        ]

        for p in targets:
            if p.exists():
                p.unlink()
                deleted.append(p.name)
            else:
                skipped.append(p.name)

        if deleted:
            self.report({"INFO"}, f"Deleted: {', '.join(deleted)}" +
                        (f"  (not found: {', '.join(skipped)})" if skipped else ""))
        else:
            self.report({"WARNING"}, f"Nothing to delete — files not found for '{name}'")
        return {"FINISHED"}


class OG_PT_DevTools(Panel):
    bl_label       = "🔧  Developer Tools"
    bl_idname      = "OG_PT_dev_tools"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout

        # ── Reload / Clean ───────────────────────────────────────────────────
        row = layout.row()
        row.scale_y = 1.4
        row.operator("og.clean_level_files",  text="🗑  Clean Files",  icon="TRASH")
        layout.separator(factor=0.5)

        # Paths
        layout.label(text="Paths", icon="PREFERENCES")
        box = layout.box()
        gk_ok = _gk().exists()
        gc_ok = _goalc().exists()
        gp_ok = _game_gp().exists()
        box.label(text=f"gk{_EXE}:    {'✓ OK' if gk_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gk_ok else "ERROR")
        box.label(text=f"goalc{_EXE}: {'✓ OK' if gc_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gc_ok else "ERROR")
        box.label(text=f"game.gp:   {'✓ OK' if gp_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gp_ok else "ERROR")
        box.operator("preferences.addon_show", text="Set EXE / Data Paths", icon="PREFERENCES").module = __name__

        layout.separator()

        # Quick Open — nested here
        layout.label(text="Quick Open", icon="FILE_FOLDER")
        name = _lname(ctx)
        self._quick_open(layout, name)

    def _btn(self, layout, label, icon, path, is_file=False):
        p = Path(path) if path else None
        row = layout.row(align=True)
        row.enabled = bool(path)
        if is_file:
            op = row.operator("og.open_file",   text=label, icon=icon)
            op.filepath = str(p) if p else ""
        else:
            op = row.operator("og.open_folder", text=label, icon=icon)
            op.folder = str(p) if p else ""
        if p and not p.exists():
            row.label(text="", icon="ERROR")

    def _quick_open(self, layout, name):
        col = layout.column(align=True)
        self._btn(col, "goal_src/",    "FILE_FOLDER", str(_goal_src()) if _goal_src().parent.exists() else "")
        self._btn(col, "game.gp",      "FILE_SCRIPT", str(_game_gp()), is_file=True)
        self._btn(col, "level-info.gc","FILE_SCRIPT", str(_level_info()), is_file=True)
        self._btn(col, "entity.gc",    "FILE_SCRIPT", str(_entity_gc()), is_file=True)

        if name:
            layout.separator(factor=0.3)
            ldir       = _ldir(name)
            goal_level = _goal_src() / "levels" / name
            col2 = layout.column(align=True)
            self._btn(col2, f"{name}/",           "FILE_FOLDER", str(ldir))
            self._btn(col2, f"{name}.jsonc",      "FILE_TEXT",   str(ldir / f"{name}.jsonc"), is_file=True)
            self._btn(col2, f"{name}.glb",        "FILE_3D",     str(ldir / f"{name}.glb"),   is_file=True)
            self._btn(col2, f"{_nick(name)}.gd",  "FILE_SCRIPT", str(ldir / f"{_nick(name)}.gd"), is_file=True)
            self._btn(col2, f"{name}-obs.gc",     "FILE_SCRIPT", str(goal_level / f"{name}-obs.gc"), is_file=True)

        layout.separator(factor=0.3)
        col3 = layout.column(align=True)
        self._btn(col3, "custom_assets/", "FILE_FOLDER", str(_data() / "custom_assets" / "jak1" / "levels"))
        self._btn(col3, "Game logs",      "SCRIPT",      str(_data_root() / "data" / "log"))
        self._btn(col3, "startup.gc",     "FILE_SCRIPT", str(_user_dir() / "startup.gc"), is_file=True)


# ── Collision (per-object, separate panel) ────────────────────────────────────

class OG_PT_Collision(Panel):
    bl_label       = "Collision"
    bl_idname      = "OG_PT_collision"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx): return ctx.active_object is not None

    def draw(self, ctx):
        layout = self.layout
        ob     = ctx.active_object

        # Actor info summary
        if ob.name.startswith("ACTOR_") and "_wp_" not in ob.name:
            parts = ob.name.split("_", 2)
            if len(parts) >= 3:
                etype = parts[1]
                einfo = ENTITY_DEFS.get(etype, {})
                box = layout.box()
                box.label(text=f"{etype}", icon="OBJECT_DATA")
                box.label(text=f"AI: {einfo.get('ai_type', '?')}")
                nm = ob.get("og_navmesh_link", "")
                if nm:
                    box.label(text=f"NavMesh: {nm}", icon="LINKED")
                elif einfo.get("ai_type") == "nav-enemy":
                    box.label(text="No navmesh linked!", icon="ERROR")
                layout.separator(factor=0.3)

        layout.prop(ob, "set_invisible")
        layout.prop(ob, "enable_custom_weights")
        layout.prop(ob, "copy_eye_draws")
        layout.prop(ob, "copy_mod_draws")
        layout.prop(ob, "set_collision")
        if ob.set_collision:
            col = layout.column()
            col.prop(ob, "ignore")
            col.prop(ob, "collide_mode")
            col.prop(ob, "collide_material")
            col.prop(ob, "collide_event")
            r = col.row(align=True)
            r.prop(ob, "noedge");  r.prop(ob, "noentity")
            r2 = col.row(align=True)
            r2.prop(ob, "nolineofsight"); r2.prop(ob, "nocamera")




# ---------------------------------------------------------------------------
# Preview collection and wiki draw helper
# ---------------------------------------------------------------------------

