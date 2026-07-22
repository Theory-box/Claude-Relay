# vertex_lit_renderer/gi.py
"""
Progressive one-bounce GI via background thread.

One sample per vertex per thread pass.  Main thread polls has_update()
each view_draw and rebuilds only bounce colours — geometry stays cached.
Converges smoothly instead of hitching.
"""

import math
import random
import threading
import time
import numpy as np
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


# ── Pure-Python helpers (safe to call from background thread) ─────────────────

def _rand_hemi(nx, ny, nz):
    """Uniform hemisphere sample around (nx,ny,nz). Returns (dx,dy,dz)."""
    while True:
        x = random.uniform(-1.0, 1.0)
        y = random.uniform(-1.0, 1.0)
        z = random.uniform(-1.0, 1.0)
        r2 = x*x + y*y + z*z
        if 1e-10 < r2 <= 1.0:
            break
    s = 1.0 / math.sqrt(r2)
    dx, dy, dz = x*s, y*s, z*s
    if dx*nx + dy*ny + dz*nz < 0.0:
        dx, dy, dz = -dx, -dy, -dz
    return dx, dy, dz


def _direct_at(px, py, pz, nx, ny, nz, lights, bvh, bias=0.003):
    """Direct Lambert + shadow test at a point. Pure-tuple inputs, no bpy."""
    r = g = b = 0.0
    ox, oy, oz = px + nx*bias, py + ny*bias, pz + nz*bias

    for light in lights:
        if light['type'] == 1:                      # Sun
            lx, ly, lz = (-light['dir'][0],
                          -light['dir'][1],
                          -light['dir'][2])
            inv = 1.0 / max(math.sqrt(lx*lx + ly*ly + lz*lz), 1e-10)
            lx, ly, lz = lx*inv, ly*inv, lz*inv
            hit = bvh.ray_cast((ox,oy,oz), (lx,ly,lz))
            if hit[0]: continue                     # occluded
            diff = max(lx*nx + ly*ny + lz*nz, 0.0)
            e = light['energy'] * diff
            r += light['color'][0] * e
            g += light['color'][1] * e
            b += light['color'][2] * e
        else:                                       # Point / Spot
            dx = light['pos'][0]-px
            dy = light['pos'][1]-py
            dz = light['pos'][2]-pz
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist < 1e-5: continue
            inv = 1.0/dist
            lx, ly, lz = dx*inv, dy*inv, dz*inv
            hit = bvh.ray_cast((ox,oy,oz), (lx,ly,lz))
            if hit[0] and hit[3] is not None and hit[3] < dist - bias:
                continue
            x_r = dist / max(light['radius'], 0.001)
            att = max(1.0 - x_r*x_r*x_r*x_r, 0.0)**2
            diff = max(lx*nx + ly*ny + lz*nz, 0.0)
            e = light['energy'] * diff * att
            r += light['color'][0] * e
            g += light['color'][1] * e
            b += light['color'][2] * e

    return r, g, b


def _one_sample(pos_t, norm_t, lights, bvh, face_albedo, bias=0.003):
    """Single Monte Carlo bounce sample. Returns (r, g, b)."""
    nx, ny, nz = norm_t
    ln = math.sqrt(nx*nx + ny*ny + nz*nz)
    if ln < 1e-10:
        return 0.0, 0.0, 0.0
    nx, ny, nz = nx/ln, ny/ln, nz/ln

    px, py, pz = pos_t
    dx, dy, dz = _rand_hemi(nx, ny, nz)

    hit_loc, hit_norm, hit_idx, hit_dist = bvh.ray_cast(
        (px + nx*bias, py + ny*bias, pz + nz*bias),
        (dx, dy, dz),
    )
    if hit_loc is None or hit_dist is None or hit_dist < bias*2.0:
        return 0.0, 0.0, 0.0

    hnx, hny, hnz = hit_norm
    hl  = math.sqrt(hnx*hnx + hny*hny + hnz*hnz)
    if hl > 1e-10:
        hnx, hny, hnz = hnx/hl, hny/hl, hnz/hl

    dr, dg, db = _direct_at(
        hit_loc[0], hit_loc[1], hit_loc[2],
        hnx, hny, hnz,
        lights, bvh, bias)

    if hit_idx is not None and hit_idx < len(face_albedo):
        ar, ag, ab = face_albedo[hit_idx]
    else:
        ar = ag = ab = 0.8

    cos_in = max(dx*nx + dy*ny + dz*nz, 0.0)
    scale  = 2.0 * math.pi * cos_in   # hemisphere Monte Carlo factor

    return (min(dr*ar*scale, 20.0),
            min(dg*ag*scale, 20.0),
            min(db*ab*scale, 20.0))


# ── Scene BVH builder ─────────────────────────────────────────────────────────

def build_scene_bvh(depsgraph):
    """World-space BVH of all visible meshes + per-face albedo list."""
    all_verts   = []
    all_polys   = []
    face_albedo = []
    v_offset    = 0
    seen        = set()

    for inst in depsgraph.object_instances:
        obj = inst.object
        if obj.type != 'MESH' or obj.hide_get():
            continue
        if obj.name in seen:
            continue
        seen.add(obj.name)

        eval_obj = obj.evaluated_get(depsgraph)
        mesh     = bpy.data.meshes.new_from_object(
            eval_obj, preserve_all_data_layers=False, depsgraph=depsgraph)
        if not mesh:
            continue
        mat_w = inst.matrix_world

        for v in mesh.vertices:
            wv = mat_w @ v.co
            all_verts.append((wv.x, wv.y, wv.z))

        for poly in mesh.polygons:
            all_polys.append([i + v_offset for i in poly.vertices])
            mi = poly.material_index
            if mi < len(obj.material_slots) and obj.material_slots[mi].material:
                c = obj.material_slots[mi].material.diffuse_color
                face_albedo.append((float(c[0]), float(c[1]), float(c[2])))
            else:
                face_albedo.append((0.8, 0.8, 0.8))

        v_offset += len(mesh.vertices)
        bpy.data.meshes.remove(mesh)

    if not all_verts:
        return None, []

    bvh = BVHTree.FromPolygons(all_verts, all_polys, epsilon=1e-6)
    return bvh, face_albedo


# ── Progressive GI accumulator ────────────────────────────────────────────────

class ProgressiveGI:
    """
    Runs one-bounce GI in a background daemon thread.
    Each pass adds 1 sample per vertex.  Main thread polls has_update()
    and applies the averaged result without hitching.

    cancel() is non-blocking — it signals the thread to stop but doesn't
    wait.  stop() is the full blocking version used when freeing the engine.
    A generation counter ensures a cancelled thread's late writes are ignored.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._accum   = {}      # obj.name → np.ndarray(n, 3)
        self._count   = 0
        self._updated = False
        self._gen     = 0       # incremented on each start(); old writes discarded
        self._stop    = threading.Event()   # current thread's stop flag
        self._thread  = None

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def sample_count(self):
        return self._count

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def has_update(self):
        with self._lock:
            return self._updated

    def get_update(self):
        """Returns (dict obj.name→list[(r,g,b)], sample_count). Clears flag."""
        with self._lock:
            self._updated = False
            if self._count == 0:
                return {}, 0
            result = {}
            for name, arr in self._accum.items():
                avg = arr / self._count
                result[name] = [
                    (min(float(avg[i,0]),20.0),
                     min(float(avg[i,1]),20.0),
                     min(float(avg[i,2]),20.0))
                    for i in range(len(avg))
                ]
            return result, self._count

    def cancel(self):
        """Non-blocking: signal current thread to stop, return immediately."""
        self._stop.set()

    def stop(self):
        """Blocking: signal + join.  Use in free() / render() / update()."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def start(self, scene_data: dict, target_samples: int = 64):
        # Signal the old thread (if any) via its own stop event
        self._stop.set()

        # New stop event for the new thread — old thread keeps its reference
        new_stop = threading.Event()
        self._stop = new_stop

        # Bump generation so any stale late-write from old thread is discarded
        with self._lock:
            self._gen   += 1
            gen          = self._gen
            self._accum  = {
                name: np.zeros((len(verts), 3), dtype=np.float64)
                for name, verts in scene_data['verts'].items()
            }
            self._count   = 0
            self._updated = False

        self._thread = threading.Thread(
            target=self._run,
            args=(scene_data, target_samples, new_stop, gen),
            daemon=True,
            name='VertexLit-GI',
        )
        self._thread.start()

    # ── Background thread ─────────────────────────────────────────────────

    def _run(self, scene_data, target_samples, stop_event, generation):
        bvh         = scene_data['bvh']
        face_albedo = scene_data['face_albedo']
        lights      = scene_data['lights']

        while not stop_event.is_set() and self._count < target_samples:
            pass_data = {}

            for name, world_verts in scene_data['verts'].items():
                if stop_event.is_set():
                    break
                world_norms = scene_data['normals'][name]
                n_v         = len(world_verts)
                contrib     = np.zeros((n_v, 3), dtype=np.float64)

                for vi in range(n_v):
                    if stop_event.is_set():
                        break
                    r, g, b = _one_sample(
                        world_verts[vi], world_norms[vi],
                        lights, bvh, face_albedo)
                    contrib[vi, 0] = r
                    contrib[vi, 1] = g
                    contrib[vi, 2] = b
                    # Yield GIL every 64 vertices so Blender's main thread
                    # can run viewport redraws without stalling.
                    if vi & 63 == 63:
                        time.sleep(0)

                pass_data[name] = contrib

            if stop_event.is_set():
                break

            with self._lock:
                if self._gen != generation:
                    return          # superseded — discard
                for name, contrib in pass_data.items():
                    if name in self._accum:
                        self._accum[name] += contrib
                self._count  += 1
                self._updated = True
