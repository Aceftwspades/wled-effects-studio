"""
WLED Effects Studio - the native front end.

    python -m native.app

Started life as the Cube FX Simulator's window: the same engine and the same
numbers as the headless tool, plus controls and live audio. It is now an
editor as well - a project holds a geometry and the effects being written for
it, the code pane compiles an effect into the engine in about a second and
swaps it in without leaving the window, and the views draw whatever the
geometry is: a strip, a matrix, the cube, a sphere, a coordinate list.

Two things here are deliberate and easy to undo by accident:

  * The clock advances in a FIXED 23 ms step, paced against the wall clock. It
    does not take the real frame interval. The browser build tied the step to
    the frame and so ran 1.38x fast on a 60 Hz monitor and 3.3x on a 144 Hz one,
    which made every timing judgement wrong by a factor that depended on the
    machine. Fixed steps also keep runs reproducible, which is what lets the
    measurement numbers mean anything.

"""
import os
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import num
from native import render_video, render_fseq, modulate, mixer, vj, clock
from native import typeface
from native import form
from native import dock
from native import messages

import queue
import threading

from native.engine import Engine, stats
from native.synth import Synth
from native.geometry import Geometry, KINDS
from native.project import default_project, list_projects, pref_num, load_prefs, save_prefs
from native.graph_ui import GraphPanel, build_panel
from native import chrome, glow, device_ui, shape_ui, midi_ui, phone_ui, pads_ui, bank_ui, reader_ui, room, weight, view3d, tasks
from native import look
from native import video_ui
from native.theme import THEME_PRESETS, theme_colors, theme_is_light, minimap_colours
from native.features import Features
from native.recorder import Recorder, GIF_DIR
from native.edit_build import EditBuild
from native import paths as _paths
from native.popout import Popouts
from native.dropfiles import DropFiles
from native.codeedit import CodeEditor
from native.keys import Keymap
from native import render
from native.apiref import API
from native import scratch
from native.remote import SHOT_DIR, SHOT_REQ, SHOT_PNG, CMD_FILE, REMOTE, service_capture, service_command
import sys
from native import oops
from native import frametime
from native.app_layout import AppLayout
from native.app_input import AppInput
from native.app_code import AppCode
from native.app_projects import AppProjects

STEP = 23
SIDE_W = px(340)        # control column


SECTION = (90, 169, 230)          # section titles in the side panel
_LUT = (np.arange(256, dtype=np.float32) / 255.0)   # uint8 -> float texture channel, by lookup


def apply_theme(prefs=None):
    """A dark theme close to the browser build's, so switching between the two
    is not jarring. Default Dear PyGui is grey-blue and tightly packed; the
    views want to sit on near-black or the LED colours read wrong against it.
    Settings > Appearance picks a preset and edits its seven colours."""
    cols = theme_colors(prefs)
    light = theme_is_light(prefs)
    bg, panel, frame, line, text, dim, accent = (cols[k] for k in ("bg", "panel", "frame", "line", "text", "dim", "accent"))
    soft    = accent + (60,)
    lift = (lambda c, k: tuple(min(255, v + k) for v in c)) if not light else (lambda c, k: tuple(max(0, v - k) for v in c))
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvAll):
            # Flat: no bevels, no bright borders. A control is a slightly
            # lighter slab on the panel; hovering lifts it, pressing or
            # switching it on paints it the accent.
            for t, c in ((dpg.mvThemeCol_WindowBg, bg),
                         (dpg.mvThemeCol_ChildBg, panel),
                         (dpg.mvThemeCol_PopupBg, lift(panel, 3)),
                         (dpg.mvThemeCol_MenuBarBg, bg),
                         (dpg.mvThemeCol_Border, line),
                         (dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0)),
                         (dpg.mvThemeCol_Text, text),
                         (dpg.mvThemeCol_TextDisabled, dim),
                         (dpg.mvThemeCol_TextSelectedBg, soft),
                         (dpg.mvThemeCol_FrameBg, frame),
                         (dpg.mvThemeCol_FrameBgHovered, lift(frame, 9)),
                         (dpg.mvThemeCol_FrameBgActive, lift(frame, 18)),
                         (dpg.mvThemeCol_Button, lift(panel, 13)),
                         (dpg.mvThemeCol_ButtonHovered, lift(panel, 26)),
                         (dpg.mvThemeCol_ButtonActive, accent),
                         (dpg.mvThemeCol_SliderGrab, accent),
                         (dpg.mvThemeCol_SliderGrabActive, lift(accent, 40)),
                         (dpg.mvThemeCol_CheckMark, accent),
                         (dpg.mvThemeCol_Header, lift(panel, 14)),
                         (dpg.mvThemeCol_HeaderHovered, lift(panel, 26)),
                         (dpg.mvThemeCol_HeaderActive, lift(panel, 40)),
                         (dpg.mvThemeCol_TitleBg, panel),
                         (dpg.mvThemeCol_TitleBgActive, lift(panel, 6)),
                         (dpg.mvThemeCol_ScrollbarBg, (0, 0, 0, 0)),
                         (dpg.mvThemeCol_ScrollbarGrab, lift(panel, 24)),
                         (dpg.mvThemeCol_ScrollbarGrabHovered, lift(panel, 40)),
                         (dpg.mvThemeCol_ScrollbarGrabActive, accent),
                         (dpg.mvThemeCol_Separator, line),
                         (dpg.mvThemeCol_ResizeGrip, (0, 0, 0, 0)),
                         (dpg.mvThemeCol_NavHighlight, soft),
                         (dpg.mvThemeCol_PlotHistogram, accent),
                         (dpg.mvThemeCol_ModalWindowDimBg, (0, 0, 0, 140))):
                dpg.add_theme_color(t, c, category=dpg.mvThemeCat_Core)
            for t, v in ((dpg.mvStyleVar_FrameRounding, px(3)),
                         (dpg.mvStyleVar_ChildRounding, px(5)),
                         (dpg.mvStyleVar_GrabRounding, px(3)),
                         (dpg.mvStyleVar_WindowRounding, px(5)),
                         (dpg.mvStyleVar_PopupRounding, px(4)),
                         (dpg.mvStyleVar_ScrollbarRounding, px(4)),
                         (dpg.mvStyleVar_ScrollbarSize, px(10)),
                         (dpg.mvStyleVar_GrabMinSize, px(10)),
                         (dpg.mvStyleVar_FrameBorderSize, 0),
                         (dpg.mvStyleVar_WindowBorderSize, 0),
                         (dpg.mvStyleVar_ChildBorderSize, 1),
                         (dpg.mvStyleVar_PopupBorderSize, 1)):
                dpg.add_theme_style(t, v, category=dpg.mvThemeCat_Core)
            for t, a, b in ((dpg.mvStyleVar_WindowPadding, px(10), px(10)),
                            (dpg.mvStyleVar_FramePadding, px(7), px(4)),
                            (dpg.mvStyleVar_ItemSpacing, px(8), px(6)),
                            (dpg.mvStyleVar_ItemInnerSpacing, px(6), px(4)),
                            (dpg.mvStyleVar_CellPadding, px(6), px(3))):
                dpg.add_theme_style(t, a, b, category=dpg.mvThemeCat_Core)
            # The node editor: the same slabs, a quieter grid, the accent
            # for a box-select; a selected node's own frame is the gradient
            # (glow.py), so its title only lifts a little.
            for t, c in ((dpg.mvNodeCol_GridBackground, lift(bg, 3)),
                         (dpg.mvNodeCol_GridLine, lift(bg, 13)),
                         (dpg.mvNodeCol_NodeBackground, frame),
                         (dpg.mvNodeCol_NodeBackgroundHovered, lift(frame, 6)),
                         (dpg.mvNodeCol_NodeBackgroundSelected, lift(frame, 10)),
                         (dpg.mvNodeCol_NodeOutline, lift(frame, 18)),
                         (dpg.mvNodeCol_TitleBar, lift(frame, 12)),
                         (dpg.mvNodeCol_TitleBarHovered, lift(frame, 24)),
                         (dpg.mvNodeCol_TitleBarSelected, lift(frame, 36)),
                         (dpg.mvNodeCol_BoxSelector, accent + (30,)),
                         (dpg.mvNodeCol_BoxSelectorOutline, accent + (180,))):
                dpg.add_theme_color(t, c, category=dpg.mvThemeCat_Nodes)
            # kept by graph_ui (one copy of it: this module runs as __main__ too), which sets them in place -
            # faint until the pointer comes to the minimap
            from native import graph_ui as _gu
            _gu.MINIMAP_ITEMS.clear()
            for t, c in minimap_colours(prefs):
                _gu.MINIMAP_ITEMS[t] = dpg.add_theme_color(t, c, category=dpg.mvThemeCat_Nodes)
        # Disabled: Dear PyGui draws a disabled control exactly as an enabled
        # one unless a component says otherwise - a greyed Send looked live.
        # The slab and the words fade, and hovering lifts nothing.
        off_text = dim + (150,)
        off_slab = lift(panel, 6) + (110,)
        off_frame = frame + (120,)
        for comp in (dpg.mvButton, dpg.mvImageButton, dpg.mvSelectable, dpg.mvCheckbox, dpg.mvCombo, dpg.mvRadioButton,
                     dpg.mvInputText, dpg.mvInputInt, dpg.mvInputFloat, dpg.mvInputDouble, dpg.mvSliderInt, dpg.mvSliderFloat,
                     dpg.mvDragInt, dpg.mvDragFloat, dpg.mvColorEdit):
            with dpg.theme_component(comp, enabled_state=False):
                for t, c in ((dpg.mvThemeCol_Text, off_text), (dpg.mvThemeCol_Button, off_slab),
                             (dpg.mvThemeCol_ButtonHovered, off_slab), (dpg.mvThemeCol_ButtonActive, off_slab),
                             (dpg.mvThemeCol_FrameBg, off_frame), (dpg.mvThemeCol_FrameBgHovered, off_frame),
                             (dpg.mvThemeCol_FrameBgActive, off_frame), (dpg.mvThemeCol_CheckMark, off_text),
                             (dpg.mvThemeCol_SliderGrab, off_text), (dpg.mvThemeCol_SliderGrabActive, off_text),
                             (dpg.mvThemeCol_HeaderHovered, (0, 0, 0, 0)), (dpg.mvThemeCol_HeaderActive, (0, 0, 0, 0))):
                    dpg.add_theme_color(t, c, category=dpg.mvThemeCat_Core)
    dpg.bind_theme(th)
    return th


def present_theme():
    """Everything black, nothing framed.

    Presentation mode is not the normal layout with the controls hidden - it is
    a different thing entirely. The panel backgrounds, the rounded corners, the
    borders and the padding all exist to separate a view from the controls
    beside it, and with the controls gone they are just furniture around a
    picture. A visualiser has no furniture.

    Bound globally while presenting and unbound after, so the working layout
    keeps its own look.
    """
    black = (0, 0, 0)
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvAll):
            for t in (dpg.mvThemeCol_WindowBg, dpg.mvThemeCol_ChildBg,
                      dpg.mvThemeCol_Border, dpg.mvThemeCol_BorderShadow,
                      dpg.mvThemeCol_PopupBg):
                dpg.add_theme_color(t, black, category=dpg.mvThemeCat_Core)
            for t, v in ((dpg.mvStyleVar_WindowBorderSize, 0),
                         (dpg.mvStyleVar_ChildBorderSize, 0),
                         (dpg.mvStyleVar_ChildRounding, 0),
                         (dpg.mvStyleVar_WindowRounding, 0)):
                dpg.add_theme_style(t, v, category=dpg.mvThemeCat_Core)
            for t, a, b in ((dpg.mvStyleVar_WindowPadding, 0, 0),
                            (dpg.mvStyleVar_FramePadding, 0, 0),
                            (dpg.mvStyleVar_ItemSpacing, 0, 0),
                            (dpg.mvStyleVar_CellPadding, 0, 0)):
                dpg.add_theme_style(t, a, b, category=dpg.mvThemeCat_Core)
    return th


# Built from the engine at start-up rather than listed here: the fixed set comes
# from the firmware's own JSON_palette_names, and the usermod-registered ones
# (the audio-reactive gradients) are queried from the DLL, so anything a usermod
# adds appears without this file knowing about it.
PALETTES = []


class Section:
    """A section of the side panel: a header row (an arrow that folds it,
    the title, a grip that moves it) over a body. The whole thing is one
    group, so moving the group moves the section; see App.sec_*.

        with Section(app, "geometry", "GEOMETRY"):
            ...the body...
    """

    def __init__(self, app, key, title, extras=None):
        self.app, self.key, self.title, self.extras = app, key, title, extras

    def __enter__(self):
        app, key = self.app, self.key
        dpg.add_group(tag=f"sec_{key}")
        dpg.push_container_stack(f"sec_{key}")
        shut = key in app.sec_closed
        with dpg.group(horizontal=True, tag=f"sec_{key}_hdr"):
            dpg.add_button(arrow=True, direction=dpg.mvDir_Right if shut else dpg.mvDir_Down, tag=f"sec_{key}_arrow",
                           callback=lambda: app.sec_toggle(key))
            typeface.label(dpg.add_text(self.title, color=SECTION, tag=f"sec_{key}_title"))
            dpg.add_button(label=":::", tag=f"sec_{key}_grip", width=px(30), height=px(19))
            if dpg.does_item_exist("grip_theme"):
                dpg.bind_item_theme(f"sec_{key}_grip", "grip_theme")
            with dpg.tooltip(f"sec_{key}_grip"):
                dpg.add_text("drag onto another section to move this one above or below it")
            if self.extras:
                self.extras()
        # the title folds the section too
        with dpg.item_handler_registry(tag=f"sec_{key}_h"):
            dpg.add_item_clicked_handler(callback=lambda: app.sec_toggle(key))
        dpg.bind_item_handler_registry(f"sec_{key}_title", f"sec_{key}_h")
        dpg.add_group(tag=f"sec_{key}_body", show=not shut)
        dpg.push_container_stack(f"sec_{key}_body")
        return self

    def __exit__(self, *a):
        dpg.pop_container_stack()                     # the body
        dpg.add_separator()
        dpg.pop_container_stack()                     # the section


class App(AppProjects, AppCode, AppInput, AppLayout, Features, Recorder, EditBuild):
    def __init__(self):
        self.project = default_project()
        from native.engine import ensure_library
        try:
            lib = ensure_library(self.project)          # built now when build/ is empty, rather than a traceback
        except RuntimeError as e:
            print(e); sys.exit(str(e))
        self.eng = Engine(lib)
        try:
            self.eng.set_geometry(self.project.geometry)
        except Exception as e:
            # a saved geometry the engine refuses (more pixels than it holds): the cube, said - it raised here,
            # and the studio did not open until project.json was mended by hand
            print(f"the project's geometry cannot be used ({e}): the 16-pixel cube instead")
            self.project.geometry = Geometry("cube", B=16)
            self.eng.set_geometry(self.project.geometry)
        # --- the editor ------------------------------------------------------
        self.edit_file = None       # file name in the project's effects/
        self.edit_dirty = False
        self.build_q = queue.Queue()  # worker -> main thread: BuildReport
        self.building = False
        # --- pane sizes: dragged on the splitters, remembered across runs ----
        self.prefs = load_prefs()
        render.PICTURE_GLOW = self.prefs.get("picture_glow") if self.prefs.get("picture_glow") in render.PICTURE_GLOWS else "auto"
        self.side_w = px(self.prefs["side_w"]) if self.prefs.get("side_w") else SIDE_W    # kept at 100%
        # where the panes sit: columns of rows of slots (see PRESETS), the
        # columns' shares of the width per layout mode, the rows' of a column
        self.arrangement = self._valid_arrangement(self.prefs.get("arrangement")) or [list(c) for c in self.PRESETS[0][1]]
        dock.settle(self, self.arrangement)                          # a frame among the panes is not a tab or a window too
        self.colw = {k: dict(v) for k, v in (self.prefs.get("colw") or {}).items()}
        self.rowh = dict(self.prefs.get("rowh") or {})
        self._rects = {}             # slot -> (x, y, w, h) as last laid out
        self._cols = []              # the visible columns as last laid out
        self._splitters = {}         # splitter tag -> (kind, col, row)
        self._free_w = 1             # the width the free columns share
        self._rows_h = []            # per column, the height its rows share
        self._pane_drag = None       # the slot whose grip is being dragged
        self._ghost = None           # (w, h, grab dx, dy, label) of the pane or section being dragged
        self._pane_target = None     # (slot, zone) under the pointer while dragging
        self.popouts = Popouts()     # views in windows of their own
        self._file_dialogs = None    # the file dialogs, found once for the frames' holes
        self._menus = None           # every menu, found once: an open one is a hole too
        self._glow_mouse = None      # the pointer last frame, to lead a dragged node's frame
        self._glow_rects = {}        # the selected nodes' rectangles last frame: did they move?
        self._color_edits = None     # every colour swatch and dropdown, found once (a rebuild finds them again)
        self._picker = None          # the swatch or dropdown whose popup is believed open
        self._popup_click = False    # the last click landed in such a popup
        # the side panel's sections: their order, and which are folded
        secs = self.prefs.get("sections") or {}
        self.sec_order = [k for k in (secs.get("order") or []) if k in self.SECTIONS]
        self.sec_order += [k for k in self.SECTIONS if k not in self.sec_order]
        self.sec_closed = set(k for k in (secs.get("closed") or []) if k in self.SECTIONS)
        self._sec_drag = None        # the section whose grip is being dragged
        self._sec_target = None      # (section, "above" | "below") under the pointer
        self.side = True             # the side panel shown (Ctrl+Shift+H hides it)
        self.props = bool(self.prefs.get("props_pane", True))   # the graph's properties pane (N hides it)
        self.focus = None            # the pane last clicked in: it wears the frame
        self.sweep = None            # {"key", "secs", "t0", "loop", "record"} while a slider is swept
        self.show_wiring = False     # the physical order drawn over the net
        self.pane_menus = {}         # pane tag -> its right-click menu window (chrome.build_pane_menus)
        self._wiring_items = []
        self.frames = None           # (glow.Frames) - set in build()
        self.history_frames = []     # the last seconds of net frames, for scrubbing while paused
        self.history_rgb = []        # and every LED's colour for the same frames (the point cloud draws from these)
        self.history_t = []          # and when each was kept (perf_counter), for the seconds the scrub reaches
        self.scrub = None            # an index into history_frames while paused, or None
        self.frame_ms = 0.0          # the engine's cost per frame on this machine, smoothed
        self.loop_ms = 0.0           # the whole app's, frame to frame
        self._loop_t = 0.0
        self.gpu_cube = bool(self.prefs.get("gpu_cube", True))   # the cube as textured quads, not a numpy warp
        self.gpu_net = bool(self.prefs.get("gpu_net", True))     # the net scaled by the GPU, not repeated on the CPU
        self.code_ed = None          # CodeEditor, made in build()
        self.cube_quads = None       # CubeQuads while the GPU view draws a cube
        self.point_quads = None      # PointQuads while it draws any other geometry
        self.ab = None               # a second engine, for comparing two effects side by side
        self.ab_name = None
        self.ab_before = None        # the time B's build was kept at, comparing before and after an edit
        self._ab_pokes = []          # the typed values still to go into B (features.start_ab_before)
        self._code_undo, self._code_redo, self._code_text, self._code_t = [], [], "", 0.0
        self.frames = None           # glow.Frames, once the viewport exists
        self.keys = Keymap(self.prefs)
        self._capture = None         # an action waiting for its key, in the shortcuts dialog
        self._split_drag = None      # ("a"|"b", mouse x at press, value at press) while a splitter is held
        self._watch_mtime = None     # the edit file's mtime when last read, for the watcher
        self._watch_at = 0.0
        self.build_msg = ""
        self.gp = GraphPanel(self)    # the node editor
        global PALETTES
        if not PALETTES:
            PALETTES = self.eng.palette_list()
        self.syn = Synth()
        self.live = None
        self.audio_sync = None          # the sound sent to WLEDs as audioreactive's sync (set_audio_sync)
        self.playing = True
        self.speed = 1.0                # simulated frames per real second, as a factor: 1/4 .. 4 (Playback > Speed)
        self.acc = 0.0
        self.last = time.perf_counter()
        self.yaw, self.pitch, self.dist = -0.6, 0.75, 4.6
        self.beat_flash = 0
        # WLED's segment defaults: primary amber, secondary and tertiary BLACK.
        # Faithful rather than convenient - "* Colors 1&2" fading to black is
        # what the device does before you have set a secondary, and the
        # simulator should show that rather than a prettier lie.
        self.seg_cols = [0xFFA000, 0x000000, 0x000000]
        self.layout = "both"        # both | net | cube
        # Set by anything that needs the panes resized; acted on at the TOP of
        # the next loop pass, never inside a callback. See request_layout().
        self._need_layout = True
        self.ui = True              # control column and pane captions
        self._themes = {}           # normal / present, built once in build()
        # --- recording ---------------------------------------------------
        # Frames are taken from the LIVE run rather than re-simulated. What
        # comes out is what was on the screen, including live audio and any
        # slider you moved while it ran - a re-simulation would quietly give
        # you the synthetic generator and today's defaults instead.
        self.rec = None             # list of frames while recording
        self.rec_next = 0.0         # wall-clock time of the next frame
        self.rec_left = 0.0         # seconds still to capture
        self.rec_msg = ""           # what to show under the button
        self.shot_req = False       # a PNG of the 3-D view into the project, next frame
        self._bufs = {}
        self._inputs = set()
        self._dragging = False
        self._yaw0, self._pitch0 = self.yaw, self.pitch
        # the project remembers the last effect by NAME - indices move
        idx = self.eng.names.index(self.project.selected) if self.project.selected in self.eng.names else 0
        self.eng.select(idx)

    # --- textures ------------------------------------------------------------
    def _rgba(self, key, img):
        """uint8 (h,w,3) -> flat float32 RGBA, which is what DPG wants.

        Into a buffer kept per view. Allocating a fresh (h,w,4) float32 array
        every frame for both views cost 6 ms between them - a fifth of the frame
        - and the alpha column never changes, so it is written once when the
        buffer is made and left alone thereafter.
        """
        h, w, _ = img.shape
        buf = self._bufs.get(key)
        if buf is None or buf.shape[:2] != (h, w):
            buf = np.ones((h, w, 4), np.float32)
            self._bufs[key] = buf
        np.take(_LUT, img, out=buf[..., :3])
        return buf.reshape(-1)

    def _rgba_scaled(self, key, img, k):
        """_rgba of img scaled k times, each pixel a k x k block - the same values. The lookup on the small
        picture and the blocks written by broadcasting: repeating the uint8 picture first and looking up the big
        one cost seven times as much (11 ms at 12x, the net's texture every frame)."""
        h, w, _ = img.shape
        buf = self._bufs.get(key)
        if buf is None or buf.shape[:2] != (h * k, w * k):
            buf = np.ones((h * k, w * k, 4), np.float32)
            self._bufs[key] = buf
        buf.reshape(h, k, w, k, 4)[..., :3] = np.take(_LUT, img)[:, None, :, None, :]
        return buf.reshape(-1)

    def net_image(self, eng=None):
        """The logical view: the segment as the effect sees it. A 1-D strip is
        one row, drawn tall enough to look at."""
        eng = eng or self.eng
        rgb = np.array(self.view_rgb(eng))
        if not eng.fx.get("o3"):
            # Cube mode: the gap corners are not pixels and effects skip them,
            # so without this they keep whatever flat mode last left there.
            mask = eng.lit_mask()
            if mask.shape != rgb.shape[:2]:
                # the geometry changed under us between the two reads (a
                # callback on another thread): one black frame, not a crash
                return np.zeros(rgb.shape, np.uint8)
            rgb[~mask] = 0
        if rgb.shape[0] == 1:
            rows = max(4, rgb.shape[1] // 12)
            rgb = np.repeat(rgb, rows, axis=0)
        return rgb

    def view_image(self, net, px, eng=None):
        """The 3-D view as a picture, with the look (look.py) - a
        screenshot, a GIF's or a video's frame, or the view itself where
        the GPU does not draw it."""
        eng = eng or self.eng
        lk = self.view_look()
        if not look.active(lk):
            return self._view_image(net, px, eng)
        img, room = self.view_image_room(net, px, eng)
        self._look_frame = getattr(self, "_look_frame", 0) + 1
        return look.finish(img, lk, self._look_frame, look.mean_light(self.frame_rgb(eng)) if lk["spill"] > 0 else None,
                           room=room)

    ROOM_MARK = (1, 0, 1)        # a background no LED is drawn in: where the picture still has it, the room shows

    def view_image_room(self, net, px, eng=None, bg=None):
        """The 3-D view as a picture (no look yet) and where in it the room shows - the background, round the shape
        and through its gaps: drawn on ROOM_MARK, the pixels still that colour are the room's, then given the real
        background. The look's spill goes there only: on the shape's own dark LEDs it tinted the shape."""
        eng = eng or self.eng
        img = self._view_image(net, px, eng, bg=self.ROOM_MARK)
        room = np.all(img == np.asarray(self.ROOM_MARK, np.uint8), axis=-1)
        real = bg if bg is not None else self.view_background(px)
        if isinstance(real, np.ndarray):
            img[room] = real[room]
        else:
            img[room] = np.asarray(real, np.uint8)
        return img, room

    def eye_above_floor(self):
        """The 3-D view's camera is above the floor (a reflection in it can be seen)."""
        from native.render import Cam, FLOOR_Z
        return bool(Cam(self.yaw, self.pitch, self.dist, 100, **view3d.kw(self)).eye[2] > FLOOR_Z + 0.02)

    def view_look(self):
        """The look of the 3-D view in force (Settings > Appearance, its 3-D view tab)."""
        return look.current(self.prefs)

    def _view_image(self, net, px, eng, bg=None):
        """The 3-D view: the face-warp renderer for the cube (faster, and
        exact for flat faces), the point cloud for everything else. `bg`: the picture behind it (a video's
        frame's part), else the view's background."""
        bgv = bg if bg is not None else self.view_background(px)
        g = eng.geom
        unlit, floor = self.view_extras()
        if g is not None and g.kind == "cube":
            # flat mode too: it changes how an effect draws, not where the LEDs are - the net's faces are the
            # cube's whichever way the picture was made (drawn as dots, its LEDs stood apart and cost a CPU render)
            src = net if net.shape[0] == eng.rows else self.view_rgb(eng)
            lk = self.view_look()
            if lk["glow"] > 0 or lk["diffuse"] > 0:        # the glowing or diffused LEDs, as the live view's texture has them
                k = 8                                      # finer than the live texture: no GPU smooths a picture's dots
                return render.render(look.led_texture(src, k, lk, unlit, B=eng.B), eng.B * k, px, self.yaw, self.pitch,
                                     self.dist, six=eng.six, bg=bgv, unlit=None, floor=floor,
                                     reflect=lk["reflect"], **view3d.kw(self))
            return render.render(src, eng.B, px, self.yaw, self.pitch, self.dist, six=eng.six, bg=bgv,
                                 unlit=unlit, floor=floor, reflect=lk["reflect"], **view3d.kw(self))
        rgb = self.view_rgb(eng).reshape(-1, 3)
        if g is None:
            return np.zeros((px, px, 3), np.uint8)
        lk = self.view_look()
        if eng is self.eng:
            pos = self.view_positions()
            rgb = look.diffuse_points(pos, shape_ui.view_colours(self, rgb), lk)     # a shape being built: each part its colour
            return render.render_points(pos, rgb, px, self.yaw, self.pitch, self.dist, bg=bgv,
                                        unlit=unlit, floor=floor, frame=view3d.frame(self), floor_step=view3d.floor_step(self),
                                        lk=lk, **view3d.kw(self))
        return render.render_points(g.pos, look.diffuse_points(g.pos, rgb, lk), px, self.yaw, self.pitch, self.dist,
                                    bg=bgv, unlit=unlit, floor=floor, lk=lk, **view3d.kw(self))

    def fill_stats(self, pw, factor, dev_fps):
        """The stats popover's figures, this frame (while it is open): the
        picture's measures in words (C9: engine.stats keeps the harness's
        maths), the time, the power."""
        s = stats(self.frame_rgb(), self.eng.lit_mask(flat=bool(self.eng.fx.get("o3"))))
        prof = getattr(self, "_prof_avg", None) or []
        parts = ", ".join(f"{n} {v:.1f}" for n, v in zip(("polls", "sim", "draw", "render"), prof)) if prof else ""
        how = f"measured {self.prefs['device_factor_measured'].get('date', '')}".strip() \
            if isinstance(self.prefs.get("device_factor_measured"), dict) else "estimated"
        vals = {"mean": f"{s['mean']:.1f}", "sigma": f"{s['sigma']:.1f}", "dark": f"{s['dark']:.1f}%", "sat": f"{s['sat']}",
                "effect": f"{self.frame_ms:.2f} ms a frame" if self.frame_ms > 0 else "-",
                "device": (f"~{dev_fps:.0f} fps (x{factor:.0f} slower, {how})" if dev_fps is not None else "-"),
                "app": f"{self.loop_ms:.1f} ms a frame" + (f" ({parts} ms)" if parts else ""),
                "current": (f"{pw[0] / 1000.0:.2f} A asked for, {pw[2] / 1000.0:.2f} A allowed" if pw and pw[2] else
                            (f"{pw[0] / 1000.0:.2f} A" if pw else "-")),
                "limiter": ((f"{int(pw[1] * 100)}% of the brightness" if pw[1] < 1.0 else "not needed") if pw and pw[2]
                            else "no limit set")}
        for k, v in vals.items():
            if dpg.does_item_exist(f"stat_{k}"):
                dpg.set_value(f"stat_{k}", v)
        chrome.fill_frametime()

    # the View menu's switches and what they are until changed: unlit LEDs black (an effect's own dark
    # stays dark), the shape on its floor
    VIEW_DEFAULTS = {"unlit_dots": False, "view_floor": True}

    def view_option(self, name):
        return bool(self.prefs.get(name, self.VIEW_DEFAULTS.get(name, True)))

    def view_extras(self):
        """What the 3-D view adds (View menu, C16): the colour an unlit LED
        is drawn in as a dim dot (None: black), and whether the shape stands
        on a faint floor."""
        return (render.UNLIT if self.view_option("unlit_dots") else None), self.view_option("view_floor")

    def set_view_option(self, name, on=None):
        """View > Unlit LEDs as dim dots / A floor under the shape: turned
        over (or set), kept in the prefs, the menu's check following."""
        v = (not self.view_option(name)) if on is None else bool(on)
        self.prefs[name] = v
        save_prefs(self.prefs)
        for tag in (f"menu_{name}",):
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, v)
        self.gp.status({"unlit_dots": "unlit LEDs as dim dots" if v else "unlit LEDs black",
                        "view_floor": "a floor under the shape" if v else "no floor under the shape"}.get(name, name))

    # --- audio ---------------------------------------------------------------
    def audio_push(self):
        from native import seq_audio
        src = seq_audio.show_source(self) or self.live or self.syn     # the show's audio while it plays, if it has any
        video_ui.push(self)                              # the newest video frame into the engine (the Video node)
        try:
            hit = src.push(self.eng)
            if src is not self.syn:
                self.eng.audio_peak()                   # the live sound's major peak, from its bands (the synth sets its own)
            if hasattr(src, "pcm"):
                self.eng.pcm(src.pcm())
            if hasattr(src, "chroma"):
                self.eng.chroma(*src.chroma())          # the pitch-class slot, as the device's patch gives it
        except Exception as e:                     # a device can vanish mid-run
            dpg.set_value("live_msg", f"live audio stopped: {e}")
            self.stop_live()
            hit = 0
        if hit:
            self.beat_flash = 6
            self.last_hit_at = __import__("native.clock", fromlist=["c"]).now()   # the modulators' beat (modulate.py)
        if self.audio_sync is not None:                  # the same sound out to the WLEDs listening (audio_sync.py)
            self.audio_sync.send(self.eng)
        return hit

    # AI: below section was generated by an AI
    def set_audio_sync(self, mode):
        """Audio sync out: "off", or "multicast" / "broadcast" / "unicast" (to the active device) - what the effects
        here hear, as audioreactive's sync packet, for the devices set to receive it."""
        from native import audio_sync
        if self.audio_sync is not None:
            self.audio_sync.close()
            self.audio_sync = None
        words = "off"
        if mode and mode != "off":
            try:
                self.audio_sync = audio_sync.AudioSyncSender(mode, host=self.active_host() if mode == "unicast" else None)
                words = self.audio_sync.describe()
            except (ValueError, OSError) as e:
                words = f"not sending: {e}"
                mode = "off"
        if dpg.does_item_exist("audio_sync_mode") and dpg.get_value("audio_sync_mode") != mode:
            dpg.set_value("audio_sync_mode", mode)
        if dpg.does_item_exist("audio_sync_msg"):
            dpg.set_value("audio_sync_msg", words)
        return self.audio_sync
    # AI: end

    def start_live(self):
        try:
            from native.audio import open_live
            # pair() names its field inp_<key>
            dev = dpg.get_value("live_dev") if dpg.does_item_exist("live_dev") else "system output"
            index = None
            if dev and dev != "system output":
                from native.audio import list_inputs
                for i, n in list_inputs():
                    if n == dev:
                        index = i
            self.live = open_live(gain=float(dpg.get_value("inp_live_gain")), device=index)
            dpg.set_value("live_msg", f"capturing: {self.live.name}")
            dpg.configure_item("live_btn", label="stop live audio")
        except Exception as e:
            dpg.set_value("live_msg", f"could not start: {e}")

    def start_file_audio(self, path):
        """An audio file as the audio source, looping, in place of the synth or
        a capture: a WAV as it is, MP3, FLAC, OGG, M4A... through ffmpeg."""
        try:
            from native.audio import FileAudio
            self.stop_live()
            self.live = FileAudio(path, gain=float(dpg.get_value("inp_live_gain")))
            dpg.set_value("live_msg", f"playing {self.live.name} ({self.live.seconds:.0f} s, looping)")
            dpg.configure_item("live_btn", label="stop the file")
        except Exception as e:
            dpg.set_value("live_msg", f"could not open the file: {e}")

    def stop_live(self):
        if self.live:
            try:
                self.live.close()
            except Exception:
                oops.swallowed()
        self.live = None
        dpg.configure_item("live_btn", label="use live audio")

    def toggle_live(self):
        self.stop_live() if self.live else self.start_live()

    def set_appearance(self, light=None, accent=None, preset=None, colors=None):
        """Settings > Appearance: a preset (its colours from scratch), or
        one colour changed; the theme is rebuilt and rebound, the accent
        reaches the toolbar's tints and the frames' section titles."""
        t = dict(self.prefs.get("theme") or {})
        if light is not None:
            preset = "light" if light else "dark"
        if preset is not None:
            t["preset"] = preset
            t.pop("colors", None); t.pop("accent", None)
        if accent is not None:
            colors = dict(colors or {}, accent=accent)
        if colors:
            cur = dict(t.get("colors") or {})
            cur.update({k: [int(v) for v in c[:3]] for k, c in colors.items() if k in THEME_PRESETS["dark"]})
            t["colors"] = cur
            t.pop("accent", None)
        t["light"] = theme_is_light({"theme": t})
        self.prefs["theme"] = t
        save_prefs(self.prefs)
        self._themes["normal"] = apply_theme(self.prefs)
        if self.ui:
            dpg.bind_theme(self._themes["normal"])
        cols = theme_colors(self.prefs)
        was = chrome.colours()
        chrome.ACCENT = tuple(cols["accent"]) + (255,)
        chrome.TEXT = tuple(cols["text"]) + (255,)
        chrome.DIM = tuple(cols["dim"]) + (255,)
        chrome.BG, chrome.PANEL, chrome.LINE = (tuple(cols[k]) + (255,) for k in ("bg", "panel", "line"))
        chrome.recolour_texts(was, chrome.colours())         # the lines made in the old colours
        chrome.refresh(self)
        chrome.refresh_appearance(self)
        if getattr(self, "gp", None) is not None:
            self.gp.on_theme_change()                        # the graph's own themes and drawing colours, made again
        reader_ui.on_theme_change(self)                      # the open document's headings in the new accent
        dpg.set_viewport_clear_color(list(cols["bg"]) + [255] if self.ui else [0, 0, 0, 255])

    # --- autosave: a version kept while there are unsaved edits -----------------
    AUTOSAVE_S = 20.0

    def poll_autosave(self):
        """Every AUTOSAVE_S seconds, what has CHANGED since the last time is
        kept as a version in the history (the file itself is not touched),
        so a crash or a slip loses at most those seconds. Nothing happens
        unless an edit was made in between - an edit counter says so - and
        the disk work runs on a thread; the main loop only takes the text."""
        now = time.time()
        if now - getattr(self, "_autosave_at", 0.0) < self.AUTOSAVE_S:
            return
        self._autosave_at = now
        jobs = []
        if self.edit_dirty and self.edit_file:
            n = getattr(self, "_code_edits", 0)
            if n != getattr(self, "_code_autosaved", -1):
                self._code_autosaved = n
                jobs.append(("effects", os.path.splitext(self.edit_file)[0], ".cpp", dpg.get_value("code")))
        g = self.gp
        if g.graph and g.file and g.edits != getattr(self, "_graph_autosaved", -1):
            self._graph_autosaved = g.edits
            import json
            g._sync_pos()
            jobs.append(("subgraphs" if g.cur_dir == g.sub_dir else "graphs", g.file[:-5], ".json",
                         json.dumps(g.graph.to_json(), indent=1)))
        if not jobs:
            return
        from native import history
        project = self.project

        def work():
            for kind, stem, ext, text in jobs:
                try:
                    history.keep(project, kind, stem, ext, text)
                except Exception:
                    oops.swallowed()
        threading.Thread(target=work, daemon=True).start()

    def set_gpu_net(self, on):
        self.gpu_net = bool(on)
        self.prefs["gpu_net"] = self.gpu_net
        save_prefs(self.prefs)
        self.request_layout()

    def set_gpu_cube(self, on):
        self.gpu_cube = bool(on)
        self.prefs["gpu_cube"] = self.gpu_cube
        save_prefs(self.prefs)
        self.request_layout()

    def set_device_factor(self, v):
        try:
            self.prefs["device_factor"] = max(1.0, float(v))
            self.prefs.pop("device_factor_measured", None)     # typed by hand: an estimate again
            save_prefs(self.prefs)
        except ValueError:
            self.gp.status("a number, please: how many times slower than this PC the device is")

    # --- callbacks -----------------------------------------------------------
    def on_effect(self, s, val):
        if val not in self.eng.names:                    # a name from elsewhere (a command, an old preset): said, not raised
            self.gp.status(f"no effect named {val!r} in this build", "error"); return
        self.eng.select(self.eng.names.index(val))
        self.rebuild_params()
        self.sync_palette_combo()
        if self.eng.seg_count() > 1:
            self.save_segments()
        self.rebuild_seg_fields()                        # the segment row names the effect too
        self.project.selected = val
        self.project.save()

    def on_palette(self, s, val):
        self.eng.pal = dict(PALETTES)[val]
        self.eng.push()

    def on_pal_source(self, s, val):
        self.eng.pal_source = dict(PALETTES)[val]
        self._ab_sync()

    def palette_name_for(self, pid):
        for n, i in PALETTES:
            if i == pid:
                return n
        return PALETTES[0][0] if PALETTES else ""

    def reload_palettes(self):
        """The palette list again (a custom palette added or changed): the
        combos' items, with the sim's choice kept."""
        global PALETTES
        PALETTES = self.eng.palette_list()
        if dpg.does_item_exist("pal_combo"):
            dpg.configure_item("pal_combo", items=[p[0] for p in PALETTES])
        if dpg.does_item_exist("pal_src"):
            dpg.configure_item("pal_src", items=[p[0] for p in PALETTES if p[1] < 201])
        self.sync_palette_combo()

    def sync_palette_combo(self):
        """Selecting an effect now loads ITS palette default, so the combo has
        to follow - otherwise it shows one palette while the cube renders
        another."""
        try:
            dpg.set_value("pal_combo", self.palette_name_for(self.eng.pal))
        except Exception:
            oops.swallowed()

    # --- geometry --------------------------------------------------------------
    GEOM_FIELDS = {
        "strip":    [("n", "LEDs", 1, 2000), ("ring", "ring", None, None)],
        "matrix":   [("w", "width", 1, 256), ("h", "height", 1, 256),
                     ("serpentine", "serpentine", None, None), ("vertical", "vertical", None, None),
                     ("start_right", "start right", None, None), ("start_bottom", "start bottom", None, None)],
        "cube":     [("B", "pixels per face", 4, 85), ("six", "six faces: the bottom lit too", None, None)],
        "cylinder": [("w", "around", 3, 256), ("h", "tall", 1, 256)],
        "sphere":   [("w", "around", 3, 256), ("h", "rows", 2, 128)],
        "torus":    [("w", "around", 3, 256), ("h", "tube", 3, 64)],
        "xyz":      [],
        "shape":    [],
    }

    def apply_geometry(self, geom):
        """A new geometry: into the engine, into the project, views resized.
        The effect restarts, so its sliders are rebuilt from the engine."""
        before = self.eng.geom                           # set_geometry keeps the new one even when it refuses it
        try:
            self.eng.set_geometry(geom)
        except Exception as e:
            # the engine said no (too many pixels): keep what was there - the engine's last one, since a project
            # switched to already holds the refused one (re-applying that raised again, out of switch_project)
            for back in (before, self.project.geometry if self.project.geometry is not geom else None, Geometry("cube", B=16)):
                if back is None:
                    continue
                try:
                    self.eng.set_geometry(back)
                    break
                except Exception:
                    oops.swallowed()
                    continue
            if self.project.geometry is geom:
                self.project.geometry = self.eng.geom
            if dpg.does_item_exist("geom_desc"):
                dpg.set_value("geom_desc", f"cannot use that geometry: {e}")
            return
        self.project.geometry = geom
        self.project.save()
        if dpg.does_item_exist("geom_kind"):            # the panel's GEOMETRY section follows, whoever changed it
            if dpg.get_value("geom_kind") != geom.kind:
                dpg.set_value("geom_kind", geom.kind)
            self.rebuild_geom_fields()
        if dpg.does_item_exist("shape_win") and dpg.is_item_shown("shape_win"):
            shape_ui.refresh(self)
        self._ab_sync()
        self.rebuild_params()
        self.rebuild_seg_fields()
        self.request_layout()
        try:
            dpg.set_value("geom_desc", geom.describe())
            dpg.configure_item("map1d2d_row", show=geom.is2d)
        except Exception:
            oops.swallowed()

    def on_geom_kind(self, s, val):
        if val == "xyz":
            dpg.show_item("xyz_dialog")
            return
        params = dict(self.project.geometry.params) if self.project.geometry.kind == val else {}
        if val == "shape" and not params.get("parts"):
            # nothing changes until a first part goes in: the Shape frame opens on its start (shape_start)
            dpg.set_value("geom_kind", self.project.geometry.kind)
            device_ui.show(self, "shape")
            shape_ui.refresh(self)
            self.gp.status("pick a start in the Shape frame: the geometry becomes the shape when its first part goes in")
            return
        self.apply_geometry(Geometry(val, **params))
        self.rebuild_geom_fields()
        if val == "shape":
            device_ui.show(self, "shape")

    def on_geom_field(self, sender, val):
        key = dpg.get_item_user_data(sender)
        g = self.project.geometry
        params = dict(g.params); params[key] = val
        if key in ("faces", "rots") and not params.get("faces"):
            params["faces"] = "N,W,T,E,S,B" if params.get("six") else "N,W,T,E,S"   # a wiring is being set: leave the raster order
        self.apply_geometry(Geometry(g.kind, **params))

    def on_xyz_file(self, s, app_data):
        path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
        if not path:
            return
        try:
            g = Geometry.from_xyz_file(path)
        except Exception as e:
            dpg.set_value("geom_desc", f"could not read {os.path.basename(path)}: {e}")
            return
        self.apply_geometry(g)
        dpg.set_value("geom_kind", "xyz")
        self.rebuild_geom_fields()
        if getattr(g, "skipped", 0):
            messages.post(self, f"{os.path.basename(path)}: {g.skipped} row(s) without three finite numbers "
                                "(nan, inf, a missing column) left out", "warn")

    def rebuild_geom_fields(self):
        if not dpg.does_item_exist("geom_fields"):
            return
        dpg.delete_item("geom_fields", children_only=True)
        g = self.project.geometry
        for key, label, lo, hi in self.GEOM_FIELDS.get(g.kind, []):
            if lo is None:
                form.check(label, parent="geom_fields", user_data=key,
                           default_value=bool(g.params.get(key, key == "serpentine")),
                           callback=self.on_geom_field)
            else:
                with form.row(label, parent="geom_fields"):
                    dpg.add_input_int(user_data=key, width=px(110),
                                      default_value=int(g.params.get(key, {"n": 60, "w": 16, "h": 16, "B": 16}.get(key, 16))),
                                      min_value=lo, max_value=hi, min_clamped=True, max_clamped=True,
                                      on_enter=True, callback=self.on_geom_field)
        if g.kind == "xyz":
            form.note(f"{g.count} points from {g.params.get('source', 'file')}", parent="geom_fields")
        if g.kind not in ("xyz", "shape"):
            with form.under(parent="geom_fields"):
                dpg.add_button(label="Read the device's wiring", tag="geom_read_wiring", small=True, callback=lambda: self.read_device_wiring())
                chrome.tip("the order the active device's LEDs are wired in, as WLED uses it - its ledmap, else its 2-D setup "
                           "(where the first LED is, rows or columns, serpentine, panels, gaps), else a strip - over this "
                           f"{g.kind}: a cube's faces, their order and turns. Read only; the device is not changed.")
        if g.kind == "shape":                             # the description line below says what it is
            with form.row("effects see", parent="geom_fields",
                          tip="one strip in wiring order (1-D effects, the 3-D nodes), or a grid the LEDs are projected "
                              "onto, for WLED's 2-D effects and the matrix ones - how it is projected is in the Shape "
                              "frame's Shape tab"):
                dpg.add_combo(["strip", "grid"], tag="geom_layout", width=px(80), default_value=g.params.get("layout", "strip"),
                              callback=lambda s, v: shape_ui.set_layout(self, v))
            if g.params.get("layout") == "grid":
                lost = int(getattr(g, "collisions", 0) or 0)
                form.note(f"a {g.w} x {g.h} grid" + (f": {lost} LEDs share a cell and stay dark" if lost else ""),
                          parent="geom_fields", **({"color": chrome.AMBER} if lost else {}))
            with form.under(parent="geom_fields"):
                dpg.add_button(label="Edit the shape...", callback=lambda: device_ui.show(self, "shape"))
                dpg.add_button(label="Shape settings...", callback=lambda: shape_ui.show_settings(self))
                chrome.tip("the Shape frame on the whole shape's settings: its sizes, what the effects see and how a grid "
                           "is projected, power")
        if g.kind == "cube" and g.params.get("map") is not None:
            # wired by a device's own map, which the settings below cannot say: they come back on request
            with form.under(parent="geom_fields"):
                dpg.add_button(label="Use the wiring fields instead", small=True, callback=self.drop_geom_map)
                chrome.tip("the face order, turns and switches set the wiring again (the device's map dropped)")
        elif g.kind == "cube":
            # the wiring: which face first, how each is turned, how each is
            # walked - what the exported ledmap says
            form.note("the wiring, as the ledmap has it:", parent="geom_fields")
            with form.row("face order", parent="geom_fields", tip="the faces in the order the wiring reaches them"):
                typeface.mono(dpg.add_input_text(user_data="faces", width=-1,
                                                 default_value=str(g.params.get("faces", "")),
                                                 hint="N,W,T,E,S,B" if g.params.get("six") else "N,W,T,E,S", on_enter=True,
                                                 callback=self.on_geom_field))
            with form.row("quarter turns", parent="geom_fields", tip="how each face is turned, in quarter turns, in the order above"):
                typeface.mono(dpg.add_input_text(user_data="rots", width=-1,
                                                 default_value=str(g.params.get("rots", "")),
                                                 hint="0,0,0,0,0,0" if g.params.get("six") else "0,0,0,0,0", on_enter=True,
                                                 callback=self.on_geom_field))
            for row in ((("serpentine", "serpentine"), ("vertical", "vertical")),
                        (("start_right", "from right"), ("start_bottom", "from bottom"))):
                with form.under(parent="geom_fields"):
                    for key, label in row:
                        dpg.add_checkbox(label=label, user_data=key, default_value=bool(g.params.get(key, False)),
                                         callback=self.on_geom_wiring)
            self._inputs.update(("faces_in",))
        if g.params.get("map") is not None:
            form.note(f"wiring from {g.params.get('source', 'a ledmap')}: {g.count} LEDs, {int((~g.lit).sum())} gaps",
                      parent="geom_fields")
        if g.kind != "xyz":
            form.check("show the wiring on the net", parent="geom_fields", default_value=self.show_wiring,
                       callback=lambda s, v: setattr(self, "show_wiring", bool(v)))

    def drop_geom_map(self):
        """A device's map off the geometry: its own settings wire it again."""
        g = self.project.geometry
        p = {k: v for k, v in g.params.items() if k not in ("map", "source")}
        self.apply_geometry(Geometry(g.kind, **p))
        self.gp.status(f"the {g.kind}'s own wiring settings again (the device's map dropped)")

    def on_map1d2d(self, s, val):
        self.eng.set_map1d2d(["strip", "bars", "arcs", "corner"].index(val))

    # --- the editor ------------------------------------------------------------
    def edit_open(self, fname):
        if not fname:
            return
        self.edit_file = fname
        self.edit_dirty = False
        self._watch_mtime = self._mtime(fname)
        dpg.set_value("code", self.project.read_effect(fname))
        self._code_reset(dpg.get_value("code"))
        if dpg.does_item_exist("meta_name"):
            self.meta_read()
        dpg.set_value("edit_status", f"{fname}")
        dpg.configure_item("edit_file", items=self.project.effect_files())
        dpg.set_value("edit_file", fname)
        self.refresh_import_buttons()

    # --- the one slider shape used everywhere ---------------------------------
    def pair(self, parent, key, label, value, lo, hi, setter, is_float=False, unit="", prefix="inp_"):
        """A row of the panel: its label, then the one number control
        (num.py) - the value on the track, drag it, click it to type, a thin
        fill for where it sits. It was a slider showing no number beside a
        box that did (C7). The field is <prefix><key>: inp_<key> in the panel."""
        it = f"{prefix}{key}"
        self._inputs.add(it)
        with form.row(label, parent=parent):                 # the label first, in the panel's column (C6)
            num.add(it, value, lo, hi, integer=not is_float, digits=1 if is_float else None, unit=unit, width=-1,
                    callback=lambda s, v: setter(max(lo, min(hi, v))))

    def fx_fit(self, meta=None):
        """A word under the effect when it cannot show on this geometry: an
        effect written for a matrix alone, on LEDs laid out as one row (a
        strip, a ring, a shape's strip layout), runs as a solid colour."""
        if not dpg.does_item_exist("fx_fit_note"):
            return
        from native.engine import matrix_only
        g = self.project.geometry
        bad = bool(self.eng.meta) and not g.is2d and matrix_only(meta or self.eng.meta[self.eng.idx])
        if bad:
            dpg.set_value("fx_fit_note", "an effect for a matrix: on this shape's one-row (strip) layout it shows one colour - "
                                         "pick one made for any shape (the project's own, a 1-D one), or lay the shape out as a "
                                         "grid" if g.kind == "shape" else
                          "an effect for a matrix: on a single row of LEDs it shows one colour - pick a 1-D effect, or one for both")
        dpg.configure_item("fx_fit_note", show=bad)
        if dpg.does_item_exist("fx_fit_grid"):
            dpg.configure_item("fx_fit_grid", show=bad and g.kind == "shape")

    def rebuild_params(self, meta=None):
        """Sliders are labelled from the effect's own metadata, as the web UI is
        - or from `meta`, an effect another stands in for (the script running a
        graph's edit until its build lands)."""
        self.fx_fit(meta)                                # the effect or the geometry changed: whether it can show here
        dpg.delete_item("params", children_only=True)
        self.param_rows("params", meta=meta)

    def param_rows(self, parent, prefix="inp_", meta=None):
        """The current effect's sliders and checkboxes into `parent`, labelled and ranged from its metadata: the
        panel's (prefix inp_) and the sequencer's step card's (seqp_) are built by this one - the same rows both
        places. A slider is <prefix><key>, a checkbox <prefix>chk_<key>."""
        m = meta or self.eng.meta[self.eng.idx]
        generic = {"sx": "Speed", "ix": "Intensity", "c1": "Custom 1",
                   "c2": "Custom 2", "c3": "Custom 3"}
        for i, k in enumerate(("sx", "ix", "c1", "c2", "c3")):
            lab = (m["labels"][i] if i < len(m["labels"]) else "").strip()
            if not lab or lab == "!":
                lab = generic[k]
            # custom3 is a five-bit field in the firmware and the API clamps it
            # to 0..31, so the slider must stop there. Letting it run to 255
            # offers settings the cube cannot hold - which is exactly how
            # fourteen effects came to be tuned against values they never got.
            hi = 31 if k == "c3" else 255
            self.pair(parent, k, lab, self.eng.fx[k], 0, hi,
                      lambda v, k=k: self._set_param(k, v), prefix=prefix)
        for i, k in enumerate(("o1", "o2", "o3")):
            lab = (m["labels"][5 + i] if 5 + i < len(m["labels"]) else "").strip()
            if not lab:
                continue
            form.check(lab, parent=parent, default_value=bool(self.eng.fx[k]), tag=f"{prefix}chk_{k}",
                       user_data=k, callback=self.on_check)

    # --- layout --------------------------------------------------------------
    def request_layout(self):
        """Ask for a relayout; do not perform one here.

        relayout() deletes the net and cube textures and builds new ones. Dear
        PyGui callbacks run INSIDE render_dearpygui_frame(), while those very
        textures are bound to the image widgets being drawn - and deleting an
        item that the renderer is walking is a native crash, not an exception.
        It survives often enough to look fine, which is worse.

        Changing face size is the case that trips it: on_faceB resizes the
        engine, which changes the net from 48x48 to 96x96, so the textures MUST
        be rebuilt and cannot simply be reused. Deferring to the top of the next
        pass costs one frame and takes the deletion out of the render entirely.
        """
        self._need_layout = True

    # --- what the menus and the toolbar call ------------------------------------------
    # Each is "the current thing": the graph when the graph pane is up, the
    # code when the code pane is, and the graph otherwise - it is the
    # primary editor. A pane's own row keeps only what names the thing in it.
    def current_file(self):
        """The effect file the current pane is about, or None."""
        if self.layout == "edit":
            return self.edit_file
        return self.gp.effect_file() or self.edit_file

    def restart_studio(self):
        """The studio again (an interface size takes it): the code's unsaved
        edits saved first if you say so - the graph saves as you go."""
        from native import wledtree

        def go(save=False):
            if save and self.edit_dirty:
                self.edit_save()
            self.gp.save()
            save_prefs(self.prefs)
            wledtree.restart()
            dpg.stop_dearpygui()
        if self.edit_dirty and self.edit_file:
            chrome.confirm(self, "Restart the studio", f"{self.edit_file} has changes that are not saved.",
                           [("Save and restart", lambda: go(True)), ("Restart without saving", lambda: go(False), "danger"),
                            ("Cancel", None)])
        else:
            go()

    def quit_studio(self):
        """File > Quit and the window's close: the open graph and the prefs saved, and the code's unsaved
        edits saved too if you say so - nothing asked before, and they were lost (as were a graph's edits with
        Live off). Whatever goes wrong in the saving, it quits: a close that could fail would keep the window."""
        def go(save=False):
            try:
                if save and self.edit_dirty:
                    self.edit_save()
                if self.gp.graph is not None:
                    self.gp.save()
                self._leave_project()            # what waits to be saved (a modulator dragged while paused) kept
                save_prefs(self.prefs)
            except Exception:
                import traceback
                traceback.print_exc()
            dpg.stop_dearpygui()
        try:
            if self.edit_dirty and self.edit_file:
                chrome.confirm(self, "Quit the studio", f"{self.edit_file} has changes that are not saved.",
                               [("Save and quit", lambda: go(True)), ("Quit without saving", lambda: go(False), "danger"),
                                ("Cancel", None)])
                return
        except Exception:
            oops.swallowed()
        go()

    def save_current(self):
        if self.layout == "edit":
            self.edit_save()
        else:
            self.gp.save()
            if self.edit_dirty:
                self.edit_save()

    def build_current(self):
        if self.layout == "edit":
            self.edit_build()
        elif self.gp.graph:
            self.gp.compile()
        else:
            self.edit_build()

    def new_effect(self, kind=None):
        kind = kind or ("code" if self.layout == "edit" else "graph")
        if kind == "code":
            chrome.ask(self, "New code effect", "a name for the effect", "", lambda v: (
                self.edit_new(v), self.show_layout("edit")))
        else:
            chrome.ask(self, "New graph effect", "a name for the effect", "", lambda v: (
                self.gp.new(v), self.show_layout("graph")))

    def rename_current(self):
        if self.layout == "edit" and self.edit_file:
            chrome.ask(self, "Rename effect", "the new name", self.project.effect_title(self.edit_file),
                       lambda v: self.edit_rename(v))
        elif self.gp.graph:
            chrome.ask(self, "Rename graph", "the new name", self.gp.graph.name, lambda v: self.gp.rename(v))

    def toggle_import_current(self):
        f = self.current_file()
        if f and f not in self.project.effect_files() and self.gp.graph:
            self.gp.compile()             # a graph never built has no .cpp yet
        self.toggle_import(f)

    def open_graph(self, fname):
        self.gp.open(fname)
        self.show_layout("graph")

    def open_code(self, fname):
        self.edit_open(fname)
        self.ensure_built()
        self.show_layout("edit")

    def show_layout(self, which):
        """A pane by name, controls shown - the menu and toolbar route."""
        self.layout = which
        self.ui = True
        self.request_layout()

    def toggle_ui(self):
        self.ui = not self.ui
        if not self.ui:
            self.hint_presentation(f"{self.keys.label('presentation') or 'H'} or Esc: the controls back")
        self.request_layout()

    def leave_presentation(self):
        """Esc while presenting: the controls back - and from a full-frame
        view (Q, E, W) the panels, as its own key again does."""
        if self.layout in ("net", "cube"):
            self.layout = "both"
        self.ui = True
        self._present_hint = None
        self.request_layout()

    HINT_S = 3.5          # the presentation hint's seconds on the picture, the last one fading

    def hint_presentation(self, text):
        self._present_hint = (text, time.time())

    def poll_present_hint(self):
        """Presentation entered: how to leave it, a pill at the bottom of the
        picture for a few seconds, fading (the critique's C13 - nothing on
        the screen said how to come back)."""
        h = getattr(self, "_present_hint", None)
        alive = h is not None and not self.ui and time.time() - h[1] < self.HINT_S
        if not dpg.does_item_exist("present_hint"):
            if not alive:
                return
            dpg.add_viewport_drawlist(front=True, tag="present_hint")
        dpg.delete_item("present_hint", children_only=True)
        if not alive:
            self._present_hint = None
            return
        text, t0 = h
        age = time.time() - t0
        k = 1.0 if age < self.HINT_S - 1.0 else max(0.0, self.HINT_S - age)
        size = typeface.size_of("body")
        w, hh = typeface.measure(text, "body", size) + px(32), size + px(18)
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        x0, y0 = (vw - w) / 2, vh - hh - px(32)
        dpg.draw_rectangle((x0, y0), (x0 + w, y0 + hh), fill=(18, 20, 26, int(220 * k)), color=(255, 255, 255, int(70 * k)),
                           rounding=hh / 2, parent="present_hint")
        typeface.draw_text((x0 + px(16), y0 + px(9)), text, size, color=(236, 239, 245, int(255 * k)), parent="present_hint")

    def toggle_play(self):
        self.playing = not self.playing

    def step_once(self):
        self.audio_push(); self.eng.frame(STEP)

    SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)

    def set_speed(self, v):
        """The sim's pace: v simulated seconds a real second. The synth's
        beat clock runs on simulated time, so it keeps step; live audio
        and a WAV play at their own, real, pace."""
        self.speed = float(v)
        chrome.refresh_speed(self)
        self.gp.status(f"speed {chrome.speed_label(self.speed)}")

    def step_speed(self, by):
        k = min(range(len(self.SPEEDS)), key=lambda i: abs(self.SPEEDS[i] - self.speed))
        self.set_speed(self.SPEEDS[max(0, min(len(self.SPEEDS) - 1, k + by))])

    def duplicate_selected(self):
        sel = self.gp._selected()
        if sel:
            self.gp._dup(sel[0], True)

    def search_nodes(self):
        """The add menu, at the middle of the graph pane."""
        if self.layout != "graph":
            self.show_layout("graph")
            self.relayout()
        if dpg.does_item_exist("node_editor"):
            x, y = self.gp.editor_origin()
            w, h = dpg.get_item_rect_size("node_editor")
            self.gp._menu_pos = self.gp._to_graph((x + w * 0.4, y + h * 0.3))
            # a plain add: a "change type" or a wire dropped on the canvas, its menu dismissed, was still pending -
            # and the node picked here replaced that node, or was wired to that old output
            self.gp._pending = None
            self.gp.show_add_menu((x + w * 0.4, y + h * 0.3))

    def add_node_from_menu(self, type_):
        if self.layout != "graph":
            self.show_layout("graph")
        self.gp.add_node(type_)

    def enter_selected_sub(self):
        sel = self.gp._selected()
        if sel:
            self.gp.enter_sub(sel[0])
        else:
            self.gp.status("select a sub-graph node first")

    def where_used_selected(self):
        sel = self.gp._selected()
        if sel and self.gp.graph:
            self.gp.show_where_used(self.gp.graph.nodes[sel[0]]["type"])
        else:
            self.gp.status("select a node first")

    def focus_find(self):
        self.show_layout("edit")
        if dpg.does_item_exist("find_text"):
            dpg.focus_item("find_text")

    def show_api(self):
        self.show_layout("edit")
        if dpg.does_item_exist("api_header"):
            dpg.set_value("api_header", True)

    def export_usermod(self, with_deps=None):
        """The usermod folder and zip. Effects calling on firmware that is
        not every WLED tree's (the IMU driver) ask whether to put those
        files in the folder too; with_deps answers without asking."""
        from native import flash
        self.gp.regenerate(self.project.build_files())
        req = set()
        for f in self.project.build_files():
            try:
                req |= flash.requirements_of_code(open(self.project.effect_path(f), encoding="utf-8", errors="replace").read())
            except OSError:
                pass
        ours = sorted(k for k in req if not flash.DEPENDENCIES[k]["standard"])
        if ours and with_deps is None:
            what = ", ".join(flash.DEPENDENCIES[k]["label"] for k in ours)
            chrome.confirm(self, "Export usermod",
                           f"The effects call on {what} - firmware that is not part of every WLED tree. "
                           "Include those files in the usermod folder, so it builds anywhere?",
                           [("Include them", lambda: self.export_usermod(True)),
                            ("Just the effects", lambda: self.export_usermod(False)), ("Cancel", None)])
            return
        msg = "exported to " + self.project.export(deps=ours if with_deps else [], requires=sorted(req))
        dpg.set_value("edit_status", msg); self.gp.status(msg)

    def save_editor_cmd(self, cmd):
        from native.project import save_prefs
        cmd = (cmd or "").strip()
        if cmd:
            self.prefs["editor"] = cmd                   # this computer's (the studio's settings), not the project's
        else:
            self.prefs.pop("editor", None)
        save_prefs(self.prefs)
        if self.project.options.pop("editor", None) is not None:
            self.project.save()                          # (an older project's own: not used, not kept)

    def reset_layout(self):
        """The default sizes; the arrangement stays."""
        self.side_w = SIDE_W
        self.colw = {}
        self.rowh = {}
        for k in ("splits", "side_w", "colw", "rowh"):
            self.prefs.pop(k, None)
        save_prefs(self.prefs)
        self.request_layout()

    def toggle_pane(self, which):
        """C and G: the pane, or back to the two views if it is already up."""
        self.layout = "both" if self.layout == which else which
        self.ui = True
        self.request_layout()

    def show_pane(self, which):
        """A pane brought up to show something in it - a message's node or
        line: up, with the interface, whatever was up before; never toggled
        away (C and G) or turned into a full frame (Q, E, W)."""
        if self.layout != which or not self.ui:
            self.layout, self.ui = which, True
            self.request_layout()

    def toggle_side(self):
        self.side = not self.side
        self.request_layout()

    def toggle_props(self):
        if room.active(self):
            room.pin_props(self, not getattr(self, "props_pinned", False))    # canvas first: N pins them open
            return
        self.props = not self.props
        self.prefs["props_pane"] = self.props
        save_prefs(self.prefs)
        self.request_layout()

    def step_effect(self, d):
        names = self.eng.names
        if names:
            self.on_effect(None, names[(self.eng.idx + d) % len(names)])
            dpg.set_value("fx_combo", names[self.eng.idx])

    def step_palette(self, d):
        names = [p[0] for p in PALETTES]
        cur = self.palette_name_for(self.eng.pal)
        i = names.index(cur) if cur in names else 0
        self.on_palette(None, names[(i + d) % len(names)])
        dpg.set_value("pal_combo", names[(i + d) % len(names)])

    def enter_or_back(self):
        if self.gp.stack:
            self.gp.back()
        else:
            self.enter_selected_sub()

    def set_layout(self, which):
        """Q, E and W go straight to a full-frame picture, every time.

        These are not layout choices with a separate "and now hide the
        controls" step - they ARE the presentation mode, and the view is what
        you wanted to look at. Requiring a second press to clear the chrome
        made the first press produce something nobody asked for: the same
        cluttered window with one view missing.

        H brings the controls back without leaving the layout, for adjusting a
        slider while watching, and takes them away again. The same key again,
        while its view is up full-frame, comes back to the panels: one key
        goes there and back, the way C and G do for their panes.
        """
        if self.layout == which and not self.ui:
            self.layout = "both"
            self.ui = True
        else:
            self.layout = which
            self.ui = False
            key = self.keys.label({"net": "view_net", "cube": "view_cube", "both": "view_both"}.get(which, "")) or ""
            self.hint_presentation((f"{key} again or Esc: back to the panels" if key else "Esc: back to the panels")
                                   + f"  ·  {self.keys.label('presentation') or 'H'}: the controls over the picture")
        self.request_layout()

    def step_sim(self):
        from native import clock
        now = clock.now()                    # the studio's clock: held and stepped by hand while a video renders
        dt = min(0.25, now - self.last)      # a stalled window must not sprint
        self.last = now
        if not self.playing:
            self.acc = 0.0
            return
        self.scrub = None
        self._poll_sweep()
        modulate.apply(self)                 # the sliders' modulators: each moved round where it is set
        self.acc += dt * 1000.0 * self.speed
        n = 0
        while self.acc >= STEP and n < 8:
            self.audio_push()
            t0 = time.perf_counter()
            self.eng.frame(STEP)
            mixer.step(self, STEP)                   # the mixer's deck B a frame on beside it (native/mixer.py)
            ms = (time.perf_counter() - t0) * 1000.0
            self.frame_ms = ms if self.frame_ms == 0.0 else self.frame_ms * 0.95 + ms * 0.05
            frametime.add("the effect (engine)", ms, "sim")
            if self.ab:
                try:
                    if self.ab_before:
                        self._ab_follow()
                    self.ab.fft[:] = self.eng.fft[:]
                    self.ab.audio(*getattr(self.eng, "last_audio", (0.0, 0)))
                    self.ab.frame(STEP)
                    if self._ab_pokes:
                        self._ab_pokes_land()
                except Exception:
                    oops.swallowed()
                    self.ab = None
                    self.ab_before = None
            self.acc -= STEP
            n += 1

    SCRUB_SECONDS = 30.0         # how far back a pause can scrub
    SCRUB_EVERY = 1.0 / 60.0     # one frame kept a sixtieth of a second at most, however fast the view draws
    SCRUB_BYTES = 96 << 20       # and no more memory than this: a big matrix keeps fewer seconds (two at the least)
    CUBE_SRC_SCALE = 4           # the net's upscale for the GPU cube's texture

    def draw(self):
        net = self.net_image()
        # the last seconds of frames are kept while playing; paused, the
        # scrub slider picks one of them to show instead of the live one
        rgb = None
        if getattr(self, "_history_geom", None) is not self.project.geometry:
            # kept on another geometry (applied, another project, a cube resized): their sizes are not the
            # textures' now - a scrub back pushed an old-size frame into them - so they go, and the scrub with them
            self.history_frames.clear(); self.history_rgb = []; self.history_t.clear()
            self.scrub = None
            self._history_geom = self.project.geometry
        if self.playing:
            now = time.perf_counter()
            if now - getattr(self, "_scrub_at", 0.0) >= self.SCRUB_EVERY:
                self._scrub_at = now
                self.history_frames.append(net)
                self.history_t.append(now)
                if self.point_quads is not None and self.cube_on():
                    self.history_rgb.append(self.frame_rgb(self.eng).copy())
                elif self.history_rgb:
                    self.history_rgb = []
                each = net.nbytes + (self.history_rgb[-1].nbytes if self.history_rgb else 0)
                keep = int(min(self.SCRUB_SECONDS / self.SCRUB_EVERY,
                               max(2.0 / self.SCRUB_EVERY, self.SCRUB_BYTES // max(1, each))))
                del self.history_frames[:-keep]
                del self.history_t[:-keep]
                if self.history_rgb:
                    del self.history_rgb[:-keep]
        elif self.scrub is not None and self.history_frames:
            k = max(0, min(len(self.history_frames) - 1, self.scrub))
            net = self.history_frames[k]
            if self.history_rgb and len(self.history_rgb) == len(self.history_frames):
                rgb = self.history_rgb[k]                  # the scrubbed frame on a strip, a sphere, a shape of parts too
        big = img = None
        _u, _f = self.view_extras()
        if self.popouts.jobs:
            shown = self.view_rgb(self.eng, rgb)          # what the views show, not the engine's own
            pop_net = net
            cue = vj.cue_picture(self) if vj.on(self) else None           # the VJ's cue: the deck off the mix there
            if cue is not None and cue.shape == shown.shape:
                shown = cue
                if pop_net.shape == cue.shape:
                    pop_net = cue
            self.popouts.publish(pop_net, self.eng, (self.yaw, self.pitch, self.dist),
                                 (1 if _u is not None else 0) | (2 if _f else 0), self.view_look(), shown)
        if self.net_on():
            if self.gpu_net:
                k = self.NET_SRC_SCALE
                dpg.set_value("net_tex", self._rgba_scaled("net", net, k))
                if self.shot_req or self.rec is not None:
                    big = net.repeat(self.net_scale, 0).repeat(self.net_scale, 1)
            else:
                big = net.repeat(self.net_scale, 0).repeat(self.net_scale, 1)
                dpg.set_value("net_tex", self._rgba("net", big))
        if self.cube_on() and self.cube_quads is not None:
            k = self.CUBE_SRC_SCALE
            src = net if net.shape[0] == self.eng.rows else self.net_image()
            unlit, floor = self.view_extras()
            lk = self.view_look()
            toned = look.tone(src, lk)
            if unlit is None and float(lk.get("glow", 0.0)) <= 0.0 and not (float(lk.get("diffuse", 0.0)) > 0 and self.eng.B):
                # the plain look: led_texture is the net in k x k blocks - made by broadcasting, as the net's is
                dpg.set_value("cube_src_tex", self._rgba_scaled("cube_src", toned, k))
            else:
                dpg.set_value("cube_src_tex", self._rgba("cube_src", look.led_texture(toned, k, lk, unlit, B=self.eng.B)))
            cq = self.cube_quads
            cq.reflect = lk["reflect"]
            cq.layers.update(lk, look.mean_light(src) if lk["spill"] > 0 else None, cq.size, cq.w, cq.h)
            self.cube_quads.floor = floor
            self.cube_quads.camera(self.yaw, self.pitch, self.dist, six=self.eng.six, **view3d.kw(self))
            self.cube_quads.background(self.view_background(self.view_side, cq.w, cq.h) if self.prefs.get("view_bg") else None)
            if self.shot_req or self.rec is not None:
                img = self.view_image(net, self.cube_px)      # a picture is wanted: the software path makes one
        elif self.cube_on() and self.point_quads is not None:
            pq = self.point_quads
            pos = self.view_positions()
            fr = view3d.frame(self)
            if pos is not pq.pos and (len(pos) != pq.n or not np.array_equal(pos, pq.pos)):
                pq.set_points(pos, fr)                     # a part dragged, a shape changed
            else:
                pq.set_frame(fr)                           # held while a shape is built, eased when it is refitted
            unlit, floor = self.view_extras()
            pq.floor, pq.dots = floor, unlit is not None
            pq.camera(self.yaw, self.pitch, self.dist, floor_step=view3d.floor_step(self), **view3d.kw(self))
            pq.background(self.view_background(self.view_side, pq.w, pq.h) if self.prefs.get("view_bg") else None)
            lk = self.view_look()
            cols = shape_ui.view_colours(self, self.view_rgb(self.eng, rgb).reshape(-1, 3))
            cols = look.diffuse_points(pos, cols, lk)          # through the diffuser: light shared by distance
            pq.reflect = lk["reflect"]
            pq.colours(look.tone(cols, lk), unlit=unlit, lk=lk)
            pq.layers.update(lk, look.mean_light(cols) if lk["spill"] > 0 else None, pq.size, pq.w, pq.h)
            if self.shot_req or self.rec is not None:
                img = self.view_image(net, self.cube_px)      # a picture is wanted: the software path makes one
        elif self.cube_on():
            img = self.view_image(net, self.cube_px)
            if self.ab:
                # side by side, a gap between: the texture is two renders wide
                p = self.cube_px
                imgb = self.view_image(self.net_image(self.ab), p, self.ab)
                both = np.zeros((p, 2 * p + 8, 3), np.uint8)
                both[:, :p] = img; both[:, p + 8:] = imgb
                img = both
            dpg.set_value("cube_tex", self._rgba("cube", img))
        self._draw_wiring()
        self._draw_segments()
        if self.layout == "graph" and self.gp.preview:
            self.gp.update_thumb(net)
        # Records whatever is being SHOWN, so Q, E and W frame the clip too.
        self.rec_frame(big, img)
        if self.rec_msg:
            dpg.set_value("rec_msg", self.rec_msg)

        factor = pref_num(self.prefs, "device_factor", 60.0)
        dev_fps = 1000.0 / max(0.001, self.frame_ms * factor) if self.frame_ms > 0 else None
        pw = getattr(self, "_power", None)
        power = ""
        if pw:
            power = f"power {pw[0] / 1000.0:.2f} A" + (f" (limiter {int(pw[1] * 100)}%)" if pw[2] and pw[1] < 1.0 else "")
        speed = f"   speed {chrome.speed_label(self.speed)}" if self.speed != 1.0 else ""
        hover = self.hover_text()
        # the footer keeps the two figures most people want - the current, and the fps on the device (C18);
        # the stats button has the rest
        fps = f"device ~{dev_fps:.0f} fps" if dev_fps is not None else ""
        dpg.set_value("stat_txt", "   ".join(t for t in (power, fps) if t) + speed + hover)
        if dpg.does_item_exist("stats_pop") and dpg.is_item_shown("stats_pop"):
            self.fill_stats(pw, factor, dev_fps)
            chrome.place_stats()
        if dpg.does_item_exist("scrub_row"):
            show = (not self.playing) and len(self.history_frames) > 1
            if dpg.is_item_shown("scrub_row") != show:
                dpg.configure_item("scrub_row", show=show)
                if show:
                    num.configure("scrub", hi=len(self.history_frames) - 1)
                    num.set("scrub", len(self.history_frames) - 1)
                    secs = (self.history_t[-1] - self.history_t[0]) if len(self.history_t) > 1 else 0.0
                    dpg.set_value("scrub_note", f"paused - scrub the last {secs:.0f} s" if secs >= 1.5
                                  else "paused - scrub the last moment")
        lvl = self.live.level if self.live else 0.0
        dpg.set_value("lvl_bar", min(1.0, lvl / 220.0))
        if self.audio_sync is not None and time.perf_counter() - getattr(self, "_sync_said", 0.0) > 0.5:
            self._sync_said = time.perf_counter()                            # its count, twice a second
            dpg.set_value("audio_sync_msg", self.audio_sync.describe())
        if self.beat_flash:
            self.beat_flash -= 1
        dpg.configure_item("beat_led", default_value=(90, 169, 230, 255)
                           if self.beat_flash else (42, 47, 58, 255))


def build(app):
    typeface.dpi_aware()                     # drawn at the monitor's size, not stretched to it
    dpg.create_context()
    ico = os.path.join(_paths.RES, "docs", "brand", "app.ico")          # the lit cube, as the exe's (package.py)
    ico = ico if sys.platform in ("win32", "darwin") and os.path.exists(ico) else ""
    # the close button asks first (app.quit_studio), as File > Quit does: the viewport does not close by itself
    dpg.create_viewport(title="WLED Effects Studio", width=px(1280), height=px(800), vsync=False, small_icon=ico, large_icon=ico,
                        disable_close=True)
    dpg.set_exit_callback(lambda: app.quit_studio())
    typeface.fonts()
    typeface.bind()                          # the interface face; the monospace where code and numbers are

    with dpg.handler_registry():
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=app.on_drag)
        # click = once on press; down = every frame while held. The
        # difference is the whole bug this replaced.
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_click)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_release)
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Right, callback=app.on_right_click)
        dpg.add_mouse_wheel_handler(callback=app.on_wheel)
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Right, callback=lambda s, a: app.gp.knife_drag())
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Right, callback=lambda s, a: app.gp.knife_end())
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Middle, callback=app.on_mid_click)
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Middle, callback=app.on_mid_drag)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Middle, callback=app.on_mid_release)
        dpg.add_key_press_handler(callback=app.on_key)

    self_app = [app]
    weight.ensure()                                  # the button weights' themes, before any button is weighed
    # no scrollbar: the panes are laid out to the window's size, and a few pixels of rounding past it put a
    # scrollbar down the right edge, whose width then pushed the panes row past the right as well
    with dpg.window(tag="root", no_scrollbar=True, no_scroll_with_mouse=True):
        chrome.build_menus(app)
        chrome.build_toolbar(app)
        with dpg.group(horizontal=True, tag="panes_row"):
            with dpg.child_window(tag="net_win", width=px(420), height=px(470)):
                chrome.grip("net_win")
                with dpg.group(horizontal=True):
                    dpg.add_text("Logical view - what the effect draws", tag="net_cap", color=(139, 147, 163))
            with dpg.child_window(tag="edit_win", width=px(420), height=px(470), show=False):
                chrome.grip("edit_win")
                with dpg.group(horizontal=True):
                    dpg.add_combo(app.project.effect_files(), tag="edit_file", width=px(220),
                                  default_value=app.edit_file or "",
                                  callback=lambda s, v: (app.edit_open(v), app.ensure_built()))
                    dpg.add_text("", tag="edit_status", color=(139, 147, 163))
                # the text lives in a hidden box everything reads and writes;
                # the editor (codeedit.py) draws and edits it
                dpg.add_input_text(tag="code", multiline=True, width=px(400), height=px(300), show=False)
                app.code_ed = CodeEditor(app, "edit_win")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="find_text", hint="find", width=px(130), on_enter=True,
                                       callback=lambda: app.find())
                    dpg.add_button(label="find", callback=lambda: app.find(False))
                    chrome.tip("the next match (Shift+Enter in the box, or Shift+F3: the previous); the status says which of how many")
                    dpg.add_checkbox(label="case", tag="find_case", callback=lambda: app.find(False))
                    chrome.tip("match the case as typed")
                    dpg.add_checkbox(label="word", tag="find_word", callback=lambda: app.find(False))
                    chrome.tip("whole words only")
                with dpg.group(horizontal=True):              # a line of its own: with the find it ran 90 px past the pane
                    dpg.add_input_text(tag="replace_text", hint="replace with", width=px(130))
                    dpg.add_button(label="replace", callback=lambda: app.replace_one())
                    chrome.tip("the match the cursor is on, then the next is found")
                    dpg.add_button(label="replace all", callback=lambda: app.replace_all())
                with dpg.collapsing_header(label="Metadata - name, labels, palette, flags, defaults", default_open=False):
                    # the effect's WLED metadata string, a field a part (C6: each led by its name, the format on hover)
                    with form.row("name", width=128):
                        dpg.add_input_text(tag="meta_name", width=px(360))
                    with form.row("slider labels", width=128, tip="eight, separated by commas: Speed, Intensity, "
                                  "Custom 1 to 3, then the three checkboxes; ! keeps WLED's own name"):
                        dpg.add_input_text(tag="meta_labels", width=px(360), hint="Speed,Intensity,!,!,!,!,!,!")
                    with form.row("colour labels", width=128, tip="three, separated by commas: what the colour slots are called"):
                        dpg.add_input_text(tag="meta_colours", width=px(360), hint="!,!,!")
                    with form.row("flags", width=128, tip="where it runs - 1 on a strip, 2 on a matrix, 12 on both - "
                                  "and what it hears: v the volume, f the frequencies"):
                        typeface.mono(dpg.add_input_text(tag="meta_flags", width=px(360), hint="12v"))
                    with form.row("defaults", width=128, tip="what the sliders and the palette start at: sx=, ix=, c1=... pal="):
                        typeface.mono(dpg.add_input_text(tag="meta_defaults", width=px(360), hint="sx=128,ix=128,pal=0"))
                    with form.under(width=128):
                        dpg.add_button(label="read from file", callback=lambda: app.meta_read())
                        dpg.add_button(label="apply to file", callback=lambda: app.meta_write())
                with dpg.collapsing_header(label="API reference - click inserts at the cursor", default_open=False,
                                           tag="api_header"):
                    for group, items in API:
                        with dpg.tree_node(label=group):
                            for label, snippet, doc in items:
                                typeface.mono(dpg.add_selectable(label=f"{label:34s} {doc}"[:110], user_data=(snippet, label),
                                                   callback=lambda s, a, u: app.api_pick(*u)))
                dpg.add_group(tag="edit_errors")
            # The wheel over the graph zooms it; the pane must not also scroll
            # (its toolbar rows plus the editor can overrun its height by a
            # few pixels, and ImGui scrolls a window on the wheel whether or
            # not a handler also took the event).
            with dpg.child_window(tag="graph_win", width=px(420), height=px(470), show=False,
                                  no_scrollbar=True, no_scroll_with_mouse=True):
                build_panel(app, app.gp)
            # no scrollbar, no wheel scroll: the wheel zooms the view, and the drawlist filling the pane overran
            # it by a couple of pixels - a scrollbar at its edge, the view nudged by the wheel as it zoomed
            with dpg.child_window(tag="cube_win", width=px(420), height=px(470), no_scrollbar=True, no_scroll_with_mouse=True):
                chrome.grip("cube_win")
                with dpg.group(horizontal=True):
                    dpg.add_text("3-D - drag to rotate, wheel to zoom",
                                 tag="cube_cap", color=(139, 147, 163))
                    with dpg.tooltip("cube_cap", tag="cube_cap_tip"):
                        dpg.add_text("drag: turn it  ·  middle-drag or Ctrl+drag: pan  ·  wheel: zoom\n"
                                     "1 front, 3 side, 7 top (Ctrl: the other side), 5 orthographic, F frame, Home everything")
                view3d.build_buttons(app, "cube_win")
            # the graph's properties pane: what a node's settings need that
            # a node cannot hold (text, files); filled by GraphPanel._poll_props
            with dpg.child_window(tag="props_win", width=px(300), height=px(300), show=False):
                chrome.grip("props_win")
                dpg.add_text("Properties", tag="props_cap", color=(139, 147, 163))
                with dpg.child_window(tag="graph_props", border=False, height=-1):
                    pass
            with dpg.child_window(tag="side_win", width=app.side_w - 10, height=px(470)):
                chrome.grip("side_win")
                with Section(app, "effect", "EFFECT"):
                    with form.row("project"):
                        dpg.add_combo(list_projects(), tag="project_combo", width=-1,
                                      default_value=os.path.basename(app.project.path),
                                      callback=lambda s, v: app.switch_project(v))
                    with form.row("effect"):
                        dpg.add_combo(app.eng.names, tag="fx_combo",
                                      default_value=app.eng.names[app.eng.idx], width=-1,
                                      callback=app.on_effect)
                    form.note("", tag="fx_fit_note", show=False, color=chrome.AMBER)
                    with form.under(tag="fx_fit_grid", show=False):
                        dpg.add_button(label="Lay the shape out as a grid", small=True, callback=lambda: shape_ui.set_layout(app, "grid"))
                        chrome.tip("the shape's LEDs projected onto a grid (the best fit), so a matrix effect draws on it - "
                                   "the Shape frame's Shape tab says how, and can change it")
                    with form.row("palette"):
                        dpg.add_combo([p[0] for p in PALETTES],
                                      default_value=app.palette_name_for(app.eng.pal),
                                      width=-1, tag="pal_combo",
                                      callback=app.on_palette)
                    # Only meaningful while a CubeFX audio palette is selected -
                    # it is where those four take their colours from.
                    with form.row("colours from", tip="the palette a CubeFX audio palette takes its colours from"):
                        dpg.add_combo([p[0] for p in PALETTES if p[1] < 201],
                                      width=-1, tag="pal_src",
                                      default_value=app.palette_name_for(app.eng.pal_source),
                                      callback=app.on_pal_source)

                with Section(app, "segments", "SEGMENTS"):
                    with form.row("segment"):
                        dpg.add_combo([], tag="seg_combo", width=-px(112), callback=lambda s, v: app.seg_pick(v))
                        dpg.add_button(label="+", small=True, callback=lambda: app.seg_add())
                        dpg.add_button(label="-", small=True, callback=lambda: app.seg_remove())
                        dpg.add_button(label="undo", small=True, callback=lambda: app.seg_undo())
                        chrome.tip("the segments as they were before the last change (add, remove, bounds, blend, options)")
                    dpg.add_group(tag="seg_fields")
                with Section(app, "geometry", "GEOMETRY"):
                    with form.row("shape"):
                        dpg.add_combo(list(KINDS), tag="geom_kind", width=-1,
                                      default_value=app.project.geometry.kind, callback=app.on_geom_kind)
                    dpg.add_group(tag="geom_fields")
                    with form.row("1-D effects as", tag="map1d2d_row", show=app.project.geometry.is2d,
                                  tip="how an effect written for a strip is laid over a matrix"):
                        dpg.add_combo(["strip", "bars", "arcs", "corner"],
                                      tag="map1d2d", width=-1, default_value="strip", callback=app.on_map1d2d)
                    form.note(app.project.geometry.describe(), tag="geom_desc")
                    with dpg.file_dialog(directory_selector=False, show=False, tag="xyz_dialog",
                                         width=px(620), height=px(420), callback=app.on_xyz_file,
                                         cancel_callback=lambda s, a: dpg.set_value("geom_kind", app.project.geometry.kind)):
                        dpg.add_file_extension(".csv", color=(120, 200, 120))
                        dpg.add_file_extension(".txt", color=(120, 200, 120))
                        dpg.add_file_extension(".json", color=(120, 200, 120))
                        dpg.add_file_extension(".*")
                # Several effects paint with SEGCOLOR(0), and the CubeFX audio
                # palettes read all THREE when their source is one of WLED's
                # segment-colour palettes - "* Color 1" takes the primary,
                # "* Colors 1&2" the first two, "* Color Gradient" and
                # "* Colors Only" all three. Without these the only way to
                # choose the colours those palettes draw from was to edit them
                # in code. WLED's DEFAULT_COLOR is amber; 2 and 3 start black,
                # as they do on the device.
                with Section(app, "colours", "COLOURS"):
                    for _ci, _lbl in enumerate(("primary", "secondary", "tertiary")):
                        form.colour(_lbl, app.rgb_of(app.seg_cols[_ci]), f"seg_col_{_ci}",
                                    lambda c, i=_ci: app.on_color(i, c))
                with Section(app, "parameters", "PARAMETERS"):
                    with dpg.group(tag="scrub_row", show=False):
                        form.note("paused - scrub the last seconds", color=SECTION, tag="scrub_note")
                        with form.row("frame"):
                            num.add("scrub", 0, 0, 1, integer=True, width=-1,
                                    callback=lambda s, v: setattr(self_app[0], "scrub", int(v)))
                    dpg.add_group(tag="params")
                with Section(app, "audio", "AUDIO"):
                    dpg.add_group(tag="audio_rows")
                    for key, lab, val, lo, hi, attr in (
                            ("vol",  "volume", 90,  0,  255, "vol"),
                            ("bass", "bass",   45,  0,  255, "bass"),
                            ("mid",  "mid",    50,  0,  255, "mid"),
                            ("treb", "treble", 35,  0,  255, "treb"),
                            ("bpm",  "tempo",  120, 30, 200, "bpm")):
                        app.pair("audio_rows", key, lab, val, lo, hi,
                                 lambda v, a=attr: setattr(app.syn, a, int(v)), unit="bpm" if key == "bpm" else "")
                    form.check("auto beat", default_value=True,
                               callback=lambda s, v: setattr(app.syn, "auto_beat", v))
                    # Gate a band and it goes silent between beats, jumping to its
                    # slider level on one. Only the bass ever had a transient
                    # otherwise, so mid and treble could not be judged on how an
                    # effect answers a hit.
                    with form.row("gate to beat", tip="a gated band is silent between beats and jumps to its level on one"):
                        for attr, lab in (("gate_bass", "bass"), ("gate_mid", "mid"),
                                          ("gate_treb", "treble")):
                            dpg.add_checkbox(label=lab, tag=f"chk_{attr}", user_data=attr,
                                             callback=lambda s, v, u: setattr(app.syn, u, bool(v)))
                    form.check("silence (mute all bands)",
                               callback=lambda s, v: setattr(app.syn, "muted", v))
                    # named and explained: unlabelled, the strip between beats read as a stray scrollbar
                    with form.row("beat", tip="lights up on each beat the audio has (the synth's, a file's or live)"):
                        with dpg.group():                       # level with the label's line: a 6 px strip sat at its top
                            dpg.add_spacer(height=px(6))
                            dpg.add_color_button(tag="beat_led", default_value=(42, 47, 58, 255),
                                                 width=px(220), height=px(6), no_border=True)
                with Section(app, "live", "LIVE AUDIO"):
                    try:
                        from native.audio import list_inputs
                        _devs = ["system output"] + [n for _, n in list_inputs()]
                    except Exception:
                        oops.swallowed()
                        _devs = ["system output"]
                    with form.row("source"):
                        dpg.add_combo(_devs, tag="live_dev", width=-1, default_value=_devs[0])
                    with form.under():
                        dpg.add_button(label="use live audio", tag="live_btn",
                                       callback=lambda: app.toggle_live())
                        dpg.add_button(label="play an audio file...", callback=lambda: dpg.show_item("wav_dialog"))
                    with dpg.file_dialog(directory_selector=False, show=False, tag="wav_dialog", width=px(620), height=px(420),
                                         callback=lambda s, a: app.start_file_audio(a.get("file_path_name", ""))):
                        from native.audio import AUDIO_EXTS
                        dpg.add_file_extension("{" + ",".join(AUDIO_EXTS) + "}", color=(120, 200, 120))   # every kind, one filter
                        for _ext in AUDIO_EXTS:
                            dpg.add_file_extension(_ext, color=(120, 200, 120))
                        dpg.add_file_extension(".*")
                    dpg.add_group(tag="gain_row")
                    app.pair("gain_row", "live_gain", "live gain", 3.0, 0.2, 12.0,
                             lambda v: setattr(app.live, "gain", float(v)) if app.live else None,
                             is_float=True, unit="×")
                    with form.row("level"):
                        dpg.add_progress_bar(tag="lvl_bar", default_value=0.0, width=-1)
                    dpg.add_text("", tag="live_msg", wrap=0)
                    with form.row("send to WLEDs", tip="the sound the effects here hear - the synth, live audio or a file - "
                                                      "sent as audioreactive's audio sync, so any WLED set to receive it moves "
                                                      "to it too: multicast as WLEDs send it, broadcast where the network "
                                                      "drops multicast, unicast to the active device only. A device "
                                                      "receives with its audio input set to network sound only "
                                                      "(Device > Audio input), or Sync set to Receive in its own settings"):
                        from native.audio_sync import MODES as _sync_modes
                        dpg.add_combo(list(_sync_modes), tag="audio_sync_mode", width=-1, default_value="off",
                                      callback=lambda s, v: app.set_audio_sync(v))
                    dpg.add_text("", tag="audio_sync_msg", wrap=0)
                with Section(app, "video", "VIDEO"):
                    video_ui.build(app)                  # a webcam, a video file or the test pattern, for the Video node
                app.sec_apply_order()
        with dpg.group(tag="footer"):
          with dpg.group(horizontal=True, tag="stat_row"):
              # the button first: the figures after it change length every frame (the LED under the pointer, the
              # current), and a button after them - and its popover, placed over it - jumped about with them
              dpg.add_button(label="stats", tag="stat_more", small=True, callback=lambda: chrome.toggle_stats(app))
              chrome.tip("every figure: the picture's brightness, contrast, unlit share and saturation; the effect's, "
                         "the device's and the studio's time; the current and the limiter - live while open")
              typeface.mono(dpg.add_text("", tag="stat_txt"))     # power and the device's fps (C18)
          messages.build(app, "footer")               # the latest message, the problems that stay, the log (C10)
    chrome.build_dialogs(app)
    chrome.build_stats_popover(app)                  # the footer's stats button's figures (C18)
    messages.build_log(app)                          # the log's window: Window > Message log, the footer's log (C10)
    chrome.build_pane_menus(app)
    room.build(app)                                  # the graph's room: the rail, the windows over the canvas
    dock.build(app)                                  # the tab strip over the side panel's column (C8)
    device_ui.refresh_devices(app)                   # the known devices into the frame and the menu
    from native import palette_ui
    palette_ui.sync(app)                             # the project's custom palettes into the engine and the combos

    app._themes['normal'] = apply_theme(app.prefs)
    _cols = theme_colors(app.prefs)
    _was = chrome.colours()                          # what the window was built in: the dark defaults
    chrome.ACCENT = tuple(_cols["accent"]) + (255,)
    chrome.TEXT = tuple(_cols["text"]) + (255,)
    chrome.DIM = tuple(_cols["dim"]) + (255,)
    chrome.BG, chrome.PANEL, chrome.LINE = (tuple(_cols[k]) + (255,) for k in ("bg", "panel", "line"))
    chrome.recolour_texts(_was, chrome.colours())    # a light project starts light, not with the dark theme's lines
    weight.rebind()                                  # the weighed buttons in the project's colours (built in the defaults)
    app._themes['present'] = present_theme()
    app.rebuild_params()
    app.rebuild_geom_fields()
    app.restore_segments()
    files = app.project.effect_files()
    if files:
        app.edit_open(files[0])
    gfiles = app.gp.files()
    if gfiles:
        app.gp.open(gfiles[0])
    # A splitter is a thin button placed between two panes; dragging it
    # moves the boundary. Enough for any arrangement of the three slots.
    for i in range(2):
        dpg.add_button(label="", tag=f"vsplit_{i}_0", width=px(8), height=px(470), show=False, parent="root")
        app._splitters[f"vsplit_{i}_0"] = ("v", i, 0)
    for i in range(3):
        for j in range(2):
            dpg.add_button(label="", tag=f"hsplit_{i}_{j}", width=px(470), height=px(8), show=False, parent="root")
            app._splitters[f"hsplit_{i}_{j}"] = ("h", i, j)
    # where a dragged pane would land, drawn over everything
    with dpg.viewport_drawlist(front=True, tag="ref_dl"):      # reference meshes as wireframes over the 3-D view
        pass
    with dpg.viewport_drawlist(front=True, tag="shape_dl"):    # the shape editor's rings and wiring line
        pass
    with dpg.viewport_drawlist(front=True, tag="snap_dl"):
        dpg.draw_rectangle((0, 0), (10, 10), tag="snap_rect", show=False, thickness=2,
                           color=tuple(chrome.ACCENT[:3]) + (230,), fill=tuple(chrome.ACCENT[:3]) + (50,))
        dpg.draw_line((0, 0), (10, 10), tag="knife_line", show=False, thickness=2, color=(240, 90, 90, 230))
        # the ghost of a pane or panel section being dragged: its outline, translucent, under the pointer
        dpg.draw_rectangle((0, 0), (10, 10), tag="ghost_rect", show=False, thickness=2, rounding=5,
                           color=tuple(chrome.ACCENT[:3]) + (200,), fill=tuple(chrome.ACCENT[:3]) + (28,))
        typeface.draw_text((0, 0), "", px(14), tag="ghost_text", show=False, color=tuple(chrome.ACCENT[:3]) + (230,))
        # the wiring a dragged node would splice into: two curves, drawn while the pointer is on the wire, as the
        # runs of them on the canvas (graph_ui._splice_draw)
        dpg.add_draw_node(tag="splice_lines")
    dpg.set_primary_window("root", True)
    # set_primary_window puts its own window flags in place of the window's: no scrollbar and no wheel scroll again
    # (without them the panes' few pixels of rounding past the window's size made it scroll, wheel and all)
    dpg.configure_item("root", no_scrollbar=True, no_scroll_with_mouse=True)
    app.frames = glow.Frames()
    chrome.apply_frames(app)
    # Callbacks are taken off Dear PyGui's own schedule and run at the top of
    # each pass of the loop below, before the frame is drawn. Otherwise they
    # run inside render_dearpygui_frame() - a callback that changes the
    # geometry while draw() is halfway through reading the engine gave a
    # mismatched mask once - and a widget deleted from a callback can be the
    # very one the renderer is walking.
    dpg.configure_app(manual_callback_management=True)
    dpg.setup_dearpygui()
    app.relayout()
    # Both views follow the window from here on. Without this, maximising left
    # two small pictures marooned in the corner of a large empty panel.
    dpg.set_viewport_resize_callback(lambda s, d: app.request_layout())


class _Tail:
    """stdout with the last lines kept, for Help > Report a problem."""
    def __init__(self, out, n=300):
        import collections
        self.out, self.lines, self._buf = out, collections.deque(maxlen=n), ""

    def write(self, s):
        self.out.write(s)
        self._buf += s
        *done, self._buf = self._buf.split("\n")
        self.lines.extend(done)

    def flush(self):
        self.out.flush()

    def __getattr__(self, k):
        return getattr(self.out, k)


def main():
    if sys.stdout is not None and not isinstance(sys.stdout, _Tail):
        sys.stdout = _Tail(sys.stdout)
    app = App()
    app._log_tail = sys.stdout.lines if isinstance(sys.stdout, _Tail) else ()
    build(app)
    dpg.show_viewport()
    app.drops = DropFiles("WLED Effects Studio")
    os.makedirs(GIF_DIR, exist_ok=True)
    crash = scratch.path("crash.txt")        # None: no folder of this user's alone to be had (the traceback: the console)
    try:                                     # this run's own file; the last run's kept beside it
        if crash and os.path.lexists(crash):
            os.replace(crash, os.path.join(SHOT_DIR, "crash.prev.txt"))
    except OSError:
        pass
    print(f"if a frame throws, the traceback lands in {crash or 'the console alone (no private scratch folder)'}")
    if REMOTE:
        print(f"frame capture: create {SHOT_REQ} to get a PNG at {SHOT_PNG}")
        print(f"remote control: write a JSON list of commands to {CMD_FILE}")
    else:
        print("remote control: off (the tests turn it on with STUDIO_REMOTE_CONTROL=1)")
    from native import update as _update
    if _update.due(app.prefs) and not os.environ.get("STUDIO_NO_UPDATE_CHECK"):
        chrome.check_updates(app)                    # once a day, on a thread; the tests set STUDIO_NO_UPDATE_CHECK
    reader_ui.maybe_welcome(app)                     # the first run's panel; the tests set STUDIO_NO_WELCOME
    app.report_project_load()                        # a project.json that did not read: said now the window is up
    try:
        from native import vj_ui as _vj_ui
        _vj_ui.project_changed(app)                  # the project's own looks and the packs' listed from the start
    except Exception:                                # (the phone, the pads and MIDI read them, the VJ shown or not)
        import traceback
        traceback.print_exc()
    try:
        while dpg.is_dearpygui_running():
            jobs = None
            try:
                jobs = dpg.get_callback_queue()
            except Exception:
                import traceback
                traceback.print_exc()
            for job in jobs or ():                   # each on its own: one that fails leaves the rest to run
                if job[0] is None:
                    continue
                try:
                    num.call(job[0], *job[1:4])      # defaulted parameters keep their defaults (num.call)
                except Exception:
                    import traceback
                    traceback.print_exc()
            if app._need_layout:
                app._need_layout = False
                app.relayout()
            try:
                _t = [time.perf_counter()]
                app.poll_build()
                app.gp.poll()
                app.poll_watch()
                chrome.poll(app)
                app.poll_devices()
                app.poll_stream()
                app.poll_autosave()
                app.poll_view_mode()
                view3d.poll(app)                     # the camera's easing, before anything draws with it
                app.poll_drops()
                app.poll_popouts()
                app.poll_menus_fit()
                if app.code_ed is not None and app.layout == "edit":
                    app.code_ed.poll()
                app.poll_glow()
                render_video.advance(app)            # rendering a video: the show a frame's time on (native/clock.py)
                render_fseq.advance(app)             # exporting for FPP: the same
                device_ui.poll(app)                  # after poll_glow: its overlays keep off this frame's holes
                tasks.poll(app)                      # what a device answered, from the workers (native/tasks.py)
                dock.poll(app)                       # a frame's tab closed by its x
                chrome.poll_dialogs()                # the dialogs' closes at their top right
                chrome.poll_placed_tips()            # the words of controls placed at their own position (their tooltips never show)
                chrome.poll_windows(app)             # the Window menu's checks: which frames are open
                messages.poll(app)                   # a note's time on the footer's line; the open log follows
                app.poll_present_hint()              # how to leave presentation, for a few seconds after entering it
                midi_ui.poll(app)
                phone_ui.poll(app)                   # the phone remote's commands, and the state its page shows
                pads_ui.poll(app)                    # the VJ's pads: drawn and played while their window is open
                bank_ui.poll(app)
                reader_ui.poll(app)
                room.poll(app)
                weight.poll(app)                     # what has nothing to act on, greyed
                chrome.pin_sideways()                # no pane nudged sideways by a few pixels of overrun
                app.poll_calibration()
                app.poll_wiring_read()
                app.poll_stream_wiring()
                chrome.poll_update(app); chrome.poll_update_download(app)
                modulate._flush(app, clock.now())    # a modulator turned while paused saved too (apply runs only playing)
                _t.append(time.perf_counter())
                app.step_sim()
                _t.append(time.perf_counter())
                app.draw()
                render_video.capture(app)            # rendering a video: this frame of the show into it
                render_fseq.capture(app)             # exporting for FPP: this frame's LEDs into the file
                _t.append(time.perf_counter())
                app._prof = [(b - a) * 1000.0 for a, b in zip(_t, _t[1:])]
            except Exception:
                oops.swallowed()
                # One bad frame should not take the window down with it. The
                # traceback goes to the console AND to a file, because the
                # console scrolls away and the interesting one is always the
                # first, not the hundredth.
                import traceback
                tb = traceback.format_exc()
                if tb != getattr(app, "_last_tb", None):     # the same frame failing the same way is written once
                    app._last_tb = tb
                    traceback.print_exc()
                    try:
                        scratch.write_text(crash, tb + "\n", append=True)     # not through a link
                    except Exception:
                        oops.swallowed()
                    app.gp.status(f"a frame failed: {tb.strip().splitlines()[-1][:90]}" + (" - see crash.txt" if crash else ""), "error")
                app.playing = False
            _r0 = time.perf_counter()
            dpg.render_dearpygui_frame()
            _now = time.perf_counter()
            if getattr(app, "_prof", None) is not None:
                app._prof.append((_now - _r0) * 1000.0)
                for _n, _ms in zip(frametime.TOP, app._prof):
                    frametime.add(_n, _ms)               # the stats popover's "where the time goes"
                pf = getattr(app, "_prof_avg", None)
                app._prof_avg = app._prof if pf is None else [x * 0.95 + y * 0.05 for x, y in zip(pf, app._prof)]
            if app._loop_t:
                app.loop_ms = app.loop_ms * 0.95 + (_now - app._loop_t) * 1000.0 * 0.05
            app._loop_t = _now
            service_capture()
            service_command(app)
    finally:
        app.stop_live()
        app.popouts.close_all()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
