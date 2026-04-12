bl_info = {
    "name": "OpenGOAL Level Tools",
    "author": "water111 / JohnCheathem",
    "version": (1, 2, 0),
    "blender": (4, 4, 0),
    "location": "View3D > N-Panel > OpenGOAL",
    "description": "Jak 1 level export, actor placement, build and launch tools",
    "category": "Development",
}

import bpy, os, re, json, socket, subprocess, threading, time, math, mathutils
from pathlib import Path
from bpy.props import (StringProperty, BoolProperty, IntProperty,
                       EnumProperty, PointerProperty, FloatProperty,
                       CollectionProperty)
from bpy.types import Panel, Operator, PropertyGroup, AddonPreferences

from .data import (
    AGGRO_EVENT_ENUM_ITEMS,
    ALL_SFX_ITEMS,
    CRATE_ITEMS,
    CRATE_PICKUP_ITEMS,
    ENEMY_ENUM_ITEMS,
    ENTITY_DEFS,
    ENTITY_ENUM_ITEMS,
    ENTITY_WIKI,
    ETYPE_AG,
    ETYPE_CODE,
    IS_PROP_TYPES,
    LEVEL_BANKS,
    LUMP_REFERENCE,
    LUMP_TYPE_ITEMS,
    NAV_UNSAFE_TYPES,
    NEEDS_PATHB_TYPES,
    NEEDS_PATH_TYPES,
    NPC_ENUM_ITEMS,
    PICKUP_ENUM_ITEMS,
    PLATFORM_ENUM_ITEMS,
    PROP_ENUM_ITEMS,
    SBK_SOUNDS,
    _LUMP_HARDCODED_KEYS,
    _actor_get_link,
    _actor_has_links,
    _actor_link_slots,
    _actor_links,
    _actor_remove_link,
    _actor_set_link,
    _aggro_event_id,
    _build_actor_link_lumps,
    _lump_ref_for_etype,
    _parse_lump_row,
    needed_tpages,
    pat_events,
    pat_modes,
    pat_surfaces,
)
from .collections import (
    _COL_PATH_SPAWNABLE_ENEMIES, _COL_PATH_SPAWNABLE_PLATFORMS,
    _COL_PATH_SPAWNABLE_PROPS, _COL_PATH_SPAWNABLE_NPCS,
    _COL_PATH_SPAWNABLE_PICKUPS, _COL_PATH_TRIGGERS, _COL_PATH_CAMERAS,
    _COL_PATH_SPAWNS, _COL_PATH_SOUND_EMITTERS, _COL_PATH_GEO_SOLID,
    _COL_PATH_GEO_COLLISION, _COL_PATH_GEO_VISUAL, _COL_PATH_GEO_REFERENCE,
    _COL_PATH_WAYPOINTS, _COL_PATH_NAVMESHES, _COL_PATH_EXPORT_AS,
    _ENTITY_CAT_TO_COL_PATH, _LEVEL_COL_DEFAULTS,
    _all_level_collections, _active_level_col, _col_is_no_export,
    _recursive_col_objects, _level_objects, _ensure_sub_collection,
    _link_object_to_sub_collection, _col_path_for_entity, _classify_object,
    _get_level_prop, _set_level_prop, _active_level_items,
    _set_blender_active_collection, _get_death_plane, _set_death_plane,
    _on_active_level_changed,
)
from .export import (
    # Navmesh geometry
    _navmesh_compute, _navmesh_to_goal,
    # Core collect / write pipeline
    _canonical_actor_objects, _collect_navmesh_actors,
    _camera_aabb_to_planes, collect_aggro_triggers, collect_cameras,
    collect_spawns, collect_actors, collect_ambients, collect_nav_mesh_geometry,
    needed_ags, needed_code, write_jsonc, write_gd, _make_continues,
    patch_level_info, patch_game_gp, discover_custom_levels,
    remove_level, export_glb,
    # Actor-type predicates
    _actor_uses_waypoints, _actor_uses_navmesh, _actor_is_platform,
    _actor_is_launcher, _actor_is_spawner, _actor_is_enemy,
    _actor_supports_aggro_trigger,
    # Volume link helpers
    _vol_links, _vol_link_targets, _vol_has_link_to, _rename_vol_for_links,
    _vols_linking_to, _vol_get_link_to, _vol_remove_link_to, _classify_target,
    _clean_orphaned_vol_links,
    # Name / path helpers used by operators and panels
    _nick, _iso, _lname, _ldir, _goal_src, _level_info, _game_gp,
    _levels_dir, _entity_gc,
)
from .build import (
    _EXE, GOALC_PORT, GOALC_TIMEOUT,
    _BUILD_STATE, _PLAY_STATE,
    _exe_root, _data_root, _data, _gk, _goalc,
    _user_dir, kill_gk, launch_gk,
    goalc_send, goalc_ok, launch_goalc,
    _bg_build, _bg_play, _bg_geo_rebuild, _bg_build_and_play,
)
from .properties import (
    OGPreferences, OGProperties,
    OGLumpRow, OG_OT_AddLumpRow, OG_OT_RemoveLumpRow,
    OG_UL_LumpRows, OGActorLink, OGVolLink,
)
from .operators import (
    _draw_mat,
    OG_OT_CreateLevel, OG_OT_AssignCollectionAsLevel,
    OG_OT_SetActiveLevel, OG_OT_NudgeLevelProp, OG_OT_DeleteLevel,
    OG_OT_AddCollectionToLevel, OG_OT_RemoveCollectionFromLevel,
    OG_OT_RemoveCollectionFromLevelActive, OG_OT_ToggleCollectionNoExport,
    OG_OT_SelectLevelCollection, OG_OT_EditLevel,
    OG_OT_SpawnPlayer, OG_OT_SpawnCheckpoint, OG_OT_SpawnCamAnchor,
    OG_OT_SpawnVolume, OG_OT_SpawnVolumeAutoLink, OG_OT_LinkVolume,
    OG_OT_UnlinkVolume, OG_OT_CleanOrphanedLinks,
    OG_OT_RemoveVolLink, OG_OT_AddLinkFromSelection, OG_OT_SpawnAggroTrigger,
    OG_OT_SetActorLink, OG_OT_ClearActorLink,
    OG_OT_SelectAndFrame, OG_OT_DeleteObject,
    OG_OT_SpawnEntity, OG_OT_ClearPreviews,
    OG_OT_SpawnCamera, OG_OT_SpawnCamAlign, OG_OT_SpawnCamPivot,
    OG_OT_SpawnCamLookAt, OG_OT_SetCamProp, OG_OT_NudgeCamFloat,
    OG_OT_NudgeFloatProp, OG_OT_NudgeIntProp,
    OG_OT_SetLauncherDest, OG_OT_ClearLauncherDest, OG_OT_AddLauncherDest,
    OG_OT_ToggleDoorFlag, OG_OT_SetDoorCP, OG_OT_ClearDoorCP,
    OG_OT_SyncWaterFromObject, OG_OT_AddWaterVolume, OG_OT_SyncWaterFromMesh, OG_OT_SetWaterAttack, OG_OT_SetCrateType, OG_OT_SetCratePickup, OG_OT_SetCrateAmount,
    OG_OT_ToggleCrystalUnderwater, OG_OT_ToggleCellSkipJump,
    OG_OT_SetBridgeVariant, OG_OT_ToggleTurbineParticles,
    OG_OT_SetElevatorMode, OG_OT_SetBoneBridgeAnim, OG_OT_SetAltTask,
    OG_OT_TogglePlatformWrap, OG_OT_SetPlatformDefaults, OG_OT_SpawnPlatform,
    OG_OT_AddWaypoint, OG_OT_DeleteWaypoint,
    OG_OT_MarkNavMesh, OG_OT_UnmarkNavMesh,
    OG_OT_LinkNavMesh, OG_OT_UnlinkNavMesh, OG_OT_PickNavMesh,
    OG_OT_ExportBuild, OG_OT_GeoRebuild, OG_OT_Play, OG_OT_PlayAutoLoad,
    OG_OT_ExportBuildPlay,
    OG_OT_OpenFolder, OG_OT_OpenFile,
    OG_OT_BakeLighting, OG_OT_PickSound, OG_OT_AddSoundEmitter,
    OG_OT_RemoveLevel, OG_OT_RefreshLevels,
)
from .panels import (
    OG_OT_ReloadAddon, OG_OT_CleanLevelFiles,
    OG_OT_UseLumpRef, OG_OT_SortLevelObjects,
    OG_PT_Level, OG_PT_SpawnLevelFlow, OG_PT_LevelManagerSub,
    OG_PT_CollectionProperties, OG_PT_DisableExport,
    OG_PT_CleanSub, OG_PT_LightBakingSub, OG_PT_Music,
    OG_PT_Spawn, OG_PT_SpawnSearch, OG_PT_SpawnLimitSearch, OG_OT_SearchSelectEntity,
    OG_PT_VertexExport, OG_OT_AssignVertexExport, OG_OT_ClearVertexExport,
    OG_PT_SpawnEnemies, OG_PT_SpawnPlatforms,
    OG_PT_SpawnProps, OG_PT_SpawnNPCs, OG_PT_SpawnPickups, OG_PT_SpawnSounds,
    OG_PT_Camera, OG_PT_Triggers,
    OG_PT_SelectedObject, OG_PT_SelectedCollision,
    OG_PT_SelectedLightBaking, OG_PT_SelectedNavMeshTag,
    OG_PT_ActorActivation, OG_PT_ActorTriggerBehaviour, OG_PT_ActorNavMesh,
    OG_PT_ActorLinks, OG_PT_ActorPlatform, OG_PT_ActorCrate,
    OG_PT_ActorDarkCrystal, OG_PT_ActorFuelCell, OG_PT_ActorLauncher,
    OG_PT_ActorSpawner, OG_PT_ActorEcoDoor, OG_PT_ActorWaterVol, OG_PT_WaterMesh, OG_PT_SpawnWater,
    OG_PT_ActorLauncherDoor, OG_PT_ActorPlatFlip, OG_PT_ActorOrbCache,
    OG_PT_ActorWhirlpool, OG_PT_ActorRopeBridge, OG_PT_ActorOrbitPlat,
    OG_PT_ActorSquarePlatform, OG_PT_ActorCaveFlamePots, OG_PT_ActorShover,
    OG_PT_ActorLavaMoving, OG_PT_ActorWindTurbine, OG_PT_ActorCaveElevator,
    OG_PT_ActorMisBoneBridge, OG_PT_ActorBreakaway,
    OG_PT_ActorSunkenFish, OG_PT_ActorSharkey,
    OG_PT_ActorTaskGated, OG_PT_ActorVisibility, OG_PT_ActorWaypoints,
    OG_PT_SpawnSettings, OG_PT_CheckpointSettings, OG_PT_AmbientEmitter,
    OG_PT_CameraSettings, OG_PT_CamAnchorInfo,
    OG_PT_VolumeLinks, OG_PT_NavmeshInfo,
    OG_PT_SelectedLumps, OG_PT_SelectedLumpReference,
    OG_PT_Waypoints, OG_PT_BuildPlay, OG_PT_DevTools, OG_PT_Collision,
)

from .utils import _preview_collections, _load_previews, _unload_previews
from . import model_preview as _mp

# bpy.utils.previews is the correct Blender API for custom images in panels.
# icon_id is just an integer texture lookup — zero overhead in draw().


# ---------------------------------------------------------------------------
# REGISTER / UNREGISTER
# ---------------------------------------------------------------------------

classes = (
    OGLumpRow,
    OGActorLink,
    OGVolLink,
    OGPreferences, OGProperties,
    OG_OT_AddLumpRow, OG_OT_RemoveLumpRow, OG_OT_UseLumpRef,
    OG_UL_LumpRows,
    OG_OT_ReloadAddon, OG_OT_CleanLevelFiles,
    OG_OT_SpawnPlayer, OG_OT_SpawnCheckpoint, OG_OT_SpawnCamAnchor,
    OG_OT_SpawnVolume, OG_OT_SpawnVolumeAutoLink, OG_OT_LinkVolume, OG_OT_UnlinkVolume, OG_OT_CleanOrphanedLinks,
    OG_OT_RemoveVolLink, OG_OT_AddLinkFromSelection, OG_OT_SpawnAggroTrigger,
    OG_OT_SetActorLink, OG_OT_ClearActorLink,
    OG_OT_SelectAndFrame, OG_OT_DeleteObject,
    OG_OT_SpawnEntity, OG_OT_ClearPreviews,
    OG_OT_SpawnCamera, OG_OT_SpawnCamAlign, OG_OT_SpawnCamPivot,
    OG_OT_SpawnCamLookAt,
    OG_OT_SetCamProp, OG_OT_NudgeCamFloat,
    OG_OT_NudgeFloatProp,
    OG_OT_NudgeIntProp,
    OG_OT_SetLauncherDest, OG_OT_ClearLauncherDest, OG_OT_AddLauncherDest,
    OG_OT_ToggleDoorFlag, OG_OT_SetDoorCP, OG_OT_ClearDoorCP,
    OG_OT_SyncWaterFromObject, OG_OT_AddWaterVolume, OG_OT_SyncWaterFromMesh, OG_OT_SetWaterAttack,
    OG_OT_SetCrateType,
    OG_OT_SetCratePickup,
    OG_OT_SetCrateAmount,
    OG_OT_ToggleCrystalUnderwater, OG_OT_ToggleCellSkipJump,
    OG_OT_SetBridgeVariant, OG_OT_ToggleTurbineParticles,
    OG_OT_SetElevatorMode, OG_OT_SetBoneBridgeAnim, OG_OT_SetAltTask,
    OG_OT_TogglePlatformWrap, OG_OT_SetPlatformDefaults, OG_OT_SpawnPlatform,
    OG_OT_AddWaypoint, OG_OT_DeleteWaypoint,
    OG_OT_MarkNavMesh, OG_OT_UnmarkNavMesh,
    OG_OT_LinkNavMesh, OG_OT_UnlinkNavMesh,
    OG_OT_PickNavMesh,
    OG_OT_ExportBuild, OG_OT_GeoRebuild, OG_OT_Play, OG_OT_PlayAutoLoad,
    OG_OT_ExportBuildPlay,
    OG_OT_OpenFolder, OG_OT_OpenFile,
    OG_OT_BakeLighting,
    OG_OT_PickSound,
    OG_OT_AddSoundEmitter,
    OG_OT_RemoveLevel,
    OG_OT_RefreshLevels,
    # ── Collection system operators ──────────────────────────────────────
    OG_OT_CreateLevel, OG_OT_AssignCollectionAsLevel,
    OG_OT_SetActiveLevel, OG_OT_NudgeLevelProp,
    OG_OT_DeleteLevel,
    OG_OT_SortLevelObjects,
    OG_OT_AddCollectionToLevel, OG_OT_RemoveCollectionFromLevel,
    OG_OT_RemoveCollectionFromLevelActive,
    OG_OT_ToggleCollectionNoExport, OG_OT_SelectLevelCollection,
    OG_OT_EditLevel,
    # ── Panels ──────────────────────────────────────────────────────────
    # Level group
    OG_PT_Level,
    OG_PT_LevelManagerSub,
    OG_PT_CollectionProperties,
    OG_PT_DisableExport,
    OG_PT_CleanSub,
    OG_PT_LightBakingSub,
    OG_PT_Music,
    # Spawn group
    OG_PT_Spawn,
    OG_OT_SearchSelectEntity,
    OG_PT_SpawnSearch,
    OG_PT_SpawnLimitSearch,
    OG_PT_SpawnEnemies,
    OG_PT_SpawnPlatforms,
    OG_PT_SpawnProps,
    OG_PT_SpawnNPCs,
    OG_PT_SpawnPickups,
    OG_PT_SpawnSounds,
    OG_PT_SpawnLevelFlow,
    OG_PT_Camera,
    OG_PT_Triggers,
    # Standalone panels
    OG_PT_SelectedObject,
    OG_PT_VertexExport,
    OG_OT_AssignVertexExport,
    OG_OT_ClearVertexExport,
    OG_PT_SelectedCollision,
    OG_PT_SelectedLightBaking,
    OG_PT_SelectedNavMeshTag,
    # Object-type sub-panels
    OG_PT_ActorActivation,
    OG_PT_ActorTriggerBehaviour,
    OG_PT_ActorNavMesh,
    OG_PT_ActorLinks,
    OG_PT_ActorPlatform,
    OG_PT_ActorCrate,
    OG_PT_ActorDarkCrystal,
    OG_PT_ActorFuelCell,
    OG_PT_ActorLauncher,
    OG_PT_ActorSpawner,
    OG_PT_ActorEcoDoor,
    OG_PT_ActorWaterVol,
    OG_PT_WaterMesh,
    OG_PT_SpawnWater,
    OG_PT_ActorLauncherDoor,
    OG_PT_ActorPlatFlip,
    OG_PT_ActorOrbCache,
    OG_PT_ActorWhirlpool,
    OG_PT_ActorRopeBridge,
    OG_PT_ActorOrbitPlat,
    OG_PT_ActorSquarePlatform,
    OG_PT_ActorCaveFlamePots,
    OG_PT_ActorShover,
    OG_PT_ActorLavaMoving,
    OG_PT_ActorWindTurbine,
    OG_PT_ActorCaveElevator,
    OG_PT_ActorMisBoneBridge,
    OG_PT_ActorBreakaway,
    OG_PT_ActorSunkenFish,
    OG_PT_ActorSharkey,
    OG_PT_ActorTaskGated,
    OG_PT_ActorVisibility,
    OG_PT_ActorWaypoints,
    OG_PT_SpawnSettings,
    OG_PT_CheckpointSettings,
    OG_PT_AmbientEmitter,
    OG_PT_CameraSettings,
    OG_PT_CamAnchorInfo,
    OG_PT_VolumeLinks,
    OG_PT_NavmeshInfo,
    # Lump sub-panels
    OG_PT_SelectedLumps,
    OG_PT_SelectedLumpReference,
    OG_PT_Waypoints,
    OG_PT_BuildPlay,
    OG_PT_DevTools,
    OG_PT_Collision,
)

def register():
    _load_previews()
    _mp.register_handler()
    for cls in classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
        bpy.utils.register_class(cls)
    bpy.types.Scene.og_props = PointerProperty(type=OGProperties)

    bpy.types.Material.set_invisible    = bpy.props.BoolProperty(name="Invisible")
    bpy.types.Material.set_collision    = bpy.props.BoolProperty(name="Apply Collision Properties")
    bpy.types.Material.ignore           = bpy.props.BoolProperty(name="ignore")
    bpy.types.Material.noedge           = bpy.props.BoolProperty(name="No-Edge")
    bpy.types.Material.noentity         = bpy.props.BoolProperty(name="No-Entity")
    bpy.types.Material.nolineofsight    = bpy.props.BoolProperty(name="No-LOS")
    bpy.types.Material.nocamera         = bpy.props.BoolProperty(name="No-Camera")
    bpy.types.Material.collide_material = bpy.props.EnumProperty(items=pat_surfaces, name="Material")
    bpy.types.Material.collide_event    = bpy.props.EnumProperty(items=pat_events,   name="Event")
    bpy.types.Material.collide_mode     = bpy.props.EnumProperty(items=pat_modes,    name="Mode")
    bpy.types.MATERIAL_PT_custom_props.prepend(_draw_mat)

    bpy.types.Object.set_invisible         = bpy.props.BoolProperty(name="Invisible")
    bpy.types.Object.set_collision         = bpy.props.BoolProperty(name="Apply Collision Properties")
    bpy.types.Object.enable_custom_weights = bpy.props.BoolProperty(name="Use Custom Bone Weights")
    bpy.types.Object.copy_eye_draws        = bpy.props.BoolProperty(name="Copy Eye Draws")
    bpy.types.Object.copy_mod_draws        = bpy.props.BoolProperty(name="Copy Mod Draws")
    bpy.types.Object.ignore                = bpy.props.BoolProperty(name="ignore")
    bpy.types.Object.noedge                = bpy.props.BoolProperty(name="No-Edge")
    bpy.types.Object.noentity              = bpy.props.BoolProperty(name="No-Entity")
    bpy.types.Object.nolineofsight         = bpy.props.BoolProperty(name="No-LOS")
    bpy.types.Object.nocamera              = bpy.props.BoolProperty(name="No-Camera")
    bpy.types.Object.collide_material      = bpy.props.EnumProperty(items=pat_surfaces, name="Material")
    bpy.types.Object.collide_event         = bpy.props.EnumProperty(items=pat_events,   name="Event")
    bpy.types.Object.collide_mode          = bpy.props.EnumProperty(items=pat_modes,    name="Mode")

    # Trigger volume link collection — registered after OGVolLink is in classes tuple.
    # Each VOL_ mesh holds a list of (target_name, behaviour) entries.
    bpy.types.Object.og_vol_links          = bpy.props.CollectionProperty(type=OGVolLink)

    # Actor entity links — registered after OGActorLink is in classes tuple.
    # Each ACTOR_ empty holds a list of (lump_key, slot_index, target_name) entries.
    bpy.types.Object.og_actor_links        = bpy.props.CollectionProperty(type=OGActorLink)

    # Custom lump rows — registered after OGLumpRow is in classes tuple.
    # Each ACTOR_ empty holds a list of (key, ltype, value) assisted lump entries.
    bpy.types.Object.og_lump_rows          = bpy.props.CollectionProperty(type=OGLumpRow)
    bpy.types.Object.og_lump_rows_index    = bpy.props.IntProperty(name="Active Lump Row", default=0)

    # Vertex-export: mesh objects tagged with an entity type export each vertex as an actor.
    bpy.types.Object.og_vertex_export_etype  = bpy.props.StringProperty(name="Export As Entity", default="")
    bpy.types.Object.og_vertex_export_search = bpy.props.StringProperty(name="", default="")

    bpy.types.Collection.og_no_export      = bpy.props.BoolProperty(
        name="Exclude from Export",
        description="When enabled, this collection and its contents are excluded from level export",
        default=False)

def unregister():
    _unload_previews()
    _mp.unregister_handler()
    bpy.types.MATERIAL_PT_custom_props.remove(_draw_mat)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "og_props"):
        del bpy.types.Scene.og_props
    for a in ("set_invisible","set_collision","ignore","noedge","noentity",
              "nolineofsight","nocamera","collide_material","collide_event","collide_mode"):
        try: delattr(bpy.types.Material, a)
        except Exception: pass
    for a in ("set_invisible","set_collision","ignore","noedge","noentity",
              "nolineofsight","nocamera","collide_material","collide_event","collide_mode",
              "enable_custom_weights","copy_eye_draws","copy_mod_draws","og_vol_links",
              "og_actor_links","og_lump_rows","og_lump_rows_index",
              "og_vertex_export_etype","og_vertex_export_search",
              "og_spring_height","og_launcher_dest","og_launcher_fly_time","og_num_lurkers",
              "og_door_auto_close","og_door_one_way","og_continue_name",
              "og_water_surface","og_water_wade","og_water_swim","og_water_bottom",
              "og_flip_delay_down","og_flip_delay_up","og_orb_count",
              "og_whirl_speed","og_whirl_var","og_vis_dist",
              "og_crystal_underwater","og_cell_skip_jump","og_flip_sync_pct",
              "og_bridge_variant","og_orbit_scale","og_orbit_timeout",
              "og_sq_down","og_sq_up","og_flame_shove","og_flame_period",
              "og_flame_phase","og_flame_pause","og_shover_force","og_shover_rot",
              "og_move_speed","og_turbine_particles",
              "og_elevator_mode","og_elevator_rot",
              "og_bone_bridge_anim","og_breakaway_h1","og_breakaway_h2",
              "og_fish_count","og_shark_scale","og_shark_delay",
              "og_shark_distance","og_shark_speed","og_alt_task"):
        try: delattr(bpy.types.Object, a)
        except Exception: pass
    try: delattr(bpy.types.Collection, "og_no_export")
    except Exception: pass

if __name__ == "__main__":
    register()
