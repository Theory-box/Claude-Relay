"""
Phase 1b helper (SPIKE) — cefpython off-screen → shared memory + control socket.

RUNS IN ITS OWN INTERPRETER, NOT BLENDER'S. Set up once on Windows:
    py -3.9 -m venv cef-venv
    cef-venv\Scripts\pip install cefpython3
    cef-venv\Scripts\python helper_cefpython.py --shm-name <name> --width 1280 --height 720 --port 8765 --url https://example.com

The Blender add-on creates the SHM segment and launches this with matching args.
This is a FIRST-DRAFT scaffold — cefpython API call signatures should be sanity-checked
(task B-5) before relying on it. Chromium 66 (cefpython) is fine here: the spike only
proves the pipe; the real build swaps in C++ CEF behind this same contract.

See SHM_CONTRACT.md for the memory layout and message schema.
"""
import argparse, json, socket, struct, threading
from multiprocessing import shared_memory
from cefpython3 import cefpython as cef   # noqa: E402

HEADER = 64

class State:
    def __init__(self, shm, w, h):
        self.shm = shm
        self.w, self.h = w, h
        self.slot_bytes = w * h * 4
        self.buf = shm.buf
        self.browser = None
        # init header
        struct.pack_into("<4sIIIIIII", self.buf, 0,
                         b"BLBR", 1, w, h, w * 4, 0, 0, 0)        # magic..active,sequence
        struct.pack_into("<I", self.buf, 48, self.slot_bytes)

    def publish(self, bgra: bytes, dx, dy, dw, dh):
        active = struct.unpack_from("<I", self.buf, 24)[0]
        write = 1 - active
        off = HEADER + write * self.slot_bytes
        self.buf[off:off + len(bgra)] = bgra
        struct.pack_into("<IIII", self.buf, 32, dx, dy, dw, dh)   # dirty rect
        struct.pack_into("<I", self.buf, 24, write)               # active (publish first)
        seq = struct.unpack_from("<I", self.buf, 28)[0]
        struct.pack_into("<I", self.buf, 28, (seq + 1) & 0xFFFFFFFF)


class RenderHandler:
    def __init__(self, state: State):
        self.state = state

    def GetViewRect(self, rect_out, **_):
        rect_out.extend([0, 0, self.state.w, self.state.h])
        return True

    def OnPaint(self, browser, element_type, dirty_rects, paint_buffer, width, height, **_):
        if element_type != cef.PET_VIEW:
            return
        bgra = paint_buffer.GetString(mode="bgra", origin="top-left")
        dx, dy, dw, dh = (dirty_rects[0] if dirty_rects else (0, 0, width, height))
        self.state.publish(bgra, dx, dy, dw, dh)


def control_server(state: State, port: int):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port)); srv.listen(1)
    conn, _ = srv.accept()
    fragment = b""
    while True:
        head = _recv_n(conn, 4)
        if not head:
            break
        (n,) = struct.unpack(">I", head)
        body = _recv_n(conn, n)
        if not body:
            break
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception:
            continue
        # Marshal onto CEF UI thread — never touch the browser from this thread.
        cef.PostTask(cef.TID_UI, _dispatch, state, msg)


def _recv_n(conn, n):
    out = b""
    while len(out) < n:
        chunk = conn.recv(n - len(out))
        if not chunk:
            return None
        out += chunk
    return out


def _dispatch(state: State, msg: dict):
    b = state.browser
    if b is None:
        return
    host = b.GetHost()
    t = msg.get("t")
    if t == "navigate":
        b.GetMainFrame().LoadUrl(msg["url"])
    elif t == "mouse_move":
        host.SendMouseMoveEvent(msg["x"], msg["y"], mouseLeave=False)
    elif t == "mouse_button":
        btn = {"left": cef.MOUSEBUTTON_LEFT, "right": cef.MOUSEBUTTON_RIGHT,
               "middle": cef.MOUSEBUTTON_MIDDLE}[msg["button"]]
        host.SendMouseClickEvent(msg["x"], msg["y"], btn,
                                 mouseUp=not msg["down"], clickCount=msg.get("clicks", 1))
    elif t == "wheel":
        host.SendMouseWheelEvent(msg["x"], msg["y"], msg.get("dx", 0), msg.get("dy", 0))
    elif t == "key":
        # TODO(B-5): confirm cefpython key event dict keys; CHAR vs KEYDOWN/KEYUP split.
        ev = {"type": cef.KEYEVENT_KEYDOWN if msg["down"] else cef.KEYEVENT_KEYUP,
              "windows_key_code": msg.get("vk", 0), "modifiers": msg.get("mods", 0)}
        host.SendKeyEvent(ev)
        if msg["down"] and msg.get("char"):
            host.SendKeyEvent({"type": cef.KEYEVENT_CHAR,
                               "windows_key_code": ord(msg["char"]),
                               "modifiers": msg.get("mods", 0)})
    elif t == "focus":
        host.SendFocusEvent(bool(msg["on"]))
    elif t == "reload":
        b.Reload()
    elif t in ("back", "forward"):
        (b.GoBack if t == "back" else b.GoForward)()
    elif t == "shutdown":
        cef.QuitMessageLoop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shm-name", required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--url", default="https://example.com")
    a = ap.parse_args()

    shm = shared_memory.SharedMemory(name=a.shm_name, create=False)
    state = State(shm, a.width, a.height)

    cef.Initialize(settings={"windowless_rendering_enabled": True})
    win = cef.WindowInfo(); win.SetAsOffscreen(0)
    state.browser = cef.CreateBrowserSync(win, url=a.url)
    state.browser.SetClientHandler(RenderHandler(state))
    state.browser.SendFocusEvent(True)
    state.browser.WasResized()

    threading.Thread(target=control_server, args=(state, a.port), daemon=True).start()
    cef.MessageLoop()
    cef.Shutdown()
    shm.close()


if __name__ == "__main__":
    main()
