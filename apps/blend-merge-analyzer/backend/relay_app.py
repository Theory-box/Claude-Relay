#!/usr/bin/env python3
"""relay_app.py — the clickable app. Starts the local API on a free port and opens
the UI in a native window (pywebview); falls back to the default browser if the
native backend is unavailable. Closing it exits; no Blender lingers."""
import threading, socket, time, sys, os
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def main():
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    try:
        import webview
        class Api:
            def pick_blend(self):
                r = self.window.create_file_dialog(
                    webview.OPEN_DIALOG, file_types=("Blender file (*.blend)",))
                return r[0] if r else None
            def pick_blender(self):
                # let the user point directly at a Blender executable / app
                r = self.window.create_file_dialog(webview.OPEN_DIALOG)
                return r[0] if r else None
        api = Api()
        win = webview.create_window("blend-merge-analyzer", url, js_api=api,
                                    width=1300, height=880, min_size=(980, 640))
        api.window = win
        webview.start()
    except Exception:
        import webbrowser
        webbrowser.open(url)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass
    httpd.shutdown()

if __name__ == "__main__":
    main()
