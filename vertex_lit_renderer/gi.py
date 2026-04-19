"""
gi.py — Progressive GI using Intel Embree via trimesh/embreex

Architecture:
  OLD: one Python call per ray → GIL held → ~1000 rays/sec
  NEW: all rays for a pass fired as one numpy batch → GIL released during
       C-level traversal → Embree uses TBB internally for multi-core

Install: embreex + trimesh are pip-installed at addon register if absent.
Fallback: silently falls back to Blender BVHTree if install fails.
"""

import threading, time, math, random, subprocess, sys
import numpy as np

# ── Dependency bootstrap ──────────────────────────────────────────────────────

_EMBREE_READY   = False
_EMBREE_CHECKED = False

def ensure_embree():
    global _EMBREE_READY, _EMBREE_CHECKED
    if _EMBREE_CHECKED:
        return _EMBREE_READY
    _EMBREE_CHECKED = True
    try:
        import trimesh, embreex, trimesh.ray.ray_pyembree  # noqa
        _EMBREE_READY = True
        print("[VertexLit] embreex backend ready")
        return True
    except ImportError:
        pass
    print("[VertexLit] Installing trimesh + embreex (first run only)…")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "trimesh", "embreex", "--quiet", "--break-system-packages"],
            timeout=120)
    except Exception as e:
        print(f"[VertexLit] pip install failed ({e}), using BVHTree fallback")
        return False
    # Verify import works after install
    try:
        import trimesh, embreex, trimesh.ray.ray_pyembree  # noqa
        _EMBREE_READY = True
        print("[VertexLit] embreex installed and ready — will use on next render view entry")
    except Exception as e:
        print(f"[VertexLit] embreex import failed after install ({e}), using BVHTree")
        _EMBREE_READY = False
    return _EMBREE_READY


# ── Embree scene builder ──────────────────────────────────────────────────────

def _build_embree_intersector(raw_bvh):
    try:
        import trimesh
        from trimesh.ray.ray_pyembree import RayMeshIntersector
        verts  = np.array(raw_bvh['verts'],  dtype=np.float64)
        faces  = np.array(raw_bvh['polys'],  dtype=np.int32)
        albedo = np.array([[a[0],a[1],a[2]] for a in raw_bvh['albedo']], dtype=np.float64)
        mesh   = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        isect  = RayMeshIntersector(mesh, scale_to_box=False)
        print(f"[VertexLit] Embree scene: {len(verts)} verts, {len(faces)} tris")
        return isect, albedo, mesh.face_normals.copy()
    except Exception as e:
        print(f"[VertexLit] Embree scene build failed ({e}), using BVHTree")
        return None, None, None


# ── BVHTree fallback ──────────────────────────────────────────────────────────

try:
    from mathutils.bvhtree import BVHTree
    _BVHTREE_OK = True
except ImportError:
    _BVHTREE_OK = False

def _build_bvh_fallback(raw_bvh):
    if not _BVHTREE_OK: return None, []
    return BVHTree.FromPolygons(raw_bvh['verts'], raw_bvh['polys'], epsilon=1e-6), raw_bvh['albedo']


# ── Vectorized hemisphere batch ───────────────────────────────────────────────

def _hemisphere_batch(origins, normals, n_samples):
    """Cosine-weighted hemisphere rays for all verts × n_samples. Pure numpy."""
    n, N, BIAS = len(origins), len(origins)*n_samples, 0.003
    orig_r = np.repeat(origins, n_samples, axis=0)
    norm_r = np.repeat(normals, n_samples, axis=0)
    cos_t  = np.sqrt(np.random.uniform(0.0, 1.0, N))
    phi    = np.random.uniform(0.0, 2*np.pi, N)
    sin_t  = np.sqrt(np.maximum(0.0, 1.0 - cos_t**2))
    local  = np.stack([sin_t*np.cos(phi), sin_t*np.sin(phi), cos_t], axis=1)
    up     = np.where(np.abs(norm_r[:,0:1]) < 0.9,
                      np.tile([1.,0.,0.], (N,1)),
                      np.tile([0.,1.,0.], (N,1)))
    tangent = np.cross(norm_r, up)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True) + 1e-8
    bitan   = np.cross(norm_r, tangent)
    dirs = local[:,0:1]*tangent + local[:,1:2]*bitan + local[:,2:3]*norm_r
    return orig_r + norm_r*BIAS, dirs


# ── Vectorized GI pass ────────────────────────────────────────────────────────

def _gi_pass_embree(origins, normals, lights, intersector,
                    face_albedo_arr, face_normals_arr, n_samp, stop_event):
    """One GI pass — fires three batches of rays:
      1. Hemisphere bounce rays from all source vertices
      2. Shadow rays from bounce hit points → indirect colour
      3. Shadow rays from source vertices → ray-traced direct lighting

    Returns per-vertex (direct_shadowed + indirect_bounce) — raw sum,
    averaged by ProgressiveGI._count in get_update(). Direct is
    deterministic so averaging it is a no-op; bounce converges over passes.
    """
    BIAS      = 0.01    # 1cm — robust against scene-scale self-intersection
    MIN_DIST  = BIAS * 2   # discard hits closer than this (self-hit)
    n_verts = len(origins)
    contrib = np.zeros((n_verts, 3))

    if stop_event.is_set(): return contrib

    # ── 1. Hemisphere bounce rays ─────────────────────────────────────────
    ray_o, ray_d = _hemisphere_batch(origins, normals, n_samp)
    if stop_event.is_set(): return contrib

    try:
        hit_locs, hit_ray_idx, hit_tri_idx = intersector.intersects_location(
            ray_o, ray_d, multiple_hits=False)
    except Exception as e:
        print(f"[VertexLit] Embree bounce error: {e}")
        return contrib

    # ── 2. Shadow + direct at bounce hit points (indirect GI) ────────────
    if len(hit_locs) > 0 and not stop_event.is_set():
        # Discard self-intersections: hits too close to their ray origin
        hit_dist = np.linalg.norm(hit_locs - ray_o[hit_ray_idx], axis=1)
        valid    = hit_dist > MIN_DIST
        if not np.any(valid):
            hit_locs = np.zeros((0,3)); hit_ray_idx = np.array([], dtype=np.int64)
            hit_tri_idx = np.array([], dtype=np.int64)
        else:
            hit_locs, hit_ray_idx, hit_tri_idx = (
                hit_locs[valid], hit_ray_idx[valid], hit_tri_idx[valid])

    if len(hit_locs) > 0 and not stop_event.is_set():
        hit_albedo    = face_albedo_arr[hit_tri_idx]
        hit_face_norm = face_normals_arr[hit_tri_idx]
        bounce_color  = np.zeros((len(hit_locs), 3))

        for light in lights:
            if stop_event.is_set(): break
            lcolor, ltype, to_ln_h, atten_h, dist_h = _light_vectors(
                light, hit_locs, len(hit_locs))
            if to_ln_h is None: continue
            ndotl_h = np.maximum(0.0, np.einsum('ij,ij->i', hit_face_norm, to_ln_h))
            sh_o = hit_locs + to_ln_h * BIAS
            occ  = _shadow_test(intersector, sh_o, to_ln_h, dist_h)
            lit  = (~occ).astype(np.float64) * ndotl_h * atten_h
            bounce_color += lcolor * lit[:,None]

        np.add.at(contrib, hit_ray_idx // n_samp, hit_albedo * bounce_color)

    if stop_event.is_set(): return contrib

    # ── 3. Ray-traced direct lighting at source vertices ─────────────────
    # Shadow rays from every vertex → replaces the old shadow map entirely.
    # Direct is deterministic; averaging over passes = same value each time.
    sh_bias_o = origins + normals * BIAS
    direct    = np.zeros((n_verts, 3))

    for light in lights:
        if stop_event.is_set(): break
        lcolor, ltype, to_ln_v, atten_v, dist_v = _light_vectors(
            light, origins, n_verts)
        if to_ln_v is None: continue
        ndotl_v = np.maximum(0.0, np.einsum('ij,ij->i', normals, to_ln_v))
        occ     = _shadow_test(intersector, sh_bias_o, to_ln_v, dist_v)
        lit     = (~occ).astype(np.float64) * ndotl_v * atten_v
        direct += lcolor * lit[:,None]

    # Repeat direct n_samp times so averaging (_count += n_samp) gives
    # the correct value: avg(direct×n_samp) = direct ✓
    contrib += direct * n_samp

    return contrib  # raw sum — get_update() divides by _count


def _light_vectors(light, points, n):
    """Return (color, type, to_light_normalized, attenuation, distance) arrays."""
    lcolor = np.array(light['color']) * float(light['energy'])
    ltype  = int(light['type'])
    if ltype == 0:
        to_l  = np.array(light['pos']) - points
        dist2 = np.einsum('ij,ij->i', to_l, to_l)
        dist  = np.sqrt(dist2) + 1e-8
        to_ln = to_l / dist[:,None]
        atten = 1.0 / (dist2 + 1e-4)
    elif ltype == 1:
        d     = -np.array(light['dir']); d /= np.linalg.norm(d) + 1e-8
        to_ln = np.tile(d, (n, 1))
        atten = np.ones(n)
        dist  = np.full(n, 1e6)
    else:
        return lcolor, ltype, None, None, None
    return lcolor, ltype, to_ln, atten, dist


def _shadow_test(intersector, origins, directions, max_dist):
    """Returns bool array (n,): True = occluded."""
    n        = len(origins)
    occluded = np.zeros(n, dtype=bool)
    try:
        sh_locs, sh_ray_idx, _ = intersector.intersects_location(
            origins, directions, multiple_hits=False)
    except Exception:
        return occluded
    if len(sh_locs) > 0:
        sh_dist = np.linalg.norm(sh_locs - origins[sh_ray_idx], axis=1)
        blocked = sh_ray_idx[sh_dist < max_dist[sh_ray_idx]]
        occluded[blocked] = True
    return occluded


# ── BVHTree fallback helpers ──────────────────────────────────────────────────

def _direct_at(px,py,pz,nx,ny,nz,lights,bvh,stop_event,bias=0.003):
    r=g=b=0.0
    for light in lights:
        if stop_event.is_set(): break
        ltype=int(light['type']); lr,lg,lb=light['color']; energy=float(light['energy'])
        if ltype==0:
            dx=light['pos'][0]-px; dy=light['pos'][1]-py; dz=light['pos'][2]-pz
            dist=math.sqrt(dx*dx+dy*dy+dz*dz)+1e-8
            dx/=dist; dy/=dist; dz/=dist
            ndl=max(0.0,nx*dx+ny*dy+nz*dz)
            if ndl<=0: continue
            atten=energy/(dist*dist+1e-4)
            hit=bvh.ray_cast((px+nx*bias,py+ny*bias,pz+nz*bias),(dx,dy,dz),dist-bias)
            if hit[0] is None: r+=lr*ndl*atten; g+=lg*ndl*atten; b+=lb*ndl*atten
        elif ltype==1:
            dx,dy,dz=[-v for v in light['dir']]
            dn=math.sqrt(dx*dx+dy*dy+dz*dz)+1e-8; dx/=dn; dy/=dn; dz/=dn
            ndl=max(0.0,nx*dx+ny*dy+nz*dz)
            if ndl<=0: continue
            hit=bvh.ray_cast((px+nx*bias,py+ny*bias,pz+nz*bias),(dx,dy,dz))
            if hit[0] is None: r+=lr*ndl*energy; g+=lg*ndl*energy; b+=lb*ndl*energy
    return r,g,b

def _one_sample_bvh(pos_t,norm_t,lights,bvh,face_albedo,stop_event,bias=0.003):
    px,py,pz=pos_t; nx,ny,nz=norm_t
    while True:
        rx=random.uniform(-1,1); ry=random.uniform(-1,1); rz=random.uniform(-1,1)
        rl=math.sqrt(rx*rx+ry*ry+rz*rz)
        if 1e-6<rl<1.0: break
    rx/=rl; ry/=rl; rz/=rl
    if rx*nx+ry*ny+rz*nz<0: rx=-rx; ry=-ry; rz=-rz
    if stop_event.is_set(): return 0.0,0.0,0.0
    hit=bvh.ray_cast((px+nx*bias,py+ny*bias,pz+nz*bias),(rx,ry,rz))
    if hit[0] is None: return 0.0,0.0,0.0
    fi=hit[3]
    if fi is None or fi>=len(face_albedo): return 0.0,0.0,0.0
    ar,ag,ab=face_albedo[fi]; hx,hy,hz=hit[0]; hn=hit[2]
    if hn is None: return 0.0,0.0,0.0
    hnx,hny,hnz=hn
    if stop_event.is_set(): return 0.0,0.0,0.0
    dr,dg,db=_direct_at(hx,hy,hz,hnx,hny,hnz,lights,bvh,stop_event)
    return ar*dr,ag*dg,ab*db


# ── ProgressiveGI ─────────────────────────────────────────────────────────────

class ProgressiveGI:
    def __init__(self):
        self._lock       = threading.Lock()
        self._gen        = 0
        self._accum      = {}
        self._count      = 0
        self._updated    = False
        self._stop       = threading.Event()
        self._thread     = None
        self._scene_data = None

    def start(self, scene_data, target_samples=64, preserve_existing=False):
        self._stop.set()
        new_stop = threading.Event()
        self._stop = new_stop
        with self._lock:
            self._gen += 1
            gen        = self._gen
            old_accum  = self._accum if preserve_existing else {}
            old_count  = self._count if preserve_existing else 0
            new_accum  = {}
            for name, verts in scene_data['verts'].items():
                n   = len(verts)
                old = old_accum.get(name)
                new_accum[name] = (old.copy() if old is not None and len(old)==n
                                   else np.zeros((n,3), dtype=np.float64))
            self._accum      = new_accum
            self._count      = old_count
            self._updated    = False
            self._scene_data = scene_data
        self._thread = threading.Thread(
            target=self._run, args=(scene_data,target_samples,new_stop,gen),
            daemon=True, name='VertexLit-GI')
        self._thread.start()

    def cancel(self):
        self._stop.set()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def has_update(self):
        with self._lock: return self._updated

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def get_update(self):
        with self._lock:
            self._updated = False
            if self._count == 0: return {}, 0
            result = {}
            for name, arr in self._accum.items():
                avg = arr / self._count
                result[name] = [
                    (min(float(avg[i,0]),20.0),
                     min(float(avg[i,1]),20.0),
                     min(float(avg[i,2]),20.0))
                    for i in range(len(avg))]
            return result, self._count

    def _run(self, scene_data, target_samples, stop_event, generation):
        raw    = scene_data.get('raw_bvh')
        lights = scene_data['lights']
        n_samp = int(scene_data.get('rays_per_pass', 4))

        use_embree = _EMBREE_READY and raw is not None
        intersector = face_albedo_arr = face_normals_arr = None

        if use_embree:
            intersector, face_albedo_arr, face_normals_arr = \
                _build_embree_intersector(raw)
            use_embree = intersector is not None

        if use_embree:
            self._run_embree(scene_data, target_samples, stop_event, generation,
                             lights, intersector, face_albedo_arr,
                             face_normals_arr, n_samp)
        else:
            bvh, fa = _build_bvh_fallback(raw) if raw else (None, [])
            if bvh:
                self._run_bvhtree(scene_data, target_samples, stop_event,
                                  generation, lights, bvh, fa, n_samp)
            else:
                print("[VertexLit] GI: no ray backend available")

    # Max verts per embreex call — keeps each C-level call under ~100ms so
    # the stop_event is checked frequently and free() join(0.5s) reliably lands.
    GI_CHUNK_VERTS = 3000

    def _run_embree(self, scene_data, target_samples, stop_event, generation,
                    lights, intersector, face_albedo_arr, face_normals_arr, n_samp):
        all_v, all_n, obj_ranges = self._flatten_verts(scene_data)
        if all_v is None: return
        n_total = len(all_v)
        print(f"[VertexLit] GI (embreex): {n_total} verts")

        while not stop_event.is_set():
            cf = np.zeros((n_total, 3), dtype=np.float64)

            # Process in chunks so stop_event is checked between each embreex call.
            # Each chunk fires at most GI_CHUNK_VERTS * n_samp rays — stays < 100ms.
            for chunk_start in range(0, n_total, self.GI_CHUNK_VERTS):
                if stop_event.is_set(): break
                chunk_end = min(chunk_start + self.GI_CHUNK_VERTS, n_total)
                chunk_cf = _gi_pass_embree(
                    all_v[chunk_start:chunk_end],
                    all_n[chunk_start:chunk_end],
                    lights, intersector, face_albedo_arr, face_normals_arr,
                    n_samp, stop_event)
                cf[chunk_start:chunk_end] = chunk_cf

            if stop_event.is_set(): break

            pass_data = {name: cf[s:e] for name,(s,e) in obj_ranges.items()}
            with self._lock:
                if self._gen != generation: return
                for name, contrib in pass_data.items():
                    if name in self._accum:
                        self._accum[name] += contrib
                self._count  += n_samp
                self._updated = True
            time.sleep(0.001)

    def _run_bvhtree(self, scene_data, target_samples, stop_event, generation,
                     lights, bvh, face_albedo, n_samp):
        SLEEP = float(scene_data.get('thread_pause', 0.001))
        while not stop_event.is_set():
            pass_data = {}
            for name, world_verts in scene_data['verts'].items():
                if stop_event.is_set(): break
                world_norms = scene_data['normals'][name]
                n_v = len(world_verts)
                contrib = np.zeros((n_v,3), dtype=np.float64)
                for vi in range(n_v):
                    if stop_event.is_set(): break
                    r=g=b=0.0
                    for _ in range(n_samp):
                        if stop_event.is_set(): break
                        sr,sg,sb=_one_sample_bvh(world_verts[vi],world_norms[vi],
                                                  lights,bvh,face_albedo,stop_event)
                        r+=sr; g+=sg; b+=sb
                    contrib[vi,0]=r; contrib[vi,1]=g; contrib[vi,2]=b
                    if vi&255==255: time.sleep(SLEEP)
                pass_data[name]=contrib
            if stop_event.is_set(): break
            with self._lock:
                if self._gen != generation: return
                for name, contrib in pass_data.items():
                    if name in self._accum: self._accum[name]+=contrib
                self._count  += n_samp
                self._updated = True

    @staticmethod
    def _flatten_verts(scene_data):
        vl=[]; nl=[]; obj_ranges={}; idx=0
        for name in scene_data['verts']:
            verts=scene_data['verts'][name]; norms=scene_data['normals'][name]
            n=len(verts); vl.extend(verts); nl.extend(norms)
            obj_ranges[name]=(idx,idx+n); idx+=n
        if idx==0: return None,None,None
        all_v=np.array(vl,dtype=np.float64)
        all_n=np.array(nl,dtype=np.float64)
        all_n/=np.linalg.norm(all_n,axis=1,keepdims=True)+1e-8
        return all_v,all_n,obj_ranges
