# vertex_lit_renderer/engine.py

import time
import bpy
import gpu
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from .shaders import MAIN_VERT, MAIN_FRAG
from .gi import ProgressiveGI

MAX_LIGHTS   = 8
MAX_BVH_TRIS = 50_000  # cap BVH tris so ray casts stay fast (< 1ms each)
                       # polygoniq/GeoNodes realized scenes can have 500k+ tris,
                       # making each ray cast take > 500ms and preventing threads
                       # from stopping within the join timeout — causing accumulation.
                       # GI only needs approximate geometry; subsampling is fine.

# Denoise neighbor count — number of nearest neighbors used by the bilateral
# filter. 8 is a good balance: enough to average out noise, few enough that
# the filter stays local and doesn't blur features.
DENOISE_K = 8

# scipy's cKDTree is ~3× faster than mathutils.kdtree for build+query on the
# scenes we see (low 100k verts). Used opportunistically if available.
try:
    from scipy.spatial import cKDTree as _scipy_kdtree
    _HAS_SCIPY_KDTREE = True
except ImportError:
    _HAS_SCIPY_KDTREE = False


def _build_neighbor_index(vert_co_local, K=DENOISE_K):
    """Build the (n_verts, K) int32 matrix of each vertex's K nearest
    neighbor indices, excluding self. Uses scipy.cKDTree when available
    (fast C query, single call), falls back to mathutils.KDTree otherwise
    (slower Python loop but always present in Blender)."""
    n_verts = len(vert_co_local)
    if n_verts <= K + 1:
        return None   # too small to bother
    if _HAS_SCIPY_KDTREE:
        tree = _scipy_kdtree(vert_co_local)
        _, idx = tree.query(vert_co_local, k=K + 1)
        return idx[:, 1:K + 1].astype(np.int32)   # drop self (column 0)
    # mathutils fallback
    tree = KDTree(n_verts)
    for i in range(n_verts):
        tree.insert(Vector(vert_co_local[i]), i)
    tree.balance()
    neighbors = np.zeros((n_verts, K), dtype=np.int32)
    for i in range(n_verts):
        co = vert_co_local[i]
        results = tree.find_n((float(co[0]), float(co[1]), float(co[2])), K + 1)
        # results[0] is self (dist=0); take K following
        for j in range(K):
            neighbors[i, j] = results[j + 1][1]
    return neighbors


def _bilateral_denoise(gi, normals, neighbors, strength):
    """Normal-weighted bilateral filter on per-vertex GI values.

    For each vertex v with K neighbors k[1..K]:
        w_k      = max(0, n_v · n_k) ** 4
        filtered = (Σ w_k · gi[k] + gi[v]) / (Σ w_k + 1)   (self weight = 1)
        output   = strength · filtered + (1 − strength) · gi[v]

    The power-4 normal weight kills any mixing across normal discontinuities
    (corners, creases, thin objects) — only flat regions see the filter.
    Strength is a scalar in [0, 1]; callers ramp it to zero as convergence
    completes so the final image is the exact raw result."""
    if strength <= 0.001 or neighbors is None:
        return gi
    gi_n    = gi[neighbors]              # (V, K, 3)
    norm_n  = normals[neighbors]         # (V, K, 3)
    n_dot   = np.einsum('vi,vki->vk', normals, norm_n)
    w_n     = np.maximum(0.0, n_dot) ** 4
    wsum    = w_n.sum(axis=1, keepdims=True) + 1.0
    filtered = (np.sum(w_n[..., None] * gi_n, axis=1) + gi) / wsum
    return strength * filtered + (1.0 - strength) * gi


# Object types we don't extract mesh data from. Anything NOT in this set may
# produce cachable geometry via the depsgraph evaluator (MESH directly, or
# CURVE/SURFACE/META/FONT converted to mesh by their evaluator). Empties have
# no geometry and are excluded to avoid scene-diff churn re-queueing them.
# Must stay in sync between scene-diff (view_update), view_draw's per-instance
# loop, and _rebuild_inner's extract loop.
_NON_GEOMETRY_OBJ_TYPES = ('LIGHT', 'CAMERA', 'ARMATURE', 'LATTICE',
                           'SPEAKER', 'LIGHT_PROBE', 'EMPTY')

# ── Shader singletons ─────────────────────────────────────────────────────────

_main_shader   = None

# ── Global GI singleton ───────────────────────────────────────────────────────
_global_gi: 'ProgressiveGI' = None

# ── Edit-mode dirty tracking ──────────────────────────────────────────────────
# depsgraph_update_post fires during edit mode (view_update does not).
# We collect dirty object names here; view_draw picks them up and does
# an incremental rebuild of just those objects.
_edit_dirty:      set   = set()
_edit_dirty_time: float = 0.0

# Light changes detected in depsgraph_update_post (more reliable than
# view_update, which in some sessions isn't called for light operations
# at all). view_draw picks this up with priority over _transform_dirty,
# since Blender tends to also fire transform updates on mesh dependents
# when lights change, and the transform path would otherwise win with
# the wrong decay value.
_lights_dirty:      bool  = False
_lights_dirty_time: float = 0.0

def _get_main_shader():
    global _main_shader
    if _main_shader is None:
        _main_shader = gpu.types.GPUShader(MAIN_VERT, MAIN_FRAG)
    return _main_shader

# ── GPU texture cache ─────────────────────────────────────────────────────────

_tex_cache:   dict = {}
_pixel_cache: dict = {}   # image.name → (np_array h×w×4, w, h) for GI sampling

def _invalidate_tex(name):
    _tex_cache.pop(name, None)

def _get_pixel_array(image):
    """Return (np_array, w, h) for CPU-side texture sampling in GI. Cached per image."""
    if image is None or not image.has_data: return None
    name = image.name
    if name not in _pixel_cache:
        w, h = image.size
        if w > 0 and h > 0:
            import numpy as _np
            arr = _np.array(image.pixels, dtype=_np.float32).reshape(h, w, 4)
            _pixel_cache[name] = (arr, w, h)
        else:
            _pixel_cache[name] = None
    return _pixel_cache.get(name)

def _get_gpu_tex(image):
    if image is None: return None
    if image.name not in _tex_cache:
        try:
            _tex_cache[image.name] = gpu.texture.from_image(image)
        except Exception as e:
            print(f"[VertexLit] tex error ({image.name}): {e}")
            _tex_cache[image.name] = None
    return _tex_cache[image.name]

def _find_base_texture(mat):
    if not mat or not mat.use_nodes: return None
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            sock = node.inputs.get('Base Color')
            if sock and sock.is_linked:
                src = sock.links[0].from_node
                if src.type == 'TEX_IMAGE' and src.image:
                    return src.image
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            return node.image
    return None

# ── Scene helpers ─────────────────────────────────────────────────────────────

def _collect_lights(depsgraph, energy_scale):
    lights=[]; ltype={'POINT':0,'SUN':1,'SPOT':0,'AREA':0}
    for inst in depsgraph.object_instances:
        obj=inst.object
        if obj.type!='LIGHT': continue
        ld=obj.data; mat=inst.matrix_world
        if ld.type=='SUN':
            energy=ld.energy*energy_scale*10.0; radius=1.0
        else:
            energy=ld.energy*energy_scale
            radius=float(ld.cutoff_distance) if getattr(ld,'use_custom_distance',False) else 20.0
        lights.append({
            'pos': tuple(mat.to_translation()),
            'dir': tuple(mat.to_3x3()@Vector((0,0,-1))),
            'color': (float(ld.color.r),float(ld.color.g),float(ld.color.b)),
            'energy': energy, 'type': ltype.get(ld.type,0),
            'radius': radius, 'is_sun': ld.type=='SUN',
            'matrix_world': mat.copy(),
            # Sun angular diameter (radians) for soft shadow jittering.
            # Default in Blender is ~0.2rad (~11.4°). Zero = hard shadow.
            'angle': float(getattr(ld, 'angle', 0.0)) if ld.type == 'SUN' else 0.0,
        })
        if len(lights)>=MAX_LIGHTS: break
    return lights

def _scene_bounds(depsgraph):
    INF=float('inf'); mn=[INF]*3; mx=[-INF]*3; any_mesh=False
    for inst in depsgraph.object_instances:
        if inst.object.type not in ('MESH','CURVE','SURFACE','META','FONT','EMPTY'): continue
        mat=inst.matrix_world
        try:
            for c in inst.object.bound_box:
                wc=mat@Vector(c)
                for i in range(3): mn[i]=min(mn[i],wc[i]); mx[i]=max(mx[i],wc[i])
            any_mesh=True
        except Exception: pass
    if not any_mesh: return Vector((0,0,0)),10.0
    center=Vector(((mn[0]+mx[0])*.5,(mn[1]+mx[1])*.5,(mn[2]+mx[2])*.5))
    return center,max(Vector((mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])).length*.5,1.0)

def _extract_mesh_data(obj, vp_dg):
    """
    Extract per-loop arrays from the evaluated mesh via foreach_get bulk reads.
    All hot-path arrays come back as numpy arrays — ~10-20x faster than the
    previous Python per-vertex/per-corner loops on large meshes.

    Return dict keys unchanged (downstream contract preserved), but array
    types change from Python lists of tuples to numpy arrays:
      - positions      (n_loops, 3) f32
      - normals        (n_loops, 3) f32 (corner normals if available, else vertex)
      - colors         (n_loops, 4) f32 (vertex color or face-default fallback)
      - uvs            (n_loops, 2) f32
      - vi_map         (n_loops,)   i32  — per-loop vertex index
      - vert_co_local  (n_verts, 3) f32
      - vert_no_local  (n_verts, 3) f32
      - texture, mat_diffuse, gi_face_albedo, gn_cast_shadow, n_verts : unchanged

    Previous attempt (reverted in commit 8fc0d9d) tripped on numpy float32
    scalars leaking into Python tuples fed to batch_for_shader. That path is
    gone now — attr_fill takes numpy arrays directly, so the type friction
    doesn't exist anymore.

    Per-attribute try/except falls back to a safe default if foreach_get
    fails on some weird mesh (rare). Catastrophic failure returns None, same
    as before.
    """
    try:
        eval_obj = obj.evaluated_get(vp_dg)
        if not eval_obj or not hasattr(eval_obj, 'data') or not eval_obj.data:
            return None
        mesh = eval_obj.data

        if not mesh.loop_triangles:
            try: mesh.calc_loop_triangles()
            except Exception: pass
        if not mesh.loop_triangles:
            return None

        n_verts       = len(mesh.vertices)
        n_tris        = len(mesh.loop_triangles)
        n_loops_total = len(mesh.loops)
        n_loops       = n_tris * 3

        # ── Per-vertex bulk reads ─────────────────────────────────────────
        vert_co_local = np.empty(n_verts * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', vert_co_local)
        vert_co_local = vert_co_local.reshape(n_verts, 3)

        vert_no_local = np.empty(n_verts * 3, dtype=np.float32)
        mesh.vertices.foreach_get('normal', vert_no_local)
        vert_no_local = vert_no_local.reshape(n_verts, 3)

        # ── Per-triangle bulk reads ───────────────────────────────────────
        tri_verts = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('vertices', tri_verts)
        tri_verts = tri_verts.reshape(n_tris, 3)

        tri_loops = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('loops', tri_loops)
        tri_loops = tri_loops.reshape(n_tris, 3)

        tri_mat = np.empty(n_tris, dtype=np.int32)
        mesh.loop_triangles.foreach_get('material_index', tri_mat)

        # ── Flat per-loop index arrays (used everywhere below) ────────────
        vi_map = tri_verts.ravel()              # (n_loops,) i32 — per-loop vertex idx
        loop_indices = tri_loops.ravel()        # (n_loops,) i32 — per-loop loop idx

        # ── Per-loop position (index vertex table by loop's vertex) ───────
        positions = vert_co_local[vi_map]       # (n_loops, 3) f32

        # ── Per-loop normal: corner normals if available, else vertex ─────
        normals = None
        try:
            cn_flat = np.empty(n_loops_total * 3, dtype=np.float32)
            mesh.corner_normals.foreach_get('vector', cn_flat)
            corner_normals_np = cn_flat.reshape(n_loops_total, 3)
            normals = corner_normals_np[loop_indices]
        except Exception:
            normals = vert_no_local[vi_map]

        # ── Materials → per-mat colors + per-triangle default ─────────────
        mat_list = [slot.material for slot in eval_obj.material_slots]
        if not mat_list:
            m = eval_obj.active_material
            mat_list = [m] if m else []

        def _mat_color(m):
            if m:
                c = m.diffuse_color
                return [float(c[0]), float(c[1]), float(c[2]), 1.0]
            return [1.0, 1.0, 1.0, 1.0]
        mat_colors = [_mat_color(m) for m in mat_list] or [[1.0, 1.0, 1.0, 1.0]]
        mat_colors_np = np.array(mat_colors, dtype=np.float32)

        # Clamp material indices into valid range, broadcast to per-loop (× 3).
        tri_mat_safe     = np.where(tri_mat < len(mat_colors_np), tri_mat, 0)
        face_colors      = mat_colors_np[tri_mat_safe]             # (n_tris, 4)
        default_per_loop = np.repeat(face_colors, 3, axis=0)       # (n_loops, 4)

        # ── Per-loop UV ───────────────────────────────────────────────────
        uv_layer = mesh.uv_layers.active
        if uv_layer and len(uv_layer.data) == n_loops_total:
            try:
                uv_flat = np.empty(n_loops_total * 2, dtype=np.float32)
                uv_layer.data.foreach_get('uv', uv_flat)
                uv_np = uv_flat.reshape(n_loops_total, 2)
                uvs = uv_np[loop_indices]                          # (n_loops, 2)
            except Exception:
                uvs = np.zeros((n_loops, 2), dtype=np.float32)
                uv_np = None
        else:
            uvs = np.zeros((n_loops, 2), dtype=np.float32)
            uv_np = None

        # ── Per-loop color: vertex color override if present, else default
        colors = default_per_loop
        if mesh.color_attributes:
            attr = None
            try: attr = mesh.color_attributes.active_color
            except Exception: pass
            if attr is None and len(mesh.color_attributes): attr = mesh.color_attributes[0]
            if attr and getattr(attr, 'data_type', '') in ('FLOAT_COLOR', 'BYTE_COLOR', ''):
                try:
                    n_data = len(attr.data)
                    c_flat = np.empty(n_data * 4, dtype=np.float32)
                    attr.data.foreach_get('color', c_flat)
                    c_np = c_flat.reshape(n_data, 4)
                    if attr.domain == 'POINT' and n_data == n_verts:
                        colors = c_np[vi_map]
                    elif attr.domain == 'CORNER' and n_data == n_loops_total:
                        colors = c_np[loop_indices]
                    # else: shape mismatch — keep default_per_loop
                except Exception:
                    pass

        # ── Texture (first textured material) ─────────────────────────────
        tex = None
        for m in mat_list:
            if m:
                t = _get_gpu_tex(_find_base_texture(m))
                if t: tex = t; break

        # ── GI face albedo (Python-side — texture sampling has edge cases
        # and is not the dominant cost; keeping it Python for safety). ─────
        default = mat_colors[0]
        _m0 = mat_list[0] if mat_list else None
        mat_diffuse = (float(_m0.diffuse_color[0]), float(_m0.diffuse_color[1]),
                       float(_m0.diffuse_color[2])) if _m0 else (0.8, 0.8, 0.8)

        gi_face_albedo = []
        for ti in range(n_tris):
            mi = int(tri_mat_safe[ti])
            face_default = mat_colors[mi] if mi < len(mat_colors) else default
            _fmat = mat_list[mi] if mi < len(mat_list) else None
            _fimg = _find_base_texture(_fmat) if _fmat else None
            _pd   = _get_pixel_array(_fimg) if (_fimg and uv_np is not None) else None
            if _pd:
                _arr, _w, _h = _pd
                l0, l1, l2 = tri_loops[ti]
                _u = (uv_np[l0,0] + uv_np[l1,0] + uv_np[l2,0]) / 3.0
                _v = (uv_np[l0,1] + uv_np[l1,1] + uv_np[l2,1]) / 3.0
                _u %= 1.0; _v %= 1.0
                _px = min(int(_u*_w), _w-1); _py = min(int(_v*_h), _h-1)
                gi_face_albedo.append((float(_arr[_py,_px,0]*face_default[0]),
                                       float(_arr[_py,_px,1]*face_default[1]),
                                       float(_arr[_py,_px,2]*face_default[2])))
            else:
                gi_face_albedo.append((face_default[0], face_default[1], face_default[2]))

        # ── cast_shadow GeoNodes named attribute ──────────────────────────
        gn_cast_shadow = None
        if mesh.attributes and 'vertex_lit_cast_shadow' in mesh.attributes:
            cs_attr = mesh.attributes['vertex_lit_cast_shadow']
            if cs_attr.data_type == 'BOOLEAN' and len(cs_attr.data) > 0:
                gn_cast_shadow = any(d.value for d in cs_attr.data)

        return dict(
            positions=positions, normals=normals, colors=colors,
            uvs=uvs, vi_map=vi_map, texture=tex, n_verts=n_verts,
            vert_co_local=vert_co_local, vert_no_local=vert_no_local,
            mat_diffuse=mat_diffuse,
            gi_face_albedo=gi_face_albedo,
            gn_cast_shadow=gn_cast_shadow,
        )

    except Exception as e:
        print(f"[VertexLit] extract error ({obj.name}): {e}")
        return None


def _build_bounce_vbo(n_loops, gi_per_vert, vi_map_np):
    """Build a fresh bounce VBO. Called on every GI update — Blender's Python
    GPU API only exposes STATIC-usage VBOs, which refuse attr_fill after their
    first draw ("Can't fill, static buffer already in use"). The workaround is
    to create a new VBO each time; at least the data is small (3 floats × n_loops)."""
    bounce_fmt = gpu.types.GPUVertFormat()
    bounce_fmt.attr_add(id="bounceColor", comp_type='F32', len=3, fetch_mode='FLOAT')
    bounce_vbo = gpu.types.GPUVertBuf(len=n_loops, format=bounce_fmt)
    if gi_per_vert is not None:
        if isinstance(gi_per_vert, np.ndarray):
            gi_np = gi_per_vert.astype(np.float32, copy=False)
        else:
            gi_np = np.asarray(gi_per_vert, dtype=np.float32)
        bounces = gi_np[vi_map_np]            # per-vertex → per-loop, numpy fancy index
    else:
        bounces = np.zeros((n_loops, 3), dtype=np.float32)
    bounce_vbo.attr_fill("bounceColor", bounces)
    return bounce_vbo


def _compose_batch(static_vbo, bounce_vbo):
    """Build a GPUBatch from a reusable static VBO + fresh bounce VBO."""
    batch = gpu.types.GPUBatch(type='TRIS', buf=static_vbo)
    batch.vertbuf_add(bounce_vbo)
    return batch


def _build_vbos_and_batch(cached, gi_per_vert=None):
    """Initial build for a mesh.
      - Static VBO  (position, normal, vertColor, texCoord) — uploaded ONCE
        and kept in the cache forever. Reused across every GI update with no
        re-upload.
      - Bounce VBO  (bounceColor) — rebuilt on every GI update via
        _build_bounce_vbo (Blender's STATIC-only Python API forces recreation).
      - Batch       — also rebuilt each update, but a batch is just a small
        container referencing the two VBOs.

    Returns (batch, static_vbo). Callers store static_vbo in _batch_dict so
    subsequent GI updates can build a new batch around it without re-uploading
    the static attributes.
    """
    vi_map  = cached['vi_map']
    n_v     = cached['n_verts']
    n_loops = len(vi_map)

    # ── Static VBO (reusable) ─────────────────────────────────────────────────
    static_fmt = gpu.types.GPUVertFormat()
    static_fmt.attr_add(id="position",  comp_type='F32', len=3, fetch_mode='FLOAT')
    static_fmt.attr_add(id="normal",    comp_type='F32', len=3, fetch_mode='FLOAT')
    static_fmt.attr_add(id="vertColor", comp_type='F32', len=4, fetch_mode='FLOAT')
    static_fmt.attr_add(id="texCoord",  comp_type='F32', len=2, fetch_mode='FLOAT')
    static_vbo = gpu.types.GPUVertBuf(len=n_loops, format=static_fmt)
    static_vbo.attr_fill("position",  cached['positions'])
    static_vbo.attr_fill("normal",    cached['normals'])
    static_vbo.attr_fill("vertColor", cached['colors'])
    static_vbo.attr_fill("texCoord",  cached['uvs'])

    # Cache the per-loop index lookup as numpy once; reused on every GI update.
    vi_map_np = cached.get('vi_map_np')
    if vi_map_np is None:
        vi_map_np = np.asarray(vi_map, dtype=np.int32)
        cached['vi_map_np'] = vi_map_np

    # ── Bounce VBO (first one; fresh one built each GI update) ─────────────────
    gi_for_build = gi_per_vert if (gi_per_vert is not None and len(gi_per_vert) == n_v) else None
    bounce_vbo = _build_bounce_vbo(n_loops, gi_for_build, vi_map_np)

    batch = _compose_batch(static_vbo, bounce_vbo)
    return batch, static_vbo


def _rebuild_batch_with_new_bounce(cached, static_vbo, gi_per_vert):
    """Hot path for GI updates: build a new bounce VBO + new batch.
    The static VBO is reused — its position/normal/color/uv data is NOT
    re-uploaded. Only the small bounce VBO hits the GPU.
    Returns the new batch, or None if gi data doesn't match the mesh."""
    if gi_per_vert is None: return None
    n_v = cached['n_verts']
    if len(gi_per_vert) != n_v: return None
    vi_map_np = cached.get('vi_map_np')
    if vi_map_np is None:
        vi_map_np = np.asarray(cached['vi_map'], dtype=np.int32)
        cached['vi_map_np'] = vi_map_np
    n_loops = len(cached['vi_map'])
    try:
        bounce_vbo = _build_bounce_vbo(n_loops, gi_per_vert, vi_map_np)
        return _compose_batch(static_vbo, bounce_vbo)
    except Exception as e:
        print(f"[VertexLit] bounce rebuild failed: {e}")
        return None


def _build_raw_bvh_data(mesh_cache, objects):
    """Returns raw vert/poly data for GI thread to build BVH — no main-thread hitch.

    World-space vertex transform is vectorized with numpy matmul: a 30k-vert
    cliff goes from a Python-level per-vertex loop to one matmul call.
    Poly indexing is also numpy (reshape vi_map to (T,3) and add offset)."""
    vert_chunks = []
    poly_chunks = []
    face_albedo = []
    v_offset    = 0

    for name, data in mesh_cache.items():
        obj = objects.get(name)
        if obj is None: continue
        # GeoNodes attribute takes priority; fall back to Object property
        gn_cs = data.get('gn_cast_shadow')
        if gn_cs is not None:
            if not gn_cs: continue
        elif not getattr(obj, 'vertex_lit_cast_shadow', True):
            continue

        # local -> world via numpy matmul (vectorized across all verts)
        local = data['vert_co_local']                               # (N, 3) f32
        if not isinstance(local, np.ndarray):
            local = np.asarray(local, dtype=np.float32)
        mat = np.asarray(obj.matrix_world, dtype=np.float32)        # (4, 4)
        world = local @ mat[:3, :3].T + mat[:3, 3]                  # (N, 3)
        vert_chunks.append(world)

        # Polys: vi_map is (n_loops,); reshape to (T, 3) and offset
        vi_map = data['vi_map']
        if not isinstance(vi_map, np.ndarray):
            vi_map = np.asarray(vi_map, dtype=np.int32)
        tri_verts = vi_map.reshape(-1, 3) + v_offset                 # (T, 3) i32
        poly_chunks.append(tri_verts)

        # Face albedo stays Python-list (variable-length per mesh; fast enough)
        n_tris = tri_verts.shape[0]
        gfa = data.get('gi_face_albedo') or [data['mat_diffuse']] * n_tris
        for fi in range(n_tris):
            face_albedo.append(gfa[fi] if fi < len(gfa) else data['mat_diffuse'])

        v_offset += local.shape[0]

    if not vert_chunks: return None

    all_verts = np.concatenate(vert_chunks, axis=0)                  # (total_V, 3)
    all_polys = np.concatenate(poly_chunks, axis=0)                  # (total_T, 3)

    # Subsample if over cap
    if all_polys.shape[0] > MAX_BVH_TRIS:
        step = max(1, all_polys.shape[0] // MAX_BVH_TRIS)
        all_polys   = all_polys[::step]
        face_albedo = face_albedo[::step]
        print(f"[VertexLit] BVH subsampled to {all_polys.shape[0]} tris (step={step})")

    return {'verts': all_verts, 'polys': all_polys, 'albedo': face_albedo}

# ── Render Engine ─────────────────────────────────────────────────────────────

class VertexLitEngine(bpy.types.RenderEngine):
    bl_idname='VERTEX_LIT'; bl_label='Vertex Lit'; bl_use_preview=False

    def _ensure_state(self):
        if getattr(self,'_state_ready',False): return
        self._dirty            = True
        self._mesh_cache       = {}
        self._batch_dict       = {}
        self._white_tex        = None
        # GI is managed via module-level _global_gi, not per-engine instance
        self._lights_cache     = []
        self._bounds_cache     = (Vector((0,0,0)),10.0)
        self._gi_preserve      = False
        self._gi_has_data      = False
        self._transform_dirty  = False
        self._transform_time   = 0.0
        self._light_dirty      = False
        self._light_dirty_time = 0.0
        self._last_light_poll_time = 0.0
        self._light_fp_cache   = None
        self._state_ready      = True

    def _ensure_resources(self):
        if self._white_tex is None:
            self._white_tex=gpu.types.GPUTexture((1,1),format='RGBA8')

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def update(self, data=None, depsgraph=None):
        global _global_gi
        if _global_gi is not None: _global_gi.cancel()

    def render(self, depsgraph):
        global _global_gi
        if _global_gi is not None: _global_gi.cancel()

    def free(self):
        """Explicitly release all resources — don't rely on GC for GPU objects."""
        global _global_gi
        if _global_gi is not None:
            # cancel() sets stop flag; join(0.5) gives the thread time to finish
            # its current chunk and exit. With chunked embreex calls each chunk
            # is < 100ms, so 0.5s is more than enough to confirm a clean stop.
            _global_gi.cancel()
            if _global_gi._thread and _global_gi._thread.is_alive():
                _global_gi._thread.join(timeout=0.5)
        self._batch_dict       = {}
        self._mesh_cache       = {}
        self._white_tex        = None
        self._state_ready      = False  # force re-init on next use

    # ── Defensive light-change detection ──────────────────────────────────

    def _lights_cmp_fingerprint(self, depsgraph):
        """Stable fingerprint of all lights for change detection.
        Iterates bpy.data.objects directly (not depsgraph.object_instances)
        — avoids walking every scatter/GeoNodes instance each 0.2s just to
        find a handful of lights. Uses base-object transforms, deterministic
        under FP drift. Includes sun angle + shadow_soft_size so changes to
        those also fire a GI restart."""
        fp = {}
        for obj in bpy.data.objects:
            if obj.type != 'LIGHT': continue
            if obj.hide_render: continue
            if len(fp) >= MAX_LIGHTS: break
            ld = obj.data
            angle = round(float(getattr(ld, 'angle', 0.0)), 6)
            soft_size = round(float(getattr(ld, 'shadow_soft_size', 0.0)), 6)
            fp[obj.name] = (
                tuple(round(x, 5) for x in obj.location),
                tuple(round(x, 5) for x in obj.rotation_euler),
                round(float(ld.energy), 6),
                (round(float(ld.color.r), 6),
                 round(float(ld.color.g), 6),
                 round(float(ld.color.b), 6)),
                angle, soft_size,
            )
        return fp

    def _lights_differ(self, depsgraph):
        """True if lights changed since the last call. First call populates
        the cache and returns False (so we don't spuriously fire _light_dirty
        immediately after a rebuild)."""
        try:
            fp = self._lights_cmp_fingerprint(depsgraph)
        except Exception as e:
            print(f"[VertexLit] lights_differ error: {e}")
            return False
        old = getattr(self, '_light_fp_cache', None)
        if old is None:
            self._light_fp_cache = fp
            return False
        if fp != old:
            self._light_fp_cache = fp
            return True
        return False

    # ── view_update ───────────────────────────────────────────────────────

    def view_update(self, context, depsgraph):
        self._ensure_state()
        global _edit_dirty, _edit_dirty_time

        # Global edit-mode pause: mirrors _edit_depsgraph_post. view_update
        # also fires for depsgraph dependents (scatter objects re-evaluating
        # because their source is being edited, modifier-chain downstream,
        # etc.) — and its geometry/mesh/transform branches would otherwise
        # queue rebuilds for them. Returning early here keeps the pause
        # genuinely global.
        active = getattr(bpy.context, 'active_object', None)
        if active is not None and active.mode != 'OBJECT':
            return

        # ── Scene membership diff ─────────────────────────────────────────
        # Compare depsgraph object_instances vs _mesh_cache to catch:
        #   - Deletions: was in cache, no longer in depsgraph. Pop from caches
        #     and restart GI with remaining objects (decay=1.0 — other objects
        #     are unchanged; no grey flash from accumulator reset).
        #   - Additions: in depsgraph but not in cache. Includes unhides, which
        #     don't fire is_updated_geometry so the per-update loop below
        #     misses them. Queue into _edit_dirty for incremental rebuild.
        # Previously both paths went through the full-rebuild route (_dirty=
        # True, _gi_preserve=False) causing the delete hitch + grey screen,
        # and unhides effectively never reached this logic at all because
        # only the deletion case fired.
        if self._mesh_cache:
            current = {inst.object.name for inst in depsgraph.object_instances
                       if inst.object.type not in _NON_GEOMETRY_OBJ_TYPES}
            cache_keys = set(self._mesh_cache.keys())
            deleted = cache_keys - current
            added   = current - cache_keys

            if deleted or added:
                for name in deleted:
                    self._mesh_cache.pop(name, None)
                    self._batch_dict.pop(name, None)

                if added:
                    # Incremental rebuild picks these up next view_draw and
                    # calls _restart_gi_for_transforms with the fresh scene.
                    for name in added:
                        _edit_dirty.add(name)
                    _edit_dirty_time = time.time()
                elif deleted:
                    # Deletion only: restart GI immediately with decay=1.0
                    # so remaining objects keep their accumulated bounce data.
                    vls = getattr(context.scene, 'vertex_lit', None)
                    self._restart_gi_for_transforms(vls, decay=1.0)

                self.tag_redraw()
                return

        # ── Defensive light-state poll ────────────────────────────────────
        # Blender's depsgraph update flags for light transform/data changes
        # are inconsistent across versions and operator paths. Rather than
        # relying solely on is_updated_transform / is_updated_geometry in
        # the loop below (which the user has observed to miss sun rotations),
        # compare current light fingerprints against the cache. If anything
        # differs, set _light_dirty. The normal per-update loop continues
        # and may also set the same flag; set dedup makes that harmless.
        if self._lights_cache and self._lights_differ(depsgraph):
            self._light_dirty      = True
            self._light_dirty_time = time.time()
            self.tag_redraw()
            return

        for update in depsgraph.updates:
            id_data = update.id
            if update.is_updated_geometry:
                if isinstance(id_data, bpy.types.Mesh):
                    if getattr(id_data,'users',0) > 0:
                        self._dirty = True
                        self.tag_redraw(); return
                if isinstance(id_data, bpy.types.Object) and id_data.type == 'MESH':
                    if id_data.mode == 'EDIT':
                        pass  # handled by depsgraph_update_post → _incremental_rebuild
                    elif id_data.name in self._mesh_cache:
                        # Known object changed (including leaving edit mode) —
                        # incremental rebuild only, no full scene rebuild needed.
                        _edit_dirty.add(id_data.name)
                        _edit_dirty_time = time.time()
                        self.tag_redraw(); return
                    else:
                        # New object — incremental rebuild adds just this one
                        _edit_dirty.add(id_data.name)
                        _edit_dirty_time = time.time()
                        self.tag_redraw(); return
                if isinstance(id_data, bpy.types.Object) and id_data.type == 'LIGHT':
                    # Light energy/color/type changed on the object. No mesh
                    # re-extraction needed — just re-collect lights and restart
                    # GI. (Was previously _dirty=True which full-rebuilt
                    # everything for no reason.)
                    self._light_dirty      = True
                    self._light_dirty_time = time.time()
                    self.tag_redraw(); return
                if isinstance(id_data, bpy.types.Light):
                    # Light datablock change (color/energy/type via the data
                    # tab). Same handling — re-collect + GI restart.
                    self._light_dirty      = True
                    self._light_dirty_time = time.time()
                    self.tag_redraw(); return
            if isinstance(id_data, bpy.types.Material):
                self._dirty = True
                self.tag_redraw(); return
            if update.is_updated_transform and isinstance(id_data, bpy.types.Object):
                if id_data.type == 'LIGHT':
                    self._light_dirty      = True
                    self._light_dirty_time = time.time()
                    self.tag_redraw(); return
                elif id_data.type == 'MESH':
                    if id_data.name not in self._mesh_cache:
                        # Not in cache yet — new object being dragged (e.g. duplicate)
                        # needs extraction, not just a GI matrix update
                        _edit_dirty.add(id_data.name)
                        _edit_dirty_time = time.time()
                    else:
                        self._transform_dirty = True
                        self._transform_time  = time.time()
                    self.tag_redraw(); return
            if isinstance(id_data, bpy.types.Image):
                _invalidate_tex(id_data.name)

    # ── Rebuild ───────────────────────────────────────────────────────────

    def _rebuild(self, context, depsgraph, vls):
        self._rebuild_inner(context, depsgraph, vls)
        # No drain counter needed — we no longer mutate bpy.data,
        # so no deferred mesh-create/remove events will fire.

    def _rebuild_inner(self, context, depsgraph, vls):
        t0 = time.time()
        global _global_gi, _pixel_cache
        _pixel_cache = {}   # drop pixel arrays from previous state
        _global_gi.cancel()

        use_gi       = vls.use_gi          if vls else True
        gi_samp      = vls.gi_samples      if vls else 128
        rays_per_pass= vls.gi_rays_per_pass if vls else 4
        thread_pause = vls.gi_thread_pause  if vls else 0.001
        en_scale     = vls.energy_scale    if vls else 0.01

        # Use the VIEWPORT depsgraph — the render depsgraph excludes objects with
        # hide_render=True, which would make GeoNodes prototype objects invisible.
        try:
            vp_dg = context.evaluated_depsgraph_get()
        except Exception:
            vp_dg = depsgraph

        lights = _collect_lights(vp_dg, en_scale)
        self._lights_cache = lights
        self._bounds_cache = _scene_bounds(vp_dg)

        # Build new dicts atomically — replaces old ones completely so deleted
        # objects don't leave stale batch entries.
        new_mesh   = {}
        new_batch  = {}
        seen       = set()

        for inst in vp_dg.object_instances:
            obj = inst.object
            if obj.type in _NON_GEOMETRY_OBJ_TYPES:
                continue
            if obj.name in seen: continue
            seen.add(obj.name)

            data = _extract_mesh_data(obj, vp_dg)
            if data:
                new_mesh[obj.name]   = data
                batch, static_vbo    = _build_vbos_and_batch(data)
                new_batch[obj.name]  = (batch, static_vbo, data['texture'])

        # Atomic replacement.
        self._mesh_cache  = new_mesh
        self._batch_dict  = new_batch
        self._dirty       = False
        print(f"[VertexLit] rebuilt {len(new_mesh)} objs ({time.time()-t0:.2f}s)")

        if use_gi:
            bpy_objects = {name: bpy.data.objects.get(name) for name in new_mesh}
            raw_bvh = _build_raw_bvh_data(new_mesh, bpy_objects)
            if raw_bvh is None: return

            plain_lights = [{
                'pos':tuple(l['pos']),'dir':tuple(l['dir']),
                'color':tuple(l['color']),'energy':float(l['energy']),
                'type':int(l['type']),'radius':float(l['radius']),
            } for l in lights]

            gi_verts = {}
            gi_norms = {}
            for name, data in new_mesh.items():
                obj = bpy_objects.get(name)
                if obj is None: continue
                local_co = data['vert_co_local']
                local_no = data['vert_no_local']
                if not isinstance(local_co, np.ndarray):
                    local_co = np.asarray(local_co, dtype=np.float32)
                if not isinstance(local_no, np.ndarray):
                    local_no = np.asarray(local_no, dtype=np.float32)
                mat  = np.asarray(obj.matrix_world, dtype=np.float32)
                mat3 = mat[:3, :3]
                gi_verts[name] = local_co @ mat3.T + mat[:3, 3]
                gi_norms[name] = local_no @ mat3.T

            _global_gi.start(
                dict(raw_bvh=raw_bvh,lights=plain_lights,
                     verts=gi_verts,normals=gi_norms,
                     rays_per_pass=rays_per_pass,
                     thread_pause=thread_pause/1000.0,
),
                target_samples=gi_samp,
                preserve_existing=self._gi_preserve,
                decay=0.1 if self._gi_preserve else 1.0)
            self._gi_preserve=False
            print(f"[VertexLit] GI started ({gi_samp} samples)")

    # ── Apply GI ──────────────────────────────────────────────────────────

    def _apply_gi_update(self, gi_data, sample_count=0, target_samples=1):
        """Fast path for GI updates: rebuild each mesh's batch around its
        preserved static VBO with a new bounce VBO.

        The static VBO (position/normal/color/uv) stays alive in _batch_dict
        and is NOT re-uploaded. Only the small bounce VBO is uploaded fresh.
        Cheaper than the original 5-attribute rebuild in both allocation and
        GPU bandwidth.

        If the scene's `use_denoise` is on, GI values are bilaterally
        filtered before upload. Strength fades quadratically with
        convergence so at target_samples the filter is mathematically zero."""
        vls = getattr(bpy.context.scene, 'vertex_lit', None)
        denoise = bool(vls and getattr(vls, 'use_denoise', False))
        if denoise:
            remaining = max(0.0, 1.0 - float(sample_count) / max(1.0, float(target_samples)))
            strength  = (remaining * remaining) * float(getattr(vls, 'denoise_strength', 1.0))
        else:
            strength = 0.0

        any_applied = False
        for name, cached in self._mesh_cache.items():
            gv = gi_data.get(name)
            if gv is None: continue
            entry = self._batch_dict.get(name)
            if entry is None: continue
            _old_batch, static_vbo, tex = entry

            if strength > 0.001:
                # Lazy-build the neighbor index once per mesh and cache it.
                # A None result (mesh too small to denoise) is cached too, so
                # we don't retry the KD build every frame.
                if 'denoise_neighbors' not in cached:
                    cached['denoise_neighbors'] = _build_neighbor_index(cached['vert_co_local'])
                nbrs = cached['denoise_neighbors']
                if nbrs is not None:
                    gv = _bilateral_denoise(gv, cached['vert_no_local'], nbrs, strength)

            new_batch = _rebuild_batch_with_new_bounce(cached, static_vbo, gv)
            if new_batch is None: continue
            self._batch_dict[name] = (new_batch, static_vbo, tex)
            any_applied = True
        if any_applied:
            self._gi_has_data = True

    # ── Lightweight GI restart after transform ──────────────────────────────────────────────

    def _restart_gi_for_transforms(self, vls, decay=0.1):
        """Restart GI from cached geometry after a scene change.
        No bpy calls, no mesh extraction — just retransforms cached verts.

        Vectorized: each object's local->world transform is one numpy matmul
        across all verts instead of a Python loop.

        decay controls how much of the previous accumulation is kept:
          - 0.1 (default): quick fade. Good for moves/transforms where old
            bounce values are partly stale (occlusion changed).
          - 1.0: keep everything. Used for deletion — remaining objects'
            lighting is unchanged, only the shadow-caster set got smaller.
            Prevents the grey flash on delete."""
        if not self._mesh_cache: return
        bpy_objects = {name: bpy.data.objects.get(name) for name in self._mesh_cache}
        raw_bvh = _build_raw_bvh_data(self._mesh_cache, bpy_objects)
        if raw_bvh is None: return
        gi_verts = {}
        gi_norms = {}
        for name, data in self._mesh_cache.items():
            obj = bpy_objects.get(name)
            if obj is None: continue
            local_co = data['vert_co_local']
            local_no = data['vert_no_local']
            if not isinstance(local_co, np.ndarray):
                local_co = np.asarray(local_co, dtype=np.float32)
            if not isinstance(local_no, np.ndarray):
                local_no = np.asarray(local_no, dtype=np.float32)
            mat  = np.asarray(obj.matrix_world, dtype=np.float32)   # (4, 4)
            mat3 = mat[:3, :3]
            gi_verts[name] = local_co @ mat3.T + mat[:3, 3]         # world positions
            gi_norms[name] = local_no @ mat3.T                       # world normals (no translation)
        gi_samp = vls.gi_samples      if vls else 128
        rpp     = vls.gi_rays_per_pass if vls else 4
        pause   = (vls.gi_thread_pause if vls else 0.1) / 1000.0
        _global_gi.start(
            dict(raw_bvh=raw_bvh, lights=self._lights_cache,
                 verts=gi_verts, normals=gi_norms,
                 rays_per_pass=rpp, thread_pause=pause),
            target_samples=gi_samp, preserve_existing=True, decay=decay)


    # ── Incremental rebuild (edit mode) ──────────────────────────────────

    def _incremental_rebuild(self, dirty_names, context, depsgraph, vls):
        """Re-extract only the edited objects — main thread stays fast.
        GPU batch updates immediately; GI restarts in background thread."""
        try:
            vp_dg = context.evaluated_depsgraph_get()
        except Exception:
            vp_dg = depsgraph

        changed = False
        for name in dirty_names:
            obj = bpy.data.objects.get(name)
            if obj is None: continue
            new_data = _extract_mesh_data(obj, vp_dg)
            if new_data is None: continue
            self._mesh_cache[name] = new_data
            # Reuse existing GI if vertex count unchanged (most edits preserve topology)
            # Prevents the grey/dark flash while GI re-converges.
            gi_for_obj = None
            if _global_gi is not None:
                with _global_gi._lock:
                    old_gi = _global_gi._accum.get(name)
                    cnt    = max(_global_gi._count, 1)
                    if old_gi is not None and len(old_gi) == new_data["n_verts"]:
                        # Vectorized: avg + cap in one numpy expression, no Python loop
                        gi_for_obj = np.minimum(old_gi / cnt, 20.0).astype(np.float32)
            batch, static_vbo = _build_vbos_and_batch(new_data, gi_for_obj)
            self._batch_dict[name] = (batch, static_vbo, new_data["texture"])
            changed = True

        if changed:
            # GI thread rebuilds BVH from updated _mesh_cache and converges
            self._restart_gi_for_transforms(vls)
            self.tag_redraw()

    # ── Main draw ─────────────────────────────────────────────────────────

    def view_draw(self, context, depsgraph):
        self._ensure_state()
        self._ensure_resources()

        scene=depsgraph.scene
        vls=getattr(scene,'vertex_lit',None)

        # Priority: merge module-level _lights_dirty (from the depsgraph
        # handler) into the instance flag. The handler fires reliably for
        # all light changes; view_update's per-entry loop does not always.
        # Clearing _transform_dirty here prevents Blender's dependent-mesh
        # transform updates (which fire on light changes) from winning the
        # restart with the wrong decay value — the light path owns decay=0.
        global _lights_dirty, _lights_dirty_time
        if _lights_dirty:
            self._light_dirty      = True
            self._light_dirty_time = _lights_dirty_time
            _lights_dirty          = False
            # Drop any transform-dirty flag set by the same event's mesh
            # dependents — we're going to restart with decay=0 anyway.
            self._transform_dirty  = False

        # Defensive light-state poll runs every view_draw (throttled to 0.2s).
        # Backup for the depsgraph handler in case something exotic bypasses
        # it (collection instance lights, etc.).
        now = time.time()
        if (not self._light_dirty and self._lights_cache
                and (now - self._last_light_poll_time) > 0.2
                and self._lights_differ(depsgraph)):
            self._light_dirty      = True
            self._light_dirty_time = now
            print("[VertexLit] defensive poll: lights changed")
        self._last_light_poll_time = now

        if self._light_dirty and (time.time() - self._light_dirty_time) > 0.3:
            self._light_dirty = False
            en_scale = vls.energy_scale if vls else 1.0
            self._lights_cache = _collect_lights(depsgraph, en_scale)
            # decay=0: discard old accumulation — it was computed against the
            # old light direction/color/energy and would otherwise bias the
            # new result for hundreds of passes. Bounce VBOs retain their old
            # values during the brief window before first new pass publishes,
            # so no grey flash; lighting snaps to new state once it does.
            print(f"[VertexLit] light change -> GI restart (decay=0, {len(self._lights_cache)} lights)")
            self._restart_gi_for_transforms(vls, decay=0.0)

        # Edit-mode geometry changes — debounced 0.2s
        global _edit_dirty, _edit_dirty_time
        if _edit_dirty and (time.time() - _edit_dirty_time) > 0.2:
            dirty = _edit_dirty.copy()
            _edit_dirty.clear()
            print(f"[VertexLit] edit-dirty pickup: {len(dirty)} objects -> incremental rebuild")
            self._incremental_rebuild(dirty, context, depsgraph, vls)

        if self._transform_dirty and (time.time() - self._transform_time) > 0.3:
            self._transform_dirty = False
            print("[VertexLit] transform-dirty pickup -> GI restart (decay=0.1)")
            self._restart_gi_for_transforms(vls)

        if self._dirty:
            self._rebuild(context, depsgraph, vls)

        if _global_gi is not None:
            _global_gi.touch()   # signal viewport is active

        if _global_gi is not None and _global_gi.has_update():
            gi_data,n=_global_gi.get_update()
            target = int(vls.gi_samples) if vls else 128
            self._apply_gi_update(gi_data, sample_count=n, target_samples=target)
            print(f"[VertexLit] GI sample {n} applied")

        lights=self._lights_cache

        needs_redraw = _global_gi is not None and _global_gi.is_running
        if needs_redraw:
            self.tag_redraw()

        sky   =tuple(c*(vls.gi_bounce_strength if vls else 1.0)
                     for c in (tuple(vls.sky_color) if vls else (0.05,0.07,0.10)))
        ground=tuple(c*(vls.gi_bounce_strength if vls else 1.0)
                     for c in (tuple(vls.ground_color) if vls else (0.03,0.02,0.02)))
        bstr  =vls.gi_bounce_strength if vls else 1.0

        region=context.region; rv3d=context.region_data
        gpu.state.viewport_set(0,0,region.width,region.height)
        try:
            fb=gpu.state.active_framebuffer_get()
            wc=scene.world.color if scene.world else None
            fb.clear(color=(wc[0],wc[1],wc[2],1.0) if wc else (0.08,0.08,0.08,1.0),depth=1.0)
        except Exception as e: print(f"[VertexLit] clear: {e}")

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set('BACK')

        shader=_get_main_shader()
        view_proj=rv3d.window_matrix@rv3d.view_matrix
        shader.bind()
        shader.uniform_float('uViewProj',       view_proj)
        shader.uniform_float('uSkyColor',       sky)
        shader.uniform_float('uGroundColor',    ground)
        shader.uniform_float('uBounceStrength', bstr)
        shader.uniform_float('uHasGI', 1.0 if self._gi_has_data else 0.0)
        shader.uniform_int('uNumLights',        len(lights))
        for i in range(8):
            l=lights[i] if i<len(lights) else None
            try:
                shader.uniform_float(f'uLPos[{i}]',    tuple(l['pos'])  if l else (0,0,0))
                shader.uniform_float(f'uLDir[{i}]',    tuple(l['dir'])  if l else (0,0,-1))
                shader.uniform_float(f'uLCol[{i}]',    l['color']       if l else (0,0,0))
                shader.uniform_float(f'uLEnergy[{i}]', l['energy']      if l else 0.0)
                shader.uniform_int  (f'uLType[{i}]',   l['type']        if l else 0)
                shader.uniform_float(f'uLRadius[{i}]', l['radius']      if l else 1.0)
            except ValueError: pass

        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type in _NON_GEOMETRY_OBJ_TYPES:
                continue
            entry=self._batch_dict.get(obj.name)
            if entry is None: continue
            batch,_static_vbo,tex=entry
            shader.uniform_float('uModel',inst.matrix_world)
            try:   normal_mat=inst.matrix_world.to_3x3().inverted().transposed()
            except Exception: normal_mat=inst.matrix_world.to_3x3()
            shader.uniform_float('uNormalMat',normal_mat)
            shader.uniform_sampler('uAlbedo',  tex if tex is not None else self._white_tex)
            shader.uniform_int('uHasTexture',  1 if tex is not None else 0)
            batch.draw(shader)

        gpu.state.depth_test_set('NONE')
        gpu.state.face_culling_set('NONE')
        gpu.state.depth_mask_set(False)


# ── Edit-mode depsgraph handler ───────────────────────────────────────────────

@bpy.app.handlers.persistent
def _edit_depsgraph_post(scene, depsgraph):
    """Fires during edit mode and on edit-mode commit/exit.

    Global edit-mode pause: while the ACTIVE object is in any non-OBJECT
    mode (EDIT, SCULPT, POSE, PAINT_*, etc.), skip all queuing — including
    updates on other objects that re-evaluated as a side effect of the
    active object's state. This catches cases like:
      - Scatter / GeoNodes objects that reference a curve or mesh being edited
      - Meshes deformed by an armature being posed
      - Modifier chains where the upstream object is being sculpted

    Without the global check, dependents keep queueing while the user edits
    and produce hitches even though the active object's rebuild is correctly
    paused. On mode exit (active back to OBJECT), one catch-up rebuild fires
    for everything that's changed."""
    global _edit_dirty, _edit_dirty_time, _lights_dirty, _lights_dirty_time

    active = getattr(bpy.context, 'active_object', None)
    if active is not None and active.mode != 'OBJECT':
        return   # paused — anyone's dependents too

    for update in depsgraph.updates:
        id_data = update.id

        # ── Light detection (any update on a Light or LIGHT Object) ──────
        # Catches the case where view_update isn't being called for light
        # operations — the depsgraph_update_post handler fires reliably
        # for any scene change regardless of render engine callbacks.
        if isinstance(id_data, bpy.types.Light):
            _lights_dirty      = True
            _lights_dirty_time = time.time()
            continue
        if isinstance(id_data, bpy.types.Object) and id_data.type == 'LIGHT':
            if update.is_updated_transform or update.is_updated_geometry:
                _lights_dirty      = True
                _lights_dirty_time = time.time()
                continue

        # ── Edit-mode geometry (existing behavior) ───────────────────────
        if not update.is_updated_geometry: continue
        # Object-level update
        if isinstance(id_data, bpy.types.Object) and id_data.type == 'MESH':
            _edit_dirty.add(id_data.name)
            _edit_dirty_time = time.time()
        # Mesh data-block update fallback
        elif isinstance(id_data, bpy.types.Mesh):
            obj = getattr(bpy.context, 'active_object', None)
            if obj is None or obj.data != id_data: continue
            _edit_dirty.add(obj.name)
            _edit_dirty_time = time.time()


def register():
    global _global_gi
    bpy.utils.register_class(VertexLitEngine)
    _global_gi = ProgressiveGI()
    if _edit_depsgraph_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_edit_depsgraph_post)

def unregister():
    global _global_gi
    if _global_gi is not None:
        _global_gi.stop()
        _global_gi = None
    if _edit_depsgraph_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_edit_depsgraph_post)
    bpy.utils.unregister_class(VertexLitEngine)
