"""
ui_audit.py: functional audit of the Workbench 2.0 UI (LIVE Blender; nothing is saved).

  blender.exe <blank>.blend --python ui_audit.py -- <out_dir>

 1. static: every scene/object property and operator referenced by ui.py exists
 2. draws the Render panel (all sections forced open) through every UI-affecting state, and the Object
    tab. Blender prints panel-draw exceptions to stdout, so grep stdout for "Traceback" afterwards
 3. Workbench panels in engine._HIDDEN_WORKBENCH_PANELS are hidden, kept ones are shown, and
    disabling/re-enabling the addon restores COMPAT_ENGINES cleanly
Writes ui_audit.txt + ui_audit_done.json.
"""
import bpy, os, sys, re, json, traceback, importlib, inspect

OUT = sys.argv[sys.argv.index('--') + 1]
os.makedirs(OUT, exist_ok=True)
L = []; FAIL = []; STATE = {'i': 0}


def log(s):
    print('[audit]', s); L.append(str(s))
    with open(os.path.join(OUT, 'ui_audit.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def check(ok, what):
    log(('PASS  ' if ok else 'FAIL  ') + what)
    if not ok:
        FAIL.append(what)


def area():
    win = bpy.context.window_manager.windows[0]
    return win, sorted(win.screen.areas, key=lambda a: a.width * a.height, reverse=True)[0]


def redraw():
    win, a = area()
    with bpy.context.temp_override(window=win, area=a):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)


def static_checks():
    import addon_utils
    addon_utils.enable('vertex_lit_renderer', default_set=False)
    ui = importlib.import_module('vertex_lit_renderer.ui')
    src = inspect.getsource(ui)
    scene_props = set(bpy.context.scene.vertex_lit.bl_rna.properties.keys())
    used = set(re.findall(r"\b(?:s|toggle_owner=s), '([a-z_]+)'", src)) | set(re.findall(r"toggle='([a-z_]+)'", src))
    missing = sorted(p for p in used if p not in scene_props)
    check(not missing, "all %d scene properties used by ui.py exist %s" % (len(used), missing or ''))
    obj_used = set(re.findall(r"ob, '([a-z_]+)'", src))
    obj_missing = sorted(p for p in obj_used if not hasattr(bpy.types.Object, p) and p not in bpy.types.Object.bl_rna.properties.keys())
    check(not obj_missing, "object properties used by ui.py exist %s %s" % (sorted(obj_used), obj_missing or ''))
    for op in sorted(set(re.findall(r'"(vertex_lit\.[a-z_]+)"', src))):
        mod, name = op.split('.')
        ok = True
        try:
            getattr(getattr(bpy.ops, mod), name).get_rna_type()
        except Exception:
            ok = False
        check(ok, "operator %s is registered" % op)
    ui._FORCE_OPEN = True


def panel_checks():
    E = importlib.import_module('vertex_lit_renderer.engine')
    hidden = getattr(E, '_HIDDEN_WORKBENCH_PANELS', set())
    for name in sorted(hidden):
        p = getattr(bpy.types, name, None)
        check(p is None or 'VERTEX_LIT' not in getattr(p, 'COMPAT_ENGINES', set()), "hidden: %s" % name)
    for name in ('RENDER_PT_opengl_film', 'RENDER_PT_simplify', 'RENDER_PT_color_management', 'RENDER_PT_format',
                 'EEVEE_MATERIAL_PT_context_material', 'EEVEE_MATERIAL_PT_surface'):
        p = getattr(bpy.types, name, None)
        check(p is not None and 'VERTEX_LIT' in getattr(p, 'COMPAT_ENGINES', set()), "kept:   %s" % name)


def addon_cycle():
    import addon_utils
    addon_utils.disable('vertex_lit_renderer', default_set=False)
    film = getattr(bpy.types, 'RENDER_PT_opengl_film', None)
    check(film is not None and 'VERTEX_LIT' not in film.COMPAT_ENGINES, "disable: borrowed panels released")
    check(not hasattr(bpy.types, 'VERTEX_LIT_PT_settings'), "disable: Workbench 2.0 panel unregistered")
    addon_utils.enable('vertex_lit_renderer', default_set=False)
    check('VERTEX_LIT' in getattr(bpy.types, 'RENDER_PT_opengl_film').COMPAT_ENGINES, "re-enable: borrowed panels restored")
    check(hasattr(bpy.types, 'VERTEX_LIT_PT_settings'), "re-enable: Workbench 2.0 panel registered")
    importlib.import_module('vertex_lit_renderer.ui')._FORCE_OPEN = True


def states():
    """(label, setup) pairs; each is drawn after its setup runs."""
    sc = bpy.context.scene
    s = lambda: bpy.context.scene.vertex_lit
    vl = bpy.context.view_layer
    cube = bpy.data.objects.get('Cube'); cam = bpy.data.objects.get('Camera')

    def set_active(o):
        vl.objects.active = o

    def new_mesh(name, with_mat, nodes):
        me = bpy.data.meshes.new(name); ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
        if with_mat:
            m = bpy.data.materials.new(name + '_mat'); m.use_nodes = nodes; me.materials.append(m)
        return ob
    no_mat = new_mesh('AuditNoMat', False, False)
    no_nodes = new_mesh('AuditNoNodes', True, False)
    out = []
    for vm in ('TEXTURED', 'SOLID', 'RANDOM', 'ATTRIBUTE', 'NORMAL', 'DEPTH'):
        out.append(("view mode %s" % vm, lambda vm=vm: setattr(s(), 'view_mode', vm)))
    out.append(("depth auto off", lambda: setattr(s(), 'depth_auto', False)))
    out.append(("view mode TEXTURED", lambda: setattr(s(), 'view_mode', 'TEXTURED')))
    out.append(("background COLOR", lambda: setattr(s(), 'background_mode', 'COLOR')))
    out.append(("shadows on, sun 0", lambda: (setattr(s(), 'use_shadows', True), setattr(s(), 'sun_intensity', 0.0))))
    out.append(("shadows on, sun 1", lambda: setattr(s(), 'sun_intensity', 1.0)))
    out.append(("outline/cavity on", lambda: (setattr(s(), 'use_outline', True), setattr(s(), 'use_ao', True), setattr(s(), 'use_cavity', True))))
    out.append(("gpu sort on", lambda: setattr(s(), 'splat_gpu_sort', True)))
    out.append(("no active object", lambda: set_active(None)))
    out.append(("active camera (non-mesh)", lambda: set_active(cam)))
    out.append(("mesh without material", lambda: set_active(no_mat)))
    out.append(("material without nodes", lambda: set_active(no_nodes)))
    out.append(("mesh with node material", lambda: set_active(cube)))
    return out


def tick():
    try:
        i = STATE['i']; STATE['i'] += 1
        if i == 0:
            static_checks()
            bpy.context.scene.render.engine = 'VERTEX_LIT'
            panel_checks()
            addon_cycle()
            bpy.context.scene.render.engine = 'VERTEX_LIT'
            win, a = area(); a.type = 'PROPERTIES'
            return 1.0
        if i == 1:
            win, a = area(); a.spaces.active.context = 'RENDER'
            STATE['states'] = states()
            redraw()
            log("drew Render tab: default state")
            return 0.3
        st = STATE['states']
        k = i - 2
        if k < len(st):
            label, fn = st[k]
            fn(); redraw()
            log("drew Render tab: %s" % label)
            return 0.2
        if k == len(st):
            win, a = area(); a.spaces.active.context = 'OBJECT'
            bpy.context.view_layer.objects.active = bpy.data.objects.get('Cube')
            redraw(); redraw()
            log("drew Object tab (mesh active)")
            return 0.3
        log("")
        log("static/panel checks: %d failures %s" % (len(FAIL), FAIL))
    except Exception:
        log("AUDIT SCRIPT ERROR:\n" + traceback.format_exc())
        FAIL.append('script error')
    with open(os.path.join(OUT, 'ui_audit_done.json'), 'w') as f:
        json.dump({'failures': FAIL}, f)
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(tick, first_interval=3.0)
