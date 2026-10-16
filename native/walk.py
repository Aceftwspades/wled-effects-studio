"""The walkers the tests drive through the remote control (native/remote.py): every menu item, every frame's
buttons, every toolbar action and context-menu row called the way Dear PyGui would, and the UI reference
written from what is on screen. A button or action that would end, restart or launch something goes in
SKIP_BUTTON / SKIP_BUTTON_TAGS / SKIP_ACTION, or the walk presses it."""
import os
import re
import sys
import threading

import dearpygui.dearpygui as dpg

from native import device_ui


def _call(item, label):
    """A menu item's or row's callback, the way Dear PyGui would call it."""
    import inspect
    cfg = dpg.get_item_configuration(item)
    cb, ud = cfg.get("callback"), cfg.get("user_data")
    if cb is None:
        return "no callback"
    try:
        n = len(inspect.signature(cb).parameters)
    except (TypeError, ValueError):
        n = 3
    args = [item, dpg.get_value(item) if dpg.get_item_type(item).endswith("::mvMenuItem") else None, ud][:n]
    try:
        cb(*args)
        return "ok"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"FAIL {type(e).__name__}: {e}"


SKIP_MENU = ("Quit", "Record 15 s GIF", "Record 15 s video", "Fullscreen", "Check for updates...",     # ends the app, a 15 s recording, flips the window
             "Open the project folder", "Open the build folder",
             "Open code in external editor",                # these hand a path to the desktop: another program opens
             "Send the graph as a script", "Send the current effect's settings", "Send the shape (ledmap + positions)",
             "Send the ledmap only", "Scan the network for devices", "Stream the sim to the device",
             "Import the device's ledmap", "Read the device's wiring")   # these reach a real device: not a test's to do (a read replaces the wiring)


def walk_menus(app, skip=()):
    """Every item of the menu bar, invoked; a dialog it opens is closed
    again. Prints one line per item."""
    skip = set(SKIP_MENU) | set(skip)
    windows_before = {w for w in dpg.get_windows() if dpg.is_item_shown(w)}
    # the paths first, then each found afresh: an item's callback may
    # rebuild a submenu (opening a graph refills the Open lists)
    paths = []
    def collect(menu, path):
        for k in dpg.get_item_children(menu, 1) or []:
            t = dpg.get_item_type(k)
            lbl = dpg.get_item_configuration(k).get("label", "")
            if t.endswith("::mvMenu"):
                collect(k, path + [lbl])
            elif t.endswith("::mvMenuItem"):
                paths.append(path + [lbl])
    for m in dpg.get_item_children("menubar", 1) or []:
        collect(m, [dpg.get_item_configuration(m).get("label", "")])
    def find(path):
        node = "menubar"
        for lbl in path:
            nxt = next((k for k in dpg.get_item_children(node, 1) or [] if dpg.get_item_configuration(k).get("label", "") == lbl), None)
            if nxt is None:
                return None
            node = nxt
        return node
    for path in paths:
        label = path[-1]
        if label in skip:
            print(f"menu  skip  {' > '.join(path)}"); continue
        k = find(path)
        if k is None:
            print(f"menu  gone  {' > '.join(path)}"); continue
        if dpg.get_item_configuration(k).get("check"):
            r1 = _call(k, label)                           # a check item: on, then back
            k2 = find(path)
            if k2 is not None:
                dpg.set_value(k2, not dpg.get_value(k2)); r2 = _call(k2, label)
            else:
                r2 = "ok"
            r = r1 if r1 != "ok" else r2
        else:
            r = _call(k, label)
        print(f"menu  {r:5s} {' > '.join(path)}")
        for w in dpg.get_windows():
            if dpg.does_item_exist(w) and dpg.is_item_shown(w) and w not in windows_before and dpg.get_item_alias(w) != "root":
                dpg.hide_item(w)                           # a dialog it opened
        for tag in ("graph_menu", "graph_ctx", "confirm_dialog", "name_dialog", "palette_win"):
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                dpg.hide_item(tag)
    if app.ab:
        app.stop_ab()
    if app.sweep:
        app.stop_sweep()
    if getattr(app, "rec", None) is not None:
        app.rec = None
    print("walk  done  menu")                            # the harness counts these: a walk the app did not finish has none


UIREF_START = "<!-- uiref start"
UIREF_END = "<!-- uiref end -->"
# buttons whose label is what they show now: named in the reference for what they are
UIREF_NAMED = {"msg_problems": ("N problems", "the problems that stay until they are fixed - a click opens the log at them"),
               "msg_line": ("the latest message", "short, the whole of it on hover; a click opens the log")}


def _tip_after(kids, j):
    """The tooltip made right after item j of `kids`, as text, or ""."""
    if j + 1 < len(kids) and dpg.get_item_type(kids[j + 1]).endswith("::mvTooltip"):
        for t in dpg.get_item_children(kids[j + 1], 1) or []:
            if dpg.get_item_type(t).endswith("::mvText") and dpg.get_value(t):
                return str(dpg.get_value(t)).replace("\n", " ").strip()
    return ""


def write_uiref(app, path=None):
    """GUIDE.md's reference section - every menu item with its key, every
    key action, every button of every frame, window and pane with its
    tooltip - written between its markers from the running app, so the
    guide names what the app has (tests/test_docs.py checks that it does).
    Returns the path written."""
    from native.keys import ACTIONS
    from native import paths as _paths
    lines = ["## Reference: every menu, key and button", "",
             "<!-- uiref start: written by `python tests/make_uiref.py` from the running app - change the app, not this -->",
             "", "### Menus", ""]

    # menus whose rows are the user's files, devices or the node library: named, their rows not listed
    dynamic = {"menu_open_graph": "the project's graphs", "menu_open_code": "the project's code effects",
               "menu_open_project": "the projects", "menu_recent_project": "the projects opened lately",
               "menu_active_device": "the devices known", "menu_add": "every node (see NODES.md)"}

    def menu(item, path):
        kids = dpg.get_item_children(item, 1) or []
        for j, k in enumerate(kids):
            t = dpg.get_item_type(k)
            cfg = dpg.get_item_configuration(k)
            lbl = cfg.get("label", "")
            if t.endswith("::mvMenu"):
                alias = dpg.get_item_alias(k) or ""
                if alias in dynamic:
                    lines.append(f"- **{' › '.join(path)}** › {lbl} › … {dynamic[alias]}"); continue
                menu(k, path + [lbl])
            elif t.endswith("::mvMenuItem"):
                key = cfg.get("shortcut") or ""
                tip = _tip_after(kids, j)
                lines.append(f"- **{' › '.join(path)}** › {lbl}" + (f" `{key}`" if key else "") + (f" — {tip}" if tip else ""))
    for m in dpg.get_item_children("menubar", 1) or []:
        menu(m, [dpg.get_item_configuration(m).get("label", "")])
    lines += ["", "### Keys", "", "Every action, its key (Settings › Keyboard shortcuts rebinds them) and where it works.", "",
              "| Key | Does | Where |", "|---|---|---|"]
    for action, label, default, ctx in ACTIONS:
        key = app.keys.label(action) or "—"
        lines.append(f"| `{key}` | {label} | {({'global': 'anywhere', 'view': 'over the 3-D view'}).get(ctx, 'in the graph')} |")
    lines += ["", "### Buttons", "", "Every button, with what its tooltip says.", ""]

    def buttons(item, out):
        kids = dpg.get_item_children(item, 1) or []
        for j, k in enumerate(kids):
            t = dpg.get_item_type(k)
            if t.endswith(("::mvButton", "::mvImageButton")):
                lbl = (dpg.get_item_configuration(k).get("label", "") or "").replace("\n", " ").strip()
                tip = _tip_after(kids, j)
                if (dpg.get_item_alias(k) or "") in UIREF_NAMED:
                    lbl, tip = UIREF_NAMED[dpg.get_item_alias(k)]
                elif not lbl and tip:                           # an icon button: named by its tooltip's first clause
                    lbl = re.split(r"[:(]|  ", tip)[0].strip()[:40]
                elif not lbl:
                    lbl = dpg.get_item_alias(k) or ""
                if lbl and lbl not in (":::",):
                    out.append((lbl, tip if tip != lbl else ""))
            elif t.endswith(("::mvMenuItem", "::mvSelectable", "::mvTooltip")):
                pass
            else:
                buttons(k, out)
        return out
    roots = [(device_ui.FRAMES[w][1] + " frame", device_ui.FRAMES[w][0]) for w in device_ui.FRAMES]
    roots += [("Keyboard shortcuts", "keys_win"), ("Appearance", "appearance_win"),
              ("History", "history_win"), ("Changes since a version", "history_diff_win"), ("Undo history", "undo_win"), ("About", "about_win"), ("Usermods and features", "usermods_win"),
              ("Update", "update_win"), ("A WLED checkout", "wled_dialog"), ("Report a problem", "report_win"),
              ("Map lights by camera", "map_win"),
              ("Message log", "log_win"), ("The panes and the toolbar", "root")]
    seen = set()
    for title, tag in roots:
        if not dpg.does_item_exist(tag):
            continue
        rows = []
        for lbl, tip in buttons(tag, []):
            if (title, lbl) in seen:
                continue
            seen.add((title, lbl)); rows.append((lbl, tip))
        if rows:
            lines.append(f"**{title}**: " + "; ".join(f"`{lbl}`" + (f" — {tip}" if tip else "") for lbl, tip in rows))
            lines.append("")
    lines.append(UIREF_END)
    block = "\n".join(lines) + "\n"
    path = path or os.path.join(_paths.RES, "GUIDE.md")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    i, j = text.find("## Reference: every menu, key and button"), text.find(UIREF_END)
    if i >= 0 and j >= 0:
        text = text[:i] + block + text[j + len(UIREF_END) + 1:]
    else:
        text = text.rstrip("\n") + "\n\n" + block
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    return path


def process_stats(app):
    """What a soak watches: the resident set in MB, Dear PyGui's item
    count, the engine's and the app's frame times, threads."""
    rss = 0.0
    try:
        if os.name == "nt":
            import ctypes, ctypes.wintypes as wt

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.windll.kernel32
            fn = k32.K32GetProcessMemoryInfo
            fn.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]; fn.restype = wt.BOOL
            k32.GetCurrentProcess.restype = wt.HANDLE            # a pseudo-handle of -1: without this it overflows an int
            fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            rss = pmc.WorkingSetSize / 1e6
        else:
            import resource
            ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss = ru / 1e6 if sys.platform == "darwin" else ru / 1e3
    except Exception:
        pass
    return {"rss_mb": round(rss, 1), "items": len(dpg.get_all_items()), "effect_ms": round(app.frame_ms, 2),
            "app_ms": round(getattr(app, "loop_ms", 0.0), 2), "threads": threading.active_count(),
            "effect": app.eng.names[app.eng.idx] if app.eng.names else "", "geometry": app.project.geometry.kind}


# buttons a walk leaves alone: a flash or a firmware build, a render or a preview that takes minutes,
# a clone or a download from the network, a restart, a program opened on the desktop, a key capture,
# the clipboard (the log's copy: what the user had copied stays)
SKIP_BUTTON_TAGS = ("flash_start", "shape_prev_go", "wled_go", "wled_restart", "app_ui_restart", "rec_btn", "log_copy",
                    "map_cam_find", "map_calib", "map_live",  # the webcam: a camera turned on is not a test's to do
                    "geom_read_wiring",                   # a real device's wiring read: the smoke reads the fake's
                    "flash_ports_refresh",                # the serial ports: a board plugged in is not a test's to probe
                    "history_switch")                     # its rows would put the walked project's settings back: the smoke does, in its own
SKIP_BUTTON = ("Clone", "Download", "Get the WLED fork", "Restart the studio", "Restart now", "Open in the browser", "Open the build folder", "Reboot the device",
               "Open the folder", "Scan the network", "Import the device's", "Generate previews", "Remake the thumbnails",
               "Render GIF", "Render video", "press a key", "Release page", "Pop out", "Quit", "Usermods...",
               "Build sheet", "Install PlatformIO", "Back up now")


def _close_dialogs(keep=()):
    """Every window a click opened, hidden again; file dialogs too."""
    for w in dpg.get_windows():
        alias = dpg.get_item_alias(w) or ""
        if alias in ("root", "") or alias in keep or not dpg.is_item_shown(w):
            continue
        if alias.endswith(("_win", "_dialog", "_menu")) or dpg.get_item_configuration(w).get("modal"):
            dpg.hide_item(w)
    for w in dpg.get_all_items():
        if dpg.get_item_type(w).endswith("::mvFileDialog") and dpg.is_item_shown(w):
            dpg.hide_item(w)


def walk_frame(app, which):
    """Every button of a frame (device_ui.FRAMES), a window by tag, or
    "root" (the panes), clicked in turn - found afresh each time, since a
    click may rebuild the rows - and whatever it opened closed again.
    Prints one line per button; the walker reads them for FAILs."""
    if which in device_ui.FRAMES:
        root = device_ui.FRAMES[which][0]
        device_ui.show(app, which)
    else:
        root = which
        if root != "root" and dpg.does_item_exist(root):
            dpg.show_item(root)
    if not dpg.does_item_exist(root):
        print(f"frame FAIL  {which}: no such item"); return

    def name(k, after):
        """A button's label; an icon button's alias, else its tooltip's
        first line (the tooltip is the sibling made right after it)."""
        lbl = dpg.get_item_configuration(k).get("label", "") or dpg.get_item_alias(k) or ""
        if not lbl and after is not None and dpg.get_item_type(after).endswith("::mvTooltip"):
            for t in dpg.get_item_children(after, 1) or []:
                if dpg.get_item_type(t).endswith("::mvText") and dpg.get_value(t):
                    lbl = str(dpg.get_value(t)).split("  ")[0].split("\n")[0][:40]; break
        return lbl.replace("\n", " ") or "?"

    def buttons(item, path):
        out = []
        kids = dpg.get_item_children(item, 1) or []
        for j, k in enumerate(kids):
            t = dpg.get_item_type(k)
            if t.endswith(("::mvButton", "::mvImageButton")):
                out.append((k, path + [name(k, kids[j + 1] if j + 1 < len(kids) else None)]))
            elif t.endswith(("::mvTab", "::mvCollapsingHeader", "::mvTreeNode", "::mvMenu")):
                out += buttons(k, path + [dpg.get_item_configuration(k).get("label", "")])
            elif t.endswith(("::mvMenuItem", "::mvSelectable")):
                pass                                          # menus have their own walk
            else:
                out += buttons(k, path)
        return out

    def keyed(item):
        seen, out = {}, []
        for k, p in buttons(item, []):
            key = tuple(p); n = seen.get(key, 0); seen[key] = n + 1
            out.append(((key, n), k))
        return out
    plan = [key for key, _ in keyed(root)]
    print(f"frame {which}: {len(plan)} button(s)")
    for key, n in plan:
        label = key[-1]
        shown = " > ".join(key) + (f" [{n + 1}]" if n else "")
        k = next((i for kk, i in keyed(root) if kk == (key, n)), None)
        if k is None:
            print(f"frame gone  {which} > {shown}"); continue
        alias = dpg.get_item_alias(k) or ""
        if alias in SKIP_BUTTON_TAGS or any(label.startswith(sk) for sk in SKIP_BUTTON):
            print(f"frame skip  {which} > {shown}"); continue
        if not dpg.get_item_configuration(k).get("enabled", True):
            print(f"frame off   {which} > {shown}"); continue
        r = _call(k, label)
        print(f"frame {r:5s} {which} > {shown}")
        _close_dialogs(keep=(root,))
        if which in device_ui.FRAMES and not dpg.is_item_shown(root):
            device_ui.show(app, which)                        # a close button: the frame back for the rest
    print(f"walk  done  frame {which}")


# actions a walk leaves alone: the window's shape, a 15 s recording, another program, the firmware, the app's end
SKIP_ACTION = ("fullscreen", "record", "record_video", "external", "flash", "shortcuts", "palette")
# actions that flip something: run twice, so the app is as it was
TOGGLE_ACTION = ("view_net", "view_cube", "view_both", "pane_code", "pane_graph", "presentation", "side_panel", "props_pane",
                 "play_pause", "live", "compare", "sweep", "stream", "focus_mode", "wire_light", "minimap", "unlit_dots", "view_floor", "snap", "hide_pins",
                 "collapse", "mute",
                 "enter_sub", "stop_preview")


def walk_actions(app, skip=()):
    """Every keymap action by name, in the keymap's order; a toggle run
    again to put it back; a change to the graph undone. One line each."""
    import json
    from native.keys import ACTIONS
    skip = set(SKIP_ACTION) | set(skip)
    gp = app.gp
    for name, label, _, ctx in ACTIONS:
        if name in skip:
            print(f"act   skip  {name}"); continue
        before = json.dumps(gp.graph.to_json(), sort_keys=True) if gp.graph else None
        print(f"act   ...   {name}", flush=True)                # first: a crash's last line names the action that did it
        try:
            app.run_action(name)
            if name in TOGGLE_ACTION:
                app.run_action(name)
            r = "ok"
        except Exception as e:
            import traceback
            traceback.print_exc()
            r = f"FAIL {type(e).__name__}: {e}"
        print(f"act   {r:5s} {name} - {label}")
        _close_dialogs()
        if gp.graph is not None and before is not None and json.dumps(gp.graph.to_json(), sort_keys=True) != before:
            gp.undo()
    gp._hide_menus()
    print("walk  done  act")


def walk_ctx(app, kind, nid, pin=None):
    """Every row of a node's or a pin's context menu: the menu is refilled,
    the row found by its label and called; a change to the graph is undone
    before the next. Prints one line per row."""
    import json
    gp = app.gp
    if nid == "auto":                                # the first node that has the pin: a walk that outlives the graph's numbering
        side = "inputs" if kind == "in" else "outputs"
        nid = next((k for k in sorted(gp.graph.nodes)
                    if any(x["name"] == pin for x in gp.graph.node_def(gp.graph.nodes[k]).get(side, []))), None)
        if nid is None:
            print(f"ctx   FAIL  no node has the {kind} pin {pin!r}"); return
    nid = int(nid)
    gp._ctx = (kind, nid, pin)
    gp._fill_ctx_menu()
    def rows(item, path):
        out = []
        for k in dpg.get_item_children(item, 1) or []:
            t = dpg.get_item_type(k)
            if t.endswith("::mvSelectable"):
                out.append((path + [dpg.get_item_configuration(k).get("label", "")], k))
            elif t.endswith(("::mvTreeNode", "::mvGroup")):
                out += rows(k, path + ([dpg.get_item_configuration(k).get("label", "")] if t.endswith("::mvTreeNode") else []))
            elif t.endswith(("::mvButton", "::mvColorButton")):
                out.append((path + [dpg.get_item_configuration(k).get("label", "") or "swatch"], k))
        return out
    labels = [p for p, _ in rows("graph_ctx", [])]
    for path in labels:
        if nid not in gp.graph.nodes:
            print(f"ctx   skip  {' > '.join(path)} (the node is gone)"); continue
        gp._ctx = (kind, nid, pin)
        try:
            gp._fill_ctx_menu()
        except Exception as e:
            print(f"ctx   FAIL  refill: {e}"); break
        k = next((i for p, i in rows("graph_ctx", []) if p == path), None)
        if k is None:
            print(f"ctx   gone  {' > '.join(path)}"); continue
        before = json.dumps(gp.graph.to_json(), sort_keys=True)
        r = _call(k, path[-1])
        print(f"ctx   {r:5s} {' > '.join(path)}")
        for tag in ("confirm_dialog", "name_dialog", "where_win"):
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                dpg.hide_item(tag)
        if gp.graph is None:
            print("ctx   FAIL  the graph closed"); break
        if json.dumps(gp.graph.to_json(), sort_keys=True) != before:
            gp.undo()
    gp._hide_menus()
    print(f"walk  done  ctx {kind}")
