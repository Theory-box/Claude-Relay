# vertex_lit_renderer/engine.py

import time
import threading
import os
import numpy as np
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d
from mathutils import Matrix, Vector

from .shaders import SHADOW_VERT, SHADOW_FRAG, PHONG_VERT, PHONG_FRAG, WORKBENCH_FRAG, ID_VERT, ID_FRAG, NORMAL_VERT, NORMAL_FRAG, VIEWMODE_FRAG, BG_VERT, BG_FRAG
from . import material_shader
from . import fx
import ctypes as _ct

# Persistent caches — survive engine instances (leaving/re-entering rendered view
# destroys the engine but NOT these). Re-entry reuses the extracted data AND the GPU
# batches, so unchanged objects need no work at all. A cheap signature detects changes
# made while away. If a persisted batch is ever stale (GPU context changed), drawing it
# raises and we self-heal by re-extracting that object. Cleared on unregister.
_PERSIST_MESH = {}     # obj name -> extraction data dict
_PERSIST_BATCH = {}    # obj name -> [(batch, material_name, texture), ...]
_PERSIST_SHADOW = {}   # obj name -> shadow batch
_PERSIST_SIG = {}      # obj name -> cheap geometry signature
_FORCE_REEXTRACT = False   # set when the chosen colour attribute changes -> full re-extract


def _area_resize(arr, W, H):
    """Area-average resize of an (h, w, 4) float image to (H, W, 4) — used to downscale a
    supersampled F12 render. Correct for any (including non-integer) ratio."""
    import numpy as _np
    sh, sw = arr.shape[0], arr.shape[1]
    if sw == W and sh == H:
        return arr

    def _axis(a, out):
        n = a.shape[0]
        cs = _np.zeros((n + 1,) + a.shape[1:], dtype=_np.float64)
        cs[1:] = _np.cumsum(a, axis=0)
        edges = _np.linspace(0.0, n, out + 1)

        def _cs_at(pos):
            p0 = _np.floor(pos).astype(int)
            frac = (pos - p0).reshape((-1,) + (1,) * (a.ndim - 1))
            p0c = _np.clip(p0, 0, n)
            p1c = _np.clip(p0 + 1, 0, n)
            return cs[p0c] + (cs[p1c] - cs[p0c]) * frac

        total = _cs_at(edges[1:]) - _cs_at(edges[:-1])
        widths = (edges[1:] - edges[:-1]).reshape((-1,) + (1,) * (a.ndim - 1))
        return (total / _np.maximum(widths, 1e-9)).astype(_np.float32)

    arr = _axis(arr, H)                                    # resample rows
    arr = _axis(arr.transpose(1, 0, 2), W).transpose(1, 0, 2)   # resample columns
    return arr


def _compute_sun(vls):
    """Sun params from Height (elevation) + Angle (azimuth): returns
    (dir_to_sun, colour, intensity, hemisphere_intensity)."""
    import math
    if vls is None:
        return ((0.0, 0.0, 1.0), (1.0, 1.0, 1.0), 0.0, 1.0)
    el = getattr(vls, 'sun_elevation', 0.785398)
    az = getattr(vls, 'sun_azimuth', 0.785398)
    ce = math.cos(el)
    d = (ce * math.sin(az), ce * math.cos(az), math.sin(el))   # direction TO the sun
    return (d, tuple(vls.sun_color), float(vls.sun_intensity),
            float(getattr(vls, 'hemi_intensity', 1.0)))


def _material_transparent(mat):
    """Decide at DRAW time whether a material is alpha-blended, from its CURRENT state (not a
    cached compile-time flag, which goes stale when the Alpha value is tweaked without a
    structural change). Blended -> yes; Opaque -> no; otherwise transparent only if the
    Principled Alpha is actually linked or < 1."""
    if mat is None:
        return False
    sr = getattr(mat, 'surface_render_method', None)
    bm = getattr(mat, 'blend_method', 'OPAQUE')
    if sr == 'BLENDED' or bm == 'BLEND':
        return True
    if sr == 'OPAQUE':
        return False
    nt = getattr(mat, 'node_tree', None)
    if nt is not None:
        for n in nt.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                a = n.inputs.get('Alpha')
                if a is not None:
                    if a.is_linked:
                        return True
                    try:
                        if float(a.default_value) < 0.999:
                            return True
                    except Exception:
                        pass
    return False


def _geo_sig(obj, mesh):
    """Cheap signature to detect whether an object's geometry changed while we weren't
    watching. Uses the ORIGINAL mesh name (stable across evaluations, unlike the temp
    evaluated mesh name), topology counts, modifier state, and a few sampled positions."""
    try:
        mods = tuple((m.type, bool(m.show_viewport)) for m in obj.modifiers)
        nv = len(mesh.vertices)
        s = 0.0
        if nv:
            vs = mesh.vertices
            for i in (0, nv // 2, nv - 1):
                c = vs[i].co; s += c.x * 1.1 + c.y * 2.3 + c.z * 3.7
        base = getattr(getattr(obj, 'data', None), 'name', '')   # stable original name
        return (base, nv, len(mesh.polygons), mods, round(s, 3))
    except Exception:
        return None


def _share_sig(obj, mesh, view_attr):
    """Key for geometry that can be SHARED across objects (e.g. linked duplicates): the
    geometry signature + material assignment + active colour attribute. Objects with the
    same key have identical evaluated geometry and materials, so one extraction + one GPU
    batch serves them all (drawn per-instance with their own matrices)."""
    try:
        mats = tuple((s.material.name if s.material else '') for s in obj.material_slots)
    except Exception:
        mats = ()
    return (_geo_sig(obj, mesh), mats, view_attr or '')


def _draw_key(inst):
    """Cache/draw key for a depsgraph instance. Normal objects key by their own name.
    GEOMETRY-NODES (and other) instances all report inst.object as the INSTANCER (whose own
    evaluated mesh is empty), but share the instanced geometry's mesh datablock — so key
    those by the mesh-data name ('i:<data>') and draw each with its instance matrix."""
    o = inst.object
    if getattr(inst, 'is_instance', False):
        d = getattr(o, 'data', None)
        if d is not None:
            return 'i:' + d.name
    return o.name


def _raw_attr(mesh, name, ctype, ncomp, count):
    """Read a mesh attribute as a numpy array DIRECTLY from Blender's contiguous
    memory (via the layer's pointer) — ~5x faster than foreach_get on the hot arrays.
    Returns an (count, ncomp) view or None (caller then uses the foreach_get fallback).
    Version-tolerant: any layout surprise -> None -> safe slow path."""
    try:
        a = mesh.attributes.get(name)
        if a is None: return None
        data = a.data
        if len(data) != count or count == 0: return None
        addr = data[0].as_pointer()
        arr = np.ctypeslib.as_array((ctype * (count * ncomp)).from_address(addr))
        return arr.reshape(count, ncomp) if ncomp > 1 else arr
    except Exception:
        return None


def _raw_corner_tris(mesh, n_tris):
    """Triangle -> 3 corner indices, read straight from the runtime corner-tris array."""
    try:
        if n_tris == 0: return None
        addr = mesh.loop_triangles[0].as_pointer()
        return np.ctypeslib.as_array((_ct.c_int * (n_tris * 3)).from_address(addr))
    except Exception:
        return None

MAX_LIGHTS = 8
_DEBUG = True   # prints "[VertexLit] rebuild <- ..." naming what triggers a rebuild

# ── GI redraw timer ───────────────────────────────────────────────────────────
# Backup for self.tag_redraw() — forces redraws at 20 fps while GI runs.
# Uses bpy.data (always valid in timers) not bpy.context (may be None).

_post_err_shown = False  # print the post-pipeline traceback only once

# ── Shader singletons ─────────────────────────────────────────────────────────

_shadow_shader = None
_main_shader   = {}   # shading mode -> GPUShader
_id_shader     = None  # object-id pass shader (outline)

def _get_shadow_shader():
    global _shadow_shader
    if _shadow_shader is None:
        _shadow_shader = gpu.types.GPUShader(SHADOW_VERT, SHADOW_FRAG)
    return _shadow_shader

def _get_id_shader():
    global _id_shader
    if _id_shader is None:
        _id_shader = gpu.types.GPUShader(ID_VERT, ID_FRAG)
    return _id_shader

_normal_shader = None
def _get_normal_shader():
    global _normal_shader
    if _normal_shader is None:
        _normal_shader = gpu.types.GPUShader(NORMAL_VERT, NORMAL_FRAG)
    return _normal_shader

_viewmode_shader = None
def _get_viewmode_shader():
    global _viewmode_shader
    if _viewmode_shader is None:
        _viewmode_shader = gpu.types.GPUShader(PHONG_VERT, VIEWMODE_FRAG)
    return _viewmode_shader

_bg_shader = None
_bg_batch = None
def _get_bg():
    global _bg_shader, _bg_batch
    if _bg_shader is None:
        from gpu_extras.batch import batch_for_shader
        _bg_shader = gpu.types.GPUShader(BG_VERT, BG_FRAG)
        _bg_batch = batch_for_shader(_bg_shader, 'TRIS',
                                     {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]})
    return _bg_shader, _bg_batch

_VIEWMODE_ID = {'SOLID': 1, 'RANDOM': 2, 'ATTRIBUTE': 3, 'NORMAL': 4, 'DEPTH': 5}

def _obj_random_color(name):
    """Stable pseudo-random colour per object (Blender-like), from the object name."""
    import hashlib
    h = hashlib.md5(name.encode('utf-8')).digest()
    return (0.15 + 0.8 * (h[0] / 255.0), 0.15 + 0.8 * (h[1] / 255.0), 0.15 + 0.8 * (h[2] / 255.0))

def _get_main_shader(mode='PIXEL'):
    sh = _main_shader.get(mode)
    if sh is None:
        if mode == 'WORKBENCH':
            sh = gpu.types.GPUShader(PHONG_VERT, WORKBENCH_FRAG)
        else:
            sh = gpu.types.GPUShader(PHONG_VERT, PHONG_FRAG)   # PIXEL (lit)
        _main_shader[mode] = sh
    return sh

# ── GPU texture cache ─────────────────────────────────────────────────────────

_tex_cache: dict = {}

def _invalidate_tex(name):
    _tex_cache.pop(name, None)

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

# ── Shadow map ────────────────────────────────────────────────────────────────

class _ShadowMap:
    def __init__(self, size):
        self.size=0; self.tex=None; self.fb=None; self.resize(size)
    def resize(self, size):
        if self.size==size: return
        self.size=size
        self.tex=gpu.types.GPUTexture((size,size),format='DEPTH_COMPONENT32F')
        try: self.fb=gpu.types.GPUFrameBuffer(depth_slot=self.tex)
        except Exception:
            d=gpu.types.GPUTexture((size,size),format='RGBA8')
            self.fb=gpu.types.GPUFrameBuffer(color_slots=[d],depth_slot=self.tex)

_shadow_map=None
def _get_shadow_map(size):
    global _shadow_map
    if _shadow_map is None: _shadow_map=_ShadowMap(size)
    else: _shadow_map.resize(size)
    return _shadow_map

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
        })
        if len(lights)>=MAX_LIGHTS: break
    return lights

def _scene_bounds(depsgraph):
    INF=float('inf'); mn=[INF]*3; mx=[-INF]*3; any_mesh=False
    for inst in depsgraph.object_instances:
        if inst.object.type!='MESH': continue
        mat=inst.matrix_world
        for c in inst.object.bound_box:
            wc=mat@Vector(c)
            for i in range(3): mn[i]=min(mn[i],wc[i]); mx[i]=max(mx[i],wc[i])
        any_mesh=True
    if not any_mesh: return Vector((0,0,0)),10.0
    center=Vector(((mn[0]+mx[0])*.5,(mn[1]+mx[1])*.5,(mn[2]+mx[2])*.5))
    return center,max(Vector((mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])).length*.5,1.0)

def _build_light_space(light,center,radius):
    mat=light['matrix_world']; ldir=(mat.to_3x3()@Vector((0,0,-1))).normalized()
    eye=center-ldir*radius*2.5; fwd=(center-eye).normalized()
    up=Vector((0,1,0))
    if abs(fwd.dot(up))>.99: up=Vector((1,0,0))
    r_v=fwd.cross(up).normalized(); u_v=r_v.cross(fwd)
    view=Matrix([[r_v.x,r_v.y,r_v.z,-r_v.dot(eye)],
                 [u_v.x,u_v.y,u_v.z,-u_v.dot(eye)],
                 [-fwd.x,-fwd.y,-fwd.z,fwd.dot(eye)],[0,0,0,1]])
    s=radius*1.6; n=0.1; f=radius*6.0
    ortho=Matrix([[1/s,0,0,0],[0,1/s,0,0],[0,0,-2/(f-n),-(f+n)/(f-n)],[0,0,0,1]])
    return ortho@view


def _build_light_space_dir(sun_dir, center, radius):
    """Ortho light-space matrix for the objectless directional sun. sun_dir is the direction
    TO the sun; the light shines along -sun_dir, covering the scene bounds."""
    ldir = -Vector(sun_dir)
    if ldir.length < 1e-6:
        ldir = Vector((0.0, 0.0, -1.0))
    ldir = ldir.normalized()
    eye = center - ldir * radius * 2.5
    fwd = (center - eye).normalized()
    up = Vector((0, 1, 0))
    if abs(fwd.dot(up)) > .99:
        up = Vector((1, 0, 0))
    r_v = fwd.cross(up).normalized(); u_v = r_v.cross(fwd)
    view = Matrix([[r_v.x, r_v.y, r_v.z, -r_v.dot(eye)],
                   [u_v.x, u_v.y, u_v.z, -u_v.dot(eye)],
                   [-fwd.x, -fwd.y, -fwd.z, fwd.dot(eye)], [0, 0, 0, 1]])
    s = radius * 1.6; n = 0.1; f = radius * 6.0
    ortho = Matrix([[1/s, 0, 0, 0], [0, 1/s, 0, 0],
                    [0, 0, -2/(f-n), -(f+n)/(f-n)], [0, 0, 0, 1]])
    return ortho @ view


def _build_light_space_fit(sun_dir, view_proj, cam_pos, shadow_distance, res, scene_radius):
    """Fit the sun's shadow ortho tightly to the CAMERA view frustum (clamped to
    shadow_distance), instead of the whole scene — so texels are small and shadows are
    sharp. Uses the frustum's bounding sphere (rotation-stable) with texel snapping (no
    shimmer) and extends the near plane toward the sun so off-frustum casters still cast.
    Returns (light_space_matrix, texel_world_size)."""
    inv = view_proj.inverted()
    ndc = [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]
    corners = []
    for c in ndc:
        p = inv @ Vector((c[0], c[1], c[2], 1.0))
        w = p.w if abs(p.w) > 1e-9 else 1.0
        corners.append(Vector((p.x/w, p.y/w, p.z/w)))
    # Clamp the far corners to shadow_distance from the camera (limits the shadowed range).
    cam = Vector(cam_pos)
    for i in range(4):
        ray = corners[i+4] - cam
        L = ray.length
        if L > shadow_distance and L > 1e-6:
            corners[i+4] = cam + ray * (shadow_distance / L)

    center = Vector((0.0, 0.0, 0.0))
    for c in corners: center += c
    center /= 8.0
    radius = 0.01
    for c in corners: radius = max(radius, (c - center).length)

    ldir = -Vector(sun_dir)
    if ldir.length < 1e-6: ldir = Vector((0.0, 0.0, -1.0))
    fwd = ldir.normalized()
    up = Vector((0, 1, 0))
    if abs(fwd.dot(up)) > 0.99: up = Vector((1, 0, 0))
    r_v = fwd.cross(up).normalized(); u_v = r_v.cross(fwd)

    # Texel-snap the sphere centre in light space so the map doesn't swim frame-to-frame.
    texel = (2.0 * radius) / max(res, 1)
    cx = round(r_v.dot(center) / texel) * texel
    cy = round(u_v.dot(center) / texel) * texel
    cz = fwd.dot(center)
    center = r_v * cx + u_v * cy + fwd * cz

    margin = max(scene_radius, radius)   # include casters behind the visible region
    eye = center - fwd * (radius + margin)
    view = Matrix([[r_v.x, r_v.y, r_v.z, -r_v.dot(eye)],
                   [u_v.x, u_v.y, u_v.z, -u_v.dot(eye)],
                   [-fwd.x, -fwd.y, -fwd.z, fwd.dot(eye)], [0, 0, 0, 1]])
    s = radius; n = 0.0; f = 2.0 * radius + margin
    ortho = Matrix([[1/s, 0, 0, 0], [0, 1/s, 0, 0],
                    [0, 0, -2/(f-n), -(f+n)/(f-n)], [0, 0, 0, 1]])
    return ortho @ view, texel

# ── Mesh extraction (one new_from_object call per object, everything derived from it) ──

def _extract_mesh_data(obj, depsgraph, mesh=None, attr_name=""):
    """
    Read the depsgraph-evaluated mesh DIRECTLY (no new_from_object copy, no
    create/remove -> no depsgraph churn -> no self-triggered rebuild loop, and far
    faster on large scenes). All reads are bulk foreach_get + numpy (no Python loops).
    `mesh` overrides the geometry source (used for the edit-mode BMesh->temp-mesh path).
    """
    try:
        eval_obj = obj.evaluated_get(depsgraph)
        if mesh is None:
            mesh = getattr(eval_obj, 'data', None)
        if mesh is None or not hasattr(mesh, 'loop_triangles'):
            return None
        mesh.calc_loop_triangles()
        n_tris = len(mesh.loop_triangles)
        if n_tris == 0:
            return None

        mat_slot = eval_obj.active_material or getattr(obj, 'active_material', None)
        tex = _get_gpu_tex(_find_base_texture(mat_slot))
        default = [1.0, 1.0, 1.0, 1.0]
        if mat_slot:
            c = mat_slot.diffuse_color
            default = [c[0], c[1], c[2], 1.0]

        n_verts = len(mesh.vertices)
        n_loops = len(mesh.loops)
        n_flat = n_tris * 3

        # --- Triangle corner/vertex indices: raw memory (fast) with foreach fallback ---
        li_flat = _raw_corner_tris(mesh, n_tris)          # tri -> corner indices
        corner_vert = _raw_attr(mesh, '.corner_vert', _ct.c_int, 1, n_loops)
        if li_flat is not None and corner_vert is not None:
            vi_flat = corner_vert[li_flat]                # vertex per corner
        else:
            li_flat = np.empty(n_flat, dtype=np.int32); mesh.loop_triangles.foreach_get('loops', li_flat)
            vi_flat = np.empty(n_flat, dtype=np.int32); mesh.loop_triangles.foreach_get('vertices', vi_flat)

        # --- Vertex positions: raw with fallback ---
        vc = _raw_attr(mesh, 'position', _ct.c_float, 3, n_verts)
        if vc is None:
            vc = np.empty(n_verts * 3, dtype=np.float32); mesh.vertices.foreach_get('co', vc)
            vc = vc.reshape(n_verts, 3)
        positions = vc[vi_flat]

        # Per-VERTEX normals for GI/BVH (averaged); per-CORNER normals for the draw
        # batch so flat/hard shading, sharp edges and custom split normals are honoured
        # (vertex normals alone force everything smooth).
        vn = np.empty(n_verts * 3, dtype=np.float32); mesh.vertices.foreach_get('normal', vn)
        vn = vn.reshape(n_verts, 3)
        try:
            cn = np.empty(n_loops * 3, dtype=np.float32)
            mesh.corner_normals.foreach_get('vector', cn)
            normals = cn.reshape(n_loops, 3)[li_flat]
        except Exception:
            normals = vn[vi_flat]
        vert_co_local = vc.copy()   # stored in cache -> must not alias Blender memory

        # --- UVs: raw from the active UV attribute, with fallback ---
        uv_layer = mesh.uv_layers.active
        if uv_layer:
            uv = _raw_attr(mesh, uv_layer.name, _ct.c_float, 2, n_loops)
            if uv is None:
                uv = np.empty(n_loops * 2, dtype=np.float32); uv_layer.data.foreach_get('uv', uv)
                uv = uv.reshape(n_loops, 2)
            uvs = uv[li_flat]
        else:
            uvs = np.zeros((n_flat, 2), dtype=np.float32)

        # Vertex colours: bulk foreach_get + numpy gather (no per-element Python loop).
        colors = None
        try:
            ca = mesh.color_attributes
            attr = None
            if ca:
                if attr_name:
                    try: attr = ca.get(attr_name)
                    except Exception: attr = None
                if attr is None:
                    try: attr = ca.active_color
                    except Exception: attr = None
                if attr is None and len(ca): attr = ca[0]
            if attr is not None and getattr(attr, 'data_type', '') in ('FLOAT_COLOR', 'BYTE_COLOR'):
                m = len(attr.data)
                carr = np.empty(m * 4, dtype=np.float32)
                attr.data.foreach_get('color', carr)
                carr = carr.reshape(m, 4)
                if attr.domain == 'CORNER':
                    colors = carr[li_flat]
                elif attr.domain == 'POINT':
                    colors = carr[vi_flat]
        except Exception:
            colors = None
        if colors is None:
            colors = np.tile(np.array(default, dtype=np.float32), (n_flat, 1))

        # Generated-coord bbox (local) — cached so the draw loop needn't recompute per frame.
        vmin = vc.min(axis=0); vmax = vc.max(axis=0); size = vmax - vmin
        gen_min = (float(vmin[0]), float(vmin[1]), float(vmin[2]))
        gen_scale = (1.0/float(size[0]) if size[0] > 1e-9 else 0.0,
                     1.0/float(size[1]) if size[1] > 1e-9 else 0.0,
                     1.0/float(size[2]) if size[2] > 1e-9 else 0.0)

        # Per-triangle material index -> split the mesh into one draw slot per material,
        # so multi-material objects show each material on its own faces.
        mi = np.zeros(n_tris, dtype=np.int32)
        try: mesh.loop_triangles.foreach_get('material_index', mi)
        except Exception: pass
        has_vcol = (colors.shape[0] == n_flat and not np.all(colors == colors[0]))
        uniq = np.unique(mi)

        def _slot(slot_idx, P, N, U, C_arr):
            slot_mat = None
            try:
                ms = obj.material_slots
                if slot_idx < len(ms): slot_mat = ms[slot_idx].material
            except Exception:
                pass
            if slot_mat is None: slot_mat = mat_slot
            stex = _get_gpu_tex(_find_base_texture(slot_mat))
            sdefault = [1.0, 1.0, 1.0, 1.0]
            if slot_mat is not None:
                dc = slot_mat.diffuse_color; sdefault = [dc[0], dc[1], dc[2], 1.0]
            scolors = C_arr if has_vcol else np.tile(np.array(sdefault, dtype=np.float32), (len(P), 1))
            return dict(positions=P, normals=N, uvs=U, colors=scolors,
                        material_name=(slot_mat.name if slot_mat else None), texture=stex)

        slots_out = []
        if len(uniq) <= 1:
            # Single material (the common case): one slot, NO per-corner masking/copies.
            slots_out.append(_slot(int(uniq[0]) if len(uniq) else 0, positions, normals, uvs, colors))
        else:
            mi_corner = np.repeat(mi, 3)                  # (n_flat,)
            for idx in uniq:
                m = (mi_corner == idx)
                slots_out.append(_slot(int(idx), positions[m], normals[m], uvs[m],
                                       colors[m] if has_vcol else None))
        return dict(
            slots=slots_out, gen_min=gen_min, gen_scale=gen_scale,
            vi_map=vi_flat, n_verts=n_verts,
            vert_co_local=vert_co_local,
        )
    except Exception as e:
        print(f"[VertexLit] extract error ({obj.name}): {e}")
        return None


def _build_slot_batch(slot):
    shader=_get_main_shader()
    return batch_for_shader(shader,'TRIS',{
        'position':    slot['positions'],
        'normal':      slot['normals'],
        'vertColor':   slot['colors'],
        'texCoord':    slot['uvs'],
    })


def _build_object_slots(cached):
    """Return a list of (batch, material_name, texture) — one per material slot."""
    out=[]
    for slot in cached.get('slots', []):
        try:
            out.append((_build_slot_batch(slot), slot.get('material_name'), slot.get('texture')))
        except Exception as e:
            print("[VertexLit] slot batch error:", e)
    return out


def _build_shadow_batch_from_cache(cached):
    """Build shadow batch from already-extracted vertex data — no extra new_from_object."""
    shader=_get_shadow_shader()
    positions=cached['vert_co_local']
    vi_map=cached['vi_map']
    indices=np.asarray(vi_map, dtype=np.int32).reshape(-1, 3)   # numpy, not a python loop
    return batch_for_shader(shader,'TRIS',{'position':positions},indices=indices)


# ── Render Engine ─────────────────────────────────────────────────────────────

class VertexLitEngine(bpy.types.RenderEngine):
    bl_idname='VERTEX_LIT'; bl_label='Workbench 2.0'; bl_use_preview=False
    # F12 render() draws with the gpu module -> Blender must hand render() a GPU context.
    bl_use_gpu_context = True
    # Use Blender's STANDARD shader nodes (not a custom node system). Without this
    # (it defaults True), Blender detaches the Shader Editor from materials: it shows
    # a generic "Shader Nodetree", won't follow the selected object, and edits don't
    # reach the real material — so live-node changes appear to do nothing.
    bl_use_shading_nodes_custom = False

    def _ensure_state(self):
        if getattr(self,'_state_ready',False): return
        self._dirty            = True
        # Reuse the persistent caches (data + batches) across engine instances so
        # re-entering rendered view does NO work for unchanged objects.
        self._mesh_cache       = _PERSIST_MESH
        self._batch_dict       = _PERSIST_BATCH
        self._shadow_dict      = _PERSIST_SHADOW
        self._needs_verify     = True    # on (re)entry, sig-check cached objects once
        self._dummy_depth      = None
        self._white_tex        = None
        self._lights_cache     = []
        self._bounds_cache     = (Vector((0,0,0)),10.0)
        self._shadow_dirty     = True
        self._shadow_tex_cache = None
        self._dirty_objects    = set()   # names of objects to re-extract (incremental)
        self._force_full       = False   # force a full re-extract next rebuild
        self._geo_pending      = False   # geometry still streaming in (progressive load)
        self._edit_tmp         = None    # reused temp mesh for live edit-mode extraction
        self._post             = fx.make_pipeline()   # screen-space effects (AO...)
        # After rebuild, skip N view_update cycles. new_from_object / remove
        # queue deferred depsgraph events that arrive after _rebuild returns.
        # The drain absorbs them so they don't re-trigger a rebuild.
        self._drain_cycles     = 0
        self._rebuild_time     = 0.0
        self._state_ready      = True

    def _ensure_resources(self):
        if self._dummy_depth is None:
            self._dummy_depth=gpu.types.GPUTexture((1,1),format='DEPTH_COMPONENT32F')
        if self._white_tex is None:
            self._white_tex=gpu.types.GPUTexture((1,1),format='RGBA8')

    def update(self, data=None, depsgraph=None):
        pass

    def render(self, depsgraph):
        # F12 final image: render the scene from the active camera into an offscreen
        # (Workbench-style shading) and hand the pixels to Blender. Viewport-quality
        # only (no shadows/GI in the F12 path yet).
        try:
            scene = depsgraph.scene
            sc = scene.render.resolution_percentage / 100.0
            w = max(int(scene.render.resolution_x * sc), 1)
            h = max(int(scene.render.resolution_y * sc), 1)
            vls = getattr(scene, 'vertex_lit', None)
            self._cull = 'BACK' if (vls and getattr(vls, 'backface_cull', True)) else 'NONE'
            cam = scene.camera

            self._ensure_state(); self._ensure_resources()
            # F12 uses the RENDER depsgraph (Is Viewport = False -> full geometry, not the
            # viewport's convex-hull preview). Drop the viewport-populated caches and extract
            # everything fresh from this depsgraph, fully (no streaming budget) before drawing.
            _PERSIST_MESH.clear(); _PERSIST_BATCH.clear(); _PERSIST_SHADOW.clear(); _PERSIST_SIG.clear()
            self._mesh_cache.clear(); self._batch_dict.clear(); self._shadow_dict.clear()
            self._force_full = True
            self._dirty = True
            self._rebuild(depsgraph, vls)
            _guard = 0
            _deadline = time.time() + 120.0   # safety cap: render what's loaded rather than hang
            while getattr(self, '_geo_pending', False) and _guard < 100000 and time.time() < _deadline:
                # _force_full already consumed; subsequent passes drain the remaining queue.
                self._rebuild(depsgraph, vls)
                _guard += 1

            result = self.begin_result(0, 0, w, h)
            rl = result.layers[0].passes["Combined"]

            if cam is None or cam.type != 'CAMERA':
                rl.rect = [[0.0, 0.0, 0.0, 1.0]] * (w * h)
                self.end_result(result)
                return

            # Use the DEPSGRAPH-EVALUATED camera so animation (and any constraints/drivers)
            # are applied at the frame being rendered — otherwise we'd read the original
            # object's stale transform and the view looks wrong / zoomed.
            cam_eval = cam.evaluated_get(depsgraph)
            view = cam_eval.matrix_world.inverted()
            proj = cam_eval.calc_matrix_camera(depsgraph, x=w, y=h)
            view_proj = proj @ view
            self._film_transparent = getattr(scene.render, 'film_transparent', False)
            self._sun = _compute_sun(vls)
            try: self._cam_pos = tuple(cam_eval.matrix_world.translation)
            except Exception: self._cam_pos = (0.0, 0.0, 0.0)
            try: self._view_mat3 = view.to_3x3()
            except Exception: self._view_mat3 = None
            try:
                kv = Vector((0.25, 0.35, 0.90)); kv.normalize()
                key_dir = tuple(cam_eval.matrix_world.to_quaternion() @ kv)
            except Exception:
                key_dir = (0.3, 0.4, 0.86)
            studio = (key_dir, (1.0, 1.0, 1.0), (vls.key_intensity if vls else 0.8))
            sky = tuple(vls.sky_color) if vls else (0.6, 0.68, 0.78)
            ground = tuple(vls.ground_color) if vls else (0.2, 0.18, 0.16)

            offscreen = gpu.types.GPUOffScreen(w, h)
            arr = None
            try:
                with offscreen.bind():
                    fb = gpu.state.active_framebuffer_get()
                    wc = scene.world.color if scene.world else None
                    if getattr(scene.render, 'film_transparent', False):
                        fb.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)   # transparent film
                    else:
                        fb.clear(color=(wc[0], wc[1], wc[2], 1.0) if wc else (0.05, 0.05, 0.05, 1.0),
                                 depth=1.0)
                    post = getattr(self, '_post', None)
                    if post is not None and post.any_enabled(vls):
                        # Same effect pipeline as the viewport (AO / cavity / outline / FXAA).
                        view_mat3 = view.to_3x3()
                        draw_scene, post_ctx = self._make_post_ctx(
                            depsgraph, vls, view_proj, view_mat3, proj, w, h, wc,
                            studio, Matrix.Identity(4), sky, ground, 1.0, self._lights_cache)
                        final_tex, sw, sh = post.render(w, h, draw_scene, post_ctx, vls, blit=False)
                        # Read the pipeline's final texture straight out (it may be at a
                        # supersampled sw x sh; downscale to w x h below).
                        tmp_fb = gpu.types.GPUFrameBuffer(color_slots=(final_tex,))
                        with tmp_fb.bind():
                            buf = tmp_fb.read_color(0, 0, sw, sh, 4, 0, 'FLOAT')
                        buf.dimensions = sw * sh * 4
                        arr = np.array(buf, dtype=np.float32).reshape(sh, sw, 4)
                        if (sw, sh) != (w, h):
                            arr = _area_resize(arr, w, h)
                    else:
                        self._draw_batches(depsgraph, vls, view_proj, studio, Matrix.Identity(4),
                                           sky, ground, 1.0, False, 0.005, 0.25, self._dummy_depth,
                                           self._lights_cache, 'PIXEL')
                        buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
                        buf.dimensions = w * h * 4
                        # read_color is bottom-up and Blender's render rect is bottom-up too.
                        arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)
            finally:
                offscreen.free()

            rl.rect = arr.reshape(-1, 4).tolist() if arr is not None else \
                [[0.0, 0.0, 0.0, 1.0]] * (w * h)
            self.end_result(result)
        except Exception as e:
            print("[VertexLit] render() failed:", e)
            import traceback; traceback.print_exc()

    def free(self):
        # Called when the engine instance is destroyed (leaving rendered mode).
        if getattr(self, '_post', None) is not None:
            try: self._post.free()
            except Exception: pass
            self._post = None
        if getattr(self, '_edit_tmp', None) is not None:
            try: bpy.data.meshes.remove(self._edit_tmp)
            except Exception: pass
            self._edit_tmp = None
        # Drop per-instance references (batches/textures) so they can be GC'd.
        # Do NOT clear the shared shader/program caches here: the viewport GPU
        # context persists across enter/leave, so those stay valid — clearing them
        # only forces an expensive full recompile on every re-entry.
        self._dummy_depth = None
        self._white_tex = None
        self._shadow_tex_cache = None
        self._batch_dict = {}
        self._shadow_dict = {}
        self._mesh_cache = {}
        self._state_ready = False

    # ── view_update ───────────────────────────────────────────────────────

    def view_update(self, context, depsgraph):
        self._ensure_state()

        # General rule: react to EVERY change in this depsgraph update, immediately.
        # (No more churn-era throttling — extraction reads the eval mesh directly and no
        # longer creates/removes datablocks, so there's nothing to "absorb".)
        changed = False
        for update in depsgraph.updates:
            id_data = update.id
            if isinstance(id_data, bpy.types.Object):
                if id_data.type == 'MESH':
                    if update.is_updated_geometry:
                        # modifier add/remove/toggle, geo-nodes, edit-mode edits, new
                        # object... all surface here -> re-extract just this object.
                        self._dirty_objects.add(id_data.name)
                        self._dirty = True; self._shadow_dirty = True; changed = True
                    elif update.is_updated_transform:
                        # moving/rotating: matrix_world is read live in the draw loop, so
                        # NO re-extract needed; only shadows must re-render.
                        self._shadow_dirty = True; changed = True
                elif id_data.type == 'LIGHT':
                    self._dirty = True; self._shadow_dirty = True; changed = True
            elif isinstance(id_data, bpy.types.Mesh):
                # mesh datablock geometry (edit mode / linked duplicates write here) ->
                # mark every cached object sharing this mesh.
                if update.is_updated_geometry and getattr(id_data, 'users', 0) > 0:
                    for nm in self._mesh_cache:
                        ob = bpy.data.objects.get(nm)
                        if ob is not None and getattr(ob, 'data', None) is id_data:
                            self._dirty_objects.add(nm)
                    self._dirty = True; self._shadow_dirty = True; changed = True
            elif isinstance(id_data, bpy.types.Material):
                # Live path: only the tiny per-material shader recompiles (peeked at draw
                # time) — no geometry rebuild.
                material_shader.mark_dirty(id_data.name); changed = True
            elif isinstance(id_data, bpy.types.Image):
                _invalidate_tex(id_data.name); changed = True

        # Object deletion doesn't always surface as an update -> sync against the scene.
        if not self._dirty and self._mesh_cache:
            for nm in self._mesh_cache:
                if nm not in bpy.data.objects:
                    self._dirty = True; changed = True; break

        if changed:
            self.tag_redraw()
            try: context.region.tag_redraw()
            except Exception: pass

    # ── Rebuild ───────────────────────────────────────────────────────────

    def _rebuild(self, depsgraph, vls):
        self._rebuild_inner(depsgraph, vls)

    def _rebuild_inner(self, depsgraph, vls):
        self._view_attr = getattr(vls, 'view_attribute', '') if vls else ''
        t0=time.time()

        en_scale=vls.energy_scale  if vls else 0.01
        lights  =_collect_lights(depsgraph,en_scale)
        self._lights_cache=lights
        self._bounds_cache=_scene_bounds(depsgraph)

        # Current visible mesh objects. Non-instances key by name; geometry-nodes/dupli
        # INSTANCES key by their shared mesh datablock (the instancer's own mesh is empty),
        # extracted eagerly here (inst.object is only valid during this iteration) and drawn
        # per-instance later. Instance geometry is usually a few unique meshes reused many
        # times, so eager extraction is cheap; the budget still gates it and we re-iterate
        # next frame for anything deferred.
        current={}
        inst_keys=set()
        _va = getattr(self, '_view_attr', '')
        _want_shadow_i = bool(vls and getattr(vls, 'use_shadows', False))
        _inst_budget_end = time.time() + 0.03
        _inst_done = 0
        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type!='MESH': continue
            if not inst.show_self: continue
            if getattr(inst, 'is_instance', False):
                key = _draw_key(inst)
                if key in inst_keys:      # already handled this frame
                    continue
                inst_keys.add(key)
                try: sig = _geo_sig(obj, getattr(obj, 'data', None))
                except Exception: sig = None
                if key in self._batch_dict and _PERSIST_SIG.get(key) == sig:
                    continue              # cached + unchanged
                if _inst_done > 0 and time.time() > _inst_budget_end:
                    self._geo_pending = True; self._dirty = True
                    continue              # over budget -> finish next frame (re-iterated)
                data = _extract_mesh_data(obj, depsgraph, mesh=getattr(obj, 'data', None), attr_name=_va)
                if data:
                    self._mesh_cache[key] = data
                    self._batch_dict[key] = _build_object_slots(data)
                    _PERSIST_SIG[key] = sig
                    if _want_shadow_i:
                        sb = _build_shadow_batch_from_cache(data)
                        if sb: self._shadow_dict[key] = sb
                    _inst_done += 1
            else:
                if obj.name not in current: current[obj.name]=obj

        # 1) Drop objects that no longer exist / were hidden. Keep instance-geometry keys
        #    ('i:...') that are still present this frame.
        for name in list(self._mesh_cache.keys()):
            if name not in current and name not in inst_keys:
                self._mesh_cache.pop(name,None)
                self._batch_dict.pop(name,None)
                self._shadow_dict.pop(name,None)
                _PERSIST_SIG.pop(name,None)

        # On (re)entry into rendered view the batches are already persisted. Verify each
        # cached object's signature ONCE and mark only the changed ones dirty -> unchanged
        # objects keep their persisted batch and are drawn immediately (no work).
        if getattr(self, '_needs_verify', False):
            for name, obj in current.items():
                if name not in self._batch_dict:
                    continue
                try:
                    eo=obj.evaluated_get(depsgraph); me=getattr(eo,'data',None)
                    if me is None or _PERSIST_SIG.get(name) != _geo_sig(obj, me):
                        self._dirty_objects.add(name)
                except Exception:
                    self._dirty_objects.add(name)
            self._needs_verify = False

        # Re-extract only dirty objects + brand-new objects (no persisted batch).
        dirty=set(getattr(self,'_dirty_objects',set()))
        full = getattr(self,'_force_full',False)
        if full:
            to_do=set(current.keys())
        else:
            to_do=(dirty & set(current.keys())) | {n for n in current if n not in self._batch_dict}

        want_shadow = bool(vls and getattr(vls, 'use_shadows', False))
        # Adaptive per-frame budget: spend more time extracting when a LOT is queued
        # (initial/large load -> load fast), less when it's a small incremental edit
        # (stay responsive). Batch creation must happen on the main thread in view_draw,
        # so this is the main lever for load speed (threading can't move the GPU upload).
        budget = 0.10 if len(to_do) > 8 else 0.04
        budget_end = time.time() + budget
        remaining = []
        done = 0
        if full or not hasattr(self, '_geo_share'):
            self._geo_share = {}   # share sig -> (data, slots, shadow_batch)
        va = getattr(self, '_view_attr', '')
        for name in to_do:
            if done > 0 and time.time() > budget_end:
                remaining.append(name)
                continue
            obj=current.get(name)
            if obj is None: continue
            try:
                eo=obj.evaluated_get(depsgraph); me=getattr(eo,'data',None)
            except Exception:
                me=None
            gsig = _geo_sig(obj, me) if me is not None else None
            ssig = _share_sig(obj, me, va) if me is not None else None
            shared = self._geo_share.get(ssig) if ssig is not None else None
            if shared is not None:
                # Identical geometry+materials already extracted (e.g. a linked duplicate) ->
                # reuse the SAME batch, no re-extract or re-upload. Instant, so it doesn't
                # count against the extraction budget; the draw loop draws it per-instance.
                self._mesh_cache[name]=shared[0]
                self._batch_dict[name]=shared[1]
                if want_shadow and shared[2] is not None:
                    self._shadow_dict[name]=shared[2]
                _PERSIST_SIG[name]=gsig
                continue
            data=_extract_mesh_data(obj,depsgraph,attr_name=va)
            if data:
                slots=_build_object_slots(data)
                self._mesh_cache[name]=data
                self._batch_dict[name]=slots
                sb=None
                if want_shadow:
                    sb=_build_shadow_batch_from_cache(data)
                    if sb: self._shadow_dict[name]=sb
                if ssig is not None:
                    self._geo_share[ssig]=(data, slots, sb)
                _PERSIST_SIG[name]=gsig
            done += 1

        if remaining:
            # more to load -> keep them pending and rebuild again next frame
            self._dirty_objects = set(remaining)
            self._dirty = True
            self._geo_pending = True
        else:
            self._dirty=False
            self._force_full=False
            if hasattr(self,'_dirty_objects'): self._dirty_objects.clear()
            self._geo_pending = False
        self._shadow_dirty=True
        if done or remaining:
            print("[VertexLit] re-extracted {}/{} objs ({:.2f}s){}{}".format(
                done, len(current), time.time()-t0,
                " [full]" if full else "",
                " (+{} streaming)".format(len(remaining)) if remaining else ""))


    # ── Shadow pass ───────────────────────────────────────────────────────

    def _shadow_pass(self, ls_mat, shad_res, depsgraph):
        if not self._shadow_dirty and self._shadow_tex_cache is not None:
            return self._shadow_tex_cache
        smap=_get_shadow_map(shad_res); shader=_get_shadow_shader()
        with smap.fb.bind():
            smap.fb.clear(depth=1.0)
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            gpu.state.viewport_set(0,0,shad_res,shad_res)
            shader.bind()
            shader.uniform_float('uLightSpace',ls_mat)
            # Iterate instances so each gets its own matrix_world (not source object's)
            for inst in depsgraph.object_instances:
                obj = inst.object
                if obj.type != 'MESH': continue
                batch = self._shadow_dict.get(_draw_key(inst))
                if batch is None:
                    # Shadows were just enabled after the geometry loaded -> build the
                    # (position-only) shadow batch on demand from the cached mesh data.
                    cached = self._mesh_cache.get(_draw_key(inst))
                    if cached is not None:
                        batch = _build_shadow_batch_from_cache(cached)
                        if batch is not None:
                            self._shadow_dict[_draw_key(inst)] = batch
                if batch is None: continue
                shader.uniform_float('uModel', inst.matrix_world)
                batch.draw(shader)
        self._shadow_tex_cache=smap.tex
        self._shadow_dirty=False
        return smap.tex

    # ── Per-frame uniforms (shared by legacy + per-material shaders) ──────

    def _apply_frame_uniforms(self, shader, view_proj, ls_mat, sky, ground, bstr,
                              do_shad, s_bias, s_dark, shad_tex, lights, studio):
        # Programs differ by shading mode (Solid studio vs per-pixel lit) and don't all
        # declare the same uniforms, so set each defensively — a uniform the current
        # program doesn't have simply raises ValueError and is skipped.
        def sf(name, val):
            try: shader.uniform_float(name, val)
            except (ValueError, Exception): pass
        def si(name, val):
            try: shader.uniform_int(name, val)
            except (ValueError, Exception): pass
        def ss(name, val):
            try: shader.uniform_sampler(name, val)
            except (ValueError, Exception): pass

        sf('uViewProj', view_proj)
        # Workbench studio light (camera-following key + flat ambient)
        key_dir, key_col, key_int = studio
        sf('uKeyDir', key_dir); sf('uKeyCol', key_col); sf('uKeyIntensity', key_int)
        # Scene-light / shadow uniforms (present only in the PIXEL program)
        sf('uLightSpace', ls_mat); sf('uSkyColor', sky); sf('uGroundColor', ground)
        # Sun + hemisphere intensity (stacked lighting), from self._sun set each frame.
        _sd, _sc, _si, _hi = getattr(self, '_sun', ((0.0, 0.0, 1.0), (1.0, 1.0, 1.0), 0.0, 1.0))
        sf('uSunDir', _sd); sf('uSunColor', _sc); sf('uSunIntensity', _si)
        sf('uHemiIntensity', _hi)
        si('uUseShadow', 1 if do_shad else 0)
        sf('uShadowBias', s_bias); sf('uShadowSoft', s_dark); ss('uShadowMap', shad_tex)
        sf('uShadowTexelWorld', getattr(self, '_shadow_texel', 0.0))
        si('uNumLights', len(lights))
        for i in range(8):
            l=lights[i] if i<len(lights) else None
            sf(f'uLPos[{i}]',    tuple(l['pos'])  if l else (0,0,0))
            sf(f'uLDir[{i}]',    tuple(l['dir'])  if l else (0,0,-1))
            sf(f'uLCol[{i}]',    l['color']       if l else (0,0,0))
            sf(f'uLEnergy[{i}]', l['energy']      if l else 0.0)
            si(f'uLType[{i}]',   l['type']        if l else 0)
            sf(f'uLRadius[{i}]', l['radius']      if l else 1.0)

    # ── Shared scene draw (used by the viewport AND F12 render) ─────────────

    def _draw_background(self, vls, view_proj, sky, ground):
        """Fullscreen background: world hemisphere gradient or a flat colour."""
        try:
            bgsh, bgbatch = _get_bg()
            bgsh.bind()
            mode = getattr(vls, 'background_mode', 'WORLD')
            bgsh.uniform_float('uInvViewProj', view_proj.inverted())
            bgsh.uniform_float('uCamPos', getattr(self, '_cam_pos', (0.0, 0.0, 0.0)))
            bgsh.uniform_float('uSkyColor', sky)
            bgsh.uniform_float('uGroundColor', ground)
            bgsh.uniform_int('uBgMode', 0 if mode == 'WORLD' else 1)
            bgc = tuple(vls.background_color) if vls else (0.05, 0.05, 0.05)
            bgsh.uniform_float('uBgColor', bgc)
            gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
            bgbatch.draw(bgsh)
            gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
        except Exception as e:
            print(f"[VertexLit] background: {e}")

    def _draw_viewmode(self, depsgraph, vls, view_proj, studio, ls_mat, sky, ground,
                       bstr, lights, view_mode):
        """Solid / Random / Attribute / Normal view: one shared lit shader, no materials."""
        sh = _get_viewmode_shader(); sh.bind()
        self._apply_frame_uniforms(sh, view_proj, ls_mat, sky, ground, bstr,
                                   False, 0.005, 0.25, self._dummy_depth, lights, studio)
        vmid = _VIEWMODE_ID.get(view_mode, 1)
        rand_mode = getattr(vls, 'random_mode', 'OBJECT') if vls else 'OBJECT'
        def sf(n, v):
            try: sh.uniform_float(n, v)
            except Exception: pass
        try: sh.uniform_int('uViewMode', vmid)
        except Exception: pass
        sf('uSolidColor', tuple(vls.solid_color) if vls else (0.8, 0.8, 0.8))
        sf('uCamPos', getattr(self, '_cam_pos', (0.0, 0.0, 0.0)))
        # Depth range: auto-fit to the scene's distance from the camera, or manual.
        if vls and vmid == 5 and getattr(vls, 'depth_auto', True):
            try:
                c, r = self._bounds_cache
                d = (Vector(self._cam_pos) - Vector(c)).length
                dmin = max(0.0, d - r); dmax = d + r
                if dmax - dmin < 1e-4: dmax = dmin + 1.0
            except Exception:
                dmin, dmax = (vls.depth_min, vls.depth_max)
        else:
            dmin = vls.depth_min if vls else 0.0
            dmax = vls.depth_max if vls else 20.0
        sf('uDepthMin', dmin); sf('uDepthMax', dmax)
        # Normal-view space (world / screen)
        try:
            sh.uniform_int('uNormalSpace', 1 if (vls and vls.normal_space == 'SCREEN') else 0)
        except Exception: pass
        vm3 = getattr(self, '_view_mat3', None)
        if vm3 is not None:
            sf('uViewMat3', vm3)
        gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set(getattr(self, '_cull', 'BACK'))
        for inst in depsgraph.object_instances:
            obj = inst.object
            if obj.type != 'MESH' or not inst.show_self: continue
            slots = self._batch_dict.get(_draw_key(inst))
            if not slots: continue
            cached = self._mesh_cache.get(_draw_key(inst))
            gmin = cached.get('gen_min', (0.0, 0.0, 0.0)) if cached else (0.0, 0.0, 0.0)
            gsc = cached.get('gen_scale', (1.0, 1.0, 1.0)) if cached else (1.0, 1.0, 1.0)
            try: nmat = inst.matrix_world.to_3x3().inverted().transposed()
            except Exception: nmat = inst.matrix_world.to_3x3()
            # Each uniform set independently — some (uGenMin/uGenScale) are optimised out of
            # this program, and a shared try/except would skip uObjColor after the first miss.
            sf('uModel', inst.matrix_world)
            sf('uNormalMat', nmat)
            sf('uGenMin', gmin); sf('uGenScale', gsc)
            if vmid == 2 and rand_mode == 'OBJECT':
                sf('uObjColor', _obj_random_color(obj.name))
            for batch, _mat_name, _tex in slots:
                if vmid == 2 and rand_mode == 'MATERIAL':
                    sf('uObjColor', _obj_random_color(_mat_name or '__no_material__'))
                try: batch.draw(sh)
                except Exception: pass

    def _draw_batches(self, depsgraph, vls, view_proj, studio, ls_mat, sky, ground,
                      bstr, do_shad, s_bias, s_dark, shad_tex, lights, mode):
        legacy=_get_main_shader(mode)
        frame_done=set(); params_done=set()
        # Progressive compile: sharpen at most ~40ms of new material shaders per frame,
        # so the scene shows instantly (base-texture path) instead of freezing while
        # every material compiles up front. While geometry is still STREAMING in, don't
        # compile at all (draw base textures) so the two budgets don't stack — geometry
        # loads first, materials sharpen once it's done.
        _compile_deadline = time.time() + (0.0 if getattr(self, '_geo_pending', False) else 0.04)
        self._mat_pending = False

        def _ensure_frame(sh):
            sh.bind()
            if id(sh) not in frame_done:
                self._apply_frame_uniforms(sh, view_proj, ls_mat, sky, ground, bstr,
                                           do_shad, s_bias, s_dark, shad_tex, lights, studio)
                frame_done.add(id(sh))

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set(getattr(self, '_cull', 'BACK'))

        # Background (behind everything). Skipped for a film-transparent render.
        if not getattr(self, '_film_transparent', False):
            self._draw_background(vls, view_proj, sky, ground)

        # Non-textured view modes bypass the material programs entirely.
        view_mode = getattr(vls, 'view_mode', 'TEXTURED')
        if view_mode != 'TEXTURED':
            self._draw_viewmode(depsgraph, vls, view_proj, studio, ls_mat, sky, ground,
                                bstr, lights, view_mode)
            return

        # Resolve each material's program at most ONCE per frame (materials are shared
        # across many objects; the peek can run topo_signature for dirty materials, so
        # doing it per-object per-frame is a real cost while editing).
        frame_progs = {}
        frame_transp = {}   # mat name -> bool (transparent), computed once per frame
        def _resolve_prog(mat_name):
            if mat_name in frame_progs:
                return frame_progs[mat_name]
            mat = bpy.data.materials.get(mat_name) if mat_name else None
            prog = None
            if mat is not None and getattr(mat, 'use_nodes', False):
                p = material_shader.get_program(mat, mode, may_compile=False)
                if p is None:
                    if time.time() < _compile_deadline:
                        p = material_shader.get_program(mat, mode, may_compile=True)
                    else:
                        self._mat_pending = True
                if p and not p['failed'] and p['shader'] is not None:
                    prog = p
            frame_progs[mat_name] = prog
            return prog

        transparent = []   # (sort_depth, draw_fn) for a back-to-front blended pass

        def _draw_one(prog, mat, batch, tex, model, nmat, gmin, gsc, oname):
            if prog is not None:
                sh=prog['shader']
                _ensure_frame(sh)
                if id(sh) not in params_done:
                    nt=mat.node_tree if mat else None
                    for p in prog['params']:
                        try: sh.uniform_float(p.uniform, p.value(nt))
                        except Exception: pass
                    params_done.add(id(sh))
                sh.uniform_float('uModel',model)
                sh.uniform_float('uNormalMat',nmat)
                try: sh.uniform_float('uGenMin',gmin); sh.uniform_float('uGenScale',gsc)
                except Exception: pass
                for uni,image in prog['samplers']:
                    gtex=_get_gpu_tex(image)
                    if gtex is not None:
                        try: sh.uniform_sampler(uni,gtex)
                        except Exception: pass
                try: batch.draw(sh)
                except Exception:
                    self._batch_dict.pop(oname, None); self._dirty_objects.add(oname); self._dirty=True
            else:
                _ensure_frame(legacy)
                legacy.uniform_float('uModel',model)
                legacy.uniform_float('uNormalMat',nmat)
                try: legacy.uniform_float('uGenMin',gmin); legacy.uniform_float('uGenScale',gsc)
                except Exception: pass
                legacy.uniform_sampler('uAlbedo',  tex if tex is not None else self._white_tex)
                legacy.uniform_int('uHasTexture',  1 if tex is not None else 0)
                try: batch.draw(legacy)
                except Exception:
                    self._batch_dict.pop(oname, None); self._dirty_objects.add(oname); self._dirty=True

        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type!='MESH': continue
            if not inst.show_self: continue
            slots=self._batch_dict.get(_draw_key(inst))
            if not slots: continue
            cached=self._mesh_cache.get(_draw_key(inst))
            gmin=cached.get('gen_min',(0.0,0.0,0.0)) if cached else (0.0,0.0,0.0)
            gsc =cached.get('gen_scale',(1.0,1.0,1.0)) if cached else (1.0,1.0,1.0)

            try:   normal_mat=inst.matrix_world.to_3x3().inverted().transposed()
            except Exception: normal_mat=inst.matrix_world.to_3x3()
            model=inst.matrix_world.copy()

            for batch, mat_name, tex in slots:
                prog=_resolve_prog(mat_name)
                mat=bpy.data.materials.get(mat_name) if mat_name else None
                # Alpha-blended if the material's render method is Blended (4.2+) or the
                # legacy blend mode is BLEND.
                # Transparent (alpha-blended) determined from the material's CURRENT state,
                # cached once per frame. Never uses a stale compiled flag -> tweaking Alpha
                # takes effect immediately, and a truly opaque material stays in the opaque
                # pass (no depth-sort artifacts).
                is_transp = frame_transp.get(mat_name)
                if is_transp is None:
                    is_transp = _material_transparent(mat)
                    frame_transp[mat_name] = is_transp
                if is_transp:
                    try:
                        c = model.translation; clip = view_proj @ c.to_4d()
                        d = clip.z / clip.w if abs(clip.w) > 1e-6 else 0.0
                    except Exception:
                        d = 0.0
                    transparent.append((d, (prog, mat, batch, tex, model, normal_mat, gmin, gsc, obj.name)))
                else:
                    _draw_one(prog, mat, batch, tex, model, normal_mat, gmin, gsc, obj.name)

        # Transparent pass: farthest first, alpha blend, no depth write (still tested).
        if transparent:
            transparent.sort(key=lambda x: x[0], reverse=True)
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_mask_set(False)
            # Only for a film-transparent render do we protect the alpha channel (so glass
            # over an opaque object keeps alpha=1 instead of showing the transparent film).
            # In the viewport, plain alpha blending is what we want.
            _mask_a = getattr(self, '_film_transparent', False)
            if _mask_a:
                gpu.state.color_mask_set(True, True, True, False)
            for _d, args in transparent:
                _draw_one(*args)
            if _mask_a:
                gpu.state.color_mask_set(True, True, True, True)
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)

    # ── Main draw ─────────────────────────────────────────────────────────

    def _draw_splats(self):
        """Draw generated splat clouds (from the splat_render registry) into the current framebuffer."""
        from . import splat_render
        clouds = splat_render.SCENE_CLOUDS
        if not clouds:
            return
        vm = getattr(self, '_splat_vm', None); pm = getattr(self, '_splat_pm', None)
        wh = getattr(self, '_splat_wh', None)
        if vm is None or pm is None or wh is None:
            return
        light = getattr(self, '_splat_light', None)
        wd = getattr(self, '_splat_need_depth', True)
        for c in clouds:
            try:
                c.draw(vm, pm, wh[0], wh[1], write_depth=wd, light=light)
            except Exception as e:
                if _DEBUG: print("[VertexLit] splat draw:", e)

    def _draw_splat_normals(self, view_mat3):
        """Render splat normals into the cavity normal buffer (so the cavity effect includes splats)."""
        from . import splat_render
        clouds = splat_render.SCENE_CLOUDS
        if not clouds or view_mat3 is None:
            return
        vm = getattr(self, '_splat_vm', None); pm = getattr(self, '_splat_pm', None)
        wh = getattr(self, '_splat_wh', None)
        if vm is None or pm is None or wh is None:
            return
        for c in clouds:
            try:
                c.draw_normals(vm, pm, view_mat3, wh[0], wh[1])
            except Exception as e:
                if _DEBUG: print("[VertexLit] splat normals:", e)

    def _make_post_ctx(self, depsgraph, vls, view_proj, view_mat3, proj, rw, rh, wc,
                       studio, ls_mat, sky, ground, bstr, lights,
                       do_shad=False, s_bias=0.0015, s_soft=1.5, shad_tex=None):
        """Build the draw-scene callback + post_ctx (AO occluders, ID pass, normal pass,
        effect params). Shared by the viewport and the F12 render so both get effects."""
        cull = getattr(self, '_cull', 'BACK')

        def _draw_objects():
            self._draw_batches(depsgraph, vls, view_proj, studio, ls_mat, sky, ground,
                               bstr, do_shad, s_bias, s_soft,
                               shad_tex if shad_tex is not None else self._dummy_depth,
                               lights, 'PIXEL')
            self._draw_splats()

        ao_occluders = None
        if vls and getattr(vls, 'use_ao', False):
            any_excl = any(getattr(i.object, 'vlr_ao_exclude', False)
                           for i in depsgraph.object_instances if i.object.type == 'MESH')
            if any_excl:
                def ao_occluders():
                    sh = _get_main_shader('PIXEL'); sh.bind()
                    try: sh.uniform_float('uViewProj', view_proj)
                    except Exception: pass
                    gpu.state.face_culling_set(cull)
                    for i in depsgraph.object_instances:
                        o = i.object
                        if o.type != 'MESH' or not i.show_self: continue
                        if getattr(o, 'vlr_ao_exclude', False): continue
                        sl = self._batch_dict.get(_draw_key(i))
                        if not sl: continue
                        try: sh.uniform_float('uModel', i.matrix_world)
                        except Exception: pass
                        for b, _mn, _tx in sl:
                            try: b.draw(sh)
                            except Exception: pass

        ids_cb = None
        if vls and (getattr(vls, 'use_outline', False) or getattr(vls, 'use_cavity', False)):
            def ids_cb():
                sh = _get_id_shader(); sh.bind()
                try: sh.uniform_float('uViewProj', view_proj)
                except Exception: pass
                gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
                gpu.state.face_culling_set(cull)
                idx = 1
                for i in depsgraph.object_instances:
                    o = i.object
                    if o.type != 'MESH' or not i.show_self: continue
                    sl = self._batch_dict.get(_draw_key(i))
                    if not sl: continue
                    if getattr(o, 'vlr_outline_exclude', False):
                        col = (1.0, 1.0, 1.0)
                    else:
                        col = ((idx & 0xFF)/255.0, ((idx >> 8) & 0xFF)/255.0, ((idx >> 16) & 0xFF)/255.0)
                    try:
                        sh.uniform_float('uModel', i.matrix_world)
                        sh.uniform_float('uId', col)
                    except Exception: pass
                    for b, _mn, _tx in sl:
                        try: b.draw(sh)
                        except Exception: pass
                    idx += 1

        normals_cb = None
        if vls and getattr(vls, 'use_cavity', False):
            def normals_cb():
                sh = _get_normal_shader(); sh.bind()
                try:
                    sh.uniform_float('uViewProj', view_proj)
                    sh.uniform_float('uViewMat3', view_mat3)
                except Exception: pass
                gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
                gpu.state.face_culling_set(cull)
                for i in depsgraph.object_instances:
                    o = i.object
                    if o.type != 'MESH' or not i.show_self: continue
                    sl = self._batch_dict.get(_draw_key(i))
                    if not sl: continue
                    try: nmat = i.matrix_world.to_3x3().inverted().transposed()
                    except Exception: nmat = i.matrix_world.to_3x3()
                    try:
                        sh.uniform_float('uModel', i.matrix_world)
                        sh.uniform_float('uNormalMat', nmat)
                    except Exception: pass
                    for b, _mn, _tx in sl:
                        try: b.draw(sh)
                        except Exception: pass
                self._draw_splat_normals(view_mat3)

        post_ctx = {
            'proj': proj, 'inv_proj': proj.inverted(),
            'texel': (1.0/max(rw, 1), 1.0/max(rh, 1)),
            'clear_color': (wc[0], wc[1], wc[2], 1.0) if wc else (0.08, 0.08, 0.08, 1.0),
            'draw_ao_occluders': ao_occluders,
            'draw_object_ids': ids_cb,
            'draw_view_normals': normals_cb,
            'ao_radius':   (vls.ao_radius   if vls else 0.5),
            'ao_strength': (vls.ao_strength if vls else 1.0),
            'ao_bias':     (vls.ao_bias     if vls else 0.02),
            'ao_ridge':    (vls.ao_ridge    if vls else 0.0),
            'ao_samples':  (int(vls.ao_samples) if vls else 16),
            'cavity_ridge':  (vls.cavity_ridge  if vls else 1.0),
            'cavity_valley': (vls.cavity_valley if vls else 1.0),
            'outline_size':      (vls.outline_size  if vls else 1.5),
            'outline_color':     (tuple(vls.outline_color) if vls else (0.0, 0.0, 0.0)),
        }
        return _draw_objects, post_ctx

    def view_draw(self, context, depsgraph):
        self._ensure_state()
        self._ensure_resources()

        scene=depsgraph.scene
        vls=getattr(scene,'vertex_lit',None)

        # Colour-attribute selection changed -> drop caches and re-extract everything so the
        # new attribute is read into the vertex-colour buffers.
        global _FORCE_REEXTRACT
        if _FORCE_REEXTRACT:
            _FORCE_REEXTRACT = False
            self._mesh_cache.clear(); self._batch_dict.clear(); self._shadow_dict.clear()
            _PERSIST_SIG.clear()
            self._dirty = True; self._force_full = True
        # geometry lives only in the edit BMesh. Write it to a reused temp mesh (~0.5ms)
        # and extract from that, so geometry edits show in real time. One object only.
        eob = getattr(context, 'edit_object', None)
        if eob is not None and eob.type == 'MESH':
            try:
                import bmesh
                bm = bmesh.from_edit_mesh(eob.data)
                if getattr(self, '_edit_tmp', None) is None:
                    self._edit_tmp = bpy.data.meshes.new('_vlr_edit_tmp')
                bm.to_mesh(self._edit_tmp)
                data = _extract_mesh_data(eob, depsgraph, mesh=self._edit_tmp, attr_name=getattr(self,'_view_attr',''))
                if data:
                    self._mesh_cache[eob.name] = data
                    self._batch_dict[eob.name] = _build_object_slots(data)
            except Exception as e:
                if _DEBUG: print("[VertexLit] edit-mode extract:", e)
            self.tag_redraw()
            try: context.region.tag_redraw()
            except Exception: pass

        if self._dirty:
            self._rebuild(depsgraph,vls)

        sky   =tuple(vls.sky_color)    if vls else (0.05,0.07,0.10)
        ground=tuple(vls.ground_color) if vls else (0.03,0.02,0.02)
        bstr  =0.0
        u_shad=vls.use_shadows        if vls else False
        s_res =int(vls.shadow_resolution) if vls else 1024
        s_bias=vls.shadow_bias        if vls else 0.005
        s_dark=getattr(vls,'shadow_softness',1.5) if vls else 1.5   # PCF softness now

        lights=self._lights_cache
        # Objectless sun: cast shadows when the sun-shadow toggle is on AND the sun contributes.
        self._sun = _compute_sun(vls)
        sun_dir = self._sun[0]; sun_int = self._sun[2]
        do_shad = bool(u_shad) and sun_int > 0.0
        if not do_shad:
            self._shadow_dirty = False

        region=context.region; rv3d=context.region_data
        center,radius=self._bounds_cache
        if do_shad:
            sdist = getattr(vls, 'shadow_distance', 25.0) if vls else 25.0
            try: cam_pos = tuple(rv3d.view_matrix.inverted().translation)
            except Exception: cam_pos = (0.0, 0.0, 0.0)
            vproj = rv3d.window_matrix @ rv3d.view_matrix
            ls_mat, self._shadow_texel = _build_light_space_fit(
                sun_dir, vproj, cam_pos, sdist, s_res, radius)
            # Re-render the shadow map only when the fit changes (view / sun / distance).
            # Static view -> cached; orbiting -> re-fits. Geometry changes already flag dirty.
            _key = tuple(round(x, 4) for row in ls_mat for x in row)
            if _key != getattr(self, '_prev_ls_key', None):
                self._shadow_dirty = True
            self._prev_ls_key = _key
        else:
            self._shadow_texel = 0.0
            ls_mat = Matrix.Identity(4)
            self._prev_ls_key = None

        # Shadows pending -> one redraw so the shadow map re-renders this frame.
        if self._shadow_dirty and do_shad:
            self.tag_redraw()
            try: context.region.tag_redraw()
            except Exception: pass
        shad_tex=self._shadow_pass(ls_mat,s_res,depsgraph) if do_shad else self._dummy_depth

        gpu.state.viewport_set(0,0,region.width,region.height)
        try:
            fb=gpu.state.active_framebuffer_get()
            wc=scene.world.color if scene.world else None
            fb.clear(color=(wc[0],wc[1],wc[2],1.0) if wc else (0.08,0.08,0.08,1.0),depth=1.0)
        except Exception as e: print(f"[VertexLit] clear: {e}")

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        self._cull = 'BACK' if (vls and getattr(vls, 'backface_cull', True)) else 'NONE'
        gpu.state.face_culling_set(self._cull)

        view_proj=rv3d.window_matrix@rv3d.view_matrix
        self._film_transparent = False
        try: self._cam_pos = tuple(rv3d.view_matrix.inverted().translation)
        except Exception: self._cam_pos = (0.0, 0.0, 0.0)
        try: self._view_mat3 = rv3d.view_matrix.to_3x3()
        except Exception: self._view_mat3 = None
        mode='PIXEL'
        # Workbench studio key light follows the view (like Blender's Solid mode):
        # a fixed view-space direction rotated into world space each frame.
        try:
            kv=Vector((0.25,0.35,0.90)); kv.normalize()
            key_dir=tuple(rv3d.view_rotation @ kv)
        except Exception:
            key_dir=(0.3,0.4,0.86)
        studio=(key_dir, (1.0,1.0,1.0), (vls.key_intensity if vls else 0.8))
        # experimental splat clouds: cache matrices + scene lighting for the draw
        self._splat_vm = rv3d.view_matrix; self._splat_pm = rv3d.window_matrix
        self._splat_wh = (region.width, region.height)
        _sun = getattr(self, '_sun', ((0.0,0.0,1.0),(1.0,1.0,1.0),0.0,1.0))
        self._splat_light = ({
            'sky': sky, 'ground': ground, 'hemi': _sun[3],
            'sun_dir': _sun[0], 'sun_col': _sun[1], 'sun_int': _sun[2],
            'key_dir': studio[0], 'key_col': studio[1], 'key_int': studio[2],
        } if (vls is None or getattr(vls, 'splat_lit', True)) else None)
        # depth pass (M2) only needed to FEED AO; compositing uses the depth TEST in the colour pass.
        self._splat_need_depth = bool(vls and getattr(vls, 'use_ao', False))
        def _draw_objects():
            self._draw_batches(depsgraph, vls, view_proj, studio, ls_mat, sky, ground,
                               bstr, do_shad, s_bias, s_dark, shad_tex, lights, mode)
            self._draw_splats()

        # Route through the screen-space post pipeline if any effect is enabled;
        # otherwise draw straight to the viewport (default path, unchanged). Any
        # failure in the offscreen pipeline falls back to a direct draw.
        rw, rh = region.width, region.height
        post = getattr(self, '_post', None)
        if post is not None:
            try:
                proj = rv3d.window_matrix
                wc = scene.world.color if scene.world else None
                draw_scene, post_ctx = self._make_post_ctx(
                    depsgraph, vls, view_proj, rv3d.view_matrix.to_3x3(), proj,
                    rw, rh, wc, studio, ls_mat, sky, ground, bstr, lights,
                    do_shad=do_shad, s_bias=s_bias, s_soft=s_dark, shad_tex=shad_tex)
                final_tex, sw, sh = post.render(rw, rh, draw_scene, post_ctx, vls, blit=False)
                # Blit to the viewport THROUGH the scene's colour management (view transform,
                # look, exposure, gamma) so the viewport matches the F12 render. Depth/Normal
                # are data passes, not scene-referred colour -> blit them RAW (no tonemap).
                gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
                gpu.state.blend_set('NONE')
                _raw = getattr(vls, 'view_mode', 'TEXTURED') in ('DEPTH', 'NORMAL')
                if _raw:
                    draw_texture_2d(final_tex, (0, 0), rw, rh)
                else:
                    try:
                        self.bind_display_space_shader(scene)
                        draw_texture_2d(final_tex, (0, 0), rw, rh)
                        self.unbind_display_space_shader()
                    except Exception:
                        draw_texture_2d(final_tex, (0, 0), rw, rh)   # fallback: linear
                gpu.state.face_culling_set('NONE')
                if getattr(self, '_mat_pending', False) or getattr(self, '_geo_pending', False):
                    self.tag_redraw()
                    try: context.region.tag_redraw()
                    except Exception: pass
                return
            except Exception as e:
                global _post_err_shown
                if not _post_err_shown:
                    _post_err_shown = True
                    import traceback
                    print("[VertexLit] post pipeline failed -> direct draw. First-time traceback:")
                    traceback.print_exc()
                elif _DEBUG:
                    print("[VertexLit] post pipeline failed -> direct draw:", e)

        _draw_objects()

        gpu.state.depth_test_set('NONE')
        gpu.state.face_culling_set('NONE')
        gpu.state.depth_mask_set(False)
        # Materials still compiling -> keep redrawing so they upgrade progressively.
        if getattr(self, '_mat_pending', False) or getattr(self, '_geo_pending', False):
            self.tag_redraw()
            try: context.region.tag_redraw()
            except Exception: pass


_ENGINE_ID = 'VERTEX_LIT'
_patched_panels = []

def _compat_panels():
    """Panels a simple non-PBR engine should show: the set Workbench uses
    (incl. the material selector EEVEE_MATERIAL_PT_context_material) plus the
    node 'surface' panel so node materials are visible/editable in Properties."""
    extra = {'EEVEE_MATERIAL_PT_surface'}
    out = []
    for p in bpy.types.Panel.__subclasses__():
        ce = getattr(p, 'COMPAT_ENGINES', None)
        if not ce:
            continue
        if 'BLENDER_WORKBENCH' in ce or p.__name__ in extra:
            out.append(p)
    return out

def _register_panels():
    _patched_panels.clear()
    for p in _compat_panels():
        try:
            p.COMPAT_ENGINES.add(_ENGINE_ID)
            _patched_panels.append(p)
        except Exception:
            pass

def _unregister_panels():
    for p in _patched_panels:
        try: p.COMPAT_ENGINES.discard(_ENGINE_ID)
        except Exception: pass
    _patched_panels.clear()

def _release_gpu_caches():
    """Drop module-level GPU objects so leaving/re-entering rendered mode never
    accumulates stale-context shaders/textures (the 'chuggier each re-enter' leak).
    Everything is lazily rebuilt on the next draw."""
    global _shadow_shader, _shadow_map
    _main_shader.clear()
    _shadow_shader = None
    global _id_shader
    _id_shader = None
    _shadow_map = None
    _tex_cache.clear()
    # Persistent mesh/batch caches hold GPU batches tied to the (now gone) context.
    _PERSIST_MESH.clear(); _PERSIST_BATCH.clear(); _PERSIST_SHADOW.clear(); _PERSIST_SIG.clear()
    try:
        material_shader.invalidate()   # release compiled per-material programs
    except Exception:
        pass


def register():
    bpy.utils.register_class(VertexLitEngine)
    _register_panels()

def unregister():
    _unregister_panels()
    _release_gpu_caches()
    bpy.utils.unregister_class(VertexLitEngine)
