"""The graph gets the room (the critique's C1): in the graph layout the
canvas takes the window.

- The side panel folds to a rail of its sections' icons at the window's
  edge. A click opens the panel beside the rail at that section, or, open,
  goes to it (the section in view lit on the rail); the rail's top button
  opens and folds it.
- The 3-D view floats in a corner of the canvas. Its ::: drags it to
  another corner, its handle (or Ctrl+wheel over it) sizes it, and its tuck
  button puts it away to a tab. While tucked it is not drawn.
- The properties come up over the canvas only when the selected node has
  settings a node cannot hold (text over several lines, a file, a curve, a
  bitmap), or while the add menu describes a node. N pins them open; their
  x closes them until another node is selected.
- The help that was a band above the graph follows the pointer.

Anything over the canvas is a top-level window of its own. Child windows
of the root that overlap take the pointer in the order they were first
drawn, not the order they are drawn in: the node editor's canvas, made the
first time the graph is shown, would have taken it from a 3-D view laid
over it. A top-level window stays over the root (the root never comes to
the front), and the gradient frames and viewport overlays keep off it
(App.compute_holes), except the 3-D view's own overlays, which are drawn
on it. The 3-D view (cube_win) and the properties (props_win) move into
those windows while the graph is up, and back among the panes after.

Off (View > Graph: canvas first), the arrangement is as it was: the 3-D
view, the properties and the panel sit beside the graph as panes.
"""
import time

import dearpygui.dearpygui as dpg

from native.typeface import px

RAIL_W = px(44)         # the rail's width (px: at the interface size)
RAIL_GAP = px(6)        # between the rail and the panel open beside it
MARGIN = px(10)         # between what floats and the canvas's edges
PIP_MIN = px(200)       # the 3-D view's smallest side
PIP_DEFAULT = 320       # at 100% (the prefs keep it so: a size change keeps its proportion)
PIP_CAP = px(26)        # its caption row: the pane's CAP_H less the pane's side padding (the picture stays square)
PROPS_W = px(380)
TIP_DELAY = 0.35        # s the pointer rests before the help comes up
CORNERS = ("br", "bl", "tr", "tl")

ICON = {"effect": "fx", "segments": "segments", "geometry": "cube", "colours": "swatches",
        "parameters": "sliders", "audio": "audio", "live": "mic"}
TIP = {"effect": "EFFECT: the project, the effect and its palette",
       "segments": "SEGMENTS: the strip's segments, their bounds and blends",
       "geometry": "GEOMETRY: the shape the LEDs are on",
       "colours": "COLOURS: the segment's three colours",
       "parameters": "PARAMETERS: the effect's sliders and checkboxes",
       "audio": "AUDIO: the synthetic audio's levels",
       "live": "LIVE: audio from a line in, a microphone or a WAV file"}


class _State:
    def __init__(self):
        self.pip_drag = None     # ("move", mouse0, rect0) or ("size", mouse0, size0)
        self.pip_rect = None     # (x, y, w, h) on screen: the 3-D view in its corner
        self.editor = None       # (x, y, w, h): the canvas, as last laid out
        self.tip_text = ""
        self.tip_since = 0.0
        self.tip_shown = False
        self.props_key = None    # the selection the properties are for
        self.props_dismissed = None
        self.sec_scroll = None   # [section, frames waited]: the panel opened at a section
        self.rail_sig = None     # what the rail was built from
        self.rail_here = None    # the section lit on the rail: the one in view in the open panel
        self.was_folded = None   # the panel's last state, and where the canvas started then
        self.main_x = None
        self.test_at = None      # the tests' pointer for the help at the pointer: (x, y), or None


S = _State()


# --- the switches ------------------------------------------------------------------------
def on(app):
    return bool(app.prefs.get("graph_room", True))


def active(app):
    """Canvas first, in force: the graph up, the controls shown."""
    return app.layout == "graph" and app.ui and on(app)


def rail(app):
    """The rail shown: canvas first, and the panel alone in its column once
    the 3-D view and the properties are off it (a frame docked beside it
    keeps the panel as it was)."""
    if not (active(app) and app.side):
        return False
    for col in app.arrangement:
        if "side" in col:
            return [s for s in col if app.slot_shown(s)] == ["side"]
    return False


def folded(app):
    """The panel folded away: the rail alone in its column."""
    return rail(app) and not app.prefs.get("graph_panel_open")


def side_px(app):
    """The panel's column's width: the rail's while folded, the rail and
    the dock side by side while open, the dock's without the rail - the
    panel's width, or the frame's whose tab is in front (dock.py)."""
    from native import dock
    if not rail(app):
        return dock.width(app)
    return RAIL_W if folded(app) else dock.width(app) + RAIL_GAP + RAIL_W


def _outer_right(app):
    """Whether the panel's column is right of the graph (the rail then goes
    on its right, at the window's edge)."""
    cols = app.arrangement
    si = next((i for i, c in enumerate(cols) if "side" in c), 0)
    mi = next((i for i, c in enumerate(cols) if "main" in c), 0)
    return si > mi


def pip(app):
    """The 3-D view's corner, size and whether it is tucked away (prefs)."""
    p = app.prefs.get("pip")
    if not isinstance(p, dict):
        p = app.prefs["pip"] = {}
    if p.get("corner") not in CORNERS:
        p["corner"] = "br"
    p.setdefault("size", PIP_DEFAULT)
    p.setdefault("tucked", False)
    return p


def pip_on(app):
    """The 3-D view in its corner, drawn: canvas first, not tucked, not popped out."""
    return active(app) and not pip(app)["tucked"] and not app.popouts.is_out("cube")


def tucked(app):
    return active(app) and bool(pip(app)["tucked"])


def _save(app):
    from native.project import save_prefs
    save_prefs(app.prefs)


def set_on(app, v):
    app.prefs["graph_room"] = bool(v)
    _save(app)
    app.request_layout()
    app.gp.status("canvas first: the 3-D view over the graph, the panel a rail" if v
                  else "panes: the 3-D view, the properties and the panel beside the graph")


def set_tucked(app, v):
    pip(app)["tucked"] = bool(v)
    _save(app)
    app.request_layout()


def open_panel(app, key=None):
    """The panel beside the graph, at a section (opened if it was folded) -
    in front of the dock's frames."""
    from native import dock
    app.prefs["graph_panel_open"] = True
    if key and dock.active(app) != "side":
        dock.state(app)["active"] = "side"
    _save(app)
    if key:
        if key in app.sec_closed:
            app.sec_set(key, True)
        S.sec_scroll = [key, 0]
    app.request_layout()


def fold_panel(app):
    app.prefs["graph_panel_open"] = False
    _save(app)
    app.request_layout()


def toggle_panel(app):
    if not rail(app):
        return
    fold_panel(app) if app.prefs.get("graph_panel_open") else open_panel(app)


def pin_props(app, v):
    """N while canvas first: the properties kept open (the selection's, or
    what to do), or back to showing only when a node needs them."""
    app.props_pinned = bool(v)
    S.props_dismissed = None
    app.gp.status("the properties stay open (N again: only when a node needs them)" if v
                  else "the properties come up when a node needs them")


def dismiss_props(app):
    S.props_dismissed = S.props_key
    app.props_pinned = False
    if dpg.does_item_exist("props_fly"):
        dpg.hide_item("props_fly")


# --- the build ---------------------------------------------------------------------------------
def build(app):
    """The rail, the windows over the canvas and their controls. After the
    panes: the rail is one of them, the controls go into two."""
    from native import chrome
    from native.icons import texture
    with dpg.child_window(tag="rail_win", parent="panes_row", width=RAIL_W, height=px(400), show=False,
                          no_scrollbar=True, no_scroll_with_mouse=True):
        pass
    fill_rail(app)
    # the 3-D view over the canvas; cube_win moves in while the graph is up
    with dpg.window(tag="pip_win", show=False, no_title_bar=True, no_resize=True, no_move=True, no_collapse=True,
                    no_scrollbar=True, no_scroll_with_mouse=True, no_focus_on_appearing=True, no_saved_settings=True,
                    width=PIP_DEFAULT, height=PIP_DEFAULT + PIP_CAP):
        pass
    dpg.add_image_button(texture("tuck", px(14)), tag="pip_tuck", parent="cube_win", width=px(14), height=px(14), show=False,
                         callback=lambda: set_tucked(app, True))
    chrome.tip("tuck the 3-D view away to a tab in its corner (it is not drawn while it is away)", item="pip_tuck")
    dpg.add_image_button(texture("resize", px(14)), tag="pip_size", parent="cube_win", width=px(14), height=px(14), show=False)
    chrome.tip("drag to size the 3-D view (or Ctrl+wheel over it); its ::: drags it to another corner", item="pip_size")
    with dpg.window(tag="pip_tab", show=False, no_title_bar=True, no_resize=True, no_move=True, no_collapse=True,
                    no_scrollbar=True, no_focus_on_appearing=True, no_saved_settings=True, width=px(104), height=px(36)):
        dpg.add_button(label="3-D view", tag="pip_tab_btn", width=px(88), callback=lambda: set_tucked(app, False))
        chrome.tip("the 3-D view back in its corner of the graph")
    # the properties over the canvas; props_win moves in
    with dpg.window(tag="props_fly", show=False, no_title_bar=True, no_resize=True, no_move=True, no_collapse=True,
                    no_scrollbar=True, no_scroll_with_mouse=True, no_focus_on_appearing=True, no_saved_settings=True,
                    width=PROPS_W, height=px(240)):
        pass
    dpg.add_image_button(texture("close", px(14)), tag="props_close", parent="props_win", width=px(14), height=px(14), show=False,
                         callback=lambda: dismiss_props(app))
    chrome.tip("close until another node is selected (N keeps it open)", item="props_close")
    # the help at the pointer
    with dpg.window(tag="help_tip", show=False, no_title_bar=True, no_resize=True, no_move=True, no_collapse=True,
                    no_scrollbar=True, no_focus_on_appearing=True, no_saved_settings=True, autosize=True):
        dpg.add_text("", tag="help_tip_text", wrap=px(420))
    app.props_pinned = False


def _rail_sig(app):
    from native import chrome, dock
    return (tuple(app.sec_order), tuple(chrome.TEXT), folded(app), tuple(dock.tabs(app)))


def fill_rail(app):
    """The rail's buttons: open or fold the panel, then each section in the
    panel's order."""
    from native import chrome
    from native.icons import texture
    if not dpg.does_item_exist("rail_win"):
        return
    S.rail_sig, S.rail_here = _rail_sig(app), None
    dpg.delete_item("rail_win", children_only=True)
    dpg.add_spacer(height=px(2), parent="rail_win")
    shut = folded(app)
    b = dpg.add_image_button(texture("rail_open" if shut else "rail_fold", px(20)), tag="rail_open", parent="rail_win",
                             width=px(20), height=px(20), tint_color=chrome.TEXT, callback=lambda: toggle_panel(app))
    chrome.tip("open the side panel beside the graph (the rail stays: its icons go to the sections)" if shut
               else "fold the panel away: the graph gets the room back", item=b)
    dpg.add_separator(parent="rail_win")
    for key in app.sec_order:
        b = dpg.add_image_button(texture(ICON.get(key, "gear"), px(20)), tag=f"rail_{key}", parent="rail_win", width=px(20),
                                 height=px(20), tint_color=chrome.TEXT, user_data=key,
                                 callback=lambda s, a, u: open_panel(app, u))
        chrome.tip(TIP.get(key, key.upper()) + (" - opens the panel there" if shut else " - goes to it"), item=b)
    # the frames in the dock: a click brings the one to the front of the drawer (C8)
    from native import dock
    if dock.tabs(app):
        dpg.add_separator(parent="rail_win")
        for slot in dock.tabs(app):
            b = dpg.add_image_button(texture(dock.ICONS.get(slot, "gear"), px(20)), tag=f"rail_frame_{slot}", parent="rail_win",
                                     width=px(20), height=px(20), tint_color=chrome.TEXT, user_data=slot,
                                     callback=lambda s, a, u: dock.activate(app, u))
            chrome.tip(f"{dock.NAMES.get(slot, slot)} - in the dock: opens it beside the rail", item=b)


# --- where things go ------------------------------------------------------------------------------
def parent_is(item, parent):
    """Whether `item` sits in `parent` (Dear PyGui names a parent by its
    alias when it has one, else by its number)."""
    ids = lambda t: dpg.get_alias_id(t) if isinstance(t, str) else t
    return dpg.does_item_exist(item) and ids(dpg.get_item_parent(item)) == ids(parent)


def _move(item, parent, before=0):
    if dpg.does_item_exist(item) and not parent_is(item, parent):
        dpg.move_item(item, parent=parent, before=before)


def prepare(app):
    """Before the panes are placed: the 3-D view and the properties in
    their windows over the canvas while it is canvas first, else back among
    the panes, in their order (the 3-D view, the properties, the panel)."""
    if active(app):
        _move("props_win", "props_fly")
        _move("cube_win", "pip_win")
    else:
        _move("props_win", "panes_row", before="side_win")
        _move("cube_win", "panes_row", before="props_win")


def _editor_top():
    """How far down the graph pane its canvas starts: under the row with
    the graph's name (the band that was under it gone)."""
    st = dpg.get_item_state("graph_file") if dpg.does_item_exist("graph_file") else {}
    pos, size = st.get("pos"), st.get("rect_size")
    if pos and size and size[1] > 0:
        return int(pos[1] + size[1] + 6)                  # the theme's item spacing under the row
    return px(38)


def editor_rect(main):
    """The canvas in the graph pane at (x, y, w, h): the pane's padding
    (the theme's 10) off the sides and the bottom."""
    x, y, w, h = main
    top = _editor_top()
    return (x + px(10), y + top, max(1, w - px(20)), max(1, h - top - px(10)))


def _pip_side(app, ed):
    ex, ey, ew, eh = ed
    most = max(PIP_MIN, min(ew * 0.6, eh - PIP_CAP - 2 * MARGIN))
    return int(max(PIP_MIN, min(px(pip(app)["size"]), most))), int(most)


def _set_side(app, s):
    """The 3-D view's side, s px on the screen, into the prefs at 100%."""
    from native import typeface
    pip(app)["size"] = int(round(s / typeface.scale()))


def pip_geometry(app, main):
    """Where the 3-D view goes in its corner of the canvas: (x, y, w, h)."""
    ed = editor_rect(main)
    ex, ey, ew, eh = ed
    s, _ = _pip_side(app, ed)
    w, h = s, s + PIP_CAP
    c = pip(app)["corner"]
    x = ex + ew - w - MARGIN if c[1] == "r" else ex + MARGIN
    y = ey + eh - h - MARGIN if c[0] == "b" else ey + MARGIN
    return (int(x), int(y), int(w), int(h))


def place_side(app, rect):
    """The panel's column at (x, y, w, h): the rail at its outer edge (the
    window's), the panel, open, between it and the graph."""
    from native import dock
    x, y, w, h = rect
    right = _outer_right(app)
    rx = x
    if not folded(app):
        pw = max(1, w - RAIL_W - RAIL_GAP)
        panel_x = x if right else x + RAIL_W + RAIL_GAP
        rx = x + pw + RAIL_GAP if right else x
        dock.place(app, (panel_x, y, pw, h))             # the panel, or the frame whose tab is in front
    else:
        dock.hide(app)
    dpg.configure_item("rail_win", width=RAIL_W, height=h)
    dpg.set_item_pos("rail_win", [rx, y])


MINIMAP = {"br": "BottomLeft", "bl": "BottomRight", "tr": "BottomRight", "tl": "BottomRight"}


def place(app, rects):
    """After the panes: the windows over the canvas, their controls, the
    help band, the minimap out of the 3-D view's corner, the rail."""
    from native import chrome
    main = rects.get("main")
    if not active(app) or not main:
        for t in ("pip_win", "pip_tab", "props_fly", "help_tip", "pip_tuck", "pip_size", "props_close"):
            if dpg.does_item_exist(t):
                dpg.hide_item(t)
        for t in ("graph_help_box", "help_split"):
            if dpg.does_item_exist(t):
                dpg.show_item(t)
        if dpg.does_item_exist("node_editor"):
            dpg.configure_item("node_editor", minimap_location=dpg.mvNodeMiniMap_Location_BottomRight)
        S.editor = S.pip_rect = None
        S.tip_shown = False
        S.was_folded, S.main_x = None, None
        return
    S.editor = editor_rect(main)
    for t in ("graph_help_box", "help_split"):              # the help follows the pointer instead
        if dpg.does_item_exist(t):
            dpg.hide_item(t)
    p = pip(app)
    if pip_on(app):
        x, y, w, h = pip_geometry(app, main)
        S.pip_rect = (x, y, w, h)
        dpg.configure_item("pip_win", width=w, height=h, show=True)
        dpg.set_item_pos("pip_win", [x, y])
        dpg.configure_item("cube_win", width=w, height=h)
        dpg.set_item_pos("cube_win", [0, 0])
        for t, dx in (("pip_size", 92), ("pip_tuck", 66)):
            dpg.configure_item(t, show=True, tint_color=chrome.TEXT)
            dpg.set_item_pos(t, [w - px(dx), px(8)])
        if dpg.does_item_exist("grip_cube_win"):
            dpg.set_item_pos("grip_cube_win", [w - px(40), px(8)])
        if dpg.does_item_exist("cube_cap") and not app.ab:
            dpg.set_value("cube_cap", "3-D  drag: turn  wheel: zoom" if w >= px(330) else "3-D")
        dpg.hide_item("pip_tab")
    else:
        S.pip_rect = None
        for t in ("pip_win", "pip_size", "pip_tuck"):
            dpg.hide_item(t)
        if p["tucked"] and not app.popouts.is_out("cube"):
            ex, ey, ew, eh = S.editor
            c = p["corner"]
            tx = ex + ew - px(104) - MARGIN if c[1] == "r" else ex + MARGIN
            ty = ey + eh - px(36) - MARGIN if c[0] == "b" else ey + MARGIN
            dpg.configure_item("pip_tab", show=True)
            dpg.set_item_pos("pip_tab", [int(tx), int(ty)])
        else:
            dpg.hide_item("pip_tab")
    if dpg.does_item_exist("node_editor"):
        loc = MINIMAP[p["corner"]] if pip_on(app) else "BottomRight"
        dpg.configure_item("node_editor", minimap_location=getattr(dpg, "mvNodeMiniMap_Location_" + loc))
    if S.rail_sig != _rail_sig(app):
        fill_rail(app)
    # the props: shown by poll() as the selection wants; here, their controls
    if dpg.does_item_exist("grip_props_win"):
        dpg.hide_item("grip_props_win")
    # The panel opened or folded on the canvas's left moves the canvas's
    # left edge: the view moves back as far, so no node moves on the screen.
    f = folded(app)
    if S.was_folded is not None and S.was_folded != f and S.main_x is not None and main[0] != S.main_x:
        app.gp.shift_view(main[0] - S.main_x)
    S.was_folded, S.main_x = f, main[0]


# --- every frame ---------------------------------------------------------------------------------
def _props_need(app):
    """(whether the properties should be up, the selection they are for)."""
    gp = app.gp
    if gp._add_preview is not None:
        return True, ("preview", gp._add_preview)
    sel = gp._selected() if gp.graph else []
    key = (gp.file, sel[0]) if sel else None
    if getattr(app, "props_pinned", False):
        return True, key
    if not sel:
        return False, None
    n = gp.graph.nodes.get(sel[0])
    if not n:
        return False, None
    if n["type"] == "Bitmap":
        return True, key
    d = gp.graph.node_def(n)
    for q in d["params"]:
        v = str(n["params"].get(q["name"], q.get("default", "")))
        if q["type"] in ("curve", "file") or (q["type"] == "text" and (q.get("lines") or len(v) > 40)):
            return True, key
    return False, key


def _props_content_h():
    """How tall the properties' content is: the lowest of its items."""
    low = 0
    for kid in dpg.get_item_children("graph_props", 1) or []:
        st = dpg.get_item_state(kid)
        pos, size = st.get("pos"), st.get("rect_size")
        if pos and size:
            low = max(low, pos[1] + size[1])
    return low


def _poll_props(app):
    need, key = _props_need(app)
    if key != S.props_key:
        S.props_key = key
        if key != S.props_dismissed:
            S.props_dismissed = None
    show = need and (key is None or key != S.props_dismissed) and S.editor is not None
    if not show:
        if dpg.is_item_shown("props_fly"):
            dpg.hide_item("props_fly")
        return
    ex, ey, ew, eh = S.editor
    c = pip(app)["corner"] if pip_on(app) else None
    right = c != "tr"                                   # the top right, unless the 3-D view is there
    x = ex + ew - PROPS_W - MARGIN if right else ex + MARGIN
    y = ey + MARGIN
    room = eh - 2 * MARGIN
    if c and S.pip_rect and c[0] == "b" and (c[1] == "r") == right:
        room -= S.pip_rect[3] + MARGIN                  # above the 3-D view on the same side
    h = int(max(px(120), min(room, _props_content_h() + px(52))))
    w = int(min(PROPS_W, ew - 2 * MARGIN))
    if not dpg.is_item_shown("props_fly"):
        dpg.configure_item("props_win", show=True)
        dpg.show_item("props_fly")
    dpg.configure_item("props_fly", width=w, height=h)
    dpg.set_item_pos("props_fly", [int(x), int(y)])
    dpg.configure_item("props_win", width=w, height=h)
    dpg.set_item_pos("props_win", [0, 0])
    from native import chrome
    dpg.configure_item("props_close", show=True, tint_color=chrome.TEXT)
    dpg.set_item_pos("props_close", [w - px(30), px(8)])


def _poll_tip(app):
    text = dpg.get_value("graph_help") if dpg.does_item_exist("graph_help") else ""
    menus = any(dpg.does_item_exist(t) and dpg.is_item_shown(t) for t in ("graph_menu", "graph_ctx", "expr_win"))
    over = dpg.does_item_exist("node_editor") and dpg.is_item_hovered("node_editor")
    at = S.test_at                                      # the tests have no pointer: where it would be
    over = over or at is not None
    now = time.time()
    if not (text and over and not menus and S.pip_drag is None):
        if S.tip_shown:
            dpg.hide_item("help_tip")
        S.tip_shown, S.tip_text = False, ""
        return
    if text != S.tip_text:
        S.tip_text = text
        dpg.set_value("help_tip_text", text)
        if not S.tip_shown:
            S.tip_since = now
    if not S.tip_shown and now - S.tip_since < TIP_DELAY:
        return
    mx, my = at if at is not None else dpg.get_mouse_pos(local=False)
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    w, h = dpg.get_item_rect_size("help_tip") or (0, 0)
    x, y = mx + px(18), my + px(22)
    if w and x + w > vw - 4:
        x = mx - w - px(12)                                # near the right edge: on the pointer's left
    if h and y + h > vh - 4:
        y = my - h - px(12)                                # near the bottom: above it
    dpg.set_item_pos("help_tip", [int(max(0, x)), int(max(0, y))])
    if not S.tip_shown:
        dpg.show_item("help_tip")
        S.tip_shown = True


def _poll_sec_scroll():
    if not S.sec_scroll or not dpg.is_item_shown("side_win"):
        return
    key, n = S.sec_scroll
    if n < 2:
        S.sec_scroll[1] += 1                           # the panel's first frames: its sections laid out
        return
    pos = dpg.get_item_state(f"sec_{key}").get("pos") if dpg.does_item_exist(f"sec_{key}") else None
    if pos:
        dpg.set_y_scroll("side_win", max(0.0, float(pos[1]) - 6.0))
    S.sec_scroll = None


def _poll_rail_here(app):
    """The open panel's section in view, lit on the rail."""
    from native import chrome
    if not rail(app) or folded(app) or not dpg.is_item_shown("side_win"):
        return
    top = dpg.get_y_scroll("side_win") + 40
    here = None
    for key in app.sec_order:
        pos = dpg.get_item_state(f"sec_{key}").get("pos") if dpg.does_item_exist(f"sec_{key}") else None
        if pos and pos[1] <= top:
            here = key
    if here == S.rail_here:
        return
    S.rail_here = here
    for key in app.sec_order:
        if dpg.does_item_exist(f"rail_{key}"):
            dpg.configure_item(f"rail_{key}", tint_color=chrome.ACCENT if key == here else chrome.TEXT)


def poll(app):
    if not active(app):
        if S.tip_shown and dpg.does_item_exist("help_tip"):
            dpg.hide_item("help_tip")
            S.tip_shown = False
        if dpg.does_item_exist("props_fly") and dpg.is_item_shown("props_fly"):
            dpg.hide_item("props_fly")
        return
    _poll_props(app)
    _poll_tip(app)
    _poll_sec_scroll()
    _poll_rail_here(app)


# --- the pointer on the 3-D view's controls ---------------------------------------------------------
def press(app):
    """A press on the 3-D view's ::: (to move it) or its size handle. True
    when it was one of those."""
    if not pip_on(app) or not dpg.is_item_shown("pip_win") or S.pip_rect is None:
        return False
    mp = tuple(dpg.get_mouse_pos(local=False))
    if dpg.does_item_exist("grip_cube_win") and dpg.is_item_hovered("grip_cube_win"):
        S.pip_drag = ("move", mp, S.pip_rect)
        return True
    if dpg.is_item_hovered("pip_size"):
        S.pip_drag = ("size", mp, px(pip(app)["size"]))
        return True
    return False


def drag(app):
    if not S.pip_drag or S.editor is None:
        return False
    kind, (mx0, my0), v0 = S.pip_drag
    mx, my = dpg.get_mouse_pos(local=False)
    ex, ey, ew, eh = S.editor
    if kind == "move":
        x, y, w, h = v0
        nx = min(max(ex, x + mx - mx0), ex + ew - w)
        ny = min(max(ey, y + my - my0), ey + eh - h)
        dpg.set_item_pos("pip_win", [int(nx), int(ny)])
        S.pip_rect = (nx, ny, w, h)
        return True
    c = pip(app)["corner"]
    dx = (mx0 - mx) if c[1] == "r" else (mx - mx0)     # away from the corner it is anchored in: larger
    dy = (my0 - my) if c[0] == "b" else (my - my0)
    _, most = _pip_side(app, S.editor)
    s = int(max(PIP_MIN, min(most, v0 + (dx + dy) / 2.0)))
    if abs(s - px(pip(app)["size"])) >= px(6):
        _set_side(app, s)
        app.request_layout()
    return True


def release(app):
    if not S.pip_drag:
        return False
    kind = S.pip_drag[0]
    S.pip_drag = None
    if kind == "move" and S.editor and S.pip_rect:
        x, y, w, h = S.pip_rect
        ex, ey, ew, eh = S.editor
        pip(app)["corner"] = ("b" if y + h / 2 > ey + eh / 2 else "t") + ("r" if x + w / 2 > ex + ew / 2 else "l")
    _save(app)
    app.request_layout()
    return True


def wheel(app, delta):
    """Ctrl+wheel over the 3-D view in its corner: its size."""
    if not pip_on(app) or S.editor is None or not dpg.is_item_hovered("pip_win"):
        return False
    if not (dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)):
        return False
    _, most = _pip_side(app, S.editor)
    _set_side(app, int(max(PIP_MIN, min(most, px(pip(app)["size"]) + px(40) * (1 if delta > 0 else -1)))))
    _save(app)
    app.request_layout()
    return True


def cube_hole(app):
    """The 3-D view's window as compute_holes lists it, or None: its own
    overlays (the shape editor's rings, reference wireframes) are drawn on
    it, not kept off it."""
    if not pip_on(app) or S.pip_rect is None:
        return None
    x, y, w, h = S.pip_rect
    return (x - 2, y - 2, x + w + 3, y + h + 3)
