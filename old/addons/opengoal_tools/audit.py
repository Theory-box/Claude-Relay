# audit.py — Level Audit checks for the OpenGOAL Blender addon.
#
# HOW TO EXTEND THIS SYSTEM
# ──────────────────────────
# 1. New actor type (standard requirements):
#    Add an "audit" block to its ENTITY_DEFS entry in data.py:
#
#      "my-actor": {
#          ...,
#          "audit": {
#              "requires_navmesh":  False,
#              "requires_path":     False,
#              "requires_pathb":    False,
#              "required_links":    [],      # lump_key strings
#              "custom_checks":     [],      # callables: (scene, obj) -> (sev, msg) | None
#          }
#      }
#    run_audit() reads this automatically.
#
# 2. New structural dependency (new prefix, scene-level rule):
#    Add a function to _REGISTERED_CHECKS at the bottom of this file.

from .data import (
    ENTITY_DEFS,
    NAV_UNSAFE_TYPES,
    NEEDS_PATH_TYPES,
    GLOBAL_TPAGE_GROUPS,
    ACTOR_LINK_DEFS,
    _actor_link_slots,
    _actor_get_link,
)
from .collections import _level_objects

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _etype(o):
    if not (o.name.startswith("ACTOR_") and o.type == "EMPTY"):
        return None
    if "_wp_" in o.name or "_wpb_" in o.name:
        return None
    parts = o.name.split("_", 2)
    return parts[1] if len(parts) >= 2 else None

def _actor_objs(scene):
    return [o for o in _level_objects(scene)
            if o.name.startswith("ACTOR_") and o.type == "EMPTY"
            and "_wp_" not in o.name and "_wpb_" not in o.name]

def _vol_objs(scene):
    return [o for o in _level_objects(scene)
            if o.type == "MESH" and o.name.startswith("VOL_")]

def _spawn_objs(scene):
    return [o for o in _level_objects(scene)
            if o.name.startswith("SPAWN_") and o.type == "EMPTY"]

def _checkpoint_objs(scene):
    return [o for o in _level_objects(scene)
            if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY"]

def _camera_objs(scene):
    return [o for o in _level_objects(scene)
            if o.name.startswith("CAMERA_") and o.type == "CAMERA"]

def _issue(severity, message, obj_name=None):
    return {"severity": severity, "message": message, "obj_name": obj_name}


# ---------------------------------------------------------------------------
# Check 1 — Tpage budget
# ---------------------------------------------------------------------------

def check_tpage_budget(scene):
    issues = []
    groups = set()
    for o in _actor_objs(scene):
        et   = _etype(o)
        info = ENTITY_DEFS.get(et, {}) if et else {}
        grp  = info.get("tpage_group")
        if grp and grp not in GLOBAL_TPAGE_GROUPS:
            groups.add(grp)
    if len(groups) > 2:
        issues.append(_issue("WARNING",
            f"Tpage budget: {len(groups)} non-global groups in use "
            f"({', '.join(sorted(groups))}). Jak 1 can load at most 2 "
            "non-global tpage groups per level — extra groups will fail to stream art."))
    elif len(groups) == 2:
        issues.append(_issue("INFO",
            f"Tpage groups: 2 non-global groups in use ({', '.join(sorted(groups))}). "
            "This is the maximum — adding more non-global actor types may break art loading."))
    return issues


# ---------------------------------------------------------------------------
# Check 2 — Nav-enemy navmesh links
# ---------------------------------------------------------------------------

def check_navmesh_links(scene):
    issues = []
    objects = scene.objects
    for o in _actor_objs(scene):
        et = _etype(o)
        if not et or et not in NAV_UNSAFE_TYPES:
            continue
        nm_name = o.get("og_navmesh_link", "")
        if not nm_name:
            issues.append(_issue("ERROR",
                f"Nav-enemy '{o.name}' ({et}) has no navmesh link. "
                "It will freeze or crash in-game without one.", o.name))
        elif objects.get(nm_name) is None:
            issues.append(_issue("ERROR",
                f"Nav-enemy '{o.name}' ({et}) navmesh link '{nm_name}' "
                "does not exist in the scene.", o.name))
    return issues


# ---------------------------------------------------------------------------
# Check 3 — Missing required path waypoints
# ---------------------------------------------------------------------------

def check_missing_paths(scene):
    issues = []
    for o in _actor_objs(scene):
        et = _etype(o)
        if not et or et not in NEEDS_PATH_TYPES:
            continue
        info      = ENTITY_DEFS.get(et, {})
        wp_prefix = o.name + "_wp_"
        wpb_prefix = o.name + "_wpb_"
        wp_count  = sum(1 for ob in _level_objects(scene) if ob.name.startswith(wp_prefix))
        wpb_count = sum(1 for ob in _level_objects(scene) if ob.name.startswith(wpb_prefix))
        if wp_count == 0:
            issues.append(_issue("ERROR",
                f"'{o.name}' ({et}) requires path waypoints but has none.", o.name))
        if info.get("needs_pathb") and wpb_count == 0:
            issues.append(_issue("ERROR",
                f"'{o.name}' ({et}) also requires a B-path (pathb) but has none.", o.name))
    return issues


# ---------------------------------------------------------------------------
# Check 4 — Actor link slots (required unset + broken targets)
# ---------------------------------------------------------------------------

def check_actor_links(scene):
    issues = []
    objects = scene.objects
    for o in _actor_objs(scene):
        et = _etype(o)
        if not et:
            continue
        for slot in _actor_link_slots(et):
            lump_key = slot[0]
            slot_idx = slot[1] if len(slot) > 1 else 0
            required = slot[4] if len(slot) > 4 else False
            if required:
                filled = bool(_actor_get_link(o, lump_key, slot_idx))
                if not filled:
                    issues.append(_issue("WARNING",
                        f"'{o.name}' ({et}): required link slot '{lump_key}' is unset.",
                        o.name))
        for lk in getattr(o, "og_actor_links", []):
            if not lk.target_name.strip():
                continue
            if objects.get(lk.target_name) is None:
                issues.append(_issue("ERROR",
                    f"'{o.name}' ({et}): link '{lk.lump_key}' points to "
                    f"'{lk.target_name}' which does not exist.", o.name))
    return issues


# ---------------------------------------------------------------------------
# Check 5 — Volume links
# ---------------------------------------------------------------------------

def check_volumes(scene):
    issues = []
    objects = scene.objects
    for vol in _vol_objs(scene):
        links = getattr(vol, "og_vol_links", [])
        if len(links) == 0:
            issues.append(_issue("WARNING",
                f"Trigger volume '{vol.name}' has no links. "
                "It will export as dead weight.", vol.name))
            continue
        for lk in links:
            target = lk.target_name.strip()
            if not target:
                issues.append(_issue("WARNING",
                    f"Volume '{vol.name}' has a link with an empty target name.", vol.name))
            elif objects.get(target) is None:
                issues.append(_issue("ERROR",
                    f"Volume '{vol.name}' links to '{target}' which does not exist.", vol.name))
    return issues


# ---------------------------------------------------------------------------
# Check 6 — Spawn points
# ---------------------------------------------------------------------------

def check_spawn_points(scene):
    issues = []
    spawns = _spawn_objs(scene)
    if len(spawns) == 0:
        issues.append(_issue("ERROR",
            "No SPAWN_ empty found. The level has no player start position."))
    elif len(spawns) > 1:
        names = ", ".join(o.name for o in spawns)
        issues.append(_issue("WARNING",
            f"Multiple SPAWN_ empties found ({names}). "
            "The engine picks one arbitrarily — remove extras."))
    return issues


# ---------------------------------------------------------------------------
# Check 7 — Duplicate actor names
# ---------------------------------------------------------------------------

def check_duplicate_names(scene):
    issues = []
    seen = {}
    for o in _actor_objs(scene):
        seen[o.name] = seen.get(o.name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            issues.append(_issue("ERROR",
                f"Duplicate object name '{name}' ({count} objects). "
                "The engine resolves actors by name — duplicates cause wrong-entity lookups.",
                name))
    return issues


# ---------------------------------------------------------------------------
# Check 8 — Camera targets in volumes
# ---------------------------------------------------------------------------

def check_camera_targets(scene):
    issues = []
    objects = scene.objects
    for vol in _vol_objs(scene):
        for lk in getattr(vol, "og_vol_links", []):
            target = lk.target_name.strip()
            if not target:
                continue
            obj = objects.get(target)
            if obj is None:
                continue  # caught by check_volumes
            if target.startswith("CAMERA_") and obj.type != "CAMERA":
                issues.append(_issue("WARNING",
                    f"Volume '{vol.name}' links to '{target}' "
                    "which is named like a camera but is not a Camera object.", vol.name))
    return issues


# ---------------------------------------------------------------------------
# Check 9 — Door system checks (v1.7.0)
# ---------------------------------------------------------------------------

_ECO_DOOR_ETYPES = {"eco-door", "jng-iris-door", "sidedoor", "rounddoor"}

def check_doors(scene):
    issues  = []
    objects = scene.objects
    actors  = _actor_objs(scene)

    # Build set of basebutton names that ARE targeted by a door's state-actor
    used_buttons = set()
    for o in actors:
        et = _etype(o)
        if et not in _ECO_DOOR_ETYPES:
            continue
        link = _actor_get_link(o, "state-actor", 0)
        if link and link.target_name.strip():
            used_buttons.add(link.target_name.strip())

    for o in actors:
        et = _etype(o)
        if not et:
            continue

        # eco-door family: state-actor target should be a basebutton
        if et in _ECO_DOOR_ETYPES:
            link = _actor_get_link(o, "state-actor", 0)
            target_name = link.target_name.strip() if link else ""
            if target_name:
                try:
                    target_obj = objects.get(target_name)
                except Exception:
                    target_obj = None
                if target_obj:
                    target_et = _etype(target_obj)
                    if target_et and target_et != "basebutton":
                        issues.append(_issue("INFO",
                            f"'{o.name}' ({et}): state-actor target '{target_name}' "
                            f"is a '{target_et}', not a basebutton. "
                            "This can work but basebutton is the standard controller.",
                            o.name))

        # launcherdoor: needs a continue-name pointing to a real checkpoint
        if et == "launcherdoor":
            cp_name = str(o.get("og_continue_name", "")).strip()
            if not cp_name:
                issues.append(_issue("WARNING",
                    f"'{o.name}' (launcherdoor) has no continue-name set. "
                    "The door won't know which checkpoint to activate when opened.",
                    o.name))
            else:
                try:
                    cp_obj = objects.get(cp_name)
                except Exception:
                    cp_obj = None
                if cp_obj is None:
                    issues.append(_issue("ERROR",
                        f"'{o.name}' (launcherdoor) continue-name '{cp_name}' "
                        "does not exist in the scene.", o.name))

        # basebutton: warn if nothing is listening to it
        if et == "basebutton":
            if o.name not in used_buttons:
                issues.append(_issue("WARNING",
                    f"'{o.name}' (basebutton) is not linked to any door via "
                    "state-actor. The button will animate but open nothing.",
                    o.name))

    return issues


# ---------------------------------------------------------------------------
# Check 10 — Data-driven custom_checks from ENTITY_DEFS audit blocks
# (future-proof: new features declare their checks in data.py, not here)
# ---------------------------------------------------------------------------

def check_entity_defs_audit_blocks(scene):
    issues = []
    for o in _actor_objs(scene):
        et = _etype(o)
        if not et:
            continue
        info  = ENTITY_DEFS.get(et, {})
        audit = info.get("audit", {})
        for check_fn in audit.get("custom_checks", []):
            try:
                result = check_fn(scene, o)
                if result:
                    sev, msg = result
                    issues.append(_issue(sev, msg, o.name))
            except Exception as exc:
                issues.append(_issue("WARNING",
                    f"Custom audit check for '{et}' raised: {exc}", o.name))
    return issues


# ---------------------------------------------------------------------------
# Check 11 — Scene summary (always INFO, always last)
# ---------------------------------------------------------------------------

def check_scene_summary(scene):
    issues  = []
    actors  = _actor_objs(scene)
    vols    = _vol_objs(scene)
    cameras = _camera_objs(scene)
    checkpts= _checkpoint_objs(scene)
    spawns  = _spawn_objs(scene)

    cats = {}
    for o in actors:
        et   = _etype(o)
        info = ENTITY_DEFS.get(et, {}) if et else {}
        cat  = info.get("cat", "Unknown")
        cats[cat] = cats.get(cat, 0) + 1
    cat_str = ", ".join(f"{v} {k}" for k, v in sorted(cats.items())) or "none"

    issues.append(_issue("INFO",
        f"Scene: {len(actors)} actor(s) ({cat_str}), "
        f"{len(vols)} volume(s), {len(cameras)} camera(s), "
        f"{len(checkpts)} checkpoint(s), {len(spawns)} spawn(s)."))

    groups = {}
    for o in actors:
        et   = _etype(o)
        info = ENTITY_DEFS.get(et, {}) if et else {}
        grp  = info.get("tpage_group")
        if grp:
            groups[grp] = groups.get(grp, 0) + 1
    if groups:
        non_global = {k: v for k, v in groups.items() if k not in GLOBAL_TPAGE_GROUPS}
        always     = {k: v for k, v in groups.items() if k in GLOBAL_TPAGE_GROUPS}
        parts = []
        if non_global:
            parts.append("non-global: " + ", ".join(f"{k}×{v}" for k, v in sorted(non_global.items())))
        if always:
            parts.append("always-resident: " + ", ".join(f"{k}×{v}" for k, v in sorted(always.items())))
        if parts:
            issues.append(_issue("INFO", "Tpage groups — " + "; ".join(parts)))

    return issues


# ---------------------------------------------------------------------------
# Registry — all active checks. Append here to add new ones.
# ---------------------------------------------------------------------------

_REGISTERED_CHECKS = [
    check_tpage_budget,
    check_navmesh_links,
    check_missing_paths,
    check_actor_links,
    check_volumes,
    check_spawn_points,
    check_duplicate_names,
    check_camera_targets,
    check_doors,
    check_entity_defs_audit_blocks,
    check_scene_summary,   # always last
]

_SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}


def run_audit(scene):
    """Run all registered checks. Returns issues sorted ERROR → WARNING → INFO."""
    issues = []
    for check in _REGISTERED_CHECKS:
        try:
            issues.extend(check(scene))
        except Exception as exc:
            issues.append(_issue("WARNING",
                f"Audit check '{check.__name__}' raised an unexpected error: {exc}"))
    issues.sort(key=lambda i: _SEVERITY_ORDER.get(i["severity"], 99))
    return issues
