# ---------------------------------------------------------------------------
# export.py — OpenGOAL Level Tools
# Level data collection, GOAL code generation, navmesh processing,
# and actor/volume/trigger/camera helpers used at export time.
# ---------------------------------------------------------------------------

import bpy, os, re, json, math, mathutils
from pathlib import Path
from .data import (
    ENTITY_DEFS, ETYPE_CODE, ETYPE_TPAGES, ETYPE_AG, VERTEX_EXPORT_TYPES,
    NAV_UNSAFE_TYPES, NEEDS_PATH_TYPES, NEEDS_PATHB_TYPES, IS_PROP_TYPES,
    needed_tpages, LUMP_REFERENCE, ACTOR_LINK_DEFS,
    _lump_ref_for_etype, _actor_link_slots, _actor_has_links,
    _actor_links, _actor_get_link, _actor_set_link,
    _actor_remove_link, _build_actor_link_lumps,
    _parse_lump_row, _aggro_event_id, AGGRO_TRIGGER_EVENTS,
    _LUMP_HARDCODED_KEYS,
)
from .collections import (
    _get_level_prop, _level_objects,
    _active_level_col, _classify_object, _col_path_for_entity,
    _ensure_sub_collection, _recursive_col_objects,
    _COL_PATH_WAYPOINTS, _COL_PATH_NAVMESHES,
)

# _data_root reads the addon pref — duplicated here to avoid circular import with build.py
def _data_root():
    import bpy as _bpy
    prefs = _bpy.context.preferences.addons.get("opengoal_tools")
    p = prefs.preferences.data_path if prefs else ""
    from pathlib import Path as _Path
    return _Path(p.strip().rstrip("\\").rstrip("/")) if p.strip() else _Path(".")

def _data():       return _data_root() / "data"
def _levels_dir(): return _data() / "custom_assets" / "jak1" / "levels"
def _goal_src():   return _data() / "goal_src" / "jak1"
def _level_info(): return _goal_src() / "engine" / "level" / "level-info.gc"
def _game_gp():    return _goal_src() / "game.gp"
def _ldir(name):   return _levels_dir() / name
def _entity_gc():  return _goal_src() / "engine" / "entity" / "entity.gc"

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
# Actor-type predicates and volume link helpers
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
# Path helpers needed by collect/write functions
# (will move to build.py when that module is extracted)
# ---------------------------------------------------------------------------

# _levels_dir, _goal_src, _level_info, _game_gp, _ldir, _entity_gc → imported from build

def _lname(ctx):
    col = _active_level_col(ctx.scene)
    if col is not None:
        return str(col.get("og_level_name", "")).strip().lower().replace(" ", "-")
    return ctx.scene.og_props.level_name.strip().lower().replace(" ","-")
def _nick(n):      return n.replace("-","")[:3].lower()
def _iso(n):       return n.replace("-","").upper()[:8]
def log(m):        print(f"[OpenGOAL] {m}")


# ---------------------------------------------------------------------------
# Collect functions and level file writers
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

def collect_actors(scene, depsgraph=None):
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
            ct     = o.get("og_crate_type",          "steel")
            pickup = o.get("og_crate_pickup",         "money")
            amount = int(o.get("og_crate_pickup_amount", 1))
            lump["crate-type"] = f"'{ct}"
            _CRATE_PICKUP_ENGINE = {
                "none":       "(pickup-type none)",
                "money":      "(pickup-type money)",
                "eco-yellow": "(pickup-type eco-yellow)",
                "eco-red":    "(pickup-type eco-red)",
                "eco-blue":   "(pickup-type eco-blue)",
                "eco-green":  "(pickup-type eco-green)",
                "buzzer":     "(pickup-type buzzer)",
            }
            eng_str = _CRATE_PICKUP_ENGINE.get(pickup, "(pickup-type money)")
            if pickup == "buzzer":
                amount = 1  # engine always spawns exactly 1 scout fly
            if pickup != "none":
                lump["eco-info"] = ["eco-info", eng_str, amount]
            log(f"  [crate] {o.name}  type={ct}  pickup={pickup}  amount={amount}")
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

        # ── Water-vol: water-height + vol lumps ───────────────────────────────
        # water-vol needs two lumps to function:
        #
        # 1. 'water-height  — 5 floats: [surface, wade, swim, flags, bottom]
        #    All in meters; C++ compiler multiplies by METER_LENGTH (4096).
        #    The engine reads these to set Jak's wade/swim thresholds and the
        #    kill-plane depth.
        #
        # 2. 'vol  — 6 "vector-vol" planes defining the activation AABB.
        #    WITHOUT this lump vol-control.pos-vol-count = 0, point-in-vol?
        #    always returns #f, and the zone NEVER activates (root cause of
        #    water-vol appearing broken in custom levels before this fix).
        #
        #    Each plane = [nx, ny, nz, d_meters].  The engine stores planes as
        #    (nx, ny, nz, d_raw) where d_raw = d_meters * 4096.  The C++ lump
        #    compiler handles the × 4096 automatically for "vector-vol" type.
        #    Plane equation: dot(normal, point) >= d  →  point is inside.
        #
        #    Box layout (game coords: X = Blender X, Y = Blender Z up,
        #                             Z = Blender -Y):
        #    All normals point INWARD.  Inside condition: dot(P,N) >= d.
        #      top cap — normal ( 0, -1,  0), d = -surface_y
        #      floor   — normal ( 0, +1,  0), d =  bot_y  (surface + bottom offset)
        #      +X cap  — normal (-1,  0,  0), d = -(cx + hx)
        #      -X cap  — normal (+1,  0,  0), d =  cx - hx
        #      +Z cap  — normal ( 0,  0, -1), d = -(cz + hz)
        #      -Z cap  — normal ( 0,  0, +1), d =  cz - hz
        #
        #    Scale: the empty's world scale sets the XZ half-extents.
        #    The user sizes the empty to cover the water area.  Scale 1 = 1 m
        #    half-extent (2 m total width) — scale up to cover the water mesh.
        if etype == "water-vol":
            # Legacy ACTOR_ water-vol path (hidden from picker — use WATER_ mesh instead).
            # wade/swim are depths below surface (positive meters); bottom is absolute Y.
            surface = float(o.get("og_water_surface", 0.0))
            wade    = float(o.get("og_water_wade",    0.5))
            swim    = float(o.get("og_water_swim",    1.0))
            bottom  = float(o.get("og_water_bottom",  surface - 5.0))
            lump["water-height"] = ["water-height", surface, wade, swim, "(water-flags wt02 wt03 wt05 wt22)", bottom]

            # Build the 6-plane vol box from the empty's world scale.
            # NOTE: o.dimensions returns (0,0,0) for empties (no mesh geometry).
            # Use o.scale directly — actor empties are never parented or rotated
            # in this addon, so local scale == world scale.
            # Scale X → game X half-extent, Scale Y → game Z half-extent.
            # Default scale is (1,1,1) = a 2m×2m box. User should scale the
            # empty to match the water area before exporting.
            hx    = abs(o.scale.x)         # game X half-extent (meters)
            hz    = abs(o.scale.y)         # game Z half-extent (meters)
            top_y = surface                # absolute Y of water surface
            bot_y = bottom                 # absolute Y of kill floor (absolute, not relative)

            lump["vol"] = [
                "vector-vol",
                # Normals point OUTWARD. Inside = negative side of each plane.
                # point-in-vol? returns #f when dot(P,N) - w > 0
                [ 0,  1,  0,   top_y      ],   # top:   P.y <= surface
                [ 0, -1,  0,  -bot_y      ],   # floor: P.y >= bottom
                [ 1,  0,  0,   gx + hx    ],   # +X:    P.x <= cx+hx
                [-1,  0,  0, -(gx - hx)   ],   # -X:    P.x >= cx-hx
                [ 0,  0,  1,   gz + hz    ],   # +Z:    P.z <= cz+hz
                [ 0,  0, -1, -(gz - hz)   ],   # -Z:    P.z >= cz-hz
            ]
            log(f"  [water-vol] {o.name}  surface={surface}m  wade={wade}m  swim={swim}m  "
                f"bottom={bottom}m  box={hx*2:.1f}x{hz*2:.1f}m")

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

        # water-vol: bsphere must enclose the full activation box so the process
        # isn't culled before it can run point-in-vol checks each frame.
        # Use o.scale — empties have no dimensions, scale is the half-extent.
        if etype == "water-vol":
            hx     = abs(o.scale.x)
            hz     = abs(o.scale.y)
            bsph_r = max((hx ** 2 + hz ** 2) ** 0.5, 10.0)  # minimum 10m

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

    # ── Vertex-export meshes ─────────────────────────────────────────────────
    # Plain MESH objects tagged with og_vertex_export_etype emit one actor per
    # vertex at world-space position. Modifiers are evaluated via the dependency
    # graph so the final post-modifier mesh is used — the original is untouched.
    # This lets you use Subdivision Surface / Array / Curve modifiers to control
    # point density non-destructively.
    #
    # depsgraph must be fetched on the main thread and passed in — calling
    # bpy.context from a background thread is unsafe and causes intermittent
    # Blender crashes (~25% of compile runs). Falls back to bpy.context only
    # when called directly from a panel (i.e. on the main thread).
    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    ve_counter = 0
    for o in _level_objects(scene):
        if o.type != "MESH":
            continue
        etype = str(o.get("og_vertex_export_etype", "")).strip()
        if not etype or etype not in VERTEX_EXPORT_TYPES:
            continue
        # Evaluate with modifiers applied — safe, does not modify the original
        o_eval = o.evaluated_get(depsgraph)
        mesh_eval = o_eval.to_mesh()
        mat  = o.matrix_world
        verts = mesh_eval.vertices
        for v in verts:
            wco  = mat @ v.co
            gx_v = round(wco.x, 4)
            gy_v = round(wco.z, 4)
            gz_v = round(-wco.y, 4)
            uid  = f"ve{ve_counter}"
            ve_counter += 1
            lump_v = {"name": f"{etype}-{uid}"}
            if etype == "money":
                lump_v["eco-info"] = ["eco-info", "(pickup-type money)", 1]
            elif etype == "buzzer":
                lump_v["eco-info"] = ["buzzer-info", "(game-task none)", 1]
            out.append({
                "trans":     [gx_v, gy_v, gz_v],
                "etype":     etype,
                "game_task": "(game-task none)",
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [gx_v, gy_v, gz_v, 3.0],
                "lump":      lump_v,
            })
        log(f"  [vertex-export] {o.name} → {len(verts)} × {etype} (modifiers applied)")
        o_eval.to_mesh_clear()  # free the temporary evaluated mesh

    # ── WATER_ mesh volumes ───────────────────────────────────────────────────
    # WATER_<name> meshes define swimmable water zones.  The mesh shape (any
    # scaled / rotated cube) drives the vol-control activation AABB.
    # Custom props on the mesh:
    #   og_water_surface  — world Y of the water surface (auto-set by sync op)
    #   og_water_wade     — depth in meters below surface (default 0.5)
    #   og_water_swim     — depth in meters below surface (default 1.0)
    #   og_water_bottom   — world Y of the kill floor
    #   og_water_attack   — damage type symbol string (default: 'drown)
    # All heights are absolute world Y (meters).  The vol planes are built from
    # the mesh AABB so rotation and non-uniform scale are fully supported.
    water_meshes = [o for o in level_objs
                    if o.type == "MESH" and o.name.startswith("WATER_")]
    for idx, o in enumerate(sorted(water_meshes, key=lambda x: x.name)):
        xmin, xmax, ymin, ymax, zmin, zmax, cx, cy, cz, _ = _vol_aabb(o)

        # Heights.
        # og_water_surface = absolute world Y of the water surface (defaults to mesh top)
        # og_water_wade    = depth in meters below surface where wading starts (default 0.5)
        # og_water_swim    = depth in meters below surface where swimming starts (default 1.0)
        # og_water_bottom  = absolute world Y of the kill floor (defaults to mesh bottom)
        #
        # Engine logic (water.gc):
        #   wade triggers when: jak_foot_y <= (surface - wade_depth)
        #   swim triggers when: jak_foot_y <= (surface - swim_depth)
        # So wade/swim are DEPTHS subtracted from surface — small positive values.
        surface    = float(o.get("og_water_surface", ymax))
        wade_depth = float(o.get("og_water_wade",    0.5))
        swim_depth = float(o.get("og_water_swim",    1.0))
        bottom     = float(o.get("og_water_bottom",  ymin))
        attack     = str(o.get("og_water_attack",    "drown"))

        # bsphere: XZ half-diagonal + 5m padding so process is never culled
        bsph_r = round((((xmax-xmin)/2)**2 + ((ymax-ymin)/2)**2 + ((zmax-zmin)/2)**2)**0.5 + 5.0, 2)

        lump = {
            "name":         f"water-vol-{idx}",
            # 5-value form with explicit flags — REQUIRED because logior! wt23 always runs
            # before the (zero? flags) auto-set check, so wt02/wt03 must be set explicitly.
            "water-height": ["water-height", surface, wade_depth, swim_depth, "(water-flags wt02 wt03 wt05 wt22)"],
            "attack-event": f"'{attack}",
            "vol": [
                "vector-vol",
                # point-in-vol? returns #f when dot(P,N) - w > 0
                # So normals must point OUTWARD. Inside = negative side of each plane.
                [ 0,  1,  0,  surface ],   # top:   outward +Y, inside when P.y <= surface
                [ 0, -1,  0, -bottom  ],   # floor: outward -Y, inside when P.y >= bottom
                [ 1,  0,  0,  xmax    ],   # +X:    outward +X, inside when P.x <= xmax
                [-1,  0,  0, -xmin    ],   # -X:    outward -X, inside when P.x >= xmin
                [ 0,  0,  1,  zmax    ],   # +Z:    outward +Z, inside when P.z <= zmax
                [ 0,  0, -1, -zmin    ],   # -Z:    outward -Z, inside when P.z >= zmin
            ],
        }
        out.append({
            "trans":     [cx, cy, cz],
            "etype":     "water-vol",
            "game_task": "(game-task none)",
            "quat":      [0, 0, 0, 1],
            "vis_id":    0,
            "bsphere":   [cx, cy, cz, bsph_r],
            "lump":      lump,
        })
        log(f"  [water] {o.name}  surface={surface:.2f}m  wade={wade_depth}m  swim={swim_depth}m  bottom={bottom:.2f}m  box={xmax-xmin:.1f}x{zmax-zmin:.1f}m")
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
            # No Geometry sub-collection yet — fall back to all meshes in the level.
            # Exclude WATER_ volumes (invisible helpers, not renderable geometry).
            _HELPER_PREFIXES = ("WATER_", "VOL_", "CPVOL_", "NAVMESH_")
            export_objs = [o for o in _recursive_col_objects(level_col, exclude_no_export=True)
                           if o.type == "MESH"
                           and not any(o.name.startswith(p) for p in _HELPER_PREFIXES)]

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
        # Fallback: v1.1.0 behaviour — export entire scene, but exclude preview meshes
        prev_active   = ctx.view_layer.objects.active
        prev_selected = [o for o in ctx.scene.objects if o.select_get()]

        # Select everything except og_preview_mesh objects
        for o in ctx.scene.objects:
            o.select_set(False)
        export_objs = [o for o in ctx.scene.objects
                       if o.type == "MESH" and not o.get("og_preview_mesh")]
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

        for o in ctx.scene.objects:
            o.select_set(False)
        for o in prev_selected:
            o.select_set(True)
        ctx.view_layer.objects.active = prev_active

    log("Exported GLB")



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
