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
import re
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import num
from native import render_video, render_fseq, modulate, mixer
from native import typeface
from native import form
from native import dock
from native import messages

import queue
import threading

from native.engine import Engine, stats
from native.synth import Synth
from native.geometry import Geometry, KINDS
from native.project import (default_project, Project, list_projects, project_path, remember_project, PROJECTS, pref_num,
                            load_prefs, save_prefs)
from native.graph_ui import GraphPanel, build_panel
from native import chrome, glow, device_ui, shape_ui, midi_ui, phone_ui, bank_ui, procs, reader_ui, room, weight, view3d, shape_tools, tasks
from native.gpucube import CubeQuads
from native import look
from native import video_ui
from native.textures import registry as tex_registry
from native.theme import THEME_PRESETS, theme_colors, theme_is_light, minimap_colours
from native.features import Features
from native.recorder import Recorder, GIF_DIR
from native.edit_build import EditBuild
from native import paths as _paths
from native.popout import Popouts
from native.dropfiles import DropFiles
from native.codeedit import CodeEditor
from native.keys import Keymap, combo as key_combo
from native import render
from native.apiref import API
from native import scratch
from native.remote import SHOT_DIR, SHOT_REQ, SHOT_PNG, CMD_FILE, REMOTE, service_capture, service_command
import shutil
import sys

STEP = 23
CUBE_MAX = 620          # cube render cost is quadratic in this, so it is capped
                        # and the image is scaled up if the pane is larger
# laid out at 100% and at the interface size (typeface.py) from here on
VIEW_MIN = px(180)
CAP_H = px(48)          # a view pane above its picture: padding, the grip and caption row, spacing; and the padding below
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


class App(Features, Recorder, EditBuild):
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
        rgb = self.frame_rgb(eng).copy()
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
            src = net if net.shape[0] == eng.rows else self.frame_rgb(eng)
            lk = self.view_look()
            if lk["glow"] > 0 or lk["diffuse"] > 0:        # the glowing or diffused LEDs, as the live view's texture has them
                k = 8                                      # finer than the live texture: no GPU smooths a picture's dots
                return render.render(look.led_texture(src, k, lk, unlit, B=eng.B), eng.B * k, px, self.yaw, self.pitch,
                                     self.dist, six=eng.six, bg=bgv, unlit=None, floor=floor,
                                     reflect=lk["reflect"], **view3d.kw(self))
            return render.render(src, eng.B, px, self.yaw, self.pitch, self.dist, six=eng.six, bg=bgv,
                                 unlit=unlit, floor=floor, reflect=lk["reflect"], **view3d.kw(self))
        rgb = self.frame_rgb(eng).reshape(-1, 3)
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
        from native import sequence_ui
        src = sequence_ui.show_source(self) or self.live or self.syn     # the show's audio while it plays, if it has any
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
                pass
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
                    pass
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
            pass

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
            pass

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

    # --- projects ---------------------------------------------------------------------
    # One folder per project under studio/projects/ (or anywhere, by path).
    # Switching swaps the project object, applies its geometry, re-lists its
    # effects and graphs, and rebuilds the engine for its effects list.
    def set_feature(self, key, value):
        """The flash dialog's picker: a feature on or off for this project;
        the graph's nodes that lean on it follow."""
        from native import flash
        f = flash.features_of(self.project)
        f[key] = value
        self.project.options["features"] = f
        self.project.save()
        self.gp.refresh_features()
        chrome.refresh_usermods(self)

    def set_usermod(self, name, on):
        """The manager's checkbox: a usermod built or left out for this
        project, whatever the environment says."""
        from native import flash
        f = flash.features_of(self.project)
        f["usermods"][name] = bool(on)
        self.project.options["features"] = f
        self.project.save()
        chrome.refresh_usermods(self)

    def add_usermod(self, name):
        """A usermod from this tree onto the project's list, on."""
        from native import flash
        if name not in flash.usermod_dirs():
            self.gp.status(f"no usermods/{name} in this tree"); return
        self.set_usermod(name, True)
        self.gp.status(f"{name} added to the project's usermods")

    def remove_usermod(self, name):
        """Off the project's list (the folder stays in the tree); one the
        environment builds goes back to the environment's say."""
        from native import flash
        f = flash.features_of(self.project)
        f["usermods"].pop(name, None)
        self.project.options["features"] = f
        self.project.save()
        chrome.refresh_usermods(self)
        self.gp.status(f"{name} removed from the project's list")

    def import_usermod(self, path):
        """A folder or a zip from anywhere, into the tree and onto the list."""
        from native import flash
        try:
            name = flash.import_usermod(path)
        except Exception as e:
            self.gp.status(f"could not import: {e}")
            if dpg.does_item_exist("um_status"):
                dpg.set_value("um_status", f"could not import: {e}")
            return
        self.set_usermod(name, True)
        self.gp.status(f"imported usermods/{name}")

    def report_project_load(self):
        """A project.json that did not read, said where it cannot be missed:
        a problem in the messages and a dialog. The project then runs on
        the defaults, its old settings kept in project.json.bad-<time>."""
        err = getattr(self.project, "load_error", None)
        messages.clear(self, "project:load")
        if err:
            print("project:", err)
            messages.post(self, err, "error", key="project:load")
            chrome.confirm(self, "The project's settings did not read", err, [("OK", None)])

    def switch_project(self, path, create=False):
        path = project_path(path)
        if not create and not os.path.isdir(path):
            dpg.set_value("edit_status", f"no project at {path}"); return
        if self.edit_dirty:
            self.edit_save()
        if self.gp.graph:
            self.gp.save()
        self.project = Project(path)
        messages.clear(self, "")                         # the last project's problems are not this one's
        shape_ui.forget(self)                            # nor its shape's undo steps and selection
        self._code_undo, self._code_redo = [], []        # nor the code pane's (they reached the next file opened)
        self.report_project_load()
        if create:
            from native import flash
            self.project.options["features"] = dict(flash.NEW_DEFAULTS)     # no hardware assumed until ticked
        remember_project(path)
        self.edit_file = None
        self.gp.graph = None; self.gp.file = None; self.gp.stack.clear()
        self.apply_geometry(self.project.geometry)
        dpg.set_value("geom_kind", self.project.geometry.kind)
        self.rebuild_geom_fields()
        self.restore_segments()
        dpg.configure_item("edit_file", items=self.project.effect_files()); dpg.set_value("edit_file", "")
        dpg.set_value("code", "")
        self.gp.refresh_lib()
        dpg.configure_item("graph_file", items=self.gp.files()); dpg.set_value("graph_file", "")
        self.gp.rebuild()
        self.refresh_import_buttons()
        self.refresh_project_list()
        self._active_state = None
        device_ui.refresh_devices(self)
        from native import palette_ui
        palette_ui.sync(self); palette_ui.refresh(self)
        name = os.path.basename(path)
        dpg.set_value("edit_status", f"project {name}"); self.gp.status(f"project {name}")
        # the engine holds the previous project's drafts: build this one's list
        self.edit_build()

    def send_ledmap(self, sure=False):
        """The ledmap to the device - its wiring changes, so it asks first."""
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        g = self.project.geometry
        if not sure:
            chrome.confirm(self, "Send the ledmap?",
                           f"The device at {host} will map its LEDs as this project's geometry does ({g.describe()}): "
                           "its picture changes, and a wiring that is not the device's leaves it dark or scrambled until "
                           "the ledmap is removed. Send it?",
                           [("Send", lambda: self.send_ledmap(True), "danger"), ("Cancel", None)])
            return
        from native import tasks

        def done(msg):
            dpg.set_value("edit_status", msg); self.gp.status(msg); device_ui.send_log(self, msg)
        # on a worker, as send_shape's: a device that does not answer held the whole studio for the upload's 5 s
        lm = self.project.geometry.ledmap()           # made here: the worker must not read a geometry being changed
        tasks.run(self, "send:ledmap", f"sending the ledmap to {host}", lambda: self.project.send_ledmap(host, lm), done)

    def send_shape(self, sure=False):
        """The geometry to the device: its ledmap (the wiring), and its
        position table when it is a shape cfx_pos has no rule for."""
        from native import flash
        host = self.active_host()
        if not host:
            device_ui.show(self, "devices"); self.gp.status("choose a device first"); return
        g = self.project.geometry
        if not sure:
            chrome.confirm(self, "Send the shape?",
                           f"The device at {host} gets this project's ledmap ({g.describe()}) and, for a shape, the "
                           "positions table the effects read. Its wiring changes with the ledmap. Send both?",
                           [("Send", lambda: self.send_shape(True), "danger"), ("Cancel", None)])
            return
        lm = g.ledmap()                               # made here, as the worker must not read a geometry being changed

        def work():                                   # on a worker: a device that does not answer froze the studio
            msg = self.project.send_ledmap(host, lm)
            ok, msg2 = flash.send_geometry(host, g)
            return msg + "; " + msg2

        def done(msg):
            dpg.set_value("edit_status", msg); self.gp.status(msg); device_ui.send_log(self, msg)
        tasks.run(self, "send:shape", f"sending the shape to {host}", work, done)

    def new_project(self, name):
        name = (name or "").strip()
        if not name:
            dpg.set_value("edit_status", "type a project name first"); return
        path = project_path(name)
        if os.path.isdir(path):
            self.switch_project(path); return
        self.switch_project(path, create=True)

    def export_project_zip(self):
        """The project as one zip in captures/ - to keep, or to hand over."""
        from native.project import zip_project
        if self.edit_dirty:
            self.edit_save()
        if self.gp.graph:
            self.gp.save()
        self.project.save()
        try:
            path = zip_project(self.project)
        except Exception as e:
            self.gp.status(f"project zip failed: {e}"); return
        msg = f"project zipped: {path} ({os.path.getsize(path) // 1024} KB)"
        dpg.set_value("edit_status", msg); self.gp.status(msg)

    def import_project_zip(self, path, sure=False):
        """A project zip into projects/, opened. Asked first: its effects are C++ that opening it builds and runs
        on this computer (`sure`: asked already)."""
        from native.project import unzip_project
        if not path:
            return
        if not sure:
            from native.graph_files import trust_words
            chrome.confirm(self, "Open this project?", trust_words("project", os.path.basename(path)),
                           [("Open it", lambda: self.import_project_zip(path, True)), ("Cancel", None)])
            return
        try:
            dest = unzip_project(path)
        except Exception as e:
            self.gp.status(f"project import failed: {e}"); return
        self.switch_project(dest)
        self.gp.status(f"project imported: {os.path.basename(dest)}")

    def refresh_project_list(self):
        if dpg.does_item_exist("project_combo"):
            names = list_projects()
            cur = os.path.basename(self.project.path)
            if os.path.dirname(self.project.path) != PROJECTS and cur not in names:
                names.append(self.project.path)
                cur = self.project.path
            dpg.configure_item("project_combo", items=names)
            dpg.set_value("project_combo", cur)

    # --- the external editor and the file watcher -------------------------------------
    # The in-app box is for quick fixes. For real editing the file opens in
    # whatever editor the system has - VS Code if it is on the path, else the
    # .cpp association - and the watcher reloads the pane (and rebuilds, when
    # "watch" is ticked) each time the file is saved there. Click-to-line
    # goes to the same editor, since the in-app box cannot move its cursor.
    def _mtime(self, fname):
        try:
            return os.path.getmtime(self.project.effect_path(fname))
        except OSError:
            return None

    def editor_command(self):
        """The command that opens a file at a line, as a list with {file} and
        {line} holes; from project options, else VS Code, else none."""
        cmd = self.project.options.get("editor")
        if cmd:
            return cmd if isinstance(cmd, list) else cmd.split()
        code = shutil.which("code") or shutil.which("code.cmd")
        if code:
            return [code, "-g", "{file}:{line}"]
        return None

    def open_external(self, line=1):
        if not self.edit_file:
            return
        if self.edit_dirty:
            self.edit_save()
        path = self.project.effect_path(self.edit_file)
        cmd = self.editor_command()
        try:
            if cmd:
                procs.popen([c.replace("{file}", path).replace("{line}", str(line)) for c in cmd])
                dpg.set_value("edit_status", f"opened in {os.path.basename(cmd[0])} - saves there reload here")
            elif hasattr(os, "startfile"):
                os.startfile(path)
                dpg.set_value("edit_status", "opened in the system's .cpp editor - saves there reload here")
            else:
                opener = shutil.which("xdg-open") or shutil.which("open")
                if opener:
                    procs.popen([opener, path])
                dpg.set_value("edit_status", "opened externally - saves there reload here")
        except Exception as e:
            dpg.set_value("edit_status", f"could not open an editor: {e}")
        if dpg.does_item_exist("edit_watch"):
            dpg.set_value("edit_watch", True)

    def poll_watch(self):
        """Twice a second: has the file been saved outside? Then the pane
        takes the new text, unless it has unsaved edits of its own, and a
        watched file rebuilds."""
        now = time.time()
        if now - self._watch_at < 0.5 or not self.edit_file:
            return
        self._watch_at = now
        m = self._mtime(self.edit_file)
        if m is None or m == self._watch_mtime:
            return
        self._watch_mtime = m
        if self.edit_dirty:
            dpg.set_value("edit_status", f"{self.edit_file} changed on disk - unsaved edits here, not reloaded")
            return
        dpg.set_value("code", self.project.read_effect(self.edit_file))
        dpg.set_value("edit_status", f"{self.edit_file} reloaded from disk")
        if dpg.does_item_exist("edit_watch") and dpg.get_value("edit_watch") and not self.building:
            self.edit_build()

    def goto_code(self, fname, line):
        """A message's line of code: the file open in the code pane, at the line."""
        if fname and fname not in self.project.effect_files():
            self.gp.status(f"{fname} is not one of this project's effects"); return
        if fname and fname != self.edit_file:
            self.edit_open(fname)
        self.show_pane("edit")
        self.goto_line(line)

    def goto_line(self, line):
        """An error or find row was clicked: the editor goes to that line;
        the external editor too when the file is being watched there."""
        text = dpg.get_value("code").split("\n")
        if 1 <= line <= len(text):
            dpg.set_value("edit_status", f"line {line}: {text[line - 1].strip()[:90]}")
        if self.code_ed is not None:
            self.code_ed.goto(line)
            self.code_ed.focus = True
            dpg.focus_item("code_key")
        if dpg.get_value("edit_watch"):
            self.open_external(line)

    # --- find and replace ----------------------------------------------------------------
    def _find_setup(self):
        """The find text and its options into the editor; the needle."""
        needle = dpg.get_value("find_text")
        if self.code_ed is not None:
            self.code_ed.set_needle(needle, case=dpg.get_value("find_case") if dpg.does_item_exist("find_case") else None,
                                    word=dpg.get_value("find_word") if dpg.does_item_exist("find_word") else None)
        return needle

    def find(self, backwards=None):
        """Find: the next match (Shift+Enter, the previous), the place and
        count in the status, and every matching line as rows that go to
        the line."""
        needle = self._find_setup()
        dpg.delete_item("edit_errors", children_only=True)
        if backwards is None:
            backwards = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
        if self.code_ed is not None and needle:
            self.code_ed.find_next(backwards)
            self.code_ed.focus = True
            dpg.focus_item("code_key")
        if not needle:
            dpg.set_value("edit_status", ""); return
        self.find_status()
        if self.code_ed is not None:
            hits = sorted({li for li, _ in self.code_ed.matches()})
            lines = self.code_ed.lines
        else:
            lines = dpg.get_value("code").split("\n")
            hits = [i for i, l in enumerate(lines) if needle.lower() in l.lower()]
        for li in hits[:40]:
            self._error_row(f"{li + 1}: {lines[li].strip()}", li + 1, lambda s, a, u: self.goto_line(u))

    def _error_row(self, text, user_data, callback):
        """A row under the code (a compiler message, a find hit): as wide as the pane lets it be, ending in "..."
        when longer, the whole of it on hover - at 140 characters a message ran past the pane, which scrolled."""
        avail = (dpg.get_item_rect_size("edit_win")[0] or px(420)) - px(40)
        shown = chrome._fit_text(text, avail)
        row = dpg.add_selectable(label=shown, parent="edit_errors", user_data=user_data, callback=callback)
        if shown != text:
            chrome.tip(text, item=row)
        return row

    def find_status(self):
        if self.code_ed is None:
            return
        k, n = self.code_ed.find_place()
        dpg.set_value("edit_status", (f"{k} of {n}" if k else f"{n} match(es)") if n else "no match")

    def replace_one(self):
        """The match the cursor is on becomes the replacement, and the next is found."""
        needle = self._find_setup(); repl = dpg.get_value("replace_text")
        if not needle or self.code_ed is None:
            return
        done = self.code_ed.replace_current(repl)
        self.edit_dirty = self.edit_dirty or done
        self.find_status()
        if done:
            dpg.set_value("edit_status", "replaced one - " + dpg.get_value("edit_status"))

    def replace_all(self):
        needle = self._find_setup(); repl = dpg.get_value("replace_text")
        if not needle:
            return
        if self.code_ed is not None:
            self.code_ed._sync_from_store()
            rx = self.code_ed._needle_re
            text = "\n".join(self.code_ed.lines)
            new, n = rx.subn(lambda m: repl, text)
        else:
            text = dpg.get_value("code")
            n = text.count(needle); new = text.replace(needle, repl)
        if n:
            dpg.set_value("code", new)
            self.edit_dirty = True
        dpg.set_value("edit_status", f"replaced {n} occurrence(s)")
        self.find()

    # --- the metadata string, as a form ----------------------------------------------
    # Name@slider labels;colour labels;palette;flags;defaults - a line most
    # people get wrong once. The form reads it out of the pane and writes it
    # back, so the fields are edited by name.
    META_FIELDS = ("meta_name", "meta_labels", "meta_colours", "meta_flags", "meta_defaults")

    def meta_read(self):
        m = re.search(r'PROGMEM\s*=\s*"([^"]*)"', dpg.get_value("code"))
        if not m:
            dpg.set_value("edit_status", "no metadata string in this file"); return
        text = m.group(1)
        name, _, rest = text.partition("@")
        parts = (rest.split(";") + ["", "", "", "", ""])[:5]
        for tag, v in zip(self.META_FIELDS, [name, parts[0], parts[1], parts[3], parts[4]]):
            dpg.set_value(tag, v)
        dpg.set_value("edit_status", "metadata read from the file")

    def meta_write(self):
        code = dpg.get_value("code")
        m = re.search(r'(PROGMEM\s*=\s*")([^"]*)(")', code)
        if not m:
            dpg.set_value("edit_status", "no metadata string in this file"); return
        name, labels, colours, flags, defaults = (dpg.get_value(t).replace('"', "'").replace(";", " ") if t == "meta_name"
                                                  else dpg.get_value(t).replace('"', "'") for t in self.META_FIELDS)
        new = f"{name}@{labels};{colours};!;{flags};{defaults}"
        dpg.set_value("code", code[:m.start(2)] + new + code[m.end(2):])
        self.edit_dirty = True
        dpg.set_value("edit_status", f"metadata: {new[:100]}")

    def api_pick(self, snippet, label):
        """A click on the API reference puts the snippet at the cursor (the
        in-app editor takes an insertion); the clipboard gets it too, for
        an external editor."""
        dpg.set_clipboard_text(snippet)
        if self.code_ed is not None and dpg.does_item_exist("code_ed"):
            self.code_ed.insert(snippet)
            dpg.set_value("edit_status", f"inserted at the cursor: {label} (and copied)")
        else:
            dpg.set_value("edit_status", f"copied: {label} - Ctrl+V to paste at the cursor")

    def refresh_import_buttons(self):
        """The File menu says what it will do to the current file, and its
        open lists follow the project."""
        chrome.refresh_files(self)

    def toggle_import(self, fname):
        """A draft joins the effects list, or leaves it. Either way the engine
        is rebuilt so the roster shows the list as it now is."""
        if not fname or fname not in self.project.effect_files():
            return
        on = not self.project.is_imported(fname)
        self.project.set_imported(fname, on)
        self.refresh_import_buttons()
        title = self.project.effect_title(fname)
        msg = f"{title} added to the effects list" if on else f"{title} removed from the effects list"
        dpg.set_value("edit_status", msg); self.gp.status(msg)
        self.edit_build()

    def ensure_built(self):
        """The file just opened for editing is previewed: if the engine does
        not have it - a draft that was not the last one built - build now."""
        if self.edit_file and self.project.effect_title(self.edit_file) not in self.eng.names:
            self.edit_build()

    def edit_rename(self, title):
        """The current effect takes a new name."""
        title = (title or "").strip()
        if not title or not self.edit_file:
            dpg.set_value("edit_status", "a name is needed to rename")
            return
        if self.edit_dirty:
            self.edit_save()
        new = self.project.rename_effect(self.edit_file, title)
        self.edit_open(new)
        dpg.set_value("edit_status", f"renamed to {title} ({new})")
        self.edit_build()

    def edit_new(self, title=None):
        title = (title or "").strip() or "New Effect"
        fname = self.project.new_effect(title)
        self.edit_open(fname)

    def edit_save(self):
        if not self.edit_file:
            return
        self.project.write_effect(self.edit_file, dpg.get_value("code"))
        self._watch_mtime = self._mtime(self.edit_file)      # the pane's own save: not a change from outside for the watcher
        self.edit_dirty = False
        dpg.set_value("edit_status", f"{self.edit_file} saved")

    # --- undo for the code box -----------------------------------------------
    # The box reports its whole text on every keystroke. Edits within a
    # second of each other share one undo step, as the graph's do, so undo
    # steps back over a word or a line, not a character. (While the box has
    # the keyboard, Ctrl+Z is its own; these are for the menu, the toolbar
    # and the key once the box is left.)
    def on_code_edit(self, s, v):
        self.edit_dirty = True
        self._code_edits = getattr(self, "_code_edits", 0) + 1
        now = time.time()
        if now - self._code_t > 0.6:                     # a pause in typing ends an undo step
            self._code_undo.append(self._code_text)
            del self._code_undo[:-200]
            self._code_redo.clear()
        self._code_t = now
        self._code_text = v

    def _code_reset(self, text):
        self._code_undo, self._code_redo = [], []
        self._code_text, self._code_t = text, 0.0

    def code_undo(self):
        if not self._code_undo:
            dpg.set_value("edit_status", "nothing to undo"); return
        self._code_redo.append(dpg.get_value("code"))
        self._code_text = self._code_undo.pop()
        dpg.set_value("code", self._code_text)
        self.edit_dirty = True
        self._code_t = 0.0
        dpg.set_value("edit_status", f"undo ({len(self._code_undo)} more)")

    def code_redo(self):
        if not self._code_redo:
            dpg.set_value("edit_status", "nothing to redo"); return
        self._code_undo.append(dpg.get_value("code"))
        self._code_text = self._code_redo.pop()
        dpg.set_value("code", self._code_text)
        self.edit_dirty = True
        self._code_t = 0.0
        dpg.set_value("edit_status", f"redo ({len(self._code_redo)} more)")

    def open_graph_code(self):
        """Generate the graph's C++ and show it in the code pane - the hand-off
        for the cases the nodes cannot reach. From here it is a code effect."""
        fname = self.gp.compile(and_build=False)
        if fname:
            self.layout = "edit"; self.ui = True; self.request_layout()
            self.edit_open(fname)

    def on_color(self, i, rgb):
        """A segment colour from its swatch or its hex (0..255 each)."""
        r, g, b = rgb
        self.seg_cols[int(i)] = (r << 16) | (g << 8) | b
        self.eng.colors(*self.seg_cols)
        self._ab_sync()

    @staticmethod
    def rgb_of(c):
        return ((int(c) >> 16) & 255, (int(c) >> 8) & 255, int(c) & 255)

    def refresh_colours(self):
        """The COLOURS rows show the colours in force (a sequence step loaded them)."""
        for i, c in enumerate(self.seg_cols[:3]):
            form.set_colour(f"seg_col_{i}", self.rgb_of(c))

    def _set_param(self, k, v):
        self.eng.fx[k] = int(v)
        self.eng.push()

    def on_check(self, sender, val):
        self.eng.fx[dpg.get_item_user_data(sender)] = 1 if val else 0
        self.eng.push()

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
            pass
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
        cmd = (cmd or "").strip()
        if cmd:
            self.project.options["editor"] = cmd
        else:
            self.project.options.pop("editor", None)
        self.project.save()

    def reset_layout(self):
        """The default sizes; the arrangement stays."""
        self.side_w = SIDE_W
        self.colw = {}
        self.rowh = {}
        for k in ("splits", "side_w", "colw", "rowh"):
            self.prefs.pop(k, None)
        save_prefs(self.prefs)
        self.request_layout()

    # --- the arrangement: which pane sits where ---------------------------------
    # Three slots - "main" (the net, the code or the graph, whichever the
    # layout mode shows), "cube" (the 3-D view) and "side" (the panel) - in
    # columns of rows, left to right, top to bottom. A pane moves by its grip
    # (the ::: at its top right) dragged onto another pane: near an edge it
    # goes beside or above that pane, in the middle the two swap.
    # The fourth slot, "props", is the graph's properties pane: a node's
    # settings too long for the node. It shows in the graph layout only,
    # and it is a pane of its own so selecting a node never moves the
    # editor - the panel it used to grow above the editor did.
    # Then the device frames - "devices", "flash", "send" - which
    # are windows of their own floating over the panes until docked: in
    # the arrangement they are placed like any pane (dock_slot puts one
    # under the main pane; the grip dragged onto a pane, beside it) and
    # out of it they float. OPTIONAL: an arrangement holds any subset.
    PRESETS = (("Classic: main pane, 3-D, panel", [["main"], ["cube", "props"], ["side"]]),
               ("Panel on the left", [["side"], ["main"], ["cube", "props"]]),
               ("3-D on the left", [["cube", "props"], ["main"], ["side"]]),
               ("3-D under the main pane", [["main", "cube"], ["side", "props"]]),
               ("3-D above the panel", [["main"], ["cube", "side"], ["props"]]),
               ("Panel under the 3-D, main pane on the right", [["cube", "side"], ["main", "props"]]))
    CORE = ("main", "cube", "side", "props")
    OPTIONAL = ("devices", "flash", "send", "shape", "sequence", "library", "palettes", "outputs", "audioin", "vj")
    SLOTS = CORE + OPTIONAL

    @classmethod
    def _valid_arrangement(cls, arr):
        try:
            cols = [[str(s) for s in c] for c in arr]
        except Exception:
            return None
        flat = sorted(s for c in cols for s in c)
        if flat == sorted(s for s in cls.CORE if s != "props") and all(cols):
            # saved before the properties pane existed: it goes under the 3-D view
            for c in cols:
                if "cube" in c:
                    c.insert(c.index("cube") + 1, "props")
                    break
            return cols
        core = sorted(s for s in flat if s in cls.CORE)
        extra = [s for s in flat if s not in cls.CORE]
        if core != sorted(cls.CORE) or not all(cols):
            return None
        if any(s not in cls.OPTIONAL for s in extra) or len(set(extra)) != len(extra):
            return None
        return cols

    def docked(self, slot):
        """Whether a frame is part of the layout - a tab in the dock beside
        the side panel's (native/dock.py), or a pane among the panes - rather
        than floating."""
        return dock.in_dock(self, slot) or dock.paned(self, slot)

    def unplace(self, slot):
        """A frame out from among the panes (to be closed, floated or docked by the caller)."""
        if dock.paned(self, slot):
            self.set_arrangement([[s for s in c if s != slot] for c in self.arrangement], to_dock=False)

    def dock_slot(self, slot):
        """A frame into the dock, its tab in front."""
        if slot not in self.OPTIONAL:
            return
        dock.dock_frame(self, slot)
        self.gp.status(f"{dock.NAMES.get(slot, slot)} in the dock; float takes it out over the panes")

    def undock_slot(self, slot):
        """A docked frame out into a window of its own, over the panes."""
        if slot not in self.OPTIONAL:
            return
        dock.float_frame(self, slot)

    def set_arrangement(self, arr, to_dock=True):
        """The panes' places. A frame the arrangement had and this one has not (a preset chosen) goes into the
        dock - unless `to_dock` is off (its caller closes, floats or docks it)."""
        cols = self._valid_arrangement([[s for s in c] for c in arr if c])
        if cols is None:
            raise ValueError(f"not an arrangement: {arr!r}")
        before = [s for c in self.arrangement for s in c if s in self.OPTIONAL] if to_dock else ()
        dock.settle(self, cols, before)
        self.arrangement = cols
        self.prefs["arrangement"] = cols
        save_prefs(self.prefs)
        self.request_layout()

    def move_slot(self, slot, target, zone):
        """`slot` dropped on `target`: beside it (left, right), above or below
        it (top, bottom), or in its place (centre - the two swap)."""
        if slot in self.OPTIONAL and target == "side" and zone == "centre":
            dock.dock_frame(self, slot)              # a frame's grip dropped on the panel: into the dock, its tab in front
            return
        if slot == target or slot not in self.SLOTS or target not in self.SLOTS or zone is None:
            return
        if zone == "centre" and slot in self.OPTIONAL and target in self.CORE:
            return                                   # a frame does not swap with the panes it sits among (drop_zone offers none)
        if slot in self.OPTIONAL:
            dock.take(self, slot)                    # among the panes, where it was dropped: not a tab or a window too
        arr = [list(c) for c in self.arrangement]
        if zone == "centre":
            arr = [[target if s == slot else slot if s == target else s for s in c] for c in arr]
        else:
            arr = [[s for s in c if s != slot] for c in arr]
            arr = [c for c in arr if c]
            ci = next(i for i, c in enumerate(arr) if target in c)
            rj = arr[ci].index(target)
            if zone == "left":
                arr.insert(ci, [slot])
            elif zone == "right":
                arr.insert(ci + 1, [slot])
            elif zone == "top":
                arr[ci].insert(rj, slot)
            else:
                arr[ci].insert(rj + 1, slot)
        self.set_arrangement(arr)

    def pane_of(self, slot):
        """The window a slot shows right now."""
        if slot == "cube":
            return "cube_win"
        if slot == "side":
            return "rail_win" if room.folded(self) else "side_win"
        if slot == "props":
            return "props_win"
        if slot in self.OPTIONAL:
            return f"{slot}_win"
        return {"edit": "edit_win", "graph": "graph_win"}.get(self.layout, "net_win")

    def _place_frame(self, slot, rect):
        """A frame among the panes: its window held at the pane's place and size, with its own header - the title,
        and at the right float, the grip (to move it again) and close - since no tab strip names it."""
        tag = device_ui.FRAMES[slot][0]
        if not dpg.does_item_exist(tag):
            return
        x, y, w, h = rect
        dpg.configure_item(tag, show=True, no_move=True, no_resize=True, no_focus_on_appearing=True, width=w, height=h)
        dpg.set_item_pos(tag, [x, y])
        device_ui.chrome_for(self, slot, docked=False)
        device_ui.place_header(tag, w, False)

    def slot_of(self, pane):
        return next((s for s in self.SLOTS if self.pane_of(s) == pane), None)

    def net_on(self):
        """The logical view drawn in the window (not popped out, not hidden)."""
        return self.layout in ("both", "net") and not self.popouts.is_out("net")

    def cube_on(self):
        return self.layout in ("both", "cube", "edit", "graph") and not self.popouts.is_out("cube") and not room.tucked(self)

    def slot_shown(self, slot):
        if not self.ui:
            return False
        if slot in self.OPTIONAL:
            return True                              # a frame placed among the panes (one in the dock or floating is not in the arrangement)
        if slot == "props":
            return self.layout == "graph" and self.props and not room.active(self)     # canvas first: over the canvas
        if slot == "side":
            return self.side
        if slot == "cube":
            return self.cube_on() and not room.active(self)
        if self.layout == "cube":
            return False
        return self.net_on() if self.layout in ("both", "net") else True

    @staticmethod
    def _col_key(cols):
        return "|".join("+".join(c) for c in cols)

    def _col_fracs(self, cols):
        """Each free column's share of the width the panel column leaves,
        {column index: share}. Per layout mode: the graph wants more room
        than the net does."""
        free = [i for i, c in enumerate(cols) if c != ["side"]]
        if not free:
            return {}
        stored = (self.colw.get(self.layout) or {}).get(self._col_key(cols))
        if stored and len(stored) == len(free):
            fr = [float(v) for v in stored]
        elif len(free) == 1:
            fr = [1.0]
        else:
            share = {"graph": 0.7, "edit": 0.55}.get(self.layout, 0.5)
            fr = [share if "main" in cols[i] else (1.0 - share) / (len(free) - 1) for i in free]
        tot = sum(fr) or 1.0
        return {i: f / tot for i, f in zip(free, fr)}

    def _row_fracs(self, col):
        stored = self.rowh.get("+".join(col))
        if stored and len(stored) == len(col):
            fr = [float(v) for v in stored]
        elif len(col) == 2 and "main" in col:
            fr = [0.58, 0.42] if col[0] == "main" else [0.42, 0.58]
        elif len(col) == 2 and "props" in col:
            fr = [0.62, 0.38] if col[1] == "props" else [0.38, 0.62]
        else:
            fr = [1.0 / len(col)] * len(col)
        tot = sum(fr) or 1.0
        return [f / tot for f in fr]

    SPLIT = px(8)                # a splitter's thickness

    def pane_rects(self, x0, y0, W, H):
        """Where each shown slot goes, {slot: (x, y, w, h)}, and the splitters
        between them, [(kind, col, row, x, y, w, h)]: "v" between column
        `col` and the next, "h" between row `row` of `col` and the next. A
        column of the panel alone keeps its pixel width; the others share
        the rest."""
        cols = [[s for s in col if self.slot_shown(s)] for col in self.arrangement]
        cols = [c for c in cols if c]
        self._cols = cols
        if not cols:
            return {}, []
        G = self.SPLIT
        n = len(cols)
        fr = self._col_fracs(cols)
        folded = room.folded(self)
        side_px = room.side_px(self)
        free_w = W - G * (n - 1) - sum(side_px for c in cols if c == ["side"])
        free_w = max(VIEW_MIN * max(1, len(fr)), free_w)
        self._free_w = free_w
        widths = [side_px if c == ["side"] else max(VIEW_MIN, int(free_w * fr[i])) for i, c in enumerate(cols)]
        rects, splits = {}, []
        self._rows_h = []
        x = x0
        for i, c in enumerate(cols):
            w = widths[i]
            rf = self._row_fracs(c)
            hs = H - G * (len(c) - 1)
            self._rows_h.append(hs)
            y = y0
            for j, s in enumerate(c):
                h = max(VIEW_MIN // 2, int(hs * rf[j])) if j < len(c) - 1 else max(VIEW_MIN // 2, y0 + H - y)
                rects[s] = (x, y, w, h)
                if j < len(c) - 1:
                    splits.append(("h", i, j, x, y + h, w, G))
                    y += h + G
            if i < n - 1 and not (folded and ["side"] in (c, cols[i + 1])):
                splits.append(("v", i, 0, x + w, y0, G, H))
            x += w + G
        return rects, splits

    # --- the ghost: what is being dragged, following the pointer ------------------------
    def _ghost_start(self, x, y, w, h, label):
        mx, my = dpg.get_mouse_pos(local=False)
        self._ghost = (w, h, mx - x, my - y, label)
        self._ghost_move()

    def _ghost_move(self):
        if not self._ghost or not dpg.does_item_exist("ghost_rect"):
            return
        w, h, dx, dy, label = self._ghost
        mx, my = dpg.get_mouse_pos(local=False)
        x0, y0 = mx - dx, my - dy
        dpg.configure_item("ghost_rect", pmin=(x0, y0), pmax=(x0 + w, y0 + h), show=True)
        dpg.configure_item("ghost_text", pos=(x0 + 10, y0 + 8), text=label, show=True)

    def _ghost_end(self):
        self._ghost = None
        for t in ("ghost_rect", "ghost_text"):
            if dpg.does_item_exist(t):
                dpg.configure_item(t, show=False)

    def drop_zone(self, mx, my, frame=False):
        """What a dragged pane would do if let go here: (slot, zone) for the
        pane under the pointer - the edge it is nearest, or the centre. A
        frame (`frame`) has a centre only on the panel - into the dock - or
        on another frame (the two swap): on the others, the nearest edge."""
        for slot, (x, y, w, h) in self._rects.items():
            if not (x <= mx < x + w and y <= my < y + h):
                continue
            rx, ry = (mx - x) / max(1, w), (my - y) / max(1, h)
            d = min(rx, 1 - rx, ry, 1 - ry)
            if d > 0.3 and not (frame and slot in self.CORE and slot != "side"):
                return slot, "centre"
            if d == rx:
                return slot, "left"
            if d == 1 - rx:
                return slot, "right"
            return slot, "top" if d == ry else "bottom"
        return None

    def _zone_rect(self, slot, zone):
        x, y, w, h = self._rects[slot]
        if zone == "left":
            return x, y, x + w // 2, y + h
        if zone == "right":
            return x + w // 2, y, x + w, y + h
        if zone == "top":
            return x, y, x + w, y + h // 2
        if zone == "bottom":
            return x, y + h // 2, x + w, y + h
        return x + 6, y + 6, x + w - 6, y + h - 6

    # --- pop-outs: a view in a window of its own ----------------------------------
    def set_popout(self, view, on):
        """The net or the 3-D view in its own window (a second monitor's),
        its pane given to the others; off, or the window closed, brings the
        pane back."""
        if view not in ("net", "cube"):
            return
        if on and not self.popouts.is_out(view):
            self.popouts.open(view, self.eng, (self.yaw, self.pitch, self.dist))
        elif not on and self.popouts.is_out(view):
            self.popouts.close(view)
        self.request_layout()

    def poll_menus_fit(self):
        """A popup menu that grew past the window's edge - a fold opened
        near the bottom - is moved back inside, so every row can be reached."""
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        for tag in ("graph_ctx", "graph_menu", "compare_menu", "open_menu", "midi_ctx", "expr_win") + tuple(self.pane_menus.values()):
            if not (dpg.does_item_exist(tag) and dpg.is_item_shown(tag)):
                continue
            w, h = dpg.get_item_rect_size(tag)
            if w <= 0 or h <= 0:
                continue
            x, y = dpg.get_item_pos(tag)
            nx = max(0, min(x, vw - w - 4)) if w < vw else 0
            ny = max(0, min(y, vh - h - 4)) if h < vh else 0
            if (nx, ny) != (x, y):
                dpg.set_item_pos(tag, [nx, ny])

    def poll_popouts(self):
        if self.popouts.jobs and self.popouts.poll():
            self.request_layout()

    # --- the side panel's sections: folded, and in any order -----------------------
    SECTIONS = ("effect", "segments", "geometry", "colours", "parameters", "audio", "live", "video")

    def sec_save(self):
        self.prefs["sections"] = {"order": list(self.sec_order), "closed": sorted(self.sec_closed)}
        save_prefs(self.prefs)

    def sec_toggle(self, key):
        self.sec_set(key, key in self.sec_closed)

    def sec_set(self, key, open_):
        if open_:
            self.sec_closed.discard(key)
        else:
            self.sec_closed.add(key)
        if dpg.does_item_exist(f"sec_{key}_body"):
            dpg.configure_item(f"sec_{key}_body", show=open_)
            dpg.configure_item(f"sec_{key}_arrow", direction=dpg.mvDir_Down if open_ else dpg.mvDir_Right)
        self.sec_save()

    def sec_all(self, open_):
        for key in self.SECTIONS:
            self.sec_set(key, open_)

    def sec_apply_order(self):
        """The sections into self.sec_order: each moved to the end in turn."""
        for key in self.sec_order:
            if dpg.does_item_exist(f"sec_{key}"):
                dpg.move_item(f"sec_{key}", parent="side_win")
        self.sec_save()

    def sec_move(self, key, target, zone):
        """`key` dropped above or below `target`."""
        if key == target or key not in self.SECTIONS or target not in self.SECTIONS:
            return
        order = [k for k in self.sec_order if k != key]
        i = order.index(target) + (1 if zone == "below" else 0)
        order.insert(i, key)
        self.sec_order = order
        self.sec_apply_order()

    def sec_reset(self):
        self.sec_order = list(self.SECTIONS)
        self.sec_closed = set()
        self.sec_all(True)
        self.sec_apply_order()

    def sec_zone(self, mx, my):
        """The section under the pointer and which half of it: (key, "above" | "below")."""
        # the panel's rectangle, not its hover: while the grip (a button)
        # is held, ImGui reports nothing under it as hovered
        pane = self._screen_rect("side_win")
        if not pane or not (pane[0] <= mx <= pane[2] and pane[1] <= my <= pane[3]):
            return None
        for key in self.sec_order:
            st = dpg.get_item_state(f"sec_{key}")
            (x, y), (w, h) = st.get("rect_min", (0, 0)), st.get("rect_size", (0, 0))
            if w > 0 and h > 0 and x <= mx < x + w and y <= my < y + h:
                return key, ("above" if my < y + h / 2 else "below")
        return None

    def _sec_zone_rect(self, key, zone):
        st = dpg.get_item_state(f"sec_{key}")
        (x, y), (w, h) = st["rect_min"], st["rect_size"]
        yy = y if zone == "above" else y + h - 4
        return x, yy - 2, x + w, yy + 4

    @staticmethod
    def build_dir():
        return os.path.join(os.path.dirname(PROJECTS), "build", "latest")

    @staticmethod
    def doc_path(name):
        from native import paths
        return os.path.join(paths.RES, name)

    def open_url(self, url):
        import webbrowser
        if url:
            webbrowser.open(url)

    def reveal(self, path):
        """Open a file or folder with whatever the system uses for it."""
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                procs.popen(["open", path])
            else:
                procs.popen(["xdg-open", path])
        except Exception as e:
            self.gp.status(f"could not open {path}: {e}")

    def relayout(self):
        """Size and place the panes for whatever the window currently is.

        The panes were fixed pixel sizes, so maximising the window left two
        small pictures in the corner of a large expanse of panel. Both views
        are square, so each gets the largest square that fits its pane. The
        panes' places come from the arrangement (pane_rects); presenting (H)
        shows the pictures only, centred by hand.
        """
        vw = max(640, dpg.get_viewport_client_width())
        vh = max(420, dpg.get_viewport_client_height())
        room.prepare(self)                   # the 3-D view and the properties: over the canvas, or among the panes

        # What is on screen decides what there is room for. A popped-out view
        # is on another window; hidden here. Presenting shows pictures only:
        # the code and graph panes are chrome too, so in those layouts the
        # 3-D view stands alone.
        show_net = self.net_on()
        show_cube = self.cube_on()
        show_edit = self.layout == "edit" and self.ui
        show_graph = self.layout == "graph" and self.ui
        nview = (show_net + show_cube + show_edit + show_graph) if self.ui else (show_net + show_cube)
        rects, splits = {}, []
        if self.ui:
            # The panes stop where the footer (record, stats, key hints)
            # starts, so the root window never has anything to scroll to.
            # The footer is measured rather than assumed; before the first
            # frame it has no size yet and 48 px is what it comes to.
            fh = dpg.get_item_rect_size("footer")[1] if dpg.does_item_exist("footer") else 0
            fh = fh if fh > 0 else px(48)
            # The menu bar and the toolbar sit above the panes; where the
            # toolbar ends is measured, since the menu bar's height is the
            # font's business. Before the first frame it has no size: 59 px
            # is what it comes to.
            tb_y = dpg.get_item_rect_min("toolbar")[1] if dpg.does_item_exist("toolbar") else 0
            tb_h = dpg.get_item_rect_size("toolbar")[1] if dpg.does_item_exist("toolbar") else 0
            top = (tb_y + tb_h + px(6)) if tb_h > 0 else px(59)
            pane_h = max(VIEW_MIN, vh - top - fh - px(18))
            rects, splits = self.pane_rects(px(8), top, vw - px(16), pane_h)
            main, cube = rects.get("main"), rects.get("cube")
            if cube is None and main and room.pip_on(self):
                cube = room.pip_geometry(self, main)          # the 3-D view in its corner of the graph
                dpg.configure_item("cube_win", width=cube[2], height=cube[3])   # its size before the picture is centred in it
            self._cube_rect = cube
            # the 3-D view is a square, the largest its pane's inside allows; the logical view has the
            # pane's inside as it is (a 40 x 12 net drawn in a square was a strip in a tall pane)
            net_box = (main[2] - px(22), main[3] - CAP_H) if (main and show_net) else (VIEW_MIN, VIEW_MIN)
            side = max(VIEW_MIN, min(cube[2] - px(22), cube[3] - CAP_H)) if cube else VIEW_MIN
        else:
            # Presenting: no control column, no captions, no borders and no
            # padding, so none of it gets an allowance. The picture takes the
            # whole frame less the gap between two of them.
            pane_h = max(VIEW_MIN, vh)
            self._cube_rect = None
            avail = vw - (16 if nview == 2 else 0)
            left_w = max(VIEW_MIN, avail // max(1, nview))
            side = max(VIEW_MIN, min(left_w, pane_h))
            net_box = (left_w, pane_h)
        self._rects = rects

        dpg.configure_item("net_win",  show=show_net)
        dpg.configure_item("cube_win", show=show_cube)
        dpg.configure_item("edit_win", show=show_edit)
        dpg.configure_item("graph_win", show=show_graph)
        dpg.configure_item("side_win", show=self.ui and self.side and not room.folded(self))
        dpg.configure_item("rail_win", show=room.rail(self))
        dpg.configure_item("props_win", show=self.slot_shown("props") or room.active(self))   # over the canvas: its window decides
        if not (self.ui and self.side and not room.folded(self)) or "side" not in rects:
            dock.hide(self)                          # the dock's column is away: its strip and frames with it
        for slot in self.OPTIONAL:
            if dock.paned(self, slot) and slot not in rects and dpg.does_item_exist(self.pane_of(slot)):
                dpg.configure_item(self.pane_of(slot), show=False)     # a frame among the panes, while they are away
        # The menu bar is the window's: a hidden mvMenuBar still draws its
        # strip, the window flag takes it away.
        dpg.configure_item("root", menubar=self.ui)
        if dpg.does_item_exist("toolbar"):
            dpg.configure_item("toolbar", show=self.ui)
        for tag in self._splitters:
            dpg.configure_item(tag, show=False)

        th = self._themes.get("present" if not self.ui else "normal")
        if th:
            dpg.bind_theme(th)
        dpg.set_viewport_clear_color([0, 0, 0, 255] if not self.ui else list(theme_colors(self.prefs)["bg"]) + [255])
        for tag in ("net_win", "cube_win", "side_win"):
            dpg.configure_item(tag, border=self.ui)
        # The captions, the grips, the readout and the key hints are UI too -
        # a clean picture means nothing left over the top of it.
        for tag in ("net_cap", "cube_cap", "cube_cap_tip", "stat_row", "msg_row", "grip_net_win", "grip_cube_win"):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=self.ui)
        if not self.ui and dpg.does_item_exist("stats_pop"):
            dpg.hide_item("stats_pop")                   # the footer's figures go with the footer
        chrome.refresh(self)

        # The net is upscaled by a WHOLE number so the LED grid stays hard;
        # bilinear scaling of a 48-pixel image looks like a photograph of a cube
        # rather than a cube.
        self.net_scale = max(1, min(max(VIEW_MIN, net_box[0]) // max(1, self.eng.cols),
                                    max(VIEW_MIN, net_box[1]) // max(1, self.net_image().shape[0])))
        # The cube render is capped whatever the pane size, and the image is
        # scaled up to fill. Measured, the renderer costs 28 ms a frame at 620
        # and 64 ms at 900 - it is quadratic in the size, and it is already the
        # single most expensive thing the app does. Rendering a fullscreen cube
        # at its true size would take the whole app from 35 fps to 15, so
        # fullscreen makes the picture BIGGER, not sharper. Raising this is not
        # a free win; measure before touching it.
        self.cube_px = min(CUBE_MAX, side // 2 if self.ab else side)
        self.view_side = side

        if self.ui:
            # A pane once placed no longer flows in its row; every one is
            # placed here, from the arrangement.
            for tag in ("net_win", "cube_win", "edit_win", "graph_win", "side_win", "props_win", "rail_win"):
                dpg.reset_pos(tag)
            for slot, (x, y, w, h) in rects.items():
                if slot == "side" and room.rail(self):
                    room.place_side(self, (x, y, w, h))        # the rail at the edge, the dock beside it
                    continue
                if slot == "side":
                    dock.place(self, (x, y, w, h))             # the panel, or the frame whose tab is in front
                    continue
                if slot in self.OPTIONAL:
                    self._place_frame(slot, (x, y, w, h))      # a frame among the panes
                    continue
                tag = self.pane_of(slot)
                dpg.configure_item(tag, width=w, height=h)
                dpg.set_item_pos(tag, [x, y])
                # the grip at the pane's top right, clear of the scrollbar
                if dpg.does_item_exist(f"grip_{tag}"):
                    dpg.set_item_pos(f"grip_{tag}", [w - px(46), px(8)])     # inside the padding: past it, the pane scrolled
            app_ed = getattr(self, "code_ed", None)
            if app_ed and show_edit and "main" in rects:
                x, y, w, h = rects["main"]
                app_ed.resize(w - px(18), h - px(192))     # the rows above and below it: find and replace are two lines
            for kind, i, j, x, y, w, h in splits:
                tag = f"{kind}split_{i}_{j}"
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, width=w, height=h, show=True)
                    dpg.set_item_pos(tag, [x, y])
        # Centre what is left, rather than letting it sit against the corner.
        # In presentation mode the panes are exactly the size of their pictures
        # and are positioned by hand; the black around them is the viewport
        # showing through, which is why the clear colour matters as much as the
        # theme does.
        if not self.ui:
            gap = 16 if nview == 2 else 0
            total = side * nview + gap
            x0 = max(0, (vw - total) // 2)
            y0 = max(0, (vh - side) // 2)
            if show_net:
                dpg.configure_item("net_win", width=side, height=side)
                dpg.set_item_pos("net_win", [x0, y0])
                x0 += side + gap
            if show_cube:
                dpg.configure_item("cube_win", width=side, height=side)
                dpg.set_item_pos("cube_win", [x0, y0])

        # Only the visible views get textures. A hidden one would otherwise
        # allocate at full pane size and never be written to - 7.7 MB of
        # float32 for a net nobody is looking at. Switching back runs this
        # again, so the texture is there by the time anything draws into it.
        if show_net:
            self.remake_net_texture()
        if show_cube:
            self.remake_cube_texture()
        # a narrow pane's caption would run under the grip: the short form
        if self.ui:
            if "main" in rects and show_net:
                dpg.set_value("net_cap", "Logical view - what the effect draws" if rects["main"][2] >= 340 else "Logical view")
            if "cube" in rects and not self.ab and rects["cube"][2] < 340:
                dpg.set_value("cube_cap", "3-D view")
        self.centre_views()
        room.place(self, rects)              # the windows over the canvas, the help band, the rail's buttons

    def centre_views(self):
        """A view sits in the middle of its pane, not in its top-left corner:
        the panes are as tall as the window, the pictures are square."""
        for win, img in (("net_win", "net_img"), ("cube_win", "cube_img")):
            if not (dpg.does_item_exist(win) and dpg.does_item_exist(img)):
                continue
            if img == "cube_img" and (self.cube_quads is not None or self.point_quads is not None):
                continue                                  # the drawlist fills the pane and centres itself
            cw = dpg.get_item_configuration(win).get("width") or 0
            ch = dpg.get_item_configuration(win).get("height") or 0
            iw = dpg.get_item_configuration(img).get("width") or 0
            ih = dpg.get_item_configuration(img).get("height") or 0
            if not (cw and ch and iw and ih):
                continue
            top = CAP_H - px(10) if self.ui else 0        # the caption row (the pane pads 10 below the picture)
            dpg.set_item_pos(img, [max(0, (cw - iw) // 2), top + max(0, (ch - top - ih - px(10)) // 2)])

    NET_SRC_SCALE = 4            # the net's upscale for the GPU-scaled view

    def remake_net_texture(self):
        """The net view's texture. Crisp: the net repeated by a whole number
        on the CPU (6 ms a frame, hard-edged LEDs). GPU: the net at 4x, the
        image widget scaling it up - a fifth of the work, edges a little
        soft (the bilinear step is a quarter of an LED)."""
        img = self.net_image()
        w = img.shape[1] * self.net_scale
        h = img.shape[0] * self.net_scale
        if dpg.does_item_exist("net_img"):
            dpg.delete_item("net_img")
        if dpg.does_item_exist("net_tex"):
            dpg.delete_item("net_tex")
        if self.gpu_net:
            k = self.NET_SRC_SCALE
            tw, th = img.shape[1] * k, img.shape[0] * k
        else:
            tw, th = w, h
        dpg.add_raw_texture(tw, th, np.zeros(tw * th * 4, np.float32),
                            format=dpg.mvFormat_Float_rgba, tag="net_tex", parent=tex_registry())
        dpg.add_image("net_tex", tag="net_img", parent="net_win", width=w, height=h)
        self._bufs.pop("net", None)

    def gpu_cube_active(self):
        """The GPU view draws a cube as its faces: five flat faces, one
        segment, in flat mode too (the LEDs are where they were). Two
        effects side by side keep the software renderer."""
        g = self.eng.geom
        return bool(self.gpu_cube and g is not None and g.kind == "cube" and not self.ab)

    def gpu_points_active(self):
        """The GPU view draws every other geometry as a cloud of squares - or, one whose LEDs lie on a surface
        (a matrix, a cylinder, a sphere, a torus: surface_geom), as that surface."""
        g = self.eng.geom
        return bool(self.gpu_cube and g is not None and g.kind != "cube" and not self.ab)

    def surface_geom(self):
        """The engine's geometry when the 3-D view draws it as a surface (gpucube.SurfaceQuads), else None."""
        g = self.eng.geom
        return g if g is not None and g.is_surface() and len(self.view_positions()) == len(g.pos) else None

    def view_positions(self):
        """The LEDs' positions the 3-D view draws: the project's geometry
        when it is the engine's shape moved (a part being dragged), else
        the engine's own."""
        g, p = self.eng.geom, self.project.geometry
        if g is not None and p is not None and p.kind == g.kind and len(p.pos) == len(g.pos):
            return p.pos
        return g.pos if g is not None else np.zeros((1, 3), np.float32)

    def remake_cube_texture(self):
        p = self.cube_px
        w, h = (2 * p + 8, p) if self.ab else (p, p)
        if dpg.does_item_exist("cube_img"):
            dpg.delete_item("cube_img")
        self.cube_quads = None
        if self.point_quads is not None and dpg.does_item_exist(self.point_quads.tex):
            dpg.delete_item(self.point_quads.tex)
        self.point_quads = None
        if dpg.does_item_exist("cube_tex"):
            dpg.delete_item("cube_tex")
        if self.gpu_points_active():
            from native.gpucube import PointQuads, SurfaceQuads
            sg = self.surface_geom()
            self.point_quads = (SurfaceQuads("cube_win", "cube_img", sg, self.view_positions()) if sg is not None
                                else PointQuads("cube_win", "cube_img", self.view_positions()))
            self.point_quads.set_frame(view3d.frame(self))
            r = getattr(self, "_cube_rect", None)
            if r and self.ui:
                self.point_quads.resize(self.view_side, r[2] - px(22), r[3] - CAP_H)
            else:
                self.point_quads.resize(self.view_side)
            if dpg.does_item_exist("cube_cap"):
                dpg.set_value("cube_cap", "3-D - drag to rotate, wheel to zoom")
            return
        if self.gpu_cube_active():
            # the net, a few times its size so bilinear sampling keeps the
            # LEDs square, is the one texture the quads draw from
            n = 3 * self.eng.B * self.CUBE_SRC_SCALE
            if dpg.does_item_exist("cube_src_tex"):
                dpg.delete_item("cube_src_tex")
            dpg.add_raw_texture(n, n, np.zeros(n * n * 4, np.float32), format=dpg.mvFormat_Float_rgba, tag="cube_src_tex", parent=tex_registry())
            self._bufs.pop("cube_src", None)
            self.cube_quads = CubeQuads("cube_win", "cube_img", "cube_src_tex")
            r = getattr(self, "_cube_rect", None)
            if r and self.ui:
                self.cube_quads.resize(self.view_side, r[2] - px(22), r[3] - CAP_H)
            else:
                self.cube_quads.resize(self.view_side)
            if dpg.does_item_exist("cube_cap"):
                dpg.set_value("cube_cap", "3-D - drag to rotate, wheel to zoom")
            return
        dpg.add_raw_texture(w, h, np.zeros(w * h * 4, np.float32),
                            format=dpg.mvFormat_Float_rgba, tag="cube_tex", parent=tex_registry())
        # Drawn at view_side even when rendered smaller, so capping the render
        # cost does not also shrink the picture.
        dpg.add_image("cube_tex", tag="cube_img", parent="cube_win",
                      width=self.view_side, height=int(self.view_side * h / w))
        if dpg.does_item_exist("cube_cap"):
            dpg.set_value("cube_cap", self.ab_caption() if self.ab else "3-D - drag to rotate, wheel to zoom")
        self._bufs.pop("cube", None)

    # --- interaction ---------------------------------------------------------
    # --- grab and turn --------------------------------------------------------
    # The angle at the start of a drag is captured ONCE, on the press, and every
    # later position is that angle plus the total drag delta. That is what makes
    # it feel like holding the object: let go of the mouse without moving and
    # the cube does not drift.
    #
    # It used to capture on mvMouseDownHandler, which fires every frame the
    # button is held rather than once when it goes down. So the "starting" angle
    # was re-taken continuously and the drag delta was added to it again each
    # frame - the cube span at a rate proportional to how far the pointer had
    # moved from where the drag began. A spin control, not a grab, exactly as it
    # felt.
    def _picker_click(self):
        """A colour swatch or a dropdown clicked opens an ImGui popup, which
        nothing reports; it is remembered, and the frames stay off while it
        is - they would draw over it. A dropdown closes on the next click
        wherever it lands (a choice, or a dismissal); a picker stays open
        for clicks inside it, so only a click outside where it sits (under
        the swatch) forgets it. Escape forgets either."""
        if self._color_edits is None:
            self._color_edits = [i for i in dpg.get_all_items()
                                 if dpg.get_item_type(i).endswith(("::mvColorEdit", "::mvCombo"))]
        prev = self._picker
        self._popup_click = prev is not None                  # this click went to a popup: not a selection
        self._picker = None                                   # a dropdown, or a click elsewhere: over
        for i in list(self._color_edits):
            if not dpg.does_item_exist(i):
                self._color_edits = None                      # stale: found again next click
                return
            if dpg.is_item_shown(i) and dpg.is_item_hovered(i):
                if i == prev and dpg.get_item_type(i).endswith("::mvCombo"):
                    return                                    # clicked again: it closed
                self._picker = i
                return
        if prev is not None and dpg.does_item_exist(prev) and dpg.get_item_type(prev).endswith("::mvColorEdit"):
            st = dpg.get_item_state(prev)
            mx, my = dpg.get_mouse_pos(local=False)
            (x0, _), (_, y1) = st.get("rect_min", (0, 0)), st.get("rect_max", (0, 0))
            if x0 - 4 <= mx <= x0 + 360 and y1 <= my <= y1 + 380:
                self._picker = prev                           # inside the picker: still open

    def _slot_label(self, slot):
        return {"main": {"edit": "Code", "graph": "Graph"}.get(self.layout, "Logical view"), "cube": "3-D view",
                "side": "Panel", "props": "Properties", "devices": "Devices", "flash": "Flash firmware",
                "send": "Send to device", "shape": "Shape", "sequence": "Sequence", "library": "Library", "palettes": "Palettes", "outputs": "LED outputs", "audioin": "Audio input", "vj": "VJ"}.get(slot, slot)

    def on_mouse_click(self, sender, app_data):
        self._picker_click()
        reader_ui.clicked(self)
        if room.press(self):
            return                                       # the 3-D view's ::: or size handle, over the graph
        if dpg.does_item_exist("help_split") and dpg.is_item_shown("help_split") and dpg.is_item_hovered("help_split"):
            self._split_drag = ("help_split", dpg.get_mouse_pos(local=False)[1], int(pref_num(self.prefs, "help_h", 46)))
            return
        for slot in self._rects:
            grip = f"grip_{self.pane_of(slot)}"
            if dpg.does_item_exist(grip) and dpg.is_item_hovered(grip):
                self._pane_drag = slot
                self._pane_target = None
                x, y, w, h = self._rects[slot]
                self._ghost_start(x, y, w, h, self._slot_label(slot))
                return
        for slot in self.OPTIONAL:
            tag = self.pane_of(slot)
            grip = f"grip_{tag}"
            if not self.docked(slot) and dpg.does_item_exist(grip) and dpg.is_item_shown(tag) and dpg.is_item_hovered(grip):
                self._pane_drag = slot
                self._pane_target = None
                x, y = dpg.get_item_pos(tag)
                w, h = dpg.get_item_rect_size(tag)
                self._ghost_start(x, y, w, h, self._slot_label(slot))
                return
        if self.side and self.ui:
            for key in self.SECTIONS:
                grip = f"sec_{key}_grip"
                if dpg.does_item_exist(grip) and dpg.is_item_hovered(grip):
                    self._sec_drag = key
                    self._sec_target = None
                    st = dpg.get_item_state(f"sec_{key}")
                    if "rect_min" in st and "rect_size" in st:
                        (x, y), (w, h) = st["rect_min"], st["rect_size"]
                        self._ghost_start(x, y, w, h, dpg.get_value(f"sec_{key}_title") if dpg.does_item_exist(f"sec_{key}_title") else key.upper())
                    return
        mp = dpg.get_mouse_pos(local=False)
        for tag, (kind, i, j) in self._splitters.items():
            if not (dpg.is_item_shown(tag) and dpg.is_item_hovered(tag)):
                continue
            cols = self._cols
            if kind == "v":
                if cols[i] == ["side"] or cols[i + 1] == ["side"]:
                    # the dock keeps a pixel width - the panel's, or the frame's in front: the splitter moves that
                    self._split_drag = (tag, mp[0], ("side", 1 if cols[i] == ["side"] else -1, dock.width(self)))
                else:
                    fr = self._col_fracs(cols)
                    self._split_drag = (tag, mp[0], ("col", i, fr[i], fr[i + 1]))
            else:
                rf = self._row_fracs(cols[i])
                self._split_drag = (tag, mp[1], ("row", i, j, rf[j], rf[j + 1]))
            return
        if dpg.is_item_hovered("cube_img"):
            if shape_ui.click(self):                 # placing an LED, or picking one up
                return
            if shape_tools.press(self):              # a handle taken, a box begun, a modal move kept
                return
            if dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl):
                self._pan_drag = [0.0, 0.0]          # Ctrl+drag pans (a touchpad has no middle button)
            else:
                self._dragging = True
                self._yaw0, self._pitch0 = self.yaw, self.pitch
        mx, my = dpg.get_mouse_pos(local=False)
        for tag in ("net_win", "cube_win", "edit_win", "graph_win", "side_win", "props_win") + tuple(t for t, _, _, _ in device_ui.FRAMES.values()):
            if not (dpg.does_item_exist(tag) and dpg.is_item_shown(tag)):
                continue
            hit = dpg.is_item_hovered(tag)
            if not hit and tag in self.docked_tags():
                # a docked frame by where it is: "hovered" is false over its list or its timeline (a child window,
                # a drawlist), and a click there left the keyboard elsewhere - Undo, Space, Delete went past it
                (x, y), (w, h) = dpg.get_item_pos(tag), dpg.get_item_state(tag).get("rect_size") or (0, 0)
                hit = x <= mx <= x + w and y <= my <= y + h
            if hit:
                self.focus = tag                      # a docked frame counts: Undo then goes to it
                break
        if self.layout == "graph" and not self.over_float():
            self.gp.on_press()

    def over_float(self):
        """The pointer on something floating over the panes - a frame, a
        dialog, the 3-D view or the properties over the graph: a press there
        is not the graph's, though a node lies under it (the graph finds the
        node under the pointer by its rectangle)."""
        mx, my = dpg.get_mouse_pos(local=False)
        return any(x0 <= mx <= x1 and y0 <= my <= y1 for x0, y0, x1, y1 in (getattr(self, "_holes", None) or ()))

    def on_mouse_release(self, sender, app_data):
        if shape_ui.release(self):
            return
        if shape_tools.release(self):                # a handle's drag kept, a box's parts selected
            return
        if room.release(self):
            return
        if self._sec_drag:
            key, target = self._sec_drag, self._sec_target
            self._sec_drag = self._sec_target = None
            self._ghost_end()
            if dpg.does_item_exist("snap_rect"):
                dpg.configure_item("snap_rect", show=False)
            if target:
                self.sec_move(key, *target)
            return
        if self._pane_drag:
            slot, target = self._pane_drag, self._pane_target
            self._pane_drag = self._pane_target = None
            self._ghost_end()
            if dpg.does_item_exist("snap_rect"):
                dpg.configure_item("snap_rect", show=False)
            if target:
                self.move_slot(slot, *target)
            return
        if self._split_drag:
            self._split_drag = None
            self.prefs["side_w"] = int(round(self.side_w / typeface.scale()))                 # at 100%, as laid out
            self.prefs["colw"] = self.colw
            self.prefs["rowh"] = self.rowh
            save_prefs(self.prefs)
        self._dragging = False
        self._pan_drag = None
        if self.layout == "graph":
            self.gp.on_release()

    def on_right_click(self, sender, app_data):
        if shape_tools.right(self):
            return                                       # a modal move put back, or a part's own menu
        if self.layout == "graph" and (dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)):
            if self.gp.knife_start():
                return                                   # Ctrl+right-drag: the knife, not the menu
        k = midi_ui.hovered_slider()
        if k and self.ui:
            midi_ui.slider_menu(self, k); return         # a parameter slider: MIDI learn, and what is on it
        for pane, tag in getattr(self, "pane_menus", {}).items():
            if pane == "side_win" and not any(dpg.is_item_hovered(f"sec_{k}_hdr") for k in self.SECTIONS
                                              if dpg.does_item_exist(f"sec_{k}_hdr")):
                continue                              # the panel's menu is its section headers'
            if dpg.does_item_exist(pane) and dpg.is_item_shown(pane) and dpg.is_item_hovered(pane) and self.ui:
                x, y = dpg.get_mouse_pos(local=False)
                dpg.configure_item(tag, show=True)
                dpg.set_item_pos(tag, [x, y])
                return
        if self.layout == "graph":
            self.gp.open_menu()

    def on_drag(self, sender, app_data):
        if shape_ui.drag(self):
            return
        if shape_tools.drag(self):
            return
        if room.drag(self):
            return
        if self._sec_drag:
            self._ghost_move()
            mx, my = dpg.get_mouse_pos(local=False)
            target = self.sec_zone(mx, my)
            if target and target[0] == self._sec_drag:
                target = None
            if target != self._sec_target:
                self._sec_target = target
                if dpg.does_item_exist("snap_rect"):
                    if target:
                        x0, y0, x1, y1 = self._sec_zone_rect(*target)
                        dpg.configure_item("snap_rect", pmin=(x0, y0), pmax=(x1, y1), show=True)
                    else:
                        dpg.configure_item("snap_rect", show=False)
            return
        if self._pane_drag:
            # the pane under the pointer lights up where the drop would go
            self._ghost_move()
            mx, my = dpg.get_mouse_pos(local=False)
            target = self.drop_zone(mx, my, frame=self._pane_drag in self.OPTIONAL)
            if target and target[0] == self._pane_drag:
                target = None
            if target != self._pane_target:
                self._pane_target = target
                if dpg.does_item_exist("snap_rect"):
                    if target:
                        x0, y0, x1, y1 = self._zone_rect(*target)
                        dpg.configure_item("snap_rect", pmin=(x0, y0), pmax=(x1, y1), show=True)
                    else:
                        dpg.configure_item("snap_rect", show=False)
            return
        if self._split_drag:
            tag, x0, v0 = self._split_drag
            mx, my = dpg.get_mouse_pos(local=False)
            vw = max(640, dpg.get_viewport_client_width())
            if tag == "help_split":
                new = int(max(20, min(240, v0 + (my - x0))))
                if new != int(pref_num(self.prefs, "help_h", 46)):
                    self.prefs["help_h"] = new
                    dpg.configure_item("graph_help_box", height=new)
                return
            if v0[0] == "side":
                _, sign, w0 = v0
                new = int(max(px(240), min(int(vw * 0.6), w0 + sign * (mx - x0))))
                if abs(new - dock.width(self)) >= 6:
                    dock.set_width(self, new); self.request_layout()
            elif v0[0] == "col":
                _, i, a, b = v0
                fw = max(1, self._free_w)
                lo = VIEW_MIN / fw
                d = max(lo - a, min(b - lo, (mx - x0) / fw))
                fr = self._col_fracs(self._cols)
                if abs((a + d) - fr.get(i, a)) * fw >= 4:
                    fr[i], fr[i + 1] = a + d, b - d
                    self.colw.setdefault(self.layout, {})[self._col_key(self._cols)] = [fr[k] for k in sorted(fr)]
                    self.request_layout()
            else:
                _, i, j, a, b = v0
                hs = max(1, self._rows_h[i] if i < len(self._rows_h) else 1)
                lo = (VIEW_MIN // 2) / hs
                d = max(lo - a, min(b - lo, (my - x0) / hs))
                rf = self._row_fracs(self._cols[i])
                if abs((a + d) - rf[j]) * hs >= 4:
                    rf[j], rf[j + 1] = a + d, b - d
                    self.rowh["+".join(self._cols[i])] = rf
                    self.request_layout()
            return
        if getattr(self, "_pan_drag", None) is not None:
            self.pan_by(app_data)
            return
        # Keyed to whether the drag STARTED on the cube, not to what is under
        # the pointer now, so running off the edge mid-turn does not drop it.
        if not self._dragging:
            return
        _, dx, dy = app_data
        # Scaled to the view, so dragging the full width is half a turn whatever
        # size the window is. A fixed radians-per-pixel means the same hand
        # movement does something different after you resize.
        k = 3.14159265 / max(120, self.view_side)
        view3d.orbit(self, self._yaw0 + dx * k, self._pitch0 + dy * k)

    def pan_by(self, app_data):
        """A drag with the pan held (middle, or Ctrl+left): the step since the last."""
        _, dx, dy = app_data
        last = self._pan_drag
        view3d.pan(self, dx - last[0], dy - last[1])
        self._pan_drag = [dx, dy]

    def on_mid_click(self, sender, app_data):
        if dpg.does_item_exist("cube_img") and dpg.is_item_hovered("cube_img"):
            self._pan_drag = [0.0, 0.0]              # middle-drag on the 3-D view pans it

    def on_mid_drag(self, sender, app_data):
        if getattr(self, "_pan_drag", None) is not None:
            self.pan_by(app_data)
            return
        self.gp.on_mid_drag((app_data[1], app_data[2]))

    def on_mid_release(self, sender, app_data):
        self._pan_drag = None
        self.gp.on_mid_release()

    def on_wheel(self, sender, app_data):
        if room.wheel(self, app_data):
            return                                       # Ctrl+wheel over the 3-D view in its corner: its size
        from native import sequence_ui
        if sequence_ui.wheel(self, app_data):
            return                                       # over the Sequence's timeline: along the time, Ctrl: a zoom
        if dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl):
            h = num.hovered()
            if h is not None:
                num.step(h, 1 if app_data > 0 else -1)   # Ctrl+wheel over a number field, anywhere: a step (num.py)
                return
        if self.layout == "edit" and self.code_ed is not None and dpg.does_item_exist("code_ed") and dpg.is_item_hovered("code_ed"):
            self.code_ed.wheel(app_data)
            return
        if self.layout == "graph" and dpg.does_item_exist("node_editor") and dpg.is_item_hovered("node_editor") \
                and not dpg.is_item_hovered("graph_menu") and not dpg.is_item_hovered("graph_ctx"):
            ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
            if ctrl and self.gp.step_hovered(app_data):
                return                                   # Ctrl+wheel over a dropdown steps it
            self.gp.zoom_step(app_data, dpg.get_mouse_pos(local=False))
            return
        if not dpg.is_item_hovered("cube_img"):
            return
        # Multiplicative, so a notch moves the same proportion at every range.
        view3d.zoom(self, app_data)

    TYPING = ("mvAppItemType::mvDragFloat", "mvAppItemType::mvDragInt",       # a number field typed into (num.py)
              "mvAppItemType::mvInputText", "mvAppItemType::mvInputInt", "mvAppItemType::mvInputFloat",
              "mvAppItemType::mvInputDouble", "mvAppItemType::mvInputIntMulti", "mvAppItemType::mvInputFloatMulti",
              "mvAppItemType::mvInputDoubleMulti", "mvAppItemType::mvSliderFloat", "mvAppItemType::mvSliderInt",
              "mvAppItemType::mvDragFloat", "mvAppItemType::mvDragInt")

    def typing(self):
        """True while a box somewhere has the keyboard: the focused item is
        an input (any frame's - the sequence's name, the library's search,
        a shape's size...) and active, or one of the boxes registered by
        hand. The key handler is global, so without this a letter typed
        into a name would also be a hotkey."""
        f = dpg.get_focused_item()
        if f and dpg.does_item_exist(f) and dpg.get_item_type(f) in self.TYPING and dpg.is_item_active(f):
            return True
        if num.any_active():                             # a number field typed into: not the focused item then
            return True
        return any(dpg.does_item_exist(t) and dpg.is_item_active(t)
                   for t in tuple(self._inputs) + ("find_text", "replace_text", "dev_add_host", "name_input", "editor_cmd") + self.META_FIELDS)

    def on_key(self, sender, app_data):
        if shape_tools.key(self, app_data):
            return                                       # a move, turn or scale under way has the keys: X Y Z, a number, Enter, Esc
        from native import sequence_ui
        if sequence_ui.key(self, app_data):
            return                                       # the sequence frame's own: Space, Delete, Ctrl+D
        # Enter in the add menu's search adds the first match. The box gives up the keyboard on Enter before this
        # handler runs (it is called after the frame), so "active" is already false: deactivated this frame counts.
        if (app_data in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter) and dpg.does_item_exist("graph_search")
                and dpg.is_item_shown("graph_menu")
                and (dpg.is_item_active("graph_search") or dpg.is_item_deactivated("graph_search"))):
            self.gp._search_enter(None, dpg.get_value("graph_search"))
            return
        if app_data == dpg.mvKey_Escape:
            self._picker = None
            if dpg.does_item_exist("expr_win") and dpg.is_item_shown("expr_win"):
                dpg.configure_item("expr_win", show=False)   # the expression box, left
        # Presentation keys sit under the left hand so the right stays on the
        # mouse for rotating the cube: Q and E either side of W, which is the
        # pair together.
        # Not while a value is being typed. The handler is global, so without
        # this, typing into a box would also be driving the layout.
        if dpg.does_item_exist("palette_win") and dpg.is_item_shown("palette_win"):
            # the palette has every key while it is up: Esc closes, Up / Down choose a row, Enter runs it
            if app_data == dpg.mvKey_Escape:
                dpg.hide_item("palette_win")
            elif app_data in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter):
                chrome.palette_enter(self)
            elif app_data in (dpg.mvKey_Down, dpg.mvKey_Up):
                chrome.palette_move(self, 1 if app_data == dpg.mvKey_Down else -1)
            return
        if self.layout == "edit" and self.code_ed is not None and self.code_ed.focus:
            ctrl_ = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
            shift_ = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
            if self.code_ed.key(app_data, ctrl_, shift_):
                return
            if not ctrl_ and app_data not in (dpg.mvKey_F1, dpg.mvKey_F2, dpg.mvKey_F3, dpg.mvKey_F5, dpg.mvKey_F11, dpg.mvKey_F12):
                return                                   # plain keys are typing
        if app_data == dpg.mvKey_F3 and dpg.does_item_exist("find_text") and dpg.is_item_active("find_text"):
            self.run_action("find_prev" if (dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)) else "find_next")
            return
        if self.typing():
            return
        if dpg.does_item_exist("name_dialog") and dpg.is_item_shown("name_dialog"):
            if app_data == dpg.mvKey_Escape:
                dpg.hide_item("name_dialog")
            return
        if self.layout == "graph" and self.gp.typing():
            if app_data == dpg.mvKey_Return and dpg.does_item_exist("graph_search") and dpg.is_item_active("graph_search"):
                self.gp._search_enter(None, dpg.get_value("graph_search"))
            elif app_data == dpg.mvKey_Escape:
                self.gp._hide_menus()
            return
        # A key waited for by the shortcuts dialog takes it, whatever it is.
        binding = key_combo(app_data)
        if self._capture:
            if app_data == dpg.mvKey_Escape:
                self._capture = None
                chrome.refresh_keys(self)
            elif binding:
                self.keys.set(self._capture, binding)
                self._capture = None
                chrome.refresh_keys(self)
            return
        if app_data == dpg.mvKey_Escape and device_ui.focused_frame(self):
            device_ui.close(self, device_ui.focused_frame(self)); return    # Esc closes the floating frame with the focus
        if app_data == dpg.mvKey_Escape and chrome.focused_dialog() and chrome.focused_dialog() not in (reader_ui.TAG, "palette_win"):
            chrome.close_dialog(chrome.focused_dialog()); return          # ... and the dialog with the focus, as a frame
        if app_data == dpg.mvKey_Escape and dpg.does_item_exist("stats_pop") and dpg.is_item_shown("stats_pop"):
            dpg.hide_item("stats_pop"); return                            # the footer's figures, away
        if app_data == dpg.mvKey_Escape and not self.ui:
            self.leave_presentation(); return                             # the way out the hint names
        if reader_ui.key(self, app_data, binding):
            return                                       # the help window has the keyboard: Esc, find, back
        if self.layout == "graph" and app_data == dpg.mvKey_Back and self.gp.reset_hovered():
            return                                       # Backspace over a value: its default
        if self.layout == "graph" and binding is None:
            return
        if self.layout == "graph":
            # Nudging is not a binding: four keys, two steps, always these.
            shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
            step = 1 if shift else 10
            arrows = {dpg.mvKey_Left: (-step, 0), dpg.mvKey_Right: (step, 0),
                      dpg.mvKey_Up: (0, -step), dpg.mvKey_Down: (0, step)}
            alt = dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)
            if app_data in arrows and not alt:
                self.gp.nudge(*arrows[app_data]); return
        if binding and self.over_view():
            va = self.keys.lookup(binding, "view")               # the 3-D view's own keys, with the pointer on it
            if va and self.keys.context.get(va) == "view" and shape_ui.view_key_ok(self, va):
                self.run_action(va)
                return
        action = self.keys.lookup(binding, "graph" if self.layout == "graph" else "global") if binding else None
        if action and len(binding) == 1 and not self.over_canvas():
            # A plain key - a letter, a digit, a sign - acts where the work is: over the views, over the graph,
            # or anywhere while presenting. From the panel, a frame or the code pane a stray one did whatever
            # it was bound to (H hid every control), so it says so instead (the critique's C13).
            messages.post(self, f"{binding} works with the pointer over the views or the graph", merge="stray-key")
            return
        if action:
            self.run_action(action)

    def over_view(self):
        """The pointer on the 3-D view - in its pane, in its corner of the
        graph, or full frame: its own keys (the camera's; the shape
        editor's) apply there. (The test hooks hold it true for a moment.)"""
        if time.time() < getattr(self, "_view_hold", 0.0):
            return True
        if time.time() < getattr(self, "_panel_hold", 0.0) or time.time() < getattr(self, "_canvas_hold", 0.0):
            return False                                     # the hooks' pointer on the panel or the graph, wherever the real one is
        return dpg.does_item_exist("cube_win") and dpg.is_item_shown("cube_win") and dpg.is_item_hovered("cube_win")

    def over_canvas(self):
        """The pointer over what a plain key is for: the logical view, the
        3-D view (in its corner of the graph too) or the graph - not a
        window over them - or anywhere while presenting. (The test hooks
        hold it true for a moment: they have no pointer.)"""
        if not self.ui or time.time() < getattr(self, "_canvas_hold", 0.0):
            return True
        if time.time() < getattr(self, "_panel_hold", 0.0):
            return False                                     # the hooks' pointer on the panel, wherever the real one is
        for tag in ("node_editor", "net_win", "cube_win"):
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag) and dpg.is_item_hovered(tag):
                return True
        return False

    def run_action(self, action):
        """Every keyboard action by name; the menus and toolbar call the same."""
        gp = self.gp
        table = {
            "view_net":     lambda: self.set_layout("net"),
            "view_cube":    lambda: self.set_layout("cube"),
            "view_both":    lambda: self.set_layout("both"),
            "pane_code":    lambda: self.toggle_pane("edit"),
            "pane_graph":   lambda: self.toggle_pane("graph"),
            "presentation": self.toggle_ui,
            "fullscreen":   dpg.toggle_viewport_fullscreen,
            "side_panel":   self.toggle_side,
            "props_pane":   self.toggle_props,
            "play_pause":   self.toggle_play,
            "step":         self.step_once,
            "speed_down":   lambda: self.step_speed(-1),
            "speed_up":     lambda: self.step_speed(1),
            "speed_reset":  lambda: self.set_speed(1.0),
            "restart":      lambda: self.eng.select(self.eng.idx),
            "prev_effect":  lambda: self.step_effect(-1),
            "next_effect":  lambda: self.step_effect(1),
            "prev_palette": lambda: self.step_palette(-1),
            "next_palette": lambda: self.step_palette(1),
            "live":         lambda: gp.set_auto(not gp.auto),
            "build":        self.build_current,
            "new":          self.new_effect,
            "open":         lambda: chrome.show_open(self),
            "save":         self.save_current,
            "rename":       self.rename_current,
            "import":       self.toggle_import_current,
            "find":         self.focus_find,
            "find_next":    lambda: self.code_ed and (self._find_setup(), self.code_ed.find_next(), self.find_status()),
            "find_prev":    lambda: self.code_ed and (self._find_setup(), self.code_ed.find_next(True), self.find_status()),
            "external":     self.open_external,
            "screenshot":   lambda: setattr(self, "shot_req", True),
            "record":       lambda: self.start_rec(15.0),
            "record_video": lambda: self.start_rec(15.0, "mp4"),
            "shortcuts":    lambda: chrome.show_keys(self),
            "guide":        lambda: reader_ui.open_doc(self, "GUIDE.md"),
            "tutorial":     lambda: reader_ui.open_doc(self, "TUTORIAL.md"),
            "tutorial_tree": lambda: reader_ui.open_doc(self, "TUTORIAL.md", "Tutorial 2: a Christmas tree in 3-D"),
            "node_ref":     lambda: reader_ui.open_doc(self, "NODES.md"),
            "node_help":    gp.help_here,
            "node_costs":   gp.measure_costs,
            "welcome":      lambda: reader_ui.show_welcome(self),
            "graph_room":   lambda: room.set_on(self, not room.on(self)),
            "graph_panel":  lambda: room.toggle_panel(self),
            "pip":          lambda: room.set_tucked(self, not room.pip(self)["tucked"]),
            "flash":        lambda: chrome.show_flash(self),
            "push":         self.push_settings,
            "stream":       lambda: self.stream_stop() if getattr(self, "ddp", None) is not None else self.stream_start(),
            "devices":      lambda: device_ui.show(self, "devices"),
            "send_frame":   lambda: device_ui.show(self, "send"),
            "shape":        lambda: device_ui.show(self, "shape"),
            "sequence":     lambda: device_ui.show(self, "sequence"),
            "library":      lambda: device_ui.show(self, "library"),
            "palettes":     lambda: device_ui.show(self, "palettes"),
            "vj":           lambda: device_ui.show(self, "vj"),
            "outputs":      lambda: device_ui.show(self, "outputs"),
            "audioin":      lambda: device_ui.show(self, "audioin"),
            "randomise":    self.randomise,
            "undo":         lambda: self.undo_where(),
            "redo":         lambda: self.undo_where(redo=True),
            "cut":          gp.cut,
            "copy":         gp.copy,
            "paste":        gp.paste,
            "duplicate":    self.duplicate_selected,
            "delete":       gp.delete_selected,
            "add_node":     self.search_nodes,
            "connect":      gp.connect_selected,
            "mute":         lambda: gp.toggle_selected("muted"),
            "collapse":     lambda: gp.toggle_selected("collapsed"),
            "hide_pins":    lambda: gp.toggle_selected("hide_pins"),
            "fold":         lambda: chrome.ask(self, "Sub-graph", "a name for the new node type", "",
                                               lambda v: gp.make_sub_from_selection(v)),
            "enter_sub":    self.enter_or_back,
            "arrange":      gp.arrange,
            "space_out":    gp.space_out,
            "align_left":   lambda: gp.align("left"),
            "align_right":  lambda: gp.align("right"),
            "align_top":    lambda: gp.align("top"),
            "align_bottom": lambda: gp.align("bottom"),
            "distribute_x": lambda: gp.distribute("x"),
            "distribute_y": lambda: gp.distribute("y"),
            "zoom_in":      lambda: gp.zoom_step(1),
            "zoom_out":     lambda: gp.zoom_step(-1),
            "zoom_reset":   lambda: gp.set_zoom(1.0),
            "frame_all":    gp.home,
            "stop_preview": gp.stop_preview,
            "focus_mode":   lambda: gp.set_focus_mode(not gp.focus_mode),
            "wire_light":   lambda: gp.set_wire_light(not gp.wire_light()),
            "unlit_dots":   lambda: self.set_view_option("unlit_dots"),
            "view_floor":   lambda: self.set_view_option("view_floor"),
            "view_front":   lambda: view3d.preset(self, "front"),
            "view_back":    lambda: view3d.preset(self, "back"),
            "view_side":    lambda: view3d.preset(self, "right"),
            "view_left":    lambda: view3d.preset(self, "left"),
            "view_top":     lambda: view3d.preset(self, "top"),
            "view_below":   lambda: view3d.preset(self, "below"),
            "view_iso":     lambda: view3d.preset(self, "isometric"),
            "view_ortho":   lambda: view3d.toggle_ortho(self),
            "view_frame":   lambda: shape_ui.frame_selection(self),
            "view_home":    lambda: view3d.home(self),
            "shape_move":   lambda: shape_tools.start(self, "move"),
            "shape_turn":   lambda: shape_tools.start(self, "turn"),
            "shape_scale":  lambda: shape_tools.start(self, "scale"),
            "shape_dup":    lambda: shape_tools.duplicate(self),
            "shape_delete": lambda: shape_tools.delete(self),
            "shape_all":    lambda: shape_tools.select_all(self),
            "minimap":      lambda: room.set_minimap(self, show=not self.prefs.get("minimap", True)),
            "select_all":   gp.select_all,
            "select_none":  gp.select_none,
            "select_invert": gp.select_invert,
            "select_up":    lambda: gp.select_linked("up"),
            "select_down":  lambda: gp.select_linked("down"),
            "select_linked": lambda: gp.select_linked("both"),
            "frame_selected": gp.frame_selected,
            "snap":         gp.toggle_snap,
            "dissolve":     gp.dissolve_selected,
            "disconnect":   gp.disconnect_selected,
            "swap_inputs":  gp.swap_inputs,
            "label_node":   gp.label_selected,
            "frame_sel":    lambda: gp.frame_selection(),
            "repeat":       self.repeat_last,
            "palette":      lambda: chrome.show_palette(self),
            "snapshots":    lambda: chrome.show_snapshots(self),
            "expr":         lambda: gp.expr_hovered(),
            "midi":         lambda: midi_ui.show(self),
            "bank":         lambda: bank_ui.show(self),
            "undo_history": lambda: chrome.show_undo_history(self),
            "history":      lambda: chrome.show_history(self),
            "compare":      lambda: self.stop_ab() if self.ab else chrome.show_compare(self),
            "script_preview": self.preview_script,
            "script_send":  self.send_script,
            "sweep":        lambda: self.stop_sweep() if self.sweep else chrome.show_sweep(self),
        }
        fn = table.get(action)
        if fn and not weight.enabled(self, action) and action not in ("undo", "redo"):
            self.gp.status(weight.WHY.get(weight.NEEDS[action], "not now"))     # greyed on the menus: say why
            return
        if fn:
            if action not in ("repeat", "palette", "undo_history", "undo", "redo"):
                self._last_action = action
            fn()

    def docked_tags(self):
        """The windows of the frames in the dock now."""
        return tuple(tag for slot, (tag, _, _, _) in device_ui.FRAMES.items() if self.docked(slot))

    def undo_target(self):
        """What Undo acts on: the frame with the keyboard (floating, or
        docked and last clicked in) - the shape, the sequence, the
        palettes - else the code pane, else the graph."""
        f = device_ui.focused_frame(self)
        if f is None and view3d.editing(self) and self.over_view():
            f = "shape"                                  # the pointer on the 3-D view while a shape is built: its steps
        if f is None:
            for slot, (tag, _, _, _) in device_ui.FRAMES.items():
                if self.focus == tag and self.docked(slot):
                    f = slot; break
        if f in ("shape", "sequence", "palettes", "vj"):
            return f
        return "code" if self.layout == "edit" else "graph"

    def undo_where(self, redo=False):
        t = self.undo_target()
        if t == "shape":
            from native import shape_ui
            shape_ui.redo(self) if redo else shape_ui.undo(self)
        elif t == "sequence":
            from native import sequence_ui
            sequence_ui.undo(self, redo)
        elif t == "palettes":
            from native import palette_ui
            palette_ui.undo(self, redo)
        elif t == "vj":
            from native import vj_ui
            vj_ui.undo(self, redo)
        elif t == "code":
            self.code_redo() if redo else self.code_undo()
        else:
            self.gp.redo() if redo else self.gp.undo()

    def repeat_last(self):
        a = getattr(self, "_last_action", None)
        if a:
            self.run_action(a)
        else:
            self.gp.status("nothing to repeat yet")

    @staticmethod
    def _merge_boxes(boxes):
        """Rectangles that overlap, merged until none do."""
        out = [tuple(b) for b in boxes]
        merged = True
        while merged and len(out) > 1:
            merged = False
            for i in range(len(out)):
                for j in range(i + 1, len(out)):
                    a, b = out[i], out[j]
                    if not (b[2] <= a[0] or b[0] >= a[2] or b[3] <= a[1] or b[1] >= a[3]):
                        out[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                        del out[j]
                        merged = True
                        break
                if merged:
                    break
        return out

    @staticmethod
    def _screen_rect(tag):
        """(x0, y0, x1, y1) on screen, or None. A child window reports no
        rect_min; its pos is in the window it sits in - the root, which is
        the screen, or a window over the panes (the 3-D view in the graph's
        corner sits at 0, 0 of its own), whose place is added: the frame of
        the pane last clicked in was drawn at the screen's corner."""
        if not dpg.does_item_exist(tag):
            return None
        placed = room.placed(tag)
        if placed:                           # the 3-D view over the graph: where the room puts it this frame
            x, y, w, h = placed
            return (x, y, x + w, y + h)
        st = dpg.get_item_state(tag)
        w, h = st.get("rect_size", (0, 0))
        if w <= 0 or h <= 0:
            return None
        if st.get("rect_min"):
            x, y = st["rect_min"]
        else:
            x, y = dpg.get_item_pos(tag)
            parent = dpg.get_item_parent(tag)
            if parent is not None and dpg.get_item_type(parent).endswith("mvWindowAppItem") and dpg.get_item_alias(parent) != "root":
                ox, oy = dpg.get_item_pos(parent)
                x, y = x + ox, y + oy
        return (x, y, x + w, y + h)

    FLOATING = ("keys_win", "flash_win", "where_win", "history_win", "history_diff_win", "palette_win", "undo_win", "confirm_dialog", "usermods_win", "um_dialog", "compare_menu", "sweep_win", "wav_dialog", "appearance_win", "name_dialog", "editor_dialog", "about_win", "update_win", "wled_dialog", "report_win", "snap_win", "midi_win", "midi_ctx", "bank_win", "expr_win", "reader_win", "welcome_win", "reader_pic",
                "open_menu", "graph_menu", "graph_ctx", "project_dialog", "graph_import_dialog", "xyz_dialog")


    def poll_view_mode(self):
        """The 3-D view is remade when what it should draw changes: A/B
        started or stopped, the GPU view switched, a surface's kind or grid."""
        sg = self.surface_geom() if self.gpu_points_active() else None
        want = (self.gpu_cube_active(), self.gpu_points_active(), (sg.kind, sg.w, sg.h) if sg is not None else None)
        if want != getattr(self, "_gpu_was", None):
            self._gpu_was = want
            self.request_layout()

    def compute_holes(self):
        """The screen rectangles of everything drawn over the panes - every
        window but the root, the file dialogs, the FLOATING list, the open
        menus - for the gradient frames and every viewport overlay."""
        # Every window that floats over the panes is a hole in the frames:
        # every Dear PyGui window but the root (asked for each time, so a
        # dialog added later is covered), the file dialogs (found once),
        # and the FLOATING list for anything else.
        holes = []
        if self._file_dialogs is None:
            self._file_dialogs = [i for i in dpg.get_all_items() if dpg.get_item_type(i).endswith("mvFileDialog")]
        tags = self._hole_tags()
        # An open menu is an ImGui popup, not a window: it is found by its
        # items being visible, and its box is theirs plus the padding.
        if self._menus is None or any(not dpg.does_item_exist(m) for m in self._menus):
            self._menus = [i for i in dpg.get_all_items() if dpg.get_item_type(i).endswith("::mvMenu")]
        # An open menu reports its popup's size (closed, zero) and its own
        # label's position: a top menu's popup hangs under the menu bar at
        # that x, a submenu's opens to the right of its parent's popup at
        # the item's height. Menus come parents first, so a parent's box is
        # known by the time its child is looked at.
        bar_bottom = (dpg.get_item_rect_min("toolbar")[1] - 8) if dpg.does_item_exist("toolbar") else 24
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        boxes = {}
        for m in self._menus:
            st = dpg.get_item_state(m)
            w, h = st.get("rect_size") or (0, 0)
            if w <= 0 or h <= 0:
                continue
            px, py = st.get("pos") or (0, 0)
            parent = boxes.get(dpg.get_item_parent(m))
            if parent is None:
                x0, y0 = px - 2, bar_bottom
            else:
                x0, y0 = parent[2] - 8, parent[1] + py - 6
                if x0 + w > vw - glow.POPUP_PAD:         # no room to the right: ImGui opens it to the left
                    x0 = parent[0] - w + 8
            # ImGui keeps a popup inside the window, so one taller than the room under it is moved up (a long list,
            # File > Open graph's, rose over the item it hangs from and the frames ran through its top)
            x0, y0 = glow.clamp_popup(x0, y0, w, h, vw, vh)
            boxes[m] = (x0, y0, x0 + w, y0 + h)
            holes.append((x0 - 2, y0 - 2, x0 + w + 2, y0 + h + 2))
        for tag in tags:
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                hole = self._window_hole(tag)
                if hole:
                    holes.append(hole)
        return holes

    def _hole_tags(self):
        """The windows that can float over the panes, once each: get_windows() also lists every theme, font
        and handler registry and drawlist (160 items for 53 windows), and the file dialogs and FLOATING named
        some again - a visibility check each, every frame, was 2 ms of it. Kept until the item count changes."""
        wins = dpg.get_windows()
        key = (len(wins), len(self._file_dialogs or []), len(self.FLOATING))
        if getattr(self, "_hole_key", None) != key:
            seen, out = set(), []
            real = [w for w in wins if dpg.get_item_type(w).endswith(("::mvWindowAppItem", "::mvFileDialog"))]
            for t in real + list(self._file_dialogs or []) + list(self.FLOATING):
                i = dpg.get_alias_id(t) if isinstance(t, str) and dpg.does_alias_exist(t) else t
                if i in seen or not dpg.does_item_exist(i) or dpg.get_item_alias(i) == "root":
                    continue
                seen.add(i); out.append(dpg.get_item_alias(i) or i)   # by tag where it has one: one made again keeps it
            self._hole_key, self._hole_list = key, out
        return self._hole_list

    @staticmethod
    def _window_hole(tag):
        """A shown window's rectangle as a hole, with a frame's border and
        rounding round it - or None before it has a size."""
        placed = room.placed(tag)
        if placed:
            x, y, w, h = placed
            return (x - 2, y - 2, x + w + 3, y + h + 3)
        st = dpg.get_item_state(tag)
        w, h = st.get("rect_size") or (0, 0)
        if w <= 0 or h <= 0:
            cfg = dpg.get_item_configuration(tag)      # a window not yet measured: its set size
            w, h = cfg.get("width") or 0, cfg.get("height") or 0
        if w <= 0 or h <= 0:
            return None
        x, y = dpg.get_item_pos(tag)
        return (x - 2, y - 2, x + w + 3, y + h + 3)

    def _host_hole(self, tag):
        """The hole of the window a pane floats in (the 3-D view over the
        graph is in pip_win), or None for a pane among the panes. Every
        frame keeps off that window but the pane's own, which is drawn round
        the window itself: cut by it, only scraps of the glow were left. A
        pane that is a window of its own (a frame in the dock: the library,
        the sequence...) is its own host - from its parent on, its frame was
        cut by itself, 4 of its 48 pieces left and a sliver at its left."""
        item = tag if dpg.does_item_exist(tag) else None
        while item is not None:
            if dpg.get_item_type(item).endswith("::mvWindowAppItem"):
                return None if dpg.get_item_alias(item) == "root" else self._window_hole(item)
            item = dpg.get_item_parent(item)
        return None

    def poll_glow(self):
        """The frames (an accent outline, or a gradient): the pane in focus,
        and the selected nodes (clipped to the editor). None while
        presenting, or while a menu is up over the graph - the frame would
        draw over it."""
        if self.frames is None:
            return
        rects = []
        if self._picker is not None and not dpg.does_item_exist(self._picker):
            self._picker = None
        if self.ui and self._picker is None:
            shown = [t for t in ("graph_win", "edit_win", "net_win", "cube_win", "side_win") + self.docked_tags()
                     if dpg.does_item_exist(t) and dpg.is_item_shown(t)]
            if self.focus not in shown:                  # a docked frame clicked in keeps it (it was taken back each frame)
                self.focus = shown[0] if shown else None
            if self.focus:
                r = self._screen_rect(self.focus)
                if r:
                    rects.append(r + (None, 0.55, "focus", glow.RADIUS, self._host_hole(self.focus)))
            pane = self._screen_rect("graph_win")
            if self.layout == "graph" and self.gp.graph and pane and dpg.does_item_exist("node_editor") \
                    and not (dpg.is_item_shown("graph_menu") or dpg.is_item_shown("graph_ctx")):
                # The editor reports no position of its own; it is the
                # bottom of its pane, its height from its size.
                eh = dpg.get_item_rect_size("node_editor")[1]
                clip = (pane[0] + 9, pane[3] - 9 - eh, pane[2] - 9, pane[3] - 9)
                pad = self.gp.px(8)
                sel = self.gp._selected()
                boxes, ids = [], []                  # ids beside the boxes: a node skipped (scrolled out, folded)
                for nid in sel:                      # shifted every pairing after it, and the frames jumped
                    tag = f"gnode_{nid}"
                    if not dpg.does_item_exist(tag):
                        continue
                    st = dpg.get_item_state(tag)
                    (x0, y0), (x1, y1) = st.get("rect_min", (0, 0)), st.get("rect_max", (0, 0))
                    if x1 > x0 and y1 > y0:          # the content rect; the node is a padding wider
                        boxes.append((x0 - pad, y0 - pad, x1 + pad, y1 + pad)); ids.append(nid)
                # A node's rectangle is last frame's; while it is being
                # dragged the frame would trail it by a frame, so the mouse's
                # movement since then is added - imnodes moves the selection
                # by exactly that. Selected nodes are drawn on top, so
                # nothing but a window ever covers their frames.
                mx, my = dpg.get_mouse_pos(local=False)
                now = {n: b for n, b in zip(ids, boxes)}
                moved = any(self._glow_rects.get(n) not in (None, b) for n, b in now.items())
                if moved and (self.gp.dragging_nodes() or self.gp.panning()) and self._glow_mouse is not None:
                    # only once the nodes really are moving: a press on a
                    # node's slider, or a middle click that pans nothing,
                    # moves the pointer and not the graph
                    dx, dy = mx - self._glow_mouse[0], my - self._glow_mouse[1]
                    boxes = [(x0 + dx, y0 + dy, x1 + dx, y1 + dy) for x0, y0, x1, y1 in boxes]
                self._glow_rects = now
                self._glow_mouse = (mx, my)
                # boxes that overlap merge into one frame round the group
                boxes = self._merge_boxes(boxes)
                if len(boxes) > 3:
                    boxes = [(min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))]
                for x0, y0, x1, y1 in boxes:
                    # the node's corners are rounded 4 at this zoom; the frame's hug them
                    rects.append((x0, y0, x1, y1, clip, 1.0, "sel", self.gp.px(4) if len(boxes) == 1 and len(sel) == 1 else glow.RADIUS))
        holes = self.compute_holes()
        self.frames.update(rects, holes)
        # Every overlay drawn on the viewport (the wiring on the net, the shape
        # editor's rings, the reference wireframes) keeps off the same holes:
        # anything floating over the panes is not to be drawn on.
        self._holes = holes


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
        self.popouts.publish(net, self.eng, (self.yaw, self.pitch, self.dist), (1 if _u is not None else 0) | (2 if _f else 0),
                             self.view_look())
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
            cols = shape_ui.view_colours(self, (rgb if rgb is not None else self.frame_rgb(self.eng)).reshape(-1, 3))
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
        while dpg.is_dearpygui_running():
            try:
                jobs = dpg.get_callback_queue()
                if jobs:
                    dpg.run_callbacks(jobs)
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
                bank_ui.poll(app)
                reader_ui.poll(app)
                room.poll(app)
                weight.poll(app)                     # what has nothing to act on, greyed
                chrome.pin_sideways()                # no pane nudged sideways by a few pixels of overrun
                app.poll_calibration()
                app.poll_wiring_read()
                app.poll_stream_wiring()
                chrome.poll_update(app); chrome.poll_update_download(app)
                _t.append(time.perf_counter())
                app.step_sim()
                _t.append(time.perf_counter())
                app.draw()
                render_video.capture(app)            # rendering a video: this frame of the show into it
                render_fseq.capture(app)             # exporting for FPP: this frame's LEDs into the file
                _t.append(time.perf_counter())
                app._prof = [(b - a) * 1000.0 for a, b in zip(_t, _t[1:])]
            except Exception:
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
                        pass
                    app.gp.status(f"a frame failed: {tb.strip().splitlines()[-1][:90]}" + (" - see crash.txt" if crash else ""), "error")
                app.playing = False
            _r0 = time.perf_counter()
            dpg.render_dearpygui_frame()
            _now = time.perf_counter()
            if getattr(app, "_prof", None) is not None:
                app._prof.append((_now - _r0) * 1000.0)
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
