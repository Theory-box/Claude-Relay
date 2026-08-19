#!/usr/bin/env python3
"""server.py — tiny local API for the merge analyzer UI.

Routes:
  GET  /                -> the single-file UI
  GET  /api/blenders    -> {version: exe} discovered on this machine
  POST /api/analyze     -> {path[, ignore_rules, version]} -> analysis + per-group names
  POST /api/execute     -> {path, plan, version, overwrite, open_after} -> stats
"""
import os, sys, json
from http.server import BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):                       # PyInstaller bundle
    APP = os.path.join(sys._MEIPASS, "blend-merge-analyzer")
    HERE = os.path.join(APP, "backend")
    UI = os.path.join(APP, "ui", "merge-analyzer.html")
else:
    APP = os.path.dirname(HERE)
    UI = os.path.join(APP, "ui", "merge-analyzer.html")
sys.path.insert(0, HERE)
import engine, analyze, blender_manage

def _cpu_and_suggested_workers():
    """Cores + a memory-aware default worker count (each worker holds ~1.5GB while it reads
    the source). Cap the DEFAULT so we don't oversubscribe RAM; the user can raise it to cores."""
    import os
    cpu = os.cpu_count() or 1
    ram_gb = 8.0
    try:
        ram_gb = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1e9
    except (ValueError, AttributeError, OSError):
        try:
            import ctypes
            class _MS(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            m = _MS(); m.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            ram_gb = m.ullTotalPhys / 1e9
        except Exception:
            pass
    by_ram = max(1, int(ram_gb // 2))     # ~1.5-2GB per worker, leave headroom
    return cpu, max(1, min(cpu, by_ram))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(UI, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, f"UI not found: {e}", "text/plain")
        elif self.path == "/api/blenders":
            try:
                self._send(200, json.dumps(engine.blenders()))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
        else:
            self._send(404, "not found", "text/plain")

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        try:
            req = self._body()
            if self.path == "/api/analyze":
                path = req["path"]
                data = engine.extract_names(path, req.get("version"))   # use selected build
                out = analyze.analyze(data["objects"], req.get("ignore_rules"))
                out["detected"] = data.get("detected")
                out["object_total"] = len(data["objects"])
                cpu, suggested = _cpu_and_suggested_workers()
                out["cpu_count"] = cpu
                out["suggested_workers"] = suggested
                self._send(200, json.dumps(out))
            elif self.path == "/api/add_blender":
                added = blender_manage.add_blender(req.get("path"))
                self._send(200, json.dumps({"added": added,
                                            "blenders": blender_manage.discover(engine.CFG)}))
            elif self.path == "/api/execute":
                res = engine.execute_plan(
                    req["path"], req["plan"],
                    version=req.get("version"),
                    overwrite=bool(req.get("overwrite")),
                    open_after=bool(req.get("open_after")),
                    include_untouched=req.get("include_untouched", True),
                    tag_materials=req.get("tag_materials", True),
                    workers=int(req.get("workers", 1) or 1),
                )
                self._send(200, json.dumps(res))
            else:
                self._send(404, json.dumps({"error": "unknown route"}))
        except Exception as e:
            import traceback
            self._send(500, json.dumps({"error": str(e), "trace": traceback.format_exc()[-1200:]}))
