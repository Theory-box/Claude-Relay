"""
ui_screenshot.py: screenshot the Workbench 2.0 Render-properties UI (LIVE Blender; nothing is saved).

  blender.exe --python ui_screenshot.py -- <out_dir> <name>

The largest area is turned into a Properties editor on the Render tab. Every addon panel is re-registered
without DEFAULT_CLOSED so all of them draw expanded, and toggles that reveal sub-settings are switched on.
All of this happens in memory only; the script exits with os._exit.
"""
import bpy, os, sys, time, json, traceback

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, NAME = ARGS[0], (ARGS[1] if len(ARGS) > 1 else 'ui')
PAGES = int(ARGS[2]) if len(ARGS) > 2 else 3
TAB = ARGS[3] if len(ARGS) > 3 else 'RENDER'      # Properties tab: RENDER, OBJECT, ...
os.makedirs(OUT_DIR, exist_ok=True)
STATE = {'step': 0}
LOG = []


def log(s):
    print('[ui]', s); LOG.append(str(s))
    with open(os.path.join(OUT_DIR, NAME + '_log.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(LOG) + '\n')


def biggest_area():
    win = bpy.context.window_manager.windows[0]
    areas = sorted(win.screen.areas, key=lambda a: a.width * a.height, reverse=True)
    return win, areas[0]


def prep():
    import addon_utils
    addon_utils.enable('vertex_lit_renderer', default_set=False)
    from vertex_lit_renderer import ui
    if hasattr(ui, '_FORCE_OPEN'):
        ui._FORCE_OPEN = True                # layout-panel sections: draw all expanded
    scene = bpy.context.scene
    scene.render.engine = 'VERTEX_LIT'
    s = scene.vertex_lit
    s.use_shadows = True                     # reveal shadow sub-settings
    for c in reversed(ui._CLASSES):
        bpy.utils.unregister_class(c)
    for c in ui._CLASSES:
        opts = set(getattr(c, 'bl_options', set())); opts.discard('DEFAULT_CLOSED')
        c.bl_options = opts
        bpy.utils.register_class(c)
    win, area = biggest_area()
    area.type = 'PROPERTIES'          # the Render tab is set after the area has drawn once
    log("area %dx%d -> PROPERTIES; addon %s" % (area.width, area.height,
        next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)))


def tick():
    try:
        STATE['step'] += 1
        if STATE['step'] == 1:
            prep()
            return 1.5
        win, area = biggest_area()
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=3)
        if STATE['step'] == 2:
            area.spaces.active.context = TAB
            return 1.0
        if STATE['step'] == 3:
            return 1.0
        region = next(r for r in area.regions if r.type == 'WINDOW')
        page = STATE['step'] - 4
        p = os.path.join(OUT_DIR, '%s_%d.png' % (NAME, page))
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=p)
        log("saved %s (%d bytes)" % (p, os.path.getsize(p) if os.path.exists(p) else -1))
        if page < PAGES - 1:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.view2d.scroll_down(page=True)
            return 0.8
    except Exception:
        log("FAILED:\n" + traceback.format_exc())
    with open(os.path.join(OUT_DIR, NAME + '_done.json'), 'w') as f:
        json.dump({'done': True}, f)
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(tick, first_interval=3.0)
