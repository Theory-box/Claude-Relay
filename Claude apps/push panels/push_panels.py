bl_info = {
    "name": "Push Panels",
    "blender": (4, 4, 0),
    "location": "Preferences > Add-ons > Push Panels (set your own key)",
    "description": "Shove area dividers out of the way with the cursor",
    "author": "",
    "version": (0, 6, 0),
    "category": "Interface",
}

# ---------------------------------------------------------------------------
# Two mechanisms, selectable in preferences.
#
# GRAB (default) -- the smooth one.
#   Blender's native edge drag (screen.area_move's modal) is speed-immune: it
#   checks its poll ONCE at invoke, captures a fixed mouse+edge anchor, and
#   from then on sets  edge = anchor_edge + (mouse - anchor_mouse)  every frame
#   without ever re-polling or warping the cursor. That is why dragging a
#   divider by hand is perfectly fluid at any speed.
#
#   So instead of imitating it, this mode hands off to it: while your key is
#   held, the moment the cursor reaches an edge we invoke the native drag and
#   let it run. We temporarily bind your key's RELEASE to the native "confirm"
#   action (via the Standard Modal Map that area_move uses), so letting go of
#   the key drops the edge -- your hold-and-release feel, native smoothness.
#
# PUSH -- the fallback.
#   Repeatedly calls area_move ourselves. Because each call re-runs the poll
#   (which fails unless the cursor is within BORDERPADDING of the edge), fast
#   motion forces either a corrective warp (jitter) or a stall (lag). Kept for
#   comparison and for anyone who wants strict release-to-stop without the
#   click/þconfirm semantics. Not as smooth as GRAB at speed.
# ---------------------------------------------------------------------------

import bpy
from bpy.props import BoolProperty, IntProperty, EnumProperty

DEFAULT_KEY = 'F6'
AREAGRID = 4                # DNA_screen_types.h
MODAL_MAP = "Standard Modal Map"


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def _prefs(context):
    try:
        return context.preferences.addons[__name__].preferences
    except (KeyError, AttributeError):
        return None


def _borderpadding(context):
    """BORDERPADDING = (3.0 * UI_SCALE_FAC) + U.pixelsize (min 2 in edge search)."""
    try:
        sp = context.preferences.system
        ui = getattr(sp, "ui_scale", 1.0) or 1.0
        px = getattr(sp, "pixel_size", 1) or 1
        return max(2, int(3.0 * ui + px))
    except AttributeError:
        return 4


class PushPanelsPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    mode: EnumProperty(
        name="Mode",
        items=[
            ('GRAB', "Grab (smooth, native)",
             "Hand off to Blender's own edge drag. Smooth at any speed. "
             "Hold the key, reach an edge to grab it, release to drop"),
            ('PUSH', "Push (release-to-stop)",
             "Move the edge ourselves each frame. Strict release-to-stop, "
             "but can jitter or lag when you move fast"),
        ],
        default='GRAB',
    )
    grab_reach: IntProperty(
        name="Grab reach",
        description="GRAB: snap onto and grab an edge when the cursor comes "
                    "this close to it (pixels)",
        default=12, min=2, max=60,
    )
    passthrough: BoolProperty(
        name="Pass mouse motion through (PUSH)",
        description="PUSH only: required so Blender keeps updating its active "
                    "region. For diagnosis only",
        default=True,
    )
    debug: BoolProperty(
        name="Report diagnostics",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode")
        col = layout.column()
        if self.mode == 'GRAB':
            col.prop(self, "grab_reach")
            box = layout.box()
            box.label(text="Hold key -> glide to an edge -> it grabs -> "
                           "release to drop.", icon='INFO')
            box.label(text="Right-click or Esc cancels a grab in progress.")
        else:
            col.prop(self, "passthrough")
            box = layout.box()
            box.label(text="Divider zone on this display: %d px"
                           % _borderpadding(context), icon='INFO')
        col.prop(self, "debug")

        layout.separator()
        layout.label(text="Keybinding (click, then press any key):")
        self._draw_keymap(context, layout)

    def _draw_keymap(self, context, layout):
        try:
            import rna_keymap_ui
        except ImportError:
            layout.label(text="Keymap UI unavailable", icon='ERROR')
            return
        kc = context.window_manager.keyconfigs.user
        km = kc.keymaps.get('Screen')
        if km is None:
            layout.label(text="'Screen' keymap not found", icon='ERROR')
            return
        for kmi in km.keymap_items:
            if kmi.idname == SCREEN_OT_push_panels.bl_idname:
                rna_keymap_ui.draw_kmi([], kc, km, kmi, layout, 0)


# ---------------------------------------------------------------------------
# Modal-map confirm binding (GRAB): make the trigger key's RELEASE confirm the
# native drag. Added just before handoff, removed when our operator ends.
# ---------------------------------------------------------------------------

def _set_release_confirm(context, key_type):
    """Bind `key_type` RELEASE -> APPLY on the Standard Modal Map. Returns the
    keymap item so it can be removed again, or None."""
    _clear_release_confirm(context)
    for kcname in ('user', 'active', 'default'):
        kc = getattr(context.window_manager.keyconfigs, kcname, None)
        if not kc:
            continue
        km = kc.keymaps.get(MODAL_MAP)
        if km is None:
            continue
        try:
            kmi = km.keymap_items.new_modal('APPLY', key_type, 'RELEASE')
            _RELEASE_KMI.append((km, kmi))
        except (RuntimeError, TypeError):
            pass
    return bool(_RELEASE_KMI)


def _clear_release_confirm(context):
    while _RELEASE_KMI:
        km, kmi = _RELEASE_KMI.pop()
        try:
            km.keymap_items.remove(kmi)
        except (RuntimeError, ReferenceError):
            pass


_RELEASE_KMI = []


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class SCREEN_OT_push_panels(bpy.types.Operator):
    bl_idname = "screen.push_panels"
    bl_label = "Push Panels"
    # No 'BLOCKING': in PUSH mode consuming mouse motion freezes active_region.

    # ---- lifecycle ----------------------------------------------------
    def invoke(self, context, event):
        screen, area = context.screen, context.area
        if area is None:
            return {'CANCELLED'}
        try:
            self._index = list(screen.areas).index(area)
        except ValueError:
            return {'CANCELLED'}

        self._trigger = event.type
        self._count = len(screen.areas)
        self._said = set()
        self._moves = 0

        p = _prefs(context)
        self._mode = p.mode if p else 'GRAB'
        self._grab_reach = p.grab_reach if p else 12
        self._passthrough = p.passthrough if p else True
        self._debug = p.debug if p else False
        self._bp = _borderpadding(context)

        # GRAB arming state (retry the native handoff across a few frames
        # while active_region catches up to a fast cursor).
        self._arming = False
        self._arm = None          # (axis, edge_coord, other_mid)
        self._tries = 0
        self._confirm_set = False

        # PUSH state
        self._x = _Axis(+1)
        self._y = _Axis(+1)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _once(self, msg, level='WARNING'):
        if msg not in self._said:
            self._said.add(msg)
            self.report({level}, msg)
            print("[push_panels] " + msg)

    def _area(self, context):
        areas = context.screen.areas
        if len(areas) != self._count or self._index >= len(areas):
            return None
        return areas[self._index]

    def _finish(self, context, status):
        # GRAB may have left a release-confirm binding; PUSH never adds one.
        return status

    # ---- modal --------------------------------------------------------
    def modal(self, context, event):
        if event.type == self._trigger and event.value == 'RELEASE':
            if self._moves == 0 and self._debug:
                self._once("released without grabbing/moving", 'INFO')
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'CANCELLED'}
        if event.type != 'MOUSEMOVE':
            return {'RUNNING_MODAL'}

        area = self._area(context)
        if area is None:
            return {'CANCELLED'}

        if self._mode == 'GRAB':
            return self._modal_grab(context, event, area)
        return self._modal_push(context, event, area)

    # ---- GRAB: hand off to the native drag ----------------------------
    #
    # The native operator's poll needs screen->active_region == null, which
    # only holds once the cursor has been observed within BORDERPADDING of an
    # edge. On a fast sweep the cursor crosses that zone between two frames, so
    # the very frame we want to hand off, active_region still reflects the
    # cursor sitting inside the area and the poll fails.
    #
    # We fix this by "arming": once the cursor is near an edge we warp it onto
    # that edge (which updates eventstate->xy, so active_region clears on the
    # next synthetic move) and retry the handoff for a few frames until the
    # poll passes. A poll failure is expected mid-arming, not an error.
    MAX_GRAB_TRIES = 12

    def _nearest_edge(self, mx, my, area):
        x, y, w, h = area.x, area.y, area.width, area.height
        cand = []
        cand.append(('V', x + w, mx, y + h // 2) if (mx - x) > w * 0.5
                    else ('V', x, mx, y + h // 2))
        cand.append(('H', y + h, my, x + w // 2) if (my - y) > h * 0.5
                    else ('H', y, my, x + w // 2))
        cand.sort(key=lambda c: abs(c[1] - c[2]))
        return cand[0]              # (axis, edge_coord, cursor_coord, other)

    def _stop_arming(self, context):
        self._arming = False
        self._arm = None
        self._tries = 0
        if self._confirm_set:
            _clear_release_confirm(context)
            self._confirm_set = False

    def _modal_grab(self, context, event, area):
        mx, my = event.mouse_x, event.mouse_y
        reach = max(self._grab_reach, self._bp)

        if not self._arming:
            axis, edge_coord, cursor_coord, other = self._nearest_edge(mx, my, area)
            if abs(edge_coord - cursor_coord) > reach:
                return {'PASS_THROUGH'}          # keep watching
            # Lock onto this edge and begin arming.
            self._arm = (axis, edge_coord, other)
            self._arming = True
            self._tries = 0

        axis, edge_coord, other = self._arm

        # Pin the cursor onto the locked edge. This is the only warp GRAB does;
        # it also nudges active_region toward null so the poll can pass.
        warp_x, warp_y = (edge_coord, my) if axis == 'V' else (mx, edge_coord)
        if (warp_x, warp_y) != (mx, my):
            context.window.cursor_warp(warp_x, warp_y)

        if not self._confirm_set:
            self._confirm_set = _set_release_confirm(context, self._trigger)

        try:
            r = bpy.ops.screen.area_move('INVOKE_DEFAULT')
        except RuntimeError as e:
            if "poll()" not in str(e):
                self._stop_arming(context)
                self._once("native area_move error: %s" % e)
                return {'PASS_THROUGH'}
            r = {'CANCELLED'}                    # poll not ready yet -> retry

        if 'RUNNING_MODAL' in r:
            self._moves += 1
            self._arming = False                 # native owns it now
            self._arm = None
            if self._debug:
                self._once("handed off to native drag", 'INFO')
            return {'FINISHED'}                  # release binding confirms it

        # Not grabbed yet: retry for a few frames, then give up gracefully so
        # the cursor is never pinned indefinitely.
        self._tries += 1
        if self._tries >= self.MAX_GRAB_TRIES:
            self._stop_arming(context)
            if self._debug:
                self._once("gave up arming (edge never became grabbable)", 'INFO')
        return {'PASS_THROUGH'}

    # ---- PUSH: self-tracked fallback ----------------------------------
    def _apply(self, ex, ey, delta):
        try:
            r = bpy.ops.screen.area_move(x=int(ex), y=int(ey), delta=int(delta))
            if 'FINISHED' in r:
                self._moves += 1
                return True
            return False
        except RuntimeError as e:
            if "poll()" in str(e):
                return None
            self._once("area_move error: %s" % e)
            return False
        except TypeError as e:
            self._once("area_move TypeError: %s" % e)
            return False

    def _run_axis(self, ax, mouse, edge_real, other_mid, is_h, bp):
        LEAD = min(AREAGRID, bp)
        if not ax.engaged:
            if ax.sign * (mouse - edge_real) >= -max(bp, 12):
                ax.engaged = True
                ax.edge = edge_real
                ax.debt = 0.0
            else:
                return mouse
        target = mouse + ax.sign * LEAD
        want = (target - ax.edge) * ax.sign + ax.debt
        step = int(want / AREAGRID) * AREAGRID
        if step > 0:
            delta = ax.sign * step
            ex, ey = (ax.edge, other_mid) if is_h else (other_mid, ax.edge)
            res = self._apply(ex, ey, delta)
            if res is True:
                new_edge = ax.edge + delta
                new_edge -= new_edge % AREAGRID
                ax.debt = want - ax.sign * (new_edge - ax.edge)
                ax.edge = new_edge
            elif res is None:
                # Stranded: rather than warp (jitter), stop pushing this frame.
                ax.debt = 0.0
        else:
            ax.debt = 0.0
        return mouse

    def _modal_push(self, context, event, area):
        mx, my = event.mouse_x, event.mouse_y
        x, y, w, h = area.x, area.y, area.width, area.height
        if not self._x.engaged:
            self._x.sign = 1 if (mx - x) > w * 0.5 else -1
        if not self._y.engaged:
            self._y.sign = 1 if (my - y) > h * 0.5 else -1
        x_edge = (x + w) if self._x.sign > 0 else x
        y_edge = (y + h) if self._y.sign > 0 else y
        self._run_axis(self._x, mx, x_edge, y + h // 2, True, self._bp)
        self._run_axis(self._y, my, y_edge, x + w // 2, False, self._bp)
        return {'PASS_THROUGH'} if self._passthrough else {'RUNNING_MODAL'}


class _Axis:
    def __init__(self, sign):
        self.sign = sign
        self.engaged = False
        self.edge = 0
        self.debt = 0.0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (PushPanelsPrefs, SCREEN_OT_push_panels)
_keymaps = []


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Screen', space_type='EMPTY')
        kmi = km.keymap_items.new(
            SCREEN_OT_push_panels.bl_idname, DEFAULT_KEY, 'PRESS')
        _keymaps.append((km, kmi))


def unregister():
    try:
        _clear_release_confirm(bpy.context)
    except Exception:
        pass
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except RuntimeError:
            pass
    _keymaps.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
