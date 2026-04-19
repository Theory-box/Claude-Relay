# vertex_lit_renderer/engine.py

import time
import numpy as np
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

    # Try depsgraph instances first, fall back to scene objects
    candidates = []
    for inst in depsgraph.object_instances:
        obj = inst.object
        if obj.type == 'LIGHT':
            candidates.append((obj, inst.matrix_world))

    if not candidates:
        # Fallback: iterate scene objects directly
        for obj in depsgraph.scene.objects:
            if obj.type == 'LIGHT' and not obj.hide_viewport:
                candidates.append((obj, obj.matrix_world))

    for obj, mat in candidates:
        ld = obj.data
        if ld.type == 'SUN':
            energy = ld.energy * energy_scale
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
    Extract mesh data using numpy foreach_get (~28x faster than Python loops).
    Stores numpy arrays so batch_for_shader receives them without conversion.
    """
    mesh = None
    try:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(
            eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
        if not mesh:
            return None

        mesh.calc_loop_triangles()
        n_tris = len(mesh.loop_triangles)
        if n_tris == 0:
            bpy.data.meshes.remove(mesh); return None

        n_verts = len(mesh.vertices)
        n_flat  = n_tris * 3

        # ── Positions & normals via foreach_get (bulk C-level read) ─────────
        vc = np.empty(n_verts * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', vc)
        vc = vc.reshape(n_verts, 3)

        vn = np.empty(n_verts * 3, dtype=np.float32)
        mesh.vertices.foreach_get('normal', vn)
        vn = vn.reshape(n_verts, 3)

        tv = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('vertices', tv)
        tv = tv.reshape(n_tris, 3)

        tl = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('loops', tl)
        tl = tl.reshape(n_tris, 3)

        vi_flat   = tv.ravel()
        positions = vc[vi_flat]
        normals   = vn[vi_flat]

        # ── UVs ─────────────────────────────────────────────────────────────
        uv_layer = mesh.uv_layers.active
        if uv_layer:
            n_loops  = len(mesh.loops)
            uv_raw   = np.empty(n_loops * 2, dtype=np.float32)
            uv_layer.data.foreach_get('uv', uv_raw)
            uvs = uv_raw.reshape(n_loops, 2)[tl.ravel()]
        else:
            uvs = np.zeros((n_flat, 2), dtype=np.float32)

        # ── Material colour + vertex colours ────────────────────────────────
        mat = eval_obj.active_material
        tex = _get_gpu_tex(_find_base_texture(mat))
        if mat:
            c = mat.diffuse_color
            base_col = np.array([c[0], c[1], c[2], 1.0], dtype=np.float32)
        else:
            base_col = np.ones(4, dtype=np.float32)

        colors = np.tile(base_col, (n_flat, 1))

        if mesh.color_attributes:
            attr = None
            try: attr = mesh.color_attributes.active_color
            except Exception: pass
            if attr is None and len(mesh.color_attributes):
                attr = mesh.color_attributes[0]
            if attr and attr.domain == 'POINT':
                col_raw = np.empty(n_verts * 4, dtype=np.float32)
                attr.data.foreach_get('color', col_raw)
                colors = col_raw.reshape(n_verts, 4)[vi_flat]

        # ── GI / BVH cache (no second new_from_object needed) ───────────────
        if mat:
            c = mat.diffuse_color
            alb = (float(c[0]), float(c[1]), float(c[2]))
        else:
            alb = (0.8, 0.8, 0.8)

        bpy.data.meshes.remove(mesh)
        return dict(
            positions=positions,        # np (n_flat, 3)
            normals=normals,            # np (n_flat, 3)
            colors=colors,             # np (n_flat, 4)
            uvs=uvs,                   # np (n_flat, 2)
            vi_map=vi_flat,            # np (n_flat,)
            texture=tex, n_verts=n_verts,
            vert_co_local=vc,          # np (n_verts, 3)
            vert_no_local=vn,          # np (n_verts, 3)
            bvh_tris=tv.tolist(),      # list for BVHTree
            face_albedo=[alb] * n_tris,
        )

    except Exception as e:
        import traceback
        print(f"[VertexLit] extract error ({obj.name}): {e}")
        traceback.print_exc()
        if mesh:
            try: bpy.data.meshes.remove(mesh)
            except Exception: pass
        return None


def _build_batch_from_cache(cached, gi_per_vert=None):
    shader = _get_main_shader()
    vi_map = cached['vi_map']
    n_v    = cached['n_verts']
    n_flat = len(vi_map)

    if gi_per_vert and len(gi_per_vert) == n_v:
        gi_arr  = np.array(gi_per_vert, dtype=np.float32)
        bounces = gi_arr[vi_map]
    else:
        bounces = np.zeros((n_flat, 3), dtype=np.float32)

    return batch_for_shader(shader, 'TRIS', {
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
        if not mesh or not mesh.loop_triangles:
            if mesh: bpy.data.meshes.remove(mesh)
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
        self._lights_dirty = False
        self._shadow_dirty = True    # re-render shadow map on first draw
        self._rebuilding   = False   # Bug 2: guard against self-triggered rebuilds
        self._mesh_cache   = {}
        self._batch_dict   = {}
        self._shadow_dict  = {}
        self._dummy_depth  = None
        self._white_tex    = None
        self._gi           = ProgressiveGI()
        # Bug 3: cached scene data (set by _rebuild, read by view_draw)
        self._lights       = []
        self._sun          = None
        self._ls_matrix    = Matrix.Identity(4)
        self._state_ready  = True

    def _ensure_resources(self):
        if self._dummy_depth is None:
            self._dummy_depth=gpu.types.GPUTexture((1,1),format='DEPTH_COMPONENT32F')
        if self._white_tex is None:
            self._white_tex=gpu.types.GPUTexture((1,1),format='RGBA8')

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def update(self, data=None, depsgraph=None):
        """Called before render() — stop GI thread so it doesn't conflict."""
        if hasattr(self, '_gi'):
            self._gi.stop()

    def render(self, depsgraph):
        """F12 render — not implemented (viewport only). Just stops GI thread."""
        if hasattr(self, '_gi'):
            self._gi.stop()

    def free(self):
        """Called when Blender frees this engine instance."""
        if hasattr(self, '_gi'):
            self._gi.stop()

    # ── Update ────────────────────────────────────────────────────────────

    def view_update(self, context, depsgraph):
        self._ensure_state()
        if getattr(self, '_rebuilding', False):
            return
        for update in depsgraph.updates:
            id_data = update.id
            if update.is_updated_geometry:
                if isinstance(id_data, (bpy.types.Object, bpy.types.Mesh)):
                    self._dirty = True
                    return
            if update.is_updated_transform:
                if isinstance(id_data, bpy.types.Object) and id_data.type == 'MESH':
                    self._shadow_dirty = True  # caster moved → re-render shadow
            if isinstance(id_data, bpy.types.Light):
                self._lights_dirty = True
            if isinstance(id_data, bpy.types.Material):
                self._dirty = True
                return
            if isinstance(id_data, bpy.types.Image):
                _invalidate_tex(id_data.name)

    # ── Rebuild (geometry + GI restart) ──────────────────────────────────

    def _cache_lights(self, depsgraph, en_scale, use_shadows, shadow_res):
        """Collect lights and compute shadow matrix. Bug 3: called once, cached."""
        self._lights = _collect_lights(depsgraph, en_scale)
        self._sun    = next((l for l in self._lights if l['is_sun']), None)
        do_shad      = use_shadows and self._sun is not None
        if do_shad:
            self._ls_matrix = _build_light_space(self._sun, *_scene_bounds(depsgraph))
        else:
            self._ls_matrix = Matrix.Identity(4)
        self._lights_dirty  = False
        self._shadow_dirty  = True   # light moved → shadow map needs re-render

    def _rebuild(self, depsgraph, vls):
        t0 = time.time()

        # Bug 2: set flag so view_update ignores the bpy.types.Mesh updates
        # that new_from_object / remove will fire during this rebuild.
        self._rebuilding = True
        try:
            self._gi.cancel()

            use_gi    = vls.use_gi        if vls else False
            gi_samp   = vls.gi_samples    if vls else 8
            en_scale  = vls.energy_scale  if vls else 0.1
            use_shad  = vls.use_shadows   if vls else True
            shad_res  = int(vls.shadow_resolution) if vls else 1024

            # Bug 3: cache lights/shadow matrix once here
            self._cache_lights(depsgraph, en_scale, use_shad, shad_res)

            ss = _get_shadow_shader()
            new_mesh = {}; new_shadow = {}; seen = set()

            for inst in depsgraph.object_instances:
                obj = inst.object
                if obj.type != 'MESH' or obj.hide_get(): continue
                if obj.name in seen: continue
                seen.add(obj.name)

                data = _extract_mesh_data(obj, depsgraph)
                if data:
                    new_mesh[obj.name] = data
                    batch = _build_batch_from_cache(data)
                    self._batch_dict[obj.name] = (batch, data['texture'])

                b = _build_shadow_batch(obj, depsgraph, ss)
                if b: new_shadow[obj.name] = b

            self._mesh_cache  = new_mesh
            self._shadow_dict = new_shadow
            self._dirty       = False
            self._shadow_dirty = True   # geometry changed → shadow map needs re-render

            print(f"[VertexLit] rebuilt: {len(new_mesh)} meshes  lights: {len(self._lights)}", end="")
            for l in self._lights:
                t = 'SUN' if l['type']==1 else 'POINT'
                print(f"  [{t} e={l['energy']:.3f}]", end="")
            print(f"  ({time.time()-t0:.2f}s)")

            # Bug 5: build GI data from cache — no second new_from_object call
            if use_gi and new_mesh:
                all_verts = []; all_polys = []; all_albedo = []
                gi_verts  = {}; gi_norms = {}
                v_offset  = 0

                for name, data in new_mesh.items():
                    obj = bpy.data.objects.get(name)
                    if obj is None: continue
                    mat_w = obj.matrix_world
                    mat3  = mat_w.to_3x3()

                    # World-space verts/normals from cached local data
                    wv = [tuple(mat_w @ Vector(co)) for co in data['vert_co_local']]
                    wn = [tuple(mat3  @ Vector(no)) for no in data['vert_no_local']]
                    gi_verts[name] = wv
                    gi_norms[name] = wn

                    # BVH data
                    all_verts.extend(wv)
                    for (i0,i1,i2) in data['bvh_tris']:
                        all_polys.append([i0+v_offset, i1+v_offset, i2+v_offset])
                    all_albedo.extend(data['face_albedo'])
                    v_offset += len(data['vert_co_local'])

                from mathutils.bvhtree import BVHTree
                bvh = BVHTree.FromPolygons(all_verts, all_polys, epsilon=1e-6) \
                      if all_verts else None

                plain_lights = [{
                    'pos': tuple(l['pos']), 'dir': tuple(l['dir']),
                    'color': tuple(l['color']), 'energy': float(l['energy']),
                    'type': int(l['type']),  'radius': float(l['radius']),
                } for l in self._lights]

                scene_data = dict(bvh=bvh, face_albedo=all_albedo,
                                  lights=plain_lights,
                                  verts=gi_verts, normals=gi_norms)
                self._gi.start(scene_data, target_samples=gi_samp)

        finally:
            self._rebuilding = False

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
        """Re-render shadow map only when geometry or lights changed."""
        if not self._shadow_dirty:
            # Return cached texture — nothing that affects shadows changed
            return getattr(self, '_shadow_tex_cache', self._dummy_depth)

        smap   = _get_shadow_map(shad_res)
        shader = _get_shadow_shader()
        with smap.fb.bind():
            smap.fb.clear(depth=1.0)
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            gpu.state.viewport_set(0, 0, shad_res, shad_res)
            shader.bind()
            shader.uniform_float('uLightSpace', ls_mat)
            for inst in depsgraph.object_instances:
                obj = inst.object
                if obj.type != 'MESH' or obj.hide_get(): continue
                batch = self._shadow_dict.get(obj.name)
                if batch is None: continue
                shader.uniform_float('uModel', inst.matrix_world)
                batch.draw(shader)

        self._shadow_tex_cache = smap.tex
        self._shadow_dirty     = False
        return smap.tex

    # ── Main draw ─────────────────────────────────────────────────────────

    def view_draw(self, context, depsgraph):
        self._ensure_state()
        self._ensure_resources()

        scene = depsgraph.scene
        vls   = getattr(scene, 'vertex_lit', None)

        if self._dirty:
            self._rebuild(depsgraph, vls)

        # Bug 3: if lights moved, recollect without full mesh rebuild
        if self._lights_dirty:
            en_sc   = vls.energy_scale if vls else 0.1
            u_shad  = vls.use_shadows  if vls else True
            s_res   = int(vls.shadow_resolution) if vls else 1024
            self._cache_lights(depsgraph, en_sc, u_shad, s_res)

        if self._gi.has_update():
            gi_data, _ = self._gi.get_update()
            self._apply_gi_update(gi_data)
        if self._gi.is_running:
            try: self.tag_redraw()
            except Exception: pass

        # Bug 3: read from cache — no depsgraph iteration here
        lights  = self._lights
        ls_mat  = self._ls_matrix
        sun     = self._sun

        sky    = tuple(vls.sky_color)    if vls else (0.08, 0.10, 0.14)
        ground = tuple(vls.ground_color) if vls else (0.03, 0.03, 0.04)
        u_shad = vls.use_shadows         if vls else True
        s_res  = int(vls.shadow_resolution) if vls else 1024
        s_bias = vls.shadow_bias         if vls else 0.005
        s_dark = vls.shadow_darkness     if vls else 0.25

        do_shad  = u_shad and sun is not None
        shad_tex = self._shadow_pass(ls_mat, s_res, depsgraph) \
                   if do_shad else self._dummy_depth

        region = context.region; rv3d = context.region_data
        w, h   = region.width, region.height
        gpu.state.viewport_set(0, 0, w, h)
        try:
            fb = gpu.state.active_framebuffer_get()
            wc = scene.world.color if scene.world else None
            fb.clear(color=(wc[0],wc[1],wc[2],1.0) if wc
                     else (0.08,0.08,0.08,1.0), depth=1.0)
        except Exception as e:
            print(f"[VertexLit] clear: {e}")

        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set('BACK')

        shader    = _get_main_shader()
        view_proj = rv3d.window_matrix @ rv3d.view_matrix
        shader.bind()
        shader.uniform_float('uViewProj',   view_proj)
        shader.uniform_float('uLightSpace', ls_mat)
        shader.uniform_float('uSkyColor',   sky)
        shader.uniform_float('uGroundColor', ground)
        shader.uniform_int  ('uUseShadow',  1 if do_shad else 0)
        shader.uniform_float('uShadowBias', s_bias)
        shader.uniform_float('uShadowDark', s_dark)
        shader.uniform_sampler('uShadowMap', shad_tex)
        shader.uniform_int('uNumLights', len(lights))
        for i in range(8):
            l = lights[i] if i < len(lights) else None
            try:
                shader.uniform_float(f'uLPos[{i}]',    tuple(l['pos'])  if l else (0,0,0))
                shader.uniform_float(f'uLDir[{i}]',    tuple(l['dir'])  if l else (0,0,-1))
                shader.uniform_float(f'uLCol[{i}]',    l['color']       if l else (0,0,0))
                shader.uniform_float(f'uLEnergy[{i}]', l['energy']      if l else 0.0)
                shader.uniform_int  (f'uLType[{i}]',   l['type']        if l else 0)
                shader.uniform_float(f'uLRadius[{i}]', l['radius']      if l else 1.0)
            except ValueError: pass

        # Draw — Bug 4: uNormalMat computed on CPU (once per object, not per vertex)
        for inst in depsgraph.object_instances:
            obj = inst.object
            if obj.type != 'MESH' or obj.hide_get(): continue
            entry = self._batch_dict.get(obj.name)
            if entry is None: continue
            batch, tex = entry
            model_mat  = inst.matrix_world
            try:
                nm = model_mat.to_3x3().inverted_safe().transposed()
            except Exception:
                nm = model_mat.to_3x3()
            shader.uniform_float('uModel',     model_mat)
            shader.uniform_float('uNormalMat', nm)
            albedo = tex if tex is not None else self._white_tex
            shader.uniform_sampler('uAlbedo',   albedo)
            shader.uniform_int('uHasTexture',   1 if tex is not None else 0)
            batch.draw(shader)

        gpu.state.depth_test_set('NONE')
        gpu.state.face_culling_set('NONE')
        gpu.state.depth_mask_set(False)


def register():
    bpy.utils.register_class(VertexLitEngine)

def unregister():
    bpy.utils.unregister_class(VertexLitEngine)
