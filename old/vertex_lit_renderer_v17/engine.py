# vertex_lit_renderer/engine.py

import time
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .shaders import SHADOW_VERT, SHADOW_FRAG, MAIN_VERT, MAIN_FRAG
from .gi import build_scene_bvh, ProgressiveGI

MAX_LIGHTS = 8

# ── Shader singletons ─────────────────────────────────────────────────────────

_shadow_shader = None
_main_shader   = None

def _get_shadow_shader():
    global _shadow_shader
    if _shadow_shader is None:
        _shadow_shader = gpu.types.GPUShader(SHADOW_VERT, SHADOW_FRAG)
    return _shadow_shader

def _get_main_shader():
    global _main_shader
    if _main_shader is None:
        _main_shader = gpu.types.GPUShader(MAIN_VERT, MAIN_FRAG)
    return _main_shader

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
            print(f"[VertexLit] texture error ({image.name}): {e}")
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
    lights = []; ltype = {'POINT':0,'SUN':1,'SPOT':0,'AREA':0}
    for inst in depsgraph.object_instances:
        obj = inst.object
        if obj.type != 'LIGHT': continue
        ld  = obj.data
        mat = inst.matrix_world

        if ld.type == 'SUN':
            energy = ld.energy * energy_scale * 10.0
            radius = 1.0
        else:
            energy = ld.energy * energy_scale
            if getattr(ld, 'use_custom_distance', False):
                radius = float(ld.cutoff_distance)
            else:
                radius = 20.0

        lights.append({
            'pos':    tuple(mat.to_translation()),
            'dir':    tuple(mat.to_3x3() @ Vector((0,0,-1))),
            'color':  (float(ld.color.r), float(ld.color.g), float(ld.color.b)),
            'energy': energy,
            'type':   ltype.get(ld.type, 0),
            'radius': radius,
            'is_sun': ld.type == 'SUN',
            'matrix_world': mat.copy(),
        })
        if len(lights) >= MAX_LIGHTS: break
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

# ── Mesh helpers ──────────────────────────────────────────────────────────────

def _extract_mesh_data(obj, depsgraph):
    """
    Extract per-loop arrays from evaluated mesh.

    FIX (Blender 4.1+): tri.split_normals was removed. Use mesh.corner_normals
    indexed by loop index instead. Also explicitly calls calc_loop_triangles()
    since it is not guaranteed to be populated on new_from_object meshes.

    FIX: Also stores vert_co_local / vert_no_local (per original vertex, not
    per loop) so _rebuild can build GI world-space arrays without a second
    new_from_object call.
    """
    mesh = None
    try:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(
            eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
        if not mesh:
            return None

        # Blender 4.x: triangulation is not auto-computed on new_from_object.
        mesh.calc_loop_triangles()

        if not mesh.loop_triangles:
            bpy.data.meshes.remove(mesh)
            return None

        # Blender 4.1+ API: per-loop normals via corner_normals.
        # tri.split_normals was removed in 4.1.
        corner_normals = mesh.corner_normals

        mat = eval_obj.active_material
        tex = _get_gpu_tex(_find_base_texture(mat))
        default = [1.0, 1.0, 1.0, 1.0]
        if mat: c = mat.diffuse_color; default = [c[0], c[1], c[2], 1.0]

        vcol = {}
        if mesh.color_attributes:
            attr = None
            try: attr = mesh.color_attributes.active_color
            except Exception: pass
            if attr is None and len(mesh.color_attributes): attr = mesh.color_attributes[0]
            if attr and attr.domain == 'POINT':
                for idx, d in enumerate(attr.data):
                    c = d.color; vcol[idx] = [c[0], c[1], c[2], c[3] if len(c) > 3 else 1.0]

        uv_layer = mesh.uv_layers.active
        n_verts  = len(mesh.vertices)

        # Per-vertex local-space arrays — stored for GI use in _rebuild so we
        # don't need a second new_from_object call there.
        vert_co_local = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]
        vert_no_local = [(v.normal.x, v.normal.y, v.normal.z) for v in mesh.vertices]

        positions = []; normals = []; colors = []; uvs = []; vi_map = []

        for tri in mesh.loop_triangles:
            for corner in range(3):
                vi = tri.vertices[corner]
                li = tri.loops[corner]
                v  = mesh.vertices[vi]
                positions.append((v.co.x, v.co.y, v.co.z))
                # FIX: corner_normals[li] replaces tri.split_normals[corner]
                normals.append(tuple(corner_normals[li]))
                colors.append(vcol.get(vi, default))
                uvs.append(tuple(uv_layer.data[li].uv) if uv_layer else (0.0, 0.0))
                vi_map.append(vi)

        bpy.data.meshes.remove(mesh)
        return dict(
            positions=positions, normals=normals, colors=colors,
            uvs=uvs, vi_map=vi_map, texture=tex, n_verts=n_verts,
            vert_co_local=vert_co_local, vert_no_local=vert_no_local,
        )

    except Exception as e:
        print(f"[VertexLit] mesh extract error ({obj.name}): {e}")
        if mesh:
            try: bpy.data.meshes.remove(mesh)
            except Exception: pass
        return None


def _build_batch_from_cache(cached, gi_per_vert=None):
    """Build GPUBatch from cached mesh data. Fast — no mesh re-extraction."""
    shader   = _get_main_shader()
    vi_map   = cached['vi_map']
    n_v      = cached['n_verts']

    if gi_per_vert and len(gi_per_vert) == n_v:
        bounces = [gi_per_vert[vi] for vi in vi_map]
    else:
        bounces = [(0.0,0.0,0.0)] * len(vi_map)

    return batch_for_shader(shader,'TRIS',{
        'position':    cached['positions'],
        'normal':      cached['normals'],
        'vertColor':   cached['colors'],
        'texCoord':    cached['uvs'],
        'bounceColor': bounces,
    })


def _build_shadow_batch(obj, depsgraph, shader):
    mesh = None
    try:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(
            eval_obj, preserve_all_data_layers=False, depsgraph=depsgraph)
        if not mesh:
            return None
        mesh.calc_loop_triangles()
        if not mesh.loop_triangles:
            bpy.data.meshes.remove(mesh)
            return None
        positions = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]
        indices   = [(t.vertices[0], t.vertices[1], t.vertices[2])
                     for t in mesh.loop_triangles]
        batch = batch_for_shader(shader, 'TRIS', {'position': positions}, indices=indices)
        bpy.data.meshes.remove(mesh)
        return batch
    except Exception as e:
        print(f"[VertexLit] shadow batch ({obj.name}): {e}")
        if mesh:
            try: bpy.data.meshes.remove(mesh)
            except Exception: pass
        return None

# ── Render Engine ─────────────────────────────────────────────────────────────

class VertexLitEngine(bpy.types.RenderEngine):
    bl_idname='VERTEX_LIT'; bl_label='Vertex Lit'; bl_use_preview=False

    def _ensure_state(self):
        if getattr(self,'_state_ready',False): return
        self._dirty        = True
        self._mesh_cache   = {}
        self._batch_dict   = {}
        self._shadow_dict  = {}
        self._dummy_depth  = None
        self._white_tex    = None
        self._gi           = ProgressiveGI()
        # FIX: cache lights and scene bounds from _rebuild so view_draw
        # doesn't iterate the full depsgraph on every single draw call.
        self._lights_cache = []
        self._bounds_cache = (Vector((0,0,0)), 10.0)
        # FIX: suppress view_update dirty-flag during our own mesh ops
        # (new_from_object / remove triggers is_updated_geometry on a Mesh,
        # which would otherwise cause an infinite rebuild loop).
        self._rebuilding   = False
        self._state_ready  = True

    def _ensure_resources(self):
        if self._dummy_depth is None:
            self._dummy_depth=gpu.types.GPUTexture((1,1),format='DEPTH_COMPONENT32F')
        if self._white_tex is None:
            self._white_tex=gpu.types.GPUTexture((1,1),format='RGBA8')

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def update(self, data=None, depsgraph=None):
        if hasattr(self, '_gi'):
            self._gi.stop()

    def render(self, depsgraph):
        if hasattr(self, '_gi'):
            self._gi.stop()

    def free(self):
        if hasattr(self, '_gi'):
            self._gi.stop()

    # ── Update ────────────────────────────────────────────────────────────

    def view_update(self, context, depsgraph):
        self._ensure_state()

        # FIX: bpy.data.meshes.new_from_object() and remove() (called during
        # _rebuild) fire depsgraph updates with is_updated_geometry=True on a
        # bpy.types.Mesh. Without this guard the engine would mark _dirty=True
        # every frame and rebuild continuously (infinite loop → full lag).
        if self._rebuilding:
            return

        for update in depsgraph.updates:
            id_data = update.id
            if update.is_updated_geometry:
                if isinstance(id_data, (bpy.types.Object, bpy.types.Mesh)):
                    self._dirty = True
                    return
            if isinstance(id_data, bpy.types.Material):
                self._dirty = True
                return
            if isinstance(id_data, bpy.types.Image):
                _invalidate_tex(id_data.name)

    # ── Rebuild (geometry + GI restart) ──────────────────────────────────

    def _rebuild(self, depsgraph, vls):
        # FIX: guard so view_update ignores depsgraph noise from our own ops.
        self._rebuilding = True
        try:
            self._rebuild_inner(depsgraph, vls)
        finally:
            self._rebuilding = False

    def _rebuild_inner(self, depsgraph, vls):
        t0=time.time()
        self._gi.cancel()

        ss=_get_shadow_shader()
        use_gi     = vls.use_gi        if vls else True
        gi_samp    = vls.gi_samples    if vls else 16
        en_scale   = vls.energy_scale  if vls else 0.01
        lights     = _collect_lights(depsgraph, en_scale)

        # FIX: cache lights + bounds so view_draw doesn't re-iterate the
        # depsgraph on every frame (was the primary cause of viewport lag).
        self._lights_cache = lights
        self._bounds_cache = _scene_bounds(depsgraph)

        new_mesh={}; new_shadow={}; seen=set()

        for inst in depsgraph.object_instances:
            obj=inst.object
            if obj.type!='MESH' or obj.hide_get(): continue
            if obj.name in seen: continue
            seen.add(obj.name)

            data=_extract_mesh_data(obj,depsgraph)
            if data:
                new_mesh[obj.name]=data
                batch=_build_batch_from_cache(data)
                self._batch_dict[obj.name]=(batch,data['texture'])

            b=_build_shadow_batch(obj,depsgraph,ss)
            if b: new_shadow[obj.name]=b

        self._mesh_cache  = new_mesh
        self._shadow_dict = new_shadow
        self._dirty       = False
        print(f"[VertexLit] mesh rebuilt: {len(new_mesh)} objs  ({time.time()-t0:.2f}s)")

        if use_gi:
            bvh, face_albedo = build_scene_bvh(depsgraph)
            plain_lights = [{
                'pos':    tuple(l['pos']), 'dir': tuple(l['dir']),
                'color':  tuple(l['color']), 'energy': float(l['energy']),
                'type':   int(l['type']),  'radius': float(l['radius']),
            } for l in lights]

            # FIX: extract GI world-space vertex data from the already-cached
            # vert_co_local / vert_no_local instead of calling new_from_object
            # a second time for every mesh. Cuts rebuild time roughly in half
            # for GI-enabled scenes.
            gi_verts = {}
            gi_norms = {}
            for name, data in new_mesh.items():
                obj = bpy.data.objects.get(name)
                if obj is None:
                    continue
                inst_mat = obj.matrix_world
                mat3     = inst_mat.to_3x3()
                gi_verts[name] = [
                    tuple(inst_mat @ Vector(co))
                    for co in data['vert_co_local']
                ]
                gi_norms[name] = [
                    tuple(mat3 @ Vector(no))
                    for no in data['vert_no_local']
                ]

            scene_data=dict(bvh=bvh, face_albedo=face_albedo,
                            lights=plain_lights,
                            verts=gi_verts, normals=gi_norms)
            print(f"[VertexLit] Starting progressive GI  target={gi_samp} samples…")
            self._gi.start(scene_data, target_samples=gi_samp)

    # ── Apply GI update (fast — geometry stays cached) ────────────────────

    def _apply_gi_update(self, gi_data):
        for name, cached in self._mesh_cache.items():
            gi_per_vert = gi_data.get(name)
            if gi_per_vert is None: continue
            batch = _build_batch_from_cache(cached, gi_per_vert)
            tex   = cached['texture']
            self._batch_dict[name] = (batch, tex)

    # ── Shadow pass ───────────────────────────────────────────────────────

    def _shadow_pass(self, ls_mat, shad_res, depsgraph):
        smap=_get_shadow_map(shad_res); shader=_get_shadow_shader()
        with smap.fb.bind():
            smap.fb.clear(depth=1.0)
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            gpu.state.viewport_set(0,0,shad_res,shad_res)
            shader.bind()
            shader.uniform_float('uLightSpace',ls_mat)
            for inst in depsgraph.object_instances:
                obj=inst.object
                if obj.type!='MESH' or obj.hide_get(): continue
                batch=self._shadow_dict.get(obj.name)
                if batch is None: continue
                shader.uniform_float('uModel',inst.matrix_world)
                batch.draw(shader)
        return smap.tex

    # ── Main draw ─────────────────────────────────────────────────────────

    def view_draw(self, context, depsgraph):
        self._ensure_state()
        self._ensure_resources()

        scene=depsgraph.scene
        vls=getattr(scene,'vertex_lit',None)

        if self._dirty:
            self._rebuild(depsgraph, vls)

        if self._gi.has_update():
            gi_data, n = self._gi.get_update()
            self._apply_gi_update(gi_data)

        if self._gi.is_running:
            try:
                self.tag_redraw()
            except Exception:
                pass

        sky    = tuple(c*(vls.gi_bounce_strength if vls else 1.0)
                       for c in (tuple(vls.sky_color) if vls else (0.05,0.07,0.10)))
        ground = tuple(c*(vls.gi_bounce_strength if vls else 1.0)
                       for c in (tuple(vls.ground_color) if vls else (0.03,0.02,0.02)))
        en_sc  = vls.energy_scale       if vls else 0.01
        bstr   = vls.gi_bounce_strength if vls else 1.0
        u_shad = vls.use_shadows        if vls else True
        s_res  = int(vls.shadow_resolution) if vls else 1024
        s_bias = vls.shadow_bias        if vls else 0.005
        s_dark = vls.shadow_darkness    if vls else 0.25

        # FIX: use cached lights and bounds — no depsgraph iteration per frame.
        lights  = self._lights_cache
        sun     = next((l for l in lights if l['is_sun']),None)
        do_shad = u_shad and sun is not None
        center, radius = self._bounds_cache
        ls_mat  = _build_light_space(sun, center, radius) \
                  if do_shad else Matrix.Identity(4)
        shad_tex= self._shadow_pass(ls_mat,s_res,depsgraph) \
                  if do_shad else self._dummy_depth

        region=context.region; rv3d=context.region_data
        w,h=region.width,region.height
        gpu.state.viewport_set(0,0,w,h)
        try:
            fb=gpu.state.active_framebuffer_get()
            wc=scene.world.color if scene.world else None
            fb.clear(color=(wc[0],wc[1],wc[2],1.0) if wc
                     else (0.08,0.08,0.08,1.0), depth=1.0)
        except Exception as e: print(f"[VertexLit] clear: {e}")

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set('BACK')

        shader=_get_main_shader(); view_proj=rv3d.window_matrix@rv3d.view_matrix
        shader.bind()
        shader.uniform_float('uViewProj',    view_proj)
        shader.uniform_float('uLightSpace',  ls_mat)
        shader.uniform_float('uSkyColor',    sky)
        shader.uniform_float('uGroundColor', ground)
        shader.uniform_float('uBounceStrength', bstr)
        shader.uniform_int  ('uUseShadow',   1 if do_shad else 0)
        shader.uniform_float('uShadowBias',  s_bias)
        shader.uniform_float('uShadowDark',  s_dark)
        shader.uniform_sampler('uShadowMap', shad_tex)
        shader.uniform_int('uNumLights', len(lights))
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
            if obj.type!='MESH' or obj.hide_get(): continue
            entry=self._batch_dict.get(obj.name)
            if entry is None: continue
            batch,tex=entry
            shader.uniform_float('uModel', inst.matrix_world)
            # FIX: compute normal matrix on CPU and pass as uniform.
            # Was: transpose(inverse(mat3(uModel))) computed per-vertex in the
            # GPU shader — that's a matrix inversion for every vertex in the
            # scene every frame. For non-uniformly scaled objects this is
            # necessary, but it belongs on the CPU as a uniform.
            try:
                normal_mat = inst.matrix_world.to_3x3().inverted().transposed()
            except Exception:
                normal_mat = inst.matrix_world.to_3x3()  # fallback for singular matrices
            shader.uniform_float('uNormalMat', normal_mat)
            albedo=tex if tex is not None else self._white_tex
            shader.uniform_sampler('uAlbedo',albedo)
            shader.uniform_int('uHasTexture',1 if tex is not None else 0)
            batch.draw(shader)

        gpu.state.depth_test_set('NONE')
        gpu.state.face_culling_set('NONE')
        gpu.state.depth_mask_set(False)


def register():
    bpy.utils.register_class(VertexLitEngine)

def unregister():
    bpy.utils.unregister_class(VertexLitEngine)
