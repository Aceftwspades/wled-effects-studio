"""A view in its own window: the 3-D cube or the logical net on a second
monitor while the graph has the main window.

Dear PyGui has one viewport a process, so a pop-out is a second process
(python -m native.popout cube <block>) showing what the app publishes into
a shared-memory block: the net at LED resolution, the geometry (a cube's
face size, or every LED's position) and the camera it started from. The
pop-out draws the picture itself - the GPU quads for a cube, the point
cloud for anything else - so it is as sharp as its window is big, and it
orbits and zooms on its own. Closing the window (or Esc) hands the pane
back to the app; the app closing takes the pop-out with it. The window
remembers where it was, which on two monitors is the point.

    app side:  Popouts.open(view, eng, cam) / close(view) / is_out(view)
               Popouts.publish(net, eng, cam) every frame, poll() for windows closed by hand
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from multiprocessing import shared_memory

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS_DIR = os.path.join(tempfile.gettempdir(), "cubefx")

MAX_NET = 512 * 512 * 3          # bytes: the net (or the raw LEDs) at LED resolution
MAX_PTS = 65536 * 3              # floats: LED positions
HDR = 256
SRC_SCALE = 4                    # the net a few times its size, so bilinear sampling keeps the LEDs square
CUBE_MAX = 620                   # the point-cloud render is quadratic in this
TITLES = {"cube": "3-D view", "net": "Logical net"}


class Block:
    """The shared block. Ints: 0 alive, 1 frame seq, 2 rows, 3 cols, 4 cube
    (1: the net of a cube of B a face; 0: LEDs with positions), 5 B, 6 point
    count, 7 geometry seq, 8 six faces. Floats: yaw, pitch, dist. Then the
    pixels, then the positions."""

    def __init__(self, name, create):
        size = HDR + MAX_NET + MAX_PTS * 4
        self.shm = shared_memory.SharedMemory(name=name, create=create, size=size)
        buf = self.shm.buf
        self.i = np.ndarray(16, np.int32, buf, 0)
        self.f = np.ndarray(8, np.float32, buf, 64)
        self.px = np.ndarray(MAX_NET, np.uint8, buf, HDR)
        self.pts = np.ndarray(MAX_PTS, np.float32, buf, HDR + MAX_NET)

    def close(self):
        # the views export the buffer; the block cannot close while they live
        self.i = self.f = self.px = self.pts = None
        try:
            self.shm.close()
        except Exception:
            pass
        try:
            self.shm.unlink()          # a no-op on Windows, where the last handle frees it
        except Exception:
            pass


# --- the app's side ---------------------------------------------------------------
class Popouts:
    def __init__(self):
        self.jobs = {}          # view -> (process, Block)
        self._pos_id = None     # id() of the positions last written

    def is_out(self, view):
        return view in self.jobs

    def views(self):
        return list(self.jobs)

    def open(self, view, eng, cam):
        if view in self.jobs:
            return
        name = f"cubefx_pop_{view}_{os.getpid()}_{int(time.time()) & 0xffff}"
        blk = Block(name, create=True)
        blk.i[:] = 0
        blk.i[0] = 1
        blk.f[0:3] = cam
        self._pos_id = None
        self.jobs[view] = (None, blk)
        # the header before the process starts, so its first frame has a size
        try:
            self._write(view, blk, np.zeros((eng.rows, eng.cols, 3), np.uint8), eng, cam)
        except Exception:
            pass
        proc = subprocess.Popen([sys.executable, "-m", "native.popout", view, name], cwd=HERE)
        self.jobs[view] = (proc, blk)

    def close(self, view):
        job = self.jobs.pop(view, None)
        if not job:
            return
        proc, blk = job
        try:
            blk.i[0] = 0                      # asks the window to close itself
            if proc is not None:
                try:
                    proc.wait(2.0)
                except Exception:
                    proc.kill()
        finally:
            blk.close()

    def close_all(self):
        for v in list(self.jobs):
            self.close(v)

    def poll(self):
        """The views whose windows were closed by hand: their panes come back."""
        gone = [v for v, (p, b) in self.jobs.items() if p is not None and p.poll() is not None]
        for v in gone:
            _, blk = self.jobs.pop(v)
            blk.close()
        return gone

    def publish(self, net, eng, cam):
        for view, (proc, blk) in self.jobs.items():
            try:
                self._write(view, blk, net, eng, cam)
            except Exception:
                pass

    def _write(self, view, blk, net, eng, cam):
        g = eng.geom
        cube = g is not None and g.kind == "cube" and not eng.fx.get("o3")
        if view == "net" or cube:
            px = net
        else:
            px = eng.rgb()                    # the LEDs in order, for the positions
        px = np.ascontiguousarray(px).reshape(-1)
        if px.size > MAX_NET:
            return
        rows, cols = (net.shape[0], net.shape[1]) if (view == "net" or cube) else (1, px.size // 3)
        blk.i[2] = rows
        blk.i[3] = cols
        blk.i[4] = 1 if cube else 0
        blk.i[5] = int(eng.B)
        blk.i[8] = 1 if getattr(eng, "six", False) else 0
        if not cube and g is not None and view == "cube":
            pos = g.pos
            if id(pos) != self._pos_id:
                flat = np.ascontiguousarray(pos, dtype=np.float32).reshape(-1)
                n = min(flat.size, MAX_PTS)
                blk.pts[:n] = flat[:n]
                blk.i[6] = n // 3
                blk.i[7] += 1
                self._pos_id = id(pos)
        else:
            blk.i[6] = 0
        blk.f[0:3] = cam
        blk.px[:px.size] = px
        blk.i[1] += 1


# --- the window ---------------------------------------------------------------------
def _pos_file(view):
    return os.path.join(POS_DIR, f"popout_{view}.json")


def _load_pos(view):
    try:
        return json.load(open(_pos_file(view)))
    except Exception:
        return {}


def run(view, name):
    import dearpygui.dearpygui as dpg
    from native import render
    from native.gpucube import CubeQuads

    lut = np.arange(256, dtype=np.float32) / 255.0
    blk = Block(name, create=False)
    cfg = _load_pos(view)
    w0, h0 = int(cfg.get("w", 720)), int(cfg.get("h", 720))
    dpg.create_context()
    with dpg.theme(tag="th"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (0, 0, 0, 255))
    dpg.bind_theme("th")
    with dpg.texture_registry(tag="texreg"):
        pass
    with dpg.window(tag="root", no_scrollbar=True, no_scroll_with_mouse=True):
        pass
    dpg.set_primary_window("root", True)

    cam = [float(blk.f[0]), float(blk.f[1]), float(blk.f[2])]
    drag = {"on": False, "y0": 0.0, "p0": 0.0}
    state = {"kind": None, "shape": None, "gseq": -1, "quads": None, "size": 0, "bufs": {}}

    def rgba(key, img):
        h, w, _ = img.shape
        buf = state["bufs"].get(key)
        if buf is None or buf.shape[:2] != (h, w):
            buf = np.ones((h, w, 4), np.float32)
            state["bufs"][key] = buf
        np.take(lut, img, out=buf[..., :3])
        return buf.reshape(-1)

    def clear():
        for t in ("img", "tex"):
            if dpg.does_item_exist(t):
                dpg.delete_item(t)
        state["quads"] = None
        state["bufs"].clear()

    def frame():
        rows, cols, cube, B, npts = (int(blk.i[k]) for k in (2, 3, 4, 5, 6))
        if rows <= 0 or cols <= 0:
            return
        # the primary window is the client area; the viewport's own client
        # size can lag the frame (and includes what the frame is not)
        rw, rh = dpg.get_item_rect_size("root")
        vw = int(rw) if rw > 0 else max(64, dpg.get_viewport_client_width())
        vh = int(rh) if rh > 0 else max(64, dpg.get_viewport_client_height())
        size = min(vw, vh)
        if view == "net" or cube:
            px = np.ndarray((rows, cols, 3), np.uint8, blk.px, 0)
        else:
            px = np.ndarray((rows * cols, 3), np.uint8, blk.px, 0)
        kind = "net" if view == "net" else ("cube" if cube else "points")
        shape = (rows, cols, B)
        if kind != state["kind"] or shape != state["shape"] or (kind == "points" and state["gseq"] != int(blk.i[7])):
            clear()
            state["kind"], state["shape"], state["gseq"] = kind, shape, int(blk.i[7])
            if kind == "net":
                k = SRC_SCALE
                dpg.add_raw_texture(cols * k, rows * k, np.zeros(cols * rows * k * k * 4, np.float32),
                                    format=dpg.mvFormat_Float_rgba, tag="tex", parent="texreg")
                dpg.add_image("tex", tag="img", parent="root", width=10, height=10)
            elif kind == "cube":
                n = cols * SRC_SCALE
                dpg.add_raw_texture(n, n, np.zeros(n * n * 4, np.float32), format=dpg.mvFormat_Float_rgba,
                                    tag="tex", parent="texreg")
                state["quads"] = CubeQuads("root", "img", "tex")
            else:
                p = min(CUBE_MAX, size)
                dpg.add_raw_texture(p, p, np.zeros(p * p * 4, np.float32), format=dpg.mvFormat_Float_rgba,
                                    tag="tex", parent="texreg")
                dpg.add_image("tex", tag="img", parent="root", width=10, height=10)
                state["px"] = p
        if kind == "net":
            k = SRC_SCALE
            dpg.set_value("tex", rgba("net", px.repeat(k, 0).repeat(k, 1)))
            # whole pixels per LED when the window allows, the grid stays hard
            sc = max(1, min(vw // cols, vh // rows))
            iw, ih = cols * sc, rows * sc
            if iw > vw or ih > vh:
                f = min(vw / cols, vh / rows)
                iw, ih = int(cols * f), int(rows * f)
            dpg.configure_item("img", width=iw, height=ih)
            dpg.set_item_pos("img", [(vw - iw) // 2, (vh - ih) // 2])
        elif kind == "cube":
            k = SRC_SCALE
            dpg.set_value("tex", rgba("src", px.repeat(k, 0).repeat(k, 1)))
            q = state["quads"]
            q.resize(int(size * 0.86), vw, vh)        # the drawlist is the window; the cube sits centred, a margin round it
            q.camera(cam[0], cam[1], cam[2], six=bool(blk.i[8]))
            state["size"] = size
        else:
            p = state["px"]
            if p != min(CUBE_MAX, size):
                state["kind"] = None           # the texture follows the window; next frame remakes it
                return
            pos = np.ndarray((max(1, npts), 3), np.float32, blk.pts, 0)
            n = min(npts, px.shape[0])
            if n <= 0:
                return
            img = render.render_points(pos[:n], px[:n], p, cam[0], cam[1], cam[2])
            dpg.set_value("tex", rgba("pts", img))
            dpg.configure_item("img", width=size, height=size)
            dpg.set_item_pos("img", [(vw - size) // 2, (vh - size) // 2])

    def on_click(s, a):
        if view == "cube":
            drag["on"] = True
            drag["y0"], drag["p0"] = cam[0], cam[1]

    def on_release(s, a):
        drag["on"] = False

    def on_drag(s, a):
        if not drag["on"]:
            return
        _, dx, dy = a
        k = 3.14159265 / max(120, state.get("size") or min(dpg.get_viewport_client_width(), dpg.get_viewport_client_height()))
        cam[0] = drag["y0"] + dx * k
        cam[1] = max(-1.45, min(1.45, drag["p0"] + dy * k))

    def on_wheel(s, a):
        if view == "cube":
            cam[2] = max(1.9, min(14.0, cam[2] * np.exp(-a * 0.06)))

    def on_key(s, a):
        if a == dpg.mvKey_Escape:
            dpg.stop_dearpygui()
        elif a in (dpg.mvKey_R, dpg.mvKey_Home):
            cam[:] = [-0.6, 0.75, 4.6]

    with dpg.handler_registry():
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=on_click)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=on_release)
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=on_drag)
        dpg.add_mouse_wheel_handler(callback=on_wheel)
        dpg.add_key_press_handler(callback=on_key)

    kw = dict(title=f"WLED Effects Studio - {TITLES.get(view, view)}", width=w0, height=h0, clear_color=(0, 0, 0, 255),
              min_width=160, min_height=160)
    if "x" in cfg and "y" in cfg:
        kw.update(x_pos=int(cfg["x"]), y_pos=int(cfg["y"]))
    dpg.create_viewport(**kw)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    last = -1
    stale = 0
    try:
        while dpg.is_dearpygui_running():
            if int(blk.i[0]) == 0:
                break
            seq = int(blk.i[1])
            if seq != last:
                last = seq
                stale = 0
                frame()
            else:
                stale += 1
                if view == "cube" and drag["on"] or (stale % 30 == 0):
                    frame()                    # the camera moves while the app is paused
            dpg.render_dearpygui_frame()
            # a capture on request, the way the app does it (checked, not the app's window)
            req = os.path.join(POS_DIR, f"popout_{view}.request")
            if os.path.exists(req):
                try:
                    os.remove(req)
                    dpg.output_frame_buffer(os.path.join(POS_DIR, f"popout_{view}.png"))
                except Exception:
                    pass
    finally:
        try:
            os.makedirs(POS_DIR, exist_ok=True)
            x, y = dpg.get_viewport_pos()
            json.dump({"x": int(x), "y": int(y), "w": int(dpg.get_viewport_width()), "h": int(dpg.get_viewport_height())},
                      open(_pos_file(view), "w"))
        except Exception:
            pass
        dpg.destroy_context()
        blk.close()


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
