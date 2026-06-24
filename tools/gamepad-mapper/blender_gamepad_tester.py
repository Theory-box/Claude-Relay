bl_info = {
    "name": "Gamepad Tester",
    "author": "Claude Relay",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Gamepad",
    "description": "Live readout + a session logger that captures every axis/button/hat to a report.",
    "category": "3D View",
}

from pathlib import Path
import bpy
from bpy.props import StringProperty, BoolProperty

_pg = None
_js = None
_log = None


def _open():
    global _pg, _js
    try:
        import pygame
    except Exception as e:
        return False, "pygame NOT installed (%s)" % type(e).__name__
    _pg = pygame
    if not pygame.get_init():
        pygame.init()
    pygame.joystick.quit()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        return False, "pygame OK, but 0 controllers detected"
    _js = pygame.joystick.Joystick(0)
    _js.init()
    return True, "%s  |  axes:%d  buttons:%d  hats:%d" % (
        _js.get_name(), _js.get_numaxes(), _js.get_numbuttons(), _js.get_numhats())


def _read_text():
    if _pg is None or _js is None:
        return "not connected"
    _pg.event.pump()
    out = []
    ax = ["a%d % .2f" % (i, _js.get_axis(i)) for i in range(_js.get_numaxes())]
    for i in range(0, len(ax), 3):
        out.append("  ".join(ax[i:i + 3]))
    down = [str(i) for i in range(_js.get_numbuttons()) if _js.get_button(i)]
    out.append("BUTTON DOWN: " + (" ".join(down) or "(none - press one)"))
    if _js.get_numhats():
        out.append("  ".join("hat%d %s" % (i, _js.get_hat(i)) for i in range(_js.get_numhats())))
    return "\n".join(out)


def _log_start():
    global _log
    _pg.event.pump()
    na = _js.get_numaxes()
    _log = {'amin': [_js.get_axis(i) for i in range(na)],
            'amax': [_js.get_axis(i) for i in range(na)],
            'btns': set(), 'hats': set(), 'name': _js.get_name(),
            'na': na, 'nb': _js.get_numbuttons(), 'nh': _js.get_numhats()}


def _log_tick():
    if _log is None:
        return
    _pg.event.pump()
    for i in range(_log['na']):
        v = _js.get_axis(i)
        if v < _log['amin'][i]:
            _log['amin'][i] = v
        if v > _log['amax'][i]:
            _log['amax'][i] = v
    for i in range(_log['nb']):
        if _js.get_button(i):
            _log['btns'].add(i)
    for i in range(_log['nh']):
        h = _js.get_hat(i)
        if h != (0, 0):
            _log['hats'].add((i, h))


def _log_report():
    L = _log
    lines = ["GAMEPAD LOG", "name: %s" % L['name'],
             "counts: axes=%d buttons=%d hats=%d" % (L['na'], L['nb'], L['nh']),
             "", "AXES (min .. max observed):"]
    for i in range(L['na']):
        lines.append("  axis %d: % .2f .. % .2f" % (i, L['amin'][i], L['amax'][i]))
    lines.append("")
    lines.append("BUTTONS pressed: " + (", ".join(map(str, sorted(L['btns']))) or "(none)"))
    lines.append("HATS seen: " + (", ".join("h%d=%s" % (i, h)
                                            for i, h in sorted(L['hats'])) or "(none)"))
    return "\n".join(lines)


class GAMEPAD_OT_test_detect(bpy.types.Operator):
    bl_idname = "gamepad.test_detect"
    bl_label = "Detect controller"

    def execute(self, context):
        ok, msg = _open()
        context.window_manager.gamepad_test_status = msg
        context.window_manager.gamepad_test_text = _read_text() if ok else ""
        return {'FINISHED'}


class GAMEPAD_OT_test_live(bpy.types.Operator):
    bl_idname = "gamepad.test_live"
    bl_label = "Live read (toggle)"
    _timer = None

    def execute(self, context):
        wm = context.window_manager
        if wm.gamepad_test_running:
            wm.gamepad_test_running = False
            return {'FINISHED'}
        ok, msg = _open()
        wm.gamepad_test_status = msg
        if not ok:
            return {'CANCELLED'}
        wm.gamepad_test_running = True
        self._timer = wm.event_timer_add(1.0 / 30.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.gamepad_test_running or event.type == 'ESC':
            if self._timer:
                wm.event_timer_remove(self._timer)
                self._timer = None
            return {'CANCELLED'}
        if event.type == 'TIMER':
            wm.gamepad_test_text = _read_text()
            for a in context.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()
        return {'PASS_THROUGH'}


class GAMEPAD_OT_log(bpy.types.Operator):
    bl_idname = "gamepad.log_session"
    bl_label = "Log session (toggle)"
    _timer = None

    def execute(self, context):
        wm = context.window_manager
        if wm.gamepad_log_running:
            wm.gamepad_log_running = False
            text = _log_report()
            name = "GamepadLog"
            t = bpy.data.texts.get(name) or bpy.data.texts.new(name)
            t.clear()
            t.write(text)
            saved = "GamepadLog text block"
            try:
                p = Path.home() / "gamepad_log.txt"
                p.write_text(text)
                saved += " + " + str(p)
            except Exception:
                pass
            wm.gamepad_test_status = "saved to " + saved
            wm.gamepad_test_text = text
            return {'FINISHED'}
        ok, msg = _open()
        wm.gamepad_test_status = msg
        if not ok:
            return {'CANCELLED'}
        _log_start()
        wm.gamepad_log_running = True
        wm.gamepad_test_status = "LOGGING - press every button and squeeze both triggers, then Stop log"
        self._timer = wm.event_timer_add(1.0 / 30.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.gamepad_log_running or event.type == 'ESC':
            if self._timer:
                wm.event_timer_remove(self._timer)
                self._timer = None
            return {'CANCELLED'}
        if event.type == 'TIMER':
            _log_tick()
            for a in context.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()
        return {'PASS_THROUGH'}


class VIEW3D_PT_gamepad_test(bpy.types.Panel):
    bl_label = "Gamepad Tester"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Gamepad"

    def draw(self, context):
        wm = context.window_manager
        col = self.layout.column()
        col.operator("gamepad.test_detect", icon='FILE_REFRESH')
        col.operator("gamepad.test_live",
                     text="Stop live" if wm.gamepad_test_running else "Start live",
                     icon='PAUSE' if wm.gamepad_test_running else 'PLAY')
        col.operator("gamepad.log_session",
                     text="Stop log (write report)" if wm.gamepad_log_running else "Start log",
                     icon='REC' if not wm.gamepad_log_running else 'CANCEL')
        col.separator()
        box = col.box()
        for line in (wm.gamepad_test_status or "press Detect").split("\n"):
            box.label(text=line)
        if wm.gamepad_test_text:
            box.separator()
            for line in wm.gamepad_test_text.split("\n"):
                box.label(text=line)


classes = (
    GAMEPAD_OT_test_detect,
    GAMEPAD_OT_test_live,
    GAMEPAD_OT_log,
    VIEW3D_PT_gamepad_test,
)


def register():
    bpy.types.WindowManager.gamepad_test_status = StringProperty(default="")
    bpy.types.WindowManager.gamepad_test_text = StringProperty(default="")
    bpy.types.WindowManager.gamepad_test_running = BoolProperty(default=False)
    bpy.types.WindowManager.gamepad_log_running = BoolProperty(default=False)
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.gamepad_test_status
    del bpy.types.WindowManager.gamepad_test_text
    del bpy.types.WindowManager.gamepad_test_running
    del bpy.types.WindowManager.gamepad_log_running


if __name__ == "__main__":
    register()
