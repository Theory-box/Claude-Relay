bl_info = {
    "name": "Gamepad Fly + Mapper",
    "author": "Claude Relay",
    "version": (0, 7, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Gamepad",
    "description": "Fly camera, mouse mode, and a self-service button->keystroke/mouse mapper (macOS).",
    "category": "3D View",
}

import sys
import time
import json
import subprocess
from pathlib import Path

import bpy
from bpy.props import (IntProperty, FloatProperty, BoolProperty, StringProperty,
                       EnumProperty, CollectionProperty)
from mathutils import Vector, Quaternion

_pg = None
_js = None
_Q = None          # Quartz module once loaded
_perm = None       # cached Accessibility-trusted bool
_mouse_held = None  # mouse button currently held down (for drag)

MOD_SHIFT = 0x20000
MOD_CONTROL = 0x40000
MOD_ALT = 0x80000
MOD_CMD = 0x100000

KEYCODES = {
    'a': 0, 'b': 11, 'c': 8, 'd': 2, 'e': 14, 'f': 3, 'g': 5, 'h': 4, 'i': 34,
    'j': 38, 'k': 40, 'l': 37, 'm': 46, 'n': 45, 'o': 31, 'p': 35, 'q': 12,
    'r': 15, 's': 1, 't': 17, 'u': 32, 'v': 9, 'w': 13, 'x': 7, 'y': 16, 'z': 6,
    '0': 29, '1': 18, '2': 19, '3': 20, '4': 21, '5': 23, '6': 22, '7': 26,
    '8': 28, '9': 25,
    'space': 49, 'return': 36, 'enter': 36, 'tab': 48, 'escape': 53, 'esc': 53,
    'delete': 51, 'backspace': 51, 'forwarddelete': 117,
    'up': 126, 'down': 125, 'left': 123, 'right': 124,
    'home': 115, 'end': 119, 'pageup': 116, 'pagedown': 121,
    'minus': 27, 'equals': 24, 'comma': 43, 'period': 47, 'slash': 44,
    'semicolon': 41, 'quote': 39, 'leftbracket': 33, 'rightbracket': 30,
    'backslash': 42, 'grave': 50,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96, 'f6': 97, 'f7': 98,
    'f8': 100, 'f9': 101, 'f10': 109, 'f11': 103, 'f12': 111,
}

BL_KEYMAP = {
    'A': 'a', 'B': 'b', 'C': 'c', 'D': 'd', 'E': 'e', 'F': 'f', 'G': 'g', 'H': 'h',
    'I': 'i', 'J': 'j', 'K': 'k', 'L': 'l', 'M': 'm', 'N': 'n', 'O': 'o', 'P': 'p',
    'Q': 'q', 'R': 'r', 'S': 's', 'T': 't', 'U': 'u', 'V': 'v', 'W': 'w', 'X': 'x',
    'Y': 'y', 'Z': 'z',
    'ZERO': '0', 'ONE': '1', 'TWO': '2', 'THREE': '3', 'FOUR': '4', 'FIVE': '5',
    'SIX': '6', 'SEVEN': '7', 'EIGHT': '8', 'NINE': '9',
    'SPACE': 'space', 'RET': 'return', 'TAB': 'tab', 'ESC': 'escape',
    'BACK_SPACE': 'backspace', 'DEL': 'forwarddelete',
    'LEFT_ARROW': 'left', 'RIGHT_ARROW': 'right', 'UP_ARROW': 'up', 'DOWN_ARROW': 'down',
    'HOME': 'home', 'END': 'end', 'PAGE_UP': 'pageup', 'PAGE_DOWN': 'pagedown',
    'MINUS': 'minus', 'EQUAL': 'equals', 'COMMA': 'comma', 'PERIOD': 'period',
    'SLASH': 'slash', 'SEMI_COLON': 'semicolon', 'QUOTE': 'quote',
    'LEFT_BRACKET': 'leftbracket', 'RIGHT_BRACKET': 'rightbracket',
    'BACK_SLASH': 'backslash', 'ACCENT_GRAVE': 'grave',
    'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4', 'F5': 'f5', 'F6': 'f6',
    'F7': 'f7', 'F8': 'f8', 'F9': 'f9', 'F10': 'f10', 'F11': 'f11', 'F12': 'f12',
}

MOD_TYPES = {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT',
             'RIGHT_ALT', 'OSKEY', 'LEFT_COMMAND', 'RIGHT_COMMAND'}

MODMAP = {'SHIFT': MOD_SHIFT, 'CTRL': MOD_CONTROL, 'ALT': MOD_ALT, 'CMD': MOD_CMD}


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


def _ensure_quartz():
    global _Q
    if _Q is not None:
        return True
    _libs()
    try:
        import Quartz
        _Q = Quartz
        return True
    except Exception:
        return False


def _check_perm(prompt):
    global _perm
    if not _ensure_quartz():
        return None
    try:
        from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                         kAXTrustedCheckOptionPrompt)
        _perm = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: bool(prompt)}))
    except Exception:
        try:
            from ApplicationServices import AXIsProcessTrusted
            _perm = bool(AXIsProcessTrusted())
        except Exception:
            _perm = None
    return _perm


def _post_key(keycode, flags, down):
    ev = _Q.CGEventCreateKeyboardEvent(None, keycode, down)
    if flags:
        _Q.CGEventSetFlags(ev, flags)
    _Q.CGEventPost(_Q.kCGHIDEventTap, ev)


def _post_mouse(btn, down, flags=0):
    loc = _Q.CGEventGetLocation(_Q.CGEventCreate(None))
    table = {
        'LEFT': (_Q.kCGEventLeftMouseDown, _Q.kCGEventLeftMouseUp, _Q.kCGMouseButtonLeft),
        'RIGHT': (_Q.kCGEventRightMouseDown, _Q.kCGEventRightMouseUp, _Q.kCGMouseButtonRight),
        'MIDDLE': (_Q.kCGEventOtherMouseDown, _Q.kCGEventOtherMouseUp, _Q.kCGMouseButtonCenter),
    }
    d, u, b = table[btn]
    ev = _Q.CGEventCreateMouseEvent(None, d if down else u, loc, b)
    if flags:
        _Q.CGEventSetFlags(ev, flags)
    _Q.CGEventPost(_Q.kCGHIDEventTap, ev)


def _post_scroll(amount):
    ev = _Q.CGEventCreateScrollWheelEvent(None, _Q.kCGScrollEventUnitLine, 1, int(amount))
    _Q.CGEventPost(_Q.kCGHIDEventTap, ev)


def _post_drag(btn):
    loc = _Q.CGEventGetLocation(_Q.CGEventCreate(None))
    table = {'LEFT': (_Q.kCGEventLeftMouseDragged, _Q.kCGMouseButtonLeft),
             'RIGHT': (_Q.kCGEventRightMouseDragged, _Q.kCGMouseButtonRight),
             'MIDDLE': (_Q.kCGEventOtherMouseDragged, _Q.kCGMouseButtonCenter)}
    t, b = table[btn]
    ev = _Q.CGEventCreateMouseEvent(None, t, loc, b)
    _Q.CGEventPost(_Q.kCGHIDEventTap, ev)


def _curve(v, c):
    return (1.0 if v >= 0 else -1.0) * (abs(v) ** c)


SCALAR_KEYS = ['deadzone', 'move_speed', 'look_speed', 'cursor_speed', 'cursor_curve',
               'boost_mult', 'invert_left_y', 'invert_right_y', 'invert_cursor_y',
               'lx_axis', 'ly_axis', 'rx_axis', 'ry_axis', 'boost_btn']
BIND_KEYS = ['input_kind', 'index', 'axis_sign', 'axis_threshold', 'hat_x', 'hat_y',
             'action', 'key', 'mod_cmd', 'mod_shift', 'mod_ctrl', 'mod_alt',
             'mouse_btn', 'scroll_amt', 'hold', 'mod_key']


def _settings_path():
    return Path(bpy.utils.user_resource('CONFIG', create=True)) / "gamepad_fly_settings.json"


def _save_settings(prefs):
    data = {'scalars': {k: getattr(prefs, k) for k in SCALAR_KEYS},
            'bindings': [{k: getattr(b, k) for k in BIND_KEYS} for b in prefs.bindings]}
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
    prefs.bindings.clear()
    for bd in data.get('bindings', []):
        b = prefs.bindings.add()
        for k, v in bd.items():
            try:
                setattr(b, k, v)
            except Exception:
                pass
    return True


def _autoload():
    try:
        _load_settings(bpy.context.preferences.addons[__name__].preferences)
    except Exception:
        pass
    return None


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


def _window_size(context):
    areas = context.screen.areas
    return (max(a.x + a.width for a in areas), max(a.y + a.height for a in areas))


def _mods(b):
    f = 0
    if b.mod_cmd:
        f |= MOD_CMD
    if b.mod_shift:
        f |= MOD_SHIFT
    if b.mod_ctrl:
        f |= MOD_CONTROL
    if b.mod_alt:
        f |= MOD_ALT
    return f


def _binding_pressed(b):
    try:
        if b.input_kind == 'BUTTON':
            return _js.get_button(b.index) == 1
        if b.input_kind == 'AXIS':
            v = _js.get_axis(b.index)
            th = b.axis_threshold
            return v > th if b.axis_sign == 'POS' else v < -th
        if b.input_kind == 'HAT':
            hx, hy = _js.get_hat(b.index)
            return (hx, hy) == (b.hat_x, b.hat_y) and (hx or hy)
    except Exception:
        return False
    return False


def _fire(b, rising, falling, held, wm, extra_flags=0):
    if b.action == 'MODIFIER':
        return ""
    if b.action == 'MODE':
        if rising:
            wm.gamepad_mouse_mode = not wm.gamepad_mouse_mode
        return "mode toggle"
    if _Q is None:
        return "needs pyobjc"
    if b.action == 'KEY':
        kc = KEYCODES.get(b.key.strip().lower())
        if kc is None:
            return "unknown key '%s'" % b.key
        flags = _mods(b) | extra_flags
        if b.hold:
            if rising:
                _post_key(kc, flags, True)
            elif falling:
                _post_key(kc, flags, False)
        elif rising:
            _post_key(kc, flags, True)
            _post_key(kc, flags, False)
        return "key %s" % b.key
    if b.action == 'MOUSE':
        global _mouse_held
        flags = _mods(b) | extra_flags
        if b.hold:
            if rising:
                _post_mouse(b.mouse_btn, True, flags)
                _mouse_held = b.mouse_btn
            elif falling:
                _post_mouse(b.mouse_btn, False, flags)
                _mouse_held = None
        elif rising:
            _post_mouse(b.mouse_btn, True, flags)
            _post_mouse(b.mouse_btn, False, flags)
        return "mouse %s" % b.mouse_btn
    if b.action == 'SCROLL':
        if rising or held:
            _post_scroll(b.scroll_amt)
        return "scroll"
    return ""


class GamepadBinding(bpy.types.PropertyGroup):
    input_kind: EnumProperty(name="Input", items=[
        ('BUTTON', "Button", ""), ('AXIS', "Trigger/Axis", ""), ('HAT', "D-pad", "")],
        default='BUTTON')
    index: IntProperty(name="Index", default=0, min=0, max=31)
    axis_sign: EnumProperty(name="Dir", items=[('POS', "+", ""), ('NEG', "-", "")], default='POS')
    axis_threshold: FloatProperty(name="Threshold", default=0.5, min=-1.0, max=1.0)
    hat_x: IntProperty(name="Hat X", default=0, min=-1, max=1)
    hat_y: IntProperty(name="Hat Y", default=0, min=-1, max=1)

    action: EnumProperty(name="Action", items=[
        ('KEY', "Keystroke", ""), ('MOUSE', "Mouse click", ""),
        ('SCROLL', "Scroll", ""), ('MODIFIER', "Hold modifier", ""),
        ('MODE', "Toggle mouse mode", "")], default='KEY')
    mod_key: EnumProperty(name="Modifier", items=[
        ('SHIFT', "Shift", ""), ('CTRL', "Ctrl", ""), ('ALT', "Alt/Option", ""),
        ('CMD', "Cmd", "")], default='SHIFT')
    key: StringProperty(name="Key", default="z")
    mod_cmd: BoolProperty(name="Cmd", default=True)
    mod_shift: BoolProperty(name="Shift", default=False)
    mod_ctrl: BoolProperty(name="Ctrl", default=False)
    mod_alt: BoolProperty(name="Alt", default=False)
    mouse_btn: EnumProperty(name="Button", items=[
        ('LEFT', "Left", ""), ('RIGHT', "Right", ""), ('MIDDLE', "Middle", "")], default='LEFT')
    scroll_amt: IntProperty(name="Scroll", default=1, min=-10, max=10)
    hold: BoolProperty(name="Hold (vs tap)", default=False)

    def summary(self):
        if self.input_kind == 'BUTTON':
            src = "btn %d" % self.index
        elif self.input_kind == 'AXIS':
            src = "axis %d%s" % (self.index, "+" if self.axis_sign == 'POS' else "-")
        else:
            src = "hat (%d,%d)" % (self.hat_x, self.hat_y)
        if self.action == 'KEY':
            m = "".join(x for x, on in [("Cmd+", self.mod_cmd), ("Shift+", self.mod_shift),
                                        ("Ctrl+", self.mod_ctrl), ("Alt+", self.mod_alt)] if on)
            dst = m + self.key
        elif self.action == 'MOUSE':
            dst = self.mouse_btn + " click"
        elif self.action == 'MODIFIER':
            dst = "hold " + self.mod_key
        elif self.action == 'SCROLL':
            dst = "scroll %d" % self.scroll_amt
        else:
            dst = "mouse mode"
        return "%s  ->  %s" % (src, dst)


class GAMEPAD_UL_bindings(bpy.types.UIList):
    def draw_item(self, ctx, layout, data, item, icon, adata, aprop, index):
        layout.label(text=item.summary(), icon='DOT')


class VIEW3D_OT_gp_install_pygame(bpy.types.Operator):
    bl_idname = "view3d.gp_install_pygame"
    bl_label = "Install pygame"

    def execute(self, context):
        r = _pip_install(["pygame"])
        try:
            import pygame
            self.report({'INFO'}, "pygame %s installed" % pygame.__version__)
        except Exception:
            self.report({'ERROR'}, "restart Blender then retry. %s" % (r.stderr or "")[-160:])
        return {'FINISHED'}


class VIEW3D_OT_gp_install_quartz(bpy.types.Operator):
    bl_idname = "view3d.gp_install_quartz"
    bl_label = "Install pyobjc (OS actions)"

    def execute(self, context):
        r = _pip_install(["pyobjc-framework-Quartz", "pyobjc-framework-ApplicationServices"])
        if _ensure_quartz():
            self.report({'INFO'}, "pyobjc ready")
        else:
            self.report({'ERROR'}, "restart Blender then retry. %s" % (r.stderr or "")[-160:])
        return {'FINISHED'}


class VIEW3D_OT_gp_permission(bpy.types.Operator):
    bl_idname = "view3d.gp_permission"
    bl_label = "Grant Accessibility"

    def execute(self, context):
        t = _check_perm(prompt=True)
        if t:
            self.report({'INFO'}, "Accessibility granted")
        else:
            self.report({'WARNING'}, "Approve Blender in System Settings > Privacy > Accessibility, then restart")
        return {'FINISHED'}


class VIEW3D_OT_gp_save(bpy.types.Operator):
    bl_idname = "view3d.gp_save_settings"
    bl_label = "Save settings"

    def execute(self, context):
        try:
            _save_settings(context.preferences.addons[__name__].preferences)
            self.report({'INFO'}, "saved")
        except Exception as e:
            self.report({'ERROR'}, "save failed: %s" % e)
        return {'FINISHED'}


class VIEW3D_OT_gp_load(bpy.types.Operator):
    bl_idname = "view3d.gp_load_settings"
    bl_label = "Load settings"

    def execute(self, context):
        ok = _load_settings(context.preferences.addons[__name__].preferences)
        self.report({'INFO'} if ok else {'WARNING'}, "loaded" if ok else "no saved file yet")
        return {'FINISHED'}


class VIEW3D_OT_gp_add(bpy.types.Operator):
    bl_idname = "view3d.gp_add_binding"
    bl_label = "Add binding"

    def execute(self, context):
        p = context.preferences.addons[__name__].preferences
        p.bindings.add()
        p.active_binding = len(p.bindings) - 1
        return {'FINISHED'}


class VIEW3D_OT_gp_remove(bpy.types.Operator):
    bl_idname = "view3d.gp_remove_binding"
    bl_label = "Remove binding"

    def execute(self, context):
        p = context.preferences.addons[__name__].preferences
        if p.bindings:
            p.bindings.remove(p.active_binding)
            p.active_binding = max(0, p.active_binding - 1)
        return {'FINISHED'}


class VIEW3D_OT_gp_learn(bpy.types.Operator):
    bl_idname = "view3d.gp_learn"
    bl_label = "Learn input"
    _timer = None
    _base = None

    def modal(self, context, event):
        wm = context.window_manager
        if event.type == 'ESC':
            return self._end(context, "cancelled")
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if _js is None:
            return self._end(context, "no controller")
        _pg.event.pump()
        p = context.preferences.addons[__name__].preferences
        if not p.bindings:
            return self._end(context, "add a binding first")
        b = p.bindings[p.active_binding]
        for i in range(_js.get_numbuttons()):
            if _js.get_button(i):
                b.input_kind = 'BUTTON'; b.index = i
                return self._end(context, "learned button %d" % i)
        for i in range(_js.get_numhats()):
            hx, hy = _js.get_hat(i)
            if hx or hy:
                b.input_kind = 'HAT'; b.index = i; b.hat_x = hx; b.hat_y = hy
                return self._end(context, "learned d-pad")
        for i in range(_js.get_numaxes()):
            d = _js.get_axis(i) - self._base[i]
            if abs(d) > 0.5:
                b.input_kind = 'AXIS'; b.index = i
                b.axis_sign = 'POS' if d > 0 else 'NEG'
                return self._end(context, "learned axis %d" % i)
        wm.gamepad_status = "learning... press a control"
        return {'PASS_THROUGH'}

    def execute(self, context):
        ok, msg = _ensure_pygame()
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        _pg.event.pump()
        self._base = [_js.get_axis(i) for i in range(_js.get_numaxes())]
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 30.0, window=context.window)
        wm.modal_handler_add(self)
        wm.gamepad_status = "learning... press a control"
        return {'RUNNING_MODAL'}

    def _end(self, context, msg):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.gamepad_status = msg
        return {'FINISHED'}


class VIEW3D_OT_gp_learn_output(bpy.types.Operator):
    bl_idname = "view3d.gp_learn_output"
    bl_label = "Learn output"

    def modal(self, context, event):
        wm = context.window_manager
        p = context.preferences.addons[__name__].preferences
        if not p.bindings:
            wm.gamepad_status = "add a binding first"
            return {'CANCELLED'}
        b = p.bindings[p.active_binding]
        et = event.type
        if et == 'ESC':
            wm.gamepad_status = "output cancelled"
            return {'CANCELLED'}
        if et in MOD_TYPES:
            return {'RUNNING_MODAL'}
        if et in ('LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE') and event.value == 'PRESS':
            b.action = 'MOUSE'
            b.mouse_btn = {'LEFTMOUSE': 'LEFT', 'RIGHTMOUSE': 'RIGHT',
                           'MIDDLEMOUSE': 'MIDDLE'}[et]
            wm.gamepad_status = "output: %s click" % b.mouse_btn
            return {'FINISHED'}
        if et in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE'):
            b.action = 'SCROLL'
            b.scroll_amt = 1 if et == 'WHEELUPMOUSE' else -1
            wm.gamepad_status = "output: scroll"
            return {'FINISHED'}
        if event.value == 'PRESS' and et in BL_KEYMAP:
            b.action = 'KEY'
            b.key = BL_KEYMAP[et]
            b.mod_cmd = event.oskey
            b.mod_shift = event.shift
            b.mod_ctrl = event.ctrl
            b.mod_alt = event.alt
            wm.gamepad_status = "output: %s" % b.summary().split('->')[-1].strip()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        p = context.preferences.addons[__name__].preferences
        if not p.bindings:
            self.report({'ERROR'}, "add a binding first")
            return {'CANCELLED'}
        context.window_manager.gamepad_status = "press a key / combo / mouse (Esc cancels)"
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class VIEW3D_OT_gamepad_fly(bpy.types.Operator):
    bl_idname = "view3d.gamepad_fly"
    bl_label = "Gamepad (modal)"
    _timer = None
    _last = 0.0
    _prev = None
    _cur_synced = False
    _cx = 0.0
    _cy = 0.0

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.gamepad_running:
            return self.cancel(context)
        if event.type == 'ESC':
            wm.gamepad_running = False
            return self.cancel(context)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if _js is None or _pg is None:
            return {'PASS_THROUGH'}

        p = context.preferences.addons[__name__].preferences
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

        try:
            for i in range(_js.get_numbuttons()):
                if _js.get_button(i):
                    wm.gamepad_last_btn = i
                    break
        except Exception:
            pass

        # --- evaluate user bindings (OS actions) ---
        active_mods = 0
        for b in p.bindings:
            if b.action == 'MODIFIER' and _binding_pressed(b):
                active_mods |= MODMAP.get(b.mod_key, 0)

        for i, b in enumerate(p.bindings):
            pressed = _binding_pressed(b)
            prev = self._prev.get(i, False)
            res = _fire(b, pressed and not prev, (not pressed) and prev, pressed, wm, active_mods)
            if res and pressed and not prev:
                wm.gamepad_status = res
            self._prev[i] = pressed

        area, rv3d = _find_view3d(context)
        if area is not None:
            area.tag_redraw()

        lx, ly = axis(p.lx_axis), axis(p.ly_axis)
        rx, ry = axis(p.rx_axis), axis(p.ry_axis)

        if wm.gamepad_mouse_mode:
            win = context.window
            W, H = _window_size(context)
            if not self._cur_synced:
                self._cx = float(min(max(event.mouse_x, 0), W - 1))
                self._cy = float(min(max(event.mouse_y, 0), H - 1))
                self._cur_synced = True
            if lx or ly:
                spd = p.cursor_speed * dt
                cdy = ly if p.invert_cursor_y else -ly
                self._cx = max(0.0, min(W - 1, self._cx + _curve(lx, p.cursor_curve) * spd))
                self._cy = max(0.0, min(H - 1, self._cy + _curve(cdy, p.cursor_curve) * spd))
                win.cursor_warp(int(self._cx), int(self._cy))
                if _mouse_held and _Q is not None:
                    _post_drag(_mouse_held)
            return {'PASS_THROUGH'}
        else:
            self._cur_synced = False

        if rv3d is None or not (lx or ly or rx or ry):
            return {'PASS_THROUGH'}

        rot = rv3d.view_rotation
        right = rot @ Vector((1.0, 0.0, 0.0))
        fwd = rot @ Vector((0.0, 0.0, -1.0))
        back = rot @ Vector((0.0, 0.0, 1.0))
        boost = p.boost_mult if button(p.boost_btn) else 1.0

        if lx or ly:
            step = p.move_speed * boost * dt
            fwd_amt = ly if p.invert_left_y else -ly
            rv3d.view_location += right * (lx * step)
            rv3d.view_location += fwd * (fwd_amt * step)

        if rx or ry:
            eye = rv3d.view_location + back * rv3d.view_distance
            yaw = -rx * p.look_speed * dt
            pitch = (ry if p.invert_right_y else -ry) * p.look_speed * dt
            new_rot = (Quaternion((0.0, 0.0, 1.0), yaw) @ Quaternion(right, pitch) @ rot).normalized()
            rv3d.view_rotation = new_rot
            back2 = new_rot @ Vector((0.0, 0.0, 1.0))
            rv3d.view_location = eye - back2 * rv3d.view_distance
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        ok, msg = _ensure_pygame()
        if not ok:
            self.report({'ERROR'}, msg)
            context.window_manager.gamepad_running = False
            return {'CANCELLED'}
        _ensure_quartz()
        _check_perm(prompt=False)
        self.report({'INFO'}, "Gamepad: %s" % msg)
        self._last = time.perf_counter()
        self._prev = {}
        self._cur_synced = False
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 90.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        global _mouse_held
        if _mouse_held and _Q is not None:
            try:
                _post_mouse(_mouse_held, False)
            except Exception:
                pass
            _mouse_held = None
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
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


class GamepadFlyPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    deadzone: FloatProperty(name="Deadzone", default=0.12, min=0.0, max=0.6)
    move_speed: FloatProperty(name="Move speed", default=6.0, min=0.1, max=80.0)
    look_speed: FloatProperty(name="Look speed", default=2.2, min=0.1, max=8.0)
    cursor_speed: FloatProperty(name="Cursor speed", default=900.0, min=50.0, max=4000.0)
    cursor_curve: FloatProperty(name="Cursor accel", default=2.0, min=1.0, max=4.0)
    boost_mult: FloatProperty(name="Boost x", default=3.0, min=1.0, max=12.0)
    invert_left_y: BoolProperty(name="Invert left stick Y", default=True)
    invert_right_y: BoolProperty(name="Invert right stick Y", default=True)
    invert_cursor_y: BoolProperty(name="Invert cursor Y", default=True)
    lx_axis: IntProperty(name="Left X axis", default=0, min=0, max=15)
    ly_axis: IntProperty(name="Left Y axis", default=1, min=0, max=15)
    rx_axis: IntProperty(name="Right X axis", default=2, min=0, max=15)
    ry_axis: IntProperty(name="Right Y axis", default=3, min=0, max=15)
    boost_btn: IntProperty(name="Boost button", default=4, min=0, max=20)

    bindings: CollectionProperty(type=GamepadBinding)
    active_binding: IntProperty(default=0)

    def draw(self, ctx):
        c = self.layout.column()
        row = c.row()
        row.operator("view3d.gp_install_pygame", icon='IMPORT')
        row.operator("view3d.gp_install_quartz", icon='IMPORT')
        row.operator("view3d.gp_permission", icon='CHECKMARK')
        row = c.row()
        row.operator("view3d.gp_save_settings", icon='FILE_TICK')
        row.operator("view3d.gp_load_settings", icon='FILE_FOLDER')
        c.separator()
        c.label(text="Feel")
        r = c.row(); r.prop(self, "move_speed"); r.prop(self, "look_speed")
        r = c.row(); r.prop(self, "cursor_speed"); r.prop(self, "cursor_curve")
        r = c.row(); r.prop(self, "deadzone"); r.prop(self, "boost_mult")
        r = c.row(); r.prop(self, "invert_left_y"); r.prop(self, "invert_right_y")
        c.prop(self, "invert_cursor_y")
        c.separator()
        c.label(text="Stick axes")
        r = c.row(); r.prop(self, "lx_axis"); r.prop(self, "ly_axis")
        r = c.row(); r.prop(self, "rx_axis"); r.prop(self, "ry_axis")
        c.prop(self, "boost_btn")
        c.separator()
        c.label(text="Button / trigger / d-pad mappings")
        row = c.row()
        row.template_list("GAMEPAD_UL_bindings", "", self, "bindings", self, "active_binding", rows=4)
        col = row.column(align=True)
        col.operator("view3d.gp_add_binding", text="", icon='ADD')
        col.operator("view3d.gp_remove_binding", text="", icon='REMOVE')
        if self.bindings and 0 <= self.active_binding < len(self.bindings):
            b = self.bindings[self.active_binding]
            box = c.box()
            r = box.row()
            r.operator("view3d.gp_learn", text="Learn (press a control)", icon='REC')
            r.prop(b, "input_kind", text="")
            r = box.row()
            r.prop(b, "index")
            if b.input_kind == 'AXIS':
                r.prop(b, "axis_sign", text="")
                r.prop(b, "axis_threshold")
            if b.input_kind == 'HAT':
                r.prop(b, "hat_x"); r.prop(b, "hat_y")
            box.prop(b, "action", text="Does")
            box.operator("view3d.gp_learn_output",
                         text="Learn output (press key / combo / mouse)", icon='REC')
            if b.action == 'KEY':
                r = box.row()
                r.prop(b, "mod_cmd", toggle=True); r.prop(b, "mod_shift", toggle=True)
                r.prop(b, "mod_ctrl", toggle=True); r.prop(b, "mod_alt", toggle=True)
                box.prop(b, "key")
            elif b.action == 'MOUSE':
                box.prop(b, "mouse_btn", text="")
            elif b.action == 'MODIFIER':
                box.prop(b, "mod_key", text="")
            elif b.action == 'SCROLL':
                box.prop(b, "scroll_amt")
            box.prop(b, "hold")


class VIEW3D_PT_gamepad_fly(bpy.types.Panel):
    bl_label = "Gamepad"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Gamepad"

    def draw(self, context):
        wm = context.window_manager
        col = self.layout.column()
        running = wm.gamepad_running
        col.operator("view3d.gamepad_toggle",
                     text="Stop" if running else "Start",
                     icon='PAUSE' if running else 'PLAY')
        mode = "MOUSE" if wm.gamepad_mouse_mode else "FLY"
        col.label(text="Mode: " + mode)
        if running:
            col.label(text="Last button: %d" % wm.gamepad_last_btn)
        perm = "granted" if _perm else ("denied/unknown" if _Q else "pyobjc not loaded")
        col.label(text="OS actions: " + perm)
        if wm.gamepad_status:
            col.label(text=wm.gamepad_status)
        col.separator()
        col.label(text="Configure mappings in")
        col.label(text="Preferences > Add-ons > this add-on")


classes = (
    GamepadBinding,
    GAMEPAD_UL_bindings,
    VIEW3D_OT_gp_install_pygame,
    VIEW3D_OT_gp_install_quartz,
    VIEW3D_OT_gp_permission,
    VIEW3D_OT_gp_save,
    VIEW3D_OT_gp_load,
    VIEW3D_OT_gp_add,
    VIEW3D_OT_gp_remove,
    VIEW3D_OT_gp_learn,
    VIEW3D_OT_gp_learn_output,
    VIEW3D_OT_gamepad_fly,
    VIEW3D_OT_gamepad_toggle,
    GamepadFlyPrefs,
    VIEW3D_PT_gamepad_fly,
)


def register():
    bpy.types.WindowManager.gamepad_running = BoolProperty(default=False)
    bpy.types.WindowManager.gamepad_mouse_mode = BoolProperty(default=False)
    bpy.types.WindowManager.gamepad_last_btn = IntProperty(default=-1)
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
    del bpy.types.WindowManager.gamepad_mouse_mode
    del bpy.types.WindowManager.gamepad_last_btn
    del bpy.types.WindowManager.gamepad_status


if __name__ == "__main__":
    register()
