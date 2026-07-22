# ---------------------------------------------------------------------------
# utils.py — OpenGOAL Level Tools
# Shared UI helpers and draw functions used by both operators.py and panels.py.
# No imports from operators or panels (breaks circular dependency).
# ---------------------------------------------------------------------------

import bpy
from bpy.types import Operator
from .data import (
    ENTITY_DEFS, ENTITY_WIKI, ENTITY_ENUM_ITEMS, ENEMY_ENUM_ITEMS,
    PROP_ENUM_ITEMS, NPC_ENUM_ITEMS, PICKUP_ENUM_ITEMS, PLATFORM_ENUM_ITEMS,
    LUMP_REFERENCE, LUMP_TYPE_ITEMS, NAV_UNSAFE_TYPES, IS_PROP_TYPES,
    _actor_has_links, _actor_link_slots, _lump_ref_for_etype, _is_custom_type,
)
from .collections import (
    _get_level_prop, _level_objects, _col_path_for_entity,
)
from .export import (
    _actor_supports_aggro_trigger, _actor_is_platform, _actor_is_launcher,
    _actor_is_spawner, _actor_is_enemy, _actor_uses_waypoints,
    _actor_uses_navmesh,
    _vol_links, _vol_has_link_to, _vols_linking_to, _lname, log,
)
from .properties import OGProperties

def _is_linkable(obj):
    """True if this object type can accept a trigger volume link.
    Cameras, checkpoints, player spawns, nav-enemy actors, and custom GOAL
    type actors are linkable. Process-drawable enemies (Yeti, Bully, etc.)
    are NOT linkable because they don't respond to 'cue-chase events.
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
            if len(parts) >= 3:
                if _actor_supports_aggro_trigger(parts[1]):
                    return True
                if _is_custom_type(parts[1]):
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

        # Period / Phase / Ease — use _prop_row (safe: no writes in draw)
        _prop_row(col, sel, "og_sync_period",   "Period (s):",  4.0)
        _prop_row(col, sel, "og_sync_phase",    "Phase (0–1):", 0.0)
        _prop_row(col, sel, "og_sync_ease_out", "Ease Out:",    0.15)
        _prop_row(col, sel, "og_sync_ease_in",  "Ease In:",     0.15)

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
        _prop_row(box, sel, "og_notice_dist", "Distance (m, -1=always):", -1.0)
        toggle_row = box.row()
        if notice >= 0:
            op = toggle_row.operator("og.nudge_float_prop", text="Set Always Active", icon="RADIOBUT_ON")
            op.prop_name = "og_notice_dist"; op.delta = -999.0; op.val_min = -1.0
        else:
            toggle_row.label(text="Moves without eco — set value above to limit range", icon="INFO")


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



# ---------------------------------------------------------------------------
# Material draw helper (used in register as MATERIAL_PT_custom_props.prepend)
# ---------------------------------------------------------------------------


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
# Safe UI helper — never writes to object during draw()
# ---------------------------------------------------------------------------

def _prop_row(layout, obj, key, label, default):
    """Draw a labelled input row for a custom property.

    Safe for use inside draw(): never writes to the object.
    If the key is missing, schedules a one-shot timer to write the default
    outside of the draw context, and shows a greyed placeholder meanwhile.
    On the next redraw the key exists and layout.prop() renders normally.

    Blender 4.4+ raises AttributeError on any ID property write inside draw(),
    including custom dict properties (obj[key] = val). Only operator execute()
    or timer callbacks are safe write contexts.
    """
    if key not in obj:
        # Schedule write outside draw — timer fires after current redraw
        obj_name = obj.name
        def _init(name=obj_name, k=key, v=default):
            o = bpy.data.objects.get(name)
            if o is not None and k not in o:
                o[k] = v
            return None  # don't repeat
        bpy.app.timers.register(_init, first_interval=0.0)
        # Show greyed placeholder this frame
        row = layout.row(align=True)
        row.label(text=label)
        sub = row.row()
        sub.enabled = False
        sub.label(text=str(default))
        return
    row = layout.row(align=True)
    row.label(text=label)
    row.prop(obj, f'["{key}"]', text="")
