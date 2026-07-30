#!/usr/bin/env python3
"""relay_app.py — the clickable app. Starts the local engine on a free port and
opens the UI in a native window. Closing the window exits everything (the server
thread is a daemon; no Blender lingers because tasks are short-lived subprocesses)."""
import threading, socket, os, sys
from http.server import ThreadingHTTPServer
import webview  # pywebview
import server   # our request handler + UI path

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class Api:
    def pick_blend(self):
        r = self.window.create_file_dialog(webview.OPEN_DIALOG,
                                            file_types=("Blender file (*.blend)",))
        return r[0] if r else None

def main():
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    api = Api()
    win = webview.create_window("Relay — blend compatibility",
                                f"http://127.0.0.1:{port}", js_api=api,
                                width=1240, height=860, min_size=(900, 620))
    api.window = win
    webview.start()          # blocks until the window closes
    httpd.shutdown()

if __name__ == "__main__":
    main()
