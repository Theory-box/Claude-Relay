"""
tests/test_extract_identical.py — PERMANENT regression test for vertex_lit_renderer's mesh extraction.

Asserts that the addon's CURRENT engine._extract_mesh_data produces output IDENTICAL to the reference
implementation (the v0.15.3 function, embedded verbatim below) on every visible mesh object of a .blend:
every slot's positions / normals / uvs / colors (bit-exact), material names, vi_map, n_verts, vert_co_local,
and gen_min / gen_scale (to float tolerance). Also reports the speed of both.

Run (background mode is fine; nothing is saved):
  blender -b <scene>.blend --python tests/test_extract_identical.py -- [--unhide] [--out result.json]

  --unhide   also show every eye-hidden mesh object (in memory) — e.g. the Azola vegetation working state
Exit code 0 = identical on every object, 1 = any mismatch, 2 = test error.
"""
import bpy, sys, os, json, time, traceback, importlib, ctypes as _ct
import numpy as np

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
UNHIDE = '--unhide' in argv
OUT = argv[argv.index('--out') + 1] if '--out' in argv else None

E = importlib.import_module('vertex_lit_renderer.engine')
if bpy.app.background:
    # gpu.texture.from_image crashes Blender without a GPU context: stub the texture lookup (the texture
    # handle is not part of the compared output; both implementations call the same helper per slot).
    E._get_gpu_tex = lambda *a, **k: None


# ───────────── reference: engine._extract_mesh_data as of v0.15.3 (verbatim, helpers via E.) ─────────────
def _reference_extract(obj, depsgraph, mesh=None, attr_name=""):
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
        tex = E._get_gpu_tex(E._find_base_texture(mat_slot))
        default = [1.0, 1.0, 1.0, 1.0]
        if mat_slot:
            c = mat_slot.diffuse_color
            default = [c[0], c[1], c[2], 1.0]

        n_verts = len(mesh.vertices)
        n_loops = len(mesh.loops)
        n_flat = n_tris * 3

        li_flat = E._raw_corner_tris(mesh, n_tris)
        corner_vert = E._raw_attr(mesh, '.corner_vert', _ct.c_int, 1, n_loops)
        if li_flat is not None and corner_vert is not None:
            vi_flat = corner_vert[li_flat]
        else:
            li_flat = np.empty(n_flat, dtype=np.int32); mesh.loop_triangles.foreach_get('loops', li_flat)
            vi_flat = np.empty(n_flat, dtype=np.int32); mesh.loop_triangles.foreach_get('vertices', vi_flat)

        vc = E._raw_attr(mesh, 'position', _ct.c_float, 3, n_verts)
        if vc is None:
            vc = np.empty(n_verts * 3, dtype=np.float32); mesh.vertices.foreach_get('co', vc)
            vc = vc.reshape(n_verts, 3)
        positions = vc[vi_flat]

        vn = np.empty(n_verts * 3, dtype=np.float32); mesh.vertices.foreach_get('normal', vn)
        vn = vn.reshape(n_verts, 3)
        try:
            cn = np.empty(n_loops * 3, dtype=np.float32)
            mesh.corner_normals.foreach_get('vector', cn)
            normals = cn.reshape(n_loops, 3)[li_flat]
        except Exception:
            normals = vn[vi_flat]
        vert_co_local = vc.copy()

        uv_layer = mesh.uv_layers.active
        if uv_layer:
            uv = E._raw_attr(mesh, uv_layer.name, _ct.c_float, 2, n_loops)
            if uv is None:
                uv = np.empty(n_loops * 2, dtype=np.float32); uv_layer.data.foreach_get('uv', uv)
                uv = uv.reshape(n_loops, 2)
            uvs = uv[li_flat]
        else:
            uvs = np.zeros((n_flat, 2), dtype=np.float32)

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

        vmin = vc.min(axis=0); vmax = vc.max(axis=0); size = vmax - vmin
        gen_min = (float(vmin[0]), float(vmin[1]), float(vmin[2]))
        gen_scale = (1.0/float(size[0]) if size[0] > 1e-9 else 0.0,
                     1.0/float(size[1]) if size[1] > 1e-9 else 0.0,
                     1.0/float(size[2]) if size[2] > 1e-9 else 0.0)

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
            stex = E._get_gpu_tex(E._find_base_texture(slot_mat))
            sdefault = [1.0, 1.0, 1.0, 1.0]
            if slot_mat is not None:
                dc = slot_mat.diffuse_color; sdefault = [dc[0], dc[1], dc[2], 1.0]
            scolors = C_arr if has_vcol else np.tile(np.array(sdefault, dtype=np.float32), (len(P), 1))
            return dict(positions=P, normals=N, uvs=U, colors=scolors,
                        material_name=(slot_mat.name if slot_mat else None), texture=stex)

        slots_out = []
        if len(uniq) <= 1:
            slots_out.append(_slot(int(uniq[0]) if len(uniq) else 0, positions, normals, uvs, colors))
        else:
            mi_corner = np.repeat(mi, 3)
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
        print(f"[reference] extract error ({obj.name}): {e}")
        return None


# ───────────────────────── comparison ─────────────────────────
def compare(a, b):
    """Return (ok, reason, worst_abs_diff). Arrays must be bit-identical; bbox-derived floats to tolerance."""
    if a is None or b is None:
        return (a is None and b is None), ('one side returned None' if (a is None) != (b is None) else ''), 0.0
    if len(a['slots']) != len(b['slots']):
        return False, 'slot count %d vs %d' % (len(a['slots']), len(b['slots'])), float('inf')
    worst = 0.0
    for i, (sa, sb) in enumerate(zip(a['slots'], b['slots'])):
        if sa['material_name'] != sb['material_name']:
            return False, 'slot %d material %r vs %r' % (i, sa['material_name'], sb['material_name']), float('inf')
        for k in ('positions', 'normals', 'uvs', 'colors'):
            x = np.asarray(sa[k]); y = np.asarray(sb[k])
            if x.shape != y.shape:
                return False, 'slot %d %s shape %s vs %s' % (i, k, x.shape, y.shape), float('inf')
            if x.size and not np.array_equal(x, y):
                d = float(np.abs(x - y).max()); worst = max(worst, d)
                return False, 'slot %d %s differs (max %.3g)' % (i, k, d), d
    if not np.array_equal(np.asarray(a['vi_map']), np.asarray(b['vi_map'])):
        return False, 'vi_map differs', float('inf')
    if a['n_verts'] != b['n_verts'] or not np.array_equal(a['vert_co_local'], b['vert_co_local']):
        return False, 'n_verts / vert_co_local differ', float('inf')
    gm = max(abs(p - q) for p, q in zip(a['gen_min'], b['gen_min']))
    gs = max(abs(p - q) / max(abs(q), 1e-12) for p, q in zip(a['gen_scale'], b['gen_scale']))
    if gm > 1e-6 or gs > 1e-5:
        return False, 'gen_min/gen_scale differ (%.3g / %.3g)' % (gm, gs), gm
    return True, '', worst


def main():
    sc = bpy.context.scene
    unhid = 0
    if UNHIDE:
        for o in sc.objects:
            if o.type != 'MESH':
                continue
            try:
                if o.hide_get():
                    o.hide_set(False); unhid += 1
            except Exception:
                pass
        bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [o for o in sc.objects if o.type == 'MESH' and o.visible_get()]
    # run each implementation on every object; reference first (pays Blender's normal computation once)
    t = time.perf_counter(); ref = [_reference_extract(o, dg) for o in objs]; t_ref_cold = time.perf_counter() - t
    t = time.perf_counter(); cur = [E._extract_mesh_data(o, dg) for o in objs]; t_cur = time.perf_counter() - t
    t = time.perf_counter(); ref = [_reference_extract(o, dg) for o in objs]; t_ref = time.perf_counter() - t
    bad = []
    for o, a, b in zip(objs, ref, cur):
        ok, why, _ = compare(a, b)
        if not ok:
            bad.append((o.name, why))
    tris = sum(sum(len(s['positions']) for s in r['slots']) // 3 for r in ref if r)
    res = dict(file=bpy.data.filepath, unhid=unhid, objects=len(objs), triangles=tris,
               identical=len(objs) - len(bad), mismatches=bad[:25],
               reference_ms=round(t_ref * 1000, 1), reference_first_ms=round(t_ref_cold * 1000, 1),
               current_ms=round(t_cur * 1000, 1), speedup=round(t_ref / max(t_cur, 1e-9), 2))
    print('[test_extract_identical] %s: %d/%d objects identical (%d tris) | reference %.0f ms, current %.0f ms (%.2fx)'
          % (os.path.basename(bpy.data.filepath), res['identical'], len(objs), tris, t_ref * 1000, t_cur * 1000,
             res['speedup']))
    for name, why in bad[:25]:
        print('   MISMATCH %s: %s' % (name, why))
    if OUT:
        with open(OUT, 'w') as f:
            json.dump(res, f, indent=1)
    return 0 if not bad else 1


try:
    code = main()
except Exception:
    traceback.print_exc(); code = 2
sys.stdout.flush()
os._exit(code)
