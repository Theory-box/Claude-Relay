# vertex_lit_renderer/engine.py

import time
import threading
import numpy as np
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .shaders import SHADOW_VERT, SHADOW_FRAG, PHONG_VERT, PHONG_FRAG, WORKBENCH_FRAG, ID_VERT, ID_FRAG, NORMAL_VERT, NORMAL_FRAG
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

# ── Mesh extraction (one new_from_object call per object, everything derived from it) ──

def _extract_mesh_data(obj, depsgraph, mesh=None):
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
    bl_idname='VERTEX_LIT'; bl_label='Vertex Lit'; bl_use_preview=False
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
            cam = scene.camera

            self._ensure_state(); self._ensure_resources()
            self._dirty = True
            self._rebuild(depsgraph, vls)

            result = self.begin_result(0, 0, w, h)
            rl = result.layers[0].passes["Combined"]

            if cam is None or cam.type != 'CAMERA':
                rl.rect = [[0.0, 0.0, 0.0, 1.0]] * (w * h)
                self.end_result(result)
                return

            view = cam.matrix_world.inverted()
            proj = cam.calc_matrix_camera(depsgraph, x=w, y=h)
            view_proj = proj @ view
            try:
                kv = Vector((0.25, 0.35, 0.90)); kv.normalize()
                key_dir = tuple(cam.matrix_world.to_quaternion() @ kv)
            except Exception:
                key_dir = (0.3, 0.4, 0.86)
            studio = (key_dir, (0.9, 0.9, 0.9), 0.35)
            mode = getattr(vls, 'shading_mode', 'WORKBENCH')

            offscreen = gpu.types.GPUOffScreen(w, h)
            arr = None
            try:
                with offscreen.bind():
                    fb = gpu.state.active_framebuffer_get()
                    wc = scene.world.color if scene.world else None
                    fb.clear(color=(wc[0], wc[1], wc[2], 1.0) if wc else (0.05, 0.05, 0.05, 1.0),
                             depth=1.0)
                    self._draw_batches(depsgraph, vls, view_proj, studio, Matrix.Identity(4),
                                       (0.05, 0.07, 0.10), (0.03, 0.02, 0.02), 1.0,
                                       False, 0.005, 0.25, self._dummy_depth,
                                       self._lights_cache, mode)
                    buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
                buf.dimensions = w * h * 4
                arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)
                arr = np.flipud(arr)               # Blender image is bottom-up
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
        t0=time.time()

        en_scale=vls.energy_scale  if vls else 0.01
        lights  =_collect_lights(depsgraph,en_scale)
        self._lights_cache=lights
        self._bounds_cache=_scene_bounds(depsgraph)

        # Current visible mesh objects in the scene.
        current={}
        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type!='MESH': continue
            if not inst.show_self: continue
            if obj.name not in current: current[obj.name]=obj

        # 1) Drop objects that no longer exist / were hidden.
        for name in list(self._mesh_cache.keys()):
            if name not in current:
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
        for name in to_do:
            if done > 0 and time.time() > budget_end:
                remaining.append(name)
                continue
            obj=current.get(name)
            if obj is None: continue
            data=_extract_mesh_data(obj,depsgraph)
            if data:
                self._mesh_cache[name]=data
                self._batch_dict[name]=_build_object_slots(data)
                try:
                    eo=obj.evaluated_get(depsgraph); me=getattr(eo,'data',None)
                    _PERSIST_SIG[name]=_geo_sig(obj, me) if me else None
                except Exception:
                    pass
                if want_shadow:
                    sb=_build_shadow_batch_from_cache(data)
                    if sb: self._shadow_dict[name]=sb
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
                batch = self._shadow_dict.get(obj.name)
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
        key_dir, key_col, ambient = studio
        sf('uKeyDir', key_dir); sf('uKeyCol', key_col); sf('uAmbient', ambient)
        # Scene-light / shadow uniforms (present only in the PIXEL program)
        sf('uLightSpace', ls_mat); sf('uSkyColor', sky); sf('uGroundColor', ground)
        si('uUseShadow', 1 if do_shad else 0)
        sf('uShadowBias', s_bias); sf('uShadowDark', s_dark); ss('uShadowMap', shad_tex)
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
        gpu.state.face_culling_set('BACK')

        # Resolve each material's program at most ONCE per frame (materials are shared
        # across many objects; the peek can run topo_signature for dirty materials, so
        # doing it per-object per-frame is a real cost while editing).
        frame_progs = {}
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
            slots=self._batch_dict.get(obj.name)
            if not slots: continue
            cached=self._mesh_cache.get(obj.name)
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
                is_transp = mat is not None and (
                    getattr(mat, 'surface_render_method', '') == 'BLENDED'
                    or getattr(mat, 'blend_method', 'OPAQUE') == 'BLEND')
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
            for _d, args in transparent:
                _draw_one(*args)
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)

    # ── Main draw ─────────────────────────────────────────────────────────

    def view_draw(self, context, depsgraph):
        self._ensure_state()
        self._ensure_resources()

        scene=depsgraph.scene
        vls=getattr(scene,'vertex_lit',None)

        # Edit mode: the evaluated mesh is empty and obj.data is stale — the live
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
                data = _extract_mesh_data(eob, depsgraph, mesh=self._edit_tmp)
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
        s_dark=vls.shadow_darkness    if vls else 0.25

        lights=self._lights_cache
        sun=next((l for l in lights if l['is_sun']),None)
        do_shad=u_shad and sun is not None
        # Shadows off -> clear any stale shadow-dirty so it can't force endless idle
        # redraws (the shadow pass that clears it only runs when shadows are on).
        if not do_shad:
            self._shadow_dirty=False

        # Shadows pending -> one redraw so the shadow map re-renders this frame.
        if self._shadow_dirty and do_shad:
            self.tag_redraw()
            try: context.region.tag_redraw()
            except Exception: pass
        center,radius=self._bounds_cache
        ls_mat=_build_light_space(sun,center,radius) if do_shad else Matrix.Identity(4)
        shad_tex=self._shadow_pass(ls_mat,s_res,depsgraph) if do_shad else self._dummy_depth

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

        view_proj=rv3d.window_matrix@rv3d.view_matrix
        mode=getattr(vls,'shading_mode','WORKBENCH')
        # Workbench studio key light follows the view (like Blender's Solid mode):
        # a fixed view-space direction rotated into world space each frame.
        try:
            kv=Vector((0.25,0.35,0.90)); kv.normalize()
            key_dir=tuple(rv3d.view_rotation @ kv)
        except Exception:
            key_dir=(0.3,0.4,0.86)
        studio=(key_dir, (0.9,0.9,0.9), 0.35)
        def _draw_objects():
            self._draw_batches(depsgraph, vls, view_proj, studio, ls_mat, sky, ground,
                               bstr, do_shad, s_bias, s_dark, shad_tex, lights, mode)

        # Route through the screen-space post pipeline if any effect is enabled;
        # otherwise draw straight to the viewport (default path, unchanged). Any
        # failure in the offscreen pipeline falls back to a direct draw.
        rw, rh = region.width, region.height
        post = getattr(self, '_post', None)
        if post is not None and post.any_enabled(vls):
            try:
                proj = rv3d.window_matrix
                wc = scene.world.color if scene.world else None
                # AO object exclusion: only build the occluder-draw callback if AO is on
                # AND at least one object is flagged (otherwise AO uses the gbuffer depth).
                ao_occluders = None
                if vls and getattr(vls, 'use_ao', False):
                    any_excl = any(getattr(i.object, 'vlr_ao_exclude', False)
                                   for i in depsgraph.object_instances if i.object.type == 'MESH')
                    if any_excl:
                        def ao_occluders():
                            sh = _get_main_shader(mode); sh.bind()
                            try: sh.uniform_float('uViewProj', view_proj)
                            except Exception: pass
                            gpu.state.face_culling_set('BACK')
                            for i in depsgraph.object_instances:
                                o = i.object
                                if o.type != 'MESH' or not i.show_self: continue
                                if getattr(o, 'vlr_ao_exclude', False): continue
                                sl = self._batch_dict.get(o.name)
                                if not sl: continue
                                try: sh.uniform_float('uModel', i.matrix_world)
                                except Exception: pass
                                for b, _mn, _tx in sl:
                                    try: b.draw(sh)
                                    except Exception: pass
                # Object-ID pass (outline + cavity both use it).
                ids_cb = None
                if vls and (getattr(vls, 'use_outline', False) or getattr(vls, 'use_cavity', False)):
                    def ids_cb():
                        sh = _get_id_shader(); sh.bind()
                        try: sh.uniform_float('uViewProj', view_proj)
                        except Exception: pass
                        gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
                        gpu.state.face_culling_set('BACK')
                        idx = 1
                        for i in depsgraph.object_instances:
                            o = i.object
                            if o.type != 'MESH' or not i.show_self: continue
                            sl = self._batch_dict.get(o.name)
                            if not sl: continue
                            if getattr(o, 'vlr_outline_exclude', False):
                                col = (1.0, 1.0, 1.0)   # reserved id -> no outline
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
                # View-space normal pass for the Cavity (curvature) effect.
                normals_cb = None
                if vls and getattr(vls, 'use_cavity', False):
                    view_mat3 = rv3d.view_matrix.to_3x3()
                    def normals_cb():
                        sh = _get_normal_shader(); sh.bind()
                        try:
                            sh.uniform_float('uViewProj', view_proj)
                            sh.uniform_float('uViewMat3', view_mat3)
                        except Exception: pass
                        gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
                        gpu.state.face_culling_set('BACK')
                        for i in depsgraph.object_instances:
                            o = i.object
                            if o.type != 'MESH' or not i.show_self: continue
                            sl = self._batch_dict.get(o.name)
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
                post_ctx = {
                    'proj': proj, 'inv_proj': proj.inverted(),
                    'texel': (1.0/max(rw,1), 1.0/max(rh,1)),
                    'clear_color': (wc[0],wc[1],wc[2],1.0) if wc else (0.08,0.08,0.08,1.0),
                    'draw_ao_occluders': ao_occluders,
                    'draw_object_ids': ids_cb,
                    'draw_view_normals': normals_cb,
                    'ao_radius':   (vls.ao_radius   if vls else 0.5),
                    'ao_strength': (vls.ao_strength if vls else 1.0),
                    'ao_bias':     (vls.ao_bias     if vls else 0.02),
                    'ao_samples':  (int(vls.ao_samples) if vls else 16),
                    'cavity_ridge':  (vls.cavity_ridge  if vls else 1.0),
                    'cavity_valley': (vls.cavity_valley if vls else 1.0),
                    'outline_size':      (vls.outline_size      if vls else 1.5),
                    'outline_color':     (tuple(vls.outline_color) if vls else (0.0,0.0,0.0)),
                }
                post.render(rw, rh, _draw_objects, post_ctx, vls)
                gpu.state.depth_test_set('NONE')
                gpu.state.face_culling_set('NONE')
                gpu.state.depth_mask_set(False)
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
