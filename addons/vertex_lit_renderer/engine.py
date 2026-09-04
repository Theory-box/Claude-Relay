# vertex_lit_renderer/engine.py

import time
import threading
import numpy as np
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .shaders import SHADOW_VERT, SHADOW_FRAG, MAIN_VERT, MAIN_FRAG, PHONG_VERT, PHONG_FRAG, WORKBENCH_FRAG
from .gi import ProgressiveGI
from . import material_shader
from . import fx

MAX_LIGHTS = 8
_DEBUG = True   # prints "[VertexLit] rebuild <- ..." naming what triggers a rebuild

# ── GI redraw timer ───────────────────────────────────────────────────────────
# Backup for self.tag_redraw() — forces redraws at 20 fps while GI runs.
# Uses bpy.data (always valid in timers) not bpy.context (may be None).

_gi_active = False
_last_draw_time = 0.0   # updated every view_draw; timer stops when this goes stale
_post_err_shown = False  # print the post-pipeline traceback only once

def _gi_redraw_timer():
    # Only force viewport redraws while GI is active AND a rendered viewport is
    # actually drawing (view_draw seen in the last 0.5s). This prevents the timer
    # from hammering redraws forever after the user leaves rendered mode.
    if _gi_active and (time.time() - _last_draw_time) < 0.5:
        try:
            for wm in bpy.data.window_managers:
                for window in wm.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
        except Exception:
            pass
    return 0.05

# ── Shader singletons ─────────────────────────────────────────────────────────

_shadow_shader = None
_main_shader   = {}   # shading mode -> GPUShader

def _get_shadow_shader():
    global _shadow_shader
    if _shadow_shader is None:
        _shadow_shader = gpu.types.GPUShader(SHADOW_VERT, SHADOW_FRAG)
    return _shadow_shader

def _get_main_shader(mode='VERTEX'):
    sh = _main_shader.get(mode)
    if sh is None:
        if mode == 'WORKBENCH':
            sh = gpu.types.GPUShader(PHONG_VERT, WORKBENCH_FRAG)
        elif mode == 'PIXEL':
            sh = gpu.types.GPUShader(PHONG_VERT, PHONG_FRAG)
        else:
            sh = gpu.types.GPUShader(MAIN_VERT, MAIN_FRAG)
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

def _extract_mesh_data(obj, depsgraph):
    """
    Read the depsgraph-evaluated mesh DIRECTLY (no new_from_object copy, no
    create/remove -> no depsgraph churn -> no self-triggered rebuild loop, and far
    faster on large scenes). All reads are bulk foreach_get + numpy (no Python loops).
    """
    try:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = getattr(eval_obj, 'data', None)
        if mesh is None or not hasattr(mesh, 'loop_triangles'):
            return None
        mesh.calc_loop_triangles()
        n_tris = len(mesh.loop_triangles)
        if n_tris == 0:
            return None

        mat_slot = eval_obj.active_material
        tex = _get_gpu_tex(_find_base_texture(mat_slot))
        default = [1.0, 1.0, 1.0, 1.0]
        mat_diffuse = (0.8, 0.8, 0.8)
        if mat_slot:
            c = mat_slot.diffuse_color
            default = [c[0], c[1], c[2], 1.0]
            mat_diffuse = (float(c[0]), float(c[1]), float(c[2]))

        n_verts = len(mesh.vertices)
        n_loops = len(mesh.loops)
        n_flat = n_tris * 3

        tv = np.empty(n_flat, dtype=np.int32); mesh.loop_triangles.foreach_get('vertices', tv)
        tl = np.empty(n_flat, dtype=np.int32); mesh.loop_triangles.foreach_get('loops', tl)
        vi_flat = tv; li_flat = tl

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
        vert_co_local = vc
        vert_no_local = vn

        uv_layer = mesh.uv_layers.active
        if uv_layer:
            uv_raw = np.empty(n_loops * 2, dtype=np.float32); uv_layer.data.foreach_get('uv', uv_raw)
            uvs = uv_raw.reshape(n_loops, 2)[li_flat]
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

        return dict(
            positions=positions, normals=normals, colors=colors,
            uvs=uvs, vi_map=vi_flat.tolist(), texture=tex, n_verts=n_verts,
            vert_co_local=vert_co_local, vert_no_local=vert_no_local,
            mat_diffuse=mat_diffuse, gen_min=gen_min, gen_scale=gen_scale,
        )
    except Exception as e:
        print(f"[VertexLit] extract error ({obj.name}): {e}")
        return None


def _build_batch_from_cache(cached, gi_per_vert=None):
    shader=_get_main_shader()
    vi_map=cached['vi_map']; n_v=cached['n_verts']
    if gi_per_vert and len(gi_per_vert) == n_v:
        gi_arr = np.array(gi_per_vert, dtype=np.float32)
        bounces = gi_arr[np.array(vi_map, dtype=np.int32)]
    else:
        bounces = np.zeros((len(vi_map), 3), dtype=np.float32)
    return batch_for_shader(shader,'TRIS',{
        'position':    cached['positions'],
        'normal':      cached['normals'],
        'vertColor':   cached['colors'],
        'texCoord':    cached['uvs'],
        'bounceColor': bounces,
    })


def _build_shadow_batch_from_cache(cached):
    """Build shadow batch from already-extracted vertex data — no extra new_from_object."""
    shader=_get_shadow_shader()
    positions=cached['vert_co_local']
    vi_map=cached['vi_map']
    n_tris=len(vi_map)//3
    indices=[(vi_map[i*3],vi_map[i*3+1],vi_map[i*3+2]) for i in range(n_tris)]
    return batch_for_shader(shader,'TRIS',{'position':positions},indices=indices)


def _build_bvh_from_cache(mesh_cache, objects):
    """
    Build world-space BVH from cached vert data.
    No new_from_object — uses vert_co_local transformed by matrix_world.
    """
    all_verts=[]; all_polys=[]; face_albedo=[]; v_offset=0
    for name,data in mesh_cache.items():
        obj=objects.get(name)
        if obj is None: continue
        mat4 = np.array(obj.matrix_world, dtype=np.float32)
        vc_local = data['vert_co_local']  # numpy (n_v, 3)
        n_v = len(vc_local)
        vc_h = np.ones((n_v, 4), dtype=np.float32)
        vc_h[:, :3] = vc_local
        wv = (mat4 @ vc_h.T).T[:, :3]
        all_verts.extend(map(tuple, wv.tolist()))
        vi_map=data['vi_map']
        alb=data['mat_diffuse']
        for i in range(0,len(vi_map),3):
            all_polys.append([vi_map[i]+v_offset,vi_map[i+1]+v_offset,vi_map[i+2]+v_offset])
            face_albedo.append(alb)
        v_offset+=len(data['vert_co_local'])
    if not all_verts: return None,[]
    bvh=BVHTree.FromPolygons(all_verts,all_polys,epsilon=1e-6)
    return bvh,face_albedo

# ── Render Engine ─────────────────────────────────────────────────────────────

class VertexLitEngine(bpy.types.RenderEngine):
    bl_idname='VERTEX_LIT'; bl_label='Vertex Lit'; bl_use_preview=False
    # Use Blender's STANDARD shader nodes (not a custom node system). Without this
    # (it defaults True), Blender detaches the Shader Editor from materials: it shows
    # a generic "Shader Nodetree", won't follow the selected object, and edits don't
    # reach the real material — so live-node changes appear to do nothing.
    bl_use_shading_nodes_custom = False

    def _ensure_state(self):
        if getattr(self,'_state_ready',False): return
        self._dirty            = True
        self._mesh_cache       = {}
        self._batch_dict       = {}
        self._shadow_dict      = {}
        self._dummy_depth      = None
        self._white_tex        = None
        self._gi               = ProgressiveGI()
        self._lights_cache     = []
        self._bounds_cache     = (Vector((0,0,0)),10.0)
        self._shadow_dirty     = True
        self._shadow_tex_cache = None
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
        if hasattr(self,'_gi'): self._gi.stop()

    def render(self, depsgraph):
        # F12 final image: render the scene from the active camera into an offscreen
        # (Workbench-style shading) and hand the pixels to Blender. Viewport-quality
        # only (no shadows/GI in the F12 path yet).
        if hasattr(self, '_gi'):
            try: self._gi.stop()
            except Exception: pass
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
        # CRITICAL: clear the module-level redraw flag, else _gi_redraw_timer keeps
        # forcing every 3D viewport to redraw at 20fps forever (view_draw — the only
        # place that resets it — stops being called once we leave rendered mode).
        global _gi_active
        _gi_active = False
        if hasattr(self, '_gi'):
            try: self._gi.stop()   # signal + join the GI worker thread
            except Exception: pass
        if getattr(self, '_post', None) is not None:
            try: self._post.free()
            except Exception: pass
            self._post = None
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
        global _gi_active
        self._ensure_state()

        if self._drain_cycles > 0:
            self._drain_cycles -= 1
            return
        # Time-based absorb: for a short window after a rebuild, ignore ALL
        # depsgraph updates. new_from_object/remove during extraction emit deferred
        # geometry/material events; without this they can re-trigger _dirty AFTER
        # the fixed cycle-drain expires -> the 0.9s rebuild loop seen in the console.
        if time.time() - getattr(self, '_rebuild_time', 0.0) < 0.4:
            return

        vls_lb = getattr(depsgraph.scene, 'vertex_lit', None)
        live = bool(getattr(vls_lb, 'use_live_nodes', False)) if vls_lb else False

        for update in depsgraph.updates:
            id_data=update.id
            if update.is_updated_geometry:
                if isinstance(id_data,bpy.types.Mesh):
                    if getattr(id_data,'users',0)>0:
                        if _DEBUG: print("[VertexLit] rebuild <- mesh geom:", id_data.name)
                        self._dirty=True; self._shadow_dirty=True
                        _gi_active=True; return
                if isinstance(id_data,bpy.types.Object) and id_data.type=='MESH':
                    if id_data.name not in self._mesh_cache:
                        if _DEBUG: print("[VertexLit] rebuild <- new object:", id_data.name)
                        self._dirty=True; self._shadow_dirty=True
                        _gi_active=True; return
                if isinstance(id_data,bpy.types.Object) and id_data.type=='LIGHT':
                    if _DEBUG: print("[VertexLit] rebuild <- light geom:", id_data.name)
                    self._dirty=True; self._shadow_dirty=True
                    _gi_active=True; return
            if isinstance(id_data,bpy.types.Material):
                material_shader.mark_dirty(id_data.name)
                if live:
                    # Live path reads the node graph at DRAW time -> only the tiny
                    # per-material shader recompiles. NO full geometry rebuild (that
                    # re-extract + GI restart on every material edit is the chug).
                    _gi_active=True
                    try: context.region.tag_redraw()
                    except Exception: pass
                    return
                if _DEBUG: print("[VertexLit] rebuild <- material:", id_data.name)
                self._dirty=True; self._shadow_dirty=True
                _gi_active=True; return
            if update.is_updated_transform:
                if isinstance(id_data, bpy.types.Object):
                    if id_data.type == 'LIGHT':
                        self._dirty = True
                        self._shadow_dirty = True
                        _gi_active = True; return
                    elif id_data.type == 'MESH':
                        self._shadow_dirty = True
                        _gi_active = True
            if isinstance(id_data,bpy.types.Image):
                _invalidate_tex(id_data.name)

    # ── Rebuild ───────────────────────────────────────────────────────────

    def _rebuild(self, depsgraph, vls):
        self._rebuild_inner(depsgraph, vls)
        self._drain_cycles=4      # absorb immediate deferred events
        self._rebuild_time=time.time()  # + time-based absorb window (see view_update)

    def _rebuild_inner(self, depsgraph, vls):
        t0=time.time()
        self._gi.cancel()

        use_gi  =vls.use_gi        if vls else True
        gi_samp        = vls.gi_samples      if vls else 128
        rays_per_pass  = vls.gi_rays_per_pass if vls else 4
        thread_pause   = vls.gi_thread_pause  if vls else 0.001
        en_scale=vls.energy_scale  if vls else 0.01
        lights  =_collect_lights(depsgraph,en_scale)

        self._lights_cache=lights
        self._bounds_cache=_scene_bounds(depsgraph)

        new_mesh={}; new_shadow={}; seen=set()

        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type!='MESH': continue
            if not inst.show_self: continue          # respect hidden objects/collections
            if obj.name in seen: continue
            seen.add(obj.name)

            data=_extract_mesh_data(obj,depsgraph)  # ONE new_from_object per object
            if data:
                new_mesh[obj.name]=data
                self._batch_dict[obj.name]=(_build_batch_from_cache(data), data['texture'], data['gen_min'], data['gen_scale'])
                # Shadow batch built from cached data — no extra new_from_object
                sb=_build_shadow_batch_from_cache(data)
                if sb: new_shadow[obj.name]=sb

        self._mesh_cache  =new_mesh
        self._shadow_dict =new_shadow
        self._dirty       =False
        self._shadow_dirty=True
        if _DEBUG:
            gi_threads=sum(1 for t in threading.enumerate() if t.name=='VertexLit-GI')
            print("[VertexLit] rebuilt {} objs ({:.2f}s) | GI-threads={} meshes={} shader-cache={}".format(
                len(new_mesh), time.time()-t0, gi_threads,
                len(bpy.data.meshes), len(material_shader._prog_cache)))
        else:
            print(f"[VertexLit] rebuilt {len(new_mesh)} objs ({time.time()-t0:.2f}s)")

        if use_gi:
            # BVH built from cached vertex data — no extra new_from_object
            bpy_objects={name:bpy.data.objects.get(name) for name in new_mesh}
            bvh,face_albedo=_build_bvh_from_cache(new_mesh,bpy_objects)
            if bvh is None: return

            plain_lights=[{
                'pos':tuple(l['pos']),'dir':tuple(l['dir']),
                'color':tuple(l['color']),'energy':float(l['energy']),
                'type':int(l['type']),'radius':float(l['radius']),
            } for l in lights]

            gi_verts={}; gi_norms={}
            for name,data in new_mesh.items():
                obj=bpy_objects.get(name)
                if obj is None: continue
                m=obj.matrix_world; m3=m.to_3x3()
                mat4_np = np.array(m, dtype=np.float32)
                mat3_np = np.array(m3, dtype=np.float32)
                vc = data['vert_co_local']  # numpy (n_v, 3)
                vn = data['vert_no_local']  # numpy (n_v, 3)
                n_v = len(vc)
                vc_h = np.ones((n_v, 4), dtype=np.float32); vc_h[:,:3] = vc
                gi_verts[name] = (mat4_np @ vc_h.T).T[:,:3].tolist()
                gi_norms[name] = (mat3_np @ vn.T).T.tolist()

            self._gi.start(
                dict(bvh=bvh, face_albedo=face_albedo,
                     lights=plain_lights, verts=gi_verts, normals=gi_norms,
                     rays_per_pass=rays_per_pass,
                     thread_pause=thread_pause / 1000.0),  # ms → seconds
                target_samples=gi_samp)
            print(f"[VertexLit] GI started ({gi_samp} samples)")

    # ── Apply GI ──────────────────────────────────────────────────────────

    def _apply_gi_update(self, gi_data):
        for name,cached in self._mesh_cache.items():
            gv=gi_data.get(name)
            if gv is None: continue
            self._batch_dict[name]=(_build_batch_from_cache(cached,gv), cached['texture'], cached.get('gen_min',(0.0,0.0,0.0)), cached.get('gen_scale',(1.0,1.0,1.0)))

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
        # Programs differ by shading mode (Workbench/Gouraud/Phong) and don't all
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
        # Scene-light / shadow / GI uniforms (present only in VERTEX/PIXEL programs)
        sf('uLightSpace', ls_mat); sf('uSkyColor', sky); sf('uGroundColor', ground)
        sf('uBounceStrength', bstr); si('uUseShadow', 1 if do_shad else 0)
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
        use_live=bool(getattr(vls,'use_live_nodes',False))
        frame_done=set(); params_done=set()

        def _ensure_frame(sh):
            sh.bind()
            if id(sh) not in frame_done:
                self._apply_frame_uniforms(sh, view_proj, ls_mat, sky, ground, bstr,
                                           do_shad, s_bias, s_dark, shad_tex, lights, studio)
                frame_done.add(id(sh))

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set('BACK')
        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type!='MESH': continue
            if not inst.show_self: continue
            entry=self._batch_dict.get(obj.name)
            if entry is None: continue
            batch,tex=entry[0],entry[1]
            gmin=entry[2] if len(entry)>2 else (0.0,0.0,0.0)
            gsc =entry[3] if len(entry)>3 else (1.0,1.0,1.0)

            try:   normal_mat=inst.matrix_world.to_3x3().inverted().transposed()
            except Exception: normal_mat=inst.matrix_world.to_3x3()

            prog=None
            if use_live:
                mat=getattr(obj,'active_material',None)
                if mat is not None and getattr(mat,'use_nodes',False):
                    p=material_shader.get_program(mat, mode)
                    if p and not p['failed'] and p['shader'] is not None:
                        prog=p

            if prog is not None:
                sh=prog['shader']
                _ensure_frame(sh)
                if id(sh) not in params_done:
                    nt=mat.node_tree if mat else None
                    for p in prog['params']:
                        try: sh.uniform_float(p.uniform, p.value(nt))
                        except Exception: pass
                    params_done.add(id(sh))
                sh.uniform_float('uModel',inst.matrix_world)
                sh.uniform_float('uNormalMat',normal_mat)
                try: sh.uniform_float('uGenMin',gmin); sh.uniform_float('uGenScale',gsc)
                except Exception: pass
                for uni,image in prog['samplers']:
                    gtex=_get_gpu_tex(image)
                    if gtex is not None:
                        try: sh.uniform_sampler(uni,gtex)
                        except Exception: pass
                batch.draw(sh)
            else:
                _ensure_frame(legacy)
                legacy.uniform_float('uModel',inst.matrix_world)
                legacy.uniform_float('uNormalMat',normal_mat)
                try: legacy.uniform_float('uGenMin',gmin); legacy.uniform_float('uGenScale',gsc)
                except Exception: pass
                legacy.uniform_sampler('uAlbedo',  tex if tex is not None else self._white_tex)
                legacy.uniform_int('uHasTexture',  1 if tex is not None else 0)
                batch.draw(legacy)

    # ── Main draw ─────────────────────────────────────────────────────────

    def view_draw(self, context, depsgraph):
        self._ensure_state()
        self._ensure_resources()

        scene=depsgraph.scene
        vls=getattr(scene,'vertex_lit',None)

        if self._dirty:
            self._rebuild(depsgraph,vls)

        gi_on = bool(vls and vls.use_gi)
        if gi_on and self._gi.has_update():
            gi_data,n=self._gi.get_update()
            self._apply_gi_update(gi_data)
            if _DEBUG: print(f"[VertexLit] GI sample {n} applied")

        # Drive continuous redraws only while GI is actually accumulating, or a
        # shadow re-render is pending. With GI off (the default) nothing here forces
        # redraws — the viewport stays idle like Workbench.
        global _gi_active, _last_draw_time
        _last_draw_time = time.time()
        _gi_active=(gi_on and self._gi.is_running) or self._shadow_dirty
        if _gi_active:
            self.tag_redraw()
            try: context.region.tag_redraw()
            except Exception: pass

        # Hemisphere ambient (sky/ground) is its OWN control — it must NOT be scaled
        # by gi_bounce_strength, or lowering GI bounce silently fades these colours to
        # black and the pickers appear to "do nothing". gi_bounce_strength now only
        # scales the GI bounce term (bstr -> uBounceStrength).
        sky   =tuple(vls.sky_color)    if vls else (0.05,0.07,0.10)
        ground=tuple(vls.ground_color) if vls else (0.03,0.02,0.02)
        bstr  =vls.gi_bounce_strength if vls else 1.0
        u_shad=vls.use_shadows        if vls else True
        s_res =int(vls.shadow_resolution) if vls else 1024
        s_bias=vls.shadow_bias        if vls else 0.005
        s_dark=vls.shadow_darkness    if vls else 0.25

        lights=self._lights_cache
        sun=next((l for l in lights if l['is_sun']),None)
        do_shad=u_shad and sun is not None
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
                post_ctx = {
                    'proj': proj, 'inv_proj': proj.inverted(),
                    'texel': (1.0/max(rw,1), 1.0/max(rh,1)),
                    'clear_color': (wc[0],wc[1],wc[2],1.0) if wc else (0.08,0.08,0.08,1.0),
                    'ao_radius':   (vls.ao_radius   if vls else 0.5),
                    'ao_strength': (vls.ao_strength if vls else 1.0),
                    'ao_bias':     (vls.ao_bias     if vls else 0.02),
                }
                post.render(rw, rh, _draw_objects, post_ctx, vls)
                gpu.state.depth_test_set('NONE')
                gpu.state.face_culling_set('NONE')
                gpu.state.depth_mask_set(False)
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
    _shadow_map = None
    _tex_cache.clear()
    try:
        material_shader.invalidate()   # release compiled per-material programs
    except Exception:
        pass


def register():
    bpy.utils.register_class(VertexLitEngine)
    _register_panels()
    if not bpy.app.timers.is_registered(_gi_redraw_timer):
        bpy.app.timers.register(_gi_redraw_timer, persistent=True)

def unregister():
    if bpy.app.timers.is_registered(_gi_redraw_timer):
        bpy.app.timers.unregister(_gi_redraw_timer)
    _unregister_panels()
    _release_gpu_caches()
    bpy.utils.unregister_class(VertexLitEngine)
