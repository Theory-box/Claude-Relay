#!/usr/bin/env python3
"""server.py — tiny local HTTP server the Relay UI talks to. Serves the UI and the
scan/convert API. In the packaged app this runs as the bundled engine process."""
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import engine

HERE=os.path.dirname(os.path.abspath(__file__))
UI=os.path.join(os.path.dirname(HERE),"ui","relay-ui.html")

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b=body if isinstance(body,bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path in ("/","/index.html"):
            self._send(200, open(UI,"rb").read(), "text/html")
        else: self._send(404,"{}")
    def do_POST(self):
        n=int(self.headers.get("Content-Length",0)); body=json.loads(self.rfile.read(n) or "{}")
        try:
            if self.path=="/api/scan":
                self._send(200, json.dumps(engine.scan(body["path"])))
            elif self.path=="/api/convert":
                res=engine.convert(body["path"], body["selected"], body.get("source_version") or body.get("detected"),
                                    body["target_version"], body["out"])
                self._send(200, json.dumps(res))
            else: self._send(404,"{}")
        except Exception as e:
            self._send(500, json.dumps({"error":str(e)}))

if __name__=="__main__":
    import sys
    port=int(sys.argv[1]) if len(sys.argv)>1 else 8765
    print(f"Relay engine on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1",port), H).serve_forever()
