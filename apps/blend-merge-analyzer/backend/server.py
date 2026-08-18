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
                )
                self._send(200, json.dumps(res))
            else:
                self._send(404, json.dumps({"error": "unknown route"}))
        except Exception as e:
            import traceback
            self._send(500, json.dumps({"error": str(e), "trace": traceback.format_exc()[-1200:]}))
