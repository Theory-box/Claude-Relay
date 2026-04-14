#!/usr/bin/env python3
"""
SpaceMouse → OpenGOAL  |  Desktop App
Just double-click this file to run.
Requires Python 3.8+ (tkinter is built in).
"""

import json, math, os, subprocess, sys, threading, time, importlib

# ── Windows: re-launch inside a console window if opened by double-click ──────
# Without this, double-clicking a .py silently crashes with no visible error.
if sys.platform == "win32" and "SPACEMOUSE_LAUNCHED" not in os.environ:
    import ctypes
    env = os.environ.copy()
    env["SPACEMOUSE_LAUNCHED"] = "1"
    subprocess.Popen(
        ["cmd", "/c", "python", os.path.abspath(__file__), "&", "pause"],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env,
    )
    sys.exit()
# ──────────────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

APP_DIR   = os.path.dirname(os.path.abspath(__file__))
CFG_FILE  = os.path.join(APP_DIR, "jak_spacemouse_settings.json")
WIN_W, WIN_H = 520, 640

DEFAULTS = {
    "deadzone":        0.08,
    "sensitivity":     1.0,
    "curve_exponent":  1.4,
    "invert_x":        False,
    "invert_y":        True,
    "poll_hz":         60,
    "button_0_mapping": "X",
    "button_1_mapping": "B",
}

BUTTON_CHOICES = ["A","B","X","Y","LB","RB","START","BACK","LS","RS","none"]

COLORS = {
    "bg":         "#0f0f12",
    "surface":    "#1a1a20",
    "surface2":   "#22222a",
    "border":     "#2e2e3a",
    "accent":     "#6c63ff",
    "accent_dim": "#3d3880",
    "green":      "#3ddc84",
    "red":        "#ff4f4f",
    "amber":      "#ffb347",
    "text":       "#e8e8f0",
    "muted":      "#7878a0",
    "white":      "#ffffff",
}

REQUIRED = ["pyspacemouse", "vgamepad"]

# ─── helpers ──────────────────────────────────────────────────────────────────

def load_cfg():
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE) as f:
                d = json.load(f)
            out = dict(DEFAULTS); out.update(d); return out
        except Exception:
            pass
    return dict(DEFAULTS)

def save_cfg(d):
    with open(CFG_FILE, "w") as f:
        json.dump(d, f, indent=2)

def pkg_ok(name):
    try:
        importlib.import_module(name.split("[")[0])
        return True
    except ImportError:
        return False

def install_pkgs(callback):
    def run():
        for pkg in REQUIRED:
            callback(f"Installing {pkg}…")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg],
                capture_output=True, text=True
            )
            if r.returncode != 0:
                callback(f"ERROR: {pkg}\n{r.stderr[:300]}", error=True)
                return
        callback("All packages installed!", done=True)
    threading.Thread(target=run, daemon=True).start()

# ─── signal chain (same as CLI script) ───────────────────────────────────────

def apply_deadzone(v, dz):
    if abs(v) < dz: return 0.0
    s = 1.0 if v > 0 else -1.0
    return s * min((abs(v) - dz) / (1.0 - dz), 1.0)

def apply_curve(v, exp):
    if v == 0.0: return 0.0
    s = 1.0 if v > 0 else -1.0
    return s * (abs(v) ** exp)

def process_axis(raw, cfg, invert_key):
    v = apply_deadzone(raw, cfg["deadzone"])
    v = apply_curve(v, cfg["curve_exponent"])
    v = v * cfg["sensitivity"]
    if cfg[invert_key]: v = -v
    return max(-1.0, min(1.0, v))

# ─── bridge thread ────────────────────────────────────────────────────────────

class Bridge:
    def __init__(self, cfg, on_state, on_error):
        self.cfg      = cfg
        self.on_state = on_state   # called with (x, y, btn0, btn1) every frame
        self.on_error = on_error
        self._stop    = threading.Event()
        self._thread  = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def update_cfg(self, cfg):
        self.cfg = cfg

    def _run(self):
        try:
            import pyspacemouse, vgamepad as vg
        except ImportError as e:
            self.on_error(f"Import error: {e}")
            return

        BMAP = {
            "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            "LS": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
            "RS": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
        }

        try:
            dev = pyspacemouse.open()
            if not dev:
                self.on_error("SpaceMouse not found — is it plugged in?")
                return
        except Exception as e:
            self.on_error(f"SpaceMouse error: {e}")
            return

        try:
            pad = vg.VX360Gamepad()
            pad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A); pad.update()
            time.sleep(0.05)
            pad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A); pad.update()
        except Exception as e:
            dev.close()
            self.on_error(f"Virtual gamepad error: {e}\nMake sure ViGEmBus driver is installed.")
            return

        prev_btns = [0, 0]
        while not self._stop.is_set():
            t0 = time.perf_counter()
            cfg = self.cfg

            state = dev.read()
            if state is None:
                time.sleep(0.016); continue

            x = process_axis(state.x, cfg, "invert_x")
            y = process_axis(state.y, cfg, "invert_y")
            pad.left_joystick_float(x_value_float=x, y_value_float=y)

            btns = list(state.buttons[:2]) if len(state.buttons) >= 2 else [0,0]
            for i, mk in enumerate(["button_0_mapping","button_1_mapping"]):
                m = cfg[mk]
                if not m or m == "none" or m not in BMAP: continue
                b = BMAP[m]
                if btns[i] and not prev_btns[i]:   pad.press_button(b)
                elif not btns[i] and prev_btns[i]: pad.release_button(b)
            prev_btns = btns

            pad.update()
            self.on_state(x, y, btns[0], btns[1])

            sleep = (1.0 / cfg["poll_hz"]) - (time.perf_counter() - t0)
            if sleep > 0: time.sleep(sleep)

        pad.left_joystick_float(0.0, 0.0); pad.update()
        dev.close()

# ─── GUI ──────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SpaceMouse → Jak & Daxter")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.cfg     = load_cfg()
        self.bridge  = None
        self.running = False

        self._build_ui()
        self._refresh_pkg_status()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        C = COLORS

        # Header
        hdr = tk.Frame(self, bg=C["surface"], pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="SpaceMouse  →  OpenGOAL",
                 bg=C["surface"], fg=C["white"],
                 font=("Segoe UI", 15, "bold")).pack()
        tk.Label(hdr, text="Jak & Daxter movement bridge",
                 bg=C["surface"], fg=C["muted"],
                 font=("Segoe UI", 10)).pack()

        # Scrollable body
        canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        scroll = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=C["bg"])
        body_id = canvas.create_window((0,0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(body_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        pad = {"padx": 18, "pady": 0}

        # ── packages section ──────────────────────────────────────────────────
        self._section(body, "1  Packages")
        pkg_frame = tk.Frame(body, bg=C["bg"])
        pkg_frame.pack(fill="x", **pad, pady=(0, 6))

        self.pkg_labels = {}
        for pkg in REQUIRED:
            row = tk.Frame(pkg_frame, bg=C["bg"])
            row.pack(fill="x", pady=3)
            dot = tk.Label(row, text="●", bg=C["bg"], fg=C["muted"],
                           font=("Segoe UI", 11))
            dot.pack(side="left")
            tk.Label(row, text=f"  {pkg}", bg=C["bg"], fg=C["text"],
                     font=("Segoe UI", 11)).pack(side="left")
            self.pkg_labels[pkg] = dot

        self.install_btn = self._btn(body, "Install all packages",
                                     self._do_install, accent=True)
        self.install_btn.pack(fill="x", **pad, pady=(4,0))

        self.install_status = tk.Label(body, text="", bg=C["bg"],
                                       fg=C["muted"], font=("Segoe UI", 10),
                                       wraplength=WIN_W-40, justify="left")
        self.install_status.pack(fill="x", **pad, pady=(4, 0))

        # ── settings section ──────────────────────────────────────────────────
        self._section(body, "2  Settings")

        self._slider(body, "Dead zone",
                     "Raise if Jak drifts at rest (0.05 – 0.30)",
                     "deadzone", 0.05, 0.30, 0.01)
        self._slider(body, "Sensitivity",
                     "Overall speed multiplier (0.3 – 2.0)",
                     "sensitivity", 0.3, 2.0, 0.05)
        self._slider(body, "Curve",
                     "1.0 = linear · 2.0 = precise centre · 0.8 = aggressive",
                     "curve_exponent", 0.5, 2.5, 0.05)
        self._slider(body, "Poll rate",
                     "Updates per second sent to game (30 – 120)",
                     "poll_hz", 30, 120, 1, is_int=True)

        self._toggle(body, "Invert X (left/right)", "invert_x")
        self._toggle(body, "Invert Y (forward/back)", "invert_y")

        self._dropdown(body, "Left button →", "button_0_mapping")
        self._dropdown(body, "Right button →", "button_1_mapping")

        save_row = tk.Frame(body, bg=C["bg"])
        save_row.pack(fill="x", padx=18, pady=(10,0))
        self._btn(save_row, "Save settings", self._save_settings).pack(
            side="left", padx=(0,8))
        self._btn(save_row, "Reset to defaults", self._reset_settings).pack(
            side="left")

        # ── run section ───────────────────────────────────────────────────────
        self._section(body, "3  Run")

        self.run_btn = self._btn(body, "▶  Start bridge",
                                 self._toggle_bridge, accent=True)
        self.run_btn.pack(fill="x", **pad, pady=(0,8))

        status_frame = tk.Frame(body, bg=C["surface"], bd=0)
        status_frame.pack(fill="x", **pad, pady=(0,4))

        self.status_dot = tk.Label(status_frame, text="●",
                                   bg=C["surface"], fg=C["muted"],
                                   font=("Segoe UI", 12))
        self.status_dot.pack(side="left", padx=(10,4), pady=8)
        self.status_lbl = tk.Label(status_frame, text="Stopped",
                                   bg=C["surface"], fg=C["muted"],
                                   font=("Segoe UI", 11))
        self.status_lbl.pack(side="left", pady=8)

        # Live axis display
        axis_frame = tk.Frame(body, bg=C["surface"])
        axis_frame.pack(fill="x", **pad, pady=(0, 4))
        axis_frame.columnconfigure(1, weight=1)

        for i, lbl in enumerate(["X axis", "Y axis"]):
            tk.Label(axis_frame, text=lbl, bg=C["surface"], fg=C["muted"],
                     font=("Segoe UI", 10), width=8, anchor="w").grid(
                row=i, column=0, padx=(10,6), pady=5, sticky="w")
            bar_bg = tk.Frame(axis_frame, bg=C["surface2"], height=10)
            bar_bg.grid(row=i, column=1, sticky="ew", padx=(0,6), pady=5)
            bar = tk.Frame(bar_bg, bg=C["muted"], height=10)
            bar.place(relx=0.5, rely=0, relwidth=0, relheight=1)
            val_lbl = tk.Label(axis_frame, text="0.00",
                               bg=C["surface"], fg=C["muted"],
                               font=("Segoe UI Mono", 10), width=6, anchor="e")
            val_lbl.grid(row=i, column=2, padx=(0,10), pady=5)
            if i == 0:
                self._bar_x, self._val_x = bar, val_lbl
            else:
                self._bar_y, self._val_y = bar, val_lbl

        # Button indicators
        btn_frame = tk.Frame(body, bg=C["bg"])
        btn_frame.pack(fill="x", **pad, pady=(4, 20))
        self._binds = []
        for i in range(2):
            dot = tk.Label(btn_frame, text=f"  BTN {i+1}", bg=C["bg"],
                           fg=C["muted"], font=("Segoe UI", 10))
            dot.pack(side="left", padx=(0,16))
            self._binds.append(dot)

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=COLORS["bg"])
        f.pack(fill="x", padx=18, pady=(18, 8))
        tk.Label(f, text=title.upper(),
                 bg=COLORS["bg"], fg=COLORS["accent"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Frame(f, bg=COLORS["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8,0), pady=6)

    def _btn(self, parent, text, cmd, accent=False):
        C = COLORS
        bg = C["accent"] if accent else C["surface2"]
        fg = C["white"]
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, activebackground=C["accent_dim"],
                      activeforeground=C["white"],
                      relief="flat", bd=0, pady=8,
                      font=("Segoe UI", 11),
                      cursor="hand2")
        return b

    def _slider(self, parent, label, hint, key, lo, hi, step, is_int=False):
        C = COLORS
        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="x", padx=18, pady=(0,8))

        top = tk.Frame(f, bg=C["bg"])
        top.pack(fill="x")
        tk.Label(top, text=label, bg=C["bg"], fg=C["text"],
                 font=("Segoe UI", 11)).pack(side="left")

        def fmt(v): return str(int(v)) if is_int else f"{v:.2f}"
        val_lbl = tk.Label(top, text=fmt(self.cfg[key]),
                           bg=C["bg"], fg=C["accent"],
                           font=("Segoe UI Mono", 11), width=5, anchor="e")
        val_lbl.pack(side="right")

        tk.Label(f, text=hint, bg=C["bg"], fg=C["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w")

        var = tk.DoubleVar(value=self.cfg[key])
        def on_change(*_):
            v = round(var.get() / step) * step
            if is_int: v = int(v)
            val_lbl.config(text=fmt(v))
            self.cfg[key] = v
            if self.bridge: self.bridge.update_cfg(dict(self.cfg))

        s = ttk.Scale(f, from_=lo, to=hi, variable=var,
                      orient="horizontal", command=on_change)
        style = ttk.Style()
        style.configure("TScale", background=C["bg"])
        s.pack(fill="x", pady=(4,0))

    def _toggle(self, parent, label, key):
        C = COLORS
        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="x", padx=18, pady=(0,8))

        var = tk.BooleanVar(value=self.cfg[key])
        def on_toggle():
            self.cfg[key] = var.get()
            if self.bridge: self.bridge.update_cfg(dict(self.cfg))

        cb = tk.Checkbutton(f, text=label, variable=var, command=on_toggle,
                            bg=C["bg"], fg=C["text"],
                            selectcolor=C["accent_dim"],
                            activebackground=C["bg"],
                            activeforeground=C["text"],
                            font=("Segoe UI", 11))
        cb.pack(anchor="w")

    def _dropdown(self, parent, label, key):
        C = COLORS
        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="x", padx=18, pady=(0,8))
        tk.Label(f, text=label, bg=C["bg"], fg=C["text"],
                 font=("Segoe UI", 11)).pack(side="left")

        var = tk.StringVar(value=self.cfg[key] or "none")
        def on_change(*_):
            v = var.get()
            self.cfg[key] = None if v == "none" else v
            if self.bridge: self.bridge.update_cfg(dict(self.cfg))

        om = ttk.OptionMenu(f, var, var.get(), *BUTTON_CHOICES,
                            command=lambda _: on_change())
        om.pack(side="left", padx=(10,0))

    # ── actions ───────────────────────────────────────────────────────────────

    def _refresh_pkg_status(self):
        for pkg, dot in self.pkg_labels.items():
            if pkg_ok(pkg):
                dot.config(fg=COLORS["green"])
            else:
                dot.config(fg=COLORS["red"])

    def _do_install(self):
        self.install_btn.config(state="disabled", text="Installing…")
        def cb(msg, error=False, done=False):
            self.after(0, lambda: self.install_status.config(
                text=msg,
                fg=COLORS["red"] if error else COLORS["green"] if done else COLORS["amber"]
            ))
            if done or error:
                self.after(0, lambda: self.install_btn.config(
                    state="normal", text="Install all packages"))
                self.after(0, self._refresh_pkg_status)
        install_pkgs(cb)

    def _save_settings(self):
        save_cfg(self.cfg)
        self.status_lbl.config(text="Settings saved.")
        self.after(2000, lambda: self.status_lbl.config(
            text="Running…" if self.running else "Stopped"))

    def _reset_settings(self):
        if messagebox.askyesno("Reset", "Reset all settings to defaults?"):
            self.cfg = dict(DEFAULTS)
            save_cfg(self.cfg)
            messagebox.showinfo("Reset", "Settings reset. Restart the app to see updated sliders.")

    def _toggle_bridge(self):
        if not self.running:
            self._start_bridge()
        else:
            self._stop_bridge()

    def _start_bridge(self):
        if not all(pkg_ok(p) for p in REQUIRED):
            messagebox.showerror("Packages missing",
                "Please install all packages first (step 1).")
            return
        self.running = True
        self.run_btn.config(text="■  Stop bridge", bg=COLORS["red"])
        self.status_dot.config(fg=COLORS["amber"])
        self.status_lbl.config(text="Connecting…", fg=COLORS["amber"])

        self.bridge = Bridge(
            dict(self.cfg),
            on_state=self._on_bridge_state,
            on_error=self._on_bridge_error,
        )
        self.bridge.start()
        self.after(600, self._check_bridge_alive)

    def _check_bridge_alive(self):
        if self.running:
            self.status_dot.config(fg=COLORS["green"])
            self.status_lbl.config(text="Running — SpaceMouse active",
                                   fg=COLORS["green"])

    def _stop_bridge(self):
        self.running = False
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        self.run_btn.config(text="▶  Start bridge", bg=COLORS["accent"])
        self.status_dot.config(fg=COLORS["muted"])
        self.status_lbl.config(text="Stopped", fg=COLORS["muted"])
        self._update_axes(0.0, 0.0)
        for dot in self._binds:
            dot.config(fg=COLORS["muted"])

    def _on_bridge_state(self, x, y, b0, b1):
        self.after(0, lambda: self._update_axes(x, y))
        self.after(0, lambda: self._update_btns(b0, b1))

    def _on_bridge_error(self, msg):
        self.after(0, lambda: self._stop_bridge())
        self.after(0, lambda: messagebox.showerror("Bridge error", msg))

    def _update_axes(self, x, y):
        for val, bar, lbl in [(x, self._bar_x, self._val_x),
                               (y, self._bar_y, self._val_y)]:
            w  = bar.master.winfo_width()
            rw = abs(val) * 0.5
            rx = 0.5 if val >= 0 else 0.5 - rw
            bar.place(relx=rx, rely=0, relwidth=rw, relheight=1)
            bar.config(bg=COLORS["accent"] if abs(val) > 0.01 else COLORS["muted"])
            lbl.config(text=f"{val:+.2f}",
                       fg=COLORS["accent"] if abs(val) > 0.01 else COLORS["muted"])

    def _update_btns(self, b0, b1):
        for i, pressed in enumerate([b0, b1]):
            m = self.cfg[f"button_{i}_mapping"] or "none"
            self._binds[i].config(
                text=f"  BTN {i+1}: {m}",
                fg=COLORS["green"] if pressed else COLORS["muted"]
            )

    def _on_close(self):
        self._stop_bridge()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
