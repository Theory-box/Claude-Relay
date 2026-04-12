# ---------------------------------------------------------------------------
# collections.py — OpenGOAL Level Tools
# Collection path constants, level collection hierarchy helpers,
# object classification, and level property accessors.
# ---------------------------------------------------------------------------

import bpy
from .data import ENTITY_DEFS

# Mapping from collection custom-property keys to OGProperties attribute names.
# Shared by _get_level_prop and _set_level_prop — defined once here.
_LEVEL_PROP_KEY_MAP = {
    "og_level_name":        "level_name",
    "og_base_id":           "base_id",
    "og_bottom_height":     "bottom_height",
    "og_vis_nick_override": "vis_nick_override",
    "og_sound_bank_1":      "sound_bank_1",
    "og_sound_bank_2":      "sound_bank_2",
    "og_music_bank":        "music_bank",
}

_COL_PATH_SPAWNABLE_ENEMIES   = ("Spawnables", "Enemies")
_COL_PATH_SPAWNABLE_PLATFORMS = ("Spawnables", "Platforms")
_COL_PATH_SPAWNABLE_PROPS     = ("Spawnables", "Props & Objects")
_COL_PATH_SPAWNABLE_NPCS      = ("Spawnables", "NPCs")
_COL_PATH_SPAWNABLE_PICKUPS   = ("Spawnables", "Pickups")
_COL_PATH_TRIGGERS            = ("Triggers",)
_COL_PATH_CAMERAS             = ("Cameras",)
_COL_PATH_SPAWNS              = ("Spawns",)
_COL_PATH_SOUND_EMITTERS      = ("Sound Emitters",)
_COL_PATH_WATER               = ("Water Volumes",)
_COL_PATH_GEO_SOLID           = ("Geometry", "Solid")
_COL_PATH_GEO_COLLISION       = ("Geometry", "Collision Only")
_COL_PATH_GEO_VISUAL          = ("Geometry", "Visual Only")
_COL_PATH_GEO_REFERENCE       = ("Geometry", "Reference")
_COL_PATH_WAYPOINTS           = ("Waypoints",)
_COL_PATH_NAVMESHES           = ("NavMeshes",)
_COL_PATH_EXPORT_AS           = ("Export As",)

# Entity category → sub-collection path
_ENTITY_CAT_TO_COL_PATH = {
    "Enemies":   _COL_PATH_SPAWNABLE_ENEMIES,
    "Bosses":    _COL_PATH_SPAWNABLE_ENEMIES,
    "Platforms":  _COL_PATH_SPAWNABLE_PLATFORMS,
    "Props":     _COL_PATH_SPAWNABLE_PROPS,
    "Objects":   _COL_PATH_SPAWNABLE_PROPS,
    "Debug":     _COL_PATH_SPAWNABLE_PROPS,
    "NPCs":      _COL_PATH_SPAWNABLE_NPCS,
    "Pickups":   _COL_PATH_SPAWNABLE_PICKUPS,
}

# Default custom property values for level collections
_LEVEL_COL_DEFAULTS = {
    "og_is_level":          True,
    "og_level_name":        "my-level",
    "og_base_id":           10000,
    "og_bottom_height":     -20.0,
    "og_vis_nick_override": "",
    "og_sound_bank_1":      "none",
    "og_sound_bank_2":      "none",
    "og_music_bank":        "none",
}


def _all_level_collections(scene):
    """Return list of top-level collections marked as levels, sorted by name."""
    result = []
    for col in scene.collection.children:
        if col.get("og_is_level", False):
            result.append(col)
    result.sort(key=lambda c: c.name)
    return result


def _active_level_col(scene):
    """Return the active level collection, or None if not in collection mode.

    If no collection has og_is_level=True, returns None → fallback to v1.1.0.
    """
    levels = _all_level_collections(scene)
    if not levels:
        return None
    # Read the active_level identifier from scene props
    active_name = scene.og_props.active_level if hasattr(scene, "og_props") else ""
    for col in levels:
        if col.name == active_name:
            return col
    # active_level doesn't match any existing collection → return first
    return levels[0]


def _col_is_no_export(col):
    """Check if a collection is marked as no-export."""
    return bool(getattr(col, "og_no_export", False))


def _recursive_col_objects(col, exclude_no_export=True):
    """Return all objects in a collection and its children, deduplicated.

    If exclude_no_export=True, skips sub-collections with og_no_export=True.
    """
    seen = set()
    result = []
    def _walk(c):
        if exclude_no_export and _col_is_no_export(c):
            return
        for o in c.objects:
            if o.name not in seen:
                seen.add(o.name)
                result.append(o)
        for child in c.children:
            _walk(child)
    _walk(col)
    return result


def _level_objects(scene, level_col=None, exclude_no_export=True):
    """Return all objects belonging to the active level collection.

    Falls back to scene.objects if not in collection mode (backward compat).
    """
    if level_col is None:
        level_col = _active_level_col(scene)
    if level_col is None:
        # Fallback: v1.1.0 behaviour — all scene objects
        return list(scene.objects)
    return _recursive_col_objects(level_col, exclude_no_export=exclude_no_export)


def _ensure_sub_collection(level_col, *path):
    """Find or create nested sub-collections under a level collection.

    Sub-collection names are prefixed with the level name to guarantee
    global uniqueness when multiple levels share a .blend file.

    Example: _ensure_sub_collection(level_col, "Spawnables", "Enemies")
    creates level_col > {level}.Spawnables > {level}.Spawnables.Enemies
    Returns the innermost collection.
    """
    level_name = str(level_col.get("og_level_name", level_col.name))
    current = level_col
    accumulated = ""
    for segment in path:
        # Build a globally unique name: level.Segment or level.Parent.Segment
        accumulated = f"{level_name}.{segment}" if not accumulated else f"{accumulated}.{segment}"
        unique_name = accumulated
        child = None
        for c in current.children:
            if c.name == unique_name:
                child = c
                break
        if child is None:
            child = bpy.data.collections.new(unique_name)
            current.children.link(child)
        current = child
    return current


def _link_object_to_sub_collection(scene, obj, *col_path):
    """Link an object into the correct sub-collection of the active level.

    If not in collection mode, does nothing (object stays wherever Blender put it).
    Unlinks from Scene Collection root if linked there.
    """
    level_col = _active_level_col(scene)
    if level_col is None:
        return  # v1.1.0 fallback — no auto-organization
    target = _ensure_sub_collection(level_col, *col_path)
    # Link to target if not already there
    if obj.name not in target.objects:
        target.objects.link(obj)
    # Unlink from scene root collection if present
    if obj.name in scene.collection.objects:
        scene.collection.objects.unlink(obj)
    # Unlink from any other collections that aren't in our target path
    # (Blender auto-links new objects to the active collection)
    for col in bpy.data.collections:
        if col == target:
            continue
        if obj.name in col.objects:
            col.objects.unlink(obj)


def _col_path_for_entity(etype):
    """Return the sub-collection path tuple for a given entity type."""
    info = ENTITY_DEFS.get(etype, {})
    cat = info.get("cat", "")
    return _ENTITY_CAT_TO_COL_PATH.get(cat, _COL_PATH_SPAWNABLE_PROPS)


def _classify_object(obj):
    """Return the correct _COL_PATH_* tuple for an object based on name/type.

    Returns None if the object cannot be classified (e.g. unknown empty type).
    This is used by the Sort Collection Objects operator to route loose objects
    into the correct sub-collection.
    """
    name = obj.name
    otype = obj.type

    # ── Meshes → Geometry/Solid (default) ───────────────────────────────────
    # VOL_ meshes are trigger volumes — they live in Triggers, not Geometry
    # NAVMESH_ meshes live in NavMeshes
    if otype == "MESH":
        if name.startswith("VOL_"):
            return _COL_PATH_TRIGGERS
        if name.startswith("NAVMESH_") or obj.get("og_navmesh", False):
            return _COL_PATH_NAVMESHES
        return _COL_PATH_GEO_SOLID

    # ── Empties by name prefix ───────────────────────────────────────────────
    if otype == "EMPTY":
        # Waypoints — must be checked before ACTOR_ since they share the prefix
        if "_wp_" in name or "_wpb_" in name:
            return _COL_PATH_WAYPOINTS

        # Actors
        if name.startswith("ACTOR_"):
            parts = name.split("_", 2)
            if len(parts) >= 3:
                etype = parts[1]
                return _col_path_for_entity(etype)
            return _COL_PATH_SPAWNABLE_PROPS

        # Spawn / checkpoint empties and their CAM anchors
        if name.startswith("SPAWN_") or name.startswith("CHECKPOINT_"):
            return _COL_PATH_SPAWNS

        # Sound emitters
        if name.startswith("AMBIENT_"):
            return _COL_PATH_SOUND_EMITTERS

        return None  # Unknown empty — leave in place

    # ── Cameras ─────────────────────────────────────────────────────────────
    if otype == "CAMERA":
        if name.startswith("CAMERA_"):
            return _COL_PATH_CAMERAS
        return None

    return None  # Any other type — leave in place


def _get_level_prop(scene, key, default=None):
    """Read a level property — from active collection or scene.og_props fallback."""
    col = _active_level_col(scene)
    if col is not None:
        return col.get(key, _LEVEL_COL_DEFAULTS.get(key, default))
    # Fallback: read from scene.og_props
    props = scene.og_props
    attr = _LEVEL_PROP_KEY_MAP.get(key)
    if attr and hasattr(props, attr):
        return getattr(props, attr)
    return default


def _set_level_prop(scene, key, value):
    """Write a level property — to active collection or scene.og_props fallback."""
    col = _active_level_col(scene)
    if col is not None:
        col[key] = value
        # Keep collection name in sync with level name
        if key == "og_level_name":
            col.name = str(value).strip().lower().replace(" ", "-") or "unnamed-level"
        return
    # Fallback: write to scene.og_props
    props = scene.og_props
    attr = _LEVEL_PROP_KEY_MAP.get(key)
    if attr and hasattr(props, attr):
        setattr(props, attr, value)


# Dynamic enum callback for active_level selector
def _active_level_items(self, context):
    """Populate the active_level dropdown from level collections."""
    scene = context.scene if context else None
    if scene is None:
        return [("NONE", "No Levels", "", 0)]
    levels = _all_level_collections(scene)
    if not levels:
        return [("NONE", "No Levels", "", 0)]
    items = []
    for i, col in enumerate(levels):
        lname = col.get("og_level_name", col.name)
        items.append((col.name, lname, f"Switch to level '{lname}'", "SCENE_DATA", i))
    return items


def _set_blender_active_collection(context, col):
    """Set Blender's active collection in the view layer so new objects land here.

    Walks the layer_collection tree to find the matching LayerCollection.
    """
    def _find_lc(lc, target_name):
        if lc.collection.name == target_name:
            return lc
        for child in lc.children:
            found = _find_lc(child, target_name)
            if found:
                return found
        return None

    if context.view_layer:
        lc = _find_lc(context.view_layer.layer_collection, col.name)
        if lc:
            context.view_layer.active_layer_collection = lc


def _get_death_plane(self):
    col = _active_level_col(bpy.context.scene) if bpy.context else None
    if col is not None:
        return float(col.get("og_bottom_height", -20.0))
    return -20.0

def _set_death_plane(self, value):
    col = _active_level_col(bpy.context.scene) if bpy.context else None
    if col is not None:
        col["og_bottom_height"] = max(-500.0, min(-1.0, value))


def _on_active_level_changed(self, context):
    """Called when active_level enum changes — sync Blender's active collection."""
    col = _active_level_col(context.scene)
    if col is not None:
        _set_blender_active_collection(context, col)

