#!/usr/bin/env python3
"""
Gamepad Mapper - standalone macOS app (engine + GUI in one file).

Double-click the built .app, or run from source:  python3 gamepad_mapper.py
Config persists at ~/.gamepad_mapper.json. Grant Accessibility when asked.
"""

import sys
import json
import time
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

CONFIG = Path.home() / ".gamepad_mapper.json"

MOD_SHIFT, MOD_CTRL, MOD_ALT, MOD_CMD = 0x20000, 0x40000, 0x80000, 0x100000
MODNAME = {"shift": MOD_SHIFT, "ctrl": MOD_CTRL, "alt": MOD_ALT, "cmd": MOD_CMD}

KEYCODES = {
    'a': 0, 'b': 11, 'c': 8, 'd': 2, 'e': 14, 'f': 3, 'g': 5, 'h': 4, 'i': 34,
    'j': 38, 'k': 40, 'l': 37, 'm': 46, 'n': 45, 'o': 31, 'p': 35, 'q': 12,
    'r': 15, 's': 1, 't': 17, 'u': 32, 'v': 9, 'w': 13, 'x': 7, 'y': 16, 'z': 6,
    '0': 29, '1': 18, '2': 19, '3': 20, '4': 21, '5': 23, '6': 22, '7': 26,
    '8': 28, '9': 25, 'space': 49, 'return': 36, 'tab': 48, 'escape': 53,
    'backspace': 51, 'forwarddelete': 117, 'up': 126, 'down': 125, 'left': 123,
    'right': 124, 'home': 115, 'end': 119, 'pageup': 116, 'pagedown': 121,
    'minus': 27, 'equals': 24, 'comma': 43, 'period': 47, 'slash': 44,
    'semicolon': 41, 'quote': 39, 'leftbracket': 33, 'rightbracket': 30,
    'backslash': 42, 'grave': 50,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96, 'f6': 97, 'f7': 98,
    'f8': 100, 'f9': 101, 'f10': 109, 'f11': 103, 'f12': 111,
}

TK_KEYMAP = {
    'space': 'space', 'Return': 'return', 'Tab': 'tab', 'Escape': 'escape',
    'BackSpace': 'backspace', 'Delete': 'forwarddelete', 'Left': 'left',
    'Right': 'right', 'Up': 'up', 'Down': 'down', 'Home': 'home', 'End': 'end',
    'Prior': 'pageup', 'Next': 'pagedown', 'minus': 'minus', 'equal': 'equals',
    'comma': 'comma', 'period': 'period', 'slash': 'slash', 'semicolon': 'semicolon',
    'apostrophe': 'quote', 'bracketleft': 'leftbracket', 'bracketright': 'rightbracket',
    'backslash': 'backslash', 'grave': 'grave',
}
for _i in range(1, 13):
    TK_KEYMAP['F%d' % _i] = 'f%d' % _i

DEFAULT_CONFIG = {
    "deadzone": 0.12, "poll_hz": 120,
    "cursor": {"enabled": True, "axis_x": 0, "axis_y": 1,
               "speed": 1100, "curve": 2.0, "invert_y": True},
    "layers": {
        "base": {"bindings": [
            {"input": {"kind": "axis", "index": 5, "sign": "pos", "threshold": 0.0},
             "on_press": [{"type": "mouse", "button": "left", "hold": True}]},
            {"input": {"kind": "axis", "index": 4, "sign": "pos", "threshold": 0.0},
             "on_press": [{"type": "mouse", "button": "right"}]},
            {"input": {"kind": "button", "index": 4},
             "on_press": [{"type": "enter_layer", "layer": "alt", "mode": "momentary"},
                          {"type": "modifier", "mod": "shift"}]},
        ]},
        "alt": {"bindings": []},
    }
}


# ----------------------------------------------------------------------------
# OS output (Quartz) + helpers
# ----------------------------------------------------------------------------
def check_permission(Quartz):
    try:
        from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                         kAXTrustedCheckOptionPrompt)
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        return None


class Output:
    def __init__(self, Quartz):
        self.Q = Quartz
        b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        self.sw, self.sh = b.size.width, b.size.height
        self.held_mouse = None

    def key(self, name, flags, down):
        kc = KEYCODES.get(name.strip().lower())
        if kc is None:
            return
        ev = self.Q.CGEventCreateKeyboardEvent(None, kc, down)
        if flags:
            self.Q.CGEventSetFlags(ev, flags)
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)

    def key_tap(self, name, flags):
        self.key(name, flags, True)
        self.key(name, flags, False)

    def mouse(self, button, down, flags):
        loc = self.Q.CGEventGetLocation(self.Q.CGEventCreate(None))
        t = {"left": (self.Q.kCGEventLeftMouseDown, self.Q.kCGEventLeftMouseUp, self.Q.kCGMouseButtonLeft),
             "right": (self.Q.kCGEventRightMouseDown, self.Q.kCGEventRightMouseUp, self.Q.kCGMouseButtonRight),
             "middle": (self.Q.kCGEventOtherMouseDown, self.Q.kCGEventOtherMouseUp, self.Q.kCGMouseButtonCenter)}[button]
        ev = self.Q.CGEventCreateMouseEvent(None, t[0] if down else t[1], loc, t[2])
        if flags:
            self.Q.CGEventSetFlags(ev, flags)
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)

    def mouse_tap(self, button, flags):
        self.mouse(button, True, flags)
        self.mouse(button, False, flags)

    def scroll(self, amount):
        ev = self.Q.CGEventCreateScrollWheelEvent(None, self.Q.kCGScrollEventUnitLine, 1, int(amount))
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)

    def move_cursor(self, dx, dy):
        loc = self.Q.CGEventGetLocation(self.Q.CGEventCreate(None))
        x = min(max(loc.x + dx, 0), self.sw - 1)
        y = min(max(loc.y + dy, 0), self.sh - 1)
        self.Q.CGWarpMouseCursorPosition(self.Q.CGPointMake(x, y))
        if self.held_mouse:
            t = {"left": (self.Q.kCGEventLeftMouseDragged, self.Q.kCGMouseButtonLeft),
                 "right": (self.Q.kCGEventRightMouseDragged, self.Q.kCGMouseButtonRight),
                 "middle": (self.Q.kCGEventOtherMouseDragged, self.Q.kCGMouseButtonCenter)}[self.held_mouse]
            ev = self.Q.CGEventCreateMouseEvent(None, t[0], self.Q.CGPointMake(x, y), t[1])
            self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)


def dz(v, dead):
    if abs(v) < dead:
        return 0.0
    s = (abs(v) - dead) / (1.0 - dead)
    return s if v > 0 else -s


def curve(v, c):
    return (1.0 if v >= 0 else -1.0) * (abs(v) ** c)


def sig(inp):
    if inp["kind"] == "axis":
        return ("axis", inp["index"], inp.get("sign", "pos"))
    if inp["kind"] == "hat":
        return ("hat", inp["index"], tuple(inp.get("dir", [0, 0])))
    return ("button", inp["index"], None)


def input_label(inp):
    if inp["kind"] == "axis":
        return "axis %d%s" % (inp["index"], "+" if inp.get("sign", "pos") == "pos" else "-")
    if inp["kind"] == "hat":
        return "dpad %s" % (tuple(inp.get("dir", [0, 0])),)
    return "button %d" % inp["index"]


def action_label(a):
    t = a["type"]
    if t == "key":
        m = "".join(x + "+" for x in a.get("mods", []))
        return "key %s%s%s" % (m, a.get("key", "?"), " (hold)" if a.get("hold") else "")
    if t == "mouse":
        return "%s click%s" % (a.get("button", "left"), " (hold)" if a.get("hold") else "")
    if t == "scroll":
        return "scroll %d" % a.get("amount", 1)
    if t == "modifier":
        return "hold %s" % a.get("mod", "shift")
    if t == "enter_layer":
        return "enter '%s' (%s)" % (a.get("layer", "?"), a.get("mode", "momentary"))
    if t == "exit_layer":
        return "exit layer"
    return t


# ----------------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------------
class Engine:
    def __init__(self, cfg, js, out):
        self.cfg, self.js, self.out = cfg, js, out
        self.stack = ["base"]
        self.prev = {}
        self.reverts = {}
        self.mods_map = {}
        self.rebuild_specs()

    def rebuild_specs(self):
        self.specs = {}
        for layer in self.cfg["layers"].values():
            for b in layer["bindings"]:
                self.specs[sig(b["input"])] = b["input"]

    def cur_mods(self):
        f = 0
        for v in self.mods_map.values():
            f |= v
        return f

    def pressed(self, inp):
        try:
            if inp["kind"] == "button":
                return self.js.get_button(inp["index"]) == 1
            if inp["kind"] == "axis":
                v = self.js.get_axis(inp["index"])
                th = inp.get("threshold", 0.5)
                return v > th if inp.get("sign", "pos") == "pos" else v < -th
            if inp["kind"] == "hat":
                return tuple(self.js.get_hat(inp["index"])) == tuple(inp.get("dir", [0, 0]))
        except Exception:
            return False
        return False

    def resolve(self, s):
        for layer in reversed(self.stack):
            for b in self.cfg["layers"].get(layer, {}).get("bindings", []):
                if sig(b["input"]) == s:
                    return b
        return None

    def do_action(self, a, s):
        t = a["type"]
        flags = self.cur_mods()
        for m in a.get("mods", []):
            flags |= MODNAME.get(m, 0)
        if t == "key":
            if a.get("hold"):
                self.out.key(a["key"], flags, True)
                return lambda: self.out.key(a["key"], flags, False)
            self.out.key_tap(a["key"], flags)
        elif t == "mouse":
            btn = a.get("button", "left")
            if a.get("hold"):
                self.out.mouse(btn, True, flags)
                self.out.held_mouse = btn
                return lambda: (self.out.mouse(btn, False, flags),
                                setattr(self.out, "held_mouse", None))
            self.out.mouse_tap(btn, flags)
        elif t == "scroll":
            self.out.scroll(a.get("amount", 1))
        elif t == "modifier":
            self.mods_map[s] = MODNAME.get(a.get("mod", "shift"), 0)
            return lambda: self.mods_map.pop(s, None)
        elif t == "enter_layer":
            name, mode = a["layer"], a.get("mode", "momentary")
            if mode == "toggle":
                (self.stack.remove(name) if name in self.stack else self.stack.append(name))
            else:
                self.stack.append(name)
                if mode == "momentary":
                    return lambda: (name in self.stack) and self.stack.remove(name)
        elif t == "exit_layer":
            name = a.get("layer")
            if name and name in self.stack:
                self.stack.remove(name)
            elif len(self.stack) > 1:
                self.stack.pop()
        return None

    def tick(self, dt):
        c = self.cfg.get("cursor", {})
        if c.get("enabled"):
            try:
                ax = dz(self.js.get_axis(c["axis_x"]), self.cfg["deadzone"])
                ay = dz(self.js.get_axis(c["axis_y"]), self.cfg["deadzone"])
                if ax or ay:
                    spd = c["speed"] * dt
                    ey = -ay if c.get("invert_y") else ay
                    self.out.move_cursor(curve(ax, c["curve"]) * spd, curve(ey, c["curve"]) * spd)
            except Exception:
                pass
        for s, inp in list(self.specs.items()):
            now = self.pressed(inp)
            was = self.prev.get(s, False)
            if now and not was:
                b = self.resolve(s)
                if b:
                    revs = []
                    for a in b.get("on_press", []):
                        r = self.do_action(a, s)
                        if r:
                            revs.append(r)
                    if revs:
                        self.reverts[s] = revs
            elif was and not now:
                for r in reversed(self.reverts.pop(s, [])):
                    try:
                        r()
                    except Exception:
                        pass
            self.prev[s] = now


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
ACTION_TYPES = ["key", "mouse", "scroll", "modifier", "enter_layer", "exit_layer"]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Gamepad Mapper")
        self.cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else json.loads(json.dumps(DEFAULT_CONFIG))
        self.pg = self.Q = self.js = self.out = self.eng = None
        self.running = False
        self.last = time.perf_counter()
        self.learn_input = None      # (layer, idx) awaiting controller press
        self.learn_base = None
        self._build()
        self.refresh_layers()
        self.root.after(8, self.poll)

    # --- layout ---
    def _build(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        self.start_btn = ttk.Button(top, text="Start", command=self.toggle_run)
        self.start_btn.pack(side="left")
        ttk.Button(top, text="Save", command=self.save).pack(side="left", padx=4)
        ttk.Button(top, text="Grant Accessibility", command=self.grant).pack(side="left")
        ttk.Button(top, text="Install deps", command=self.install).pack(side="left", padx=4)
        self.status = ttk.Label(top, text="stopped")
        self.status.pack(side="left", padx=8)

        body = ttk.Frame(self.root, padding=6)
        body.pack(fill="both", expand=True)

        # layers
        lf = ttk.LabelFrame(body, text="Layers", padding=4)
        lf.grid(row=0, column=0, sticky="nsew", padx=3)
        self.layer_list = tk.Listbox(lf, width=16, height=14, exportselection=False)
        self.layer_list.pack(fill="both", expand=True)
        self.layer_list.bind("<<ListboxSelect>>", lambda e: self.refresh_bindings())
        lb = ttk.Frame(lf); lb.pack(fill="x")
        ttk.Button(lb, text="+", width=3, command=self.add_layer).pack(side="left")
        ttk.Button(lb, text="-", width=3, command=self.del_layer).pack(side="left")
        ttk.Button(lb, text="ren", width=4, command=self.ren_layer).pack(side="left")

        # bindings
        bf = ttk.LabelFrame(body, text="Bindings (selected layer)", padding=4)
        bf.grid(row=0, column=1, sticky="nsew", padx=3)
        self.bind_list = tk.Listbox(bf, width=28, height=14, exportselection=False)
        self.bind_list.pack(fill="both", expand=True)
        self.bind_list.bind("<<ListboxSelect>>", lambda e: self.refresh_actions())
        bb = ttk.Frame(bf); bb.pack(fill="x")
        ttk.Button(bb, text="+", width=3, command=self.add_binding).pack(side="left")
        ttk.Button(bb, text="-", width=3, command=self.del_binding).pack(side="left")
        ttk.Button(bb, text="Learn input", command=self.start_learn_input).pack(side="left", padx=4)

        # actions
        af = ttk.LabelFrame(body, text="Actions (stack, run on press)", padding=4)
        af.grid(row=0, column=2, sticky="nsew", padx=3)
        self.act_list = tk.Listbox(af, width=28, height=8, exportselection=False)
        self.act_list.pack(fill="both", expand=True)
        self.act_list.bind("<<ListboxSelect>>", lambda e: self.refresh_action_fields())
        ab = ttk.Frame(af); ab.pack(fill="x")
        self.new_type = tk.StringVar(value="key")
        ttk.OptionMenu(ab, self.new_type, "key", *ACTION_TYPES).pack(side="left")
        ttk.Button(ab, text="+", width=3, command=self.add_action).pack(side="left")
        ttk.Button(ab, text="-", width=3, command=self.del_action).pack(side="left")
        self.fields = ttk.Frame(af, padding=4)
        self.fields.pack(fill="x")

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.columnconfigure(2, weight=2)
        body.rowconfigure(0, weight=1)

    # --- helpers to get current selection ---
    def cur_layer(self):
        s = self.layer_list.curselection()
        return self.layer_list.get(s[0]) if s else None

    def cur_binding(self):
        ly = self.cur_layer()
        s = self.bind_list.curselection()
        if ly and s:
            return self.cfg["layers"][ly]["bindings"][s[0]]
        return None

    def cur_action(self):
        b = self.cur_binding()
        s = self.act_list.curselection()
        if b and s:
            return b["on_press"][s[0]]
        return None

    # --- refreshers ---
    def refresh_layers(self):
        self.layer_list.delete(0, "end")
        for name in self.cfg["layers"]:
            self.layer_list.insert("end", name)
        if self.cfg["layers"]:
            self.layer_list.selection_set(0)
        self.refresh_bindings()

    def refresh_bindings(self):
        self.bind_list.delete(0, "end")
        ly = self.cur_layer()
        if ly:
            for b in self.cfg["layers"][ly]["bindings"]:
                acts = " + ".join(action_label(a) for a in b.get("on_press", [])) or "(empty)"
                self.bind_list.insert("end", "%s -> %s" % (input_label(b["input"]), acts))
        self.refresh_actions()

    def refresh_actions(self):
        self.act_list.delete(0, "end")
        b = self.cur_binding()
        if b:
            for a in b.get("on_press", []):
                self.act_list.insert("end", action_label(a))
        self.refresh_action_fields()

    def refresh_action_fields(self):
        for w in self.fields.winfo_children():
            w.destroy()
        a = self.cur_action()
        if not a:
            return
        t = a["type"]

        def row(lbl):
            r = ttk.Frame(self.fields); r.pack(fill="x", pady=1)
            ttk.Label(r, text=lbl, width=8).pack(side="left")
            return r

        if t == "key":
            r = row("key")
            kv = tk.StringVar(value=a.get("key", ""))
            e = ttk.Entry(r, textvariable=kv, width=10); e.pack(side="left")
            kv.trace_add("write", lambda *_: self._set(a, "key", kv.get()))
            for m in ("cmd", "shift", "ctrl", "alt"):
                v = tk.BooleanVar(value=m in a.get("mods", []))
                ttk.Checkbutton(r, text=m, variable=v,
                                command=lambda m=m, v=v: self._set_mod(a, m, v.get())).pack(side="left")
            self._hold_chk(a)
            ttk.Button(self.fields, text="Learn output", command=self.learn_output).pack(fill="x")
        elif t == "mouse":
            r = row("button")
            bv = tk.StringVar(value=a.get("button", "left"))
            ttk.OptionMenu(r, bv, a.get("button", "left"), "left", "right", "middle",
                           command=lambda val: self._set(a, "button", val)).pack(side="left")
            self._hold_chk(a)
            ttk.Button(self.fields, text="Learn output", command=self.learn_output).pack(fill="x")
        elif t == "scroll":
            r = row("amount")
            sv = tk.IntVar(value=a.get("amount", 1))
            ttk.Spinbox(r, from_=-10, to=10, textvariable=sv, width=5,
                        command=lambda: self._set(a, "amount", sv.get())).pack(side="left")
        elif t == "modifier":
            r = row("modifier")
            mv = tk.StringVar(value=a.get("mod", "shift"))
            ttk.OptionMenu(r, mv, a.get("mod", "shift"), "shift", "ctrl", "alt", "cmd",
                           command=lambda val: self._set(a, "mod", val)).pack(side="left")
        elif t == "enter_layer":
            r = row("layer")
            lv = tk.StringVar(value=a.get("layer", ""))
            ttk.OptionMenu(r, lv, a.get("layer", ""), *self.cfg["layers"].keys(),
                           command=lambda val: self._set(a, "layer", val)).pack(side="left")
            r2 = row("mode")
            mo = tk.StringVar(value=a.get("mode", "momentary"))
            ttk.OptionMenu(r2, mo, a.get("mode", "momentary"), "momentary", "latched", "toggle",
                           command=lambda val: self._set(a, "mode", val)).pack(side="left")

    def _hold_chk(self, a):
        v = tk.BooleanVar(value=a.get("hold", False))
        ttk.Checkbutton(self.fields, text="hold (vs tap)", variable=v,
                        command=lambda: self._set(a, "hold", v.get())).pack(anchor="w")

    def _set(self, a, k, val):
        a[k] = val
        self.refresh_actions_keep()

    def _set_mod(self, a, m, on):
        mods = set(a.get("mods", []))
        mods.add(m) if on else mods.discard(m)
        a["mods"] = sorted(mods)
        self.refresh_actions_keep()

    def refresh_actions_keep(self):
        sel = self.act_list.curselection()
        self.refresh_bindings()
        if sel:
            try:
                self.act_list.selection_set(sel[0])
            except Exception:
                pass

    # --- structural edits ---
    def add_layer(self):
        name = simpledialog.askstring("New layer", "Layer name:")
        if name and name not in self.cfg["layers"]:
            self.cfg["layers"][name] = {"bindings": []}
            self.refresh_layers()

    def del_layer(self):
        ly = self.cur_layer()
        if ly and ly != "base":
            del self.cfg["layers"][ly]
            self.refresh_layers()
        elif ly == "base":
            messagebox.showinfo("Gamepad Mapper", "Can't delete the base layer.")

    def ren_layer(self):
        ly = self.cur_layer()
        if not ly or ly == "base":
            return
        name = simpledialog.askstring("Rename", "New name:", initialvalue=ly)
        if name and name not in self.cfg["layers"]:
            self.cfg["layers"][name] = self.cfg["layers"].pop(ly)
            self.refresh_layers()

    def add_binding(self):
        ly = self.cur_layer()
        if ly:
            self.cfg["layers"][ly]["bindings"].append(
                {"input": {"kind": "button", "index": 0}, "on_press": []})
            self.refresh_bindings()
            self._rebuild_engine()

    def del_binding(self):
        ly, s = self.cur_layer(), self.bind_list.curselection()
        if ly and s:
            del self.cfg["layers"][ly]["bindings"][s[0]]
            self.refresh_bindings()
            self._rebuild_engine()

    def add_action(self):
        b = self.cur_binding()
        if b is None:
            return
        t = self.new_type.get()
        a = {"type": t}
        if t == "key":
            a.update({"key": "g", "mods": [], "hold": False})
        elif t == "mouse":
            a.update({"button": "left", "hold": False})
        elif t == "scroll":
            a.update({"amount": 1})
        elif t == "modifier":
            a.update({"mod": "shift"})
        elif t == "enter_layer":
            a.update({"layer": next(iter(self.cfg["layers"])), "mode": "momentary"})
        b["on_press"].append(a)
        self.refresh_actions()

    def del_action(self):
        b, s = self.cur_binding(), self.act_list.curselection()
        if b and s:
            del b["on_press"][s[0]]
            self.refresh_actions()

    # --- learn ---
    def start_learn_input(self):
        if not self.running:
            messagebox.showinfo("Gamepad Mapper", "Press Start first so the controller is read.")
            return
        b = self.cur_binding()
        if b is None:
            return
        try:
            self.learn_base = [self.js.get_axis(i) for i in range(self.js.get_numaxes())]
        except Exception:
            self.learn_base = []
        self.learn_input = b
        self.status.config(text="LEARN: press a control...")

    def learn_output(self):
        a = self.cur_action()
        if a is None:
            return
        top = tk.Toplevel(self.root)
        top.title("Press a key combo or click")
        ttk.Label(top, text="Press a key (with modifiers) or click a mouse button.\nEsc cancels.",
                  padding=16).pack()
        top.grab_set()
        top.focus_force()

        def finish_key(ev):
            if ev.keysym == "Escape":
                top.destroy(); return
            name = TK_KEYMAP.get(ev.keysym) or (ev.keysym.lower() if len(ev.keysym) == 1 else None)
            if not name:
                return
            mods = []
            if ev.state & 0x1:
                mods.append("shift")
            if ev.state & 0x4:
                mods.append("ctrl")
            if ev.state & 0x8 or ev.state & 0x40000:
                mods.append("cmd")
            if ev.state & 0x10:
                mods.append("alt")
            a["type"] = "key"; a["key"] = name; a["mods"] = mods
            top.destroy(); self.refresh_actions_keep()

        def finish_btn(ev):
            a["type"] = "mouse"
            a["button"] = {1: "left", 2: "middle", 3: "right"}.get(ev.num, "left")
            top.destroy(); self.refresh_actions_keep()

        top.bind("<Key>", finish_key)
        top.bind("<Button>", finish_btn)

    # --- run loop ---
    def install(self):
        self.status.config(text="installing deps...")
        self.root.update()
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "pygame",
                        "pyobjc-framework-Quartz", "pyobjc-framework-ApplicationServices"])
        self.status.config(text="deps installed (restart if needed)")

    def grant(self):
        try:
            import Quartz
            check_permission(Quartz)
            self.status.config(text="check System Settings > Privacy > Accessibility")
        except Exception:
            self.status.config(text="install deps first")

    def toggle_run(self):
        if self.running:
            if self.eng:
                for s in list(self.eng.reverts):
                    for r in reversed(self.eng.reverts.pop(s, [])):
                        try:
                            r()
                        except Exception:
                            pass
            self.running = False
            self.start_btn.config(text="Start")
            self.status.config(text="stopped")
            return
        try:
            import pygame
            import Quartz
        except Exception:
            self.status.config(text="click 'Install deps' first")
            return
        self.pg, self.Q = pygame, Quartz
        check_permission(Quartz)
        pygame.init(); pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            self.status.config(text="no controller detected")
            return
        self.js = pygame.joystick.Joystick(0); self.js.init()
        self.out = Output(Quartz)
        self.eng = Engine(self.cfg, self.js, self.out)
        self.running = True
        self.last = time.perf_counter()
        self.start_btn.config(text="Stop")

    def _rebuild_engine(self):
        if self.eng:
            self.eng.rebuild_specs()

    def poll(self):
        if self.running and self.js is not None:
            self.pg.event.pump()
            if self.learn_input is not None:
                self._try_learn()
            else:
                now = time.perf_counter()
                self.eng.tick(min(now - self.last, 0.1))
                self.last = now
                self.status.config(text="running | layers: %s" % " > ".join(self.eng.stack))
        self.root.after(8, self.poll)

    def _try_learn(self):
        js, b = self.js, self.learn_input
        for i in range(js.get_numbuttons()):
            if js.get_button(i):
                b["input"] = {"kind": "button", "index": i}
                return self._end_learn()
        for i in range(js.get_numhats()):
            h = js.get_hat(i)
            if h != (0, 0):
                b["input"] = {"kind": "hat", "index": i, "dir": list(h)}
                return self._end_learn()
        for i in range(js.get_numaxes()):
            base = self.learn_base[i] if i < len(self.learn_base) else 0.0
            d = js.get_axis(i) - base
            if abs(d) > 0.5:
                b["input"] = {"kind": "axis", "index": i,
                              "sign": "pos" if d > 0 else "neg", "threshold": 0.0}
                return self._end_learn()

    def _end_learn(self):
        self.learn_input = None
        self._rebuild_engine()
        self.refresh_bindings()
        self.status.config(text="input learned")

    def save(self):
        try:
            CONFIG.write_text(json.dumps(self.cfg, indent=2))
            self.status.config(text="saved to %s" % CONFIG)
        except Exception as e:
            self.status.config(text="save failed: %s" % e)


def main():
    root = tk.Tk()
    App(root)
    root.geometry("900x420")
    root.mainloop()


if __name__ == "__main__":
    main()
