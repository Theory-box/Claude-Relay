# textures.py — Texture browser panel for the OpenGOAL Blender addon.
#
# Provides:
#   OG_PT_Texturing      — main panel (polls for mesh selection)
#   OG_OT_LoadTextures   — loads PNGs for selected tpage group into preview collection
#   OG_OT_ApplyTexture   — applies selected texture as a material to selected objects
#   OG_OT_TexPagePrev / OG_OT_TexPageNext — pagination operators
#
# Path used:
#   <data_path>/data/decompiler_out/jak1/textures/<tpage_name>/<texture_name>.png

import bpy
import bpy.utils.previews
from bpy.types import Panel, Operator
from bpy.props import StringProperty, IntProperty, EnumProperty, CollectionProperty
from pathlib import Path

from .build import _data_root

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEXTURES_PER_PAGE = 20

# Tpage group → list of tpage folder name prefixes, in display order.
# Folders are matched by startswith() so variants like beach-vis-pris,
# beach-vis-tfrag, beach-vis-shrub etc. all fall under "Beach".
TPAGE_GROUPS = [
    ("ALL",         "All",          []),           # special: show everything
    ("COMMON",      "Common",       ["common"]),
    ("EFFECTS",     "Effects",      ["effects", "environment-generic", "ocean"]),
    ("CHARACTERS",  "Characters",   ["eichar", "sidekick-lod0"]),
    ("BEACH",       "Beach",        ["beach-vis"]),
    ("JUNGLE",      "Jungle",       ["jungle-vis", "jungleb-vis"]),
    ("SWAMP",       "Swamp",        ["swamp-vis"]),
    ("MISTY",       "Misty",        ["misty-vis"]),
    ("SNOW",        "Snow",         ["snow-vis"]),
    ("FIRE_CANYON", "Fire Canyon",  ["firecanyon-vis"]),
    ("LAVA_TUBE",   "Lava Tube",    ["lavatube-vis"]),
    ("OGRE",        "Ogre",         ["ogre-vis"]),
    ("SUNKEN",      "Sunken",       ["sunken-vis", "sunkenb-vis"]),
    ("ROLLING",     "Rolling",      ["rolling-vis"]),
    ("CAVE",        "Cave",         ["maincave-vis", "darkcave-vis", "robocave-vis"]),
    ("VILLAGE",     "Village",      ["village1-vis", "village2-vis", "village3-vis"]),
    ("TRAINING",    "Training",     ["training-vis"]),
    ("CITADEL",     "Citadel",      ["citadel-vis"]),
    ("FINAL_BOSS",  "Final Boss",   ["finalboss-vis"]),
    ("HUD",         "HUD / UI",     ["Hud", "zoomerhud", "gamefontnew"]),
]

TPAGE_GROUP_ITEMS = [(g[0], g[1], "") for g in TPAGE_GROUPS]

# ---------------------------------------------------------------------------
# Preview collection — one global, loaded per-group on demand
# ---------------------------------------------------------------------------

_previews = None          # bpy.utils.previews.ImagePreviewCollection
_loaded_group = None      # which group is currently loaded
_loaded_items = []        # list of (identifier, name, desc, icon_id, index)

def _get_previews():
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()
    return _previews


def _tex_root() -> Path:
    return _data_root() / "data" / "decompiler_out" / "jak1" / "textures"


def _prefixes_for_group(group_id: str):
    for gid, _label, prefixes in TPAGE_GROUPS:
        if gid == group_id:
            return prefixes
    return []


def _png_paths_for_group(group_id: str):
    """Return sorted list of PNG Paths matching the given group."""
    tex_root = _tex_root()
    if not tex_root.exists():
        return []

    prefixes = _prefixes_for_group(group_id)
    paths = []

    for folder in sorted(tex_root.iterdir()):
        if not folder.is_dir():
            continue
        name = folder.name
        if group_id == "ALL" or any(name.startswith(p) for p in prefixes):
            paths.extend(sorted(folder.glob("*.png")))

    return paths


def _load_group(group_id: str):
    """Load PNG previews for the given group into the preview collection."""
    global _loaded_group, _loaded_items

    if _loaded_group == group_id:
        return  # already loaded

    pcoll = _get_previews()
    pcoll.clear()
    _loaded_items = []

    png_paths = _png_paths_for_group(group_id)

    for i, path in enumerate(png_paths):
        key = path.stem  # filename without extension
        if key not in pcoll:
            try:
                pcoll.load(key, str(path), "IMAGE")
            except Exception:
                continue
        icon_id = pcoll[key].icon_id
        _loaded_items.append((key, key, path.parent.name, icon_id, i))

    _loaded_group = group_id


def _page_items(page: int):
    """Return the slice of _loaded_items for the given page (0-indexed)."""
    start = page * TEXTURES_PER_PAGE
    return _loaded_items[start:start + TEXTURES_PER_PAGE]


def _total_pages():
    if not _loaded_items:
        return 0
    return (len(_loaded_items) + TEXTURES_PER_PAGE - 1) // TEXTURES_PER_PAGE


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class OG_OT_LoadTextures(Operator):
    """Load textures for the selected group into the browser"""
    bl_idname  = "og.load_textures"
    bl_label   = "Load Textures"
    bl_options = {"REGISTER"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        if not _tex_root().exists():
            self.report({"WARNING"}, "Texture folder not found — check addon data_path preference.")
            return {"CANCELLED"}
        _load_group(props.tex_group)
        props.tex_page = 0
        props.tex_selected = ""
        n = len(_loaded_items)
        self.report({"INFO"}, f"Loaded {n} texture(s) for group '{props.tex_group}'.")
        return {"FINISHED"}


class OG_OT_TexPagePrev(Operator):
    """Previous page of textures"""
    bl_idname  = "og.tex_page_prev"
    bl_label   = "Previous Page"
    bl_options = {"REGISTER"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        if props.tex_page > 0:
            props.tex_page -= 1
            props.tex_selected = ""
        return {"FINISHED"}


class OG_OT_TexPageNext(Operator):
    """Next page of textures"""
    bl_idname  = "og.tex_page_next"
    bl_label   = "Next Page"
    bl_options = {"REGISTER"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        if props.tex_page < _total_pages() - 1:
            props.tex_page += 1
            props.tex_selected = ""
        return {"FINISHED"}


class OG_OT_SelectTexture(Operator):
    """Select a texture from the grid"""
    bl_idname  = "og.select_texture"
    bl_label   = "Select Texture"
    bl_options = {"REGISTER"}

    tex_name: StringProperty()

    def execute(self, ctx):
        ctx.scene.og_props.tex_selected = self.tex_name
        return {"FINISHED"}


class OG_OT_ApplyTexture(Operator):
    """Apply the selected texture as a material to all selected mesh objects"""
    bl_idname  = "og.apply_texture"
    bl_label   = "Apply to Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        props      = ctx.scene.og_props
        tex_name   = props.tex_selected
        group      = props.tex_group

        if not tex_name:
            self.report({"WARNING"}, "No texture selected.")
            return {"CANCELLED"}

        # Find the PNG path
        png_path = None
        tex_root = _tex_root()
        if tex_root.exists():
            for folder in tex_root.iterdir():
                if not folder.is_dir():
                    continue
                candidate = folder / f"{tex_name}.png"
                if candidate.exists():
                    png_path = candidate
                    break

        if png_path is None:
            self.report({"WARNING"}, f"PNG not found for '{tex_name}'.")
            return {"CANCELLED"}

        targets = [o for o in ctx.selected_objects if o.type == "MESH"]
        if not targets:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        # Build or reuse material
        mat_name = f"og_{tex_name}"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            nodes.clear()

            out   = nodes.new("ShaderNodeOutputMaterial")
            bsdf  = nodes.new("ShaderNodeBsdfPrincipled")
            tex_n = nodes.new("ShaderNodeTexImage")
            out.location  = (300, 0)
            bsdf.location = (0, 0)
            tex_n.location = (-350, 0)

            # Load image (reuse existing data block if already loaded)
            img = bpy.data.images.get(png_path.name)
            if img is None:
                img = bpy.data.images.load(str(png_path))
            img.colorspace_settings.name = "sRGB"
            tex_n.image = img

            links.new(tex_n.outputs["Color"], bsdf.inputs["Base Color"])
            links.new(bsdf.outputs["BSDF"],   out.inputs["Surface"])

        # Assign to all selected meshes
        for obj in targets:
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

        self.report({"INFO"}, f"Applied '{tex_name}' to {len(targets)} object(s).")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class OG_PT_Texturing(Panel):
    bl_label       = "🎨  Texturing"
    bl_idname      = "OG_PT_texturing"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        # Show when at least one mesh is selected
        return any(o.type == "MESH" for o in ctx.selected_objects)

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        tex_root = _tex_root()

        # ── Missing textures warning ──────────────────────────────────────
        if not tex_root.exists():
            box = layout.box()
            box.label(text="Textures not found.", icon="ERROR")
            box.label(text="Run decompiler with")
            box.label(text="save_texture_pngs: true")
            box.label(text="then re-extract.")
            return

        # ── Group selector + Load button ─────────────────────────────────
        row = layout.row(align=True)
        row.prop(props, "tex_group", text="")
        row.operator("og.load_textures", text="Load", icon="FILE_REFRESH")

        # ── Search bar ───────────────────────────────────────────────────
        layout.prop(props, "tex_search", text="", icon="VIEWZOOM")

        # ── Nothing loaded yet ───────────────────────────────────────────
        if _loaded_group != props.tex_group or not _loaded_items:
            layout.label(text="Press Load to browse textures.", icon="INFO")
            return

        # ── Filter by search ─────────────────────────────────────────────
        search = props.tex_search.lower().strip()
        if search:
            filtered = [item for item in _loaded_items if search in item[0].lower()]
        else:
            filtered = _loaded_items

        total   = len(filtered)
        n_pages = max(1, (total + TEXTURES_PER_PAGE - 1) // TEXTURES_PER_PAGE)
        page    = min(props.tex_page, n_pages - 1)
        start   = page * TEXTURES_PER_PAGE
        items   = filtered[start:start + TEXTURES_PER_PAGE]

        # ── Pagination header ─────────────────────────────────────────────
        prow = layout.row(align=True)
        prow.operator("og.tex_page_prev", text="", icon="TRIA_LEFT")
        prow.label(text=f"Page {page + 1} / {n_pages}  ({total} textures)")
        prow.operator("og.tex_page_next", text="", icon="TRIA_RIGHT")

        layout.separator(factor=0.3)

        # ── Texture grid (4 columns) ──────────────────────────────────────
        pcoll   = _get_previews()
        col_n   = 4
        grid    = layout.grid_flow(row_major=True, columns=col_n,
                                   even_columns=True, even_rows=True, align=True)

        for (key, name, tpage, icon_id, _idx) in items:
            cell = grid.column(align=True)
            is_selected = (props.tex_selected == key)

            # Highlight selected with a box
            if is_selected:
                box = cell.box()
                box.scale_y = 0.85
                box.template_icon(icon_value=icon_id, scale=4.5)
                op = box.operator("og.select_texture", text=key[:12], emboss=True, depress=True)
            else:
                cell.template_icon(icon_value=icon_id, scale=4.5)
                op = cell.operator("og.select_texture", text=key[:12], emboss=False)
            op.tex_name = key

        layout.separator(factor=0.5)

        # ── Selected texture info + Apply button ──────────────────────────
        if props.tex_selected:
            box = layout.box()
            box.label(text=props.tex_selected, icon="IMAGE_DATA")

            # Find which tpage it came from
            for (key, name, tpage, icon_id, _idx) in _loaded_items:
                if key == props.tex_selected:
                    box.label(text=f"Source: {tpage}", icon="TEXTURE")
                    break

            box.operator("og.apply_texture", text="Apply to Selected", icon="CHECKMARK")
        else:
            layout.label(text="Click a texture to select it.", icon="INFO")


# ---------------------------------------------------------------------------
# Registration helpers (called from __init__.py)
# ---------------------------------------------------------------------------

TEXTURING_CLASSES = (
    OG_OT_LoadTextures,
    OG_OT_TexPagePrev,
    OG_OT_TexPageNext,
    OG_OT_SelectTexture,
    OG_OT_ApplyTexture,
    OG_PT_Texturing,
)


def register_texturing():
    global _previews
    _previews = bpy.utils.previews.new()


def unregister_texturing():
    global _previews, _loaded_group, _loaded_items
    if _previews:
        bpy.utils.previews.remove(_previews)
        _previews = None
    _loaded_group = None
    _loaded_items = []
