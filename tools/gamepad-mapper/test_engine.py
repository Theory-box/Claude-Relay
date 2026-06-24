#!/usr/bin/env python3
"""Headless tests for the mapper engine (no pygame/Quartz/display needed)."""
import gamepad_mapper as gm


class FakeJoy:
    def __init__(self, nb, na, nh=0):
        self.b = [0] * nb
        self.a = [0.0] * na
        self.h = [(0, 0)] * nh

    def get_numbuttons(self):
        return len(self.b)

    def get_numaxes(self):
        return len(self.a)

    def get_numhats(self):
        return len(self.h)

    def get_button(self, i):
        return self.b[i]

    def get_axis(self, i):
        return self.a[i]

    def get_hat(self, i):
        return self.h[i]


class FakeOut:
    def __init__(self):
        self.events = []
        self.held_mouse = None

    def key(self, name, flags, down):
        self.events.append(("key", name, flags, down))

    def key_tap(self, name, flags):
        self.events.append(("keytap", name, flags))

    def mouse(self, btn, down, flags):
        self.events.append(("mouse", btn, down, flags))

    def mouse_tap(self, btn, flags):
        self.events.append(("mousetap", btn, flags))

    def scroll(self, amt):
        self.events.append(("scroll", amt))

    def move_cursor(self, dx, dy):
        pass


CFG = {
    "deadzone": 0.12,
    "cursor": {"enabled": False, "axis_x": 0, "axis_y": 1, "speed": 0, "curve": 2.0},
    "layers": {
        "base": {"bindings": [
            {"input": {"kind": "button", "index": 4},
             "on_press": [{"type": "modifier", "mod": "shift"}]},
            {"input": {"kind": "axis", "index": 5, "sign": "pos", "threshold": 0.0},
             "on_press": [{"type": "mouse", "button": "left"}]},
            {"input": {"kind": "button", "index": 0},
             "on_press": [{"type": "enter_layer", "layer": "alt", "mode": "momentary"}]},
            {"input": {"kind": "button", "index": 1},
             "on_press": [{"type": "key", "key": "g"},
                          {"type": "enter_layer", "layer": "grab", "mode": "latched"}]},
        ]},
        "alt": {"bindings": [
            {"input": {"kind": "button", "index": 2}, "on_press": [{"type": "key", "key": "x"}]},
        ]},
        "grab": {"bindings": [
            {"input": {"kind": "axis", "index": 5, "sign": "pos", "threshold": 0.0},
             "on_press": [{"type": "mouse", "button": "left"}, {"type": "exit_layer"}]},
        ]},
    },
}

results = []


def check(name, cond):
    results.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name)


def fresh():
    js = FakeJoy(nb=8, na=6)
    out = FakeOut()
    eng = gm.Engine(__import__("json").loads(__import__("json").dumps(CFG)), js, out)
    return js, out, eng


# 1. shift-click: hold button4 (shift modifier), then squeeze RT (axis5)
js, out, eng = fresh()
js.b[4] = 1
eng.tick(0.01)                      # modifier down
js.a[5] = 1.0
eng.tick(0.01)                      # RT click while shift held
clicks = [e for e in out.events if e[0] == "mousetap"]
check("shift-click fires a mouse tap", len(clicks) == 1)
check("click carries the Shift flag", bool(clicks and clicks[0][2] & gm.MOD_SHIFT))

# 2. modifier reverts on release
js.b[4] = 0
eng.tick(0.01)
check("shift cleared after release", eng.cur_mods() == 0)

# 3. momentary layer: button0 enters alt; button2 -> x only while held
js, out, eng = fresh()
js.b[0] = 1
eng.tick(0.01)
check("momentary layer pushed", eng.stack == ["base", "alt"])
js.b[2] = 1
eng.tick(0.01)
check("alt binding fires x", ("keytap", "x", 0) in out.events)
js.b[0] = 0
js.b[2] = 0
eng.tick(0.01)
check("momentary layer popped on release", eng.stack == ["base"])

# 4. latched layer + exit_layer: button1 -> g + latch grab; RT -> click + exit
js, out, eng = fresh()
js.b[1] = 1
eng.tick(0.01)
check("latched layer pushed", eng.stack == ["base", "grab"])
check("latch binding also typed g", ("keytap", "g", 0) in out.events)
js.b[1] = 0
eng.tick(0.01)
check("latched layer persists after release", eng.stack == ["base", "grab"])
js.a[5] = 1.0
eng.tick(0.01)
check("exit_layer left grab", eng.stack == ["base"])

# 5. resolution precedence: same input in two layers picks the top layer
js, out, eng = fresh()
js.b[0] = 1            # enter alt (momentary)
eng.tick(0.01)
js.a[5] = 1.0          # axis5 exists in base only -> base click still resolves
eng.tick(0.01)
check("axis5 resolves while in alt", any(e[0] == "mousetap" for e in out.events))

ok = all(c for _, c in results)
print("\n%d/%d passed" % (sum(1 for _, c in results if c), len(results)))
raise SystemExit(0 if ok else 1)
