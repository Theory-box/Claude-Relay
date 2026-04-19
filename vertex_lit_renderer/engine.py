# vertex_lit_renderer/engine.py

import time
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .shaders import MAIN_VERT, MAIN_FRAG
from .gi import ProgressiveGI

MAX_LIGHTS   = 8
MAX_BVH_TRIS = 50_000  # cap BVH tris so ray casts stay fast (< 1ms each)
                       # polygoniq/GeoNodes realized scenes can have 500k+ tris,
                       # making each ray cast take > 500ms and preventing threads
                       # from stopping within the join timeout — causing accumulation.
                       # GI only needs approximate geometry; subsampling is fine.

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
    Extract per-loop arrays from the evaluated mesh WITHOUT touching bpy.data.
    Uses eval_obj.data directly (borrowed reference — do not remove).
    vp_dg is the viewport depsgraph so GeoNodes/hidden prototypes evaluate correctly.
    """
    try:
        eval_obj = obj.evaluated_get(vp_dg)
        if not eval_obj or not hasattr(eval_obj, 'data') or not eval_obj.data:
            return None

        mesh = eval_obj.data   # borrowed — never call bpy.data.meshes.remove() on this

        # Triangulation may or may not be pre-computed on the evaluated mesh.
        if not mesh.loop_triangles:
            try: mesh.calc_loop_triangles()
            except Exception: pass
        if not mesh.loop_triangles:
            return None

        # corner_normals is computed by the evaluator; safe to read on borrowed mesh.
        try:
            corner_normals = mesh.corner_normals
            has_corner_normals = True
        except Exception:
            has_corner_normals = False

        # Per-face material list — GeoNodes "Set Material" assigns per face.
        mat_list = [slot.material for slot in eval_obj.material_slots]
        if not mat_list:
            m = eval_obj.active_material
            mat_list = [m] if m else []

        def _mat_color(m):
            if m:
                c = m.diffuse_color
                return [float(c[0]), float(c[1]), float(c[2]), 1.0]
            return [1.0, 1.0, 1.0, 1.0]
        mat_colors = [_mat_color(m) for m in mat_list]
        default    = mat_colors[0] if mat_colors else [1.0, 1.0, 1.0, 1.0]

        # First textured material as the mesh texture.
        tex = None
        for m in mat_list:
            if m:
                t = _get_gpu_tex(_find_base_texture(m))
                if t: tex = t; break

        # Vertex colours — FLOAT_COLOR / BYTE_COLOR only.
        vcol_point = {}; vcol_corner = {}
        if mesh.color_attributes:
            attr = None
            try: attr = mesh.color_attributes.active_color
            except Exception: pass
            if attr is None and len(mesh.color_attributes): attr = mesh.color_attributes[0]
            if attr and getattr(attr,'data_type','') in ('FLOAT_COLOR','BYTE_COLOR',''):
                for idx, d in enumerate(attr.data):
                    try:
                        c = d.color
                        rgba = [float(c[0]),float(c[1]),float(c[2]),float(c[3]) if len(c)>3 else 1.0]
                        if attr.domain=='POINT':  vcol_point[idx]  = rgba
                        elif attr.domain=='CORNER': vcol_corner[idx] = rgba
                    except Exception: pass

        # Read cast_shadow from GeoNodes named attribute if present.
        # Falls back to the Object property if the attribute doesn't exist.
        # Attribute domain=POINT, type=BOOLEAN, name='vertex_lit_cast_shadow'
        gn_cast_shadow = None
        if mesh.attributes and 'vertex_lit_cast_shadow' in mesh.attributes:
            attr = mesh.attributes['vertex_lit_cast_shadow']
            if attr.data_type == 'BOOLEAN' and len(attr.data) > 0:
                # ANY vertex with cast_shadow=False → whole object excluded
                # (GeoNodes sets it per-point; we treat it as object-level for BVH)
                gn_cast_shadow = any(d.value for d in attr.data)

        uv_layer = mesh.uv_layers.active
        n_verts  = len(mesh.vertices)

        # Per-vertex local-space arrays for GI world transform.
        vert_co_local = [(v.co.x,v.co.y,v.co.z) for v in mesh.vertices]
        vert_no_local = [(v.normal.x,v.normal.y,v.normal.z) for v in mesh.vertices]

        _m0 = mat_list[0] if mat_list else None
        mat_diffuse = (float(_m0.diffuse_color[0]),float(_m0.diffuse_color[1]),
                       float(_m0.diffuse_color[2])) if _m0 else (0.8,0.8,0.8)

        positions=[]; normals=[]; colors=[]; uvs=[]; vi_map=[]
        gi_face_albedo=[]
        for tri in mesh.loop_triangles:
            mi = tri.material_index
            face_default = mat_colors[mi] if mi < len(mat_colors) else default

            # Sample texture at UV centroid for accurate GI albedo
            _fmat = mat_list[mi] if mi < len(mat_list) else None
            _fimg = _find_base_texture(_fmat) if _fmat else None
            _pd   = _get_pixel_array(_fimg) if (_fimg and uv_layer) else None
            if _pd:
                _arr,_w,_h = _pd
                _u = sum(uv_layer.data[tri.loops[_c]].uv[0] for _c in range(3))/3.0
                _v = sum(uv_layer.data[tri.loops[_c]].uv[1] for _c in range(3))/3.0
                _u %= 1.0; _v %= 1.0
                _px=min(int(_u*_w),_w-1); _py=min(int(_v*_h),_h-1)
                _mc=face_default
                gi_face_albedo.append((_arr[_py,_px,0]*_mc[0],_arr[_py,_px,1]*_mc[1],_arr[_py,_px,2]*_mc[2]))
            else:
                gi_face_albedo.append(tuple(face_default[:3]))

            for corner in range(3):
                vi=tri.vertices[corner]; li=tri.loops[corner]
                v=mesh.vertices[vi]
                positions.append((v.co.x,v.co.y,v.co.z))
                if has_corner_normals:
                    try:
                        cn=corner_normals[li]
                        normals.append((cn.vector.x,cn.vector.y,cn.vector.z))
                    except Exception:
                        normals.append((v.normal.x,v.normal.y,v.normal.z))
                else:
                    normals.append((v.normal.x,v.normal.y,v.normal.z))
                colors.append(vcol_corner.get(li,vcol_point.get(vi,face_default)))
                uvs.append(tuple(uv_layer.data[li].uv) if uv_layer else (0.0,0.0))
                vi_map.append(vi)

        # No bpy.data.meshes.remove() — mesh is borrowed from eval_obj.
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
        return None   # nothing to remove


def _build_batch_from_cache(cached, gi_per_vert=None):
    shader=_get_main_shader()
    vi_map=cached['vi_map']; n_v=cached['n_verts']
    bounces=[gi_per_vert[vi] for vi in vi_map] if (gi_per_vert and len(gi_per_vert)==n_v)             else [(0.0,0.0,0.0)]*len(vi_map)
    return batch_for_shader(shader,'TRIS',{
        'position':    cached['positions'],
        'normal':      cached['normals'],
        'vertColor':   cached['colors'],
        'texCoord':    cached['uvs'],
        'bounceColor': bounces,
    })


def _build_raw_bvh_data(mesh_cache, objects):
    """Returns raw vert/poly data for GI thread to build BVH — no main-thread hitch."""
    all_verts=[]; all_polys=[]; face_albedo=[]; v_offset=0
    for name,data in mesh_cache.items():
        obj=objects.get(name)
        if obj is None: continue
        # GeoNodes attribute takes priority; fall back to Object property
        gn_cs = data.get('gn_cast_shadow')
        if gn_cs is not None:
            if not gn_cs: continue   # GN attribute says don't cast
        elif not getattr(obj,'vertex_lit_cast_shadow',True):
            continue                  # Object property says don't cast
        inst_mat=obj.matrix_world
        for co in data['vert_co_local']:
            wv=inst_mat@Vector(co)
            all_verts.append((wv.x,wv.y,wv.z))
        vi_map=data['vi_map']
        gfa=data.get('gi_face_albedo') or [data['mat_diffuse']]*(len(vi_map)//3)
        for fi,i in enumerate(range(0,len(vi_map),3)):
            all_polys.append([vi_map[i]+v_offset,vi_map[i+1]+v_offset,vi_map[i+2]+v_offset])
            face_albedo.append(gfa[fi] if fi<len(gfa) else data['mat_diffuse'])
        v_offset+=len(data['vert_co_local'])
    if not all_verts: return None,[]

    # Subsample if over the cap — keeps same vertex pool, just fewer triangles.
    # face_albedo is subsampled in sync so face indices remain correct.
    if len(all_polys) > MAX_BVH_TRIS:
        step = max(1, len(all_polys) // MAX_BVH_TRIS)
        all_polys   = all_polys[::step]
        face_albedo = face_albedo[::step]
        print(f"[VertexLit] BVH subsampled to {len(all_polys)} tris (step={step})")

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

    # ── view_update ───────────────────────────────────────────────────────

    def view_update(self, context, depsgraph):
        self._ensure_state()

        # ── Deletion detection ────────────────────────────────────────────
        # Check if any cached object no longer exists in the scene.
        # Without this, deleted objects leave stale batches, and re-adding
        # an object with the same name would show the old GI data.
        if self._mesh_cache:
            current = {inst.object.name for inst in depsgraph.object_instances
                       if inst.object.type == 'MESH'}
            if not current.issuperset(self._mesh_cache.keys()):
                self._dirty = True
                self._gi_preserve = False  # full reset — scene changed significantly
                self.tag_redraw(); return

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
                        global _edit_dirty, _edit_dirty_time
                        _edit_dirty.add(id_data.name)
                        _edit_dirty_time = time.time()
                        self.tag_redraw(); return
                    else:
                        # New object — incremental rebuild adds just this one
                        global _edit_dirty, _edit_dirty_time
                        _edit_dirty.add(id_data.name)
                        _edit_dirty_time = time.time()
                        self.tag_redraw(); return
                if isinstance(id_data, bpy.types.Object) and id_data.type == 'LIGHT':
                    self._dirty = True
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
                        global _edit_dirty, _edit_dirty_time
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
            if obj.type in ('LIGHT','CAMERA','ARMATURE','LATTICE','SPEAKER','LIGHT_PROBE'):
                continue
            if obj.name in seen: continue
            seen.add(obj.name)

            data = _extract_mesh_data(obj, vp_dg)
            if data:
                new_mesh[obj.name]   = data
                new_batch[obj.name]  = (_build_batch_from_cache(data), data['texture'])

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

            gi_verts={}; gi_norms={}
            for name, data in new_mesh.items():
                obj = bpy_objects.get(name)
                if obj is None: continue
                m=obj.matrix_world; m3=m.to_3x3()
                gi_verts[name]=[tuple(m@Vector(co)) for co in data['vert_co_local']]
                gi_norms[name]=[tuple(m3@Vector(no)) for no in data['vert_no_local']]

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

    def _apply_gi_update(self, gi_data):
        self._gi_has_data = True
        new_batch = dict(self._batch_dict)
        for name, cached in self._mesh_cache.items():
            gv = gi_data.get(name)
            if gv is None: continue
            new_batch[name] = (_build_batch_from_cache(cached, gv), cached['texture'])
        self._batch_dict = new_batch

    # ── Lightweight GI restart after transform ──────────────────────────────────────────────

    def _restart_gi_for_transforms(self, vls):
        """Restart GI from cached geometry after an object is moved.
        No bpy calls, no mesh extraction — just retransforms cached verts."""
        if not self._mesh_cache: return
        bpy_objects = {name: bpy.data.objects.get(name) for name in self._mesh_cache}
        raw_bvh = _build_raw_bvh_data(self._mesh_cache, bpy_objects)
        if raw_bvh is None: return
        gi_verts={}; gi_norms={}
        for name, data in self._mesh_cache.items():
            obj = bpy_objects.get(name)
            if obj is None: continue
            m=obj.matrix_world; m3=m.to_3x3()
            gi_verts[name]=[tuple(m@Vector(co)) for co in data['vert_co_local']]
            gi_norms[name]=[tuple(m3@Vector(no)) for no in data['vert_no_local']]
        gi_samp = vls.gi_samples      if vls else 128
        rpp     = vls.gi_rays_per_pass if vls else 4
        pause   = (vls.gi_thread_pause if vls else 0.1) / 1000.0
        _global_gi.start(
            dict(raw_bvh=raw_bvh, lights=self._lights_cache,
                 verts=gi_verts, normals=gi_norms,
                 rays_per_pass=rpp, thread_pause=pause),
            target_samples=gi_samp, preserve_existing=True, decay=0.1)


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
                        gi_for_obj = [(min(float(old_gi[i,0]/cnt),20.),
                                       min(float(old_gi[i,1]/cnt),20.),
                                       min(float(old_gi[i,2]/cnt),20.))
                                      for i in range(len(old_gi))]
            batch = _build_batch_from_cache(new_data, gi_for_obj)
            self._batch_dict[name] = (batch, new_data["texture"])
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

        if self._light_dirty and (time.time() - self._light_dirty_time) > 0.3:
            self._light_dirty = False
            en_scale = vls.energy_scale if vls else 1.0
            self._lights_cache = _collect_lights(depsgraph, en_scale)
            self._restart_gi_for_transforms(vls)

        # Edit-mode geometry changes — debounced 0.2s
        global _edit_dirty, _edit_dirty_time
        if _edit_dirty and (time.time() - _edit_dirty_time) > 0.2:
            dirty = _edit_dirty.copy()
            _edit_dirty.clear()
            self._incremental_rebuild(dirty, context, depsgraph, vls)

        if self._transform_dirty and (time.time() - self._transform_time) > 0.3:
            self._transform_dirty = False
            self._restart_gi_for_transforms(vls)

        if self._dirty:
            self._rebuild(context, depsgraph, vls)

        if _global_gi is not None and _global_gi.has_update():
            gi_data,n=_global_gi.get_update()
            self._apply_gi_update(gi_data)
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
            if obj.type in ('LIGHT','CAMERA','ARMATURE','LATTICE','SPEAKER','LIGHT_PROBE'):
                continue
            entry=self._batch_dict.get(obj.name)
            if entry is None: continue
            batch,tex=entry
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
    """Fires during edit mode. Collects objects with changed geometry."""
    global _edit_dirty, _edit_dirty_time
    for update in depsgraph.updates:
        if not update.is_updated_geometry: continue
        id_data = update.id
        # Object-level update (most common in edit mode)
        if isinstance(id_data, bpy.types.Object) and id_data.type == 'MESH':
            if id_data.mode == 'EDIT':
                _edit_dirty.add(id_data.name)
                _edit_dirty_time = time.time()
        # Mesh data-block update fallback
        elif isinstance(id_data, bpy.types.Mesh):
            obj = getattr(bpy.context, 'active_object', None)
            if obj and obj.mode == 'EDIT' and obj.data == id_data:
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
