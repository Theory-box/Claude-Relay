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

def _wait_ready(port, timeout=10):
    """Make sure the local server is accepting connections before we point the window at
    it — avoids an intermittent blank/frozen window from a startup race."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False

def main():
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    _wait_ready(port)
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
        # private_mode gives a fresh in-memory profile each launch, so a force-close
        # can't leave a corrupted WebView2 profile that breaks the next run.
        webview.start(private_mode=True)
    except Exception:
        # Native window backend unavailable — log why, then fall back to the browser.
        try:
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
                   else os.path.dirname(os.path.abspath(__file__))
            import traceback
            with open(os.path.join(base, "merge-analyzer-startup.log"), "w") as f:
                f.write("pywebview could not start; opened in browser instead.\n\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        import webbrowser
        webbrowser.open(url)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass
    httpd.shutdown()

if __name__ == "__main__":
    main()
