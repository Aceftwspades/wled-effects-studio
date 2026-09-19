"""The window chrome: the menu bar, the toolbar and the small dialogs.

Every action the app has is reachable from a menu, with its shortcut beside
it, and the ones used all day are on the toolbar as icons. The panes keep
only what is about the thing in them (which file, find/replace, the graph's
status line); everything that used to be a button in a pane lives here.

    build_menus(app)      # inside the root window, first
    build_toolbar(app)    # a row of icon buttons under the menus
    build_dialogs(app)    # the name box, editor command, shortcuts, about, the Device frames
    refresh(app)          # menu checks, toolbar tints and labels, the file lists
    poll(app)             # per frame: refresh() when something it shows changed
"""
import os
import sys
import subprocess
import dearpygui.dearpygui as dpg

from native.icons import texture
from native.keys import ACTIONS, FIXED
from native import glow, flash, device_ui

TEXT   = (215, 219, 227, 255)
DIM    = (139, 147, 163, 255)
ACCENT = (90, 169, 230, 255)
AMBER  = (255, 184, 70, 255)
RED    = (255, 96, 96, 255)
GREEN  = (110, 220, 150, 255)
ICON   = 16

LAYOUTS = (("net", "Logical net", "view_net"), ("cube", "3-D view", "view_cube"), ("both", "Net and 3-D", "view_both"),
           ("edit", "Code", "pane_code"), ("graph", "Graph", "pane_graph"))

# --- the menu bar -------------------------------------------------------------------
def _mi(app, label, action=None, **kw):
    """A menu item; with an action, its shortcut shows the keymap's key and
    the item is tagged so a rebind updates it."""
    if action:
        kw.setdefault("tag", f"mi_{action}")
        kw["shortcut"] = app.keys.label(action)
    return dpg.add_menu_item(label=label, **kw)


def build_menus(app):
    with dpg.menu_bar(tag="menubar"):
        with dpg.menu(label="File"):
            _mi(app, "New graph effect...", "new", callback=lambda: app.new_effect("graph"))
            dpg.add_menu_item(label="New code effect...", callback=lambda: app.new_effect("code"))
            with dpg.menu(label="Open graph", tag="menu_open_graph"):
                pass
            with dpg.menu(label="Open code effect", tag="menu_open_code"):
                pass
            _mi(app, "Save", "save", callback=lambda: app.save_current())
            _mi(app, "Rename...", "rename", callback=lambda: app.rename_current())
            dpg.add_separator()
            _mi(app, "Add to the effects list", "import", tag="menu_import", callback=lambda: app.toggle_import_current())
            _mi(app, "History...", "history", callback=lambda: show_history(app))
            dpg.add_menu_item(label="Library...", callback=lambda: device_ui.show(app, "library"))
            dpg.add_menu_item(label="Generate previews of every effect", callback=lambda: (device_ui.show(app, "library"),
                              __import__("native.library_ui", fromlist=["x"]).generate_previews(app)))
            dpg.add_menu_item(label="Open graph as code", callback=lambda: app.open_graph_code())
            dpg.add_separator()
            with dpg.menu(label="Project"):
                dpg.add_menu_item(label="New project...", callback=lambda: ask(
                    app, "New project", "a name, or a folder path", "", lambda v: app.new_project(v)))
                with dpg.menu(label="Open", tag="menu_open_project"):
                    pass
                with dpg.menu(label="Recent", tag="menu_recent_project"):
                    pass
                dpg.add_menu_item(label="Open folder...", callback=lambda: dpg.show_item("project_dialog"))
                dpg.add_separator()
                dpg.add_menu_item(label="Export usermod (folder + zip)", callback=lambda: app.export_usermod())
            dpg.add_menu_item(label="Import graph bundle...", callback=lambda: dpg.show_item("graph_import_dialog"))
            dpg.add_menu_item(label="Export graph bundle", callback=lambda: app.gp.export_bundle())
            dpg.add_separator()
            _mi(app, "Screenshot of the 3-D view", "screenshot", callback=lambda: setattr(app, "shot_req", True))
            _mi(app, "Record 15 s GIF", "record", callback=lambda: app.start_rec(15.0))
            dpg.add_separator()
            dpg.add_menu_item(label="Quit", callback=lambda: dpg.stop_dearpygui())
        with dpg.menu(label="Edit"):
            _mi(app, "Undo", "undo", callback=lambda: app.run_action("undo"))
            _mi(app, "Redo", "redo", callback=lambda: app.run_action("redo"))
            _mi(app, "Undo history...", "undo_history", callback=lambda: show_undo_history(app))
            _mi(app, "Repeat last action", "repeat", callback=lambda: app.repeat_last())
            dpg.add_separator()
            _mi(app, "Cut", "cut", callback=lambda: app.gp.cut())
            _mi(app, "Copy", "copy", callback=lambda: app.gp.copy())
            _mi(app, "Paste", "paste", callback=lambda: app.gp.paste())
            _mi(app, "Duplicate with inputs", "duplicate", callback=lambda: app.duplicate_selected())
            with dpg.menu(label="Delete"):
                _mi(app, "Delete", "delete", callback=lambda: app.gp.delete_selected())
                _mi(app, "Delete and reconnect", "dissolve", callback=lambda: app.gp.dissolve_selected())
                _mi(app, "Disconnect (keep the nodes)", "disconnect", callback=lambda: app.gp.disconnect_selected())
            with dpg.menu(label="Select"):
                _mi(app, "All", "select_all", callback=lambda: app.gp.select_all())
                _mi(app, "None", "select_none", callback=lambda: app.gp.select_none())
                _mi(app, "Invert", "select_invert", callback=lambda: app.gp.select_invert())
                dpg.add_separator()
                _mi(app, "What feeds the selection", "select_up", callback=lambda: app.gp.select_linked("up"))
                _mi(app, "What the selection feeds", "select_down", callback=lambda: app.gp.select_linked("down"))
                _mi(app, "Everything wired to it", "select_linked", callback=lambda: app.gp.select_linked("both"))
            dpg.add_separator()
            _mi(app, "Command palette...", "palette", callback=lambda: show_palette(app))
            dpg.add_menu_item(label="Palettes (gradients)...", callback=lambda: device_ui.show(app, "palettes"))
            dpg.add_separator()
            _mi(app, "Find / replace in code", "find", callback=lambda: app.focus_find())
            _mi(app, "Open code in external editor", "external", callback=lambda: app.open_external())
        with dpg.menu(label="Device"):
            # the three frames: each a window that floats or docks into the pane space
            dpg.add_menu_item(label="Devices...", callback=lambda: device_ui.show(app, "devices"))
            _mi(app, "Flash firmware...", "flash", callback=lambda: device_ui.show(app, "flash"))
            dpg.add_menu_item(label="Send to device...", callback=lambda: device_ui.show(app, "send"))
            dpg.add_menu_item(label="Sequence: presets and a playlist...", callback=lambda: device_ui.show(app, "sequence"))
            dpg.add_menu_item(label="LED outputs and power...", callback=lambda: device_ui.show(app, "outputs"))
            dpg.add_separator()
            with dpg.menu(label="Active device", tag="menu_active_device"):
                pass
            dpg.add_menu_item(label="Scan the network for devices", callback=lambda: (device_ui.show(app, "devices"), app.scan_devices("all")))
            dpg.add_separator()
            dpg.add_menu_item(label="Stream the sim to the device (DDP)", check=True, tag="menu_stream", default_value=False,
                              callback=lambda s, a: app.stream_start() if a else app.stream_stop())
            _mi(app, "Send the graph as a script", "script_send", callback=lambda: app.send_script())
            _mi(app, "Send the current effect's settings", "push", callback=lambda: app.push_settings())
            dpg.add_menu_item(label="Send the shape (ledmap + positions)", callback=lambda: app.send_shape())
            dpg.add_menu_item(label="Send the ledmap only", callback=lambda: app.send_ledmap())
            dpg.add_menu_item(label="Import the device's ledmap", callback=lambda: app.import_ledmap(host=app.active_host())
                              if app.active_host() else device_ui.show(app, "devices"))
            dpg.add_menu_item(label="Import a ledmap file...", callback=lambda: dpg.show_item("ledmap_dialog"))
            dpg.add_separator()
            dpg.add_menu_item(label="Usermods and features...", callback=lambda: show_usermods(app))
            dpg.add_menu_item(label="Export usermod (folder + zip)", callback=lambda: app.export_usermod())
        with dpg.menu(label="View"):
            for key, label, act in LAYOUTS:
                _mi(app, label, act, check=True, tag=f"menu_view_{key}",
                    callback=lambda s, a, u: app.show_layout(u), user_data=key)
            dpg.add_separator()
            _mi(app, "Presentation (hide controls)", "presentation", check=True, tag="menu_present",
                callback=lambda: app.toggle_ui())
            dpg.add_menu_item(label="Side panel", check=True, default_value=True, tag="menu_side",
                              callback=lambda: app.toggle_side())
            _mi(app, "Properties pane (graph)", "props_pane", check=True, tag="menu_props",
                callback=lambda: app.toggle_props())
            _mi(app, "Focus mode (dim all but the selection)", "focus_mode", check=True, tag="menu_focus",
                callback=lambda s, a: app.gp.set_focus_mode(bool(a)))
            _mi(app, "Fullscreen", "fullscreen", callback=lambda: dpg.toggle_viewport_fullscreen())
            dpg.add_separator()
            with dpg.menu(label="Zoom"):
                _mi(app, "Zoom in", "zoom_in", callback=lambda: app.gp.zoom_step(1))
                _mi(app, "Zoom out", "zoom_out", callback=lambda: app.gp.zoom_step(-1))
                _mi(app, "Zoom 100%", "zoom_reset", callback=lambda: app.gp.set_zoom(1.0))
                dpg.add_separator()
                _mi(app, "Frame all", "frame_all", callback=lambda: app.gp.home())
                _mi(app, "Frame the selection", "frame_selected", callback=lambda: app.gp.frame_selected())
            _mi(app, "Snap to grid", "snap", check=True, tag="menu_snap", callback=lambda: app.gp.toggle_snap())
            dpg.add_menu_item(label="Minimap", check=True, default_value=True, tag="menu_minimap",
                              callback=lambda s, a: dpg.configure_item("node_editor", minimap=bool(a)))
            dpg.add_separator()
            dpg.add_menu_item(label="Shape editor...", callback=lambda: device_ui.show(app, "shape"))
            dpg.add_menu_item(label="Generate a preview of the shape", callback=lambda: (device_ui.show(app, "shape"), shape_ui_preview(app)))
            with dpg.menu(label="Layout"):
                for k, (label, arr) in enumerate(app.PRESETS):
                    dpg.add_menu_item(label=label, check=True, tag=f"menu_arr_{k}", user_data=arr,
                                      callback=lambda s, a, u: app.set_arrangement(u))
                dpg.add_separator()
                dpg.add_text("drag a pane by the ::: at its top right onto another to move it", color=DIM)
                dpg.add_menu_item(label="Reset pane sizes", callback=lambda: app.reset_layout())
            with dpg.menu(label="Pop out (a window of its own, for another monitor)"):
                dpg.add_menu_item(label="The logical net", check=True, tag="menu_pop_net",
                                  callback=lambda s, a: app.set_popout("net", bool(a)))
                dpg.add_menu_item(label="The 3-D view", check=True, tag="menu_pop_cube",
                                  callback=lambda s, a: app.set_popout("cube", bool(a)))
        with dpg.menu(label="Node"):
            _mi(app, "Add node...  (or right-click the graph)", "add_node", callback=lambda: app.search_nodes())
            with dpg.menu(label="Add", tag="menu_add"):
                pass
            dpg.add_separator()
            _mi(app, "Connect selected", "connect", callback=lambda: app.gp.connect_selected())
            _mi(app, "Swap the first two inputs", "swap_inputs", callback=lambda: app.gp.swap_inputs())
            _mi(app, "Label the node...", "label_node", callback=lambda: app.gp.label_selected())
            with dpg.menu(label="Show"):
                _mi(app, "Collapse / expand", "collapse", callback=lambda: app.gp.toggle_selected("collapsed"))
                _mi(app, "Hide / show unwired pins", "hide_pins", callback=lambda: app.gp.toggle_selected("hide_pins"))
                _mi(app, "Mute (pass through)", "mute", callback=lambda: app.gp.toggle_selected("muted"))
            with dpg.menu(label="Arrange"):
                _mi(app, "Arrange (the selection, or all)", "arrange", callback=lambda: app.gp.arrange())
                _mi(app, "Frame the selection", "frame_sel", callback=lambda: app.gp.frame_selection())
                dpg.add_separator()
                _mi(app, "Align left edges", "align_left", callback=lambda: app.gp.align("left"))
                _mi(app, "Align right edges", "align_right", callback=lambda: app.gp.align("right"))
                _mi(app, "Align tops", "align_top", callback=lambda: app.gp.align("top"))
                _mi(app, "Align bottoms", "align_bottom", callback=lambda: app.gp.align("bottom"))
                dpg.add_menu_item(label="Align centres, across", callback=lambda: app.gp.align("centre_x"))
                dpg.add_menu_item(label="Align centres, down", callback=lambda: app.gp.align("centre_y"))
                dpg.add_separator()
                _mi(app, "Distribute across", "distribute_x", callback=lambda: app.gp.distribute("x"))
                _mi(app, "Distribute down", "distribute_y", callback=lambda: app.gp.distribute("y"))
            dpg.add_separator()
            with dpg.menu(label="Sub-graph"):
                _mi(app, "Fold the selection into one...", "fold", callback=lambda: ask(
                    app, "Sub-graph", "a name for the new node type", "", lambda v: app.gp.make_sub_from_selection(v)))
                _mi(app, "Enter the selected sub-graph", "enter_sub", callback=lambda: app.enter_selected_sub())
                dpg.add_menu_item(label="Back to the parent graph", callback=lambda: app.gp.back())
            dpg.add_menu_item(label="Where is the selected node's type used", callback=lambda: app.where_used_selected())
            dpg.add_separator()
            _mi(app, "Stop pin preview", "stop_preview", callback=lambda: app.gp.stop_preview())
        with dpg.menu(label="Playback"):
            _mi(app, "Play / pause", "play_pause", callback=lambda: app.toggle_play())
            _mi(app, "Step one frame", "step", callback=lambda: app.step_once())
            _mi(app, "Restart effect", "restart", callback=lambda: app.eng.select(app.eng.idx))
            dpg.add_menu_item(label="Randomise the settings", callback=lambda: app.randomise())
            dpg.add_menu_item(label="Sequence...", callback=lambda: device_ui.show(app, "sequence"))
            _mi(app, "Compare with another effect...", "compare", callback=lambda: app.run_action("compare"))
            _mi(app, "Sweep a slider...", "sweep", callback=lambda: app.run_action("sweep"))
            dpg.add_separator()
            _mi(app, "Compile + reload", "build", callback=lambda: app.build_current())
            _mi(app, "Run the graph as a script (no build)", "script_preview", callback=lambda: app.preview_script())
            _mi(app, "Live: rebuild the graph as it changes", "live", check=True, tag="menu_live",
                              default_value=app.gp.auto, callback=lambda s, a: app.gp.set_auto(bool(a)))
            dpg.add_menu_item(label="Watch: rebuild when the code is saved outside", check=True, tag="edit_watch",
                              default_value=False)
        with dpg.menu(label="Settings"):
            dpg.add_menu_item(label="Keyboard shortcuts...", callback=lambda: show_keys(app))
            dpg.add_menu_item(label="Selection frames...", callback=lambda: show_frames(app))
            dpg.add_menu_item(label="Appearance...", callback=lambda: show_appearance(app))
            dpg.add_menu_item(label="External editor command...", callback=lambda: show_editor(app))
            dpg.add_menu_item(label="Draw the cube on the GPU", check=True, default_value=app.gpu_cube, tag="menu_gpu",
                              callback=lambda s, a: app.set_gpu_cube(bool(a)))
            dpg.add_menu_item(label="Scale the net on the GPU (softer LED edges, faster)", check=True, default_value=app.gpu_net,
                              tag="menu_gpu_net", callback=lambda s, a: app.set_gpu_net(bool(a)))
            with dpg.menu(label="Simplified nodes below"):
                from native.graph_ui import OVERVIEW_CHOICES
                for z, lbl in OVERVIEW_CHOICES:
                    dpg.add_menu_item(label=lbl, check=True, tag=f"menu_ov_{int(z * 100)}", user_data=z,
                                      callback=lambda s, a, u: app.gp.set_overview_zoom(u))
                dpg.add_text("zoomed out past this, nodes are a title and their wires", color=DIM)
            dpg.add_menu_item(label="Device speed factor...", callback=lambda: ask(
                app, "Device speed", "how many times slower than this PC the device is (the fps estimate in the footer)",
                str(app.prefs.get("device_factor", 60)), lambda v: app.set_device_factor(v)))
            dpg.add_separator()
            dpg.add_menu_item(label="Open the project folder", callback=lambda: app.reveal(app.project.path))
            dpg.add_menu_item(label="Open the build folder", callback=lambda: app.reveal(app.build_dir()))
        with dpg.menu(label="Help"):
            _mi(app, "Keyboard shortcuts", "shortcuts", callback=lambda: show_keys(app))
            dpg.add_menu_item(label="Node reference (NODES.md)", callback=lambda: app.reveal(app.doc_path("NODES.md")))
            dpg.add_menu_item(label="Studio guide (STUDIO.md)", callback=lambda: app.reveal(app.doc_path("STUDIO.md")))
            dpg.add_menu_item(label="Effect API reference", callback=lambda: app.show_api())
            dpg.add_separator()
            dpg.add_menu_item(label="About", callback=lambda: dpg.show_item("about_win"))


# --- the toolbar --------------------------------------------------------------------
def _sep():
    dpg.add_spacer(width=1)
    with dpg.drawlist(width=1, height=22):
        dpg.draw_line((0, 3), (0, 19), color=(52, 58, 70, 255))
    dpg.add_spacer(width=1)


def _btn(app, icon, tip, cb, tag=None, action=None):
    """An icon button with a tooltip; with an action, the tooltip carries
    its key and follows a rebind (the text is tagged by the action)."""
    kw = {"tag": tag} if tag else {}
    b = dpg.add_image_button(texture(icon, ICON), width=ICON, height=ICON, tint_color=TEXT,
                             frame_padding=3, callback=cb, **kw)
    with dpg.tooltip(b):
        tt = f"tbtip_{action}"
        if action and not dpg.does_item_exist(tt):
            dpg.add_text("", tag=tt)
            app._tips[action] = tip
        else:
            dpg.add_text(tip + ("  " + app.keys.label(action) if action else ""))
    return b


def build_toolbar(app):
    app._tips = {"zoom_reset": "Zoom 100%"}
    with dpg.group(horizontal=True, tag="toolbar"):
        _btn(app, "new", "New effect", lambda: app.new_effect(), action="new")
        _btn(app, "open", "Open a graph or a code effect", lambda: show_open(app), tag="tb_open", action="open")
        _btn(app, "save", "Save", lambda: app.save_current(), action="save")
        _sep()
        _btn(app, "build", "Compile + reload", lambda: app.build_current(), tag="tb_build", action="build")
        _btn(app, "live", "Live: rebuild the graph as it changes", lambda: app.gp.set_auto(not app.gp.auto), tag="tb_live", action="live")
        _sep()
        _btn(app, "undo", "Undo", lambda: app.run_action("undo"), action="undo")
        _btn(app, "redo", "Redo", lambda: app.run_action("redo"), action="redo")
        _sep()
        _btn(app, "play", "Play", lambda: app.toggle_play(), tag="tb_play", action="play_pause")
        _btn(app, "pause", "Pause", lambda: app.toggle_play(), tag="tb_pause", action="play_pause")
        _btn(app, "step", "Step one frame", lambda: app.step_once(), action="step")
        _btn(app, "restart", "Restart the effect", lambda: app.eng.select(app.eng.idx), action="restart")
        _sep()
        for key, label, act in LAYOUTS:
            _btn(app, "code" if key == "edit" else key, label, lambda s, a, u: app.show_layout(u), tag=f"tb_view_{key}", action=act)
            dpg.configure_item(f"tb_view_{key}", user_data=key)
        _sep()
        _btn(app, "zoom_out", "Zoom out", lambda: app.gp.zoom_step(-1), action="zoom_out")
        z = dpg.add_button(label="100%", tag="tb_zoom", width=46, callback=lambda: app.gp.set_zoom(1.0))
        with dpg.tooltip(z):
            dpg.add_text("", tag="tbtip_zoom_reset")
        _btn(app, "zoom_in", "Zoom in", lambda: app.gp.zoom_step(1), action="zoom_in")
        _btn(app, "frame_all", "Frame the whole graph", lambda: app.gp.home(), action="frame_all")
        _sep()
        _btn(app, "search", "Add a node (or right-click the graph)", lambda: app.search_nodes(), action="add_node")
        _btn(app, "trash", "Delete the selection", lambda: app.gp.delete_selected(), action="delete")
        _btn(app, "arrange", "Arrange the graph", lambda: app.gp.arrange(), action="arrange")
        _btn(app, "fold", "Fold the selection into a sub-graph", lambda: app.run_action("fold"), action="fold")
        _sep()
        _btn(app, "send", "Build the firmware and flash the device", lambda: show_flash(app), action="flash")
        _btn(app, "external", "Open the code in an external editor", lambda: app.open_external(), action="external")
        _btn(app, "camera", "Screenshot of the 3-D view", lambda: setattr(app, "shot_req", True), tag="shot_btn", action="screenshot")
        _btn(app, "record", "Record a 15 s GIF", lambda: app.start_rec(15.0), tag="rec_btn", action="record")
        dpg.add_text("", tag="rec_msg", color=DIM)
    refresh_keys(app)


# --- dialogs ------------------------------------------------------------------------
def build_dialogs(app):
    with dpg.window(tag="name_dialog", label="Name", modal=True, show=False, no_resize=True, width=360, height=118, no_collapse=True):
        dpg.add_text("", tag="name_prompt", color=DIM)
        dpg.add_input_text(tag="name_input", width=-1, on_enter=True, callback=lambda: _name_ok(app))
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=80, callback=lambda: _name_ok(app))
            dpg.add_button(label="Cancel", width=80, callback=lambda: dpg.hide_item("name_dialog"))
    with dpg.window(tag="usermods_win", label="Usermods and features", show=False, width=720, height=600, no_collapse=True):
        dpg.add_text("What the firmware carries, for this project. The features are the studio's own optional parts; "
                     "the usermods are WLED's, from this tree's usermods/ folder - the environment's, and any you add. "
                     "Unticked ones are left out of the build.", color=DIM, wrap=690)
        dpg.add_text("FEATURES", color=ACCENT)
        with dpg.child_window(tag="um_features", height=200, border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_text("USERMODS", color=ACCENT)
            dpg.add_text("", tag="um_env", color=DIM)
        with dpg.child_window(tag="um_rows", height=190, border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_combo([], tag="um_pick", width=260)
            dpg.add_button(label="Add", callback=lambda: app.add_usermod(dpg.get_value("um_pick")))
            dpg.add_button(label="Import a folder...", callback=lambda: dpg.show_item("um_dialog"))
            dpg.add_button(label="Import a zip...", callback=lambda: dpg.show_item("um_zip_dialog"))
        dpg.add_text("", tag="um_status", color=DIM, wrap=690)
    with dpg.file_dialog(directory_selector=True, show=False, tag="um_dialog", width=620, height=420,
                         callback=lambda s, a: app.import_usermod(a.get("file_path_name", ""))):
        pass
    with dpg.file_dialog(directory_selector=False, show=False, tag="um_zip_dialog", width=620, height=420,
                         callback=lambda s, a: app.import_usermod(a.get("file_path_name", ""))):
        dpg.add_file_extension(".zip", color=(120, 200, 120))
    with dpg.window(tag="confirm_dialog", label="Question", modal=True, show=False, no_resize=True, width=460, height=170, no_collapse=True):
        dpg.add_text("", tag="confirm_text", color=TEXT, wrap=440)
        with dpg.group(horizontal=True, tag="confirm_buttons"):
            pass
    with dpg.window(tag="editor_dialog", label="External editor", modal=True, show=False, no_resize=True, width=460, height=150, no_collapse=True):
        dpg.add_text("the command that opens a file at a line; {file} and {line} are filled in.\n"
                     "Empty uses VS Code if it is on the path.", color=DIM)
        dpg.add_input_text(tag="editor_cmd", hint="code -g {file}:{line}", width=-1)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save", width=80, callback=lambda: (app.save_editor_cmd(dpg.get_value("editor_cmd")),
                                                                   dpg.hide_item("editor_dialog")))
            dpg.add_button(label="Cancel", width=80, callback=lambda: dpg.hide_item("editor_dialog"))
    with dpg.file_dialog(directory_selector=True, show=False, tag="project_dialog", width=620, height=420,
                         callback=lambda s, a: app.new_project(a.get("file_path_name", ""))):
        pass
    with dpg.file_dialog(directory_selector=False, show=False, tag="ledmap_dialog", width=620, height=420,
                         callback=lambda s, a: app.import_ledmap(path=a.get("file_path_name", ""))):
        dpg.add_file_extension(".json", color=(120, 200, 120))
        dpg.add_file_extension(".*")
    with dpg.window(tag="keys_win", label="Keyboard shortcuts", show=False, width=640, height=600, no_collapse=True,
                    on_close=lambda: setattr(app, "_capture", None)):
        dpg.add_text("Click a key to change it, then press the new one (Escape keeps the old). "
                     "A key taken from another action leaves that one unbound.", color=DIM, wrap=600)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Reset all to defaults", callback=lambda: (app.keys.reset(), refresh_keys(app)))
        with dpg.child_window(tag="keys_rows", height=-1, border=False):
            pass
    with dpg.window(tag="about_win", label="About", show=False, width=460, height=200, no_collapse=True):
        dpg.add_text("WLED Effects Studio")
        dpg.add_text("Node graphs and C++ compiled into WLED effects, previewed on a\n"
                     "simulated cube, sphere, matrix or strip with synthetic or live audio.", color=DIM)
        dpg.add_spacer(height=6)
        dpg.add_text("", tag="about_paths", color=DIM)
    with dpg.window(tag="open_menu", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        pass
    with dpg.window(tag="compare_menu", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        pass
    th = app.prefs.get("theme") or {}
    with dpg.window(tag="appearance_win", label="Appearance", show=False, width=560, height=400, no_collapse=True):
        from native.app import THEME_PRESETS, THEME_ROLES
        dpg.add_text("The look. A preset to start from, then any of its seven colours - the change shows as you make it "
                     "and is kept.", color=DIM, wrap=540)
        with dpg.group(horizontal=True):
            for name in THEME_PRESETS:
                dpg.add_button(label=name, small=True, user_data=name, callback=lambda s, a, u: app.set_appearance(preset=u))
            dpg.add_text("", tag="app_preset", color=DIM)
        dpg.add_separator()
        for key, label, what in THEME_ROLES:
            with dpg.group(horizontal=True):
                dpg.add_color_edit([0, 0, 0, 255], tag=f"app_col_{key}", width=150, no_alpha=True, no_label=True, user_data=key,
                                   callback=lambda s, v, u: app.set_appearance(colors={u: [int(round(c * 255)) if c <= 1.0 else int(c) for c in v[:3]]}))
                dpg.add_text(label, tag=f"app_lbl_{key}")
                dpg.add_text(what, color=DIM)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Back to the preset", small=True, callback=lambda: app.set_appearance(preset=(app.prefs.get("theme") or {}).get("preset") or "dark"))
            dpg.add_text("the preset's colours again, your changes dropped", color=DIM)
    with dpg.window(tag="sweep_win", label="Sweep a slider", show=False, width=400, height=190, no_collapse=True):
        dpg.add_text("The slider goes 0 to full and back over the seconds given, so the whole range is seen; "
                     "record makes that one pass the GIF.", color=DIM, wrap=380)
        with dpg.group(horizontal=True):
            dpg.add_combo([], tag="sweep_key", width=200)
            dpg.add_input_float(tag="sweep_secs", width=80, default_value=8.0, step=0, format="%.0f s")
        with dpg.group(horizontal=True):
            dpg.add_checkbox(label="loop", tag="sweep_loop", default_value=True)
            dpg.add_checkbox(label="record a GIF of one pass", tag="sweep_rec")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Start", callback=lambda: _sweep_start(app))
            dpg.add_button(label="Cancel", callback=lambda: dpg.hide_item("sweep_win"))
    build_frames_dialog(app)
    device_ui.build(app)
    with dpg.window(tag="history_win", label="History", show=False, width=520, height=420, no_collapse=True):
        dpg.add_text("", tag="history_what", color=DIM, wrap=500)
        with dpg.child_window(tag="history_rows", height=-1, border=False):
            pass
    # the command palette: every action by name, Enter runs the first hit
    with dpg.window(tag="palette_win", show=False, no_title_bar=True, no_resize=True, no_move=True, width=460, height=380,
                    no_collapse=True):
        dpg.add_input_text(tag="palette_text", hint="type an action (Esc closes)", width=440,
                           callback=lambda s, v: _palette_fill(app, v))
        with dpg.child_window(tag="palette_rows", height=-1, border=False):
            pass
    with dpg.window(tag="undo_win", label="Undo history", show=False, width=420, height=380, no_collapse=True):
        dpg.add_text("the graph's edits, newest first; click one to go back to before it", color=DIM, wrap=400)
        with dpg.child_window(tag="undo_rows", height=-1, border=False):
            pass


def ask(app, title, prompt, default, cb):
    """A one-line name box; cb(value) on OK or Enter."""
    app._ask_cb = cb
    dpg.configure_item("name_dialog", label=title)
    dpg.set_value("name_prompt", prompt)
    dpg.set_value("name_input", default or "")
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    dpg.configure_item("name_dialog", pos=(max(0, vw // 2 - 180), max(0, vh // 3)))
    dpg.show_item("name_dialog")
    dpg.focus_item("name_input")


def confirm(app, title, text, buttons):
    """A question with up to three answers: buttons is [(label, callback or
    None), ...]; the box closes on any of them."""
    dpg.configure_item("confirm_dialog", label=title)
    dpg.set_value("confirm_text", text)
    dpg.delete_item("confirm_buttons", children_only=True)
    app._confirm = [cb for _, cb in buttons]
    for k, (label, cb) in enumerate(buttons):
        dpg.add_button(label=label, parent="confirm_buttons", user_data=k, callback=lambda s, a, u: confirm_pick(app, u))
    lines = max(2, len(text) // 58 + 1)
    _centre("confirm_dialog", 460, 78 + 17 * lines)
    dpg.configure_item("confirm_dialog", height=78 + 17 * lines)
    dpg.show_item("confirm_dialog")


def confirm_pick(app, k):
    dpg.hide_item("confirm_dialog")
    cbs, app._confirm = getattr(app, "_confirm", None) or [], None
    if 0 <= k < len(cbs) and cbs[k]:
        cbs[k]()


def _name_ok(app):
    v = dpg.get_value("name_input")
    dpg.hide_item("name_dialog")
    cb, app._ask_cb = getattr(app, "_ask_cb", None), None
    if cb:
        cb(v)


def show_keys(app):
    refresh_keys(app)
    _centre("keys_win", 640, 600)
    dpg.show_item("keys_win")


def refresh_keys(app):
    """The keymap dialog's rows, and every menu item's shortcut label."""
    for action, _, _, _ in ACTIONS:
        tag = f"mi_{action}"
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, shortcut=app.keys.label(action))
        tt = f"tbtip_{action}"
        if dpg.does_item_exist(tt):
            b = app.keys.label(action)
            dpg.set_value(tt, app._tips.get(action, "") + (f"  {b}" if b else ""))
    if not dpg.does_item_exist("keys_rows"):
        return
    dpg.delete_item("keys_rows", children_only=True)
    last = None
    for action, label, default, ctx in ACTIONS:
        if ctx != last:
            dpg.add_text("anywhere" if ctx == "global" else "in the graph", parent="keys_rows", color=ACCENT)
            last = ctx
        with dpg.group(horizontal=True, parent="keys_rows"):
            b = app.keys.label(action)
            waiting = app._capture == action
            dpg.add_button(label="press a key..." if waiting else (b or "-"), width=130, user_data=action,
                           callback=lambda s, a, u: (setattr(app, "_capture", u), refresh_keys(app)))
            dpg.add_button(label="x", small=True, user_data=action, enabled=bool(b),
                           callback=lambda s, a, u: (app.keys.set(u, ""), refresh_keys(app)))
            dpg.add_text(label, color=TEXT if b else DIM)
            if b != default:
                dpg.add_text(f"(default {default or '-'})", color=DIM)
    dpg.add_spacer(height=6, parent="keys_rows")
    dpg.add_text("always", parent="keys_rows", color=ACCENT)
    for key, what in FIXED:
        dpg.add_text(f"  {key:30s} {what}", parent="keys_rows", color=DIM)


def show_device(app):
    """The Devices frame (what "the device address" became)."""
    device_ui.show(app, "devices")


def show_editor(app):
    cmd = app.project.options.get("editor") or ""
    dpg.set_value("editor_cmd", " ".join(cmd) if isinstance(cmd, list) else cmd)
    _centre("editor_dialog", 460)
    dpg.show_item("editor_dialog")


def _centre(tag, w, h=None):
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    y = max(0, vh // 3) if h is None else max(10, (vh - h) // 2)
    dpg.configure_item(tag, pos=(max(0, vw // 2 - w // 2), y))


def show_open(app):
    """The open button's list: every graph and every code effect, two
    scrolling columns so the popup fits under the button whatever the count."""
    dpg.delete_item("open_menu", children_only=True)
    graphs, codes = app.gp.files(), app.project.effect_files()
    with dpg.group(horizontal=True, parent="open_menu"):
        with dpg.child_window(width=210, height=360, border=False):
            dpg.add_text("graphs", color=DIM)
            for f in graphs:
                dpg.add_selectable(label=f[:-5], width=190, user_data=f,
                                   callback=lambda s, a, u: (dpg.hide_item("open_menu"), app.open_graph(u)))
            if not graphs:
                dpg.add_text("  none yet", color=DIM)
        with dpg.child_window(width=230, height=360, border=False):
            dpg.add_text("code effects", color=DIM)
            for f in codes:
                dpg.add_selectable(label=app.project.effect_title(f), width=210, user_data=f,
                                   callback=lambda s, a, u: (dpg.hide_item("open_menu"), app.open_code(u)))
            if not codes:
                dpg.add_text("  none yet", color=DIM)
    x, y = dpg.get_item_rect_min("tb_open")
    dpg.configure_item("open_menu", show=True)
    dpg.set_item_pos("open_menu", [x, y + 26])


# --- the selection frames: which gradient, and a creator ---------------------------------
# A gradient key is "studio", "wled:<palette name>" or "custom:<name>". The
# choice per frame kind lives in prefs["frames"]; custom gradients in
# prefs["gradients"] as {name: {"stops": [[pos, r, g, b], ...], "mirror": bool}}.
FRAME_KINDS = (("sel", "Selected nodes"), ("focus", "Pane last clicked in"))


def _palettes(app):
    """(name, id) for every WLED palette the engine has, asked once."""
    if not hasattr(app, "_pal_list"):
        app._pal_list = app.eng.palette_list()
    return app._pal_list


def gradient_keys(app):
    return ["studio"] + [f"wled:{n}" for n, _ in _palettes(app)] + \
           [f"custom:{n}" for n in sorted(app.prefs.get("gradients") or {})]


def gradient_label(key):
    return {"studio": "Studio"}.get(key) or key.replace("wled:", "WLED: ").replace("custom:", "Custom: ")


def resolve_gradient(app, key):
    """(stops, mirror) for a key; the studio's own when it names nothing."""
    if key and key.startswith("wled:"):
        pid = dict(_palettes(app)).get(key[5:])
        if pid is not None:
            sw = app.eng.palette_swatch(pid, 16)
            return [[k / 15.0, r, g, b] for k, (r, g, b) in enumerate(sw)], True
    if key and key.startswith("custom:"):
        g = (app.prefs.get("gradients") or {}).get(key[7:])
        if g and g.get("stops"):
            return [list(st) for st in g["stops"]], bool(g.get("mirror"))
    return [list(st) for st in glow.DEFAULT_STOPS], False


def apply_frames(app):
    """The frames take their gradients from the prefs."""
    if not app.frames:
        return
    choice = app.prefs.get("frames") or {}
    for kind, _ in FRAME_KINDS:
        stops, mirror = resolve_gradient(app, choice.get(kind, "studio"))
        app.frames.set_gradient(kind, stops, mirror)


def _strip(stops, mirror, width=260, height=14, parent=None):
    """A gradient drawn across a strip, as it goes round the frame."""
    kw = {"parent": parent} if parent else {}
    with dpg.drawlist(width=width, height=height, **kw):
        for x in range(0, width, 2):
            r, g, b = glow.sample(stops, x / max(1, width - 1), mirror)
            dpg.draw_rectangle((x, 0), (x + 2, height), color=(r, g, b, 255), fill=(r, g, b, 255))


def build_frames_dialog(app):
    app._gc = {"name": "", "stops": [list(st) for st in glow.DEFAULT_STOPS], "mirror": False}
    with dpg.window(tag="frames_win", label="Selection frames", show=False, width=560, height=620, no_collapse=True):
        dpg.add_text("The turning gradient frame around the selected nodes, and the one around the pane "
                     "last clicked in. Pick a WLED palette, the studio's own, or one you made below.", color=DIM, wrap=530)
        dpg.add_group(tag="frames_choice")
        dpg.add_separator()
        dpg.add_text("GRADIENT CREATOR", color=ACCENT)
        with dpg.group(horizontal=True):
            dpg.add_combo([], tag="gc_from", width=220, callback=lambda s, v: _gc_load(app, v))
            dpg.add_text("start from", color=DIM)
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="gc_name", hint="a name for this gradient", width=220,
                               callback=lambda s, v: app._gc.__setitem__("name", v))
            dpg.add_checkbox(label="mirror (seamless: 0 to 1 and back)", tag="gc_mirror",
                             callback=lambda s, v: (app._gc.__setitem__("mirror", bool(v)), refresh_frames(app)))
        dpg.add_group(tag="gc_rows")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save", callback=lambda: _gc_save(app))
            dpg.add_button(label="Save + use for nodes", callback=lambda: _gc_save(app, "sel"))
            dpg.add_button(label="Save + use for pane", callback=lambda: _gc_save(app, "focus"))
            dpg.add_button(label="Delete", tag="gc_delete", callback=lambda: _gc_delete(app))
        dpg.add_text("", tag="gc_status", color=DIM)


def show_frames(app):
    refresh_frames(app)
    _centre("frames_win", 560, 620)
    dpg.show_item("frames_win")


def refresh_frames(app):
    if not dpg.does_item_exist("frames_choice"):
        return
    keys = gradient_keys(app)
    labels = [gradient_label(k) for k in keys]
    choice = app.prefs.get("frames") or {}
    dpg.delete_item("frames_choice", children_only=True)
    for kind, label in FRAME_KINDS:
        cur = choice.get(kind, "studio")
        if cur not in keys:
            cur = "studio"
        with dpg.group(parent="frames_choice"):
            dpg.add_text(label, color=TEXT)
            with dpg.group(horizontal=True):
                dpg.add_combo(labels, width=260, default_value=gradient_label(cur), user_data=kind,
                              callback=lambda s, v, u: _choose(app, u, keys[labels.index(v)]))
                stops, mirror = resolve_gradient(app, cur)
                _strip(stops, mirror)
    dpg.configure_item("gc_from", items=labels)
    gc = app._gc
    dpg.set_value("gc_name", gc["name"])
    dpg.set_value("gc_mirror", gc["mirror"])
    dpg.configure_item("gc_delete", enabled=gc["name"] in (app.prefs.get("gradients") or {}))
    dpg.delete_item("gc_rows", children_only=True)
    _strip(gc["stops"], gc["mirror"], parent="gc_rows")
    for k, st in enumerate(sorted(gc["stops"], key=lambda q: q[0])):
        with dpg.group(horizontal=True, parent="gc_rows"):
            dpg.add_input_float(width=64, default_value=float(st[0]), step=0, format="%.2f",
                                user_data=(k, "pos"), callback=lambda s, v, u: _gc_edit(app, u, v))
            dpg.add_color_edit([int(st[1]), int(st[2]), int(st[3]), 255], width=90, no_alpha=True, no_inputs=True,
                               user_data=(k, "col"), callback=lambda s, v, u: _gc_edit(app, u, v))
            if len(gc["stops"]) > 2:
                dpg.add_button(label="-", small=True, user_data=(k, "del"), callback=lambda s, a, u: _gc_edit(app, u, None))
    dpg.add_button(label="+ stop", small=True, parent="gc_rows", user_data=(-1, "add"),
                   callback=lambda s, a, u: _gc_edit(app, u, None))


def _choose(app, kind, key):
    app.prefs.setdefault("frames", {})[kind] = key
    from native.project import save_prefs
    save_prefs(app.prefs)
    apply_frames(app)
    refresh_frames(app)


def _gc_load(app, label):
    keys = gradient_keys(app)
    labels = [gradient_label(k) for k in keys]
    if label not in labels:
        return
    key = keys[labels.index(label)]
    stops, mirror = resolve_gradient(app, key)
    app._gc = {"name": key[7:] if key.startswith("custom:") else "", "stops": stops, "mirror": mirror}
    refresh_frames(app)


def _gc_edit(app, ud, val):
    k, what = ud
    gc = app._gc
    gc["stops"] = sorted(gc["stops"], key=lambda q: q[0])
    if what == "pos":
        gc["stops"][k][0] = max(0.0, min(1.0, float(val)))
    elif what == "col":
        gc["stops"][k][1:4] = [int(round(c * 255)) if c <= 1.0 else int(c) for c in val[:3]]
    elif what == "del":
        gc["stops"].pop(k)
    elif what == "add":
        gc["stops"].append([1.0, 255, 255, 255])
    refresh_frames(app)


def _gc_save(app, use=None):
    gc = app._gc
    name = (dpg.get_value("gc_name") or gc["name"] or "").strip()
    if not name:
        dpg.set_value("gc_status", "give it a name first"); return
    gc["name"] = name
    app.prefs.setdefault("gradients", {})[name] = {"stops": [list(st) for st in gc["stops"]], "mirror": bool(gc["mirror"])}
    if use:
        app.prefs.setdefault("frames", {})[use] = f"custom:{name}"
    from native.project import save_prefs
    save_prefs(app.prefs)
    apply_frames(app)
    refresh_frames(app)
    dpg.set_value("gc_status", f"saved {name}" + (f" - in use for the {dict(FRAME_KINDS)[use].lower()}" if use else ""))


def _gc_save_named(app, name, use=None):
    dpg.set_value("gc_name", name)
    app._gc["name"] = name
    _gc_save(app, use)


def _gc_delete(app):
    name = app._gc.get("name")
    grads = app.prefs.get("gradients") or {}
    if name not in grads:
        return
    grads.pop(name)
    for kind, key in list((app.prefs.get("frames") or {}).items()):
        if key == f"custom:{name}":
            app.prefs["frames"][kind] = "studio"
    from native.project import save_prefs
    save_prefs(app.prefs)
    app._gc["name"] = ""
    apply_frames(app)
    refresh_frames(app)
    dpg.set_value("gc_status", f"deleted {name}")


def _feature_rows(app, parent="flash_features"):
    """The picker: a checkbox per optional part of the firmware, the audio
    choice, and under each what it brings and which nodes lean on it."""
    if not dpg.does_item_exist(parent):
        return
    from native.nodedefs import NEEDS
    f = flash.features_of(app.project)
    dpg.delete_item(parent, children_only=True)
    for key, label, files, flag, what in flash.FEATURES:
        with dpg.group(parent=parent):
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label=label, default_value=bool(f.get(key)), user_data=key,
                                 callback=lambda s, a, u: app.set_feature(u, bool(a)))
                dpg.add_text(files, color=DIM)
            nodes = sorted(n for n, need in NEEDS.items() if need == key)
            dpg.add_text("    " + what + (f" Nodes: {', '.join(nodes)}." if nodes else ""), color=DIM, wrap=660)
    with dpg.group(parent=parent):
        with dpg.group(horizontal=True):
            labels = [a[1] for a in flash.AUDIO]
            cur = next((a[1] for a in flash.AUDIO if a[0] == f["audio"]), labels[0])
            dpg.add_combo(labels, default_value=cur, width=420, tag=f"{parent}_audio",
                          callback=lambda s, v: app.set_feature("audio", next(a[0] for a in flash.AUDIO if a[1] == v)))
            dpg.add_text("audio", color=DIM)
        what = next(a[2] for a in flash.AUDIO if a[0] == f["audio"])
        nodes = sorted(n for n, need in NEEDS.items() if need == "audio")
        dpg.add_text("    " + what + f" Nodes: {', '.join(nodes)}.", color=DIM, wrap=660)


def show_usermods(app):
    refresh_usermods(app)
    _centre("usermods_win", 720, 600)
    dpg.show_item("usermods_win")


def refresh_usermods(app):
    """The manager's rows: the features (the same rows the flash dialog
    has), then the usermods with their source and a line about each."""
    if not dpg.does_item_exist("um_rows"):
        return
    _feature_rows(app, "um_features")
    env = dpg.get_value("flash_env") if dpg.does_item_exist("flash_env") else ""
    env = env or app.project.options.get("flash_env") or ""
    dpg.set_value("um_env", f"the environment {env}'s, then this project's" if env else "choose an environment in the flash dialog to see its own")
    rows = flash.usermod_rows(app.project, env)
    dpg.delete_item("um_rows", children_only=True)
    for name, on, source in rows:
        with dpg.group(horizontal=True, parent="um_rows"):
            dpg.add_checkbox(default_value=on, user_data=name, callback=lambda s, a, u: app.set_usermod(u, bool(a)))
            dpg.add_text(name, color=TEXT if name not in flash.CORE else ACCENT)
            dpg.add_text("(env)" if source == "env" else "(added)", color=DIM)
            if source == "project" or name in flash.features_of(app.project)["usermods"]:
                dpg.add_button(label="remove" if source == "project" else "as the env says", small=True, user_data=name,
                               callback=lambda s, a, u: app.remove_usermod(u))
            info = flash.usermod_info(name)
            if info:
                room = 58 - len(name)
                dpg.add_text(info[:room] + ("..." if len(info) > room else ""), color=DIM)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text(info, wrap=400)
    if not rows:
        dpg.add_text("none yet - add one below", parent="um_rows", color=DIM)
    listed = {r[0] for r in rows}
    dpg.configure_item("um_pick", items=[n for n in flash.usermod_dirs() if n not in listed])
    refresh_flash(app)


def shape_ui_preview(app):
    from native import shape_ui
    shape_ui.generate_preview(app)


def show_flash(app):
    device_ui.show(app, "flash")


def refresh_flash(app):
    device_ui.refresh_flash(app)


def start_flash(app):
    device_ui.start_flash(app)


def poll_flash(app):
    device_ui.poll(app)


def show_history(app):
    """The versions kept of the current graph (graph pane) or code effect
    (code pane), newest first; restore keeps the current one first."""
    from native import history
    import time as _t
    if app.layout == "edit" and app.edit_file:
        kind, stem, ext, what = "effects", os.path.splitext(app.edit_file)[0], ".cpp", app.edit_file
    elif app.gp.graph and app.gp.file:
        kind = "subgraphs" if app.gp.cur_dir == app.gp.sub_dir else "graphs"
        stem, ext, what = app.gp.file[:-5], ".json", app.gp.file
    else:
        app.gp.status("open a graph or a code effect first"); return
    vs = history.versions(app.project, kind, stem)
    dpg.set_value("history_what", f"{what}: {len(vs)} earlier version(s), a copy kept at every save (the newest {history.KEEP}). "
                                  "Restoring keeps the current one here first.")
    dpg.delete_item("history_rows", children_only=True)
    for p, t, size in vs:
        with dpg.group(horizontal=True, parent="history_rows"):
            dpg.add_button(label="restore", small=True, user_data=(kind, stem, ext, p),
                           callback=lambda s, a, u: _restore(app, *u))
            dpg.add_text(_t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(t)))
            dpg.add_text(f"{size / 1024:.1f} KB", color=DIM)
            if kind != "effects":
                try:
                    import json
                    n = len(json.load(open(p, encoding="utf-8")).get("nodes", []))
                    dpg.add_text(f"{n} nodes", color=DIM)
                except Exception:
                    pass
    if not vs:
        dpg.add_text("no earlier versions yet", parent="history_rows", color=DIM)
    _centre("history_win", 520, 420)
    dpg.show_item("history_win")


def show_palette(app):
    dpg.set_value("palette_text", "")
    _palette_fill(app, "")
    _centre("palette_win", 460, 380)
    dpg.show_item("palette_win")
    dpg.focus_item("palette_text")


def _palette_fill(app, text):
    """The rows: actions whose label or name has the text, the key beside
    each; menu-only things are on the menus already."""
    from native.keys import ACTIONS
    text = (text or "").strip().lower()
    dpg.delete_item("palette_rows", children_only=True)
    ctx = "graph" if app.layout == "graph" else "global"
    rows = []
    for action, label, _, where in ACTIONS:
        if where == "graph" and ctx != "graph":
            continue
        if text and text not in label.lower() and text not in action.replace("_", " "):
            continue
        rows.append((0 if text and label.lower().startswith(text) else 1, label, action))
    rows.sort(key=lambda r: (r[0], r[1].lower()) if text else 0)
    for _, label, action in rows[:40]:
        with dpg.group(horizontal=True, parent="palette_rows"):
            dpg.add_selectable(label=label, width=330, user_data=action,
                               callback=lambda s, a, u: (dpg.hide_item("palette_win"), app.run_action(u)))
            dpg.add_text(app.keys.label(action), color=DIM)
    if not rows:
        dpg.add_text("no action matches", parent="palette_rows", color=DIM)


def palette_enter(app):
    """Enter in the palette runs the first row."""
    for k in dpg.get_item_children("palette_rows", 1) or []:
        kids = dpg.get_item_children(k, 1) or []
        if kids and dpg.get_item_user_data(kids[0]):
            dpg.hide_item("palette_win")
            app.run_action(dpg.get_item_user_data(kids[0]))
            return


def show_undo_history(app):
    steps = app.gp.undo_steps()
    dpg.delete_item("undo_rows", children_only=True)
    for k, desc in enumerate(reversed(steps)):
        dpg.add_selectable(label=f"{len(steps) - k:3d}  {desc}", parent="undo_rows", user_data=k + 1,
                           callback=lambda s, a, u: (app.gp.undo_to(u), show_undo_history(app)))
    if not steps:
        dpg.add_text("nothing to undo", parent="undo_rows", color=DIM)
    _centre("undo_win", 420, 380)
    dpg.show_item("undo_win")


def _restore(app, kind, stem, ext, path):
    from native import history
    text = open(path, encoding="utf-8").read()
    if kind == "effects":
        fname = stem + ext
        app.project.write_effect(fname, text)          # keeps the current one
        app.edit_open(fname)
        app.edit_build()
    else:
        sub = kind == "subgraphs"
        d = app.gp.sub_dir if sub else app.gp.dir
        target = os.path.join(d, stem + ext)
        if os.path.exists(target):
            history.keep(app.project, kind, stem, ext, open(target, encoding="utf-8").read())
        open(target, "w", encoding="utf-8", newline="\n").write(text)
        app.gp.open(stem + ext, sub=sub)
        app.gp.touch()
    dpg.hide_item("history_win")
    app.gp.status(f"restored {os.path.basename(path)}")


# --- compare ------------------------------------------------------------------------------
def show_compare(app):
    """Pick the effect to run beside the current one."""
    dpg.delete_item("compare_menu", children_only=True)
    dpg.add_text(f"beside {app.eng.names[app.eng.idx]}, show", parent="compare_menu", color=DIM)
    with dpg.child_window(width=240, height=360, border=False, parent="compare_menu"):
        for n in app.eng.names:
            dpg.add_selectable(label=n, width=220, user_data=n,
                               callback=lambda s, a, u: (dpg.hide_item("compare_menu"), app.start_ab(u)))
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    dpg.configure_item("compare_menu", show=True)
    dpg.set_item_pos("compare_menu", [vw // 2 - 130, vh // 4])


# --- appearance, pane menus ----------------------------------------------------------------
def show_appearance(app):
    refresh_appearance(app)
    _centre("appearance_win", 560, 400)
    dpg.show_item("appearance_win")


def refresh_appearance(app):
    """The editor's swatches show the colours in force."""
    if not dpg.does_item_exist("app_preset"):
        return
    from native.app import theme_colors, THEME_PRESETS
    t = app.prefs.get("theme") or {}
    cols = theme_colors(app.prefs)
    name = t.get("preset") or ("light" if t.get("light") else "dark")
    changed = sorted(k for k in (t.get("colors") or {}) if k in cols and tuple(cols[k]) != tuple(THEME_PRESETS.get(name, {}).get(k, ())))
    dpg.set_value("app_preset", f"{name}" + (f", with {', '.join(changed)} changed" if changed else ""))
    for key in cols:
        if dpg.does_item_exist(f"app_col_{key}"):
            dpg.set_value(f"app_col_{key}", list(cols[key]) + [255])


def grip(pane):
    """The handle a pane is dragged by: ::: at its top right (placed by the
    layout; an item with a position is out of the flow). The app's click
    handler looks for the pointer on it (app.on_mouse_click)."""
    dpg.add_button(label=":::", tag=f"grip_{pane}", width=30, height=19, pos=(400, 8))
    if not dpg.does_item_exist("grip_theme"):
        # the default frame padding hides a third of the label
        with dpg.theme(tag="grip_theme"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 2)
    dpg.bind_item_theme(f"grip_{pane}", "grip_theme")
    with dpg.tooltip(f"grip_{pane}"):
        dpg.add_text("drag onto another pane to move this one there")


def _pane_menu(app, pane, rows):
    """A right-click menu on a pane: a popup window the app's right-click
    handler shows at the pointer (dpg.popup wants a container stack the
    build has already left, and a child window takes no item handlers)."""
    tag = f"{pane}_menu"
    with dpg.window(tag=tag, show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        for label, fn in rows:
            dpg.add_selectable(label=label, user_data=fn, callback=lambda s, a, u: (dpg.hide_item(tag), u()))

    # a child window takes no item handlers: the app's right-click handler
    # looks the panes up here
    app.pane_menus[pane] = tag
    app.FLOATING = tuple(app.FLOATING) + (tag,)


def build_pane_menus(app):
    """Right-click menus on the panes that had none: the two views and the
    code. The graph has its own."""
    _pane_menu(app, "cube_win", [
        ("Screenshot", lambda: setattr(app, "shot_req", True)),
        ("Record 15 s GIF", lambda: app.start_rec(15.0)),
        ("Reset the camera", lambda: (setattr(app, "yaw", -0.6), setattr(app, "pitch", 0.75), setattr(app, "dist", 4.6))),
        ("Compare with another effect...", lambda: app.run_action("compare")),
        ("Full frame (E)", lambda: app.set_layout("cube")),
        ("Pop out to its own window", lambda: app.set_popout("cube", True))])
    _pane_menu(app, "net_win", [
        ("Show / hide the wiring", lambda: setattr(app, "show_wiring", not app.show_wiring)),
        ("Screenshot", lambda: setattr(app, "shot_req", True)),
        ("Full frame (Q)", lambda: app.set_layout("net")),
        ("Pop out to its own window", lambda: app.set_popout("net", True))])
    _pane_menu(app, "side_win", [
        ("Expand every section", lambda: app.sec_all(True)),
        ("Collapse every section", lambda: app.sec_all(False)),
        ("Sections back in their original order", lambda: app.sec_reset())])
    _pane_menu(app, "edit_win", [
        ("Save", lambda: app.save_current()),
        ("Compile + reload", lambda: app.build_current()),
        ("Find / replace", lambda: app.focus_find()),
        ("Open in the external editor", lambda: app.open_external()),
        ("History...", lambda: show_history(app))])


# --- sweep --------------------------------------------------------------------------------
SWEEP_KEYS = ("sx", "ix", "c1", "c2", "c3")


def show_sweep(app):
    m = app.eng.meta[app.eng.idx]
    generic = {"sx": "Speed", "ix": "Intensity", "c1": "Custom 1", "c2": "Custom 2", "c3": "Custom 3"}
    labels = []
    for i, k in enumerate(SWEEP_KEYS):
        lab = (m["labels"][i] if i < len(m["labels"]) else "").strip()
        labels.append(f"{k}  {lab if lab and lab != '!' else generic[k]}")
    dpg.configure_item("sweep_key", items=labels)
    dpg.set_value("sweep_key", labels[0])
    _centre("sweep_win", 400, 190)
    dpg.show_item("sweep_win")


def _sweep_start(app):
    key = (dpg.get_value("sweep_key") or "sx").split()[0]
    dpg.hide_item("sweep_win")
    app.start_sweep(key, dpg.get_value("sweep_secs"), loop=dpg.get_value("sweep_loop") and not dpg.get_value("sweep_rec"),
                    record=dpg.get_value("sweep_rec"))


# --- state -> chrome ------------------------------------------------------------------
def refresh_files(app):
    """The Open submenus and the Add submenu follow the project."""
    if not dpg.does_item_exist("menu_open_graph"):
        return
    dpg.delete_item("menu_open_graph", children_only=True)
    for f in app.gp.files():
        dpg.add_menu_item(label=f[:-5], parent="menu_open_graph", user_data=f, callback=lambda s, a, u: app.open_graph(u))
    dpg.delete_item("menu_open_code", children_only=True)
    for f in app.project.effect_files():
        dpg.add_menu_item(label=app.project.effect_title(f), parent="menu_open_code", user_data=f,
                          callback=lambda s, a, u: app.open_code(u))
    dpg.delete_item("menu_open_project", children_only=True)
    from native.project import list_projects, recent_projects
    for p in list_projects():
        dpg.add_menu_item(label=p, parent="menu_open_project", user_data=p, callback=lambda s, a, u: app.switch_project(u))
    dpg.delete_item("menu_recent_project", children_only=True)
    for p in recent_projects():
        dpg.add_menu_item(label=os.path.basename(p), parent="menu_recent_project", user_data=p,
                          callback=lambda s, a, u: app.switch_project(u))
    dpg.delete_item("menu_add", children_only=True)
    cats = {}
    for name, d in app.gp.lib.items():
        cats.setdefault(d["cat"], []).append(name)
    order = ["controls", "signals", "coords", "generate", "maths", "colour", "graph", "subgraphs", "custom", "output"]
    for c in order + sorted(k for k in cats if k not in order):
        names = cats.get(c)
        if not names:
            continue
        with dpg.menu(label=c, parent="menu_add"):
            for n in sorted(names):
                dpg.add_menu_item(label=app.gp.lib[n].get("label") or n, user_data=n,
                                  callback=lambda s, a, u: app.add_node_from_menu(u))
    f = app.current_file()
    on = bool(f) and app.project.is_imported(f)
    dpg.configure_item("menu_import", label="Remove from the effects list" if on else "Add to the effects list",
                       enabled=bool(f))
    dpg.set_value("about_paths", f"project  {app.project.path}\nbuild    {app.build_dir()}")


def _signature(app):
    return (app.layout, app.ui, app.side, app.playing, app.gp.auto, app.gp.zoom, bool(app.gp.stack), app.building,
            app.gp.focus_mode, app.ab_name, bool(app.sweep), getattr(app, "ddp", None) is not None)


def refresh(app):
    """Toolbar tints and labels and the View menu's checks, from the app's state."""
    if not dpg.does_item_exist("toolbar"):
        return
    app._chrome_sig = _signature(app)
    # every icon in the plain text colour first (the theme may have changed
    # it), then the ones with a state of their own
    for child in dpg.get_item_children("toolbar", 1) or []:
        if "ImageButton" in dpg.get_item_type(child):
            dpg.configure_item(child, tint_color=TEXT)
    for k, (_, arr) in enumerate(app.PRESETS):
        if dpg.does_item_exist(f"menu_arr_{k}"):
            dpg.set_value(f"menu_arr_{k}", app.arrangement == arr)
    for v in ("net", "cube"):
        if dpg.does_item_exist(f"menu_pop_{v}"):
            dpg.set_value(f"menu_pop_{v}", app.popouts.is_out(v))
    if dpg.does_item_exist("menu_snap"):
        dpg.set_value("menu_snap", bool(app.prefs.get("snap")))
    from native.graph_ui import OVERVIEW_CHOICES, OVERVIEW_ZOOM
    ov = float(app.prefs.get("overview_zoom", OVERVIEW_ZOOM))
    for z, _ in OVERVIEW_CHOICES:
        if dpg.does_item_exist(f"menu_ov_{int(z * 100)}"):
            dpg.set_value(f"menu_ov_{int(z * 100)}", abs(z - ov) < 1e-6)
    for key, _, _ in LAYOUTS:
        on = app.layout == key and app.ui
        dpg.set_value(f"menu_view_{key}", on)
        dpg.configure_item(f"tb_view_{key}", tint_color=ACCENT if on else TEXT)
    dpg.set_value("menu_present", not app.ui)
    dpg.set_value("menu_side", app.side)
    if dpg.does_item_exist("menu_props"):
        dpg.set_value("menu_props", app.props)
    dpg.set_value("menu_focus", app.gp.focus_mode)
    if dpg.does_item_exist("mi_compare"):
        dpg.configure_item("mi_compare", label="Stop comparing" if app.ab else "Compare with another effect...")
    if dpg.does_item_exist("mi_sweep"):
        dpg.configure_item("mi_sweep", label="Stop the sweep" if app.sweep else "Sweep a slider...")
    dpg.set_value("menu_live", app.gp.auto)
    if dpg.does_item_exist("menu_stream"):
        dpg.set_value("menu_stream", getattr(app, "ddp", None) is not None)
    dpg.configure_item("tb_live", tint_color=AMBER if app.gp.auto else TEXT)
    dpg.configure_item("tb_build", tint_color=AMBER if app.building else TEXT)
    dpg.configure_item("tb_play", show=not app.playing, tint_color=GREEN)
    dpg.configure_item("tb_pause", show=app.playing)
    dpg.configure_item("rec_btn", tint_color=RED)
    dpg.configure_item("tb_zoom", label=f"{int(app.gp.zoom * 100)}%")


def poll(app):
    if getattr(app, "_chrome_sig", None) != _signature(app):
        refresh(app)
