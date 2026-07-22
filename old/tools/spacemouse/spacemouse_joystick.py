#!/usr/bin/env python3
"""
spacemouse_joystick.py  —  SpaceMouse → Virtual Xbox Controller
Run with: py spacemouse_joystick.py

Windows: Requires ViGEmBus driver (auto-prompted if missing)
         https://github.com/nefarius/ViGEmBus/releases/latest

Mapped axes:
  SpaceMouse X  (left/right pan)   →  Left Stick X
  SpaceMouse Y  (fwd/back push)    →  Left Stick Y
  SpaceMouse Rz (yaw/twist)        →  Right Stick X
  Z, Rx, Ry  (up/down, tilt)       →  IGNORED
"""

import sys, subprocess, importlib, importlib.util, threading, time, struct, webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

REQUIRED = ["hid", "vgamepad"]
PIP_NAMES = {"hid": "hidapi", "vgamepad": "vgamepad"}
VIGEMBUS_URL = "https://github.com/nefarius/ViGEmBus/releases/latest"

SPACEMOUSE_DEVICES = [
    (0x256f, 0xc62e, "SpaceMouse Wireless (USB)"),
    (0x256f, 0xc62f, "SpaceMouse Wireless (BT)"),
    (0x256f, 0xc631, "SpaceMouse Pro Wireless (USB)"),
    (0x256f, 0xc632, "SpaceMouse Pro Wireless (BT)"),
    (0x256f, 0xc633, "SpaceMouse Enterprise"),
    (0x256f, 0xc635, "SpaceMouse Compact"),
    (0x256f, 0xc652, "SpaceMouse Module"),
    (0x046d, 0xc626, "SpaceMouse Plus"),
    (0x046d, 0xc628, "SpaceNavigator"),
    (0x046d, 0xc62b, "SpaceMouse Pro"),
    (0x046d, 0xc629, "SpacePilot"),
    (0x046d, 0xc627, "SpaceExplorer"),
    (0x046d, 0xc603, "SpaceMouse Plus XT"),
]
KNOWN_VID_PID = {(v, p) for v, p, _ in SPACEMOUSE_DEVICES}


# ── Dependency installer ──────────────────────────────────────────────────────

def install_deps_if_needed():
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if not missing:
        return

    splash = tk.Tk()
    splash.title("SpaceMouse → Joystick")
    splash.geometry("380x140")
    splash.resizable(False, False)
    splash.configure(bg="#ffffff")
    tk.Label(splash, text="First-run setup", font=("Segoe UI", 13, "bold"),
             bg="#ffffff", fg="#111111").pack(pady=(22, 4))
    tk.Label(splash, text="Installing required packages...",
             font=("Segoe UI", 10), bg="#ffffff", fg="#555555").pack()
    bar = ttk.Progressbar(splash, mode="indeterminate", length=300)
    bar.pack(pady=14)
    bar.start(12)
    splash.update()

    def do_install():
        ok = True
        for mod in missing:
            pkg = PIP_NAMES.get(mod, mod)
            r = subprocess.run([sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                               capture_output=True)
            if r.returncode != 0:
                ok = False
        splash.after(0, lambda: finish(ok))

    def finish(ok):
        splash.destroy()
        if not ok:
            messagebox.showerror("Setup failed",
                "Could not install packages.\nRun:  pip install hidapi vgamepad")
            sys.exit(1)

    threading.Thread(target=do_install, daemon=True).start()
    splash.mainloop()


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_spacemouse():
    import hid
    for dev in hid.enumerate():
        key = (dev["vendor_id"], dev["product_id"])
        if key in KNOWN_VID_PID:
            name = next(n for v, p, n in SPACEMOUSE_DEVICES if (v, p) == key)
            return dev["vendor_id"], dev["product_id"], name
    return None


def parse_report(data, current):
    """
    Parse one HID report, updating only the axes present in that report.
    Returns a new dict with unchanged axes carried over from `current`.
    Report ID 1 = translation x/y/z
    Report ID 2 = rotation rx/ry/rz
    Some devices pack all 6 axes into a single report — handled too.
    """
    out = dict(current)  # carry over all previous axis values
    if len(data) < 7:
        return out

    rid = data[0]

    if rid == 1:
        out["x"] = struct.unpack_from("<h", bytes(data[1:3]))[0]
        out["y"] = struct.unpack_from("<h", bytes(data[3:5]))[0]
        out["z"] = struct.unpack_from("<h", bytes(data[5:7]))[0]

    elif rid == 2:
        out["rx"] = struct.unpack_from("<h", bytes(data[1:3]))[0]
        out["ry"] = struct.unpack_from("<h", bytes(data[3:5]))[0]
        out["rz"] = struct.unpack_from("<h", bytes(data[5:7]))[0]

    elif rid == 0 and len(data) >= 13:
        # Some devices use report ID 0 with all axes packed together
        out["x"]  = struct.unpack_from("<h", bytes(data[1:3]))[0]
        out["y"]  = struct.unpack_from("<h", bytes(data[3:5]))[0]
        out["z"]  = struct.unpack_from("<h", bytes(data[5:7]))[0]
        out["rx"] = struct.unpack_from("<h", bytes(data[7:9]))[0]
        out["ry"] = struct.unpack_from("<h", bytes(data[9:11]))[0]
        out["rz"] = struct.unpack_from("<h", bytes(data[11:13]))[0]

    return out


def scale(raw, deadzone, sensitivity, max_in):
    if abs(raw) < deadzone:
        return 0.0
    sign = 1 if raw > 0 else -1
    mag = (abs(raw) - deadzone) / max(1, max_in - deadzone)
    return max(-1.0, min(1.0, sign * mag * sensitivity))


# ── Main App ──────────────────────────────────────────────────────────────────

class App:
    ACCENT  = "#5b5bd6"
    RED     = "#e5484d"
    GREEN   = "#46a758"
    BG      = "#fafafa"
    SURFACE = "#ffffff"
    BORDER  = "#e4e4e7"
    TEXT    = "#111111"
    MUTED   = "#71717a"
    TRACK_H = 6
    THUMB_S = 16

    def __init__(self, root):
        self.root = root
        self.root.title("SpaceMouse → Joystick")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG)

        self.running  = False
        self.gamepad  = None
        self.hid_dev  = None
        self._lock    = threading.Lock()
        self._vals    = {"x": 0.0, "y": 0.0, "rz": 0.0}
        self._raw     = {"x": 0, "y": 0, "rz": 0}
        self._obs_max = {"x": 50, "y": 50, "rz": 50}

        self.dz_var   = tk.IntVar(value=10)
        self.sens_var = tk.DoubleVar(value=1.0)
        self.inv_x    = tk.BooleanVar(value=False)
        self.inv_y    = tk.BooleanVar(value=True)
        self.inv_rz   = tk.BooleanVar(value=False)

        self._style()
        self._build()
        self._poll_device()

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TCheckbutton", background=self.BG, foreground=self.TEXT,
                    font=("Segoe UI", 10))
        s.map("TCheckbutton", background=[("active", self.BG)])

    def _card(self, parent):
        return tk.Frame(parent, bg=self.SURFACE,
                        highlightthickness=1, highlightbackground=self.BORDER)

    def _build(self):
        P = 14

        # Status
        sc = self._card(self.root)
        sc.pack(fill="x", padx=P, pady=(P, 6))
        self._dot = tk.Canvas(sc, width=10, height=10, bg=self.SURFACE,
                              highlightthickness=0)
        self._dot.pack(side="left", padx=(12, 6), pady=12)
        self._dot_item = self._dot.create_oval(1, 1, 9, 9, fill=self.BORDER, outline="")
        self.status_lbl = tk.Label(sc, text="Looking for SpaceMouse…",
                                   bg=self.SURFACE, fg=self.MUTED,
                                   font=("Segoe UI", 10))
        self.status_lbl.pack(side="left", pady=12)

        # Settings
        setc = self._card(self.root)
        setc.pack(fill="x", padx=P, pady=6)
        tk.Label(setc, text="Settings", bg=self.SURFACE, fg=self.MUTED,
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w",
                                            padx=12, pady=(10, 2), columnspan=3)

        def row_slider(r, label, var, lo, hi, res=1, fmt=lambda v: str(int(v))):
            tk.Label(setc, text=label, bg=self.SURFACE, fg=self.TEXT,
                     font=("Segoe UI", 10), width=14, anchor="w").grid(
                row=r, column=0, padx=(12, 4), pady=4, sticky="w")
            sl = tk.Scale(setc, from_=lo, to=hi, resolution=res,
                          orient="horizontal", variable=var, showvalue=False,
                          length=160, bg=self.SURFACE, troughcolor=self.BORDER,
                          activebackground=self.ACCENT, highlightthickness=0,
                          sliderlength=self.THUMB_S, sliderrelief="flat", bd=0)
            sl.grid(row=r, column=1, pady=4)
            val_lbl = tk.Label(setc, text=fmt(var.get()), bg=self.SURFACE,
                               fg=self.TEXT, font=("Segoe UI", 10), width=5)
            val_lbl.grid(row=r, column=2, padx=(4, 12))
            var.trace_add("write", lambda *_: val_lbl.config(text=fmt(var.get())))

        row_slider(1, "Deadzone", self.dz_var, 0, 200)
        row_slider(2, "Sensitivity", self.sens_var, 0.1, 3.0, 0.05,
                   fmt=lambda v: f"{float(v):.2f}")
        tk.Frame(setc, bg=self.BORDER, height=1).grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=4)
        for r, (text, var) in enumerate([
            ("Invert X  (left/right)", self.inv_x),
            ("Invert Y  (fwd/back)",   self.inv_y),
            ("Invert Yaw  (twist)",    self.inv_rz),
        ], start=4):
            tk.Checkbutton(setc, text=text, variable=var, bg=self.SURFACE,
                           fg=self.TEXT, activebackground=self.SURFACE,
                           font=("Segoe UI", 10), selectcolor=self.SURFACE).grid(
                row=r, column=0, columnspan=3, sticky="w", padx=12, pady=2)
        tk.Frame(setc, bg=self.SURFACE, height=8).grid(row=7, column=0)

        # Axis monitor
        axc = self._card(self.root)
        axc.pack(fill="x", padx=P, pady=6)
        tk.Label(axc, text="Live output  (raw device value shown right)",
                 bg=self.SURFACE, fg=self.MUTED, font=("Segoe UI", 8)).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4), columnspan=5)

        self._bars     = {}
        self._raw_lbls = {}
        self._max_lbls = {}

        for i, (axis, lbl) in enumerate([
            ("x",  "LS-X  (pan)"),
            ("y",  "LS-Y  (push)"),
            ("rz", "RS-X  (yaw)"),
        ]):
            r = i + 1
            tk.Label(axc, text=lbl, bg=self.SURFACE, fg=self.TEXT,
                     font=("Segoe UI", 10), width=13, anchor="w").grid(
                row=r, column=0, padx=(12, 4), pady=5, sticky="w")
            bf = tk.Frame(axc, bg=self.SURFACE)
            bf.grid(row=r, column=1, pady=5)
            neg = tk.Canvas(bf, width=70, height=self.TRACK_H,
                            bg=self.BORDER, highlightthickness=0)
            neg.pack(side="left")
            pos = tk.Canvas(bf, width=70, height=self.TRACK_H,
                            bg=self.BORDER, highlightthickness=0)
            pos.pack(side="left")
            scaled_lbl = tk.Label(axc, text=" 0.00", bg=self.SURFACE,
                                  fg=self.TEXT, font=("Segoe UI", 10, "bold"),
                                  width=6, anchor="e")
            scaled_lbl.grid(row=r, column=2, padx=4)
            raw_lbl = tk.Label(axc, text="raw: 0", bg=self.SURFACE,
                               fg=self.MUTED, font=("Segoe UI", 9), width=10, anchor="w")
            raw_lbl.grid(row=r, column=3, padx=(4, 4))
            max_lbl = tk.Label(axc, text="max: 50", bg=self.SURFACE,
                               fg=self.MUTED, font=("Segoe UI", 9), width=9, anchor="w")
            max_lbl.grid(row=r, column=4, padx=(0, 12))
            self._bars[axis]     = (neg, pos, scaled_lbl)
            self._raw_lbls[axis] = raw_lbl
            self._max_lbls[axis] = max_lbl

        tk.Button(axc, text="Reset learned max", font=("Segoe UI", 9),
                  bg=self.BG, fg=self.MUTED, relief="flat", bd=0,
                  cursor="hand2", command=self._reset_max).grid(
            row=4, column=0, columnspan=5, pady=(0, 8))
        tk.Frame(axc, bg=self.SURFACE, height=4).grid(row=5, column=0)

        # Buttons
        bf2 = tk.Frame(self.root, bg=self.BG)
        bf2.pack(pady=(4, P))
        self.start_btn = tk.Button(bf2, text="▶  Start", width=13,
            font=("Segoe UI", 10, "bold"), bg=self.GREEN, fg="#ffffff",
            activebackground="#3a8f49", activeforeground="#ffffff",
            relief="flat", bd=0, padx=8, pady=6, cursor="hand2", command=self.start)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = tk.Button(bf2, text="■  Stop", width=13,
            font=("Segoe UI", 10, "bold"), bg=self.BORDER, fg=self.MUTED,
            relief="flat", bd=0, padx=8, pady=6, cursor="hand2",
            state="disabled", command=self.stop)
        self.stop_btn.pack(side="left", padx=6)

        hint = tk.Label(self.root, text="Windows: needs ViGEmBus driver  ↗",
                        bg=self.BG, fg=self.MUTED, font=("Segoe UI", 8), cursor="hand2")
        hint.pack(pady=(0, 6))
        hint.bind("<Button-1>", lambda _: webbrowser.open(VIGEMBUS_URL))

    def _update_bar(self, axis, value):
        neg, pos, lbl = self._bars[axis]
        W = 70
        if value < 0:
            fw = int(abs(value) * W)
            neg.delete("all")
            neg.create_rectangle(W - fw, 0, W, self.TRACK_H,
                                 fill=self.ACCENT, outline="")
            pos.delete("all")
        else:
            fw = int(value * W)
            neg.delete("all")
            pos.delete("all")
            pos.create_rectangle(0, 0, fw, self.TRACK_H,
                                 fill=self.ACCENT, outline="")
        sign = "+" if value >= 0 else ""
        lbl.config(text=f"{sign}{value:.2f}")

    def _reset_max(self):
        with self._lock:
            self._obs_max = {"x": 50, "y": 50, "rz": 50}

    def _poll_device(self):
        found = find_spacemouse()
        if found:
            _, _, name = found
            self._dot.itemconfig(self._dot_item, fill=self.GREEN)
            self.status_lbl.config(text=f"{name} connected", fg=self.TEXT)
        else:
            self._dot.itemconfig(self._dot_item, fill=self.BORDER)
            self.status_lbl.config(text="No SpaceMouse found — plug it in", fg=self.MUTED)
        self.root.after(3000, self._poll_device)

    def start(self):
        import hid, vgamepad as vg
        found = find_spacemouse()
        if not found:
            messagebox.showwarning("No device",
                "No SpaceMouse detected.\nPlug it in and try again.")
            return
        try:
            self.gamepad = vg.VX360Gamepad()
        except Exception:
            if messagebox.askyesno("ViGEmBus required",
                "The ViGEmBus driver is needed.\nOpen the download page?"):
                webbrowser.open(VIGEMBUS_URL)
            return

        vid, pid, name = found
        try:
            self.hid_dev = hid.device()
            self.hid_dev.open(vid, pid)
            self.hid_dev.set_nonblocking(True)
        except Exception as e:
            messagebox.showerror("HID error",
                f"Could not open SpaceMouse:\n{e}\n\nTry running as administrator.")
            self.gamepad = None
            return

        self.running = True
        self.start_btn.config(state="disabled", bg="#aaaaaa")
        self.stop_btn.config(state="normal", bg=self.RED, fg="#ffffff",
                             activebackground="#c0392b")
        self._dot.itemconfig(self._dot_item, fill=self.ACCENT)
        self.status_lbl.config(text=f"Mapping {name}…", fg=self.ACCENT)
        threading.Thread(target=self._loop, daemon=True).start()
        self._refresh_ui()

    def stop(self):
        self.running = False
        time.sleep(0.12)
        if self.hid_dev:
            try: self.hid_dev.close()
            except: pass
            self.hid_dev = None
        if self.gamepad:
            try:
                self.gamepad.reset()
                self.gamepad.update()
            except: pass
            self.gamepad = None
        self.start_btn.config(state="normal", bg=self.GREEN)
        self.stop_btn.config(state="disabled", bg=self.BORDER, fg=self.MUTED)
        self._dot.itemconfig(self._dot_item, fill=self.GREEN)
        self.status_lbl.config(text="Stopped — ready", fg=self.MUTED)
        for axis in self._bars:
            self._update_bar(axis, 0.0)
        with self._lock:
            self._vals = {"x": 0.0, "y": 0.0, "rz": 0.0}
            self._raw  = {"x": 0, "y": 0, "rz": 0}

    def _loop(self):
        # Persistent axis state — only updated when that report ID arrives
        axis_state = {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}
        prev_out = {"x": 0.0, "y": 0.0, "rz": 0.0}

        while self.running:
            try:
                data = self.hid_dev.read(64)
            except Exception:
                break
            if not data:
                time.sleep(0.005)
                continue

            # Merge new report into persistent state (don't zero unmentioned axes)
            axis_state = parse_report(data, axis_state)

            dz   = self.dz_var.get()
            sens = float(self.sens_var.get())

            # Auto-learn max from observed values
            with self._lock:
                for axis in ("x", "y", "rz"):
                    v = abs(axis_state[axis])
                    if v > self._obs_max[axis]:
                        self._obs_max[axis] = v
                obs = dict(self._obs_max)
                self._raw = {"x": axis_state["x"],
                             "y": axis_state["y"],
                             "rz": axis_state["rz"]}

            ax  = scale(axis_state["x"],  dz, sens, obs["x"])
            ay  = scale(axis_state["y"],  dz, sens, obs["y"])
            arz = scale(axis_state["rz"], dz, sens, obs["rz"])

            if self.inv_x.get():  ax  = -ax
            if self.inv_y.get():  ay  = -ay
            if self.inv_rz.get(): arz = -arz

            cur = {"x": ax, "y": ay, "rz": arz}
            if cur != prev_out:
                try:
                    self.gamepad.left_joystick_float(x_value_float=ax, y_value_float=ay)
                    self.gamepad.right_joystick_float(x_value_float=arz, y_value_float=0.0)
                    self.gamepad.update()
                except Exception:
                    break
                with self._lock:
                    self._vals = dict(cur)
                prev_out = dict(cur)

        if self.running:
            self.root.after(0, self.stop)

    def _refresh_ui(self):
        if not self.running:
            return
        with self._lock:
            vals = dict(self._vals)
            raws = dict(self._raw)
            maxs = dict(self._obs_max)
        for axis, v in vals.items():
            self._update_bar(axis, v)
            self._raw_lbls[axis].config(text=f"raw: {raws[axis]}")
            self._max_lbls[axis].config(text=f"max: {maxs[axis]}")
        self.root.after(33, self._refresh_ui)


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    install_deps_if_needed()
    import hid, vgamepad
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop(), root.destroy()))
    root.mainloop()
