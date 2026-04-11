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
# Preview collection — loaded once at register(), cleared at unregister().
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
# NAV MESH — geometry processing and GOAL code generation
# ---------------------------------------------------------------------------

def _navmesh_compute(world_tris):
    """
    world_tris: list of 3-tuples of (x,y,z) world-space points (already in game coords)
    Returns dict with all data needed to write the GOAL nav-mesh struct.
    """
    import math
    EPS = 0.01

    verts = []
    def find_or_add(pt):
        for i, v in enumerate(verts):
            if abs(v[0]-pt[0]) < EPS and abs(v[1]-pt[1]) < EPS and abs(v[2]-pt[2]) < EPS:
                return i
        verts.append(pt)
        return len(verts) - 1

    polys = []
    for tri in world_tris:
        i0 = find_or_add(tri[0])
        i1 = find_or_add(tri[1])
        i2 = find_or_add(tri[2])
        if len({i0, i1, i2}) == 3:
            polys.append((i0, i1, i2))

    N = len(polys)
    V = len(verts)
    if N == 0 or V == 0:
        return None

    ox = sum(v[0] for v in verts) / V
    oy = sum(v[1] for v in verts) / V
    oz = sum(v[2] for v in verts) / V
    rel = [(v[0]-ox, v[1]-oy, v[2]-oz) for v in verts]
    max_dist = max(math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in rel)
    bounds_r = max_dist + 5.0

    def edge_key(a, b): return (min(a,b), max(a,b))
    edge_to_polys = {}
    for pi, (v0,v1,v2) in enumerate(polys):
        for ea, eb in [(v0,v1),(v1,v2),(v2,v0)]:
            edge_to_polys.setdefault(edge_key(ea,eb), []).append(pi)

    adj = []
    for pi, (v0,v1,v2) in enumerate(polys):
        neighbors = []
        for ea, eb in [(v0,v1),(v1,v2),(v2,v0)]:
            others = [p for p in edge_to_polys.get(edge_key(ea,eb),[]) if p != pi]
            neighbors.append(others[0] if others else 0xFF)
        adj.append(tuple(neighbors))

    INF = 9999
    def bfs_from(src):
        dist = [INF] * N
        came = [None] * N
        dist[src] = 0
        q = [src]; qi = 0
        while qi < len(q):
            cur = q[qi]; qi += 1
            for slot, nb in enumerate(adj[cur]):
                if nb != 0xFF and dist[nb] == INF:
                    dist[nb] = dist[cur] + 1
                    came[nb] = (cur, slot)
                    q.append(nb)
        next_hop = [3] * N
        for dst in range(N):
            if dst == src or dist[dst] == INF:
                continue
            node = dst
            while came[node][0] != src:
                node = came[node][0]
            next_hop[dst] = came[node][1]
        return next_hop

    route_table = [bfs_from(i) for i in range(N)]
    total_bits = N * N * 2
    total_bytes = (total_bits + 7) // 8
    route_bytes = bytearray(total_bytes)
    for frm in range(N):
        for to in range(N):
            val = route_table[frm][to] & 3
            bit_idx = (frm * N + to) * 2
            byte_idx = bit_idx // 8
            bit_off = bit_idx % 8
            route_bytes[byte_idx] |= (val << bit_off)
    total_vec4ub = (total_bytes + 3) // 4
    padded = route_bytes + bytearray(total_vec4ub * 4 - len(route_bytes))
    vec4ubs = [tuple(padded[i*4:(i+1)*4]) for i in range(total_vec4ub)]

    # Build BVH nodes — required by find-poly-fast (called during enemy chase).
    # Without nodes, recursive-inside-poly dereferences null -> crash.
    # For small meshes we use a simple flat structure:
    # One root node per group of <=4 polys, so ceil(N/4) leaf nodes,
    # plus one branch node if more than one leaf.
    # For our typical small meshes (2-16 polys) one leaf node is enough.
    # Leaf node: type != 0, num-tris stored in low 16 bits of left-offset field.
    # first-tris: up to 4 poly indices packed in 4 uint8 slots.
    # last-tris:  next 4 poly indices (for polys 5-8).
    # center/radius: AABB of all verts in the node (in local/rel coords).
    import math as _math

    # Compute AABB of all relative verts for the node bounding box
    xs = [v[0] for v in rel]; ys = [v[1] for v in rel]; zs = [v[2] for v in rel]
    cx = (_math.fsum(xs)) / V
    cy = (_math.fsum(ys)) / V
    cz = (_math.fsum(zs)) / V
    rx = max(abs(x - cx) for x in xs) + 1.0  # 1m padding
    ry = max(abs(y - cy) for y in ys) + 5.0  # extra Y padding for height tolerance
    rz = max(abs(z - cz) for z in zs) + 1.0

    # Build flat list of leaf nodes — one per group of 4 polys
    # Each leaf: (cx, cy, cz, rx, ry, rz, [poly_idx...])
    nodes = []
    for start in range(0, N, 4):
        chunk = list(range(start, min(start+4, N)))
        # AABB for this chunk's verts
        chunk_verts = []
        for pi in chunk:
            for vi in polys[pi]:
                chunk_verts.append(rel[vi])
        if chunk_verts:
            cxs = [v[0] for v in chunk_verts]
            cys = [v[1] for v in chunk_verts]
            czs = [v[2] for v in chunk_verts]
            ncx = (_math.fsum(cxs)) / len(cxs)
            ncy = (_math.fsum(cys)) / len(cys)
            ncz = (_math.fsum(czs)) / len(czs)
            nrx = max(abs(x - ncx) for x in cxs) + 1.0
            nry = max(abs(y - ncy) for y in cys) + 5.0
            nrz = max(abs(z - ncz) for z in czs) + 1.0
        else:
            ncx, ncy, ncz, nrx, nry, nrz = cx, cy, cz, rx, ry, rz
        nodes.append((ncx, ncy, ncz, nrx, nry, nrz, chunk))

    return {
        'origin': (ox, oy, oz), 'bounds_r': bounds_r,
        'verts_rel': rel, 'polys': polys, 'adj': adj,
        'vec4ubs': vec4ubs, 'poly_count': N, 'vertex_count': V,
        'nodes': nodes,
        'node_aabb': (cx, cy, cz, rx, ry, rz),
    }


def _navmesh_to_goal(mesh, actor_aid):
    ox, oy, oz = mesh['origin']
    br = mesh['bounds_r']
    N = mesh['poly_count']
    V = mesh['vertex_count']

    def gx(n):
        """Format integer as GOAL hex literal: #x0, #xff, #x1a etc."""
        return f"#x{n:x}"

    def gadj(n):
        """Format adjacency index — #xff for boundary, else #xNN."""
        return "#xff" if n == 0xFF else f"#x{n:x}"

    L = []
    L.append(f"    (({actor_aid})")
    L.append(f"      (set! (-> this nav-mesh)")
    L.append(f"        (new 'static 'nav-mesh")
    L.append(f"          :bounds (new 'static 'sphere :x (meters {ox:.4f}) :y (meters {oy:.4f}) :z (meters {oz:.4f}) :w (meters {br:.4f}))")
    L.append(f"          :origin (new 'static 'vector :x (meters {ox:.4f}) :y (meters {oy:.4f}) :z (meters {oz:.4f}) :w 1.0)")
    node_list = mesh.get('nodes', [])
    L.append(f"          :node-count {len(node_list)}")
    L.append(f"          :nodes (new 'static 'inline-array nav-node {len(node_list)}")
    for ncx, ncy, ncz, nrx, nry, nrz, chunk in node_list:
        # Leaf node: type=1, num-tris in lower 16 of left-offset field
        # first-tris: poly indices 0-3, last-tris: poly indices 4-7
        ft = chunk[:4] + [0] * (4 - len(chunk[:4]))
        lt = (chunk[4:8] if len(chunk) > 4 else []) + [0] * (4 - len(chunk[4:8]) if len(chunk) > 4 else 4)
        L.append(f"            (new 'static 'nav-node")
        L.append(f"              :center-x (meters {ncx:.4f}) :center-y (meters {ncy:.4f}) :center-z (meters {ncz:.4f})")
        L.append(f"              :type #x1 :parent-offset #x0")
        L.append(f"              :radius-x (meters {nrx:.4f}) :radius-y (meters {nry:.4f}) :radius-z (meters {nrz:.4f})")
        L.append(f"              :num-tris {len(chunk)}")
        L.append(f"              :first-tris (new 'static 'array uint8 4 {gx(ft[0])} {gx(ft[1])} {gx(ft[2])} {gx(ft[3])})")
        L.append(f"              :last-tris  (new 'static 'array uint8 4 {gx(lt[0])} {gx(lt[1])} {gx(lt[2])} {gx(lt[3])})")
        L.append(f"            )")
    L.append(f"          )")
    L.append(f"          :vertex-count {V}")
    L.append(f"          :vertex (new 'static 'inline-array nav-vertex {V}")
    for vx, vy, vz in mesh['verts_rel']:
        L.append(f"            (new 'static 'nav-vertex :x (meters {vx:.4f}) :y (meters {vy:.4f}) :z (meters {vz:.4f}) :w 1.0)")
    L.append(f"          )")
    L.append(f"          :poly-count {N}")
    L.append(f"          :poly (new 'static 'inline-array nav-poly {N}")
    for i, ((v0,v1,v2),(a0,a1,a2)) in enumerate(zip(mesh['polys'], mesh['adj'])):
        L.append(f"            (new 'static 'nav-poly :id {gx(i)} :vertex (new 'static 'array uint8 3 {gx(v0)} {gx(v1)} {gx(v2)}) :adj-poly (new 'static 'array uint8 3 {gadj(a0)} {gadj(a1)} {gadj(a2)}))")
    L.append(f"          )")
    rc = len(mesh['vec4ubs'])
    L.append(f"          :route (new 'static 'inline-array vector4ub {rc}")
    for b0,b1,b2,b3 in mesh['vec4ubs']:
        L.append(f"            (new 'static 'vector4ub :data (new 'static 'array uint8 4 {gx(b0)} {gx(b1)} {gx(b2)} {gx(b3)}))")
    L.append(f"          )")
    L.append(f"        )")
    L.append(f"      )")
    L.append(f"    )")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# COLLECTION SYSTEM — Level = Collection
# ---------------------------------------------------------------------------
# Each level lives in a top-level Blender collection with og_is_level=True.
# Sub-collections organize objects by category (Geometry, Spawnables, etc.).
# When no level collections exist, the addon falls back to v1.1.0 behaviour
# (scene-wide scan, scene.og_props for settings).

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

def _canonical_actor_objects(scene, objects=None):
    """
    Single source of truth for actor ordering and AID assignment.
    Both collect_actors and _collect_navmesh_actors must use this so
    idx values — and therefore AIDs — are guaranteed to match.
    Sorted by name for full determinism regardless of Blender object order.
    Excludes waypoints (_wp_, _wpb_) and non-EMPTY objects.

    If objects is provided, scans that list instead of scene.objects.
    """
    source = objects if objects is not None else scene.objects
    actors = []
    for o in source:
        if not (o.name.startswith("ACTOR_") and o.type == "EMPTY"):
            continue
        if "_wp_" in o.name or "_wpb_" in o.name:
            continue
        if len(o.name.split("_", 2)) < 3:
            continue
        actors.append(o)
    actors.sort(key=lambda o: o.name)
    return actors


def _collect_navmesh_actors(scene):
    """
    Returns list of (actor_aid, mesh_data) for actors linked to navmeshes.
    actor_aid = base_id + 1-based index in canonical actor order,
    matching exactly what collect_actors and the JSONC builder assign.
    """
    base_id = int(_get_level_prop(scene, "og_base_id", 10000))
    level_objs = _level_objects(scene)
    ordered = _canonical_actor_objects(scene, objects=level_objs)

    result = []
    for idx, o in enumerate(ordered):
        nm_name = o.get("og_navmesh_link", "")
        if not nm_name:
            continue
        nm_obj = scene.objects.get(nm_name)
        if not nm_obj or nm_obj.type != "MESH":
            continue

        actor_aid = base_id + idx + 1  # base_id+1 = first actor AID
        log(f"[navmesh] {o.name} idx={idx} aid={actor_aid} -> {nm_name}")

        nm_obj.data.calc_loop_triangles()
        mat = nm_obj.matrix_world
        tris = []
        for tri in nm_obj.data.loop_triangles:
            pts = []
            for vi in tri.vertices:
                co = mat @ nm_obj.data.vertices[vi].co
                # Blender Y-up -> game coords: game_x=bl_x, game_y=bl_z, game_z=-bl_y
                pts.append((round(co.x, 4), round(co.z, 4), round(-co.y, 4)))
            tris.append(tuple(pts))

        mesh_data = _navmesh_compute(tris)
        if mesh_data:
            result.append((actor_aid, mesh_data))
            log(f"[navmesh]   {mesh_data['poly_count']} polys OK")
        else:
            log(f"[navmesh]   WARNING: navmesh compute returned nothing for {o.name}")

    return result


def _camera_aabb_to_planes(b_min, b_max):
    """Convert an AABB in game-space meters to 6 half-space plane equations.

    Each plane is [nx, ny, nz, d_meters] where a point P (meters) is INSIDE
    the volume when dot(P, normal) <= d for ALL planes.

    The C++ loader (vector_vol_from_json) multiplies the w component by 4096,
    so we provide values in meters here.
    """
    mn = tuple(min(b_min[i], b_max[i]) for i in range(3))
    mx = tuple(max(b_min[i], b_max[i]) for i in range(3))
    return [
        [ 1.0,  0.0,  0.0,  mx[0]],  # +X wall
        [-1.0,  0.0,  0.0, -mn[0]],  # -X wall
        [ 0.0,  1.0,  0.0,  mx[1]],  # +Y ceiling
        [ 0.0, -1.0,  0.0, -mn[1]],  # -Y floor
        [ 0.0,  0.0,  1.0,  mx[2]],  # +Z back
        [ 0.0,  0.0, -1.0, -mn[2]],  # -Z front
    ]


def _vol_aabb(vol_obj):
    """Compute the game-space AABB of a volume mesh.
    Returns (xs_min, xs_max, ys_min, ys_max, zs_min, zs_max, cx, cy, cz, radius).
    Used by all trigger build passes (camera, checkpoint, aggro).
    """
    corners = [vol_obj.matrix_world @ v.co for v in vol_obj.data.vertices]
    gc = [(c.x, c.z, -c.y) for c in corners]
    xs = [c[0] for c in gc]; ys = [c[1] for c in gc]; zs = [c[2] for c in gc]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    cx = round((xmin + xmax) / 2, 4)
    cy = round((ymin + ymax) / 2, 4)
    cz = round((zmin + zmax) / 2, 4)
    rad = round(max(xmax - xmin, ymax - ymin, zmax - zmin) / 2 + 5.0, 2)
    return (round(xmin, 4), round(xmax, 4),
            round(ymin, 4), round(ymax, 4),
            round(zmin, 4), round(zmax, 4),
            cx, cy, cz, rad)


def collect_aggro_triggers(scene):
    """Build aggro-trigger actor list from VOL_ meshes whose og_vol_links
    contain at least one nav-enemy ACTOR_ target.

    One actor is emitted per (volume, enemy_link) pair. The actor's lump holds
    the target enemy's name (string), an event-id integer (0=cue-chase,
    1=cue-patrol, 2=go-wait-for-cue), and 6 AABB bound-* floats.

    The target-name lump must match the *emitted name lump* on the target
    actor (which is f"{etype}-{uid}", e.g. "babak-1"), NOT the Blender object
    name (e.g. "ACTOR_babak_1"). The engine's entity-by-name walks all loaded
    actors and matches the 'name lump string verbatim — this lookup is what
    process-by-ename uses at runtime.

    At runtime the aggro-trigger polls AABB; on rising edge it calls
    (process-by-ename target-name) and sends the appropriate event symbol.
    Implemented entirely with res-lumps — no engine patches required.

    Engine refs:
      nav-enemy.gc:142 — 'cue-chase, 'cue-patrol, 'go-wait-for-cue handlers
      entity.gc:92    — entity-by-name lookup
      entity.gc:167   — process-by-ename helper
    """
    out = []
    counter = 0
    for vol in _level_objects(scene):
        if vol.type != "MESH" or not vol.name.startswith("VOL_"):
            continue
        for entry in _vol_links(vol):
            if _classify_target(entry.target_name) != "enemy":
                continue
            target_obj = scene.objects.get(entry.target_name)
            if not target_obj:
                log(f"  [WARNING] aggro-trigger {vol.name}: target '{entry.target_name}' not in scene — skipped")
                continue
            # Convert Blender object name to the actor's emitted 'name lump.
            # ACTOR_<etype>_<uid> -> <etype>-<uid>  (matches collect_actors line ~3170)
            parts = entry.target_name.split("_", 2)
            if len(parts) < 3:
                log(f"  [WARNING] aggro-trigger {vol.name}: malformed target name '{entry.target_name}' — skipped")
                continue
            target_lump_name = f"{parts[1]}-{parts[2]}"
            xmin, xmax, ymin, ymax, zmin, zmax, cx, cy, cz, rad = _vol_aabb(vol)
            event_id = _aggro_event_id(entry.behaviour)
            uid = counter
            counter += 1
            out.append({
                "trans":     [cx, cy, cz],
                "etype":     "aggro-trigger",
                "game_task": "(game-task none)",
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [cx, cy, cz, rad],
                "lump": {
                    "name":        f"aggrotrig-{uid}",
                    "target-name": target_lump_name,
                    "event-id":    ["uint32", event_id],
                    "bound-xmin":  ["meters", xmin],
                    "bound-xmax":  ["meters", xmax],
                    "bound-ymin":  ["meters", ymin],
                    "bound-ymax":  ["meters", ymax],
                    "bound-zmin":  ["meters", zmin],
                    "bound-zmax":  ["meters", zmax],
                },
            })
            log(f"  [aggro-trigger] {vol.name} → {entry.target_name} (lump: {target_lump_name}, {entry.behaviour})")
    return out


def collect_cameras(scene):
    """Build camera actor list from CAMERA_ camera objects.

    Returns (camera_actors, trigger_actors) where both are JSONC actor dicts.
    camera_actors  -- camera-marker entities (hold position/rotation)
    trigger_actors -- camera-trigger entities (AABB polling, birth on level load)

    A volume can hold multiple links. We iterate every VOL_ mesh's links and
    emit one camera-trigger actor per (volume, camera_link) pair.
    """
    level_objs = _level_objects(scene)

    cam_objects = sorted(
        [o for o in level_objs
         if o.name.startswith("CAMERA_") and o.type == "CAMERA"],
        key=lambda o: o.name,
    )

    # Build cam_name -> [vol_obj, ...] from VOL_ meshes' og_vol_links collections.
    # One camera can be linked from multiple volumes (Scenario A from design discussion).
    vols_by_cam = {}
    for o in level_objs:
        if o.type == "MESH" and o.name.startswith("VOL_"):
            for entry in _vol_links(o):
                if _classify_target(entry.target_name) == "camera":
                    vols_by_cam.setdefault(entry.target_name, []).append(o)

    camera_actors  = []
    trigger_actors = []

    for cam_obj in cam_objects:
        cam_name = cam_obj.name

        loc = cam_obj.matrix_world.translation
        gx = round(loc.x, 4)
        gy = round(loc.z, 4)
        gz = round(-loc.y, 4)

        # Blender -> game camera quaternion.
        #
        # 1. Extract camera look direction: -local_Z of matrix_world (BL cam looks along -Z)
        # 2. Remap to game space: (bl.x, bl.z, -bl.y)  -- same as position remap
        # 3. Build canonical rotation via forward-down->inv-matrix style (world-down roll ref)
        # 4. Conjugate the result (negate xyz) -- the game's quaternion->matrix reads
        #    the inverse convention from what standard math produces.
        #
        # All four steps confirmed empirically via nREPL inv-camera-rot readback.
        m3 = cam_obj.matrix_world.to_3x3()
        bl_look = -m3.col[2]   # BL camera looks along local -Z (world space)
        # Remap to game space: bl(x,y,z) -> game(x,z,-y)
        gl = mathutils.Vector((bl_look.x, bl_look.z, -bl_look.y))
        gl.normalize()
        # Build canonical game rotation: forward=gl, roll from world down (0,-1,0)
        game_down = mathutils.Vector((0.0, -1.0, 0.0))
        right = gl.cross(game_down)
        if right.length < 1e-6:
            right = mathutils.Vector((1.0, 0.0, 0.0))  # degenerate: straight up/down
        right.normalize()
        up = gl.cross(right)
        up.normalize()
        game_mat = mathutils.Matrix([right, up, gl])
        gq = game_mat.to_quaternion()
        # Game's quaternion->matrix uses the conjugate convention (negate xyz).
        # Confirmed empirically: sending (0,-0.7071,0,0.7071) for a BL +X camera
        # produced r2=(-1,0,0) in game. Conjugate fixes it to r2=(+1,0,0).
        qx = round(-gq.x, 6)
        qy = round(-gq.y, 6)
        qz = round(-gq.z, 6)
        qw = round( gq.w, 6)

        cam_mode = cam_obj.get("og_cam_mode",  "fixed")
        interp_t = float(cam_obj.get("og_cam_interp", 1.0))
        fov_deg  = float(cam_obj.get("og_cam_fov",    0.0))

        lump = {"name": cam_name}
        lump["interpTime"] = ["float", round(interp_t, 3)]
        if fov_deg > 0.0:
            lump["fov"] = ["degrees", round(fov_deg, 2)]

        # Look-at target: export "interesting" lump (bypasses quaternion entirely)
        look_at_name = cam_obj.get("og_cam_look_at", "").strip()
        if look_at_name:
            look_obj = scene.objects.get(look_at_name)
            if look_obj:
                lt = look_obj.matrix_world.translation
                lump["interesting"] = ["vector3m", [round(lt.x,4), round(lt.z,4), round(-lt.y,4)]]
                log(f"  [camera] {cam_name} look-at -> {look_at_name} game({lump['interesting'][1]})")
            else:
                log(f"  [camera] WARNING: look-at object '{look_at_name}' not found in scene")
        if cam_mode == "standoff":
            align_name = cam_name + "_ALIGN"
            align_obj  = scene.objects.get(align_name)
            if align_obj:
                al = align_obj.matrix_world.translation
                lump["trans"] = ["vector3m", [round(al.x,4), round(al.z,4), round(-al.y,4)]]
                lump["align"] = ["vector3m", [gx, gy, gz]]
                log(f"  [camera] {cam_name} standoff -- align={align_name}")
            else:
                log(f"  [camera] WARNING: {cam_name} standoff but no {align_name}")
        elif cam_mode == "orbit":
            pivot_name = cam_name + "_PIVOT"
            pivot_obj  = scene.objects.get(pivot_name)
            if pivot_obj:
                pl = pivot_obj.matrix_world.translation
                lump["trans"] = ["vector3m", [gx, gy, gz]]
                lump["pivot"] = ["vector3m", [round(pl.x,4), round(pl.z,4), round(-pl.y,4)]]
                log(f"  [camera] {cam_name} orbit -- pivot={pivot_name}")
            else:
                log(f"  [camera] WARNING: {cam_name} orbit but no {pivot_name}")

        camera_actors.append({
            "trans":     [gx, gy, gz],
            "etype":     "camera-marker",
            "game_task": 0,
            "quat":      [qx, qy, qz, qw],
            "vis_id":    0,
            "bsphere":   [gx, gy, gz, 30.0],
            "lump":      lump,
        })

        vol_list = vols_by_cam.get(cam_name, [])
        if vol_list:
            for vol_obj in vol_list:
                xmin, xmax, ymin, ymax, zmin, zmax, cx, cy, cz, rad = _vol_aabb(vol_obj)
                trigger_actors.append({
                    "trans":     [cx, cy, cz],
                    "etype":     "camera-trigger",
                    "game_task": 0,
                    "quat":      [0, 0, 0, 1],
                    "vis_id":    0,
                    "bsphere":   [cx, cy, cz, rad],
                    "lump": {
                        "name":       f"camtrig-{cam_name.lower()}-{vol_obj.get('og_vol_id', 0)}",
                        "cam-name":   cam_name,
                        "bound-xmin": ["meters", xmin],
                        "bound-xmax": ["meters", xmax],
                        "bound-ymin": ["meters", ymin],
                        "bound-ymax": ["meters", ymax],
                        "bound-zmin": ["meters", zmin],
                        "bound-zmax": ["meters", zmax],
                    },
                })
                log(f"  [camera] {cam_name} + trigger {vol_obj.name}")
        else:
            log(f"  [camera] {cam_name} -- no trigger volume")

    return camera_actors, trigger_actors


def write_gc(name, has_triggers=False, has_checkpoints=False, has_aggro_triggers=False):
    """Write obs.gc: always emits camera-marker type; if has_triggers also
    emits camera-trigger type; if has_checkpoints emits checkpoint-trigger type;
    if has_aggro_triggers emits aggro-trigger type.
    All types birth automatically via entity-actor.birth! — no nREPL needed.
    """
    d = _goal_src() / "levels" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-obs.gc"

    lines = [
        ";;-*-Lisp-*-",
        "(in-package goal)",
        f";; {name}-obs.gc -- auto-generated by OpenGOAL Level Tools",
        "",
        ";; camera-marker: inert entity that holds camera position/rotation.",
        "(deftype camera-marker (process-drawable)",
        "  ()",
        "  (:states camera-marker-idle))",
        "",
        "(defstate camera-marker-idle (camera-marker)",
        "  :code (behavior () (loop (suspend))))",
        "",
        "(defmethod init-from-entity! ((this camera-marker) (arg0 entity-actor))",
        "  (set! (-> this root) (new (quote process) (quote trsqv)))",
        "  (process-drawable-from-entity! this arg0)",
        "  (go camera-marker-idle)",
        "  (none))",
        "",
    ]

    if has_triggers:
        lines += [
            ";; camera-trigger: AABB volume entity that switches the active camera.",
            ";; Reads bounds from meters lumps; reads cam-name string lump.",
            ";; No nREPL call needed -- births automatically on level load.",
            "(deftype camera-trigger (process-drawable)",
            "  ((cam-name    string  :offset-assert 176)",
            "   (cull-radius float   :offset-assert 180)",
            "   (xmin        float   :offset-assert 184)",
            "   (xmax        float   :offset-assert 188)",
            "   (ymin        float   :offset-assert 192)",
            "   (ymax        float   :offset-assert 196)",
            "   (zmin        float   :offset-assert 200)",
            "   (zmax        float   :offset-assert 204)",
            "   (inside      symbol  :offset-assert 208))",
            "  :heap-base #x70",
            "  :size-assert #xd4",
            "  (:states camera-trigger-active))",
            "",
            "(defstate camera-trigger-active (camera-trigger)",
            "  :code",
            "  (behavior ()",
            "    (loop",
            "      (when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))",
            "        (let* ((pos  (-> *target* control trans))",
            "               (dx   (- (-> pos x) (-> self root trans x)))",
            "               (dy   (- (-> pos y) (-> self root trans y)))",
            "               (dz   (- (-> pos z) (-> self root trans z)))",
            "               (cr   (-> self cull-radius))",
            "               (in-vol (and",
            "                 (< (+ (* dx dx) (* dy dy) (* dz dz)) (* cr cr))",
            "                 (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))",
            "                 (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))",
            "                 (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))))",
            "          (cond",
            "            ((and in-vol (not (-> self inside)))",
            "             (set! (-> self inside) #t)",
            "             (format 0 \"[cam-trigger] enter -> ~A~%\" (-> self cam-name))",
            "             (send-event *camera* (quote change-to-entity-by-name) (-> self cam-name)))",
            "            ((and (not in-vol) (-> self inside))",
            "             (set! (-> self inside) #f)",
            "             (format 0 \"[cam-trigger] exit ~A~%\" (-> self cam-name))",
            "             (send-event *camera* (quote clear-entity))))))",
            "      (suspend))))",
            "",
            "(defmethod init-from-entity! ((this camera-trigger) (arg0 entity-actor))",
            "  (set! (-> this root) (new (quote process) (quote trsqv)))",
            "  (process-drawable-from-entity! this arg0)",
            "  (set! (-> this cam-name) (res-lump-struct arg0 (quote cam-name) string))",
            "  (set! (-> this xmin) (res-lump-float arg0 (quote bound-xmin)))",
            "  (set! (-> this xmax) (res-lump-float arg0 (quote bound-xmax)))",
            "  (set! (-> this ymin) (res-lump-float arg0 (quote bound-ymin)))",
            "  (set! (-> this ymax) (res-lump-float arg0 (quote bound-ymax)))",
            "  (set! (-> this zmin) (res-lump-float arg0 (quote bound-zmin)))",
            "  (set! (-> this zmax) (res-lump-float arg0 (quote bound-zmax)))",
            "  (let* ((hx (* 0.5 (- (-> this xmax) (-> this xmin))))",
            "         (hy (* 0.5 (- (-> this ymax) (-> this ymin))))",
            "         (hz (* 0.5 (- (-> this zmax) (-> this zmin)))))",
            "    (set! (-> this cull-radius) (sqrtf (+ (* hx hx) (* hy hy) (* hz hz)))))",
            "  (set! (-> this inside) #f)",
            "  (format 0 \"[cam-trigger] armed: ~A cull-r ~M~%\" (-> this cam-name) (-> this cull-radius))",
            "  (go camera-trigger-active)",
            "  (none))",
            "",
        ]
        log(f"  [write_gc] camera-trigger type embedded")

    if has_checkpoints:
        lines += [
            ";; checkpoint-trigger: sets continue point when Jak enters the volume.",
            ";; After firing it enters a 5-second cooldown then re-arms automatically,",
            ";; so if the player dies and respawns in the same zone it fires again.",
            ";; Two modes: sphere (default) or AABB (has-volume lump = 1).",
            "(deftype checkpoint-trigger (process-drawable)",
            "  ((cp-name     string  :offset-assert 176)",
            "   (cull-radius float   :offset-assert 180)",
            "   (radius      float   :offset-assert 184)",
            "   (use-vol     symbol  :offset-assert 188)",
            "   (was-near    symbol  :offset-assert 192)",
            "   (xmin        float   :offset-assert 196)",
            "   (xmax        float   :offset-assert 200)",
            "   (ymin        float   :offset-assert 204)",
            "   (ymax        float   :offset-assert 208)",
            "   (zmin        float   :offset-assert 212)",
            "   (zmax        float   :offset-assert 216))",
            "  :heap-base #x70",
            "  :size-assert #xdc",
            "  (:states checkpoint-trigger-active checkpoint-trigger-wait-exit))",
            "",
            ";; Wait-for-exit state: fired, now waiting for player to leave the volume.",
            ";; Re-arms the moment they step out — zero overhead while inside, instant",
            ";; re-arm on exit. No timer needed.",
            "(defstate checkpoint-trigger-wait-exit (checkpoint-trigger)",
            "  :code",
            "  (behavior ()",
            "    (loop",
            "      (when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))",
            "        (let* ((pos  (-> *target* control trans))",
            "               (dx   (- (-> pos x) (-> self root trans x)))",
            "               (dy   (- (-> pos y) (-> self root trans y)))",
            "               (dz   (- (-> pos z) (-> self root trans z)))",
            "               (cr   (-> self cull-radius))",
            "               (still-inside (and",
            "                 (< (+ (* dx dx) (* dy dy) (* dz dz)) (* cr cr))",
            "                 (if (-> self use-vol)",
            "                   (and",
            "                     (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))",
            "                     (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))",
            "                     (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))",
            "                   (let ((r (-> self radius)))",
            "                     (< (+ (* dx dx) (* dy dy) (* dz dz)) (* r r)))))))",
            "          (when (not still-inside)",
            "            (format 0 \"[cp-trigger] ~A re-armed~%\" (-> self cp-name))",
            "            (go checkpoint-trigger-active))))",
            "      (suspend))))",
            "",
            "(defstate checkpoint-trigger-active (checkpoint-trigger)",
            "  :code",
            "  (behavior ()",
            "    (loop",
            "      (when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))",
            "        (let* ((pos  (-> *target* control trans))",
            "               (dx   (- (-> pos x) (-> self root trans x)))",
            "               (dy   (- (-> pos y) (-> self root trans y)))",
            "               (dz   (- (-> pos z) (-> self root trans z)))",
            "               (cr   (-> self cull-radius))",
            "               (near (< (+ (* dx dx) (* dy dy) (* dz dz)) (* cr cr)))",
            "               (inside (and near",
            "                 (if (-> self use-vol)",
            "                   (and",
            "                     (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))",
            "                     (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))",
            "                     (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))",
            "                   (let ((r (-> self radius)))",
            "                     (< (+ (* dx dx) (* dy dy) (* dz dz)) (* r r)))))))",
            "          (when (and near (not inside) (not (-> self was-near)))",
            "            (format 0 \"[cp-trigger] ~A sphere-hit AABB-miss~%\" (-> self cp-name)))",
            "          (set! (-> self was-near) near)",
            "          (when inside",
            "            (format 0 \"[cp-trigger] fired -> ~A~%\" (-> self cp-name))",
            "            (set-continue! *game-info* (-> self cp-name))",
            "            (go checkpoint-trigger-wait-exit))))",
            "      (suspend))))",
            "",
            "(defmethod init-from-entity! ((this checkpoint-trigger) (arg0 entity-actor))",
            "  (set! (-> this root) (new (quote process) (quote trsqv)))",
            "  (process-drawable-from-entity! this arg0)",
            "  (set! (-> this cp-name)  (res-lump-struct arg0 (quote continue-name) string))",
            "  (set! (-> this radius)   (res-lump-float  arg0 (quote radius) :default 12288.0))",
            "  (set! (-> this use-vol)  (!= 0 (the int (res-lump-value arg0 (quote has-volume) uint128))))",
            "  (set! (-> this was-near) #f)",
            "  (set! (-> this xmin)     (res-lump-float arg0 (quote bound-xmin)))",
            "  (set! (-> this xmax)     (res-lump-float arg0 (quote bound-xmax)))",
            "  (set! (-> this ymin)     (res-lump-float arg0 (quote bound-ymin)))",
            "  (set! (-> this ymax)     (res-lump-float arg0 (quote bound-ymax)))",
            "  (set! (-> this zmin)     (res-lump-float arg0 (quote bound-zmin)))",
            "  (set! (-> this zmax)     (res-lump-float arg0 (quote bound-zmax)))",
            "  (let* ((hx (* 0.5 (- (-> this xmax) (-> this xmin))))",
            "         (hy (* 0.5 (- (-> this ymax) (-> this ymin))))",
            "         (hz (* 0.5 (- (-> this zmax) (-> this zmin))))",
            "         (r  (-> this radius)))",
            "    (set! (-> this cull-radius)",
            "      (if (-> this use-vol)",
            "        (sqrtf (+ (* hx hx) (* hy hy) (* hz hz)))",
            "        (* r 1.2))))",
            "  (format 0 \"[cp-trigger] armed: ~A~%\" (-> this cp-name))",
            "  (go checkpoint-trigger-active)",
            "  (none))",
            "",
        ]
        log(f"  [write_gc] checkpoint-trigger type embedded")

    if has_aggro_triggers:
        lines += [
            ";; aggro-trigger: AABB volume entity that sends a wakeup event to a target enemy.",
            ";; On rising edge (player enters volume), looks up target enemy by name via",
            ";; (process-by-ename ...) and sends one of three quoted symbols based on event-id:",
            ";;   0 = 'cue-chase        — wake enemy + chase player",
            ";;   1 = 'cue-patrol       — return to patrol",
            ";;   2 = 'go-wait-for-cue  — freeze until next cue",
            ";; Re-fires every time the player re-enters (inside flag clears on exit).",
            ";; Only nav-enemies respond to these events (engine: nav-enemy.gc line 142).",
            "(deftype aggro-trigger (process-drawable)",
            "  ((target-name string  :offset-assert 176)",
            "   (cull-radius float   :offset-assert 180)",
            "   (event-id    int32   :offset-assert 184)",
            "   (xmin        float   :offset-assert 188)",
            "   (xmax        float   :offset-assert 192)",
            "   (ymin        float   :offset-assert 196)",
            "   (ymax        float   :offset-assert 200)",
            "   (zmin        float   :offset-assert 204)",
            "   (zmax        float   :offset-assert 208)",
            "   (inside      symbol  :offset-assert 212))",
            "  :heap-base #x70",
            "  :size-assert #xd8",
            "  (:states aggro-trigger-active))",
            "",
            "(defstate aggro-trigger-active (aggro-trigger)",
            "  :code",
            "  (behavior ()",
            "    (loop",
            "      (when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))",
            "        (let* ((pos  (-> *target* control trans))",
            "               (dx   (- (-> pos x) (-> self root trans x)))",
            "               (dy   (- (-> pos y) (-> self root trans y)))",
            "               (dz   (- (-> pos z) (-> self root trans z)))",
            "               (cr   (-> self cull-radius))",
            "               (in-vol (and",
            "                 (< (+ (* dx dx) (* dy dy) (* dz dz)) (* cr cr))",
            "                 (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))",
            "                 (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))",
            "                 (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))))",
            "          (cond",
            "            ((and in-vol (not (-> self inside)))",
            "             (set! (-> self inside) #t)",
            "             (format 0 \"[aggro-trigger] enter -> ~A~%\" (-> self target-name))",
            "             (let ((proc (process-by-ename (-> self target-name))))",
            "               (when proc",
            "                 (cond",
            "                   ((zero? (-> self event-id))",
            "                    (send-event proc 'cue-chase))",
            "                   ((= (-> self event-id) 1)",
            "                    (send-event proc 'cue-patrol))",
            "                   ((= (-> self event-id) 2)",
            "                    (send-event proc 'go-wait-for-cue))))))",
            "            ((and (not in-vol) (-> self inside))",
            "             (set! (-> self inside) #f)",
            "             (format 0 \"[aggro-trigger] exit ~A~%\" (-> self target-name))))))",
            "      (suspend))))",
            "",
            "(defmethod init-from-entity! ((this aggro-trigger) (arg0 entity-actor))",
            "  (set! (-> this root) (new (quote process) (quote trsqv)))",
            "  (process-drawable-from-entity! this arg0)",
            "  (set! (-> this target-name) (res-lump-struct arg0 (quote target-name) string))",
            "  (set! (-> this event-id)    (the int (res-lump-value arg0 (quote event-id) uint128)))",
            "  (set! (-> this xmin)        (res-lump-float arg0 (quote bound-xmin)))",
            "  (set! (-> this xmax)        (res-lump-float arg0 (quote bound-xmax)))",
            "  (set! (-> this ymin)        (res-lump-float arg0 (quote bound-ymin)))",
            "  (set! (-> this ymax)        (res-lump-float arg0 (quote bound-ymax)))",
            "  (set! (-> this zmin)        (res-lump-float arg0 (quote bound-zmin)))",
            "  (set! (-> this zmax)        (res-lump-float arg0 (quote bound-zmax)))",
            "  (set! (-> this inside)      #f)",
            "  (let* ((hx (* 0.5 (- (-> this xmax) (-> this xmin))))",
            "         (hy (* 0.5 (- (-> this ymax) (-> this ymin))))",
            "         (hz (* 0.5 (- (-> this zmax) (-> this zmin)))))",
            "    (set! (-> this cull-radius) (sqrtf (+ (* hx hx) (* hy hy) (* hz hz)))))",
            "  (format 0 \"[aggro-trigger] armed: ~A cull-r ~M~%\" (-> this target-name) (-> this cull-radius))",
            "  (go aggro-trigger-active)",
            "  (none))",
            "",
        ]
        log(f"  [write_gc] aggro-trigger type embedded")

    new_text = "\n".join(lines)
    if p.exists() and p.read_text() == new_text:
        log(f"Skipped {p} (unchanged)")
    else:
        p.write_text(new_text)
        log(f"Wrote {p}")



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
def _levels_dir(): return _data() / "custom_assets" / "jak1" / "levels"
def _goal_src():   return _data() / "goal_src" / "jak1"
def _level_info(): return _goal_src() / "engine" / "level" / "level-info.gc"
def _game_gp():    return _goal_src() / "game.gp"
def _ldir(name):   return _levels_dir() / name
def _entity_gc():  return _goal_src() / "engine" / "entity" / "entity.gc" 

def _lname(ctx):
    col = _active_level_col(ctx.scene)
    if col is not None:
        return str(col.get("og_level_name", "")).strip().lower().replace(" ", "-")
    return ctx.scene.og_props.level_name.strip().lower().replace(" ","-")
def _nick(n):      return n.replace("-","")[:3].lower()
def _iso(n):       return n.replace("-","").upper()[:8]
def log(m):        print(f"[OpenGOAL] {m}")


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

def collect_spawns(scene):
    """Collect SPAWN_ empties into continue-point data dicts.

    Each dict contains:
      name       — uid string (e.g. "start", "spawn1", or custom SPAWN_<name>)
      x/y/z      — game-space position (metres, Blender→game remap applied)
      qx/qy/qz/qw — game-space facing quaternion from the empty's rotation
      cam_x/cam_y/cam_z — camera-trans position (from linked SPAWN_<uid>_CAM empty,
                          or defaults to spawn pos + 4m up)
      cam_rot    — camera 3x3 row-major matrix as flat list of 9 floats
                   (from linked SPAWN_<uid>_CAM empty, or identity)
      is_checkpoint — True if this is a CHECKPOINT_ empty (auto-assigned mid-level)
    """
    # R_remap: Blender(x,y,z) → game(x,z,-y), stored as a 3×3 row matrix.
    # Used to conjugate Blender rotation matrices into game space:
    #   game_rot = R_remap @ bl_rot @ R_remap^T
    # Verified: identity Blender empty → identity game quat (x:0 y:0 z:0 w:1).
    R_remap = mathutils.Matrix(((1,0,0),(0,0,1),(0,-1,0)))

    out = []
    for o in sorted(_level_objects(scene), key=lambda o: o.name):
        # BUG FIX: _CAM anchor empties share the SPAWN_/CHECKPOINT_ prefix.
        # Skip them here — they are not spawns/checkpoints themselves.
        if o.name.endswith("_CAM"):
            continue

        is_spawn      = o.name.startswith("SPAWN_")      and o.type == "EMPTY"
        is_checkpoint = o.name.startswith("CHECKPOINT_") and o.type == "EMPTY"
        if not (is_spawn or is_checkpoint):
            continue

        if is_spawn:
            uid = o.name[6:] or "start"
        else:
            uid = o.name[11:] or "cp0"

        l = o.location
        gx = round(l.x,  4)
        gy = round(l.z,  4)
        gz = round(-l.y, 4)

        # ── Facing quaternion ────────────────────────────────────────────────
        # Correct remap: game_rot = R_remap @ bl_rot @ R_remap^T
        # This ensures an unrotated Blender empty produces identity game quat (w=1).
        # The engine reads quaternions as the inverse, so we negate x/y/z (conjugate).
        m3      = o.matrix_world.to_3x3()
        game_m3 = R_remap @ m3 @ R_remap.transposed()
        gq      = game_m3.to_quaternion()
        qx   = round(-gq.x, 6)
        qy   = round(-gq.y, 6)
        qz   = round(-gq.z, 6)
        qw   = round( gq.w, 6)

        # ── Camera empty (optional) ──────────────────────────────────────────
        # User can place a SPAWN_<uid>_CAM or CHECKPOINT_<uid>_CAM empty to
        # set the camera position/orientation at respawn.
        # If absent, we default to spawn pos + 4m up, identity rotation.
        cam_suffix = "_CAM"
        cam_name   = o.name + cam_suffix
        cam_obj    = scene.objects.get(cam_name)

        if cam_obj and cam_obj.type == "EMPTY":
            cl = cam_obj.location
            cam_x = round(cl.x,  4)
            cam_y = round(cl.z,  4)
            cam_z = round(-cl.y, 4)
            # Build camera rotation matrix (same conjugate formula as camera system)
            cm3      = cam_obj.matrix_world.to_3x3()
            bl_look  = -cm3.col[2]                            # camera looks along -local_Z
            gl = mathutils.Vector((bl_look.x, bl_look.z, -bl_look.y))
            gl.normalize()
            game_down = mathutils.Vector((0.0, -1.0, 0.0))
            cr = gl.cross(game_down)
            if cr.length < 1e-6:
                cr = mathutils.Vector((1.0, 0.0, 0.0))
            cr.normalize()
            cu = gl.cross(cr)
            cu.normalize()
            # camera-rot is a 3x3 row-major matrix stored as 9 floats
            cam_rot = [
                round(cr.x, 6), round(cr.y, 6), round(cr.z, 6),
                round(cu.x, 6), round(cu.y, 6), round(cu.z, 6),
                round(gl.x, 6), round(gl.y, 6), round(gl.z, 6),
            ]
        else:
            # Default: camera sits 4m above spawn, looks forward (identity-ish)
            cam_x, cam_y, cam_z = gx, gy + 4.0, gz
            cam_rot = [1.0, 0.0, 0.0,  0.0, 1.0, 0.0,  0.0, 0.0, 1.0]

        out.append({
            "name":          uid,
            "x": gx, "y": gy, "z": gz,
            "qx": qx, "qy": qy, "qz": qz, "qw": qw,
            "cam_x": cam_x, "cam_y": cam_y, "cam_z": cam_z,
            "cam_rot":       cam_rot,
            "is_checkpoint": is_checkpoint,
        })
    return out

def collect_actors(scene):
    """Build actor list from ACTOR_ empties.

    Nav-unsafe enemies (move-to-ground=True, hover-if-no-ground=False) will
    crash the game when they try to resolve a navmesh and find a null pointer.
    Workaround: inject a 'nav-mesh-sphere' res-lump tag on each such actor.
    This tells the nav-control initialiser to use *default-nav-mesh* (a tiny
    stub mesh in navigate.gc) instead of dereferencing null.  The enemy will
    stand, idle, and notice Jak but won't properly pathfind — that requires a
    real navmesh (future work).
    """
    out = []
    level_objs = _level_objects(scene)
    for o in _canonical_actor_objects(scene, objects=level_objs):
        p = o.name.split("_", 2)
        etype, uid = p[1], p[2]
        l = o.location
        gx, gy, gz = round(l.x, 4), round(l.z, 4), round(-l.y, 4)

        lump = {"name": f"{etype}-{uid}"}

        if etype == "fuel-cell":
            lump["eco-info"] = ["cell-info", "(game-task none)"]
            # skip-jump-anim: fact-options bit 2 (value 4)
            if bool(o.get("og_cell_skip_jump", False)):
                lump["options"] = ["uint32", 4]
                log(f"  [fuel-cell] {o.name}  skip-jump-anim=true")
        elif etype == "buzzer":
            lump["eco-info"] = ["buzzer-info", "(game-task none)", 1]
        elif etype == "crate":
            ct = o.get("og_crate_type", "steel")
            lump["crate-type"] = f"'{ct}"
            lump["eco-info"] = ["eco-info", "(pickup-type money)", 3]
        elif etype == "money":
            lump["eco-info"] = ["eco-info", "(pickup-type money)", 1]

        einfo = ENTITY_DEFS.get(etype, {})

        # Collect waypoints for this actor (named ACTOR_<etype>_<uid>_wp_00 etc.)
        wp_prefix = o.name + "_wp_"
        wp_objects = sorted(
            [sc_obj for sc_obj in bpy.data.objects
             if sc_obj.name.startswith(wp_prefix) and sc_obj.type == "EMPTY"],
            key=lambda sc_obj: sc_obj.name
        )
        path_pts = []
        for wp in wp_objects:
            wl = wp.location
            path_pts.append([round(wl.x, 4), round(wl.z, 4), round(-wl.y, 4), 1.0])

        # ── Nav-enemy workaround (nav_safe=False) ────────────────────────────
        # These extend nav-enemy. Without a real navmesh they idle forever.
        # Inject nav-mesh-sphere so the engine doesn't dereference null.
        # entity.gc is also patched separately with a real navmesh if linked.
        if etype in NAV_UNSAFE_TYPES:
            nav_r = float(o.get("og_nav_radius", 6.0))
            if path_pts:
                first = path_pts[0]
                lump["nav-mesh-sphere"] = ["vector4m", [first[0], first[1], first[2], nav_r]]
                log(f"  [nav+path] {o.name}  {len(wp_objects)} waypoints  sphere r={nav_r}m")
            else:
                lump["nav-mesh-sphere"] = ["vector4m", [gx, gy, gz, nav_r]]
                log(f"  [nav-workaround] {o.name}  sphere r={nav_r}m  (no waypoints - will idle)")

        # ── Path lump (needs_path=True) ───────────────────────────────────────
        # process-drawable enemies that error without a path lump.
        # Also used by nav-enemies that patrol (snow-bunny, muse etc.).
        # Waypoints tagged _wp_00, _wp_01 ... drive this lump.
        # For needs_path enemies with no waypoints we log a warning — the level
        # will likely crash or error at runtime without at least 1 waypoint.
        # Platforms handle their own path lump below — skip them here to avoid double-emit
        if (einfo.get("needs_path") or (etype in NAV_UNSAFE_TYPES and path_pts)) and einfo.get("cat") != "Platforms":
            if path_pts:
                lump["path"] = ["vector4m"] + path_pts
                log(f"  [path] {o.name}  {len(path_pts)} points")
            elif einfo.get("needs_path"):
                log(f"  [WARNING] {o.name} needs a path but has no waypoints — will crash/error at runtime!")

        # ── Second path lump (needs_pathb=True — swamp-bat only) ─────────────
        # swamp-bat reads 'pathb' for its second patrol route for bat slaves.
        # Tag secondary waypoints as ACTOR_swamp-bat_<uid>_wpb_00 etc.
        if einfo.get("needs_pathb"):
            wpb_prefix = o.name + "_wpb_"
            wpb_objects = sorted(
                [sc_obj for sc_obj in bpy.data.objects
                 if sc_obj.name.startswith(wpb_prefix) and sc_obj.type == "EMPTY"],
                key=lambda sc_obj: sc_obj.name
            )
            pathb_pts = []
            for wp in wpb_objects:
                wl = wp.location
                pathb_pts.append([round(wl.x, 4), round(wl.z, 4), round(-wl.y, 4), 1.0])
            if pathb_pts:
                lump["pathb"] = ["vector4m"] + pathb_pts
                log(f"  [pathb] {o.name}  {len(pathb_pts)} points")
            else:
                log(f"  [WARNING] {o.name} (swamp-bat) needs 'pathb' waypoints (_wpb_00, _wpb_01 ...) — will error at runtime!")

        # ── Platform: sync lump ───────────────────────────────────────────────
        # plat / plat-eco / side-to-side-plat use a 'sync' res lump to control
        # path timing.  Format: [period_s, phase, ease_out, ease_in]
        # Only emitted when the platform has waypoints — without waypoints the
        # engine ignores sync and the platform spawns idle.
        if einfo.get("needs_sync"):
            period   = float(o.get("og_sync_period",   4.0))
            phase    = float(o.get("og_sync_phase",    0.0))
            ease_out = float(o.get("og_sync_ease_out", 0.15))
            ease_in  = float(o.get("og_sync_ease_in",  0.15))
            if path_pts:
                lump["sync"] = ["float", period, phase, ease_out, ease_in]
                wrap = bool(o.get("og_sync_wrap", False))
                if wrap:
                    # fact-options wrap-phase: bit 3 of the options uint64
                    # GOAL: (defenum fact-options :bitfield #t  (wrap-phase 3))
                    # value = 1 << 3 = 8
                    # Read via: (res-lump-value ent 'options fact-options)
                    lump["options"] = ["uint32", 8]
                log(f"  [sync] {o.name}  period={period}s  phase={phase}  ease={ease_out}/{ease_in}  wrap={wrap}")
            else:
                log(f"  [sync-platform] {o.name}  no waypoints — will spawn idle (add ≥2 waypoints to make it move)")

        # ── Platform: path lump (plat-button) ────────────────────────────────
        # plat-button follows a path when pressed. Requires ≥2 waypoints.
        # Uses needs_path flag and is a Platform, distinguishing from enemy paths.
        if einfo.get("needs_path") and einfo.get("cat") == "Platforms":
            if path_pts:
                lump["path"] = ["vector4m"] + path_pts
                log(f"  [plat-path] {o.name}  {len(path_pts)} points")
            else:
                log(f"  [WARNING] {o.name} (plat-button) needs ≥2 waypoints or it will not move!")

        # ── Platform: sync path (plat / plat-eco) ────────────────────────────
        # When a sync platform has waypoints, also emit the path lump so the
        # engine can evaluate the curve.
        if einfo.get("needs_sync") and path_pts and "path" not in lump:
            lump["path"] = ["vector4m"] + path_pts
            log(f"  [sync-path] {o.name}  {len(path_pts)} points")

        # ── Platform: notice-dist (plat-eco) ─────────────────────────────────
        # Controls how close Jak must be before the platform notices blue eco.
        # Default -1.0 = always active (never needs eco to activate).
        if einfo.get("needs_notice_dist"):
            notice = float(o.get("og_notice_dist", -1.0))
            lump["notice-dist"] = ["meters", notice]
            log(f"  [notice-dist] {o.name}  {notice}m  ({'always active' if notice < 0 else 'eco required'})")

        # ── Dark-crystal: mode lump (underwater variant) ─────────────────────
        if etype == "dark-crystal":
            if bool(o.get("og_crystal_underwater", False)):
                lump["mode"] = ["int32", 1]
                log(f"  [dark-crystal] {o.name}  mode=1 (underwater)")

        # ── Plat-flip: sync-percent (phase offset) ────────────────────────────
        if etype == "plat-flip":
            sync_pct = float(o.get("og_flip_sync_pct", 0.0))
            if sync_pct != 0.0:
                lump["sync-percent"] = ["float", sync_pct]
                log(f"  [plat-flip sync-percent] {o.name}  {sync_pct:.2f}")

        # ── Eco-door: flags lump ─────────────────────────────────────────────
        # eco-door reads a 'flags lump (eco-door-flags bitfield).
        # auto-close = bit 0, one-way = bit 1.
        if etype == "eco-door":
            auto_close = bool(o.get("og_door_auto_close", False))
            one_way    = bool(o.get("og_door_one_way",    False))
            flags = (1 if auto_close else 0) | (2 if one_way else 0)
            if flags:
                lump["flags"] = ["uint32", flags]
                log(f"  [eco-door flags] {o.name}  auto-close={auto_close}  one-way={one_way}")

        # ── Water-vol: water-height multi-field lump ──────────────────────────
        # water-vol reads a 5-field 'water-height lump:
        # [surface_m, wade_m, swim_m, flags, bottom_m]
        if etype == "water-vol":
            surface = float(o.get("og_water_surface", 0.0))
            wade    = float(o.get("og_water_wade",   -0.5))
            swim    = float(o.get("og_water_swim",   -1.0))
            bottom  = float(o.get("og_water_bottom", -5.0))
            lump["water-height"] = ["water-height", surface, wade, swim, "(water-flags)", bottom]
            log(f"  [water-vol] {o.name}  surface={surface}m  wade={wade}m  swim={swim}m  bottom={bottom}m")

        # ── Launcherdoor: continue-name lump ─────────────────────────────────
        # launcherdoor writes a continue-name string lump to set the active
        # checkpoint when Jak passes through the door.
        if etype == "launcherdoor":
            cp_name = str(o.get("og_continue_name", "")).strip()
            if cp_name:
                lump["continue-name"] = cp_name
                log(f"  [launcherdoor] {o.name}  continue-name='{cp_name}'")
            else:
                log(f"  [launcherdoor] {o.name}  no continue-name set")

        # ── Launcher: spring-height and alt-vector (destination) ─────────────
        # launcher and springbox both read spring-height for launch force.
        # launcher also reads alt-vector: xyz = destination, w = fly_time_frames.
        if _actor_is_launcher(etype):
            height = float(o.get("og_spring_height", -1.0))
            if height >= 0:
                lump["spring-height"] = ["meters", height]
                log(f"  [spring-height] {o.name}  {height}m")

            if etype == "launcher":
                dest_name = o.get("og_launcher_dest", "")
                dest_obj  = bpy.data.objects.get(dest_name) if dest_name else None
                fly_time  = float(o.get("og_launcher_fly_time", -1.0))
                if dest_obj:
                    dl = dest_obj.location
                    # Convert Blender coords → game coords (X, Z, -Y)
                    dx = round(dl.x * 4096, 2)
                    dy = round(dl.z * 4096, 2)
                    dz = round(-dl.y * 4096, 2)
                    # w = fly time in frames (seconds × 300); default 150 if not set
                    fw = round((fly_time if fly_time >= 0 else 0.5) * 300, 2)
                    lump["alt-vector"] = ["vector", [dx, dy, dz, fw]]
                    log(f"  [alt-vector] {o.name}  dest={dest_name}  fly={fw:.0f}frames")

        # ── Spawner: num-lurkers ──────────────────────────────────────────────
        # swamp-bat, yeti, villa-starfish, swamp-rat-nest read num-lurkers to
        # control how many child entities they spawn.
        if _actor_is_spawner(etype):
            count = int(o.get("og_num_lurkers", -1))
            if count >= 0:
                lump["num-lurkers"] = ["int32", count]
                log(f"  [num-lurkers] {o.name}  {count}")

        # ── Enemy: idle-distance ──────────────────────────────────────────────
        # Per-instance activation range. The engine reads this in
        # fact-info-enemy:new (engine fact-h.gc line 191) — when the player is
        # farther than idle-distance from the enemy, the enemy stays in its
        # idle state and won't notice the player. Engine default is 80m.
        # Lower = enemy stays "asleep" longer; higher = enemy wakes up sooner.
        # Applies to all enemies and bosses (they all inherit fact-info-enemy).
        if _actor_is_enemy(etype):
            idle_d = float(o.get("og_idle_distance", 80.0))
            lump["idle-distance"] = ["meters", idle_d]
            log(f"  [idle-distance] {o.name}  {idle_d}m")

                # Bsphere radius controls vis-culling distance.  nav-enemy run-logic?
        # only processes AI/collision events when draw-status was-drawn is set,
        # which requires the bsphere to pass the renderer's cull test.
        # Custom levels lack a proper BSP vis system, so enemies need a large
        # bsphere (120m) to guarantee was-drawn is always true in a play area.
        # Pickups / static props can stay small.
        info     = ENTITY_DEFS.get(etype, {})
        is_enemy = info.get("cat") in ("Enemies", "Bosses")
        bsph_r   = 10.0  # Rockpool uses 10m for all entities; 120m caused merc renderer crashes

        # Add vis-dist for enemies so they stay active at reasonable range.
        # og_vis_dist custom prop overrides; default 200m.
        if is_enemy and "vis-dist" not in lump:
            vis = float(o.get("og_vis_dist", 200.0))
            lump["vis-dist"] = ["meters", vis]

        # ── Plat-flip: delay lump ─────────────────────────────────────────────
        # plat-flip reads 'delay as two floats: [before_down, before_up] in seconds.
        if etype == "plat-flip":
            d_down = float(o.get("og_flip_delay_down", 2.0))
            d_up   = float(o.get("og_flip_delay_up",   2.0))
            lump["delay"] = ["float", d_down, d_up]
            log(f"  [plat-flip delay] {o.name}  down={d_down}s  up={d_up}s")

        # ── Orb-cache: orb-cache-count lump ──────────────────────────────────
        if etype == "orb-cache-top":
            count = int(o.get("og_orb_count", 20))
            lump["orb-cache-count"] = ["int32", count]
            log(f"  [orb-cache] {o.name}  count={count}")

        # ── Whirlpool: speed lump ────────────────────────────────────────────
        # whirlpool reads 'speed as two floats: [base, variation] in internal units.
        if etype == "whirlpool":
            speed = float(o.get("og_whirl_speed", 0.3))
            var   = float(o.get("og_whirl_var",   0.1))
            lump["speed"] = ["float", speed, var]
            log(f"  [whirlpool speed] {o.name}  base={speed}  var={var}")

        # ── Ropebridge: art-name lump ─────────────────────────────────────────
        if etype == "ropebridge":
            variant = str(o.get("og_bridge_variant", "ropebridge-32"))
            lump["art-name"] = ["symbol", variant]
            log(f"  [ropebridge] {o.name}  art-name={variant}")

        # ── Orbit-plat: scale + timeout lumps ────────────────────────────────
        if etype == "orbit-plat":
            scale   = float(o.get("og_orbit_scale",   1.0))
            timeout = float(o.get("og_orbit_timeout", 10.0))
            if scale != 1.0:
                lump["scale"] = ["float", scale]
            if timeout != 10.0:
                lump["timeout"] = ["float", timeout]
            log(f"  [orbit-plat] {o.name}  scale={scale}  timeout={timeout}s")

        # ── Square-platform: distance lump (down, up in raw units) ───────────
        if etype == "square-platform":
            down_m = float(o.get("og_sq_down", -2.0))
            up_m   = float(o.get("og_sq_up",    4.0))
            # convert meters to internal units (×4096)
            lump["distance"] = ["float", down_m * 4096, up_m * 4096]
            log(f"  [square-platform] {o.name}  down={down_m}m  up={up_m}m")

        # ── Caveflamepots: shove + cycle-speed lumps ─────────────────────────
        if etype == "caveflamepots":
            shove  = float(o.get("og_flame_shove",  2.0))
            period = float(o.get("og_flame_period", 4.0))
            phase  = float(o.get("og_flame_phase",  0.0))
            pause  = float(o.get("og_flame_pause",  2.0))
            lump["shove"]       = ["meters", shove]
            lump["cycle-speed"] = ["float", period, phase, pause]
            log(f"  [caveflamepots] {o.name}  shove={shove}m  period={period}s  phase={phase}  pause={pause}s")

        # ── Shover: shove force + rotoffset ──────────────────────────────────
        if etype == "shover":
            shove = float(o.get("og_shover_force", 3.0))
            rot   = float(o.get("og_shover_rot",   0.0))
            lump["shove"] = ["meters", shove]
            if rot != 0.0:
                lump["rotoffset"] = ["degrees", rot]
            log(f"  [shover] {o.name}  shove={shove}m  rot={rot}°")

        # ── Lavaballoon / darkecobarrel: speed lump ──────────────────────────
        if etype in ("lavaballoon", "darkecobarrel"):
            default_speed = 3.0 if etype == "lavaballoon" else 15.0
            speed = float(o.get("og_move_speed", default_speed))
            lump["speed"] = ["meters", speed]
            log(f"  [{etype}] {o.name}  speed={speed}m/s")

        # ── Windturbine: particle-select lump ────────────────────────────────
        if etype == "windturbine":
            if bool(o.get("og_turbine_particles", False)):
                lump["particle-select"] = ["uint32", 1]
                log(f"  [windturbine] {o.name}  particles=on")

        # ── Cave elevator: mode + rotoffset ──────────────────────────────────
        if etype == "caveelevator":
            mode = int(o.get("og_elevator_mode", 0))
            rot  = float(o.get("og_elevator_rot", 0.0))
            if mode != 0:
                lump["mode"] = ["uint32", mode]
            if rot != 0.0:
                lump["rotoffset"] = ["degrees", rot]
            log(f"  [caveelevator] {o.name}  mode={mode}  rot={rot}°")

        # ── Mis-bone-bridge: animation-select ────────────────────────────────
        if etype == "mis-bone-bridge":
            anim = int(o.get("og_bone_bridge_anim", 0))
            if anim != 0:
                lump["animation-select"] = ["uint32", anim]
            log(f"  [mis-bone-bridge] {o.name}  animation-select={anim}")

        # ── Breakaway platforms: height-info ─────────────────────────────────
        if etype in ("breakaway-left", "breakaway-mid", "breakaway-right"):
            h1 = float(o.get("og_breakaway_h1", 0.0))
            h2 = float(o.get("og_breakaway_h2", 0.0))
            if h1 != 0.0 or h2 != 0.0:
                lump["height-info"] = ["float", h1, h2]
            log(f"  [breakaway] {o.name}  h1={h1}  h2={h2}")

        # ── Sunkenfisha: count lump ───────────────────────────────────────────
        if etype == "sunkenfisha":
            count = int(o.get("og_fish_count", 1))
            if count != 1:
                lump["count"] = ["uint32", count]
            log(f"  [sunkenfisha] {o.name}  count={count}")

        # ── Sharkey: scale, delay, distance, speed ────────────────────────────
        if etype == "sharkey":
            scale    = float(o.get("og_shark_scale",    1.0))
            delay    = float(o.get("og_shark_delay",    1.0))
            distance = float(o.get("og_shark_distance", 30.0))
            speed    = float(o.get("og_shark_speed",    12.0))
            if scale != 1.0:
                lump["scale"] = ["float", scale]
            lump["delay"]    = ["float", delay]
            lump["distance"] = ["meters", distance]
            lump["speed"]    = ["meters", speed]
            log(f"  [sharkey] {o.name}  scale={scale}  delay={delay}s  dist={distance}m  speed={speed}m/s")

        # ── Oracle / pontoon: alt-task ────────────────────────────────────────
        if etype in ("oracle", "pontoon"):
            task = str(o.get("og_alt_task", "none"))
            if task and task != "none":
                lump["alt-task"] = ["enum-uint32", f"(game-task {task})"]
                log(f"  [{etype}] {o.name}  alt-task={task}")

        # ── Entity links (alt-actor, water-actor, state-actor, etc.) ─────────
        # Build string-array lumps from og_actor_links CollectionProperty.
        # These are merged before custom lump rows so rows can override them.
        link_lumps = _build_actor_link_lumps(o, etype)
        for lkey, lval in link_lumps.items():
            lump[lkey] = lval
            names = lval[1:]  # strip "string" prefix
            log(f"  [entity-link] {o.name}  '{lkey}' → {names}")

        # Warn about required slots that are unset
        for (lkey, sidx, label, _accepted, required) in _actor_link_slots(etype):
            if required and not _actor_get_link(o, lkey, sidx):
                log(f"  [WARNING] {o.name} required link '{lkey}[{sidx}]' ({label}) is not set — may crash at runtime!")

        # ── Custom lump rows (assisted panel) ────────────────────────────────
        # Merge OGLumpRow entries into the lump dict. Rows take priority over
        # hardcoded values above — any conflict logs a warning but the row wins.
        for row in getattr(o, "og_lump_rows", []):
            value, err = _parse_lump_row(row.key, row.ltype, row.value)
            if err:
                log(f"  [WARNING] {o.name} lump row '{row.key}': {err} — skipped")
                continue
            key = row.key.strip()
            if key in _LUMP_HARDCODED_KEYS and key in lump:
                log(f"  [WARNING] {o.name} lump row '{key}' overrides addon default")
            lump[key] = value
            log(f"  [lump-row] {o.name}  '{key}' = {value}")

        out.append({
            "trans":     [gx, gy, gz],
            "etype":     etype,
            "game_task": "(game-task none)",
            "quat":      [0, 0, 0, 1],
            "vis_id":    0,
            "bsphere":   [gx, gy, gz, bsph_r],
            "lump":      lump,
        })

    # ── Checkpoint trigger actors ─────────────────────────────────────────────
    # CHECKPOINT_ empties export as two things:
    #   1. A continue-point record in level-info.gc (via collect_spawns) — the
    #      spawn data the engine uses on respawn.
    #   2. A checkpoint-trigger actor in the JSONC (here) — an invisible entity
    #      that calls set-continue! when Jak enters it.
    # Both are needed: the actor does the triggering, the continue-point holds
    # the spawn position. The actor's continue-name lump must match the
    # continue-point name exactly: "{level_name}-{uid}".
    #
    # Volume mode: if a CPVOL_ mesh is linked (og_cp_link = checkpoint name),
    # the actor uses AABB bounds instead of sphere radius. The GOAL code reads
    # a 'has-volume' lump (uint32 1) to choose AABB vs sphere.
    level_name_for_cp = str(_get_level_prop(scene, "og_level_name", "")).strip().lower().replace(" ", "-")

    # Build cp_name → first linked vol_obj from og_vol_links collections.
    # Checkpoint links are soft-enforced 1:1 at link time (block duplicates),
    # so first() is the same as only() in well-formed scenes.
    vol_by_cp = {}
    for o in level_objs:
        if o.type == "MESH" and o.name.startswith("VOL_"):
            for entry in _vol_links(o):
                if _classify_target(entry.target_name) == "checkpoint":
                    vol_by_cp.setdefault(entry.target_name, o)

    for o in sorted(level_objs, key=lambda o: o.name):
        if not (o.name.startswith("CHECKPOINT_") and o.type == "EMPTY"):
            continue
        if o.name.endswith("_CAM"):
            continue
        uid = o.name[11:] or "cp0"
        l   = o.location
        gx  = round(l.x,  4)
        gy  = round(l.z,  4)
        gz  = round(-l.y, 4)
        r   = float(o.get("og_checkpoint_radius", 3.0))
        cp_name = f"{level_name_for_cp}-{uid}"
        lump = {
            "name":          f"checkpoint-trigger-{uid}",
            "continue-name": cp_name,
        }

        vol_obj = vol_by_cp.get(o.name)
        if vol_obj:
            # AABB mode — derive bounds from volume mesh world-space verts
            xmin, xmax, ymin, ymax, zmin, zmax, cx, cy, cz, rad = _vol_aabb(vol_obj)
            # Slightly tighter padding for checkpoints (matches old behaviour)
            rad = round(max(xmax - xmin, ymax - ymin, zmax - zmin) / 2 + 2.0, 2)
            lump["has-volume"]  = ["uint32", 1]
            lump["bound-xmin"]  = ["meters", xmin]
            lump["bound-xmax"]  = ["meters", xmax]
            lump["bound-ymin"]  = ["meters", ymin]
            lump["bound-ymax"]  = ["meters", ymax]
            lump["bound-zmin"]  = ["meters", zmin]
            lump["bound-zmax"]  = ["meters", zmax]
            out.append({
                "trans":     [cx, cy, cz],
                "etype":     "checkpoint-trigger",
                "game_task": "(game-task none)",
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [cx, cy, cz, rad],
                "lump":      lump,
            })
            log(f"  [checkpoint] {o.name} → '{cp_name}'  AABB vol={vol_obj.name}")
        else:
            # Sphere mode — use og_checkpoint_radius
            lump["radius"] = ["meters", r]
            out.append({
                "trans":     [gx, gy, gz],
                "etype":     "checkpoint-trigger",
                "game_task": "(game-task none)",
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [gx, gy, gz, max(r, 3.0)],
                "lump":      lump,
            })
            log(f"  [checkpoint] {o.name} → '{cp_name}'  sphere r={r}m")

    return out

def collect_ambients(scene):
    out = []
    for o in _level_objects(scene):
        if not (o.name.startswith("AMBIENT_") and o.type == "EMPTY"):
            continue
        l = o.location
        gx, gy, gz = round(l.x, 4), round(l.z, 4), round(-l.y, 4)

        if o.get("og_sound_name"):
            # Sound emitter — placed via the Audio panel
            radius   = float(o.get("og_sound_radius", 15.0))
            mode     = str(o.get("og_sound_mode", "loop"))
            snd_name = str(o["og_sound_name"]).lower().strip()

            # cycle-speed: ["float", base_secs, random_range_secs]
            # Negative base = looping (ambient-type-sound-loop) — confirmed working
            # Positive base = one-shot interval (ambient-type-sound) — engine bug, crashes
            if mode == "loop":
                cycle_speed = ["float", -1.0, 0.0]
            else:
                cycle_speed = ["float",
                               float(o.get("og_cycle_min", 5.0)),
                               float(o.get("og_cycle_rnd", 2.0))]

            out.append({
                "trans":   [gx, gy, gz, radius],
                "bsphere": [gx, gy, gz, radius],
                "lump": {
                    "name":        o.name[8:].lower() or "ambient",
                    "type":        "'sound",
                    "effect-name": ["symbol", snd_name],
                    "cycle-speed": cycle_speed,
                },
            })
        else:
            # Legacy hint emitter — unchanged behaviour
            out.append({
                "trans":   [gx, gy, gz, 10.0],
                "bsphere": [gx, gy, gz, 15.0],
                "lump": {
                    "name":      o.name[8:].lower() or "ambient",
                    "type":      "'hint",
                    "text-id":   ["enum-uint32", "(text-id fuel-cell)"],
                    "play-mode": "'notice",
                },
            })
    return out

def collect_nav_mesh_geometry(scene, level_name):
    """Collect geometry tagged og_navmesh=True for future navmesh generation.

    Full navmesh injection into the level BSP is not yet implemented in the
    OpenGOAL custom level pipeline (Entity.cpp writes a null pointer for the
    nav-mesh field).  This function gathers the data so it's ready when
    engine-side support lands.
    """
    tris = []
    for o in _level_objects(scene):
        if not (o.type == "MESH" and o.get("og_navmesh", False)):
            continue
        mesh = o.data
        mat  = o.matrix_world
        verts = [mat @ v.co for v in mesh.vertices]
        mesh.calc_loop_triangles()
        for tri in mesh.loop_triangles:
            a, b, c = [verts[tri.vertices[i]] for i in range(3)]
            tris.append((
                (round(a.x,4), round(a.z,4), round(-a.y,4)),
                (round(b.x,4), round(b.z,4), round(-b.y,4)),
                (round(c.x,4), round(c.z,4), round(-c.y,4)),
            ))
    log(f"[navmesh] collected {len(tris)} tris from '{level_name}' "
        f"(injection pending engine support)")
    return tris

def needed_ags(actors):
    seen, r = set(), []
    for a in actors:
        for g in ETYPE_AG.get(a["etype"], []):
            if g and g not in seen:
                seen.add(g); r.append(g)
    return r

def needed_code(actors):
    """Return list of (o_file, gc_path, dep) for enemy types not in GAME.CGO.

    o_only=True entries: inject .o into custom DGO only — vanilla game.gp already
    has the goal-src line so we must not duplicate it (causes 'duplicate defstep').

    Returns list of (o_file, gc_path_or_None, dep_or_None).
    write_gd() uses o_file for DGO injection.
    patch_game_gp() skips entries where gc_path is None.
    """
    seen, r = set(), []
    for a in actors:
        etype = a["etype"]
        info = ETYPE_CODE.get(etype)
        if not info or info.get("in_game_cgo"):
            continue
        o = info["o"]
        if o not in seen:
            seen.add(o)
            if info.get("o_only"):
                r.append((o, None, None))
            else:
                r.append((o, info["gc"], info.get("dep", "process-drawable")))
    return r

# ---------------------------------------------------------------------------
# FILE WRITERS
# ---------------------------------------------------------------------------

def write_jsonc(name, actors, ambients, camera_actors=None, base_id=10000):
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)
    all_actors = list(actors) + (camera_actors or [])
    ags = needed_ags(actors)  # camera-tracker has no art group, so only scan regular actors
    data = {
        "long_name": name, "iso_name": _iso(name), "nickname": _nick(name),
        "gltf_file": f"custom_assets/jak1/levels/{name}/{name}.glb",
        "automatic_wall_detection": True, "automatic_wall_angle": 45.0,
        "double_sided_collide": False, "base_id": base_id,
        "art_groups": [g.replace(".go","") for g in ags],
        "custom_models": [], "textures": [["village1-vis-alpha"]],
        "tex_remap": "village1", "sky": "village1", "tpages": [],
        "ambients": ambients, "actors": all_actors,
    }
    p = d / f"{name}.jsonc"
    new_text = f"// OpenGOAL custom level: {name}\n" + json.dumps(data, indent=2)
    if p.exists() and p.read_text() == new_text:
        log(f"Skipped {p} (unchanged)")
    else:
        p.write_text(new_text)
        log(f"Wrote {p}  ({len(actors)} actors + {len(camera_actors or [])} cameras)")

def write_gd(name, ags, code_deps, tpages=None):
    """Write .gd file.

    code_deps is a list of (o_file, gc_path, dep) from needed_code().
    Each enemy .o is inserted before the art groups so it links first.

    FIX v0.5.0 (Bug 1): The opening paren for the inner file list is now its
    own line so that the first file entry keeps correct indentation.  The old
    code concatenated ' (' + files[0].lstrip() which produced a malformed
    S-expression when enemy .o entries were present and caused GOALC to crash.
    """
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)
    dgo_name = f"{_nick(name).upper()}.DGO"
    code_o   = [f'  "{o}"' for o, _, _ in code_deps]
    # Village1 sky tpages always present; add entity-specific tpages before art groups
    base_tpages = ['  "tpage-398.go"', '  "tpage-400.go"', '  "tpage-399.go"',
                   '  "tpage-401.go"', '  "tpage-1470.go"']
    extra_tpages = [f'  "{tp}"' for tp in (tpages or [])
                    if f'  "{tp}"' not in base_tpages]
    files = (
        [f'  "{name}-obs.o"']
        + code_o
        + base_tpages
        + extra_tpages
        + [f'  "{g}"' for g in ags]
        + [f'  "{name}.go"']
    )
    lines = (
        [f';; DGO for {name}', f'("{dgo_name}"', ' (']
        + files
        + ['  )', ' )']
    )
    p = d / f"{_nick(name)}.gd"
    new_text = "\n".join(lines) + "\n"
    if not p.exists() or p.read_text() != new_text:
        p.write_text(new_text)
        log(f"Wrote {p}  (enemy .o files: {[o for o,_,_ in code_deps]})")
    else:
        log(f"Skipped {p} (unchanged)")



def _make_continues(name, spawns):
    """Build the GOAL :continues list for level-load-info.

    Each spawn dict carries full quat + camera data from collect_spawns.
    Spawns include both SPAWN_ (primary) and CHECKPOINT_ (auto-assigned) empties.

    :vis-nick is intentionally 'none for all custom-level continues.
    Custom levels have no vis data, so vis?=#f at runtime and this field is never
    acted upon. Matches the test-zone reference implementation in level-info.gc.
    """
    def cp(sp):
        cr = sp.get("cam_rot", [1,0,0, 0,1,0, 0,0,1])
        cr_str = " ".join(str(v) for v in cr)
        return (f"(new 'static 'continue-point\n"
                f"             :name \"{name}-{sp['name']}\"\n"
                f"             :level '{name}\n"
                f"             :trans (new 'static 'vector"
                f" :x (meters {sp['x']:.4f}) :y (meters {sp['y']:.4f}) :z (meters {sp['z']:.4f}) :w 1.0)\n"
                f"             :quat (new 'static 'quaternion"
                f" :x {sp.get('qx',0.0)} :y {sp.get('qy',0.0)} :z {sp.get('qz',0.0)} :w {sp.get('qw',1.0)})\n"
                f"             :camera-trans (new 'static 'vector"
                f" :x (meters {sp.get('cam_x', sp['x']):.4f})"
                f" :y (meters {sp.get('cam_y', sp['y']+4.0):.4f})"
                f" :z (meters {sp.get('cam_z', sp['z']):.4f}) :w 1.0)\n"
                f"             :camera-rot (new 'static 'array float 9 {cr_str})\n"
                f"             :load-commands '()\n"
                f"             :vis-nick 'none\n"
                f"             :lev0 '{name}\n"
                f"             :disp0 'display\n"
                f"             :lev1 #f\n"
                f"             :disp1 #f)")

    if spawns:
        return "'(" + "\n             ".join(cp(s) for s in spawns) + ")"

    # No spawns placed — emit a safe default at origin + 10m up
    return (f"'((new 'static 'continue-point\n"
            f"             :name \"{name}-start\"\n"
            f"             :level '{name}\n"
            f"             :trans (new 'static 'vector :x 0.0 :y (meters 10.) :z 0.0 :w 1.0)\n"
            f"             :quat (new 'static 'quaternion :w 1.0)\n"
            f"             :camera-trans (new 'static 'vector :x 0.0 :y (meters 14.) :z 0.0 :w 1.0)\n"
            f"             :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)\n"
            f"             :load-commands '()\n"
            f"             :vis-nick 'none\n"
            f"             :lev0 '{name}\n"
            f"             :disp0 'display\n"
            f"             :lev1 #f\n"
            f"             :disp1 #f))")

def patch_level_info(name, spawns, scene=None):
    p = _level_info()
    if not p.exists(): log(f"WARNING: {p} not found"); return
    # Audio settings from scene props (if scene provided)
    if scene is not None:
        _bank      = str(_get_level_prop(scene, "og_music_bank",    "none") or "none")
        _music_val = f"'{_bank}" if _bank and _bank != "none" else "#f"
        _sb1       = str(_get_level_prop(scene, "og_sound_bank_1",  "none") or "none")
        _sb2       = str(_get_level_prop(scene, "og_sound_bank_2",  "none") or "none")
        _sb_list   = [s for s in [_sb1, _sb2] if s and s != "none"]
        _sbanks    = " ".join(_sb_list)
        _sbanks_val = f"'({_sbanks})" if _sbanks else "'()"
        _bot_h     = float(_get_level_prop(scene, "og_bottom_height", -20.0))
        _vis_ov    = str(_get_level_prop(scene, "og_vis_nick_override", "") or "").strip()
        _vnick     = _vis_ov if _vis_ov else _nick(name)
    else:
        _music_val = "#f"
        _sbanks_val = "'()"
        _bot_h   = -20.0
        _vnick   = _nick(name)

    # ── Auto-compute bsphere from spawn positions ────────────────────────────
    # Centre = mean of all spawn XZ positions, Y = mean spawn Y + 2m.
    # Radius = max distance from centre to any spawn + 64m padding so the
    # engine considers the level "nearby" well before the player reaches it.
    # Fallback when no spawns: a very large sphere (40km radius) that always passes.
    if spawns:
        xs  = [s["x"] for s in spawns]
        ys  = [s["y"] for s in spawns]
        zs  = [s["z"] for s in spawns]
        cx  = sum(xs) / len(xs)
        cy  = sum(ys) / len(ys) + 2.0
        cz  = sum(zs) / len(zs)
        r   = max(
            math.sqrt((s["x"]-cx)**2 + (s["y"]-cy)**2 + (s["z"]-cz)**2)
            for s in spawns
        ) + 64.0
        # Convert to game units (4096 per metre) for the sphere :w value
        bsphere_w = round(r * 4096.0, 1)
        bsphere_str = (f"(new 'static 'sphere"
                       f" :x {round(cx*4096.0, 1)} :y {round(cy*4096.0, 1)} :z {round(cz*4096.0, 1)}"
                       f" :w {bsphere_w})")
    else:
        bsphere_str = "(new 'static 'sphere :w 167772160000.0)"  # ~40km radius

    block = (f"\n(define {name}\n"
             f"  (new 'static 'level-load-info\n"
             f"       :index 27\n"
             f"       :name '{name}\n"
             f"       :visname '{name}-vis\n"
             f"       :nickname '{_vnick}\n"
             f"       :packages '()\n"
             f"       :sound-banks {_sbanks_val}\n"
             f"       :music-bank {_music_val}\n"
             f"       :ambient-sounds '()\n"
             f"       :mood '*village1-mood*\n"
             f"       :mood-func 'update-mood-village1\n"
             f"       :ocean #f\n"
             f"       :sky #t\n"
             f"       :sun-fade 1.0\n"
             f"       :continues\n"
             f"       {_make_continues(name, spawns)}\n"
             f"       :tasks '()\n"
             f"       :priority 100\n"
             f"       :load-commands '()\n"
             f"       :alt-load-commands '()\n"
             f"       :bsp-mask #xffffffffffffffff\n"
             f"       :bsphere {bsphere_str}\n"
             f"       :bottom-height (meters {_bot_h:.1f})\n"
             f"       :run-packages '()\n"
             f"       :wait-for-load #t))\n"
             f"\n(cons! *level-load-list* '{name})\n")
    txt = p.read_text(encoding="utf-8")
    txt = re.sub(rf"\n\(define {re.escape(name)}\b.*?\(cons!.*?'{re.escape(name)}\)\n",
                 "", txt, flags=re.DOTALL)
    marker = ";;;;; CUSTOM LEVELS"
    new_txt = (txt.replace(marker, marker+block, 1) if marker in txt
               else txt + "\n;;;;; CUSTOM LEVELS\n" + block)
    original = p.read_text(encoding="utf-8")
    if new_txt != original:
        p.write_text(new_txt, encoding="utf-8")
        log("Patched level-info.gc")
    else:
        log("Skipped level-info.gc (unchanged)")

def patch_game_gp(name, code_deps=None):
    """Patch game.gp to build our custom level and compile enemy code files.

    code_deps: list of (o_file, gc_path, dep) from needed_code().
    For each enemy type not in GAME.CGO we add a goal-src line so GOALC
    compiles and links its code into our DGO.  Without this the type is
    undefined at runtime and the entity spawns as a do-nothing process.
    """
    p = _game_gp()
    if not p.exists(): log(f"WARNING: {p} not found"); return
    raw  = p.read_bytes()
    crlf = b"\r\n" in raw
    txt  = raw.decode("utf-8").replace("\r\n", "\n")
    nick = _nick(name)
    dgo  = f"{nick.upper()}.DGO"

    # goal-src lines for enemy code (de-duplicated)
    # Skip o_only entries (gc=None) — vanilla game.gp already has their goal-src lines.
    extra_goal_src = ""
    if code_deps:
        seen_gc = set()
        for o, gc, dep in code_deps:
            if gc is None:
                continue  # o_only: .o injected into DGO but no goal-src needed
            if gc not in seen_gc:
                seen_gc.add(gc)
                extra_goal_src += f'(goal-src "{gc}" "{dep}")\n'

    correct_block = (
        f'(build-custom-level "{name}")\n'
        f'(custom-level-cgo "{dgo}" "{name}/{nick}.gd")\n'
        f'(goal-src "levels/{name}/{name}-obs.gc" "process-drawable")\n'
        + extra_goal_src
    )

    # Strip any previously written block for this level
    txt = re.sub(r'\(build-custom-level "' + re.escape(name) + r'"\)\n', '', txt)
    txt = re.sub(r'\(custom-level-cgo "[^"]*" "' + re.escape(name) + r'/[^"]+"\)\n', '', txt)
    # FIX v0.5.0 (Bug 2): was r'/[^"]+\"[^)]*\)' — the \" was a literal
    # backslash+quote so the regex never matched, leaving stale goal-src lines
    # in game.gp across exports which caused duplicate-compile crashes in GOALC.
    txt = re.sub(r'\(goal-src "levels/' + re.escape(name) + r'/[^"]+"[^)]*\)\n', '', txt)
    # Strip ALL enemy goal-src lines that could have been injected by any previous export.
    # This catches leftover entries even if the dep changed between exports.
    # We match any goal-src line whose path matches a known ETYPE_CODE gc file.
    for _etype_info in ETYPE_CODE.values():
        _gc = _etype_info.get("gc", "")
        if _gc:
            txt = re.sub(r'\(goal-src "' + re.escape(_gc) + r'"[^)]*\)\n', '', txt)

    if correct_block in txt:
        log("game.gp already correct"); return

    for anchor in ['(build-custom-level "test-zone")', '(group-list "all-code"']:
        if anchor in txt:
            txt = txt.replace(anchor, correct_block + "\n" + anchor, 1)
            break
    else:
        txt += "\n" + correct_block

    if crlf:
        txt = txt.replace("\n", "\r\n")
    p.write_bytes(txt.encode("utf-8"))
    log(f"Patched game.gp  (extra goal-src: {[gc for _,gc,_ in (code_deps or []) if gc is not None]})")



# ---------------------------------------------------------------------------
# LEVEL MANAGER — discover / remove custom levels
# ---------------------------------------------------------------------------

def discover_custom_levels():
    """Scan the filesystem and game.gp to find all custom levels.

    Returns a list of dicts:
      name        - level name (folder name)
      has_glb     - .glb exists
      has_jsonc   - .jsonc exists
      has_obs     - obs.gc exists
      has_gp      - entry found in game.gp
      conflict    - True if multiple levels share the same DGO nick
      nick        - 3-char nickname
      dgo         - DGO filename
    """
    levels_dir = _levels_dir()
    goal_levels = _goal_src() / "levels"
    gp_path = _game_gp()

    # Read game.gp entries
    gp_names = set()
    if gp_path.exists():
        txt = gp_path.read_text(encoding="utf-8")
        for m in re.finditer(r'\(build-custom-level "([^"]+)"\)', txt):
            gp_names.add(m.group(1))

    # Scan custom_assets/jak1/levels/
    found = {}
    if levels_dir.exists():
        for d in sorted(levels_dir.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            nick = _nick(name)
            dgo  = f"{nick.upper()}.DGO"
            found[name] = {
                "name":      name,
                "has_glb":   (d / f"{name}.glb").exists(),
                "has_jsonc": (d / f"{name}.jsonc").exists(),
                "has_gd":    (d / f"{nick}.gd").exists(),
                "has_obs":   (goal_levels / name / f"{name}-obs.gc").exists(),
                "has_gp":    name in gp_names,
                "nick":      nick,
                "dgo":       dgo,
                "conflict":  False,
            }

    # Detect DGO nickname conflicts
    nick_to_names = {}
    for info in found.values():
        nick_to_names.setdefault(info["dgo"], []).append(info["name"])
    for names in nick_to_names.values():
        if len(names) > 1:
            for n in names:
                found[n]["conflict"] = True

    return list(found.values())


def remove_level(name):
    """Remove all files for a custom level and clean game.gp.

    Deletes:
      custom_assets/jak1/levels/<name>/   (entire folder)
      goal_src/jak1/levels/<name>/        (entire folder)

    Removes from game.gp:
      (build-custom-level "<name>")
      (custom-level-cgo ...)
      (goal-src "levels/<name>/...")

    Returns list of log messages.
    """
    import shutil
    msgs = []

    # Delete custom_assets folder
    assets_dir = _levels_dir() / name
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
        msgs.append(f"Deleted {assets_dir}")
    else:
        msgs.append(f"(not found) {assets_dir}")

    # Delete goal_src levels folder
    goal_dir = _goal_src() / "levels" / name
    if goal_dir.exists():
        shutil.rmtree(goal_dir)
        msgs.append(f"Deleted {goal_dir}")
    else:
        msgs.append(f"(not found) {goal_dir}")

    # Patch level-info.gc — strip the define block and cons! entry
    li_path = _level_info()
    if li_path.exists():
        txt = li_path.read_text(encoding="utf-8")
        new_txt = re.sub(
            rf"\n\(define {re.escape(name)}\b.*?\(cons!.*?'{re.escape(name)}\)\n",
            "", txt, flags=re.DOTALL)
        if new_txt != txt:
            li_path.write_text(new_txt, encoding="utf-8")
            msgs.append(f"Cleaned level-info.gc entry for '{name}'")
        else:
            msgs.append(f"level-info.gc had no entry for '{name}'")
    else:
        msgs.append("level-info.gc not found")

    # Patch game.gp — strip all entries for this level
    gp_path = _game_gp()
    if gp_path.exists():
        raw  = gp_path.read_bytes()
        crlf = b"\r\n" in raw
        txt  = raw.decode("utf-8").replace("\r\n", "\n")
        before = txt

        nick = _nick(name)
        txt = re.sub(r'\(build-custom-level "' + re.escape(name) + r'"\)\n', '', txt)
        txt = re.sub(r'\(custom-level-cgo "[^"]*" "' + re.escape(name) + r'/[^"]+\"\)\n', '', txt)
        txt = re.sub(r'\(goal-src "levels/' + re.escape(name) + r'/[^"]+\"[^)]*\)\n', '', txt)

        if txt != before:
            if crlf:
                txt = txt.replace("\n", "\r\n")
            gp_path.write_bytes(txt.encode("utf-8"))
            msgs.append(f"Cleaned game.gp entries for '{name}'")
        else:
            msgs.append(f"game.gp had no entries for '{name}'")
    else:
        msgs.append("game.gp not found")

    return msgs


def export_glb(ctx, name):
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)

    level_col = _active_level_col(ctx.scene)
    if level_col is not None:
        # Collection mode — export only objects inside the Geometry sub-collection,
        # excluding anything under the Reference sub-collection (og_no_export=True).
        # We select only those objects, export with use_selection=True, then restore.
        geo_col = None
        for c in level_col.children:
            if c.name == "Geometry":
                geo_col = c
                break

        # Gather exportable objects: meshes in Geometry (and its children) except Reference
        if geo_col is not None:
            export_objs = _recursive_col_objects(geo_col, exclude_no_export=True)
            export_objs = [o for o in export_objs if o.type == "MESH"]
        else:
            # No Geometry sub-collection yet — fall back to all meshes in the level
            export_objs = [o for o in _recursive_col_objects(level_col, exclude_no_export=True)
                           if o.type == "MESH"]

        # Save selection state
        prev_active    = ctx.view_layer.objects.active
        prev_selected  = [o for o in ctx.scene.objects if o.select_get()]

        # Deselect all, select export targets
        for o in ctx.scene.objects:
            o.select_set(False)
        for o in export_objs:
            o.select_set(True)
        if export_objs:
            ctx.view_layer.objects.active = export_objs[0]

        bpy.ops.export_scene.gltf(
            filepath=str(d / f"{name}.glb"), export_format="GLB",
            export_vertex_color="ACTIVE", export_normals=True,
            export_materials="EXPORT", export_texcoords=True,
            export_apply=True, use_selection=True,
            export_yup=True, export_skins=False, export_animations=False,
            export_extras=True)

        # Restore selection state
        for o in ctx.scene.objects:
            o.select_set(False)
        for o in prev_selected:
            o.select_set(True)
        ctx.view_layer.objects.active = prev_active

    else:
        # Fallback: v1.1.0 behaviour — export entire scene
        bpy.ops.export_scene.gltf(
            filepath=str(d / f"{name}.glb"), export_format="GLB",
            export_vertex_color="ACTIVE", export_normals=True,
            export_materials="EXPORT", export_texcoords=True,
            export_apply=True, use_selection=False,
            export_yup=True, export_skins=False, export_animations=False,
            export_extras=True)

    log("Exported GLB")

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

def _actor_uses_waypoints(etype):
    """True if this entity type can use waypoints (path lump or nav patrol)."""
    info = ENTITY_DEFS.get(etype, {})
    return (not info.get("nav_safe", True)    # nav-enemy — optional patrol path
            or info.get("needs_path", False)  # process-drawable that requires path
            or info.get("needs_pathb", False)
            or info.get("needs_sync", False)) # sync platform — path drives movement


def _actor_uses_navmesh(etype):
    """True if this entity type is a nav-enemy and needs entity.gc navmesh patch."""
    info = ENTITY_DEFS.get(etype, {})
    return info.get("ai_type") == "nav-enemy"


def _actor_is_platform(etype):
    """True if this entity is in the Platforms category."""
    return ENTITY_DEFS.get(etype, {}).get("cat") == "Platforms"

_LAUNCHER_TYPES = {"launcher", "springbox"}

def _actor_is_launcher(etype):
    """True if this entity is a launcher or springbox (spring-height lump)."""
    return etype in _LAUNCHER_TYPES

_SPAWNER_TYPES = {"swamp-bat", "yeti", "villa-starfish", "swamp-rat-nest"}

def _actor_is_spawner(etype):
    """True if this entity spawns child enemies (num-lurkers lump)."""
    return etype in _SPAWNER_TYPES


def _actor_is_enemy(etype):
    """True if this entity is in the Enemies or Bosses category.
    Enemies/bosses inherit fact-info-enemy, which reads idle-distance from
    the entity's res-lump on construction (engine: fact-h.gc line 191).
    Engine default is 80 meters.
    """
    return ENTITY_DEFS.get(etype, {}).get("cat") in ("Enemies", "Bosses")


def _actor_supports_aggro_trigger(etype):
    """True if this enemy responds to 'cue-chase / 'cue-patrol / 'go-wait-for-cue.
    Only nav-enemies have these handlers (engine: nav-enemy.gc line 142).
    Process-drawable enemies (junglesnake, bully, yeti, mother-spider, etc.)
    do NOT respond to these events — silently doing nothing if sent.
    """
    return _actor_uses_navmesh(etype)


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


def _vol_links(vol):
    """Return the og_vol_links CollectionProperty on a volume mesh.
    Migrates legacy single-string og_vol_link if present.
    Always safe to call — returns the live collection.
    """
    if vol is None:
        return None
    # Migration: legacy single-string format -> single-entry collection
    legacy = vol.get("og_vol_link", "")
    if legacy and len(vol.og_vol_links) == 0:
        entry = vol.og_vol_links.add()
        entry.target_name = legacy
        entry.behaviour   = "cue-chase"
        try:
            del vol["og_vol_link"]
        except Exception:
            pass
    return vol.og_vol_links


def _vol_link_targets(vol):
    """Return list of target_name strings for a volume. Migrates if needed."""
    links = _vol_links(vol)
    if links is None:
        return []
    return [e.target_name for e in links]


def _vol_has_link_to(vol, target_name):
    """True if the volume has at least one link to target_name."""
    return target_name in _vol_link_targets(vol)


def _rename_vol_for_links(vol):
    """Rename a volume mesh based on its current link count.
    0 links → VOL_<id>
    1 link  → VOL_<target_name>
    2+ links → VOL_<id>_<n>links
    Idempotent. Stores the original numeric id in og_vol_id (set on spawn).
    """
    if vol is None:
        return
    links = _vol_links(vol)
    n = len(links)
    vid = vol.get("og_vol_id", 0)
    if n == 0:
        new_name = f"VOL_{vid}"
    elif n == 1:
        new_name = f"VOL_{links[0].target_name}"
    else:
        new_name = f"VOL_{vid}_{n}links"
    if vol.name != new_name:
        vol.name = new_name


def _vols_linking_to(scene, target_name):
    """Return all VOL_ meshes that have at least one link to target_name."""
    return sorted(
        [o for o in _level_objects(scene)
         if o.type == "MESH" and o.name.startswith("VOL_")
         and _vol_has_link_to(o, target_name)],
        key=lambda o: o.name,
    )


def _vol_get_link_to(vol, target_name):
    """Return the OGVolLink entry on vol pointing at target_name, or None."""
    for entry in _vol_links(vol):
        if entry.target_name == target_name:
            return entry
    return None


def _vol_remove_link_to(vol, target_name):
    """Remove the link entry pointing at target_name from vol. Returns True if found."""
    links = _vol_links(vol)
    for i, entry in enumerate(links):
        if entry.target_name == target_name:
            links.remove(i)
            _rename_vol_for_links(vol)
            return True
    return False


def _classify_target(target_name):
    """Return one of 'camera', 'checkpoint', 'enemy', or '' for an unknown target."""
    if target_name.startswith("CAMERA_"):
        return "camera"
    if target_name.startswith("CHECKPOINT_") and not target_name.endswith("_CAM"):
        return "checkpoint"
    if target_name.startswith("ACTOR_") and "_wp_" not in target_name and "_wpb_" not in target_name:
        parts = target_name.split("_", 2)
        if len(parts) >= 3 and _actor_supports_aggro_trigger(parts[1]):
            return "enemy"
    return ""
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
