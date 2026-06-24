bl_info = {
    "name": "Gamepad Fly Navigation",
    "author": "Claude Relay",
    "version": (0, 9, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Gamepad",
    "description": "Fly the 3D viewport with the left/right sticks. A controller button "
                   "(or key) switches between Fly mode and Cursor mode; Cursor mode yields "
                   "the sticks to the standalone GamepadMapper app, which drives the OS pointer.",
    "category": "3D View",
}

import sys
import time
import json
import subprocess
from pathlib import Path

import bpy
from bpy.props import (IntProperty, FloatProperty, BoolProperty, StringProperty,
                       EnumProperty)
from mathutils import Vector, Quaternion

_pg = None   # pygame module once loaded
_js = None   # joystick handle


# ----------------------------------------------------------------------------
# pygame bootstrap (Blender has no built-in gamepad API)
# ----------------------------------------------------------------------------
def _libs():
    p = Path(bpy.utils.user_resource('SCRIPTS', create=True)) / "modules"
    p.mkdir(parents=True, exist_ok=True)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    return p


def _blender_python():
    return next((Path(sys.prefix) / "bin").glob("python3*"))


def _pip_install(pkgs):
    libs = _libs()
    py = _blender_python()
    subprocess.run([str(py), "-m", "ensurepip"], capture_output=True)
    return subprocess.run([str(py), "-m", "pip", "install", "--target", str(libs)] + pkgs,
                          capture_output=True, text=True)


def _ensure_pygame():
    global _pg, _js
    if _js is not None:
        return True, "ready"
    _libs()
    try:
        import pygame
    except Exception:
        return False, "pygame missing - click 'Install pygame'"
    _pg = pygame
    if not pygame.get_init():
        pygame.init()
    pygame.joystick.quit()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        return False, "no controller (connect BEFORE launching Blender)"
    _js = pygame.joystick.Joystick(0)
    _js.init()
    return True, _js.get_name()


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _dz(v, dead):
    if abs(v) < dead:
        return 0.0
    s = (abs(v) - dead) / (1.0 - dead)
    return s if v > 0 else -s


def _find_view3d(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            return area, area.spaces.active.region_3d
    return None, None


def _redraw(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def _mode_status(cursor):
    return "CURSOR mode (app drives pointer)" if cursor else "FLY mode"


# ----------------------------------------------------------------------------
# settings persistence
# ----------------------------------------------------------------------------
SCALAR_KEYS = ['deadzone', 'move_speed', 'look_speed', 'boost_mult',
               'invert_left_y', 'invert_right_y',
               'lx_axis', 'ly_axis', 'rx_axis', 'ry_axis', 'boost_btn',
               'toggle_btn', 'toggle_kind', 'toggle_axis_sign',
               'toggle_behavior', 'toggle_key']


def _settings_path():
    return Path(bpy.utils.user_resource('CONFIG', create=True)) / "gamepad_fly_settings.json"


def _save_settings(prefs):
    data = {'scalars': {k: getattr(prefs, k) for k in SCALAR_KEYS}}
    _settings_path().write_text(json.dumps(data, indent=1))


def _load_settings(prefs):
    p = _settings_path()
    if not p.exists():
        return False
    data = json.loads(p.read_text())
    for k, v in data.get('scalars', {}).items():
        try:
            setattr(prefs, k, v)
        except Exception:
            pass
    return True


def _autoload():
    try:
        _load_settings(bpy.context.preferences.addons[__name__].preferences)
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# operators
# ----------------------------------------------------------------------------
class VIEW3D_OT_gp_install_pygame(bpy.types.Operator):
    bl_idname = "view3d.gp_install_pygame"
    bl_label = "Install pygame"
    bl_description = "Install the pygame library into Blender's modules folder"

    def execute(self, context):
        r = _pip_install(["pygame"])
        try:
            import pygame  # noqa: F401
            self.report({'INFO'}, "pygame %s installed" % pygame.__version__)
        except Exception:
            self.report({'ERROR'}, "install failed: %s" % (r.stderr or "")[-200:])
            return {'CANCELLED'}
        return {'FINISHED'}


class VIEW3D_OT_gp_save(bpy.types.Operator):
    bl_idname = "view3d.gp_save_settings"
    bl_label = "Save settings"

    def execute(self, context):
        _save_settings(context.preferences.addons[__name__].preferences)
        self.report({'INFO'}, "saved")
        return {'FINISHED'}


class VIEW3D_OT_gp_load(bpy.types.Operator):
    bl_idname = "view3d.gp_load_settings"
    bl_label = "Load settings"

    def execute(self, context):
        ok = _load_settings(context.preferences.addons[__name__].preferences)
        self.report({'INFO'}, "loaded" if ok else "no saved settings")
        return {'FINISHED'}


class VIEW3D_OT_gp_learn_button(bpy.types.Operator):
    bl_idname = "view3d.gp_learn_button"
    bl_label = "Listen for a button or trigger"
    bl_description = "Press a button or pull a trigger to assign it as the Fly/Cursor switch"
    _timer = None
    _base = None

    def modal(self, context, event):
        if event.type == 'ESC':
            return self._end(context, "cancelled")
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if _js is None or _pg is None:
            return self._end(context, "no controller")
        _pg.event.pump()
        prefs = context.preferences.addons[__name__].preferences
        try:
            for i in range(_js.get_numbuttons()):
                if _js.get_button(i):
                    prefs.toggle_kind = 'BUTTON'
                    prefs.toggle_btn = i
                    return self._end(context, "learned button %d" % i)
            for i in range(_js.get_numaxes()):
                base = self._base[i] if (self._base and i < len(self._base)) else 0.0
                dev = _js.get_axis(i) - base
                if abs(dev) > 0.6:
                    prefs.toggle_kind = 'AXIS'
                    prefs.toggle_btn = i
                    prefs.toggle_axis_sign = 'POS' if dev > 0 else 'NEG'
                    return self._end(context, "learned axis %d %s" % (i, "+" if dev > 0 else "-"))
        except Exception:
            pass
        return {'RUNNING_MODAL'}

    def _end(self, context, msg):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        self.report({'INFO'}, msg)
        return {'FINISHED'}

    def execute(self, context):
        ok, msg = _ensure_pygame()
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        _pg.event.pump()
        try:
            self._base = [_js.get_axis(i) for i in range(_js.get_numaxes())]
        except Exception:
            self._base = []
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 60.0, window=context.window)
        wm.modal_handler_add(self)
        self.report({'INFO'}, "press a button or pull a trigger...")
        return {'RUNNING_MODAL'}


class VIEW3D_OT_gamepad_mode(bpy.types.Operator):
    bl_idname = "view3d.gamepad_mode"
    bl_label = "Toggle Fly / Cursor"
    bl_description = "Manually switch between Fly mode and Cursor mode"

    def execute(self, context):
        wm = context.window_manager
        wm.gamepad_cursor_mode = not wm.gamepad_cursor_mode
        wm.gamepad_status = _mode_status(wm.gamepad_cursor_mode)
        _redraw(context)
        return {'FINISHED'}


def _apply_mode(wm, behavior, rising, falling):
    """Update cursor mode from an input edge. Returns True if it changed."""
    changed = False
    if behavior == 'TOGGLE':
        if rising:
            wm.gamepad_cursor_mode = not wm.gamepad_cursor_mode
            changed = True
    elif behavior == 'HOLD_FLY':
        if rising:
            wm.gamepad_cursor_mode = False
            changed = True
        elif falling:
            wm.gamepad_cursor_mode = True
            changed = True
    elif behavior == 'HOLD_CURSOR':
        if rising:
            wm.gamepad_cursor_mode = True
            changed = True
        elif falling:
            wm.gamepad_cursor_mode = False
            changed = True
    if changed:
        wm.gamepad_status = _mode_status(wm.gamepad_cursor_mode)
    return changed


class VIEW3D_OT_gamepad_fly(bpy.types.Operator):
    bl_idname = "view3d.gamepad_fly"
    bl_label = "Gamepad (modal)"
    _timer = None
    _last = 0.0
    _tbtn_prev = False

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.gamepad_running:
            return self.cancel(context)
        if event.type == 'ESC' and event.value == 'PRESS':
            wm.gamepad_running = False
            return self.cancel(context)

        p = context.preferences.addons[__name__].preferences

        # keyboard switch (kept as an alternative to the controller button)
        if event.type == p.toggle_key and event.value in {'PRESS', 'RELEASE'}:
            _apply_mode(wm, p.toggle_behavior, event.value == 'PRESS', event.value == 'RELEASE')
            _redraw(context)
            return {'RUNNING_MODAL'}  # swallow so Blender ignores it

        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if _js is None or _pg is None:
            return {'PASS_THROUGH'}

        now = time.perf_counter()
        dt = min(now - self._last, 0.1)
        self._last = now
        _pg.event.pump()

        def axis(i):
            try:
                return _dz(_js.get_axis(i), p.deadzone)
            except Exception:
                return 0.0

        def button(i):
            try:
                return _js.get_button(i) == 1
            except Exception:
                return False

        # controller switch — evaluated in BOTH modes so it can flip back
        if p.toggle_btn >= 0:
            if p.toggle_kind == 'AXIS':
                try:
                    v = _js.get_axis(p.toggle_btn)
                except Exception:
                    v = 0.0
                cur = (v > 0.3) if p.toggle_axis_sign == 'POS' else (v < -0.3)
            else:
                cur = button(p.toggle_btn)
            if _apply_mode(wm, p.toggle_behavior, cur and not self._tbtn_prev,
                           (not cur) and self._tbtn_prev):
                _redraw(context)
            self._tbtn_prev = cur

        # Cursor mode: do nothing with the sticks — the standalone app reads them.
        if wm.gamepad_cursor_mode:
            return {'PASS_THROUGH'}

        lx, ly = axis(p.lx_axis), axis(p.ly_axis)
        rx, ry = axis(p.rx_axis), axis(p.ry_axis)
        if not (lx or ly or rx or ry):
            return {'PASS_THROUGH'}

        area, rv3d = _find_view3d(context)
        if rv3d is None:
            return {'PASS_THROUGH'}

        rot = rv3d.view_rotation
        right = rot @ Vector((1.0, 0.0, 0.0))
        fwd = rot @ Vector((0.0, 0.0, -1.0))
        back = rot @ Vector((0.0, 0.0, 1.0))
        boost = p.boost_mult if (p.boost_btn >= 0 and button(p.boost_btn)) else 1.0

        # left stick: move on the view plane (strafe + forward/back)
        if lx or ly:
            step = p.move_speed * boost * dt
            fwd_amt = ly if p.invert_left_y else -ly
            rv3d.view_location += right * (lx * step)
            rv3d.view_location += fwd * (fwd_amt * step)

        # right stick: look (yaw + pitch) about the current view pivot
        if rx or ry:
            eye = rv3d.view_location + back * rv3d.view_distance
            yaw = -rx * p.look_speed * dt
            pitch = (ry if p.invert_right_y else -ry) * p.look_speed * dt
            new_rot = (Quaternion((0.0, 0.0, 1.0), yaw) @ Quaternion(right, pitch) @ rot).normalized()
            rv3d.view_rotation = new_rot
            back2 = new_rot @ Vector((0.0, 0.0, 1.0))
            rv3d.view_location = eye - back2 * rv3d.view_distance

        if area is not None:
            area.tag_redraw()
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        ok, msg = _ensure_pygame()
        if not ok:
            self.report({'ERROR'}, msg)
            context.window_manager.gamepad_running = False
            return {'CANCELLED'}
        wm = context.window_manager
        wm.gamepad_cursor_mode = False
        wm.gamepad_status = "FLY mode"
        self._tbtn_prev = False
        self.report({'INFO'}, "Gamepad: %s" % msg)
        self._last = time.perf_counter()
        self._timer = wm.event_timer_add(1.0 / 90.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.gamepad_status = "stopped"
        return {'CANCELLED'}


class VIEW3D_OT_gamepad_toggle(bpy.types.Operator):
    bl_idname = "view3d.gamepad_toggle"
    bl_label = "Start / Stop"

    def execute(self, context):
        wm = context.window_manager
        if wm.gamepad_running:
            wm.gamepad_running = False
        else:
            wm.gamepad_running = True
            bpy.ops.view3d.gamepad_fly('INVOKE_DEFAULT')
        return {'FINISHED'}


# ----------------------------------------------------------------------------
# preferences + panel
# ----------------------------------------------------------------------------
_BEHAVIOR_ITEMS = [
    ('TOGGLE', "Toggle (press to switch)", "Each press flips between Fly and Cursor"),
    ('HOLD_FLY', "Hold to Fly", "Fly while held, Cursor when released"),
    ('HOLD_CURSOR', "Hold to Cursor", "Cursor while held, Fly when released"),
]

_TOGGLE_KEY_ITEMS = [
    ('ACCENT_GRAVE', "` (backtick)", ""),
    ('TAB', "Tab", ""),
    ('SPACE', "Space", ""),
    ('LEFT_BRACKET', "[", ""),
    ('RIGHT_BRACKET', "]", ""),
    ('Q', "Q", ""), ('E', "E", ""), ('R', "R", ""), ('F', "F", ""),
    ('Z', "Z", ""), ('X', "X", ""), ('C', "C", ""), ('V', "V", ""),
    ('F1', "F1", ""), ('F2', "F2", ""), ('F3', "F3", ""), ('F4', "F4", ""),
    ('F5', "F5", ""), ('F6', "F6", ""), ('F7', "F7", ""), ('F8', "F8", ""),
    ('F9', "F9", ""), ('F10', "F10", ""), ('F11', "F11", ""), ('F12', "F12", ""),
]


class GamepadFlyPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    deadzone: FloatProperty(name="Deadzone", default=0.12, min=0.0, max=0.6)
    move_speed: FloatProperty(name="Move speed", default=6.0, min=0.1, max=80.0)
    look_speed: FloatProperty(name="Look speed", default=2.2, min=0.1, max=8.0)
    boost_mult: FloatProperty(name="Boost x", default=3.0, min=1.0, max=12.0)
    invert_left_y: BoolProperty(name="Invert left stick Y", default=True)
    invert_right_y: BoolProperty(name="Invert right stick Y", default=True)
    lx_axis: IntProperty(name="Left X axis", default=0, min=0, max=15)
    ly_axis: IntProperty(name="Left Y axis", default=1, min=0, max=15)
    rx_axis: IntProperty(name="Right X axis", default=2, min=0, max=15)
    ry_axis: IntProperty(name="Right Y axis", default=3, min=0, max=15)
    boost_btn: IntProperty(name="Boost button (-1 = off)", default=4, min=-1, max=20)

    toggle_behavior: EnumProperty(name="Switch behavior", items=_BEHAVIOR_ITEMS,
                                  default='HOLD_FLY')
    toggle_kind: EnumProperty(name="Switch input",
                              items=[('BUTTON', "Button", ""), ('AXIS', "Trigger / Axis", "")],
                              default='BUTTON')
    toggle_btn: IntProperty(name="Index (-1 = none)", default=-1, min=-1, max=31)
    toggle_axis_sign: EnumProperty(name="Axis dir",
                                   items=[('POS', "+", ""), ('NEG', "-", "")], default='POS')
    toggle_key: EnumProperty(name="Fly/Cursor key (optional)", items=_TOGGLE_KEY_ITEMS,
                             default='ACCENT_GRAVE')

    def draw(self, ctx):
        c = self.layout.column()
        row = c.row()
        row.operator("view3d.gp_install_pygame", icon='IMPORT')
        row.operator("view3d.gp_save_settings", icon='FILE_TICK')
        row.operator("view3d.gp_load_settings", icon='FILE_FOLDER')
        c.separator()
        c.label(text="Feel")
        r = c.row(); r.prop(self, "move_speed"); r.prop(self, "look_speed")
        r = c.row(); r.prop(self, "deadzone"); r.prop(self, "boost_mult")
        r = c.row(); r.prop(self, "invert_left_y"); r.prop(self, "invert_right_y")
        c.separator()
        c.label(text="Stick axes")
        r = c.row(); r.prop(self, "lx_axis"); r.prop(self, "ly_axis")
        r = c.row(); r.prop(self, "rx_axis"); r.prop(self, "ry_axis")
        c.prop(self, "boost_btn")
        c.separator()
        c.label(text="Fly / Cursor switch")
        c.prop(self, "toggle_behavior")
        c.operator("view3d.gp_learn_button", text="Listen (button or trigger)", icon='REC')
        r = c.row()
        r.prop(self, "toggle_kind", text="")
        r.prop(self, "toggle_btn")
        if self.toggle_kind == 'AXIS':
            r.prop(self, "toggle_axis_sign", text="")
        c.prop(self, "toggle_key")


class VIEW3D_PT_gamepad_fly(bpy.types.Panel):
    bl_label = "Gamepad Fly"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Gamepad"

    def draw(self, context):
        wm = context.window_manager
        p = context.preferences.addons[__name__].preferences
        col = self.layout.column()
        running = wm.gamepad_running
        col.operator("view3d.gamepad_toggle",
                     text="Stop" if running else "Start",
                     icon='PAUSE' if running else 'PLAY')
        mode = "CURSOR" if wm.gamepad_cursor_mode else "FLY"
        col.label(text="Mode: " + mode)
        row = col.row()
        row.enabled = running
        row.operator("view3d.gamepad_mode",
                     text="Switch to %s" % ("FLY" if wm.gamepad_cursor_mode else "CURSOR"))
        if p.toggle_btn >= 0:
            if p.toggle_kind == 'AXIS':
                src = "axis %d%s" % (p.toggle_btn, "+" if p.toggle_axis_sign == 'POS' else "-")
            else:
                src = "button %d" % p.toggle_btn
            col.label(text="Switch: %s (%s)" % (src, p.toggle_behavior))
        else:
            col.label(text="Switch: key %s (%s)" % (p.toggle_key, p.toggle_behavior))
        if wm.gamepad_status:
            col.label(text=wm.gamepad_status)
        col.separator()
        col.label(text="Cursor mode hands the sticks")
        col.label(text="to the GamepadMapper app.")


classes = (
    VIEW3D_OT_gp_install_pygame,
    VIEW3D_OT_gp_save,
    VIEW3D_OT_gp_load,
    VIEW3D_OT_gp_learn_button,
    VIEW3D_OT_gamepad_mode,
    VIEW3D_OT_gamepad_fly,
    VIEW3D_OT_gamepad_toggle,
    GamepadFlyPrefs,
    VIEW3D_PT_gamepad_fly,
)


def register():
    bpy.types.WindowManager.gamepad_running = BoolProperty(default=False)
    bpy.types.WindowManager.gamepad_cursor_mode = BoolProperty(default=False)
    bpy.types.WindowManager.gamepad_status = StringProperty(default="")
    for c in classes:
        bpy.utils.register_class(c)
    try:
        bpy.app.timers.register(_autoload, first_interval=0.3)
    except Exception:
        pass


def unregister():
    try:
        _save_settings(bpy.context.preferences.addons[__name__].preferences)
    except Exception:
        pass
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.gamepad_running
    del bpy.types.WindowManager.gamepad_cursor_mode
    del bpy.types.WindowManager.gamepad_status


if __name__ == "__main__":
    register()
