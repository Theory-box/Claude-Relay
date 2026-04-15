# ---------------------------------------------------------------------------
# operators.py — OpenGOAL Level Tools
# All OG_OT_* operator classes and their helper functions.
# ---------------------------------------------------------------------------

import bpy, os, re, json, subprocess, threading, time, math, mathutils
from pathlib import Path
from bpy.props import (StringProperty, BoolProperty, IntProperty,
                       EnumProperty, FloatProperty, CollectionProperty)
from bpy.types import Operator
from .data import (
    ENTITY_DEFS, ENTITY_ENUM_ITEMS, ENEMY_ENUM_ITEMS, PROP_ENUM_ITEMS,
    NPC_ENUM_ITEMS, PICKUP_ENUM_ITEMS, PLATFORM_ENUM_ITEMS, CRATE_ITEMS, CRATE_PICKUP_ITEMS,
    ALL_SFX_ITEMS, SBK_SOUNDS, LEVEL_BANKS, LUMP_REFERENCE, ACTOR_LINK_DEFS,
    MUSIC_FLAVA_TABLE,
    NAV_UNSAFE_TYPES, NEEDS_PATH_TYPES, NEEDS_PATHB_TYPES, IS_PROP_TYPES,
    ETYPE_AG, ETYPE_CODE,
    needed_tpages, _lump_ref_for_etype, _actor_link_slots, _actor_has_links,
    _actor_links, _actor_get_link, _actor_set_link, _actor_remove_link,
    _build_actor_link_lumps, _parse_lump_row, _LUMP_HARDCODED_KEYS,
    _aggro_event_id, AGGRO_EVENT_ENUM_ITEMS, LUMP_TYPE_ITEMS,
    UNIVERSAL_LUMPS, _is_custom_type,
)
from .collections import (
    _get_level_prop, _set_level_prop, _level_objects, _active_level_col,
    _all_level_collections, _ensure_sub_collection, _classify_object,
    _col_path_for_entity, _link_object_to_sub_collection,
    _recursive_col_objects, _COL_PATH_WAYPOINTS, _COL_PATH_NAVMESHES,
    _COL_PATH_TRIGGERS, _COL_PATH_CAMERAS, _COL_PATH_SPAWNS,
    _COL_PATH_SOUND_EMITTERS, _COL_PATH_SPAWNABLE_ENEMIES,
    _COL_PATH_SPAWNABLE_PLATFORMS, _COL_PATH_SPAWNABLE_PROPS,
    _COL_PATH_SPAWNABLE_NPCS, _COL_PATH_SPAWNABLE_PICKUPS,
    _COL_PATH_GEO_SOLID, _COL_PATH_WATER,
    _set_blender_active_collection, _LEVEL_COL_DEFAULTS,
)
from .export import (
    _nick, _iso, _lname, _ldir, _goal_src, _level_info, _game_gp,
    _levels_dir, _entity_gc, _actor_uses_waypoints, _actor_uses_navmesh,
    _actor_is_platform, _actor_is_launcher, _actor_is_spawner,
    _actor_is_enemy, _actor_supports_aggro_trigger,
    _vol_links, _vol_link_targets, _vol_has_link_to, _rename_vol_for_links,
    _vols_linking_to, _vol_get_link_to, _vol_remove_link_to,
    _classify_target, _clean_orphaned_vol_links, log, collect_actors,
    collect_spawns, collect_ambients, needed_ags, needed_code,
    patch_level_info, patch_game_gp, discover_custom_levels, remove_level,
    export_glb,
)
from .build import (
    _EXE, _BUILD_STATE, _PLAY_STATE, _GEO_REBUILD_STATE, _BUILD_PLAY_STATE, _exe_root, _data_root, _data,
    _gk, _goalc, _user_dir, kill_gk, launch_gk, goalc_send, goalc_ok,
    launch_goalc, _bg_build, _bg_play, _bg_geo_rebuild, _bg_build_and_play,
)
from .properties import OGLumpRow, OGActorLink, OGVolLink, OGProperties
from .utils import (
    _is_linkable, _is_aggro_target, _vol_for_target,
    _ENEMY_CATS, _NPC_CATS, _PICKUP_CATS, _PROP_CATS,
    _draw_platform_settings, _header_sep, _draw_entity_sub,
    _draw_wiki_preview,
)
from . import model_preview as _mp

class OG_OT_CreateLevel(Operator):
    """Create a new level collection with default settings."""
    bl_idname   = "og.create_level"
    bl_label    = "Add Level"
    bl_options  = {"REGISTER", "UNDO"}

    level_name: StringProperty(name="Level Name", default="my-level",
                               description="Name for the new level (lowercase, dashes)")
    base_id:    IntProperty(name="Base Actor ID", default=10000, min=1000, max=60000,
                            description="Starting actor ID — must be unique per level")

    def invoke(self, ctx, event):
        # Auto-increment base_id if other levels exist
        levels = _all_level_collections(ctx.scene)
        if levels:
            max_id = max(c.get("og_base_id", 10000) for c in levels)
            self.base_id = max_id + 1000
            self.level_name = "new-level"
        return ctx.window_manager.invoke_props_dialog(self)

    def execute(self, ctx):
        name = self.level_name.strip().lower().replace(" ", "-")
        if not name:
            self.report({"ERROR"}, "Level name cannot be empty")
            return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10")
            return {"CANCELLED"}

        # Check for duplicate names
        for col in _all_level_collections(ctx.scene):
            if col.get("og_level_name", "") == name:
                self.report({"ERROR"}, f"A level named '{name}' already exists")
                return {"CANCELLED"}

        # Create the level collection
        col = bpy.data.collections.new(name)
        ctx.scene.collection.children.link(col)

        # Set level properties
        col["og_is_level"]          = True
        col["og_level_name"]        = name
        col["og_base_id"]           = self.base_id
        col["og_bottom_height"]     = -20.0
        col["og_vis_nick_override"] = ""
        col["og_sound_bank_1"]      = "none"
        col["og_sound_bank_2"]      = "none"
        col["og_music_bank"]        = "none"

        # Set as active level
        ctx.scene.og_props.active_level = col.name
        _set_blender_active_collection(ctx, col)

        self.report({"INFO"}, f"Created level '{name}' (base ID {self.base_id})")
        log(f"[collections] Created level collection '{name}' base_id={self.base_id}")
        return {"FINISHED"}


class OG_OT_AssignCollectionAsLevel(Operator):
    """Assign an existing Blender collection as a level."""
    bl_idname   = "og.assign_collection_as_level"
    bl_label    = "Assign Collection as Level"
    bl_options  = {"REGISTER", "UNDO"}

    col_name:   StringProperty(name="Collection",
                               description="Existing collection to designate as a level")
    level_name: StringProperty(name="Level Name", default="my-level",
                               description="Level name (max 10 chars, lowercase with dashes)")
    base_id:    IntProperty(name="Base Actor ID", default=10000, min=1000, max=60000)

    def invoke(self, ctx, event):
        # Auto-increment base_id
        levels = _all_level_collections(ctx.scene)
        if levels:
            max_id = max(c.get("og_base_id", 10000) for c in levels)
            self.base_id = max_id + 1000
        return ctx.window_manager.invoke_props_dialog(self)

    def draw(self, ctx):
        layout = self.layout
        layout.prop_search(self, "col_name", bpy.data, "collections", text="Collection")
        layout.prop(self, "level_name")
        layout.prop(self, "base_id")

    def execute(self, ctx):
        if not self.col_name:
            self.report({"ERROR"}, "No collection selected"); return {"CANCELLED"}
        col = bpy.data.collections.get(self.col_name)
        if col is None:
            self.report({"ERROR"}, f"Collection '{self.col_name}' not found"); return {"CANCELLED"}
        if col.get("og_is_level", False):
            self.report({"ERROR"}, f"'{self.col_name}' is already a level"); return {"CANCELLED"}

        name = self.level_name.strip().lower().replace(" ", "-")
        if not name:
            self.report({"ERROR"}, "Level name cannot be empty"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}

        # Check for duplicate level names
        for c in _all_level_collections(ctx.scene):
            if c.get("og_level_name", "") == name:
                self.report({"ERROR"}, f"A level named '{name}' already exists"); return {"CANCELLED"}

        # Ensure collection is a direct child of the scene collection
        if col.name not in [c.name for c in ctx.scene.collection.children]:
            # It might be nested — link to scene root
            ctx.scene.collection.children.link(col)

        # Set level properties
        col["og_is_level"]          = True
        col["og_level_name"]        = name
        col["og_base_id"]           = self.base_id
        col["og_bottom_height"]     = -20.0
        col["og_vis_nick_override"] = ""
        col["og_sound_bank_1"]      = "none"
        col["og_sound_bank_2"]      = "none"
        col["og_music_bank"]        = "none"

        # Set as active level
        ctx.scene.og_props.active_level = col.name
        _set_blender_active_collection(ctx, col)

        self.report({"INFO"}, f"Assigned '{self.col_name}' as level '{name}'")
        log(f"[collections] Assigned existing collection '{self.col_name}' as level '{name}'")
        return {"FINISHED"}


class OG_OT_SetActiveLevel(Operator):
    """Set a level collection as the active level."""
    bl_idname   = "og.set_active_level"
    bl_label    = "Set Active Level"
    bl_options  = {"REGISTER", "UNDO"}

    col_name: StringProperty(name="Collection Name")

    def execute(self, ctx):
        col = None
        for c in _all_level_collections(ctx.scene):
            if c.name == self.col_name:
                col = c
                break
        if col is None:
            self.report({"ERROR"}, f"Level collection '{self.col_name}' not found")
            return {"CANCELLED"}
        ctx.scene.og_props.active_level = col.name
        _set_blender_active_collection(ctx, col)
        lname = col.get("og_level_name", col.name)
        self.report({"INFO"}, f"Active level: {lname}")
        return {"FINISHED"}


class OG_OT_NudgeLevelProp(Operator):
    """Nudge a numeric property on the active level collection."""
    bl_idname   = "og.nudge_level_prop"
    bl_label    = "Nudge Level Property"
    bl_options  = {"REGISTER", "UNDO"}

    prop_name: StringProperty()
    delta:     FloatProperty()
    val_min:   FloatProperty(default=-999999.0)
    val_max:   FloatProperty(default=999999.0)

    def execute(self, ctx):
        col = _active_level_col(ctx.scene)
        if col is None:
            self.report({"ERROR"}, "No active level"); return {"CANCELLED"}
        cur = float(col.get(self.prop_name, 0.0))
        col[self.prop_name] = max(self.val_min, min(self.val_max, cur + self.delta))
        return {"FINISHED"}


class OG_OT_DeleteLevel(Operator):
    """Remove a collection from the level list (does not delete the collection)."""
    bl_idname   = "og.delete_level"
    bl_label    = "Remove Level"
    bl_options  = {"REGISTER", "UNDO"}

    col_name: StringProperty(name="Collection Name")

    def execute(self, ctx):
        target = None
        for c in _all_level_collections(ctx.scene):
            if c.name == self.col_name:
                target = c
                break
        if target is None:
            self.report({"ERROR"}, f"Level '{self.col_name}' not found")
            return {"CANCELLED"}

        lname = target.get("og_level_name", target.name)

        # Just remove the level marker — collection stays intact
        if "og_is_level" in target:
            del target["og_is_level"]
        for key in list(target.keys()):
            if key.startswith("og_"):
                del target[key]

        self.report({"INFO"}, f"Removed '{lname}' from levels (collection preserved)")
        return {"FINISHED"}


class OG_OT_AddCollectionToLevel(Operator):
    """Search for and add a collection from inside the level to the managed list."""
    bl_idname   = "og.add_collection_to_level"
    bl_label    = "Add Collection"
    bl_options  = {"REGISTER", "UNDO"}

    col_name: StringProperty(name="Collection",
                             description="Name of the collection to add")

    def invoke(self, ctx, event):
        self.col_name = ""
        return ctx.window_manager.invoke_props_dialog(self)

    def draw(self, ctx):
        level_col = _active_level_col(ctx.scene)
        if level_col is not None:
            self.layout.prop_search(self, "col_name", level_col, "children",
                                    text="Collection")
        else:
            self.layout.label(text="No active level", icon="ERROR")

    def execute(self, ctx):
        level_col = _active_level_col(ctx.scene)
        if level_col is None:
            self.report({"ERROR"}, "No active level"); return {"CANCELLED"}
        if not self.col_name:
            self.report({"ERROR"}, "No collection selected"); return {"CANCELLED"}
        # Verify the collection is actually a child of the level
        found = False
        for c in level_col.children:
            if c.name == self.col_name:
                found = True
                break
        if not found:
            self.report({"ERROR"}, f"'{self.col_name}' is not inside this level"); return {"CANCELLED"}
        # Select it in the panel
        ctx.scene.og_props.selected_collection = self.col_name
        self.report({"INFO"}, f"Selected '{self.col_name}'")
        return {"FINISHED"}


class OG_OT_RemoveCollectionFromLevel(Operator):
    """Remove a collection from the active level (moves it back to scene root)."""
    bl_idname   = "og.remove_collection_from_level"
    bl_label    = "Remove Collection"
    bl_options  = {"REGISTER", "UNDO"}

    col_name: StringProperty(name="Collection Name")

    def execute(self, ctx):
        level_col = _active_level_col(ctx.scene)
        if level_col is None:
            self.report({"ERROR"}, "No active level"); return {"CANCELLED"}
        col = None
        for c in level_col.children:
            if c.name == self.col_name:
                col = c
                break
        if col is None:
            self.report({"ERROR"}, f"Collection '{self.col_name}' not in this level"); return {"CANCELLED"}
        level_col.children.unlink(col)
        # Re-link to scene root so it doesn't vanish
        ctx.scene.collection.children.link(col)
        self.report({"INFO"}, f"Removed '{self.col_name}' from level")
        return {"FINISHED"}


class OG_OT_RemoveCollectionFromLevelActive(Operator):
    """Remove the selected collection from the active level."""
    bl_idname   = "og.remove_collection_from_level_active"
    bl_label    = "Remove Selected Collection"
    bl_options  = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        level_col = _active_level_col(ctx.scene)
        if level_col is None:
            self.report({"ERROR"}, "No active level"); return {"CANCELLED"}
        if not props.col_list or props.col_list_index >= len(props.col_list):
            self.report({"ERROR"}, "No collection selected"); return {"CANCELLED"}
        col_name = props.col_list[props.col_list_index].name
        col = None
        for c in level_col.children:
            if c.name == col_name:
                col = c
                break
        if col is None:
            self.report({"ERROR"}, f"'{col_name}' not found"); return {"CANCELLED"}
        level_col.children.unlink(col)
        ctx.scene.collection.children.link(col)
        # Remove from UIList
        props.col_list.remove(props.col_list_index)
        if props.col_list_index >= len(props.col_list):
            props.col_list_index = max(0, len(props.col_list) - 1)
        self.report({"INFO"}, f"Removed '{col_name}' from level")
        return {"FINISHED"}


class OG_OT_ToggleCollectionNoExport(Operator):
    """Toggle the no-export flag on a collection."""
    bl_idname   = "og.toggle_collection_no_export"
    bl_label    = "Toggle Exclude from Export"
    bl_options  = {"REGISTER", "UNDO"}

    col_name: StringProperty(name="Collection Name")

    def execute(self, ctx):
        col = bpy.data.collections.get(self.col_name)
        if col is None:
            self.report({"ERROR"}, f"Collection '{self.col_name}' not found"); return {"CANCELLED"}
        cur = bool(col.get("og_no_export", False))
        col["og_no_export"] = not cur
        state = "excluded" if not cur else "included"
        self.report({"INFO"}, f"'{self.col_name}' now {state} from export")
        return {"FINISHED"}


class OG_OT_SelectLevelCollection(Operator):
    """Select a sub-collection in the Collection Properties panel."""
    bl_idname   = "og.select_level_collection"
    bl_label    = "Select Collection"

    col_name: StringProperty(name="Collection Name")

    def execute(self, ctx):
        props = ctx.scene.og_props
        # Toggle: clicking the already-selected collection deselects it
        if props.selected_collection == self.col_name:
            props.selected_collection = ""
        else:
            props.selected_collection = self.col_name
        return {"FINISHED"}


class OG_OT_EditLevel(Operator):
    """Edit the active level's name, base actor ID, and death plane."""
    bl_idname   = "og.edit_level"
    bl_label    = "Edit Level Settings"
    bl_options  = {"REGISTER", "UNDO"}

    level_name:   StringProperty(name="Level Name", default="")
    base_id:      IntProperty(name="Base Actor ID", default=10000, min=1000, max=60000)
    bottom_height: FloatProperty(name="Death Plane (m)", default=-20.0, min=-500.0, max=-1.0,
                                 description="Y height below which the player gets an endlessfall death")

    def invoke(self, ctx, event):
        col = _active_level_col(ctx.scene)
        if col is None:
            self.report({"ERROR"}, "No active level"); return {"CANCELLED"}
        self.level_name    = str(col.get("og_level_name", col.name))
        self.base_id       = int(col.get("og_base_id", 10000))
        self.bottom_height = float(col.get("og_bottom_height", -20.0))
        return ctx.window_manager.invoke_props_dialog(self)

    def execute(self, ctx):
        col = _active_level_col(ctx.scene)
        if col is None:
            self.report({"ERROR"}, "No active level"); return {"CANCELLED"}
        name = self.level_name.strip().lower().replace(" ", "-")
        if not name:
            self.report({"ERROR"}, "Level name cannot be empty"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
        # Check for duplicate names (excluding self)
        for c in _all_level_collections(ctx.scene):
            if c.name != col.name and c.get("og_level_name", "") == name:
                self.report({"ERROR"}, f"A level named '{name}' already exists"); return {"CANCELLED"}
        col["og_level_name"]    = name
        col["og_base_id"]       = self.base_id
        col["og_bottom_height"] = max(-500.0, min(-1.0, self.bottom_height))
        col.name = name  # Keep collection name in sync
        # Update active_level reference since collection name changed
        ctx.scene.og_props.active_level = col.name
        self.report({"INFO"}, f"Level updated: '{name}' (ID {self.base_id})")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# OPERATORS — Spawn / NavMesh
# ---------------------------------------------------------------------------

class OG_OT_SpawnPlayer(Operator):
    bl_idname = "og.spawn_player"
    bl_label  = "Add Player Spawn"
    bl_description = "Place a player spawn empty at the 3D cursor"
    def execute(self, ctx):
        n   = len([o for o in _level_objects(ctx.scene) if o.name.startswith("SPAWN_") and not o.name.endswith("_CAM")])
        uid = "start" if n == 0 else f"spawn{n}"
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"SPAWN_{uid}"; o.show_name = True
        o.empty_display_size = 1.0; o.color = (0.0,1.0,0.0,1.0)
        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_SPAWNS)
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}


class OG_OT_SpawnCheckpoint(Operator):
    bl_idname = "og.spawn_checkpoint"
    bl_label  = "Add Checkpoint"
    bl_description = (
        "Place a mid-level checkpoint empty at the 3D cursor. "
        "The engine auto-assigns the nearest zero-flag checkpoint as the player "
        "moves around, so these act as silent progress saves without any trigger actors."
    )
    def execute(self, ctx):
        n   = len([o for o in _level_objects(ctx.scene) if o.name.startswith("CHECKPOINT_") and not o.name.endswith("_CAM")])
        uid = f"cp{n}"
        bpy.ops.object.empty_add(type="SINGLE_ARROW", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"CHECKPOINT_{uid}"; o.show_name = True
        o.empty_display_size = 1.2; o.color = (1.0, 0.85, 0.0, 1.0)
        o["og_checkpoint_radius"] = 3.0
        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_SPAWNS)
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}


class OG_OT_SpawnCamAnchor(Operator):
    bl_idname = "og.spawn_cam_anchor"
    bl_label  = "Add Spawn Camera"
    bl_description = (
        "Place a camera-anchor empty linked to the selected SPAWN_ or CHECKPOINT_ empty. "
        "This sets the camera position and orientation used when the player respawns at that point."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if sel is None or sel.type != "EMPTY":
            self.report({"ERROR"}, "Select a SPAWN_ or CHECKPOINT_ empty first")
            return {"CANCELLED"}
        is_spawn = sel.name.startswith("SPAWN_") or sel.name.startswith("CHECKPOINT_")
        if not is_spawn:
            self.report({"ERROR"}, "Selected object must be a SPAWN_ or CHECKPOINT_ empty")
            return {"CANCELLED"}
        cam_name = sel.name + "_CAM"
        if ctx.scene.objects.get(cam_name):
            self.report({"WARNING"}, f"{cam_name} already exists")
            return {"CANCELLED"}
        # Place camera 6m behind and 3m above spawn in Blender space
        offset = mathutils.Vector((0.0, -6.0, 3.0))
        loc    = sel.matrix_world.translation + sel.matrix_world.to_3x3() @ offset
        bpy.ops.object.empty_add(type="ARROWS", location=loc)
        o = ctx.active_object
        o.name = cam_name; o.show_name = True
        o.empty_display_size = 0.8; o.color = (0.2, 0.6, 1.0, 1.0)
        # Point it toward the spawn (face -Z toward spawn so camera looks at it)
        direction = sel.matrix_world.translation - loc
        if direction.length > 1e-4:
            rot_quat = direction.to_track_quat('-Z', 'Y')
            o.rotation_euler = rot_quat.to_euler()
        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_SPAWNS)
        self.report({"INFO"}, f"Added {cam_name}")
        return {"FINISHED"}







# ── Entity placement ──────────────────────────────────────────────────────────

class OG_OT_SpawnEntity(Operator):
    bl_idname = "og.spawn_entity"
    bl_label  = "Add Entity"
    bl_description = "Place selected entity at the 3D cursor"
    # Which OGProperties prop holds the selected type. Sub-panels set this
    # so the operator reads from the correct per-category dropdown.
    source_prop: bpy.props.StringProperty(default="entity_type")

    def execute(self, ctx):
        props = ctx.scene.og_props
        # Read from the per-category prop if specified, else fall back to entity_type
        etype = getattr(props, self.source_prop, None) or props.entity_type
        # Keep entity_type in sync so export / wiki preview stay consistent
        if hasattr(props, "entity_type"):
            try: props.entity_type = etype
            except Exception: pass
        info  = ENTITY_DEFS.get(etype, {})
        shape = info.get("shape", "SPHERE")
        color = info.get("color", (1.0,0.5,0.1,1.0))
        n     = len([o for o in _level_objects(ctx.scene) if o.name.startswith(f"ACTOR_{etype}_")])
        bpy.ops.object.empty_add(type=shape, location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"ACTOR_{etype}_{n}"
        o.show_name = True
        o.empty_display_size = 0.6
        o.color = color
        _link_object_to_sub_collection(ctx.scene, o, *_col_path_for_entity(etype))
        if etype == "crate":
            o["og_crate_type"]          = ctx.scene.og_props.crate_type
            o["og_crate_pickup"]        = "money"
            o["og_crate_pickup_amount"] = 1
        if etype in NAV_UNSAFE_TYPES:
            o["og_nav_radius"] = ctx.scene.og_props.nav_radius
            self.report({"WARNING"},
                f"Added {o.name}  —  nav-mesh workaround will be applied on export. "
                f"Enemy will idle/notice but won't pathfind without a real navmesh.")
        elif etype in NEEDS_PATHB_TYPES:
            self.report({"WARNING"},
                f"Added {o.name}  —  swamp-bat needs TWO path sets: "
                f"waypoints named _wp_00/_wp_01... AND _wpb_00/_wpb_01... (second patrol route).")
        elif etype in NEEDS_PATH_TYPES:
            self.report({"WARNING"},
                f"Added {o.name}  —  this entity requires at least 1 waypoint (_wp_00). "
                f"It will crash or error at runtime without a path.")
        elif etype in IS_PROP_TYPES:
            self.report({"INFO"}, f"Added {o.name}  (prop — idle animation only, no AI/combat)")
        else:
            self.report({"INFO"}, f"Added {o.name}")

        # ---- Set default custom props so UI fields render immediately ------
        if _actor_is_enemy(etype):
            o["og_idle_distance"] = 80.0
            o["og_vis_dist"]      = 200.0
        if _actor_is_spawner(etype):
            o["og_num_lurkers"] = -1
        if etype == "orb-cache-top":
            o["og_orb_count"] = 20
        if etype == "sunkenfisha":
            o["og_fish_count"] = 1
        if etype in {"lavaballoon", "darkecobarrel"}:
            o["og_move_speed"] = 3.0 if etype == "lavaballoon" else 15.0

        # ---- Model preview ------------------------------------------------
        _prefs = bpy.context.preferences.addons.get("opengoal_tools")
        if _prefs and _prefs.preferences.preview_models:
            try:
                attached = _mp.attach_preview(ctx, etype, o)
                if not attached and ENTITY_DEFS.get(etype, {}).get("glb"):
                    self.report({"WARNING"}, f"No GLB for {etype} — delete decompiler_out/jak1/ and re-run extractor")
            except Exception as e:
                # Never crash the spawn operator over a preview failure
                log(f"model_preview: {e}")

        return {"FINISHED"}


class OG_OT_DuplicateEntity(Operator):
    """Duplicate the selected ACTOR empty and re-attach its preview mesh."""
    bl_idname   = "og.duplicate_entity"
    bl_label    = "Duplicate Entity"
    bl_description = "Duplicate this entity and carry its preview mesh to the copy"
    bl_options  = {"UNDO"}

    def execute(self, ctx):
        src = ctx.active_object
        if src is None or not src.name.startswith("ACTOR_"):
            self.report({"ERROR"}, "Select an ACTOR_ empty first")
            return {"CANCELLED"}

        # Parse entity type from name: ACTOR_<etype>_<uid>
        parts = src.name.split("_", 2)
        if len(parts) < 3:
            self.report({"ERROR"}, f"Cannot parse entity type from {src.name!r}")
            return {"CANCELLED"}
        etype = parts[1]

        # --- Duplicate just the empty (no children) via ops ---
        # Deselect all, select only the source, then duplicate
        bpy.ops.object.select_all(action="DESELECT")
        src.select_set(True)
        ctx.view_layer.objects.active = src
        bpy.ops.object.duplicate(linked=False, mode="TRANSLATION")
        new_empty = ctx.active_object

        # Give it a fresh unique name (Blender appends .001 etc automatically,
        # but we want to follow the ACTOR_<etype>_<n> convention)
        prefix = f"ACTOR_{etype}_"
        # Use bpy.data.objects (not just level objects) so we avoid collisions
        # with the freshly duplicated object which may not yet be in the level col
        existing = {o.name for o in bpy.data.objects}
        n = 0
        while f"{prefix}{n}" in existing:
            n += 1
        new_empty.name = f"{prefix}{n}"

        # --- Strip any preview children the duplicate inherited ---
        # bpy.ops.object.duplicate copies children too; remove them so we
        # can attach a fresh independent preview below.
        _mp.remove_preview(new_empty)

        # Also unlink any child objects Blender may have copied
        for child in list(new_empty.children):
            if child.get(_mp._PREVIEW_PROP) or child.get(_mp._WAYPOINT_PREVIEW_PROP):
                bpy.data.objects.remove(child, do_unlink=True)

        # --- Re-attach a fresh preview mesh ---
        _prefs = bpy.context.preferences.addons.get("opengoal_tools")
        if _prefs and _prefs.preferences.preview_models:
            try:
                _mp.attach_preview(ctx, etype, new_empty)
            except Exception as e:
                log(f"duplicate_entity model_preview: {e}")

        self.report({"INFO"}, f"Duplicated as {new_empty.name}")
        return {"FINISHED"}

class OG_OT_ClearPreviews(Operator):
    bl_idname   = "og.clear_previews"
    bl_label    = "Clear Preview Models"
    bl_description = "Remove all enemy preview meshes from the scene"

    def execute(self, ctx):
        n = _mp.remove_all_previews(ctx.scene)
        self.report({"INFO"}, f"Removed {n} preview mesh{'es' if n != 1 else ''}")
        return {"FINISHED"}


class OG_OT_MarkNavMesh(Operator):
    bl_idname = "og.mark_navmesh"
    bl_label  = "Mark as NavMesh"
    bl_description = "Tag selected mesh objects as navmesh geometry and move into NavMeshes sub-collection"
    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if o.type == "MESH":
                o["og_navmesh"] = True
                if not o.name.startswith("NAVMESH_"):
                    o.name = "NAVMESH_" + o.name
                _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_NAVMESHES)
                count += 1
        self.report({"INFO"}, f"Tagged {count} object(s) as navmesh geometry")
        return {"FINISHED"}

class OG_OT_UnmarkNavMesh(Operator):
    bl_idname = "og.unmark_navmesh"
    bl_label  = "Unmark NavMesh"
    bl_description = "Remove navmesh tag and move out of NavMeshes sub-collection into Geometry/Solid"
    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if "og_navmesh" in o:
                del o["og_navmesh"]
                # Strip NAVMESH_ prefix if present
                if o.name.startswith("NAVMESH_"):
                    o.name = o.name[len("NAVMESH_"):]
                # Move to Geometry/Solid
                _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_GEO_SOLID)
                count += 1
        self.report({"INFO"}, f"Untagged {count} object(s)")
        return {"FINISHED"}




# ---------------------------------------------------------------------------
# OPERATORS — NavMesh linking
# ---------------------------------------------------------------------------

class OG_OT_LinkNavMesh(Operator):
    """Link selected enemy actor(s) to the selected navmesh mesh.
    Select any combination of enemy empties + one mesh — order doesn't matter."""
    bl_idname = "og.link_navmesh"
    bl_label  = "Link to NavMesh"
    bl_description = "Select enemy actor(s) + navmesh mesh (any order), then click"

    def execute(self, ctx):
        selected = ctx.selected_objects

        # Find the mesh and the enemy empties from the full selection — order irrelevant
        meshes  = [o for o in selected if o.type == "MESH"]
        enemies = [o for o in selected if o.type == "EMPTY"
                   and o.name.startswith("ACTOR_") and "_wp_" not in o.name
                   and "_wpb_" not in o.name]

        if not meshes:
            self.report({"ERROR"}, "No mesh in selection — select a navmesh quad too")
            return {"CANCELLED"}
        if len(meshes) > 1:
            self.report({"ERROR"}, "Multiple meshes selected — select only one navmesh quad")
            return {"CANCELLED"}
        if not enemies:
            self.report({"ERROR"}, "No enemy actor in selection — select the enemy empty too")
            return {"CANCELLED"}

        nm = meshes[0]

        # Tag mesh as navmesh, prefix name if needed, route into NavMeshes sub-collection
        nm["og_navmesh"] = True
        if not nm.name.startswith("NAVMESH_"):
            nm.name = "NAVMESH_" + nm.name
        _link_object_to_sub_collection(ctx.scene, nm, *_COL_PATH_NAVMESHES)

        for enemy in enemies:
            enemy["og_navmesh_link"] = nm.name

        self.report({"INFO"}, f"Linked {len(enemies)} actor(s) to {nm.name}")
        return {"FINISHED"}


class OG_OT_UnlinkNavMesh(Operator):
    """Remove navmesh link from selected enemy actors.
    Also renames the mesh (strips NAVMESH_ prefix) and moves it to Geometry/Solid."""
    bl_idname = "og.unlink_navmesh"
    bl_label  = "Unlink NavMesh"
    bl_description = "Remove navmesh link from selected enemy actor(s)"

    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if "og_navmesh_link" in o:
                nm_name = o["og_navmesh_link"]
                del o["og_navmesh_link"]
                # Clean up the mesh itself if it still exists
                nm_obj = bpy.data.objects.get(nm_name)
                if nm_obj and nm_obj.type == "MESH":
                    # Remove navmesh tag
                    if "og_navmesh" in nm_obj:
                        del nm_obj["og_navmesh"]
                    # Strip NAVMESH_ prefix
                    if nm_obj.name.startswith("NAVMESH_"):
                        nm_obj.name = nm_obj.name[len("NAVMESH_"):]
                    # Move back to Geometry/Solid
                    _link_object_to_sub_collection(ctx.scene, nm_obj, *_COL_PATH_GEO_SOLID)
                count += 1
        self.report({"INFO"}, f"Unlinked {count} actor(s)")
        return {"FINISHED"}

# ---------------------------------------------------------------------------
# OPERATOR — Export & Build
# ---------------------------------------------------------------------------


class OG_OT_ExportBuild(Operator):
    bl_idname = "og.export_build"
    bl_label  = "Export & Build"
    bl_description = "Export GLB, write all level files, compile with GOALC"
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max is 10. Shorten it in Level Settings.")
            return {"CANCELLED"}
        try:
            export_glb(ctx, name)
        except Exception as e:
            self.report({"ERROR"}, f"GLB export failed: {e}"); return {"CANCELLED"}
        _BUILD_STATE.clear()
        _BUILD_STATE.update({"done":False,"status":"Starting...","error":None,"ok":False})
        depsgraph = ctx.evaluated_depsgraph_get()  # fetch on main thread — unsafe from bg thread
        threading.Thread(target=_bg_build, args=(name, ctx.scene, depsgraph), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL: " + _BUILD_STATE.get("status","Working..."))
            if _BUILD_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _BUILD_STATE.get("error"):
                    self.report({"ERROR"}, _BUILD_STATE["error"]); return {"CANCELLED"}
                self.report({"INFO"}, "Build complete!"); return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)

# ---------------------------------------------------------------------------
# OPERATOR — Play
# ---------------------------------------------------------------------------

class OG_OT_AddWaypoint(Operator):
    """Add a waypoint empty linked to the selected enemy. Spawns at the 3D cursor, or at the actor position if Spawn at Position is enabled."""
    bl_idname = "og.add_waypoint"
    bl_label  = "Add Waypoint"

    enemy_name: bpy.props.StringProperty()
    pathb_mode: bpy.props.BoolProperty(default=False,
        description="Add to secondary path (pathb) — swamp-bat only")

    def execute(self, ctx):
        if not self.enemy_name:
            self.report({"ERROR"}, "No enemy name provided")
            return {"CANCELLED"}

        # Find next available index for primary (_wp_) or secondary (_wpb_) path
        # Scope to level objects so multi-level .blends don't cross-count
        suffix = "_wpb_" if self.pathb_mode else "_wp_"
        prefix = self.enemy_name + suffix
        existing = {o.name for o in _level_objects(ctx.scene) if o.name.startswith(prefix)}
        idx = 0
        while f"{prefix}{idx:02d}" in existing:
            idx += 1

        wp_name = f"{prefix}{idx:02d}"

        # Create empty — at actor position or 3D cursor depending on user preference
        actor_obj = bpy.data.objects.get(self.enemy_name)
        use_actor_pos = ctx.scene.og_props.waypoint_spawn_at_actor and actor_obj is not None
        spawn_loc = actor_obj.location.copy() if use_actor_pos else ctx.scene.cursor.location.copy()

        empty = bpy.data.objects.new(wp_name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        empty.location = spawn_loc

        # Custom property to link back to enemy
        empty["og_waypoint_for"] = self.enemy_name

        # Link into scene first (required before collection routing)
        ctx.scene.collection.objects.link(empty)

        # Route into Waypoints sub-collection under the active level
        _link_object_to_sub_collection(ctx.scene, empty, *_COL_PATH_WAYPOINTS)

        # ---- Waypoint ghost preview ----------------------------------------
        # Parse the entity type from the actor name (ACTOR_<etype>_<uid>)
        # and attach a white, 50%-transparent ghost of its mesh so the user
        # can see where the entity will stand at each waypoint.
        _prefs = bpy.context.preferences.addons.get("opengoal_tools")
        if _prefs and _prefs.preferences.preview_models:
            parts = self.enemy_name.split("_")  # ["ACTOR", "<etype>", "<uid>"]
            etype = parts[1] if len(parts) >= 3 else ""
            if etype:
                try:
                    _mp.attach_waypoint_preview(ctx, etype, empty)
                except Exception as e:
                    log(f"waypoint model_preview: {e}")

        # Do NOT change active object — user needs to keep the actor selected
        # so they can quickly add more waypoints without re-selecting.
        loc_desc = "actor position" if use_actor_pos else "cursor"
        self.report({"INFO"}, f"Added {wp_name} at {loc_desc}")
        return {"FINISHED"}


class OG_OT_DeleteWaypoint(Operator):
    """Remove a waypoint empty."""
    bl_idname = "og.delete_waypoint"
    bl_label  = "Delete Waypoint"

    wp_name: bpy.props.StringProperty()

    def execute(self, ctx):
        ob = bpy.data.objects.get(self.wp_name)
        if ob:
            bpy.data.objects.remove(ob, do_unlink=True)
            self.report({"INFO"}, f"Deleted {self.wp_name}")
        return {"FINISHED"}


class OG_OT_Play(Operator):
    """Launch GK in debug mode. No GOALC, no auto-load — just opens the game
    so you can navigate to your level manually via the debug menu."""
    bl_idname      = "og.play"
    bl_label       = "Launch Game (Debug)"
    bl_description = "Kill existing GK, launch fresh in debug mode. Navigate to your level manually."

    def execute(self, ctx):
        kill_gk()
        ok, msg = launch_gk()
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, "Game launched in debug mode — select your level manually")
        return {"FINISHED"}


class OG_OT_PlayAutoLoad(Operator):
    """Kill GK+GOALC, relaunch, and auto-load the level via nREPL.
    Slower (~30-60s) but fully automated."""
    bl_idname      = "og.play_autoload"
    bl_label       = "Launch & Auto-Load Level"
    bl_description = "Kill GK/GOALC, relaunch, and automatically load your level via nREPL (slower)"
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
        _PLAY_STATE.clear()
        _PLAY_STATE.update({"done":False,"error":None,"status":"Starting..."})
        threading.Thread(target=_bg_play, args=(name,), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL: " + _PLAY_STATE.get("status","..."))
            if _PLAY_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _PLAY_STATE.get("error"):
                    self.report({"ERROR"}, _PLAY_STATE["error"]); return {"CANCELLED"}
                self.report({"INFO"}, "Game launched!")
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)



# ---------------------------------------------------------------------------
# OPERATORS — Open Folder / File
# ---------------------------------------------------------------------------

class OG_OT_OpenFolder(Operator):
    """Open a folder in the system file explorer."""
    bl_idname  = "og.open_folder"
    bl_label   = "Open Folder"
    bl_description = "Open folder in system file explorer"

    folder: bpy.props.StringProperty()

    def execute(self, ctx):
        p = Path(self.folder)
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                self.report({"WARNING"}, f"Folder not found: {p}")
                return {"CANCELLED"}
        try:
            if os.name == "nt":
                os.startfile(str(p))
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self.report({"ERROR"}, f"Could not open folder: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class OG_OT_OpenFile(Operator):
    """Open a specific file in the default system editor."""
    bl_idname  = "og.open_file"
    bl_label   = "Open File"
    bl_description = "Open file in default editor"

    filepath: bpy.props.StringProperty()

    def execute(self, ctx):
        p = Path(self.filepath)
        if not p.exists():
            self.report({"WARNING"}, f"File not found: {p}")
            return {"CANCELLED"}
        try:
            if os.name == "nt":
                os.startfile(str(p))
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self.report({"ERROR"}, f"Could not open file: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}

# ---------------------------------------------------------------------------
# OPERATOR — Export, Build & Play (combined)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OPERATOR — Quick Geo Rebuild
# Re-exports GLB + actor placement, repacks DGO, relaunches GK.
# Skips all GOAL (.gc) recompilation — fastest iteration for geo/placement changes.
# ---------------------------------------------------------------------------



class OG_OT_GeoRebuild(Operator):
    """Re-export geometry and actor placement, repack DGO, relaunch game.
    Skips GOAL compilation — fastest loop for geo and enemy placement changes."""
    bl_idname      = "og.geo_rebuild"
    bl_label       = "Quick Geo Rebuild"
    bl_description = (
        "Re-export geo + actor placement, repack DGO, relaunch game. "
        "No GOAL recompile. Use when only geometry or placement changed."
    )
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max is 10. Shorten it in Level Settings.")
            return {"CANCELLED"}
        try:
            export_glb(ctx, name)
        except Exception as e:
            self.report({"ERROR"}, f"GLB export failed: {e}"); return {"CANCELLED"}
        _GEO_REBUILD_STATE.clear()
        _GEO_REBUILD_STATE.update({"done": False, "status": "Starting...", "error": None, "ok": False})
        depsgraph = ctx.evaluated_depsgraph_get()  # fetch on main thread — unsafe from bg thread
        threading.Thread(target=_bg_geo_rebuild, args=(name, ctx.scene, depsgraph), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL Geo: " + _GEO_REBUILD_STATE.get("status", "Working..."))
            if _GEO_REBUILD_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _GEO_REBUILD_STATE.get("error"):
                    self.report({"ERROR"}, _GEO_REBUILD_STATE["error"]); return {"CANCELLED"}
                self.report({"INFO"}, "Geo rebuild done — load your level in-game")
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)




class OG_OT_ExportBuildPlay(Operator):
    bl_idname      = "og.export_build_play"
    bl_label       = "Export, Build & Play"
    bl_description = "Export GLB, write level files, compile with GOALC, then launch the game"
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first")
            return {"CANCELLED"}
        try:
            export_glb(ctx, name)
        except Exception as e:
            self.report({"ERROR"}, f"GLB export failed: {e}")
            return {"CANCELLED"}

        _BUILD_PLAY_STATE.clear()
        _BUILD_PLAY_STATE.update({"done": False, "status": "Starting...", "error": None, "ok": False})
        depsgraph = ctx.evaluated_depsgraph_get()  # fetch on main thread — unsafe from bg thread
        threading.Thread(target=_bg_build_and_play, args=(name, ctx.scene, depsgraph), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL: " + _BUILD_PLAY_STATE.get("status", "Working..."))
            if _BUILD_PLAY_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _BUILD_PLAY_STATE.get("error"):
                    self.report({"ERROR"}, _BUILD_PLAY_STATE["error"])
                    return {"CANCELLED"}
                self.report({"INFO"}, "Build & launch complete!")
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)



# ---------------------------------------------------------------------------
# HELPERS — waypoint eligibility
# ---------------------------------------------------------------------------



# ===========================================================================
# LUMP REFERENCE TABLE
# ---------------------------------------------------------------------------
# Per-actor lump reference data. Each entry is:
#   (key, ltype, description)
# Used by OG_PT_SelectedLumpReference to auto-populate a read-only reference
# panel and to pre-fill new rows when the user clicks "Use This".
#
# UNIVERSAL_LUMPS apply to every actor.
# LUMP_REFERENCE maps etype → list of actor-specific entries.
# ===========================================================================


# Format: etype → [(key, ltype, description), ...]

# ---------------------------------------------------------------------------
# Lump row operators
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------


class OG_OT_PickSound(Operator):
    """Open sound picker — choose a sound then click OK to place an emitter"""
    bl_idname   = "og.pick_sound"
    bl_label    = "Pick Sound"
    bl_property = "sfx_sound"

    sfx_sound: bpy.props.EnumProperty(
        name="Sound",
        description="Select a sound to place",
        items=ALL_SFX_ITEMS,
    )

    def execute(self, ctx):
        # Just store the selected sound — emitter is placed separately via Add Emitter
        ctx.scene.og_props.sfx_sound = self.sfx_sound
        snd = self.sfx_sound.split("__")[0] if "__" in self.sfx_sound else self.sfx_sound
        self.report({"INFO"}, f"Sound selected: {snd}")
        return {"FINISHED"}

    def invoke(self, ctx, event):
        self.sfx_sound = ctx.scene.og_props.sfx_sound
        ctx.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

class OG_OT_AddSoundEmitter(Operator):
    """Add a sound emitter empty at the 3D cursor"""
    bl_idname  = "og.add_sound_emitter"
    bl_label   = "Add Sound Emitter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        snd   = props.sfx_sound.split("__")[0] if "__" in props.sfx_sound else props.sfx_sound
        if not snd:
            snd = "waterfall"
        existing = [o for o in _level_objects(ctx.scene) if o.name.startswith("AMBIENT_snd")]
        idx  = len(existing) + 1
        name = f"AMBIENT_snd{idx:03d}"

        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = name
        o.show_name = True
        o.empty_display_size = max(0.3, props.ambient_default_radius * 0.05)
        o.color = (0.2, 0.8, 1.0, 1.0)

        # Stamp editable custom props
        o["og_sound_name"]   = snd
        o["og_sound_radius"] = props.ambient_default_radius
        o["og_sound_mode"]   = "loop"

        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_SOUND_EMITTERS)
        self.report({"INFO"}, f"Added '{name}' → {snd}")
        return {"FINISHED"}


class OG_OT_AddMusicZone(Operator):
    """Add a music ambient zone (sphere) at the 3D cursor.
    When the player enters the bsphere the engine calls set-setting! 'music.
    One large zone covering the whole level is the standard setup."""
    bl_idname  = "og.add_music_zone"
    bl_label   = "Add Music Zone"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        bank     = props.og_music_amb_bank
        flava    = props.og_music_amb_flava
        priority = props.og_music_amb_priority
        radius   = props.og_music_amb_radius

        existing = [o for o in _level_objects(ctx.scene) if o.name.startswith("AMBIENT_mus")]
        idx  = len(existing) + 1
        name = f"AMBIENT_mus{idx:03d}"

        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = name
        o.show_name = True
        o.empty_display_size = max(0.3, radius * 0.04)
        o.color = (1.0, 0.85, 0.1, 1.0)   # gold — distinct from sound emitters (cyan)

        o["og_music_bank"]     = bank
        o["og_music_flava"]    = flava
        o["og_music_priority"] = priority
        o["og_music_radius"]   = radius

        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_SOUND_EMITTERS)
        self.report({"INFO"}, f"Added '{name}' → music:{bank} flava:{flava}")
        return {"FINISHED"}


# --- Bank enum items (static — all valid banks) ---
_MUSIC_BANK_ITEMS = [(b[0], b[1], b[2], b[3]) for b in LEVEL_BANKS if b[0] != "none"]


class OG_OT_SetMusicZoneBank(bpy.types.Operator):
    """Pick a music bank for the selected music zone"""
    bl_idname   = "og.set_music_zone_bank"
    bl_label    = "Set Music Bank"
    bl_property = "bank"

    bank: bpy.props.EnumProperty(
        name="Music Bank",
        description="Select music bank for this zone",
        items=_MUSIC_BANK_ITEMS,
    )

    def execute(self, ctx):
        sel = ctx.active_object
        if sel and sel.name.startswith("AMBIENT_mus"):
            sel["og_music_bank"]  = self.bank
            sel["og_music_flava"] = "default"   # reset flava when bank changes
        return {"FINISHED"}

    def invoke(self, ctx, event):
        sel = ctx.active_object
        cur = sel.get("og_music_bank", "village1") if sel else "village1"
        if cur in [b[0] for b in _MUSIC_BANK_ITEMS]:
            self.bank = cur
        ctx.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}


def _flava_items_for_active(self, context):
    """Dynamic items callback — flavas for whatever bank the selected object has."""
    sel  = context.active_object if context else None
    bank = sel.get("og_music_bank", "village1") if sel else "village1"
    flavas = MUSIC_FLAVA_TABLE.get(bank, ["default"])
    return [(f, f, "", i) for i, f in enumerate(flavas)]


class OG_OT_SetMusicZoneFlava(bpy.types.Operator):
    """Pick a flava variant for the selected music zone"""
    bl_idname   = "og.set_music_zone_flava"
    bl_label    = "Set Music Flava"
    bl_property = "flava"

    flava: bpy.props.EnumProperty(
        name="Flava",
        description="Select music variant for this zone",
        items=_flava_items_for_active,
    )

    def execute(self, ctx):
        sel = ctx.active_object
        if sel and sel.name.startswith("AMBIENT_mus"):
            sel["og_music_flava"] = self.flava
        return {"FINISHED"}

    def invoke(self, ctx, event):
        ctx.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}


class OG_OT_SpawnCamera(Operator):
    bl_idname = "og.spawn_camera"
    bl_label  = "Add Camera"
    bl_description = (
        "Place a Blender camera at the 3D cursor.\n"
        "Named CAMERA_0, CAMERA_1 etc.\n"
        "Look through it with Numpad-0 to preview the game view.\n"
        "Link a trigger volume mesh with 'Link Trigger Volume'."
    )
    def execute(self, ctx):
        n = len([o for o in _level_objects(ctx.scene)
                 if o.name.startswith("CAMERA_") and o.type == "CAMERA"])
        cam_name = f"CAMERA_{n}"
        bpy.ops.object.camera_add(location=ctx.scene.cursor.location)
        o = ctx.active_object
        # Set name twice: Blender resolves duplicate data-block names after the
        # first assignment, so the second set lands the exact name we want.
        o.name      = cam_name
        o.name      = cam_name
        o.data.name = cam_name
        o.show_name = True
        o.color = (0.0, 0.8, 0.9, 1.0)
        # Default custom properties
        o["og_cam_mode"]   = "fixed"
        o["og_cam_interp"] = 1.0
        o["og_cam_fov"]    = 0.0
        o["og_cam_look_at"] = ""
        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_CAMERAS)
        self.report({"INFO"}, f"Added {o.name}  |  Numpad-0 to look through it")
        return {"FINISHED"}



class OG_OT_SpawnVolume(Operator):
    """Spawn a generic trigger volume (VOL_N wireframe cube).
    If the active object is a linkable target (CAMERA_, SPAWN_, CHECKPOINT_),
    the volume is auto-linked to it immediately on spawn."""
    bl_idname = "og.spawn_volume"
    bl_label  = "Add Trigger Volume"
    bl_description = (
        "Add a box mesh trigger volume at the 3D cursor. "
        "If a camera, spawn, or checkpoint is selected, it auto-links."
    )
    def execute(self, ctx):
        n = len([o for o in _level_objects(ctx.scene)
                 if o.type == "MESH" and o.name.startswith("VOL_")])
        bpy.ops.mesh.primitive_cube_add(size=4.0, location=ctx.scene.cursor.location)
        vol = ctx.active_object
        vol.name = f"VOL_{n}"
        vol["og_vol_id"] = n          # numeric id used for naming when 0 or 2+ links
        vol.show_name = True
        vol.display_type = "WIRE"
        vol.color = (0.0, 0.9, 0.3, 0.4)
        vol.set_invisible = True
        vol.set_collision = True
        vol.ignore        = True

        # Auto-link if a target name was stamped on the scene by invoke()
        target_name = ctx.scene.get("_pending_vol_target", "")
        if target_name:
            target = ctx.scene.objects.get(target_name)
            if target:
                links = _vol_links(vol)
                entry = links.add()
                entry.target_name = target_name
                entry.behaviour   = "cue-chase"
                _rename_vol_for_links(vol)
                ctx.scene["_pending_vol_target"] = ""
                _link_object_to_sub_collection(ctx.scene, vol, *_COL_PATH_TRIGGERS)
                self.report({"INFO"}, f"Added and linked {vol.name} → {target_name}")
                return {"FINISHED"}

        ctx.scene["_pending_vol_target"] = ""
        _link_object_to_sub_collection(ctx.scene, vol, *_COL_PATH_TRIGGERS)
        self.report({"INFO"}, f"Added {vol.name}  —  select volume + target → Link in Triggers panel")
        return {"FINISHED"}

    def invoke(self, ctx, event):
        # Store active object name before adding geometry changes active
        sel = ctx.active_object
        if sel and _is_linkable(sel):
            # Block duplicate camera/checkpoint links; aggro targets allow multiple
            if not _is_aggro_target(sel):
                existing = _vol_for_target(ctx.scene, sel.name)
                if existing:
                    self.report({"WARNING"}, f"{sel.name} already has {existing.name} linked — unlink first")
                    return {"CANCELLED"}
            ctx.scene["_pending_vol_target"] = sel.name
        else:
            ctx.scene["_pending_vol_target"] = ""
        return self.execute(ctx)










class OG_OT_SpawnVolumeAutoLink(Operator):
    """Internal: spawn a volume and auto-link to the given target."""
    bl_idname = "og.spawn_volume_autolink"
    bl_label  = "Add & Link Trigger Volume"
    bl_description = "Spawn a trigger volume and immediately link it to the active object"

    target_name: bpy.props.StringProperty()

    def execute(self, ctx):
        target = ctx.scene.objects.get(self.target_name)
        if not target:
            self.report({"ERROR"}, f"Target {self.target_name} not found")
            return {"CANCELLED"}
        # Cameras / checkpoints: 1:1 (block duplicate). Aggro enemies: allow multiple.
        if not _is_aggro_target(target):
            existing = _vol_for_target(ctx.scene, self.target_name)
            if existing:
                self.report({"WARNING"}, f"{self.target_name} already linked to {existing.name} — unlink first")
                return {"CANCELLED"}
        n = len([o for o in _level_objects(ctx.scene) if o.type == "MESH" and o.name.startswith("VOL_")])
        # Place at target location
        bpy.ops.mesh.primitive_cube_add(size=4.0, location=target.location)
        vol = ctx.active_object
        vol.name = f"VOL_{n}"   # interim — _rename_vol_for_links replaces this
        vol["og_vol_id"] = n
        vol.show_name = True
        vol.display_type = "WIRE"
        vol.set_invisible = True
        vol.set_collision = True
        vol.ignore        = True
        if target.type == "CAMERA":
            vol.color = (0.0, 0.9, 0.3, 0.4)   # green — camera
        elif _is_aggro_target(target):
            vol.color = (1.0, 0.3, 0.0, 0.4)   # red-orange — aggro
        else:
            vol.color = (1.0, 0.85, 0.0, 0.4)  # yellow — checkpoint
        links = _vol_links(vol)
        entry = links.add()
        entry.target_name = self.target_name
        entry.behaviour   = "cue-chase"
        _rename_vol_for_links(vol)
        _link_object_to_sub_collection(ctx.scene, vol, *_COL_PATH_TRIGGERS)
        self.report({"INFO"}, f"Added {vol.name} → {self.target_name}")
        return {"FINISHED"}


class OG_OT_LinkVolume(Operator):
    """Append a link from a VOL_ mesh to a camera, checkpoint, or nav-enemy.
    Select the VOL_ mesh first, then shift-click the target, then click Link.
    A volume can hold multiple links — each fires its own action on enter."""
    bl_idname   = "og.link_volume"
    bl_label    = "Link Volume"
    bl_description = "Select VOL_ mesh first, then shift-click the target (camera/checkpoint/enemy), then click"

    def execute(self, ctx):
        selected = ctx.selected_objects
        vols    = [o for o in selected if o.type == "MESH" and o.name.startswith("VOL_")]
        targets = [o for o in selected if _is_linkable(o)]

        if not vols:
            self.report({"ERROR"}, "No VOL_ mesh in selection")
            return {"CANCELLED"}
        if len(vols) > 1:
            self.report({"ERROR"}, "Multiple volumes selected — select exactly one")
            return {"CANCELLED"}
        if not targets:
            self.report({"ERROR"}, "No linkable target (camera, checkpoint, or nav-enemy) in selection")
            return {"CANCELLED"}
        if len(targets) > 1:
            self.report({"ERROR"}, "Multiple targets selected — select exactly one")
            return {"CANCELLED"}

        vol    = vols[0]
        target = targets[0]
        links  = _vol_links(vol)

        # Block duplicate link to the same camera/checkpoint on this vol
        # (Scenario B from design — pointless duplicate). Aggro enemy targets
        # are also blocked from exact duplicates: each link entry must have
        # a unique target_name on a given vol.
        if _vol_has_link_to(vol, target.name):
            self.report({"WARNING"}, f"{vol.name} is already linked to {target.name}")
            return {"CANCELLED"}

        # For cameras/checkpoints, also block the cross-volume duplicate
        # (one camera/checkpoint should have one trigger volume system-wide).
        if not _is_aggro_target(target):
            existing = _vol_for_target(ctx.scene, target.name)
            if existing and existing != vol:
                self.report({"WARNING"},
                    f"{target.name} already has {existing.name} linked — unlink first")
                return {"CANCELLED"}

        entry = links.add()
        entry.target_name = target.name
        entry.behaviour   = "cue-chase"
        _rename_vol_for_links(vol)
        self.report({"INFO"}, f"Linked {vol.name} → {target.name}  ({len(links)} link{'s' if len(links)!=1 else ''})")
        return {"FINISHED"}


class OG_OT_UnlinkVolume(Operator):
    """Unlink a VOL_ mesh from its target. Works on selected VOL_ meshes."""
    bl_idname   = "og.unlink_volume"
    bl_label    = "Unlink Volume"
    bl_description = "Remove the link from the selected VOL_ mesh and restore its generic name"

    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if o.type == "MESH" and o.name.startswith("VOL_"):
                links = _vol_links(o)
                if len(links) > 0:
                    links.clear()
                    _rename_vol_for_links(o)
                    count += 1
        if count:
            self.report({"INFO"}, f"Unlinked all entries from {count} volume(s)")
        else:
            self.report({"WARNING"}, "No linked VOL_ meshes in selection")
        return {"FINISHED"}


class OG_OT_SelectAndFrame(Operator):
    """Make an object active, select it, and frame it in the viewport."""
    bl_idname = "og.select_and_frame"
    bl_label  = "View"
    bl_description = "Select this object and frame it in the viewport"

    obj_name: bpy.props.StringProperty()

    def execute(self, ctx):
        obj = ctx.scene.objects.get(self.obj_name)
        if not obj:
            self.report({"ERROR"}, f"Object '{self.obj_name}' not found")
            return {"CANCELLED"}
        # Deselect all, select and make active
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        ctx.view_layer.objects.active = obj
        # Frame in viewport
        bpy.ops.view3d.view_selected()
        return {"FINISHED"}


class OG_OT_DeleteObject(Operator):
    """Delete an object by name, also cleaning up any linked volumes."""
    bl_idname = "og.delete_object"
    bl_label  = "Delete"
    bl_description = "Delete this object (volumes linked to it will be unlinked)"

    obj_name: bpy.props.StringProperty()

    def execute(self, ctx):
        obj = ctx.scene.objects.get(self.obj_name)
        if not obj:
            self.report({"ERROR"}, f"Object '{self.obj_name}' not found")
            return {"CANCELLED"}
        # Clean any link entries pointing to this object before deleting it.
        # Volumes themselves stay (orphaned) — user decision per design discussion.
        for o in _level_objects(ctx.scene):
            if o.type == "MESH" and o.name.startswith("VOL_"):
                _vol_remove_link_to(o, self.obj_name)
        # Remove preview mesh children (model previews parented to this actor)
        _mp.remove_preview(obj)
        # Also delete associated _CAM, _ALIGN, _PIVOT, _LOOK_AT empties for cameras
        suffixes = ["_CAM", "_ALIGN", "_PIVOT", "_LOOK_AT"]
        for suf in suffixes:
            associated = ctx.scene.objects.get(self.obj_name + suf)
            if associated:
                bpy.data.objects.remove(associated, do_unlink=True)
        # Delete the object itself
        bpy.data.objects.remove(obj, do_unlink=True)
        self.report({"INFO"}, f"Deleted '{self.obj_name}'")
        return {"FINISHED"}


class OG_OT_CleanOrphanedLinks(Operator):
    """Remove link entries from VOL_ meshes whose targets have been deleted."""
    bl_idname   = "og.clean_orphaned_links"
    bl_label    = "Clean Orphaned Links"
    bl_description = "Remove links from volumes whose target (camera/checkpoint/enemy) has been deleted"

    def execute(self, ctx):
        cleaned = _clean_orphaned_vol_links(ctx.scene)
        if cleaned:
            msg = ", ".join(f"{v}→{t}" for v, t in cleaned)
            self.report({"INFO"}, f"Cleaned {len(cleaned)} orphaned link(s): {msg}")
        else:
            self.report({"INFO"}, "No orphaned links found")
        return {"FINISHED"}


class OG_OT_RemoveVolLink(Operator):
    """Remove a single link entry from a volume.
    Used by per-link X buttons in the volume / camera / checkpoint / enemy panels.
    Volume is renamed automatically based on remaining link count.
    Removing the last link leaves the volume orphaned (per design — user
    can re-link or delete it manually).
    """
    bl_idname   = "og.remove_vol_link"
    bl_label    = "Remove Link"
    bl_options  = {"REGISTER", "UNDO"}
    bl_description = "Remove this single link from the volume"

    vol_name:    bpy.props.StringProperty()
    target_name: bpy.props.StringProperty()

    def execute(self, ctx):
        vol = ctx.scene.objects.get(self.vol_name)
        if not vol:
            self.report({"ERROR"}, f"Volume '{self.vol_name}' not found")
            return {"CANCELLED"}
        if _vol_remove_link_to(vol, self.target_name):
            self.report({"INFO"}, f"Removed link {self.vol_name} → {self.target_name}")
        else:
            self.report({"WARNING"}, f"No link to {self.target_name} on {self.vol_name}")
        return {"FINISHED"}


class OG_OT_AddLinkFromSelection(Operator):
    """Append a link from a volume to a target (specified by name).
    Used by panel buttons that have both objects in scope.
    """
    bl_idname   = "og.add_link_from_selection"
    bl_label    = "Link"
    bl_options  = {"REGISTER", "UNDO"}
    bl_description = "Append a link from this volume to the named target"

    vol_name:    bpy.props.StringProperty()
    target_name: bpy.props.StringProperty()

    def execute(self, ctx):
        vol    = ctx.scene.objects.get(self.vol_name)
        target = ctx.scene.objects.get(self.target_name)
        if not vol:
            self.report({"ERROR"}, f"Volume '{self.vol_name}' not found")
            return {"CANCELLED"}
        if not target:
            self.report({"ERROR"}, f"Target '{self.target_name}' not found")
            return {"CANCELLED"}
        if not _is_linkable(target):
            self.report({"ERROR"}, f"{self.target_name} is not linkable")
            return {"CANCELLED"}
        if _vol_has_link_to(vol, self.target_name):
            self.report({"WARNING"}, f"{self.vol_name} already linked to {self.target_name}")
            return {"CANCELLED"}
        # Cross-volume duplicate check for camera/checkpoint
        if not _is_aggro_target(target):
            existing = _vol_for_target(ctx.scene, self.target_name)
            if existing and existing != vol:
                self.report({"WARNING"},
                    f"{self.target_name} already linked to {existing.name} — unlink first")
                return {"CANCELLED"}
        links = _vol_links(vol)
        entry = links.add()
        entry.target_name = self.target_name
        entry.behaviour   = "cue-chase"
        _rename_vol_for_links(vol)
        self.report({"INFO"}, f"Linked {vol.name} → {self.target_name}")
        return {"FINISHED"}


class OG_OT_SetActorLink(Operator):
    """Set an entity link slot on an ACTOR_ empty.

    Called from the Actor Links panel when the user clicks 'Link →'.
    source_name = the ACTOR_ empty being edited.
    lump_key / slot_index = which slot to fill.
    target_name = the ACTOR_ empty to link to.
    """
    bl_idname   = "og.set_actor_link"
    bl_label    = "Set Actor Link"
    bl_options  = {"REGISTER", "UNDO"}

    source_name:  bpy.props.StringProperty()
    lump_key:     bpy.props.StringProperty()
    slot_index:   bpy.props.IntProperty(default=0)
    target_name:  bpy.props.StringProperty()

    def execute(self, ctx):
        obj = ctx.scene.objects.get(self.source_name)
        if not obj:
            self.report({"ERROR"}, f"Source '{self.source_name}' not found")
            return {"CANCELLED"}
        target = ctx.scene.objects.get(self.target_name)
        if not target:
            self.report({"ERROR"}, f"Target '{self.target_name}' not found")
            return {"CANCELLED"}
        _actor_set_link(obj, self.lump_key, self.slot_index, self.target_name)
        self.report({"INFO"}, f"Linked {self.source_name} [{self.lump_key}[{self.slot_index}]] → {self.target_name}")
        return {"FINISHED"}


class OG_OT_ClearActorLink(Operator):
    """Remove an entity link slot from an ACTOR_ empty."""
    bl_idname   = "og.clear_actor_link"
    bl_label    = "Clear Actor Link"
    bl_options  = {"REGISTER", "UNDO"}

    source_name: bpy.props.StringProperty()
    lump_key:    bpy.props.StringProperty()
    slot_index:  bpy.props.IntProperty(default=0)

    def execute(self, ctx):
        obj = ctx.scene.objects.get(self.source_name)
        if not obj:
            self.report({"ERROR"}, f"Source '{self.source_name}' not found")
            return {"CANCELLED"}
        _actor_remove_link(obj, self.lump_key, self.slot_index)
        self.report({"INFO"}, f"Cleared {self.source_name} [{self.lump_key}[{self.slot_index}]]")
        return {"FINISHED"}


class OG_OT_SpawnAggroTrigger(Operator):
    """Spawn a new trigger volume at an enemy's location and link it as aggro.
    Used by the per-enemy 'Add Aggro Trigger' button in the selected-actor panel.
    Multiple aggro triggers per enemy are allowed.
    """
    bl_idname   = "og.spawn_aggro_trigger"
    bl_label    = "Add Aggro Trigger"
    bl_options  = {"REGISTER", "UNDO"}
    bl_description = "Spawn a new trigger volume at this enemy and link it as aggro"

    target_name: bpy.props.StringProperty()

    def execute(self, ctx):
        target = ctx.scene.objects.get(self.target_name)
        if not target:
            self.report({"ERROR"}, f"Target '{self.target_name}' not found")
            return {"CANCELLED"}
        if not _is_aggro_target(target):
            self.report({"ERROR"}, f"{self.target_name} is not a nav-enemy")
            return {"CANCELLED"}
        n = len([o for o in _level_objects(ctx.scene)
                 if o.type == "MESH" and o.name.startswith("VOL_")])
        bpy.ops.mesh.primitive_cube_add(size=4.0, location=target.location)
        vol = ctx.active_object
        vol.name = f"VOL_{n}"
        vol["og_vol_id"] = n
        vol.show_name = True
        vol.display_type = "WIRE"
        vol.color = (1.0, 0.3, 0.0, 0.4)   # red-orange aggro
        vol.set_invisible = True
        vol.set_collision = True
        vol.ignore        = True
        links = _vol_links(vol)
        entry = links.add()
        entry.target_name = self.target_name
        entry.behaviour   = "cue-chase"
        _rename_vol_for_links(vol)
        _link_object_to_sub_collection(ctx.scene, vol, *_COL_PATH_TRIGGERS)
        self.report({"INFO"}, f"Added {vol.name} → {self.target_name}")
        return {"FINISHED"}


# ── Entity placement ──────────────────────────────────────────────────────────




class OG_OT_SpawnCamAlign(Operator):
    bl_idname = "og.spawn_cam_align"
    bl_label  = "Add Player Anchor"
    bl_description = (
        "Add a CAMERA_N_ALIGN empty for standoff (side-scroller) mode.\n"
        "Place this at the player position the camera tracks.\n"
        "The camera stays at a fixed offset from this anchor."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("CAMERA_") or sel.type != "CAMERA":
            self.report({"ERROR"}, "Select a CAMERA_N camera first")
            return {"CANCELLED"}
        align_name = sel.name + "_ALIGN"
        if ctx.scene.objects.get(align_name):
            self.report({"WARNING"}, f"{align_name} already exists")
            return {"CANCELLED"}
        bpy.ops.object.empty_add(type="PLAIN_AXES", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = align_name
        o.show_name = True
        o.empty_display_size = 0.5
        o.color = (1.0, 0.6, 0.0, 1.0)
        self.report({"INFO"}, f"Added {align_name}  —  place at player anchor position")
        return {"FINISHED"}


class OG_OT_SpawnCamPivot(Operator):
    bl_idname = "og.spawn_cam_pivot"
    bl_label  = "Add Orbit Pivot"
    bl_description = (
        "Add a CAMERA_N_PIVOT empty for orbit mode.\n"
        "The camera orbits around this world position following the player angle."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("CAMERA_") or sel.type != "CAMERA":
            self.report({"ERROR"}, "Select a CAMERA_N camera first")
            return {"CANCELLED"}
        pivot_name = sel.name + "_PIVOT"
        if ctx.scene.objects.get(pivot_name):
            self.report({"WARNING"}, f"{pivot_name} already exists")
            return {"CANCELLED"}
        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = pivot_name
        o.show_name = True
        o.empty_display_size = 0.5
        o.color = (1.0, 0.2, 0.8, 1.0)
        self.report({"INFO"}, f"Added {pivot_name}  —  place at orbit center point")
        return {"FINISHED"}




class OG_OT_SpawnCamLookAt(Operator):
    bl_idname = "og.spawn_cam_look_at"
    bl_label  = "Add Look-At Target"
    bl_description = (
        "Add an empty that the camera will always face.\n"
        "Bypasses quaternion export — just point the camera at a world position.\n"
        "Place the empty on the object / area you want the camera to look at."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("CAMERA_") or sel.type != "CAMERA":
            self.report({"ERROR"}, "Select a CAMERA_N camera first")
            return {"CANCELLED"}
        look_name = sel.name + "_LOOKAT"
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = look_name
        o.show_name = True
        o.empty_display_size = 0.4
        o.color = (1.0, 0.8, 0.0, 1.0)
        sel["og_cam_look_at"] = look_name
        self.report({"INFO"}, f"Added {look_name}  —  move it to where the camera should look")
        return {"FINISHED"}


class OG_OT_SetCamProp(Operator):
    """Set a string custom property on a CAMERA_ object."""
    bl_idname   = "og.set_cam_prop"
    bl_label    = "Set Camera Property"
    bl_options  = {"REGISTER", "UNDO"}
    cam_name:  bpy.props.StringProperty()
    prop_name: bpy.props.StringProperty()
    str_val:   bpy.props.StringProperty()
    def execute(self, ctx):
        o = ctx.scene.objects.get(self.cam_name)
        if o:
            o[self.prop_name] = self.str_val
        return {"FINISHED"}


class OG_OT_NudgeCamFloat(Operator):
    """Nudge a float custom property on a CAMERA_ object."""
    bl_idname   = "og.nudge_cam_float"
    bl_label    = "Nudge Camera Float"
    bl_options  = {"REGISTER", "UNDO"}
    cam_name:  bpy.props.StringProperty()
    prop_name: bpy.props.StringProperty()
    delta:     bpy.props.FloatProperty()
    def execute(self, ctx):
        o = ctx.scene.objects.get(self.cam_name)
        if o:
            current = float(o.get(self.prop_name, 0.0))
            o[self.prop_name] = round(max(0.0, current + self.delta), 2)
        return {"FINISHED"}




# ── Platform ──────────────────────────────────────────────────────────────────


class OG_OT_NudgeFloatProp(Operator):
    """Nudge a float custom property on the active object by a fixed delta."""
    bl_idname  = "og.nudge_float_prop"
    bl_label   = "Nudge Float Property"
    bl_options = {"REGISTER", "UNDO"}

    prop_name: bpy.props.StringProperty()
    delta:     bpy.props.FloatProperty()
    val_min:   bpy.props.FloatProperty(default=-1e9)
    val_max:   bpy.props.FloatProperty(default=1e9)

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            current = float(o.get(self.prop_name, 0.0))
            o[self.prop_name] = round(max(self.val_min, min(self.val_max, current + self.delta)), 4)
        return {"FINISHED"}


class OG_OT_NudgeIntProp(Operator):
    """Nudge an integer custom property on the active object by a fixed delta."""
    bl_idname  = "og.nudge_int_prop"
    bl_label   = "Nudge Int Property"
    bl_options = {"REGISTER", "UNDO"}

    prop_name: bpy.props.StringProperty()
    delta:     bpy.props.IntProperty()
    val_min:   bpy.props.IntProperty(default=-999)
    val_max:   bpy.props.IntProperty(default=9999)

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            current = int(o.get(self.prop_name, 0))
            o[self.prop_name] = max(self.val_min, min(self.val_max, current + self.delta))
        return {"FINISHED"}


class OG_OT_SetLauncherDest(Operator):
    """Link a DEST_ empty as the destination for a launcher actor."""
    bl_idname  = "og.set_launcher_dest"
    bl_label   = "Set Launcher Destination"
    bl_options = {"REGISTER", "UNDO"}

    launcher_name: bpy.props.StringProperty()
    dest_name:     bpy.props.StringProperty()

    def execute(self, ctx):
        launcher = bpy.data.objects.get(self.launcher_name)
        if launcher:
            launcher["og_launcher_dest"] = self.dest_name
        return {"FINISHED"}


class OG_OT_ClearLauncherDest(Operator):
    """Clear the destination link from a launcher actor."""
    bl_idname  = "og.clear_launcher_dest"
    bl_label   = "Clear Launcher Destination"
    bl_options = {"REGISTER", "UNDO"}

    launcher_name: bpy.props.StringProperty()

    def execute(self, ctx):
        launcher = bpy.data.objects.get(self.launcher_name)
        if launcher and "og_launcher_dest" in launcher:
            del launcher["og_launcher_dest"]
        return {"FINISHED"}


class OG_OT_AddLauncherDest(Operator):
    """Add a DEST_ empty at the 3D cursor and link it to this launcher."""
    bl_idname  = "og.add_launcher_dest"
    bl_label   = "Add Launcher Destination"
    bl_options = {"REGISTER", "UNDO"}

    launcher_name: bpy.props.StringProperty()

    def execute(self, ctx):
        launcher = bpy.data.objects.get(self.launcher_name)
        if not launcher:
            return {"CANCELLED"}
        uid = self.launcher_name.split("_", 2)[-1] if "_" in self.launcher_name else "0"
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        dest = ctx.active_object
        dest.name = f"DEST_{uid}"
        dest.show_name = True
        dest.empty_display_size = 0.5
        dest.color = (1.0, 0.5, 0.0, 1.0)
        launcher["og_launcher_dest"] = dest.name
        self.report({"INFO"}, f"Added {dest.name} and linked to {self.launcher_name}")
        return {"FINISHED"}


class OG_OT_ToggleDoorFlag(Operator):
    """Toggle an eco-door behaviour flag."""
    bl_idname  = "og.toggle_door_flag"
    bl_label   = "Toggle Door Flag"
    bl_options = {"REGISTER", "UNDO"}

    flag: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if not o: return {"CANCELLED"}
        prop = f"og_door_{self.flag}"
        o[prop] = 0 if bool(o.get(prop, False)) else 1
        return {"FINISHED"}


class OG_OT_SetDoorCP(Operator):
    """Set the continue-name for a launcherdoor from a scene checkpoint."""
    bl_idname  = "og.set_door_cp"
    bl_label   = "Set Door Continue Point"
    bl_options = {"REGISTER", "UNDO"}

    actor_name: bpy.props.StringProperty()
    cp_name:    bpy.props.StringProperty()

    def execute(self, ctx):
        o = bpy.data.objects.get(self.actor_name)
        if o:
            o["og_continue_name"] = self.cp_name
        return {"FINISHED"}


class OG_OT_ClearDoorCP(Operator):
    """Clear the continue-name from a launcherdoor."""
    bl_idname  = "og.clear_door_cp"
    bl_label   = "Clear Door Continue Point"
    bl_options = {"REGISTER", "UNDO"}

    actor_name: bpy.props.StringProperty()

    def execute(self, ctx):
        o = bpy.data.objects.get(self.actor_name)
        if o and "og_continue_name" in o:
            del o["og_continue_name"]
        return {"FINISHED"}


class OG_OT_SyncWaterFromObject(Operator):
    """Set the water-vol surface height from the object's world Y position."""
    bl_idname  = "og.sync_water_from_object"
    bl_label   = "Sync Water Surface from Object"
    bl_options = {"REGISTER", "UNDO"}

    actor_name: bpy.props.StringProperty()

    def execute(self, ctx):
        o = bpy.data.objects.get(self.actor_name)
        if not o: return {"CANCELLED"}
        # Blender Z = game Y (up). Use location.z for the surface height.
        surface_y = round(o.location.z, 4)
        o["og_water_surface"] = surface_y
        o["og_water_wade"]    = 0.5
        o["og_water_swim"]    = 1.0
        o["og_water_bottom"]  = round(surface_y - 5.0, 4)
        self.report({"INFO"}, f"Water surface={surface_y:.2f}m  wade={surface_y-0.5:.2f}  swim={surface_y-1.0:.2f}  bottom={surface_y-5.0:.2f}")
        return {"FINISHED"}


class OG_OT_AddWaterVolume(Operator):
    """Add a water volume mesh at the 3D cursor.
Place and scale it to cover your water area — rotation is supported."""
    bl_idname  = "og.add_water_volume"
    bl_label   = "Add Water Volume"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        scene = ctx.scene

        # Name: WATER_0, WATER_1, etc. Count only in current level objects.
        existing = [o for o in _level_objects(scene) if o.name.startswith("WATER_")]
        idx  = len(existing)
        name = f"WATER_{idx}"

        # Create a cube mesh — primitive_cube_add sets it as the active object
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=ctx.scene.cursor.location)
        o      = ctx.active_object
        # Set name twice: Blender resolves data-block name conflicts after first set
        o.name = name
        o.name = name

        # Style: wireframe blue so it doesn't obscure the level
        o.display_type   = "WIRE"
        o.color          = (0.1, 0.4, 1.0, 0.5)
        o.show_name      = True
        # set_invisible tells the level builder to skip this mesh entirely —
        # it exports via extras in the GLB but generates no geometry or collision
        o.set_invisible  = True

        # Lock rotation — water-vol uses an AABB, rotation has no effect in-game
        o.lock_rotation[0] = True
        o.lock_rotation[1] = True
        o.lock_rotation[2] = True

        # Set default water properties from cursor Z (game Y)
        surface_y = round(ctx.scene.cursor.location.z, 4)
        o["og_water_surface"] = surface_y
        o["og_water_wade"]    = 0.5   # depth below surface in meters
        o["og_water_swim"]    = 1.0   # depth below surface in meters
        o["og_water_bottom"]  = round(surface_y - 5.0, 4)  # absolute Y of kill floor
        o["og_water_attack"]  = "drown"

        # Link into the level collection
        _link_object_to_sub_collection(scene, o, *_COL_PATH_WATER)

        self.report({"INFO"}, f"Added {name} — scale to cover your water area, then export")
        return {"FINISHED"}


class OG_OT_SyncWaterFromMesh(Operator):
    """Sync water surface height from the top of the WATER_ mesh bounding box."""
    bl_idname  = "og.sync_water_from_mesh"
    bl_label   = "Sync Surface from Mesh Top"
    bl_options = {"REGISTER", "UNDO"}

    mesh_name: bpy.props.StringProperty()

    def execute(self, ctx):
        import bpy
        o = bpy.data.objects.get(self.mesh_name)
        if not o or o.type != "MESH": return {"CANCELLED"}
        # World-space bounding box corners
        corners = [o.matrix_world @ v.co for v in o.data.vertices]
        ys      = [c.z for c in corners]   # Blender Z = game Y
        top_y   = round(max(ys), 4)
        bot_y   = round(min(ys), 4)
        o["og_water_surface"] = top_y
        o["og_water_wade"]    = 0.5   # depth below surface in meters
        o["og_water_swim"]    = 1.0   # depth below surface in meters
        o["og_water_bottom"]  = bot_y
        self.report({"INFO"}, f"Surface={top_y:.2f}m  wade=0.5m  swim=1.0m  bottom={bot_y:.2f}m")
        return {"FINISHED"}



class OG_OT_SetWaterAttack(Operator):
    """Set the damage type for this water volume."""
    bl_idname  = "og.set_water_attack"
    bl_label   = "Set Water Attack"
    bl_options = {"REGISTER", "UNDO"}
    mesh_name:  bpy.props.StringProperty()
    attack_val: bpy.props.StringProperty()
    def execute(self, ctx):
        o = bpy.data.objects.get(self.mesh_name)
        if o: o["og_water_attack"] = self.attack_val
        return {"FINISHED"}


class OG_OT_SetCrateType(Operator):
    """Set the crate type (look/defense) on the selected crate actor."""
    bl_idname  = "og.set_crate_type"
    bl_label   = "Set Crate Type"
    bl_options = {"REGISTER", "UNDO"}

    crate_type: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        pickup = o.get("og_crate_pickup", "money")
        # Engine auto-upgrades wood→iron when a scout fly is inside.
        # Mirror that logic: if user picks wood and there's a buzzer, force iron.
        if self.crate_type == "wood" and pickup == "buzzer":
            o["og_crate_type"] = "iron"
            self.report({"WARNING"}, "Scout Fly requires Iron box — crate type set to Iron")
        else:
            o["og_crate_type"] = self.crate_type
        return {"FINISHED"}


class OG_OT_SetCratePickup(Operator):
    """Set what drops from this crate when broken."""
    bl_idname  = "og.set_crate_pickup"
    bl_label   = "Set Crate Pickup"
    bl_options = {"REGISTER", "UNDO"}

    pickup_id: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        o["og_crate_pickup"] = self.pickup_id
        # Scout fly always amount 1; reset amount to 1 when switching to buzzer
        if self.pickup_id == "buzzer":
            o["og_crate_pickup_amount"] = 1
            # Enforce iron/steel — wood can't hold a scout fly
            ct = o.get("og_crate_type", "steel")
            if ct == "wood":
                o["og_crate_type"] = "iron"
                self.report({"WARNING"}, "Scout Fly requires Iron box — crate type set to Iron")
        return {"FINISHED"}


class OG_OT_SetCrateAmount(Operator):
    """Set the pickup amount dropped by this crate."""
    bl_idname  = "og.set_crate_amount"
    bl_label   = "Set Crate Amount"
    bl_options = {"REGISTER", "UNDO"}

    delta: bpy.props.IntProperty(default=1)

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        # Scout fly is always 1 — don't allow changes
        if o.get("og_crate_pickup", "money") == "buzzer":
            return {"CANCELLED"}
        current = int(o.get("og_crate_pickup_amount", 1))
        o["og_crate_pickup_amount"] = max(1, min(5, current + self.delta))
        return {"FINISHED"}


class OG_OT_ToggleCrystalUnderwater(Operator):
    """Toggle dark crystal underwater variant (mode=1 lump)."""
    bl_idname  = "og.toggle_crystal_underwater"
    bl_label   = "Toggle Crystal Underwater"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_crystal_underwater"] = 0 if bool(o.get("og_crystal_underwater", False)) else 1
        return {"FINISHED"}


class OG_OT_ToggleCellSkipJump(Operator):
    """Toggle skip-jump-anim fact-option on fuel-cell (options lump bit 2)."""
    bl_idname  = "og.toggle_cell_skip_jump"
    bl_label   = "Toggle Cell Skip Jump"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_cell_skip_jump"] = 0 if bool(o.get("og_cell_skip_jump", False)) else 1
        return {"FINISHED"}


class OG_OT_SetBridgeVariant(Operator):
    """Set the art-name (bridge variant) on a ropebridge actor."""
    bl_idname  = "og.set_bridge_variant"
    bl_label   = "Set Bridge Variant"
    bl_options = {"REGISTER", "UNDO"}

    variant: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_bridge_variant"] = self.variant
        return {"FINISHED"}


class OG_OT_ToggleTurbineParticles(Operator):
    """Toggle particle-select on windturbine actor."""
    bl_idname  = "og.toggle_turbine_particles"
    bl_label   = "Toggle Turbine Particles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_turbine_particles"] = 0 if bool(o.get("og_turbine_particles", False)) else 1
        return {"FINISHED"}


class OG_OT_SetElevatorMode(Operator):
    """Set the mode lump on a cave elevator."""
    bl_idname  = "og.set_elevator_mode"
    bl_label   = "Set Elevator Mode"
    bl_options = {"REGISTER", "UNDO"}

    mode_val: bpy.props.IntProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_elevator_mode"] = self.mode_val
        return {"FINISHED"}


class OG_OT_SetBoneBridgeAnim(Operator):
    """Set the animation-select lump on a mis-bone-bridge."""
    bl_idname  = "og.set_bone_bridge_anim"
    bl_label   = "Set Bone Bridge Anim"
    bl_options = {"REGISTER", "UNDO"}

    anim_val: bpy.props.IntProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_bone_bridge_anim"] = self.anim_val
        return {"FINISHED"}


class OG_OT_SetAltTask(Operator):
    """Set the alt-task lump on oracle / pontoon actors."""
    bl_idname  = "og.set_alt_task"
    bl_label   = "Set Alt Task"
    bl_options = {"REGISTER", "UNDO"}

    task_name: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_alt_task"] = self.task_name
        return {"FINISHED"}


class OG_OT_TogglePlatformWrap(Operator):
    """Toggle wrap-phase (one-way loop vs ping-pong) on the selected platform."""
    bl_idname = "og.toggle_platform_wrap"
    bl_label  = "Toggle Wrap Phase"

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        o["og_sync_wrap"] = 0 if bool(o.get("og_sync_wrap", 0)) else 1
        return {"FINISHED"}


class OG_OT_SetPlatformDefaults(Operator):
    """Reset sync values on the selected platform actor to defaults."""
    bl_idname = "og.set_platform_defaults"
    bl_label  = "Reset Sync Defaults"

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        o["og_sync_period"]   = 4.0
        o["og_sync_phase"]    = 0.0
        o["og_sync_ease_out"] = 0.15
        o["og_sync_ease_in"]  = 0.15
        o["og_sync_wrap"]     = 0
        return {"FINISHED"}


class OG_OT_SpawnPlatform(Operator):
    """Place a platform actor empty at the 3D cursor."""
    bl_idname     = "og.spawn_platform"
    bl_label      = "Add Platform"
    bl_description = "Place a platform actor at the 3D cursor"

    def execute(self, ctx):
        etype = ctx.scene.og_props.platform_type
        einfo = ENTITY_DEFS.get(etype, {})

        # Use count of existing same-type actors as uid, matching OG_OT_SpawnEntity pattern
        n   = len([o for o in _level_objects(ctx.scene) if o.name.startswith(f"ACTOR_{etype}_")])
        uid = f"{n:04d}"

        bpy.ops.object.empty_add(type=einfo.get("shape", "CUBE"),
                                 location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name               = f"ACTOR_{etype}_{uid}"
        o.show_name          = True
        o.empty_display_size = 0.5
        o.color              = einfo.get("color", (0.5, 0.5, 0.8, 1.0))
        if hasattr(o, "show_in_front"):
            o.show_in_front = True
        _link_object_to_sub_collection(ctx.scene, o, *_COL_PATH_SPAWNABLE_PLATFORMS)

        # ---- Set default custom props so UI fields render immediately ------
        if einfo.get("needs_sync"):
            o["og_sync_period"]   = 4.0
            o["og_sync_phase"]    = 0.0
            o["og_sync_ease_out"] = 0.15
            o["og_sync_ease_in"]  = 0.15
            o["og_sync_wrap"]     = 0
        if einfo.get("needs_notice_dist"):
            o["og_notice_dist"] = -1.0

        self.report({"INFO"}, f"Added {o.name}")

        # ---- Model preview ------------------------------------------------
        _prefs = bpy.context.preferences.addons.get("opengoal_tools")
        if _prefs and _prefs.preferences.preview_models:
            try:
                attached = _mp.attach_preview(ctx, etype, o)
                if not attached and ENTITY_DEFS.get(etype, {}).get("glb"):
                    self.report({"WARNING"}, f"No GLB for {etype} — delete decompiler_out/jak1/ and re-run extractor")
            except Exception as e:
                log(f"model_preview: {e}")

        return {"FINISHED"}


# ── Platforms panel ───────────────────────────────────────────────────────────




def _entity_enum_for_cats(cats):
    """Return enum items filtered to the given category set, in display order."""
    return [
        (ek, ei["label"], ei.get("label",""), i)
        for i, (ek, ei) in enumerate(
            (k, v) for k, v in ENTITY_DEFS.items() if v.get("cat") in cats
        )
    ]


def _draw_mat(self, ctx):
    ob = ctx.object
    if not ob or not ob.active_material: return
    mat    = ob.active_material
    layout = self.layout
    layout.prop(mat, "set_invisible")
    layout.prop(mat, "set_collision")
    if mat.set_collision:
        layout.prop(mat, "ignore")
        layout.prop(mat, "collide_mode")
        layout.prop(mat, "collide_material")
        layout.prop(mat, "collide_event")
        layout.prop(mat, "noedge"); layout.prop(mat, "noentity")
        layout.prop(mat, "nolineofsight"); layout.prop(mat, "nocamera")



# ---------------------------------------------------------------------------
# Late operators (navmesh, bake, remove level, refresh)
# ---------------------------------------------------------------------------

class OG_OT_PickNavMesh(Operator):
    """Link the active mesh object as the navmesh for the selected enemy actor.
    Select the enemy, then shift-click the navmesh quad, then click this button."""
    bl_idname      = "og.pick_navmesh"
    bl_label       = "Pick NavMesh Mesh"
    bl_description = "Select enemy actor(s) + navmesh mesh (active), then click"

    actor_name: bpy.props.StringProperty()

    def execute(self, ctx):
        actor = bpy.data.objects.get(self.actor_name)
        if not actor:
            self.report({"ERROR"}, f"Actor not found: {self.actor_name}")
            return {"CANCELLED"}

        # Active object must be a mesh to use as navmesh
        active = ctx.active_object
        if not active or active.type != "MESH":
            self.report({"ERROR"}, "Make the navmesh quad the active object (shift-click it last)")
            return {"CANCELLED"}

        if active == actor:
            self.report({"ERROR"}, "Active object must be the navmesh mesh, not the enemy")
            return {"CANCELLED"}

        # Mark it as a navmesh object
        active["og_navmesh"] = True

        # Link actor to this mesh
        actor["og_navmesh_link"] = active.name
        self.report({"INFO"}, f"Linked {actor.name} → {active.name}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# OPERATOR — Light Bake (Cycles → Vertex Color)
# ---------------------------------------------------------------------------

class OG_OT_BakeLighting(Operator):
    """Bake Cycles lighting to vertex colors on each selected mesh object."""
    bl_idname      = "og.bake_lighting"
    bl_label       = "Bake Lighting"
    bl_description = "Bake Cycles lighting to vertex colors on each selected mesh object"

    def execute(self, ctx):
        scene   = ctx.scene
        props   = scene.og_props
        samples = props.lightbake_samples

        # Collect only MESH objects from the selection
        targets = [o for o in ctx.selected_objects if o.type == "MESH"]
        if not targets:
            self.report({"ERROR"}, "No mesh objects selected")
            return {"CANCELLED"}

        # Store previous render settings
        prev_engine  = scene.render.engine
        prev_samples = scene.cycles.samples
        prev_device  = scene.cycles.device

        scene.render.engine  = "CYCLES"
        scene.cycles.samples = samples

        baked = []
        failed = []

        for obj in targets:
            try:
                # Ensure vertex color layer exists (named "BakedLight")
                vc_name = "BakedLight"
                mesh = obj.data
                if vc_name not in mesh.color_attributes:
                    mesh.color_attributes.new(name=vc_name, type="BYTE_COLOR", domain="CORNER")

                # Set as active render and active display layer
                attr = mesh.color_attributes[vc_name]
                mesh.color_attributes.active_color = attr

                # Deselect all, select only this object, make it active
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                ctx.view_layer.objects.active = obj

                # Run Cycles bake — diffuse pass (combined colour + indirect)
                bpy.ops.object.bake(
                    type="DIFFUSE",
                    pass_filter={"COLOR", "DIRECT", "INDIRECT"},
                    target="VERTEX_COLORS",
                    save_mode="INTERNAL",
                )
                baked.append(obj.name)

            except Exception as exc:
                failed.append(f"{obj.name}: {exc}")

        # Restore render settings
        scene.render.engine  = prev_engine
        scene.cycles.samples = prev_samples

        # Restore original selection
        bpy.ops.object.select_all(action="DESELECT")
        for obj in targets:
            obj.select_set(True)
        if targets:
            ctx.view_layer.objects.active = targets[0]

        if failed:
            self.report({"WARNING"}, f"Baked {len(baked)}, failed: {'; '.join(failed)}")
        else:
            self.report({"INFO"}, f"Baked lighting to vertex colors on: {', '.join(baked)}")

        return {"FINISHED"}


# ---------------------------------------------------------------------------
# PANEL — Light Baking
# ---------------------------------------------------------------------------

class OG_OT_RemoveLevel(Operator):
    """Remove a custom level and all its files from the project."""
    bl_idname   = "og.remove_level"
    bl_label    = "Remove Level"
    bl_options  = {"REGISTER", "UNDO"}
    level_name: bpy.props.StringProperty()

    def invoke(self, ctx, event):
        return ctx.window_manager.invoke_confirm(self, event)

    def execute(self, ctx):
        if not self.level_name:
            self.report({"ERROR"}, "No level name given")
            return {"CANCELLED"}
        msgs = remove_level(self.level_name)
        for m in msgs:
            log(m)
        self.report({"INFO"}, f"Removed level '{self.level_name}'")
        return {"FINISHED"}


class OG_OT_RefreshLevels(Operator):
    """Refresh the custom levels list."""
    bl_idname = "og.refresh_levels"
    bl_label  = "Refresh"
    def execute(self, ctx):
        return {"FINISHED"}





# ---------------------------------------------------------------------------
# GOAL Code Block operators
# ---------------------------------------------------------------------------

_GOAL_BOILERPLATE = """\
;;-*-Lisp-*-
(in-package goal)
;; {name}-obs.gc custom code — injected by OpenGOAL Level Tools
;; Entity type: {etype}
;;
;; Replace this with your deftype + defstate + init-from-entity!
;; See knowledge-base/opengoal/goal-scripting.md for reference.
;;
;; IMPORTANT:
;;   • First field starts at offset-assert 176 (end of process-drawable base)
;;   • Each state :code loop must call (suspend) or the game will freeze
;;   • Compile errors appear in the goalc build log, not in Blender
;;   • The entity type name in your deftype must match what you put in ACTOR_<n>_<uid>
;;     i.e. ACTOR_{etype}_0 expects a (deftype {etype} (process-drawable) ...)

(deftype {etype} (process-drawable)
  ()   ;; add fields here starting at :offset-assert 176
  (:states {etype}-idle))

(defstate {etype}-idle ({etype})
  :code
    (behavior ()
      (loop (suspend))))

(defmethod init-from-entity! ((this {etype}) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (go {etype}-idle)
  (none))
"""


class OG_OT_CreateGoalCodeBlock(bpy.types.Operator):
    """Create a new Blender text block pre-filled with GOAL boilerplate and assign it to this actor"""
    bl_idname = "og.create_goal_code_block"
    bl_label  = "Create GOAL Code Block"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        if not sel or sel.type != "EMPTY":
            return False
        parts = sel.name.split("_", 2)
        return (len(parts) >= 3 and parts[0] == "ACTOR"
                and "_wp_" not in sel.name and "_wpb_" not in sel.name)

    def execute(self, ctx):
        sel   = ctx.active_object
        parts = sel.name.split("_", 2)
        etype = parts[1]
        uid   = parts[2] if len(parts) >= 3 else "0"

        # Generate a unique text block name
        block_name = f"{etype}-goal-code"
        counter    = 0
        base_name  = block_name
        while block_name in bpy.data.texts:
            counter   += 1
            block_name = f"{base_name}-{counter}"

        # Create and fill the text block
        txt = bpy.data.texts.new(block_name)
        txt.write(_GOAL_BOILERPLATE.format(name=etype, etype=etype, uid=uid))
        txt.cursor_set(0)

        # Assign to this object
        sel.og_goal_code_ref.text_block = txt
        sel.og_goal_code_ref.enabled    = True

        self.report({"INFO"}, f"Created GOAL code block '{block_name}' — open it in the Text Editor to edit")
        return {"FINISHED"}


class OG_OT_ClearGoalCodeBlock(bpy.types.Operator):
    """Disconnect the GOAL code block from this actor (does not delete the text block)"""
    bl_idname  = "og.clear_goal_code_block"
    bl_label   = "Disconnect GOAL Code"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and sel.type == "EMPTY"
                and hasattr(sel, "og_goal_code_ref")
                and sel.og_goal_code_ref.text_block is not None)

    def execute(self, ctx):
        ctx.active_object.og_goal_code_ref.text_block = None
        return {"FINISHED"}


class OG_OT_OpenGoalCodeInEditor(bpy.types.Operator):
    """Switch an open Text Editor area to show this actor's GOAL code block, or report instructions if none is open"""
    bl_idname  = "og.open_goal_code_in_editor"
    bl_label   = "Open in Text Editor"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, ctx):
        sel = ctx.active_object
        return (sel is not None
                and hasattr(sel, "og_goal_code_ref")
                and sel.og_goal_code_ref.text_block is not None)

    def execute(self, ctx):
        txt = ctx.active_object.og_goal_code_ref.text_block
        for window in ctx.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "TEXT_EDITOR":
                    area.spaces.active.text = txt
                    self.report({"INFO"}, f"Showing '{txt.name}' in Text Editor")
                    return {"FINISHED"}
        self.report({"INFO"},
                    f"Open a Text Editor area (Shift+F11) then re-click. "
                    f"Block name: '{txt.name}'")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Custom GOAL Type spawn operator
# ---------------------------------------------------------------------------

import re as _re

_VALID_ETYPE_RE = _re.compile(r'^[a-z][a-z0-9\-]*$')


class OG_OT_SpawnCustomType(bpy.types.Operator):
    """Spawn an ACTOR_ empty for a user-defined GOAL type.

    The type name must:
      • be lowercase letters, digits, and hyphens only
      • not already exist in the addon's built-in entity list
      • match the deftype name written in your GOAL code block exactly

    The empty is placed at the 3D cursor and named ACTOR_<typename>_<n>.
    Attach a GOAL code block via the GOAL Code sub-panel to define its behaviour.
    """
    bl_idname  = "og.spawn_custom_type"
    bl_label   = "Spawn Custom Type"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, ctx):
        name = (ctx.scene.og_props.custom_type_name or "").strip()
        return bool(name)

    def execute(self, ctx):
        etype = (ctx.scene.og_props.custom_type_name or "").strip().lower()

        if not etype:
            self.report({"ERROR"}, "Enter a type name first")
            return {"CANCELLED"}

        if not _VALID_ETYPE_RE.match(etype):
            self.report({"ERROR"},
                f"'{etype}' is not a valid type name. "
                "Use lowercase letters, digits, and hyphens only (e.g. 'spin-prop').")
            return {"CANCELLED"}

        if not _is_custom_type(etype):
            self.report({"ERROR"},
                f"'{etype}' is already a built-in entity type. "
                "Use the normal Spawn sub-panels to place it, or choose a different name.")
            return {"CANCELLED"}

        n = len([o for o in _level_objects(ctx.scene)
                 if o.name.startswith(f"ACTOR_{etype}_")])

        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name               = f"ACTOR_{etype}_{n}"
        o.show_name          = True
        o.empty_display_size = 0.5
        # Distinctive yellow-green colour so custom types stand out from built-ins
        o.color = (0.6, 1.0, 0.2, 1.0)

        # Link into the level collection (Props sub-collection is the best fit
        # for a generic unknown type — no AI, no navmesh assumed)
        _link_object_to_sub_collection(
            ctx.scene, o, *_col_path_for_entity("evilplant"))  # reuse Props path

        self.report({"INFO"},
            f"Spawned '{o.name}' — open the GOAL Code panel to assign a code block, "
            f"then define 'deftype {etype}' in that block.")
        return {"FINISHED"}
