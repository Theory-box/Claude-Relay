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
    _COL_PATH_WAYPOINTS, _COL_PATH_NAVMESHES,
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
    # Name / path helpers used by operators and panels
    _nick, _iso, _lname, _ldir, _goal_src, _level_info, _game_gp,
    _levels_dir, _entity_gc,
)
# bpy.utils.previews is the correct Blender API for custom images in panels.
# icon_id is just an integer texture lookup — zero overhead in draw().
_preview_collections: dict = {}


def _load_previews():
    """Load all enemy images into a PreviewCollection. Called from register()."""
    import bpy.utils.previews, os
    pcoll = bpy.utils.previews.new()
    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'enemy-images')
    if os.path.isdir(img_dir):
        for etype, wiki in ENTITY_WIKI.items():
            fname = wiki.get('img')
            if not fname:
                continue
            fpath = os.path.join(img_dir, fname)
            if os.path.exists(fpath) and etype not in pcoll:
                pcoll.load(etype, fpath, 'IMAGE')
    _preview_collections['wiki'] = pcoll


def _unload_previews():
    """Remove preview collection. Called from unregister()."""
    import bpy.utils.previews
    for pcoll in _preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    _preview_collections.clear()


def _draw_wiki_preview(layout, etype: str, ctx=None):
    """Draw image + description preview for the selected entity. Call from panel draw()."""
    wiki = ENTITY_WIKI.get(etype)
    if not wiki:
        return

    pcoll = _preview_collections.get('wiki')
    box = layout.box()

    # ── Image ─────────────────────────────────────────────────────────────
    # layout.label(icon_value=) is the standard Blender addon pattern for
    # custom images. scale_y enlarges the row so the icon renders big.
    if pcoll and etype in pcoll:
        icon_id = pcoll[etype].icon_id
        col = box.column(align=True)
        col.template_icon(icon_value=icon_id, scale=8.0)
    elif wiki.get('img'):
        box.label(text="Image not found — check enemy-images/ folder", icon="ERROR")
    else:
        box.label(text="No image available", icon="IMAGE_DATA")

    # ── Description ────────────────────────────────────────────────────────
    desc = wiki.get('desc', '').strip()
    if desc:
        col = box.column(align=True)
        words = desc.split()
        line, out = [], []
        for w in words:
            if sum(len(x) + 1 for x in line) + len(w) > 52:
                out.append(' '.join(line))
                line = [w]
            else:
                line.append(w)
        if line:
            out.append(' '.join(line))
        for ln in out:
            col.label(text=ln)

# ---------------------------------------------------------------------------
# ADDON PREFERENCES
# ---------------------------------------------------------------------------

class OGPreferences(AddonPreferences):
    bl_idname = __name__

    exe_path: StringProperty(
        name="EXE folder",
        description=(
            "Folder containing the OpenGOAL executables (gk / gk.exe and goalc / goalc.exe). "
            "Usually the versioned release folder, e.g. .../opengoal/v0.2.29/"
        ),
        subtype="DIR_PATH",
        default="",
    )
    data_path: StringProperty(
        name="Data folder",
        description=(
            "Your active jak1 source folder — the one that contains data/goal_src. "
            "Usually .../jak-project/ or .../active/jak1/"
        ),
        subtype="DIR_PATH",
        default="",
    )
    def draw(self, ctx):
        layout = self.layout
        layout.label(text="EXE folder — contains gk / goalc executables:")
        layout.prop(self, "exe_path", text="")
        layout.label(text="Data folder — contains data/goal_src (e.g. your jak-project folder):")
        layout.prop(self, "data_path", text="")

# ---------------------------------------------------------------------------
# PATH HELPERS
# ---------------------------------------------------------------------------

import sys as _sys
_EXE = ".exe" if _sys.platform == "win32" else ""   # platform-aware exe extension

GOALC_PORT    = 8181   # runtime default; updated by launch_goalc() and _load_port_file()
GOALC_TIMEOUT = 120

import tempfile as _tempfile
_PORT_FILE = Path(_tempfile.gettempdir()) / "opengoal_blender_goalc.port"

def _save_port_file(port):
    try:
        _PORT_FILE.write_text(str(port))
    except Exception:
        pass

def _load_port_file():
    """Read port from previous launch. Only applies if goalc is still running."""
    global GOALC_PORT
    try:
        if _PORT_FILE.exists() and _process_running(f"goalc{_EXE}"):
            port = int(_PORT_FILE.read_text().strip())
            if 1024 <= port <= 65535:
                GOALC_PORT = port
                log(f"[nREPL] restored port {port} from port file")
    except Exception:
        pass

def _delete_port_file():
    try:
        _PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def _find_free_nrepl_port():
    """Ask the OS for a free port — guaranteed to work on any machine.
    Binds to port 0 (OS assigns a free one), records it, releases it,
    then passes it to GOALC via --port. No scanning, no timeouts.
    """
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log(f"[nREPL] OS-assigned free port: {port}")
    return port

def _strip(p): return p.strip().rstrip("\\").rstrip("/")

def _exe_root():
    prefs = bpy.context.preferences.addons.get(__name__)
    p = prefs.preferences.exe_path if prefs else ""
    return Path(_strip(p)) if p.strip() else Path(".")

def _data_root():
    prefs = bpy.context.preferences.addons.get(__name__)
    p = prefs.preferences.data_path if prefs else ""
    return Path(_strip(p)) if p.strip() else Path(".")

def _gk():         return _exe_root() / f"gk{_EXE}"
def _goalc():      return _exe_root() / f"goalc{_EXE}"
def _data():       return _data_root() / "data"


# ---------------------------------------------------------------------------
# AUDIO ENUMS
# ---------------------------------------------------------------------------


class OGProperties(PropertyGroup):
    # Collection-based level selection
    active_level:   EnumProperty(name="Active Level", items=_active_level_items,
                                 update=_on_active_level_changed,
                                 description="Select which level collection is active")
    level_name:  StringProperty(name="Name", description="Lowercase with dashes", default="my-level")
    entity_type:    EnumProperty(name="Entity Type",    items=ENTITY_ENUM_ITEMS)
    platform_type:  EnumProperty(name="Platform Type",  items=PLATFORM_ENUM_ITEMS)
    crate_type:  EnumProperty(name="Crate Type",  items=CRATE_ITEMS)
    # Per-category entity pickers — each Spawn sub-panel uses its own prop
    # so the dropdown only shows types relevant to that sub-panel.
    enemy_type:     EnumProperty(name="Enemy Type",   items=ENEMY_ENUM_ITEMS,
                                 description="Select an enemy or boss to place")
    prop_type:      EnumProperty(name="Prop Type",    items=PROP_ENUM_ITEMS,
                                 description="Select a prop or object to place")
    npc_type:       EnumProperty(name="NPC Type",     items=NPC_ENUM_ITEMS,
                                 description="Select an NPC to place")
    pickup_type:    EnumProperty(name="Pickup Type",  items=PICKUP_ENUM_ITEMS,
                                 description="Select a pickup to place")
    nav_radius:  FloatProperty(name="Nav Sphere Radius (m)", default=6.0, min=0.5, max=50.0,
                               description="Fallback navmesh sphere radius for nav-unsafe enemies")
    base_id:     IntProperty(name="Base Actor ID", default=10000, min=1000, max=60000,
                             description="Starting actor ID for this level. Must be unique across all custom levels to avoid ghost entity spawns.")
    lightbake_samples: IntProperty(name="Sample Count", default=128, min=1, max=4096,
                                   description="Number of Cycles render samples used when baking lighting to vertex colors")
    # Audio
    sound_bank_1:           EnumProperty(name="Bank 1", items=LEVEL_BANKS, default="none",
                                         description="First level sound bank (max 2 total)")
    sound_bank_2:           EnumProperty(name="Bank 2", items=LEVEL_BANKS, default="none",
                                         description="Second level sound bank (max 2 total)")
    music_bank:             EnumProperty(name="Music Bank", items=LEVEL_BANKS, default="none",
                                         description="Music bank to load for this level")
    sfx_sound:              EnumProperty(name="Sound", items=ALL_SFX_ITEMS, default="waterfall",
                                         description="Currently selected sound for emitter placement")
    ambient_default_radius: FloatProperty(name="Default Emitter Radius (m)", default=15.0, min=1.0, max=200.0,
                                          description="Bsphere radius for new sound emitter empties")
    # Level flow spawn type picker
    spawn_flow_type: EnumProperty(
        name="Type",
        items=[
            ("SPAWN",      "Player Spawn",  "Place a player spawn / continue point", "EMPTY_ARROWS",        0),
            ("CHECKPOINT", "Checkpoint",    "Place a mid-level checkpoint trigger",  "EMPTY_SINGLE_ARROW",  1),
        ],
        default="SPAWN",
        description="Select the type of level flow object to place",
    )
    # Level flow
    bottom_height:     FloatProperty(name="Death Plane (m)", default=-20.0, min=-500.0, max=-1.0,
                                     get=_get_death_plane, set=_set_death_plane,
                                     description="Y height below which the player gets an endlessfall death (negative = below level floor)")
    vis_nick_override: StringProperty(name="Vis Nick Override", default="",
                                      description="Override the auto-generated 3-letter vis nickname (leave blank to use auto)")
    # UI collapse state
    show_camera_list:       BoolProperty(name="Show Camera List",       default=True)
    show_volume_list:       BoolProperty(name="Show Volume List",       default=True)
    show_spawn_list:        BoolProperty(name="Show Spawn List",        default=True)
    show_checkpoint_list:   BoolProperty(name="Show Checkpoint List",   default=True)
    show_platform_list:     BoolProperty(name="Show Platform List",     default=True)
    # Collection Properties panel
    selected_collection:    StringProperty(name="Selected Collection", default="")

# ---------------------------------------------------------------------------
# PROCESS MANAGEMENT
# ---------------------------------------------------------------------------

def _process_running(exe_name):
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/fi", f"imagename eq {exe_name}"],
                               capture_output=True, text=True)
            return exe_name.lower() in r.stdout.lower()
        else:
            r = subprocess.run(["pgrep", "-f", exe_name], capture_output=True, text=True)
            return bool(r.stdout.strip())
    except Exception:
        return False

def _kill_process(exe_name):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/f", "/im", exe_name], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", exe_name], capture_output=True)
        time.sleep(0.8)
    except Exception:
        pass

def kill_gk():
    _kill_process(f"gk{_EXE}")
    time.sleep(0.5)

def kill_goalc():
    killed_port = GOALC_PORT   # snapshot before kill — GOALC_PORT may update later
    _delete_port_file()
    _kill_process(f"goalc{_EXE}")
    time.sleep(0.5)
    # On Windows, SO_EXCLUSIVEADDRUSE holds the port until fully released.
    # Poll until the port is free so the next launch_goalc() doesn't get
    # "nREPL: DISABLED". Use 127.0.0.1 explicitly — localhost may resolve
    # to ::1 (IPv6) on Windows, causing timeouts instead of clean refusals.
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", killed_port), timeout=0.3):
                pass
            time.sleep(0.3)  # port still held, keep waiting
        except (ConnectionRefusedError, OSError):
            break  # port is free
# ---------------------------------------------------------------------------
# GOALC / nREPL
# ---------------------------------------------------------------------------

def goalc_send(cmd, timeout=GOALC_TIMEOUT):
    """Send a GOAL expression to the nREPL server and return the response.

    Wire format (from common/repl/nrepl/ReplClient.cpp):
      [u32 length LE][u32 type=10 LE][utf-8 string]
    Sending raw text causes "Bad message, aborting the read" errors.
    """
    import struct
    EVAL_TYPE = 10
    try:
        with socket.create_connection(("127.0.0.1", GOALC_PORT), timeout=10) as s:
            encoded = cmd.encode("utf-8")
            header = struct.pack("<II", len(encoded), EVAL_TYPE)
            s.sendall(header + encoded)
            chunks = []
            s.settimeout(timeout)
            while True:
                try:
                    c = s.recv(4096)
                    if not c: break
                    chunks.append(c)
                    if b"g >" in c or b"g  >" in c: break
                except socket.timeout: break
            return b"".join(chunks).decode(errors="replace")
    except ConnectionRefusedError: return None
    except Exception as e: return f"ERROR:{e}"

def goalc_ok():
    """Return True if GOALC's nREPL is reachable on GOALC_PORT.

    On first miss, tries to restore GOALC_PORT from the port file written
    by launch_goalc() — this handles the case where GOALC was already running
    when Blender started (e.g. from a previous session).
    """
    if goalc_send("(+ 1 1)", timeout=3) is not None:
        return True
    # Fast path missed. Try restoring port from file (written at launch time).
    _load_port_file()
    return goalc_send("(+ 1 1)", timeout=3) is not None

USER_NAME = "blender"

def _user_base(): return _data_root() / "data" / "goal_src" / "user"
def _user_dir():
    d = _user_base() / USER_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def write_startup_gc(commands):
    base = _user_base()
    base.mkdir(parents=True, exist_ok=True)
    (base / "user.txt").write_text(USER_NAME)
    udir = _user_dir()
    (udir / "user.gc").write_text(
        ";; Auto-generated by OpenGOAL Tools Blender addon\n"
        "(define-extern bg (function symbol int))\n"
        "(define-extern bg-custom (function symbol object))\n"
        "(define-extern *artist-all-visible* symbol)\n"
    )
    p = udir / "startup.gc"
    p.write_text("\n".join(commands) + "\n")
    log(f"Wrote startup.gc: {commands}")

def launch_goalc(wait_for_nrepl=False):
    global GOALC_PORT
    exe = _goalc()
    if not exe.exists():
        return False, f"goalc not found at {exe}"
    # Caller is responsible for kill_goalc() + port-free wait before calling here.
    # Do NOT kill internally — it would reset the port-free polling the caller did.
    # Find a free port starting from the user-configured preference.
    GOALC_PORT = _find_free_nrepl_port()
    _save_port_file(GOALC_PORT)
    log(f"[nREPL] launching GOALC on port {GOALC_PORT}")
    try:
        data_dir = str(_data())
        cmd = [str(exe), "--user-auto", "--game", "jak1", "--proj-path", data_dir,
               "--port", str(GOALC_PORT)]
        if os.name == "nt":
            proc = subprocess.Popen(cmd, cwd=str(_exe_root()),
                                    creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(cmd, cwd=str(_exe_root()))
        log(f"launch_goalc: pid={proc.pid}")
        if wait_for_nrepl:
            for _ in range(60):
                time.sleep(0.5)
                if goalc_ok():
                    return True, "GOALC started with nREPL"
            return False, "GOALC started but nREPL not available"
        return True, f"GOALC launched (pid={proc.pid})"
    except Exception as e:
        return False, str(e)

def launch_gk():
    exe = _gk()
    if not exe.exists(): return False, f"Not found: {exe}"
    # Kill existing GK — no window stacking
    if _process_running(f"gk{_EXE}"):
        log("launch_gk: killing existing GK")
        kill_gk()
    try:
        data_dir = str(_data())
        subprocess.Popen([str(exe), "-v", "--game", "jak1",
                          "--proj-path", data_dir,
                          "--", "-boot", "-fakeiso", "-debug"],
                         cwd=str(_exe_root()))
        return True, "gk launched"
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------------------------
# SCENE PARSING
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OPERATORS — Level Collection Management
# ---------------------------------------------------------------------------

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
            o["og_crate_type"] = ctx.scene.og_props.crate_type
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

def validate_ambients(ambients):
    errors = []
    for i, a in enumerate(ambients):
        t = a.get("trans", [])
        b = a.get("bsphere", [])
        name = a.get("lump", {}).get("name", f"ambient[{i}]")
        if len(t) != 4:
            errors.append(f"{name}: ambient trans has {len(t)} elements, expected 4  (value={t})")
        if len(b) != 4:
            errors.append(f"{name}: ambient bsphere has {len(b)} elements, expected 4  (value={b})")
    return errors




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

_BUILD_STATE = {"done":False, "status":"", "error":None, "ok":False}


def patch_entity_gc(navmesh_actors):
    """
    Patch engine/entity/entity.gc to add custom-nav-mesh-check-and-setup.

    navmesh_actors: list of (actor_aid, mesh_data) tuples.

    Adds/replaces:
      1. A (defun custom-nav-mesh-check-and-setup ...) with one case per actor.
      2. A call to it at the top of (defmethod birth! entity-actor ...).

    Safe to call repeatedly — old injected code is stripped before re-injecting.
    """
    p = _entity_gc()
    if not p.exists():
        log(f"WARNING: entity.gc not found at {p}")
        return

    raw  = p.read_bytes()
    crlf = b"\r\n" in raw
    txt  = raw.decode("utf-8").replace("\r\n", "\n")

    # ── Strip any previously injected block ──────────────────────────────────
    import re
    txt = re.sub(
        r"\n;; \[OpenGOAL Tools\] BEGIN custom-nav-mesh.*?;; \[OpenGOAL Tools\] END custom-nav-mesh\n",
        "",
        txt,
        flags=re.DOTALL,
    )
    # Strip old birth! injection line
    txt = re.sub(r"  \(custom-nav-mesh-check-and-setup this\)\n", "", txt)

    if not navmesh_actors:
        # Nothing to inject — just clean file
        out = txt.replace("\n", "\r\n") if crlf else txt
        p.write_bytes(out.encode("utf-8"))
        log("entity.gc: cleaned (no navmesh actors)")
        return

    # ── Build the defun block ─────────────────────────────────────────────────
    lines = [
        "",
        ";; [OpenGOAL Tools] BEGIN custom-nav-mesh",

        "(defun custom-nav-mesh-check-and-setup ((this entity-actor))",
        "  (case (-> this aid)",
    ]
    for aid, mesh in navmesh_actors:
        lines.append(_navmesh_to_goal(mesh, aid))
    lines += [
        "  )",
        "  ;; Manually init the nav-mesh without calling entity-nav-login.",
        "  ;; entity-nav-login calls update-route-table which writes back to the route",
        "  ;; array — but our mesh is 'static (read-only GAME.CGO memory), so that",
        "  ;; write would segfault. Instead we just set up the user-list engine.",
        "  (when (nonzero? (-> this nav-mesh))",
        "    (when (zero? (-> (-> this nav-mesh) user-list))",
        "      (set! (-> (-> this nav-mesh) user-list)",
        "            (new 'loading-level 'engine 'nav-engine 32))",
        "    )",
        "  )",
        "  (none)",
        ")",
        ";; [OpenGOAL Tools] END custom-nav-mesh",
        "",
    ]
    inject_block = "\n".join(lines)

    # Insert before (defmethod birth! ((this entity-actor))
    BIRTH_MARKER = "(defmethod birth! ((this entity-actor))"
    if BIRTH_MARKER not in txt:
        log("WARNING: entity.gc birth! marker not found — cannot inject nav-mesh")
        return
    txt = txt.replace(BIRTH_MARKER, inject_block + "\n" + BIRTH_MARKER, 1)

    # ── Inject call at top of birth! body ────────────────────────────────────
    # Find the body start — line after "Create a process for this entity..."
    # We look for the first (let* ... after the birth! marker
    CALL_MARKER = "  (let* ((entity-type (-> this etype))"
    txt = txt.replace(
        CALL_MARKER,
        "  (custom-nav-mesh-check-and-setup this)\n" + CALL_MARKER,
        1,
    )

    out = txt.replace("\n", "\r\n") if crlf else txt
    p.write_bytes(out.encode("utf-8"))
    log(f"Patched entity.gc with {len(navmesh_actors)} nav-mesh actor(s)")

def _bg_build(name, scene):
    state = _BUILD_STATE
    try:
        state["status"] = "Collecting scene..."
        _clean_orphaned_vol_links(scene)
        actors    = collect_actors(scene)
        ambients  = collect_ambients(scene)
        spawns    = collect_spawns(scene)
        ags       = needed_ags(actors)
        tpages    = needed_tpages(actors)
        code_deps = needed_code(actors)
        collect_nav_mesh_geometry(scene, name)
        cam_actors, trigger_actors = collect_cameras(scene)

        if code_deps:
            state["status"] = f"Injecting code for: {[o for o,_,_ in code_deps]}..."
            log(f"[code-deps] {code_deps}")

        state["status"] = "Writing files..."
        base_id = int(_get_level_prop(scene, "og_base_id", 10000))
        aggro_actors = collect_aggro_triggers(scene)
        write_jsonc(name, actors, ambients, cam_actors + trigger_actors + aggro_actors, base_id)
        write_gd(name, ags, code_deps, tpages)
        navmesh_actors = _collect_navmesh_actors(scene)
        _lv_objs = _level_objects(scene)
        has_cps = bool([o for o in _lv_objs if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")])
        write_gc(name, has_triggers=bool(trigger_actors), has_checkpoints=has_cps, has_aggro_triggers=bool(aggro_actors))
        patch_entity_gc(navmesh_actors)
        patch_level_info(name, spawns, scene)
        patch_game_gp(name, code_deps)

        if goalc_ok():
            state["status"] = "Running (mi) via nREPL..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is not None:
                state["ok"] = True; state["status"] = "Build complete!"; return

        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(mi)"])
        state["status"] = "Launching GOALC..."
        kill_goalc()
        ok, msg = launch_goalc()
        if not ok:
            state["error"] = msg; return
        state["ok"] = True
        state["status"] = "GOALC launched — watch console for compile progress."
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True

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
        threading.Thread(target=_bg_build, args=(name, ctx.scene), daemon=True).start()
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

_PLAY_STATE = {"done":False, "error":None, "status":""}

def _bg_play(name):
    """Kill GK+GOALC, relaunch GOALC with nREPL, launch GK, load level, spawn player.

    ARCHITECTURE NOTES (read before modifying):

    nREPL (port 8181) is a TCP socket that GOALC opens on startup.  The addon
    sends all commands ((lt), (bg), (start)) through this socket via goalc_send().
    If another GOALC instance is already holding port 8181, bind() fails and
    GOALC prints "nREPL: DISABLED" — every goalc_send() then silently returns
    None and nothing happens.

    FIX: Always kill GOALC before relaunching it.  The goalc_ok() fast-path
    (reuse existing GOALC) is ONLY safe when nREPL is confirmed working.

    startup.gc SEQUENCING:
    Lines above ";; og:run-below-on-listen" → run_before_listen (run immediately
    at GOALC startup, before GK exists).
    Lines below the sentinel             → run_after_listen (run automatically
    when (lt) successfully connects to GK).
    (lt) itself is in run_before_listen so it fires first; everything after the
    sentinel fires after GK connects.  No need for (suspend-for) here — the
    run_after_listen lines don't execute until GK is alive and (lt) connected.

    WHY (start) IS NEEDED:
    (bg) loads geometry and calls set-continue! to our level's first continue-
    point, but does NOT kill/respawn the player.  The boot-sequence player is
    still alive, falls in the void, dies, and respawns in a race with level load.
    (start 'play ...) kills that player and spawns fresh at the continue-point.
    """
    state = _PLAY_STATE
    try:
        # Always kill both GK and GOALC before relaunching.
        # GOALC must be killed so port 8181 is free for the new instance.
        # If an old GOALC holds 8181, the new one shows "nREPL: DISABLED" and
        # all goalc_send() calls silently fail.
        state["status"] = "Killing GK and GOALC..."
        kill_gk()
        kill_goalc()

        # Write startup.gc with only (lt) and (bg).
        # (start) is NOT in startup.gc because run_after_listen fires the moment
        # (lt) connects — before GAME.CGO finishes linking and *game-info* exists.
        # Calling (start) before *game-info* is defined causes a compile error.
        # Instead we poll via nREPL after GK boots until *game-info* is live.
        # Write startup.gc with ONLY (lt) — no (bg) here.
        # Putting (bg) in run_after_listen causes two problems:
        #   1. It re-fires every time GK reconnects, triggering "generated code,
        #      but wasn't supposed to" spam after play is done.
        #   2. It fires before GAME.CGO finishes linking, so the level may load
        #      into an unready engine state.
        # Instead we send (bg) manually via nREPL once *game-info* is confirmed live.
        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(lt)"])

        state["status"] = "Launching GOALC (waiting for nREPL)..."
        ok, msg = launch_goalc(wait_for_nrepl=True)
        if not ok:
            state["error"] = f"GOALC failed to start: {msg}"; return

        state["status"] = "Launching game..."
        ok, msg = launch_gk()
        if not ok: state["error"] = msg; return

        # Poll until *game-info* exists (GAME.CGO finished linking) then load level + spawn.
        # Match "'ready" (with leading quote) to catch only the GOAL symbol return value,
        # not console noise like "Listener: ready" which was causing false-positive triggers.
        state["status"] = "Waiting for game to finish loading..."
        spawned = False
        for _ in range(240):
            time.sleep(0.5)
            r = goalc_send("(if (nonzero? *game-info*) 'ready 'wait)", timeout=3)
            if r and "'ready" in r:
                state["status"] = "Loading level..."
                goalc_send(f"(bg '{name}-vis)", timeout=30)
                time.sleep(1.0)  # brief extra wait for level geometry to become active
                state["status"] = "Spawning player..."
                goalc_send(f"(start 'play (or (get-continue-by-name *game-info* \"{name}-start\") (get-or-create-continue! *game-info*)))")
                spawned = True
                break
        if not spawned:
            state["status"] = "Done (spawn timed out — load level manually)"
            return
        state["status"] = "Done!"
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True


# ── Waypoint operators ────────────────────────────────────────────────────────

class OG_OT_AddWaypoint(Operator):
    """Add a waypoint empty at the 3D cursor, linked to the selected enemy."""
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

        # Create empty at 3D cursor
        empty = bpy.data.objects.new(wp_name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        empty.location = ctx.scene.cursor.location.copy()

        # Custom property to link back to enemy
        empty["og_waypoint_for"] = self.enemy_name

        # Link into scene first (required before collection routing)
        ctx.scene.collection.objects.link(empty)

        # Route into Waypoints sub-collection under the active level
        _link_object_to_sub_collection(ctx.scene, empty, *_COL_PATH_WAYPOINTS)

        # Do NOT change active object — user needs to keep the actor selected
        # so they can quickly add more waypoints without re-selecting.
        self.report({"INFO"}, f"Added {wp_name} at cursor")
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

_GEO_REBUILD_STATE = {"done": False, "status": "", "error": None, "ok": False}


def _bg_geo_rebuild(name, scene):
    """Export geo + actor placement, repack DGO, relaunch GK. No GOAL recompile.

    (mi) is GOALC's incremental build command — it skips .gc files that haven't
    changed, so it only re-extracts the GLB and repacks the DGO.

    NOTE: if you've added a NEW enemy type since the last full Export & Compile,
    use that instead — this path skips the game.gp patch those types need.
    """
    state = _GEO_REBUILD_STATE
    try:
        state["status"] = "Collecting scene..."
        _clean_orphaned_vol_links(scene)
        actors   = collect_actors(scene)
        ambients = collect_ambients(scene)
        spawns   = collect_spawns(scene)
        ags      = needed_ags(actors)
        tpages   = needed_tpages(actors)
        code_deps = needed_code(actors)  # still needed for DGO .o injection
        cam_actors, trigger_actors = collect_cameras(scene)

        state["status"] = "Writing level files..."
        base_id = int(_get_level_prop(scene, "og_base_id", 10000))
        aggro_actors = collect_aggro_triggers(scene)
        write_jsonc(name, actors, ambients, cam_actors + trigger_actors + aggro_actors, base_id)
        write_gd(name, ags, code_deps, tpages)
        _lv_objs = _level_objects(scene)
        has_cps = bool([o for o in _lv_objs if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")])
        write_gc(name, has_triggers=bool(trigger_actors), has_checkpoints=has_cps, has_aggro_triggers=bool(aggro_actors))
        patch_level_info(name, spawns, scene)  # update spawn continue-points if moved

        # Run (mi) — re-extracts GLB, repacks DGO, skips unchanged .gc files
        if goalc_ok():
            state["status"] = "Running (mi) — re-extracting geo..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is None:
                state["error"] = "(mi) timed out or GOALC lost connection"; return
        else:
            state["status"] = "GOALC not running — launching for (mi)..."
            write_startup_gc(["(mi)"])
            ok, msg = launch_goalc(wait_for_nrepl=True)
            if not ok:
                state["error"] = f"GOALC failed to start: {msg}"; return
            state["status"] = "Running (mi)..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is None:
                state["error"] = "(mi) timed out"; return

        state["ok"] = True
        state["status"] = "Done! Reload your level in-game."
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True


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
        threading.Thread(target=_bg_geo_rebuild, args=(name, ctx.scene), daemon=True).start()
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


_BUILD_PLAY_STATE = {"done": False, "status": "", "error": None, "ok": False}


def _bg_build_and_play(name, scene):
    """Export files, compile with GOALC, then launch GK and load the level.

    FLOW:
      Phase 1 — collect scene, write all level files.
      Phase 2 — compile: ensure GOALC+nREPL are live, send (mi).
      Phase 3 — launch: write startup.gc with (lt)/(bg)/(start), restart GOALC
                 so it auto-runs those commands when GK connects.

    WHY WE RESTART GOALC AFTER COMPILE:
      After (mi) finishes we need GOALC to re-read startup.gc so it can auto-run
      (lt)/(bg)/(start) when GK boots.  Restarting is simpler and more reliable
      than trying to sequence manual goalc_send() calls with arbitrary sleeps —
      the startup.gc run_after_listen mechanism handles the GK-ready timing for us.

    WHY startup.gc INSTEAD OF goalc_send() FOR LAUNCH:
      goalc_send() is fire-and-forget with fixed sleeps.  If GK takes longer to
      boot than expected the (lt) call fails and nothing loads.  startup.gc
      run_after_listen fires only after (lt) actually connects — it is driven by
      GK being ready, not by a sleep timer.  See _bg_play() docstring for more.
    """
    state = _BUILD_PLAY_STATE
    try:
        # ── Phase 1: Build ────────────────────────────────────────────────────
        state["status"] = "Collecting scene..."
        _clean_orphaned_vol_links(scene)
        actors    = collect_actors(scene)
        ambients  = collect_ambients(scene)
        spawns    = collect_spawns(scene)
        ags       = needed_ags(actors)
        tpages    = needed_tpages(actors)
        code_deps = needed_code(actors)
        cam_actors, trigger_actors = collect_cameras(scene)

        state["status"] = "Writing level files..."
        base_id = int(_get_level_prop(scene, "og_base_id", 10000))
        aggro_actors = collect_aggro_triggers(scene)
        write_jsonc(name, actors, ambients, cam_actors + trigger_actors + aggro_actors, base_id)
        write_gd(name, ags, code_deps, tpages)
        navmesh_actors = _collect_navmesh_actors(scene)
        _lv_objs = _level_objects(scene)
        has_cps = bool([o for o in _lv_objs if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")])
        write_gc(name, has_triggers=bool(trigger_actors), has_checkpoints=has_cps, has_aggro_triggers=bool(aggro_actors))
        patch_entity_gc(navmesh_actors)
        patch_level_info(name, spawns, scene)
        patch_game_gp(name, code_deps)

        # ── Phase 2: Compile ──────────────────────────────────────────────────
        # Kill GK first — game must not be running during compile.
        # Keep GOALC alive if nREPL is working — saves startup time for (mi).
        state["status"] = "Killing existing GK..."
        kill_gk()
        time.sleep(0.3)

        if not goalc_ok():
            # nREPL not reachable — kill any stale GOALC holding port 8181
            # and launch fresh so (mi) can connect.
            state["status"] = "Launching GOALC (waiting for nREPL)..."
            kill_goalc()
            ok, msg = launch_goalc(wait_for_nrepl=True)
            if not ok:
                state["error"] = f"GOALC failed to start: {msg}"; return

        state["status"] = "Compiling (mi) — please wait..."
        r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
        if r is None:
            state["error"] = "Compile timed out — check GOALC console"; return

        # ── Phase 3: Launch game and load level ───────────────────────────────
        # Write startup.gc with ONLY (lt) — no (bg) here.
        # Putting (bg) in run_after_listen causes "generated code, but wasn't
        # supposed to" spam every time GK reconnects after play is done.
        # We send (bg) manually via nREPL once *game-info* is confirmed live.
        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(lt)"])

        # Restart GOALC so it reads the new startup.gc.
        state["status"] = "Restarting GOALC with launch startup..."
        kill_goalc()
        ok, msg = launch_goalc(wait_for_nrepl=True)
        if not ok:
            state["error"] = f"GOALC relaunch failed: {msg}"; return

        state["status"] = "Launching game..."
        ok, msg = launch_gk()
        log(f"[launch] launch_gk returned: ok={ok} msg={msg}")
        if not ok:
            state["error"] = f"GK launch failed: {msg}"; return

        # Poll until *game-info* exists (GAME.CGO done) then load level + spawn.
        # Match "'ready" (with leading quote) to catch only the GOAL symbol return,
        # not console noise like "Listener: ready" which causes false-positive triggers.
        state["status"] = "Waiting for game to finish loading..."
        spawned = False
        for _ in range(240):
            time.sleep(0.5)
            r = goalc_send("(if (nonzero? *game-info*) 'ready 'wait)", timeout=3)
            if r and "'ready" in r:
                state["status"] = "Loading level..."
                goalc_send(f"(bg '{name}-vis)", timeout=30)
                time.sleep(1.0)
                state["status"] = "Spawning player..."
                goalc_send(f"(start 'play (or (get-continue-by-name *game-info* \"{name}-start\") (get-or-create-continue! *game-info*)))")
                spawned = True
                break
        if not spawned:
            state["status"] = "Done (spawn timed out — load level manually)"
            return
        state["status"] = "Done!"
        state["ok"] = True

    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True


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
        threading.Thread(target=_bg_build_and_play, args=(name, ctx.scene), daemon=True).start()
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

UNIVERSAL_LUMPS = [
    ("vis-dist",      "meters",  "Distance at which entity stays active/visible. Enemies default 200m."),
    ("idle-distance", "meters",  "Player must be closer than this to wake the enemy. Default 80m."),
    ("shadow-mask",   "uint32",  "Which shadow layers render for this entity. e.g. 255 = all."),
    ("light-index",   "uint32",  "Index into the level's light array. Controls entity illumination."),
    ("lod-dist",      "meters",  "Distance threshold for LOD switching. Array of floats per LOD level."),
    ("texture-bucket","int32",   "Texture bucket for draw calls. Default 1."),
    ("options",       "enum-uint32", "fact-options bitfield e.g. '(fact-options has-power-cell)'."),
    ("visvol",        "vector4m","Visibility bounding box — two vector4m entries (min corner, max corner)."),
]

# Format: etype → [(key, ltype, description), ...]
class OGLumpRow(bpy.types.PropertyGroup):
    """One custom lump entry on an ACTOR_ empty.
    Stored as a CollectionProperty on the Object (og_lump_rows).
    Rendered as a scrollable list in OG_PT_SelectedLumps.
    """
    key:   StringProperty(
        name="Key",
        description="Lump key name (e.g. notice-dist, mode, num-lurkers)",
        default="",
    )
    ltype: EnumProperty(
        name="Type",
        items=LUMP_TYPE_ITEMS,
        default="meters",
        description="JSONC lump value type",
    )
    value: StringProperty(
        name="Value",
        description="Value(s) — space-separated for multi-value types",
        default="",
    )


# ---------------------------------------------------------------------------
# Lump row operators
# ---------------------------------------------------------------------------

class OG_OT_AddLumpRow(bpy.types.Operator):
    bl_idname  = "og.add_lump_row"
    bl_label   = "Add Lump Row"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        obj = ctx.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object"); return {"CANCELLED"}
        obj.og_lump_rows.add()
        obj.og_lump_rows_index = len(obj.og_lump_rows) - 1
        return {"FINISHED"}


class OG_OT_RemoveLumpRow(bpy.types.Operator):
    bl_idname  = "og.remove_lump_row"
    bl_label   = "Remove Lump Row"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        obj = ctx.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object"); return {"CANCELLED"}
        rows = obj.og_lump_rows
        idx  = obj.og_lump_rows_index
        if not rows or idx < 0 or idx >= len(rows):
            self.report({"ERROR"}, "Nothing to remove"); return {"CANCELLED"}
        rows.remove(idx)
        obj.og_lump_rows_index = max(0, min(idx, len(rows) - 1))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Lump UIList
# ---------------------------------------------------------------------------

class OG_UL_LumpRows(bpy.types.UIList):
    """Scrollable list of custom lump rows for an ACTOR_ empty."""

    def draw_item(self, ctx, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        # Key field — reasonably wide
        row.prop(item, "key",   text="", emboss=True, placeholder="key")
        # Type dropdown — compact
        sub = row.row(align=True)
        sub.scale_x = 0.9
        sub.prop(item, "ltype", text="")
        # Value field
        row.prop(item, "value", text="", emboss=True, placeholder="value(s)")
        # Live parse indicator — red dot on bad rows
        _, err = _parse_lump_row(item.key, item.ltype, item.value)
        if err:
            row.label(text="", icon="ERROR")

    def filter_items(self, ctx, data, propname):
        # No filtering — just return defaults
        return [], []


# ===========================================================================
# VOLUME LINK SYSTEM
# ---------------------------------------------------------------------------
# A trigger volume (VOL_ mesh) holds a CollectionProperty of OGVolLink entries.
# Each entry links the volume to one target (camera / checkpoint / nav-enemy).
# Multiple entries per volume = one volume drives multiple things on enter.
#
# Behaviour field is per-link, only meaningful for nav-enemy targets:
#   cue-chase        — wake up + chase player (default)
#   cue-patrol       — return to patrol
#   go-wait-for-cue  — freeze until next cue
# Translated to integer enum at build time and emitted as a uint32 lump.
# Camera and checkpoint links ignore this field.
# ===========================================================================

class OGActorLink(bpy.types.PropertyGroup):
    """One entity link slot on an ACTOR_ empty.

    Stored as og_actor_links CollectionProperty on the Object.
    Each entry maps (lump_key, slot_index) → target_name.
    At export these are serialised as  lump_key: ["string", name0, name1, ...]
    """
    lump_key:     bpy.props.StringProperty(
        name="Lump Key",
        description="The res-lump key this link writes to (e.g. alt-actor, water-actor)",
    )
    slot_index:   bpy.props.IntProperty(
        name="Slot Index",
        description="Index within the lump array (0 = first element)",
        default=0,
        min=0,
    )
    target_name:  bpy.props.StringProperty(
        name="Target",
        description="Name of the linked ACTOR_ empty",
    )


class OGVolLink(PropertyGroup):
    """One link between a trigger volume and a target object.
    Stored in a CollectionProperty on the volume mesh as og_vol_links.
    """
    target_name: StringProperty(
        name="Target",
        description="Name of the linked target object (camera, checkpoint, or enemy)",
    )
    behaviour:   EnumProperty(
        name="Behaviour",
        items=AGGRO_EVENT_ENUM_ITEMS,
        default="cue-chase",
        description="Event sent to the enemy on volume enter (nav-enemies only — ignored for cameras/checkpoints)",
    )


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


def _is_linkable(obj):
    """True if this object type can accept a trigger volume link.
    Cameras, checkpoints, player spawns, and nav-enemy actors are linkable.
    Process-drawable enemies (Yeti, Bully, etc.) are NOT linkable because
    they don't respond to 'cue-chase events.
    """
    if obj is None:
        return False
    if obj.type == "CAMERA" and obj.name.startswith("CAMERA_"):
        return True
    if obj.type == "EMPTY":
        n = obj.name
        if n.endswith("_CAM"):
            return False
        if n.startswith("SPAWN_") or n.startswith("CHECKPOINT_"):
            return True
        if n.startswith("ACTOR_") and "_wp_" not in n and "_wpb_" not in n:
            parts = n.split("_", 2)
            if len(parts) >= 3 and _actor_supports_aggro_trigger(parts[1]):
                return True
    return False


def _is_aggro_target(obj):
    """True if this object is a nav-enemy ACTOR_ empty.
    Aggro targets allow multiple linked volumes (and multiple links per volume
    pointing at the same enemy with different behaviours). Cameras and
    checkpoints are 1:1 (soft-enforced at link time).
    """
    if obj is None or obj.type != "EMPTY" or not obj.name.startswith("ACTOR_"):
        return False
    if "_wp_" in obj.name or "_wpb_" in obj.name or obj.name.endswith("_CAM"):
        return False
    parts = obj.name.split("_", 2)
    return len(parts) >= 3 and _actor_supports_aggro_trigger(parts[1])


def _vol_for_target(scene, target_name):
    """Return the first VOL_ mesh that has at least one link to target_name, or None.
    For multi-link enemies, use _vols_linking_to() instead.
    """
    for o in _level_objects(scene):
        if o.type == "MESH" and o.name.startswith("VOL_") and _vol_has_link_to(o, target_name):
            return o
    return None


def _clean_orphaned_vol_links(scene):
    """Remove link entries from VOL_ meshes whose targets no longer exist.
    Called at export time and available as a panel button.
    Returns list of (vol_name, target_name) tuples that were cleaned.
    Volume is renamed if its link count changes (or restored to VOL_<id> if empty).
    """
    cleaned = []
    for o in _level_objects(scene):
        if o.type != "MESH" or not o.name.startswith("VOL_"):
            continue
        links = _vol_links(o)
        # walk in reverse so removals don't shift indices
        i = len(links) - 1
        any_removed = False
        while i >= 0:
            tname = links[i].target_name
            if not scene.objects.get(tname):
                links.remove(i)
                cleaned.append((o.name, tname))
                log(f"  [vol] cleaned orphaned link {o.name} → '{tname}' (target deleted)")
                any_removed = True
            i -= 1
        if any_removed:
            _rename_vol_for_links(o)
    return cleaned


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
        # Blender Y maps to game Z (up axis), so use location.z for height
        surface_y = round(o.location.z, 4)
        o["og_water_surface"] = surface_y
        # Auto-set reasonable wade/swim/bottom relative to surface if not manually set
        if "og_water_wade"   not in o: o["og_water_wade"]   = round(surface_y - 0.5, 4)
        if "og_water_swim"   not in o: o["og_water_swim"]   = round(surface_y - 1.0, 4)
        if "og_water_bottom" not in o: o["og_water_bottom"] = round(surface_y - 5.0, 4)
        self.report({"INFO"}, f"Water surface set to {surface_y:.2f}m from object Z")
        return {"FINISHED"}


class OG_OT_SetCrateType(Operator):
    """Set the crate type on the selected crate actor."""
    bl_idname  = "og.set_crate_type"
    bl_label   = "Set Crate Type"
    bl_options = {"REGISTER", "UNDO"}

    crate_type: bpy.props.StringProperty()

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            o["og_crate_type"] = self.crate_type
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
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}


# ── Platforms panel ───────────────────────────────────────────────────────────


def _draw_platform_settings(layout, sel, scene):
    """Draw per-platform settings for the active platform actor."""
    etype = sel.name.split("_", 2)[1]
    einfo = ENTITY_DEFS.get(etype, {})

    layout.label(text=einfo.get("label", etype), icon="CUBE")

    # ── Sync controls (plat, plat-eco, side-to-side-plat) ────────────────────
    if einfo.get("needs_sync"):
        box = layout.box()
        box.label(text="Sync (Path Timing)", icon="TIME")

        wp_prefix = sel.name + "_wp_"
        wp_count  = sum(1 for o in _level_objects(scene)
                        if o.name.startswith(wp_prefix) and o.type == "EMPTY")

        if wp_count < 2:
            box.label(text="⚠ Add ≥2 waypoints to enable movement", icon="INFO")
        else:
            box.label(text=f"✓ {wp_count} waypoints — platform will move", icon="CHECKMARK")

        col = box.column(align=True)

        # Period
        row = col.row(align=True)
        row.label(text="Period (s):")
        period = float(sel.get("og_sync_period", 4.0))
        op = row.operator("og.nudge_float_prop", text="-0.5", icon="REMOVE")
        op.prop_name = "og_sync_period"; op.delta = -0.5; op.val_min = 0.5
        row.label(text=f"{period:.1f}s")
        op = row.operator("og.nudge_float_prop", text="+0.5", icon="ADD")
        op.prop_name = "og_sync_period"; op.delta = 0.5; op.val_max = 300.0

        # Phase
        row = col.row(align=True)
        row.label(text="Phase (0–1):")
        phase = float(sel.get("og_sync_phase", 0.0))
        op = row.operator("og.nudge_float_prop", text="-0.1", icon="REMOVE")
        op.prop_name = "og_sync_phase"; op.delta = -0.1; op.val_min = 0.0
        row.label(text=f"{phase:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.1", icon="ADD")
        op.prop_name = "og_sync_phase"; op.delta = 0.1; op.val_max = 0.9

        # Ease out
        row = col.row(align=True)
        row.label(text="Ease Out:")
        ease_out = float(sel.get("og_sync_ease_out", 0.15))
        op = row.operator("og.nudge_float_prop", text="-0.05", icon="REMOVE")
        op.prop_name = "og_sync_ease_out"; op.delta = -0.05; op.val_min = 0.0
        row.label(text=f"{ease_out:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.05", icon="ADD")
        op.prop_name = "og_sync_ease_out"; op.delta = 0.05; op.val_max = 0.5

        # Ease in
        row = col.row(align=True)
        row.label(text="Ease In:")
        ease_in = float(sel.get("og_sync_ease_in", 0.15))
        op = row.operator("og.nudge_float_prop", text="-0.05", icon="REMOVE")
        op.prop_name = "og_sync_ease_in"; op.delta = -0.05; op.val_min = 0.0
        row.label(text=f"{ease_in:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.05", icon="ADD")
        op.prop_name = "og_sync_ease_in"; op.delta = 0.05; op.val_max = 0.5

        # Wrap phase toggle
        wrap = bool(sel.get("og_sync_wrap", 0))
        row = box.row()
        icon = "CHECKBOX_HLT" if wrap else "CHECKBOX_DEHLT"
        label = "Loop (wrap-phase) ✓" if wrap else "Loop (wrap-phase)"
        row.operator("og.toggle_platform_wrap", text=label, icon=icon)

        box.operator("og.set_platform_defaults", text="Reset to Defaults", icon="LOOP_BACK")

        if wp_count >= 2:
            box.label(text="Tip: phase staggers multiple platforms", icon="INFO")

    # ── plat-button path info ─────────────────────────────────────────────────
    if einfo.get("needs_path") and not einfo.get("needs_sync"):
        box = layout.box()
        box.label(text="Path (Button Travel)", icon="ANIM")
        wp_prefix = sel.name + "_wp_"
        wp_count  = sum(1 for o in _level_objects(scene)
                        if o.name.startswith(wp_prefix) and o.type == "EMPTY")
        if wp_count < 2:
            box.label(text="⚠ Needs ≥2 waypoints (start + end)", icon="ERROR")
        else:
            box.label(text=f"✓ {wp_count} waypoints", icon="CHECKMARK")
        box.label(text="Use Waypoints panel to add points ↓", icon="INFO")

    # ── notice-dist (plat-eco) ────────────────────────────────────────────────
    if einfo.get("needs_notice_dist"):
        box = layout.box()
        box.label(text="Eco Notice Distance", icon="RADIOBUT_ON")
        notice = float(sel.get("og_notice_dist", -1.0))
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-5m", icon="REMOVE")
        op.prop_name = "og_notice_dist"; op.delta = -5.0; op.val_min = 0.0
        if notice < 0:
            row.label(text="∞ (always active)")
        else:
            row.label(text=f"{notice:.0f}m")
        op = row.operator("og.nudge_float_prop", text="+5m", icon="ADD")
        op.prop_name = "og_notice_dist"; op.delta = 5.0; op.val_max = 500.0
        toggle_row = box.row()
        if notice < 0:
            toggle_row.label(text="Moves without eco — click +5m to set range", icon="INFO")
        else:
            op = toggle_row.operator("og.nudge_float_prop", text="Set Always Active", icon="RADIOBUT_ON")
            op.prop_name = "og_notice_dist"; op.delta = -999.0; op.val_min = -1.0


# ===========================================================================
# PANELS — Restructured UI
# ---------------------------------------------------------------------------
# Tab: OpenGOAL (N-panel)
#
#  📁 Level              OG_PT_Level          (parent, always open)
#    🗂 Level Manager     OG_PT_LevelManagerSub (sub, DEFAULT_CLOSED)
#    📂 Collections       OG_PT_CollectionProperties (sub, DEFAULT_CLOSED, poll-gated)
#      Disable Export    OG_PT_DisableExport     (sub-sub, DEFAULT_CLOSED)
#      🧹 Clean          OG_PT_CleanSub          (sub-sub, DEFAULT_CLOSED)
#    💡 Light Baking      OG_PT_LightBakingSub  (sub, DEFAULT_CLOSED)
#    🎵 Music             OG_PT_Music           (sub, DEFAULT_CLOSED)
#
#  📁 Spawn              OG_PT_Spawn          (parent, DEFAULT_CLOSED)
#    ⚔ Enemies           OG_PT_SpawnEnemies   (sub, DEFAULT_CLOSED)
#    🟦 Platforms         OG_PT_SpawnPlatforms (sub, DEFAULT_CLOSED)
#    📦 Props & Objects   OG_PT_SpawnProps     (sub, DEFAULT_CLOSED)
#    🧍 NPCs              OG_PT_SpawnNPCs      (sub, DEFAULT_CLOSED)
#    ⭐ Pickups           OG_PT_SpawnPickups   (sub, DEFAULT_CLOSED)
#    🔊 Sound Emitters    OG_PT_SpawnSounds    (sub, DEFAULT_CLOSED)
#    🗺 Level Flow        OG_PT_SpawnLevelFlow (sub, DEFAULT_CLOSED)
#    📷 Cameras           OG_PT_Camera         (sub, DEFAULT_CLOSED)
#    🔗 Triggers          OG_PT_Triggers       (sub, DEFAULT_CLOSED)
#
#  🔍 Selected Object   OG_PT_SelectedObject    (always visible)
#    Collision          OG_PT_SelectedCollision  (sub, DEFAULT_CLOSED, mesh poll)
#    Light Baking       OG_PT_SelectedLightBaking(sub, DEFAULT_CLOSED, mesh poll)
#    NavMesh            OG_PT_SelectedNavMeshTag (sub, DEFAULT_CLOSED, mesh poll)
#  〰 Waypoints          OG_PT_Waypoints          (context, poll-gated)
#  ▶  Build & Play       OG_PT_BuildPlay      (always visible)
#  🔧 Developer Tools    OG_PT_DevTools       (DEFAULT_CLOSED)
#  Collision             OG_PT_Collision      (object context)
# ===========================================================================

def _header_sep(layout):
    layout.separator(factor=0.4)

# ---------------------------------------------------------------------------
# Helpers — shared entity draw helpers
# ---------------------------------------------------------------------------

_ENEMY_CATS  = {"Enemies", "Bosses"}
_PROP_CATS   = {"Props", "Objects", "Debug"}
_NPC_CATS    = {"NPCs"}
_PICKUP_CATS = {"Pickups"}

def _entity_enum_for_cats(cats):
    """Return enum items filtered to the given category set, in display order."""
    return [
        (ek, ei["label"], ei.get("label",""), i)
        for i, (ek, ei) in enumerate(
            (k, v) for k, v in ENTITY_DEFS.items() if v.get("cat") in cats
        )
    ]

def _draw_entity_sub(layout, ctx, cats, nav_inline=False, prop_name="entity_type"):
    """Shared draw logic for entity sub-panels.
    cats:       set of category strings to include.
    nav_inline: if True, show navmesh status/link inline when a nav-enemy actor is selected.
    prop_name:  OGProperties prop holding this sub-panel's selected type.
    """
    props = ctx.scene.og_props
    etype = getattr(props, prop_name, props.entity_type)
    einfo = ENTITY_DEFS.get(etype, {})

    # Filtered dropdown — only shows types for this sub-panel's categories
    layout.prop(props, prop_name, text="")

    if etype == "crate":
        layout.prop(props, "crate_type", text="Crate Type")

    _draw_wiki_preview(layout, etype, ctx)

    # ── Spawn requirements info ──────────────────────────────────────────
    if einfo.get("is_prop"):
        box = layout.box()
        box.label(text="Prop — idle animation only", icon="INFO")
        box.label(text="No AI or combat")
    elif nav_inline and etype in NAV_UNSAFE_TYPES:
        box = layout.box()
        box.label(text="Nav-enemy — needs navmesh", icon="ERROR")
        box.prop(props, "nav_radius", text="Sphere Radius (m)")

        # ── Inline navmesh link status ───────────────────────────────────
        # Shows when ANY nav-enemy actor is selected — uses actor's actual type,
        # not the dropdown (so selecting a babak actor always shows its navmesh
        # status regardless of what the entity picker currently shows).
        sel = ctx.active_object
        if sel and sel.name.startswith("ACTOR_") and "_wp_" not in sel.name:
            parts = sel.name.split("_", 2)
            if len(parts) >= 3 and _actor_uses_navmesh(parts[1]):
                nm_name = sel.get("og_navmesh_link", "")
                nm_obj  = bpy.data.objects.get(nm_name) if nm_name else None
                layout.separator(factor=0.3)
                layout.label(text=f"NavMesh — {sel.name}", icon="MOD_MESHDEFORM")
                row = layout.row(align=True)
                if nm_obj:
                    row.label(text=f"✓ {nm_obj.name}", icon="CHECKMARK")
                    row.operator("og.unlink_navmesh", text="", icon="X")
                else:
                    row.label(text="No mesh linked", icon="ERROR")
                    # Only show Link button when a mesh is also in the selection
                    sel_meshes = [o for o in ctx.selected_objects if o.type == "MESH"]
                    if sel_meshes:
                        box2 = layout.box()
                        box2.label(text=f"Will link to: {sel_meshes[0].name}", icon="INFO")
                        box2.operator("og.link_navmesh", text="Link NavMesh", icon="LINKED")
                    else:
                        box2 = layout.box()
                        box2.label(text="Shift-select a mesh to link", icon="INFO")
    elif einfo.get("needs_pathb"):
        box = layout.box()
        box.label(text="Needs 2 path sets", icon="INFO")
        box.label(text="Waypoints: _wp_00... and _wpb_00...")
    elif einfo.get("needs_path"):
        box = layout.box()
        box.label(text="Needs waypoints to patrol", icon="INFO")

    layout.separator(factor=0.3)
    op = layout.operator("og.spawn_entity", text="Add Entity", icon="ADD")
    op.source_prop = prop_name


# ===========================================================================
# LEVEL PANEL (parent)
# ===========================================================================

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
        # Parent header only — content lives in sub-panels
        pass


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
        _draw_entity_sub(self.layout, ctx, _ENEMY_CATS, nav_inline=True, prop_name="enemy_type")


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
        ct = sel.get("og_crate_type", "steel")
        box = layout.box()
        box.label(text=f"Crate Type: {ct}", icon="PACKAGE")

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
        ct     = sel.get("og_crate_type", "steel")

        box = layout.box()
        box.label(text="Crate Type", icon="PACKAGE")
        col = box.column(align=True)
        for (val, label, _, _) in CRATE_ITEMS:
            row = col.row(align=True)
            icon = "RADIOBUT_ON" if ct == val else "RADIOBUT_OFF"
            op = row.operator("og.set_crate_type", text=label, icon=icon)
            op.crate_type = val


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
        return len(parts) >= 3 and parts[0] == "ACTOR" and parts[1] == "eco-door"

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        box = layout.box()
        box.label(text="Door Behaviour", icon="SETTINGS")

        auto_close = bool(sel.get("og_door_auto_close", False))
        one_way    = bool(sel.get("og_door_one_way", False))

        row = box.row()
        icon = "CHECKBOX_HLT" if auto_close else "CHECKBOX_DEHLT"
        row.operator("og.toggle_door_flag", text="Auto Close", icon=icon).flag = "auto_close"

        row2 = box.row()
        icon2 = "CHECKBOX_HLT" if one_way else "CHECKBOX_DEHLT"
        row2.operator("og.toggle_door_flag", text="One Way", icon=icon2).flag = "one_way"

        sub = box.row(); sub.enabled = False
        if auto_close and one_way:
            sub.label(text="Closes after Jak passes, one direction only", icon="INFO")
        elif auto_close:
            sub.label(text="Door closes automatically after Jak passes", icon="INFO")
        elif one_way:
            sub.label(text="Door can only be opened from one side", icon="INFO")
        else:
            sub.label(text="Default: stays open, bidirectional", icon="INFO")


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

        # Surface height
        box = layout.box()
        box.label(text="Water Heights", icon="MOD_OCEAN")

        water_y  = float(sel.get("og_water_surface", 0.0))
        wade_y   = float(sel.get("og_water_wade",    -0.5))
        swim_y   = float(sel.get("og_water_swim",    -1.0))
        bottom_y = float(sel.get("og_water_bottom",  -5.0))

        col = box.column(align=True)
        for label, prop, val in [
            ("Surface Y:",  "og_water_surface", water_y),
            ("Wade level:", "og_water_wade",    wade_y),
            ("Swim level:", "og_water_swim",    swim_y),
            ("Bottom Y:",   "og_water_bottom",  bottom_y),
        ]:
            row = col.row(align=True)
            row.label(text=label)
            op = row.operator("og.nudge_float_prop", text="-0.5m", icon="REMOVE")
            op.prop_name = prop; op.delta = -0.5; op.val_min = -200.0
            row.label(text=f"{val:.1f}m")
            op = row.operator("og.nudge_float_prop", text="+0.5m", icon="ADD")
            op.prop_name = prop; op.delta = 0.5; op.val_max = 200.0

        sub = box.row(); sub.enabled = False
        sub.label(text="Heights are world Y positions in meters", icon="INFO")

        op = box.operator("og.sync_water_from_object", text="Sync Surface from Object Y", icon="OBJECT_ORIGIN")
        op.actor_name = sel.name


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
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("og.reload_addon",       text="🔄  Reload Addon", icon="FILE_REFRESH")
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
# OPERATOR — Pick NavMesh (eyedropper-style via active selection)
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
    OG_OT_SpawnEntity,
    OG_OT_SpawnCamera, OG_OT_SpawnCamAlign, OG_OT_SpawnCamPivot,
    OG_OT_SpawnCamLookAt,
    OG_OT_SetCamProp, OG_OT_NudgeCamFloat,
    OG_OT_NudgeFloatProp,
    OG_OT_NudgeIntProp,
    OG_OT_SetLauncherDest, OG_OT_ClearLauncherDest, OG_OT_AddLauncherDest,
    OG_OT_ToggleDoorFlag, OG_OT_SetDoorCP, OG_OT_ClearDoorCP,
    OG_OT_SyncWaterFromObject,
    OG_OT_SetCrateType,
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
    for cls in classes:
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

    bpy.types.Collection.og_no_export      = bpy.props.BoolProperty(
        name="Exclude from Export",
        description="When enabled, this collection and its contents are excluded from level export",
        default=False)

def unregister():
    _unload_previews()
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
