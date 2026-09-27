"""The graph view used with a mouse: what the command-file hooks cannot
show, because it is the pointer's - hover, focus, a click landing on the
window it is over. The app is driven by mouse messages posted to its own
window (found by its process id), so the real pointer never moves:

- the app hands the front back to the window that had it: a window in
  front has Dear PyGui's GLFW backend read the real cursor every frame;
- its window drops WM_MOUSELEAVE (subclassed through the test hook): a
  posted move has GLFW track the mouse's leaving, and the real cursor
  being elsewhere, Windows answers at once - the pointer would count as
  gone;
- ImGui is told it has the focus (WM_SETFOCUS), the system left as it is.

    python tests/pointer_app.py          # from studio; Windows; ~1 min; exits 1 on a failure

Checks: the focus frame whole round the 3-D view over the graph; the add
menu's description beside its list, reached and scrolled; the properties
over the canvas kept by clicks on them after a click on a node (the side
panel open and folded); the 3-D view turned by a drag after a click on a
node; the Bitmap painter left alone by a drag from the canvas, painting at
a press; a number dragged in a plain node's properties, the node's own
field following; a node clicked after another and a zoom, selected; the
focus frame drawn where the 3-D view is in every frame while it is moved
and sized. It works in a project of its own, deleted after.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from native import scratch                                 # noqa: E402

PROJECT = "pointer_run"
CMD, LOG = scratch.path("command.json"), scratch.path("pointer.log")
WM_MOUSEMOVE, WM_LDOWN, WM_LUP, WM_RDOWN, WM_RUP, WM_WHEEL, WM_SETFOCUS = 0x0200, 0x0201, 0x0202, 0x0204, 0x0205, 0x020A, 0x0007


class App:
    """The studio from the tree, its window, and a pointer of its own."""

    def __init__(self):
        from ctypes import wintypes
        self.wt = wintypes
        self.u32 = ctypes.windll.user32
        self.pos = None
        self.btn = 0
        self.spam = None

    def start(self):
        prefs = os.path.join(ROOT, "projects", "studio.json")
        self.saved_prefs = open(prefs, "rb").read() if os.path.exists(prefs) else None
        self.project = os.path.join(ROOT, "projects", PROJECT)
        shutil.rmtree(self.project, ignore_errors=True)
        if os.path.exists(CMD):
            os.remove(CMD)
        env = dict(os.environ, STUDIO_NO_UPDATE_CHECK="1", STUDIO_NO_WELCOME="1", STUDIO_REMOTE_CONTROL="1")
        prev = self.u32.GetForegroundWindow()
        self.proc = subprocess.Popen([sys.executable, "-u", "-m", "native.app"], cwd=ROOT, stdout=open(LOG, "w"),
                                     stderr=subprocess.STDOUT, env=env)
        self.hwnd = None
        for _ in range(80):
            time.sleep(0.5)
            self.hwnd = self._window()
            if self.hwnd and "remote control: write" in open(LOG, encoding="utf-8", errors="replace").read():
                break
        if not self.hwnd:
            raise RuntimeError("the studio's window did not come up")
        time.sleep(2)
        if prev and prev != self.hwnd:
            self.send([{"py": f"__import__('ctypes').windll.user32.SetForegroundWindow({int(prev)})"}], 0.5)
        self._drop_mouse_leave()
        self.u32.PostMessageW(self.hwnd, WM_SETFOCUS, 0, 0)
        self.send([{"viewport": [1600, 1000]}, {"project": PROJECT}], 3.0)
        self.send([{"wait_build": True}, {"py": "1"}], 1.0)

    def stop(self):
        self.release()
        try:
            self.send([{"py": "dpg.stop_dearpygui()"}], 1.0, taken=False)
            self.proc.wait(20)
        except Exception:
            self.proc.kill()
        prefs = os.path.join(ROOT, "projects", "studio.json")
        if self.saved_prefs is not None:
            open(prefs, "wb").write(self.saved_prefs)
        shutil.rmtree(self.project, ignore_errors=True)

    def _window(self):
        w, found = self.wt, []

        @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def each(h, _):
            pid = w.DWORD()
            self.u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == self.proc.pid and self.u32.IsWindowVisible(h):
                name = ctypes.create_unicode_buffer(256)
                self.u32.GetWindowTextW(h, name, 256)
                if name.value.startswith("WLED Effects Studio"):
                    found.append(h)
            return True
        self.u32.EnumWindows(each, 0)
        return found[0] if found else None

    def _drop_mouse_leave(self):
        code = "\n".join([
            "import ctypes",
            "from ctypes import wintypes as wt",
            "u = ctypes.windll.user32",
            "u.GetWindowLongPtrW.restype = ctypes.c_longlong",
            "u.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]",
            "u.SetWindowLongPtrW.restype = ctypes.c_longlong",
            "u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_longlong]",
            "u.CallWindowProcW.restype = ctypes.c_longlong",
            "u.CallWindowProcW.argtypes = [ctypes.c_longlong, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]",
            "P = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)",
            f"old = u.GetWindowLongPtrW({int(self.hwnd)}, -4)",
            "def proc(hw, m, w, l):",
            "    return 0 if m == 0x02A3 else u.CallWindowProcW(old, hw, m, w, l)",
            "cb = P(proc)",
            "app._pointer_test_proc = (cb, old)",
            f"u.SetWindowLongPtrW({int(self.hwnd)}, -4, ctypes.cast(cb, ctypes.c_void_p).value)", ""])
        self.send([{"py": f"exec({code!r}, {{'app': app}})"}], 0.3)

    # --- the command file -------------------------------------------------------------------
    def send(self, cmds, wait=0.4, taken=True):
        end = time.time() + 120
        while os.path.exists(CMD) and time.time() < end:
            time.sleep(0.05)
        scratch.write_whole(CMD, json.dumps(cmds))
        end = time.time() + 120
        while taken and os.path.exists(CMD) and time.time() < end:
            time.sleep(0.05)
        time.sleep(wait)

    def ask(self, expr):
        n0 = len(open(LOG, encoding="utf-8", errors="replace").read())
        self.send([{"py": expr}], 0.2)
        for _ in range(50):
            m = re.search(r"^py (.*)$", open(LOG, encoding="utf-8", errors="replace").read()[n0:], re.M)
            if m:
                return eval(m.group(1), {"True": True, "False": False, "None": None})
            time.sleep(0.1)
        return None

    def rect(self, tag):
        """(x, y, w, h) on the screen of a shown item: a window by its position, the rest by their state."""
        r = self.ask(f"(lambda t: (list(dpg.get_item_pos(t) if dpg.get_item_type(t).endswith('::mvWindowAppItem') "
                     f"else dpg.get_item_state(t).get('rect_min', (0, 0))), list(dpg.get_item_state(t).get('rect_size', (0, 0))), "
                     f"dpg.is_item_shown(t)) if dpg.does_item_exist(t) else None)({tag!r})")
        if not r or not r[2]:
            return None
        return tuple(int(v) for v in r[0] + r[1])

    # --- the pointer -------------------------------------------------------------------------
    def _lp(self, x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    def hold(self, x, y, settle=0.15):
        self.pos = (x, y)
        if self.spam is None:
            self.stopping = False

            def run():
                while not self.stopping:
                    if self.pos:
                        self.u32.PostMessageW(self.hwnd, WM_MOUSEMOVE, self.btn, self._lp(*self.pos))
                    time.sleep(0.005)
            self.spam = threading.Thread(target=run, daemon=True)
            self.spam.start()
        time.sleep(settle)

    def move(self, path, secs=0.4):
        for x, y in path:
            self.hold(x, y, settle=max(0.05, secs / max(1, len(path))))

    def release(self):
        if self.spam is not None:
            self.stopping = True
            self.spam.join()
            self.spam = None

    def down(self, x, y, right=False):
        self.hold(x, y)
        self.btn = 2 if right else 1
        self.u32.PostMessageW(self.hwnd, WM_RDOWN if right else WM_LDOWN, self.btn, self._lp(x, y))
        time.sleep(0.1)

    def up(self, right=False):
        self.btn = 0
        self.u32.PostMessageW(self.hwnd, WM_RUP if right else WM_LUP, 0, self._lp(*self.pos))
        time.sleep(0.2)

    def click(self, x, y, right=False):
        self.down(x, y, right)
        self.up(right)

    def wheel(self, x, y, notches):
        self.hold(x, y)
        pt = self.wt.POINT(int(x), int(y))
        self.u32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        for _ in range(abs(notches)):
            self.u32.PostMessageW(self.hwnd, WM_WHEEL, ((120 if notches > 0 else -120) & 0xFFFF) << 16, self._lp(pt.x, pt.y))
            time.sleep(0.08)
        time.sleep(0.3)


def node_rect(app, nid):
    return app.ask(f"[int(v) for v in dpg.get_item_state('gnode_{nid}')['rect_min']] + "
                   f"[int(v) for v in dpg.get_item_state('gnode_{nid}')['rect_size']]")


def title_point(app, nid):
    """The middle of a node's title bar, or None where the canvas does not show it (off it, or under a window on it)."""
    r = node_rect(app, nid)
    x, y = r[0] + r[2] // 2, r[1] + 6
    ok = app.ask(f"(lambda ed, holes: ed[0] + 10 < {x} < ed[0] + ed[2] - 10 and ed[1] + 10 < {y} < ed[1] + ed[3] - 10 and "
                 f"not any(a - 12 <= {x} <= c + 12 and b - 12 <= {y} <= d + 12 for a, b, c, d in holes))"
                 f"(room.S.editor, list(app._holes or []))")
    return (x, y) if ok else None


def empty_spot(app):
    """A point of the canvas with no node and no window over it."""
    return app.ask("(lambda ed, holes, nodes: next(((x, y) for y in range(int(ed[1]) + 60, int(ed[1] + ed[3]) - 40, 24) "
                   "for x in range(int(ed[0]) + 40, int(ed[0] + ed[2]) - 40, 24) "
                   "if not any(a - 12 <= x <= c + 12 and b - 12 <= y <= d + 12 for a, b, c, d in holes + nodes)), None))"
                   "(room.S.editor, list(app._holes or []), [tuple(dpg.get_item_state(f'gnode_{n}').get('rect_min', (0, 0))) + "
                   "tuple(dpg.get_item_state(f'gnode_{n}').get('rect_max', (0, 0))) for n in app.gp.graph.nodes])")


# --- the checks ---------------------------------------------------------------------------------
def check_frame(app, bad):
    """The focus frame round the 3-D view over the graph: its border drawn on every side."""
    app.send([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"py": "room.fold_panel(app)"}, {"action": "select_none"}], 2.0)
    x, y, w, h = app.rect("pip_win")
    app.click(x + w // 2, y + h // 2 + 20)
    app.hold(x - 150, y + 40)
    time.sleep(0.5)
    if app.ask("app.focus") != "cube_win":
        bad.append("a click in the 3-D view over the graph did not give it the focus")
    # the frame's border: a strip 2 px wide just outside each side of the view (its own window used to cut it away)
    quads = app.ask("[(list(c['p1']), list(c['p3'])) for c in (dpg.get_item_configuration(k) for k in app.frames.quads['focus']) if c['show']]")
    near = lambda a, b: abs(a - b) <= 3
    found = {"top": any(near(p[1][1], y) and p[1][0] - p[0][0] > 20 for p in quads),
             "bottom": any(near(p[0][1], y + h) and p[1][0] - p[0][0] > 20 for p in quads),
             "left": any(near(p[1][0], x) and p[1][1] - p[0][1] > 20 for p in quads),
             "right": any(near(p[0][0], x + w) and p[1][1] - p[0][1] > 20 for p in quads)}
    missing = [s for s, ok in found.items() if not ok]
    if missing:
        bad.append(f"the focus frame round the 3-D view has no border on its {', '.join(missing)}")


def check_add_menu(app, bad):
    """The add menu describes the node under the pointer beside its list; the pointer goes across to it, the wheel
    scrolls it, and it stays the node last under the pointer."""
    spot = empty_spot(app)
    app.click(*spot, right=True)
    app.hold(spot[0] + 30, spot[1] + 30)
    rows = app.ask("[(dpg.get_item_user_data(k), [int(v) for v in dpg.get_item_rect_min(k)], [int(v) for v in dpg.get_item_rect_size(k)]) "
                   "for k in app.gp._menu_entries() if dpg.is_item_visible(k) and dpg.get_item_rect_size(k)[1] > 0]")
    if not rows:
        bad.append("the add menu did not come up at a right click on the empty canvas"); return
    t, (rx, ry), (rw, rh) = rows[len(rows) // 2]
    app.move([(rx + 20, ry + rh // 2)], 0.3)
    time.sleep(0.5)
    if app.ask("(dpg.is_item_shown('graph_menu'), app.gp._add_preview)") != (True, t):
        bad.append(f"hovering {t} in the add menu did not describe it (or closed the menu)")
    if app.ask("dpg.is_item_shown('props_fly')"):
        bad.append("the add menu's hover brought the properties up over the canvas")
    menu = app.rect("graph_menu")
    col_x = rx + rw + (menu[0] + menu[2] - (rx + rw)) // 2       # the column: the menu's right part
    app.move([(rx + rw - 5, ry + rh // 2), (col_x, ry + rh // 2)], 0.5)
    time.sleep(0.3)
    if app.ask("(dpg.is_item_shown('graph_menu'), app.gp._add_preview, dpg.is_item_hovered('graph_desc'))") != (True, t, True):
        bad.append("the pointer taken across to the description lost it (or the menu)")
    # a long one scrolls: the longest described, into the column's box, then the wheel
    app.send([{"py": "app.gp.describe_type(max(app.gp.lib, key=lambda k: len(app.gp.lib[k].get('doc', '')) + "
                     "sum(len(p.get('doc', '')) for s in ('inputs', 'outputs', 'params') for p in app.gp.lib[k].get(s, []))))"}], 0.5)
    if app.ask("dpg.get_y_scroll_max('graph_desc')") > 0:
        app.wheel(col_x, ry + rh // 2, -3)
        if not app.ask("dpg.get_y_scroll('graph_desc')") > 0:
            bad.append("the wheel over the add menu's description did not scroll it")
    vw = app.ask("dpg.get_viewport_client_width()")
    if menu[0] + menu[2] > vw:
        bad.append(f"the add menu runs off the window: {menu}, the window {vw} wide")
    app.send([{"py": "app.gp._hide_menus()"}], 0.3)


def check_properties(app, bad, panel):
    """After a click on a node whose properties come up over the canvas, clicks on them keep them and the selection."""
    app.send([{"graph_open": "box_fire.json"}, {"py": f"room.{panel}(app)"}, {"action": "select_none"}, {"graph_selected": []}], 1.5)
    r = node_rect(app, 1)
    app.click(r[0] + r[2] // 2, r[1] + 6)
    time.sleep(0.6)
    fly = app.rect("props_fly")
    if not fly or app.ask("app.gp._selected()") != [1]:
        bad.append(f"({panel}) a click on node 1's title did not select it and bring its properties up"); return
    fx, fy, fw, fh = fly
    for name, (x, y) in (("its caption", (fx + fw // 2, fy + 12)), ("its left edge", (fx + 3, fy + fh // 2)),
                         ("below its last line", (fx + fw // 2, fy + fh - 5))):
        app.click(x, y)
        time.sleep(0.4)
        if app.ask("(dpg.is_item_shown('props_fly'), app.gp._selected())") != (True, [1]):
            bad.append(f"({panel}) a click on the properties' {name} lost them or the selection"); return


def check_props_field(app, bad):
    """A plain node's properties (a Noise's: its settings and its free input): a drag on a number there changes it,
    the node's own field follows, the node stays selected and its properties up."""
    app.send([{"graph_open": "box_fire.json"}, {"py": "room.fold_panel(app)"}, {"action": "select_none"},
              {"graph_zoom": 1.0}, {"graph_selected": []}], 1.5)
    at = title_point(app, 12)
    if not at:
        bad.append("the Noise (12) is not in sight on the canvas"); return
    app.click(*at)
    time.sleep(0.6)
    w = app.ask("next((w for w in app.gp._props_widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (12, 'scale')), None)")
    r = app.rect(w) if w else None
    if app.ask("(dpg.is_item_shown('props_fly'), app.gp._selected())") != (True, [12]) or not r:
        bad.append("a click on the Noise did not select it and bring its properties up, its scale among them"); return
    before = app.ask("app.gp.graph.nodes[12]['inputs'].get('scale')")
    x, y = r[0] + r[2] // 2, r[1] + r[3] // 2
    app.down(x, y)
    app.move([(x + 10, y), (x + 40, y), (x + 70, y)], 0.5)
    app.up()
    time.sleep(0.3)
    after = app.ask("app.gp.graph.nodes[12]['inputs'].get('scale')")
    twins = app.ask("[dpg.get_value(w) for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (12, 'scale')]")
    if after == before:
        bad.append(f"a drag on the Noise's scale in its properties did not change it ({before})")
    elif any(abs(v - after) > 1e-6 for v in twins) or len(twins) != 2:
        bad.append(f"the Noise's scale dragged to {after} in its properties: its fields show {twins}")
    if app.ask("(dpg.is_item_shown('props_fly'), app.gp._selected())") != (True, [12]):
        bad.append("a drag on a number in the properties lost them or the selection")
    app.send([{"graph_undo": True}], 0.5)


def check_zoom_select(app, bad):
    """A node clicked, the canvas zoomed, another node clicked: the second is the selection. (The click after a
    zoom used to leave nothing selected: the zoom carries the selection on by key, and ending that ended the
    selection imnodes had just made.)"""
    app.send([{"graph_open": "box_fire.json"}, {"py": "room.fold_panel(app)"}, {"action": "select_none"},
              {"graph_zoom": 1.0}, {"graph_selected": []}], 1.5)
    first = next((n for n in (2, 3, 1, 4) if title_point(app, n)), None)
    if first is None:
        bad.append("no control node in sight on the canvas"); return
    app.click(*title_point(app, first))
    time.sleep(0.4)
    if app.ask("app.gp._selected()") != [first]:
        bad.append(f"a click on node {first}'s title did not select it"); return
    zoom = app.ask("app.gp.zoom")
    app.wheel(*empty_spot(app), -1)
    time.sleep(0.5)
    if app.ask(f"abs(app.gp.zoom - {zoom}) > 0.01") is not True:
        bad.append("the wheel over the canvas did not zoom it"); return
    second = next((n for n in app.ask("sorted(app.gp.graph.nodes)") if n != first and title_point(app, n)), None)
    app.click(*title_point(app, second))
    time.sleep(0.4)
    got = app.ask("app.gp._selected()")
    if got != [second]:
        bad.append(f"after a click on node {first} and a zoom, a click on node {second} left the selection {got}")
    app.send([{"graph_zoom": 1.0}], 0.3)


FRAME_REC = "\n".join([
    "orig = app.poll_glow",
    "app._frame_rec = []",
    "def rec():",
    "    orig()",
    "    q = [(c['p1'], c['p3']) for c in (dpg.get_item_configuration(k) for k in app.frames.quads['focus']) if c['show']]",
    "    box = (min(a[0] for a, b in q), min(a[1] for a, b in q), max(b[0] for a, b in q), max(b[1] for a, b in q)) if q else None",
    "    app._frame_rec.append((room.S.pip_rect, box))",
    "app.poll_glow = rec", ""])


def check_frame_follows(app, bad):
    """The 3-D view over the graph moved by its ::: towards another corner, then sized by its grip: in every frame
    its focus frame is drawn where the view is that frame - the same margin round it, never a frame behind."""
    app.send([{"graph_open": "box_fire.json"}, {"py": "room.fold_panel(app)"}, {"action": "select_none"}, {"graph_selected": []},
              {"py": "(room.pip(app).__setitem__('corner', 'br'), app.request_layout())"}], 1.5)
    x, y, w, h = app.rect("pip_win")
    app.click(x + w // 2, y + h // 2 + 30)
    time.sleep(0.4)
    if app.ask("app.focus") != "cube_win":
        bad.append("a click in the 3-D view over the graph did not give it the focus"); return
    app.send([{"py": f"exec({FRAME_REC!r}, {{'app': app, 'dpg': dpg, 'room': room}})"}], 0.3)
    try:
        for what, tag in (("moved", "grip_cube_win"), ("sized", "pip_size")):
            g = app.rect(tag)
            if not g:
                bad.append(f"the 3-D view's {tag} is not shown"); continue
            gx, gy = g[0] + g[2] // 2, g[1] + g[3] // 2
            c = app.ask("room.pip(app)['corner']")
            # moved: towards the far corner; sized: away from the corner it is anchored in
            dx, dy = ((-420, -220) if what == "moved" else (-150 if c[1] == "r" else 150, 150 if c[0] == "t" else -150))
            app.hold(gx, gy)
            app.send([{"py": "app._frame_rec.clear()"}], 0.1)
            app.down(gx, gy)
            app.move([(gx + dx * k // 30, gy + dy * k // 30) for k in range(1, 31)], 1.2)
            app.up()
            time.sleep(0.4)
            rows = app.ask("[(tuple(round(v) for v in r), tuple(round(v) for v in b)) for r, b in app._frame_rec if r and b]") or []
            margins = {(r[0] - b[0], r[1] - b[1], b[2] - (r[0] + r[2]), b[3] - (r[1] + r[3])) for r, b in rows}
            places = {r for r, b in rows}
            if len(places) < 5:
                bad.append(f"the 3-D view {what} by its {tag} went through {len(places)} places (a drag not taken?)")
            elif len(margins) != 1:
                bad.append(f"the 3-D view {what}: its focus frame off its place in some frames - margins {sorted(margins)[:4]}")
    finally:
        app.send([{"py": "app.__dict__.pop('poll_glow', None)"},
                  {"py": "(room.pip(app).__setitem__('corner', 'br'), app.request_layout())"}], 0.8)


def check_pip_drag(app, bad):
    """After a click on a node, a drag in the 3-D view over the graph turns it and keeps the selection."""
    r = node_rect(app, 1)
    app.send([{"action": "select_none"}], 0.3)
    app.click(r[0] + r[2] // 2, r[1] + 6)
    x, y, w, h = app.rect("pip_win")
    yaw = app.ask("app.yaw")
    cx, cy = x + w // 2, y + h // 2 + 30
    app.down(cx, cy)
    app.move([(cx + 30, cy), (cx + 90, cy + 8)], 0.4)
    app.up()
    if app.ask("abs(app.yaw - {:.6f}) > 0.05".format(yaw)) is not True:
        bad.append("a drag in the 3-D view over the graph after a click on a node did not turn it")
    if app.ask("app.gp._selected()") != [1]:
        bad.append("a drag in the 3-D view over the graph lost the node's selection")


def check_painter(app, bad):
    """The Bitmap painter: a drag from the canvas across it paints nothing; a press on a cell paints it."""
    app.send([{"graph_open": "question_block.json"}, {"py": "room.fold_panel(app)"}, {"graph_select": [29]}], 1.5)
    ed = app.ask("(lambda e: [int(v) for v in dpg.get_item_state(e['tag'])['rect_min']] + [e['cell']])(app.gp._bitmap_ed)")
    fly = app.rect("props_fly")
    if not ed or not fly:
        bad.append("the Bitmap's painter did not come up in its properties"); return
    gx, gy, cell = ed
    row = "app.gp.graph.nodes[29]['params'].get('rows', '').split('/')[7]"
    before = app.ask(row)
    y = gy + 7 * cell + cell // 2
    app.down(fly[0] - 120, y)
    app.move([(fly[0] - 20, y), (gx + 3 * cell, y), (gx + 9 * cell, y), (fly[0] - 60, y + 30)], 0.8)
    app.up()
    if app.ask(row) != before:
        bad.append("a drag from the canvas across the Bitmap's painter painted it")
    app.send([{"action": "select_none"}, {"graph_select": [29]}], 1.0)
    app.send([{"py": "app.gp._bitmap_ed.__setitem__('pen', '5')"}], 0.3)
    ed = app.ask("(lambda e: [int(v) for v in dpg.get_item_state(e['tag'])['rect_min']] + [e['cell']])(app.gp._bitmap_ed)")
    gx, gy, cell = ed                                         # the properties made again: where the painter is now
    y = gy + 7 * cell + cell // 2
    app.hold(gx + cell + cell // 2, y, settle=0.4)
    app.click(gx + cell + cell // 2, y)                       # the row's second cell, a 1: painted a 5
    time.sleep(0.4)
    got = app.ask(row) or ".."
    if got[1] != "5":
        hov = app.ask("dpg.is_item_hovered(app.gp._bitmap_ed['tag'])")
        bad.append(f"a press on the Bitmap painter's cell did not paint it: row {got}, the painter hovered {hov}")


def main():
    if os.name != "nt":
        print("pointer: Windows only (it posts mouse messages to the studio's window)")
        return 0
    if not scratch.DIR:
        print("pointer: no private scratch folder to drive the app through (native/scratch.py)")
        return 1
    app, bad = App(), []
    try:
        app.start()
        for name, fn in (("frame", lambda: check_frame(app, bad)), ("add menu", lambda: check_add_menu(app, bad)),
                         ("properties, panel open", lambda: check_properties(app, bad, "open_panel")),
                         ("properties, panel folded", lambda: check_properties(app, bad, "fold_panel")),
                         ("3-D view", lambda: check_pip_drag(app, bad)), ("painter", lambda: check_painter(app, bad)),
                         ("a plain node's properties", lambda: check_props_field(app, bad)),
                         ("a click after a zoom", lambda: check_zoom_select(app, bad)),
                         ("the frame round a moving 3-D view", lambda: check_frame_follows(app, bad))):
            n = len(bad)
            try:
                fn()
            except Exception as e:
                bad.append(f"{name}: {type(e).__name__}: {e}")
            print(("ok  " if len(bad) == n else "FAIL") + " " + name)
    finally:
        app.stop()
    text = open(LOG, encoding="utf-8", errors="replace").read()
    bad += [l for l in text.splitlines() if "Traceback" in l or l.startswith("command {")]
    for b in bad:
        print("  " + b)
    print(f"pointer: {'ok' if not bad else 'FAILED'} (log {LOG})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
