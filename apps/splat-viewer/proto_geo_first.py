"""
proto_geo_first.py: PROTOTYPE of geometry-first loading with buffer REUSE (the installed engine is untouched).

  blender.exe <file>.blend --python proto_geo_first.py -- <out_dir> <benchmark_splats.py>
  env VLR_NO_SAVE=1     required for a user's own file (never saved; exits with os._exit)
  env VLR_UNHIDE_EYE=1  show eye-hidden meshes in memory first (the Azola baseline configuration)
  env VLR_TEX_BUDGET_MS texture streaming budget per frame (default 50)

PASS 1, geometry, all objects in one frame. Per UNIQUE evaluated mesh (linked duplicates share it):
  * ONE vertex buffer of per-CORNER positions;
  * ONE index buffer of triangles sorted by material (each material = a contiguous range).
  Drawn faceted, in each OBJECT's flat material colours (materials are per object, so duplicates with
  different materials still share geometry). No change-detection signature is computed (nothing is cached).
PASS 2, attributes, one frame. Per unique mesh:
  * ONE more vertex buffer (corner normals, UVs, vertex colours) added to the SAME batch (vertbuf_add).
PASS 3, textures, streamed with a per-frame budget while the scene keeps drawing.
EQUIVALENCE: expanding the buffers through each material range must reproduce the engine's own per-slot
arrays (_extract_mesh_data) for EVERY object, shared or not.
"""
import bpy, sys, os, json, time, statistics, traceback, importlib, importlib.util, ctypes as _ct
import numpy as np
import gpu

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
os.makedirs(OUT_DIR, exist_ok=True)
RESULTS = os.path.join(OUT_DIR, 'proto_results.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
TEX_BUDGET = float(os.environ.get('VLR_TEX_BUDGET_MS', '50')) / 1000.0
L = []
status = {'ok': False}
bench = None
API = {}
TEXLOG = []


def log(s=''):
    print('[proto]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


for _scr in bpy.data.screens:
    for _a in _scr.areas:
        if _a.type == 'VIEW_3D':
            for _s in _a.spaces:
                if _s.type == 'VIEW_3D':
                    _s.shading.type = 'SOLID'

VERT_GEO = """
uniform mat4 uMVP; uniform mat4 uMV;
in vec3 pos; out vec3 vPV;
void main(){ vPV = (uMV * vec4(pos, 1.0)).xyz; gl_Position = uMVP * vec4(pos, 1.0); }
"""
FRAG_GEO = """
uniform vec4 uColor; in vec3 vPV; out vec4 fragColor;
void main(){ vec3 n = normalize(cross(dFdx(vPV), dFdy(vPV)));
  fragColor = vec4(uColor.rgb * (0.35 + 0.65 * abs(n.z)), 1.0); }
"""
VERT_FULL = """
uniform mat4 uMVP; uniform mat3 uNrm;
in vec3 pos; in vec3 normal; in vec2 texCoord; out vec3 vN; out vec2 vUV;
void main(){ vN = uNrm * normal; vUV = texCoord; gl_Position = uMVP * vec4(pos, 1.0); }
"""
FRAG_FULL = """
uniform vec4 uColor; uniform sampler2D uTex; in vec3 vN; in vec2 vUV; out vec4 fragColor;
void main(){ vec3 base = uColor.rgb * texture(uTex, vUV).rgb;
  fragColor = vec4(base * (0.35 + 0.65 * abs(normalize(vN).z)), 1.0); }
"""


def draw1():
    win, area, region, rv3d = bench._find_view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
    bench._gpu_sync()


def make_ibo(idx):
    for label, arr in (('uint32 buffer', idx), ('int32 buffer', idx.astype(np.int32))):
        try:
            ibo = gpu.types.GPUIndexBuf(type='TRIS', seq=arr)
            API.setdefault('ibo_path', label)
            return ibo
        except Exception as e:
            API.setdefault('ibo_errors', []).append('%s: %s' % (label, e))
    API.setdefault('ibo_path', 'python list (SLOW)')
    return gpu.types.GPUIndexBuf(type='TRIS', seq=idx.tolist())


def slot_material(obj, eo, k):
    ms = obj.material_slots
    m = ms[k].material if k < len(ms) else None
    return m if m is not None else (eo.active_material or obj.active_material)


# ───────────────────────── pass 1: geometry (per unique mesh) ─────────────────────────
def geo_read(E, me):
    if me is None or not hasattr(me, 'loop_triangles'):
        return None
    me.calc_loop_triangles(); nt = len(me.loop_triangles)
    if nt == 0:
        return None
    nv, nl, npo = len(me.vertices), len(me.loops), len(me.polygons)
    li = E._raw_corner_tris(me, nt)
    cv = E._raw_attr(me, '.corner_vert', _ct.c_int, 1, nl)
    if li is None or cv is None:
        li = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get('loops', li)
        cv = np.empty(nl, np.int32); me.loops.foreach_get('vertex_index', cv)
    vc = E._raw_attr(me, 'position', _ct.c_float, 3, nv)
    if vc is None:
        vc = np.empty(nv * 3, np.float32); me.vertices.foreach_get('co', vc); vc = vc.reshape(nv, 3)
    if npo and 'material_index' in me.attributes:                 # same derivation as the engine
        pmi = E._raw_attr(me, 'material_index', _ct.c_int, 1, npo)
        if pmi is None:
            pmi = np.empty(npo, np.int32); me.attributes['material_index'].data.foreach_get('value', pmi)
        lt = np.empty(npo, np.int32); me.polygons.foreach_get('loop_total', lt)
        tri_mi = np.repeat(np.asarray(pmi).astype(np.int32, copy=False), lt - 2)
        if len(tri_mi) != nt:
            tri_mi = np.zeros(nt, np.int32); me.loop_triangles.foreach_get('material_index', tri_mi)
    else:
        tri_mi = np.zeros(nt, np.int32)
    tris = np.asarray(li).reshape(nt, 3)
    uniq, counts = np.unique(tri_mi, return_counts=True)
    if len(uniq) > 1:
        tris = tris[np.argsort(tri_mi, kind='stable')]
    idx = np.ascontiguousarray(tris, dtype=np.uint32)
    pos = np.ascontiguousarray(vc[np.asarray(cv)], dtype=np.float32)
    ranges = []; s = 0
    for k, c in zip(uniq, counts):
        ranges.append((int(k), s * 3, int(c) * 3)); s += int(c)
    return dict(pos=pos, idx=idx, ranges=ranges, nl=nl, nt=nt)


def geo_build(g, fmt):
    vbo = gpu.types.GPUVertBuf(fmt, len(g['pos'])); vbo.attr_fill(id='pos', data=g['pos'])
    ibo = make_ibo(g['idx'])
    g['vbo'] = vbo; g['ibo'] = ibo
    g['batch'] = gpu.types.GPUBatch(type='TRIS', buf=vbo, elem=ibo)


# ───────────────────────── pass 2: attributes (per unique mesh) ─────────────────────────
def rest_read(E, me, nl):
    nv = len(me.vertices)
    try:
        nrm = np.empty(nl * 3, np.float32); me.corner_normals.foreach_get('vector', nrm); nrm = nrm.reshape(nl, 3)
    except Exception:
        cv = np.asarray(E._raw_attr(me, '.corner_vert', _ct.c_int, 1, nl))
        vn = np.empty(nv * 3, np.float32); me.vertices.foreach_get('normal', vn); nrm = vn.reshape(nv, 3)[cv]
    uvl = me.uv_layers.active
    if uvl:
        uv = E._raw_attr(me, uvl.name, _ct.c_float, 2, nl)
        if uv is None:
            uv = np.empty(nl * 2, np.float32); uvl.data.foreach_get('uv', uv); uv = uv.reshape(nl, 2)
        uv = np.ascontiguousarray(uv, dtype=np.float32)
    else:
        uv = np.zeros((nl, 2), np.float32)
    col = None
    try:
        ca = me.color_attributes; attr = None
        if ca:
            attr = ca.active_color
            if attr is None and len(ca): attr = ca[0]
        if attr is not None and attr.data_type in ('FLOAT_COLOR', 'BYTE_COLOR'):
            m = len(attr.data); carr = np.empty(m * 4, np.float32); attr.data.foreach_get('color', carr)
            carr = carr.reshape(m, 4)
            if attr.domain == 'CORNER':
                col = carr
            elif attr.domain == 'POINT':
                col = carr[np.asarray(E._raw_attr(me, '.corner_vert', _ct.c_int, 1, nl))]
            if col is not None and np.all(col == col[0]):
                col = None
    except Exception:
        col = None
    return nrm, uv, col


def rest_build(g, nrm, uv, col, fmt_nc, fmt_nuc):
    vbo2 = gpu.types.GPUVertBuf(fmt_nuc if col is not None else fmt_nc, g['nl'])
    vbo2.attr_fill(id='normal', data=nrm); vbo2.attr_fill(id='texCoord', data=uv)
    if col is not None:
        vbo2.attr_fill(id='vertColor', data=np.ascontiguousarray(col, dtype=np.float32))
    g['vbo2'] = vbo2; g['has_col'] = col is not None
    g['batch'].vertbuf_add(vbo2)


# ───────────────────────── drawing ─────────────────────────
def draw_all(items, sh, view, proj, off, full, white, read=False):
    """Returns (seconds until the GPU finished, pixels or None). Readback is excluded from the timing."""
    t = time.perf_counter(); px = None
    with off.bind():
        fb = gpu.state.active_framebuffer_get(); fb.clear(color=(0.08, 0.08, 0.08, 1.0), depth=1.0)
        gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True); gpu.state.face_culling_set('NONE')
        sh.bind()
        for it in items:
            g = it['geo']; mv = view @ it['mw']
            sh.uniform_float('uMVP', proj @ mv)
            if full:
                sh.uniform_float('uNrm', mv.to_3x3().inverted_safe().transposed())
            else:
                sh.uniform_float('uMV', mv)
            for k, st, cnt in g['ranges']:
                sh.uniform_float('uColor', it['cols'][k])
                if full:
                    sh.uniform_sampler('uTex', it['tex'].get(k) or white)
                g['batch'].draw_range(sh, elem_start=st, elem_count=cnt)
        bench._gpu_sync()
        dt = time.perf_counter() - t
        if read:
            buf = fb.read_color(0, 0, off.width, off.height, 4, 0, 'FLOAT')
            buf.dimensions = off.width * off.height * 4
            px = np.array(buf, dtype=np.float32)
    gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
    return dt, px


def save_png(px, w, h, name):
    img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
    img.pixels.foreach_set(np.clip(px, 0.0, 1.0)); p = os.path.join(OUT_DIR, name + '.png')
    img.filepath_raw = p; img.file_format = 'PNG'; img.save()
    return p


def run():
    global bench
    try:
        if bpy.app.background:
            raise RuntimeError('needs a live GPU session')
        if not bpy.data.filepath or ('claude' not in bpy.data.filepath.lower() and os.environ.get('VLR_NO_SAVE') != '1'):
            raise RuntimeError('refusing to run on a non-scratch file without VLR_NO_SAVE=1')
        spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
        bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
        E = importlib.import_module('vertex_lit_renderer.engine')
        scene = bpy.context.scene
        if not (hasattr(gpu.types.GPUBatch, 'draw_range') and hasattr(gpu.types.GPUBatch, 'vertbuf_add')):
            raise RuntimeError('this Blender lacks GPUBatch.draw_range / vertbuf_add')
        log("GEOMETRY-FIRST PROTOTYPE v2 (sharing + texture streaming) | Blender %s | %s | %s"
            % (bpy.app.version_string, bench.detect_caps()['gpu'], os.path.basename(bpy.data.filepath)))
        for _ in range(3): draw1()
        if os.environ.get('VLR_UNHIDE_EYE') == '1':
            hid = []
            for o in scene.objects:
                try:
                    if o.type == 'MESH' and o.hide_get(): hid.append(o)
                except Exception:
                    pass
            for o in hid: o.hide_set(False)
            t = time.perf_counter()
            for _ in range(3): draw1()
            log("unhid %d eye-hidden meshes in memory; Solid-view evaluation %.2f s (not part of any timing below)"
                % (len(hid), time.perf_counter() - t))
        win, area, region, rv3d = bench._find_view3d()
        W, H = region.width, region.height
        view = rv3d.view_matrix.copy(); proj = rv3d.window_matrix.copy()
        off = gpu.types.GPUOffScreen(W, H)
        white = gpu.types.GPUTexture((1, 1), format='RGBA8', data=gpu.types.Buffer('FLOAT', 4, [1.0, 1.0, 1.0, 1.0]))
        sh_geo = gpu.types.GPUShader(VERT_GEO, FRAG_GEO); sh_full = gpu.types.GPUShader(VERT_FULL, FRAG_FULL)
        fmt_pos = gpu.types.GPUVertFormat(); fmt_pos.attr_add(id='pos', comp_type='F32', len=3, fetch_mode='FLOAT')
        fmt_nc = gpu.types.GPUVertFormat()
        fmt_nc.attr_add(id='normal', comp_type='F32', len=3, fetch_mode='FLOAT')
        fmt_nc.attr_add(id='texCoord', comp_type='F32', len=2, fetch_mode='FLOAT')
        fmt_nuc = gpu.types.GPUVertFormat()
        fmt_nuc.attr_add(id='normal', comp_type='F32', len=3, fetch_mode='FLOAT')
        fmt_nuc.attr_add(id='texCoord', comp_type='F32', len=2, fetch_mode='FLOAT')
        fmt_nuc.attr_add(id='vertColor', comp_type='F32', len=4, fetch_mode='FLOAT')
        bench._gpu_sync()

        # ── PASS 1: geometry ──
        T = {}
        t0 = time.perf_counter()
        dg = bpy.context.evaluated_depsgraph_get()
        items = []; geos = {}; tr = tb = 0.0; t_share = 0.0
        for inst in dg.object_instances:
            if getattr(inst, 'is_instance', False) or inst.object.type != 'MESH' or not inst.show_self:
                continue
            o = bpy.data.objects.get(inst.object.name)
            if o is None:
                continue
            a = time.perf_counter()
            eo = o.evaluated_get(dg); me = getattr(eo, 'data', None)
            key = me.as_pointer() if me is not None else None
            g = geos.get(key)
            t_share += time.perf_counter() - a
            if g is None:
                a = time.perf_counter(); g = geo_read(E, me); tr += time.perf_counter() - a
                if g is None:
                    continue
                a = time.perf_counter(); geo_build(g, fmt_pos); tb += time.perf_counter() - a
                g['me_owner'] = o.name; geos[key] = g
            cols = {}
            for k, _, _ in g['ranges']:
                m = slot_material(o, eo, k)
                dc = m.diffuse_color if m is not None else (1.0, 1.0, 1.0, 1.0)
                cols[k] = (dc[0], dc[1], dc[2], 1.0)
            items.append(dict(obj=o, mw=inst.matrix_world.copy(), geo=g, cols=cols, tex={}))
        T['collect_share'] = t_share; T['geo_read'] = tr; T['geo_build'] = tb
        t_pre = time.perf_counter()
        T['geo_first_draw'], px1 = draw_all(items, sh_geo, view, proj, off, False, white, read=True)
        T['geo_total'] = (t_pre - t0) + T['geo_first_draw']      # excludes the image readback
        nl = sum(g['nl'] for g in geos.values()); nt = sum(g['nt'] for g in geos.values())
        nt_all = sum(it['geo']['nt'] for it in items)
        log("")
        log("scene: %d mesh objects -> %d UNIQUE meshes (linked duplicates share buffers) | %.2fM unique triangles "
            "(%.2fM drawn) | %.2fM unique corners | index buffers via %s"
            % (len(items), len(geos), nt / 1e6, nt_all / 1e6, nl / 1e6, API.get('ibo_path')))
        log("")
        log("PASS 1 geometry: read+sort %.2f s | build %.2f s | object walk + share lookup %.3f s | first draw (upload) %.2f s"
            % (T['geo_read'], T['geo_build'], T['collect_share'], T['geo_first_draw']))
        log("  => ALL GEOMETRY ON SCREEN: %.2f s   (prototype v1 without sharing: 1.89 s | engine today: 6.09 s)" % T['geo_total'])

        # ── PASS 2: attributes (one frame) ──
        t1 = time.perf_counter(); tr = tb = 0.0; ncol = 0
        for g in geos.values():
            o = bpy.data.objects[g['me_owner']]; me = o.evaluated_get(dg).data
            a = time.perf_counter(); nrm, uv, col = rest_read(E, me, g['nl']); tr += time.perf_counter() - a
            a = time.perf_counter(); rest_build(g, nrm, uv, col, fmt_nc, fmt_nuc); tb += time.perf_counter() - a
            ncol += col is not None
            del nrm, uv, col
        T['rest_read'] = tr; T['rest_build'] = tb
        T['rest_first_draw'], _ = draw_all(items, sh_full, view, proj, off, True, white)
        T['rest_total'] = time.perf_counter() - t1
        log("")
        log("PASS 2 attributes: read %.2f s | build + vertbuf_add %.2f s | first draw (upload) %.2f s | %d meshes with vertex colours"
            % (T['rest_read'], T['rest_build'], T['rest_first_draw'], ncol))
        log("  => SHADED (untextured) ON SCREEN: %.2f s after start" % (T['geo_total'] + T['rest_total']))

        # ── PASS 3: textures streamed with a per-frame budget ──
        queue = []
        for it in items:
            eo = it['obj'].evaluated_get(dg)
            for k, _, _ in it['geo']['ranges']:
                queue.append((it, k, slot_material(it['obj'], eo, k)))
        t2 = time.perf_counter(); frames = []; tex_frames = []; qi = 0; n_tex = 0
        while qi < len(queue):
            f0 = time.perf_counter(); b_end = f0 + TEX_BUDGET; ttex = 0.0
            while qi < len(queue) and (time.perf_counter() < b_end or ttex == 0.0):
                it, k, m = queue[qi]; qi += 1
                a = time.perf_counter()
                img = E._find_base_texture(m) if m is not None else None
                b = time.perf_counter()
                tex = E._get_gpu_tex(img) if img is not None else None
                c = time.perf_counter()
                ttex += c - a
                if img is not None and (c - a) > 0.01:
                    TEXLOG.append((c - a, b - a, img.name, tuple(img.size), img.source, img.file_format,
                                   bool(img.packed_file), img.colorspace_settings.name))
                if tex is not None:
                    it['tex'][k] = tex; n_tex += 1
            ddt, _ = draw_all(items, sh_full, view, proj, off, True, white)
            frames.append((time.perf_counter() - f0) * 1000.0); tex_frames.append(ttex * 1000.0)
        T['tex_stream'] = time.perf_counter() - t2
        T['full_redraw'], px2 = draw_all(items, sh_full, view, proj, off, True, white, read=True)
        fs = sorted(frames) if frames else [0.0]
        log("")
        log("PASS 3 textures streamed (budget %.0f ms/frame): %d material slots, %d textured, %d frames in %.2f s"
            % (TEX_BUDGET * 1000, len(queue), n_tex, len(frames), T['tex_stream']))
        log("  frame ms while streaming: median %.0f | p90 %.0f | max %.0f   (texture load within the worst frame: %.0f ms)"
            % (statistics.median(fs), fs[int(len(fs) * 0.9)], fs[-1], max(tex_frames) if tex_frames else 0))
        log("  => FULLY LOADED: %.2f s after start   (prototype v1: 4.55 s | engine today: 6.65 s incl. 0.32 s material compile)"
            % (T['geo_total'] + T['rest_total'] + T['tex_stream']))
        TEXLOG.sort(reverse=True)
        log("  slow texture loads (>10 ms): %d, together %.2f s. Slowest:" % (len(TEXLOG), sum(x[0] for x in TEXLOG)))
        for tt_, tf_, nm_, sz_, src_, ff_, pk_, cs_ in TEXLOG[:10]:
            log("    %6.0f ms  %-40s %5dx%-5d %s %s packed=%s %s  (node search %.1f ms)"
                % (tt_ * 1000, nm_[:40], sz_[0], sz_[1], src_, ff_, pk_, cs_, tf_ * 1000))
        log("  steady redraw, all objects, full shader: %.0f ms" % (T['full_redraw'] * 1000))
        gmb = nl * 12 + nt * 12
        rmb = sum(g['nl'] * (20 + (16 if g.get('has_col') else 0)) for g in geos.values())
        log("  GPU vertex data: %.0f MB + %.0f MB (unique meshes only)   (v1 without sharing: 751 + 948 MB)" % (gmb / 1e6, rmb / 1e6))
        p1 = save_png(px1, W, H, 'proto_v2_pass1_geometry'); p2 = save_png(px2, W, H, 'proto_v2_full')
        log("  images: %s | %s" % (p1, p2))

        # ── EQUIVALENCE vs the engine (not timed): every object, shared or not ──
        a = time.perf_counter(); bad = []; checked = 0; cache_rest = {}
        for it in items:
            o = it['obj']; g = it['geo']; eo = o.evaluated_get(dg)
            ed = E._extract_mesh_data(o, dg)
            if ed is None:
                bad.append((o.name, 'engine returned None')); continue
            checked += 1
            es = ed['slots']
            if len(es) != len(g['ranges']):
                bad.append((o.name, 'slots %d vs %d' % (len(es), len(g['ranges'])))); continue
            gid = id(g)
            if gid not in cache_rest:
                cache_rest = {gid: rest_read(E, bpy.data.objects[g['me_owner']].evaluated_get(dg).data, g['nl'])}
            nrm, uv, col = cache_rest[gid]
            flat = g['idx'].reshape(-1).astype(np.int64); why = None
            for s_, (k, st, cnt) in zip(es, g['ranges']):
                I = flat[st:st + cnt]
                for key, arr in (('positions', g['pos']), ('normals', nrm), ('uvs', uv)):
                    if not np.array_equal(arr[I], s_[key]):
                        why = key; break
                if why is None and col is not None and not np.array_equal(col[I], s_['colors']):
                    why = 'colors'
                m = slot_material(o, eo, k)
                if why is None and (m.name if m else None) != s_.get('material_name'):
                    why = 'material %r vs %r' % (m.name if m else None, s_.get('material_name'))
                if why:
                    break
            if why:
                bad.append((o.name, why))
        log("")
        log("EQUIVALENCE vs engine _extract_mesh_data, every object incl. shared ones: %d checked, %d mismatches %s  (%.1f s)"
            % (checked, len(bad), bad[:6], time.perf_counter() - a))
        status.update(ok=True, T=T, API=API, objects=len(items), unique=len(geos), mismatches=len(bad))
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2, default=str)
    print('[proto] exiting without saving'); sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(run, first_interval=5.0)
