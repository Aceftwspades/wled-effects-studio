"""The Device menu's three frames: Devices (finding them and choosing the
active one), Flash (build the firmware and send it) and Send (a graph as
a script, an effect's settings, the ledmap - to the active device).

Each is a Dear PyGui window of its own with the app's header - a title,
the ::: grip, a dock button - so it floats over the panes by default and
slots into the pane space like any other pane: the dock button puts it
under the main pane, the grip dragged onto a pane puts it beside or
above that one (app.move_slot), "float" takes it out again. Docked, the
window is placed and sized by the layout (app.relayout) and cannot be
moved by hand; floating, it can.

    build(app)            # the three windows, once, inside build_dialogs
    show(app, which)      # "devices" / "flash" / "send": to the front (docked or not)
    refresh_devices(app)  # the rows, from app.devices
    refresh_send(app)     # the "to:" line and what the device runs
    poll(app)             # per frame: scans and probes finishing, grips on floating frames
"""
import os
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import form
from native import typeface

from native import flash, devices, live_out, weight

# a frame's title is in sentence case, as a dialog's is (one window style, C8); the capitals are for its labels
FRAMES = {"devices": ("devices_win", "Devices", 640, 420),
          "flash": ("flash_win", "Flash firmware", 720, 660),
          "send": ("send_win", "Send to device", 620, 440),
          "shape": ("shape_win", "Shape", 600, 700),          # the shape editor (shape_ui.py), the same kind of frame
          "sequence": ("sequence_win", "Sequence", 640, 660),  # steps into presets and a playlist, and the schedule (sequence_ui.py)
          "library": ("library_win", "Library", 640, 520),     # the graphs as looping thumbnails (library_ui.py)
          "palettes": ("palettes_win", "Palettes", 560, 460),  # gradients of the project's own (palette_ui.py)
          "outputs": ("outputs_win", "LED outputs", 680, 400),  # the wiring as the device's busses, and the power (outputs_ui.py)
          "audioin": ("audioin_win", "Audio input", 640, 340)}  # the device's microphone or line-in module (audioin_ui.py)
HEADER_H = 30


def _c():
    from native import chrome
    return chrome


def header(app, slot):
    """A frame's first row: the title, then at the right the dock button
    and the grip. The two are positioned items (out of the flow) placed
    by the layout when docked and by poll() when floating."""
    tag, title, _, _ = FRAMES[slot]
    c = _c()
    typeface.heading(dpg.add_text(title, tag=f"{tag}_title", color=c.ACCENT))
    c.grip(tag)
    from native.icons import texture
    dpg.add_image_button(texture("dock", px(14)), tag=f"dock_{tag}", width=px(14), height=px(14), frame_padding=2, tint_color=c.TEXT,
                         pos=(300, 8), user_data=slot,
                         callback=lambda s, a, u: app.undock_slot(u) if app.docked(u) else app.dock_slot(u))
    with dpg.tooltip(f"dock_{tag}"):
        dpg.add_text("", tag=f"dock_{tag}_tip")
    _dock_tip(tag)
    dpg.add_image_button(texture("close", px(14)), tag=f"close_{tag}", width=px(14), height=px(14), frame_padding=2, tint_color=c.TEXT,
                         pos=(340, 8), user_data=slot, callback=lambda s, a, u: close(app, u))
    with dpg.tooltip(f"close_{tag}"):
        dpg.add_text("close (Esc while the frame has the focus); the menu opens it again")


def close(app, which):
    """The frame away: its tab in the dock, or its window."""
    from native import dock
    dock.close_frame(app, which)


def chrome_for(app, slot, docked):
    """A frame's own header - its title, float or dock, its grip, close - is
    for a floating frame; docked, its tab names it and the tab strip closes
    and floats it, and the frame's content starts at the top."""
    tag = FRAMES[slot][0]
    for t in (f"{tag}_title", f"dock_{tag}", f"grip_{tag}", f"close_{tag}"):
        if dpg.does_item_exist(t):
            dpg.configure_item(t, show=not docked)


def focused_frame(app):
    """The floating frame that has the keyboard, if any (its slot name)."""
    for slot, (tag, _, _, _) in FRAMES.items():
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag) and dpg.is_item_focused(tag) and not app.docked(slot):
            return slot
    return None


def _dock_tip(tag):
    dpg.set_value(f"dock_{tag}_tip", "dock: a tab beside the side panel's (or drag the grip onto the panes)")


def place_header(tag, w, docked):
    """The dock button, the grip and the close button at the frame's top
    right for its width: [dock] [:::] [x]. They show while the frame
    floats - docked, its tab names it and the dock's strip closes and
    floats it (chrome_for) - so the button is always the dock."""
    if dpg.does_item_exist(f"close_{tag}"):
        dpg.set_item_pos(f"close_{tag}", [w - px(30), px(8)])
    if dpg.does_item_exist(f"grip_{tag}"):
        dpg.set_item_pos(f"grip_{tag}", [w - px(30 + 36), px(8)])
    if dpg.does_item_exist(f"dock_{tag}"):
        dpg.set_item_pos(f"dock_{tag}", [w - px(30 + 36 + 26), px(8)])


# --- build --------------------------------------------------------------------------------
def build(app):
    c = _c()
    # DEVICES: the list, a scan, an address typed in
    with dpg.window(tag="devices_win", show=False, width=px(640), height=px(420), no_collapse=True, no_title_bar=True):
        header(app, "devices")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Scan the network", tag="dev_scan", callback=lambda: app.scan_devices("all"))
            weight.primary(dpg.last_item())
            c.tip("asks by mDNS, asks every known device for the nodes it has heard of, and sweeps the subnet")
            dpg.add_button(label="Stop", tag="dev_scan_stop", enabled=False, callback=lambda: app.stop_scan())
            dpg.add_input_text(tag="dev_add_host", hint="or an address: 192.168.1.50", width=px(200),
                               on_enter=True, callback=lambda: app.add_device(dpg.get_value("dev_add_host")))
            dpg.add_button(label="Add", callback=lambda: app.add_device(dpg.get_value("dev_add_host")))
            dpg.add_button(label="Refresh all", callback=lambda: app.refresh_devices_info())
            c.tip("asks every listed device again what it is and runs")
            c.info("WLED devices on the network. The ticked one is the active device: where every send and the flash go.")
        dpg.add_text("", tag="dev_status", color=c.DIM, wrap=0)
        with dpg.child_window(tag="dev_rows", height=-70, border=True):
            pass
        with dpg.child_window(tag="dev_log", height=-1, border=False):
            typeface.mono(dpg.last_container())         # a log: its lines in the monospace
            pass
    # SEND: the active device, what it runs, the four sends
    with dpg.window(tag="send_win", show=False, width=px(620), height=px(520), no_collapse=True, no_title_bar=True):
        header(app, "send")
        with dpg.group(horizontal=True):
            dpg.add_text("to: no device chosen - Device > Devices...", tag="send_to", color=c.TEXT, wrap=0)
            dpg.add_button(label="Find a device", tag="send_find", show=False, callback=lambda: show(app, "devices"))
            weight.primary(dpg.last_item())
        with dpg.group(horizontal=True):
            dpg.add_text("", tag="send_running", color=c.DIM, wrap=0)
            dpg.add_button(label="Read", small=True, callback=lambda: app.probe_active())
            weight.need(dpg.last_item(), "device")
            c.tip("ask the device again what it is and runs")
            dpg.add_button(label="Open in the browser", small=True, callback=lambda: app.open_device_page())
            weight.need(dpg.last_item(), "device")
            dpg.add_button(label="Calibrate the speed factor", small=True, callback=lambda: app.calibrate_factor())
            weight.need(dpg.last_item(), "device")
            c.tip("the current effect's settings sent, the device's fps read for three seconds, and the footer's "
                  "device fps estimate set from the measurement (Settings > Device speed factor holds the number)")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send the graph as a script", tag="send_script_btn", width=px(200), callback=lambda: app.send_script())
            weight.primary(dpg.last_item())
            weight.need(dpg.last_item(), _script_ok)
            c.tip("the graph as bytecode for the Studio Script effect - no firmware build; the device runs it at once")
            dpg.add_button(label="Send the effect's settings", width=px(200), callback=lambda: app.push_settings())
            weight.need(dpg.last_item(), "device")
            c.tip("the effect the sim shows, with its sliders, checks, palette and colours, onto the device's segment")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send the shape", width=px(200), callback=lambda: app.send_shape())
            weight.need(dpg.last_item(), "device")
            c.tip("the ledmap (the wiring) and the positions table, so Position and Direction see the real shape")
            dpg.add_button(label="Send the ledmap only", width=px(200), callback=lambda: app.send_ledmap())
            weight.need(dpg.last_item(), "device")
        with dpg.group(horizontal=True):
            dpg.add_text("ledmap", color=c.DIM)
            dpg.add_button(label="Import the device's", small=True, callback=lambda: app.import_ledmap(host=app.active_host()))
            weight.danger(dpg.last_item())
            weight.need(dpg.last_item(), "device")
            c.tip("the device's ledmap becomes the geometry: a matrix with its gaps and wiring, or a strip")
            dpg.add_button(label="Import a file...", small=True, callback=lambda: dpg.show_item("ledmap_dialog"))
        dpg.add_separator()
        # LIVE: the sim's frames to the device as they are drawn, and the wiring test
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("LIVE", color=c.ACCENT))
            dpg.add_checkbox(label="stream the sim to the device (DDP)", tag="live_on", default_value=False,
                             callback=lambda s, v: (app.stream_start(fps=int(dpg.get_value("live_fps").split()[0])) if v else app.stream_stop()))
            weight.need(dpg.last_item(), "stream")          # a device to stream to (or the stream running, to stop it)
            c.tip("whatever the sim shows - any effect, built or not - on the device as it is drawn; the device goes back to its own effect when this stops")
            form.inline("at")
            typeface.mono(dpg.add_combo(["15 fps", "30 fps", "60 fps"], tag="live_fps", width=px(96), default_value="30 fps",
                                        callback=lambda s, v: app.stream_start(fps=int(v.split()[0])) if getattr(app, "ddp", None) else None))
            dpg.add_text("", tag="live_status", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("WIRING TEST", color=c.ACCENT))
            dpg.add_combo(list(live_out.MODES), tag="wt_mode", width=px(120), default_value="off",
                          callback=lambda s, v: app.wiring_stop() if v == "off" else app.wiring_start(v))
            c.tip("in the sim, and on the device while streaming: a chase along the wiring order; one LED by its index; one part of a shape, "
                  "or the parts in turn; one LED output (the LED outputs frame's ranges); all red / green / blue / white for the colour "
                  "order; every other LED; a twinkle")
            form.inline("at")
            typeface.mono(dpg.add_input_float(tag="wt_speed", width=px(110), default_value=20.0, step=0, format="%.0f LEDs/s",
                                              callback=lambda s, v: setattr(app.wiring, "speed", max(0.5, float(v))) if getattr(app, "wiring", None) else None))
            c.tip("how fast the chase runs")
            dpg.add_button(label="<", small=True, callback=lambda: _wt_step(app, -1))
            dpg.add_button(label=">", small=True, callback=lambda: _wt_step(app, 1))
            typeface.mono(dpg.add_input_int(tag="wt_index", width=px(80), default_value=0, min_value=0, min_clamped=True, on_enter=True,
                                            callback=lambda s, v: _wt_set(app, int(v))))
            c.tip("the LED, the part or the output lit in the index, part and output modes; < and > step it")
        dpg.add_text("", tag="wt_status", color=c.TEXT, wrap=0)
        dpg.add_separator()
        dpg.add_text("", tag="send_status", color=c.DIM, wrap=0)
        with dpg.child_window(tag="send_log", height=-1, border=False):
            typeface.mono(dpg.last_container())         # a log: its lines in the monospace
            pass
    build_flash(app)
    build_wled_dialog(app)
    from native import shape_ui, sequence_ui, library_ui, palette_ui, outputs_ui, audioin_ui
    shape_ui.build(app)
    sequence_ui.build(app)
    library_ui.build(app)
    palette_ui.build(app)
    outputs_ui.build(app)
    audioin_ui.build(app)


def build_flash(app):
    """FLASH: stage, build, send - to the active device, on the environment
    that fits it (the device's chip suggests one)."""
    c = _c()
    app.flash_job = None
    envs, default = flash.read_envs()
    with dpg.window(tag="flash_win", show=False, width=px(720), height=px(660), no_collapse=True, no_title_bar=True):
        header(app, "flash")
        with dpg.group(horizontal=True):
            dpg.add_text("to: no device chosen - Device > Devices...", tag="flash_to", color=c.TEXT, wrap=0)
            c.info("Stages the project's effects into the WLED tree as a usermod, builds the firmware on an environment "
                   "that extends the one chosen (its usermods plus ours), and sends the binary to the device's /update. "
                   "The device must have OTA unlocked and be on this subnet.")
        with dpg.group(horizontal=True):
            form.inline("environment")
            dpg.add_combo(envs, tag="flash_env", width=px(260), default_value=app.project.options.get("flash_env") or default or "",
                          callback=lambda: refresh_flash(app))
            c.tip("the PlatformIO environment the build extends; the device's chip suggests one")
            dpg.add_button(label="", tag="flash_env_fit", small=True, show=False,
                           callback=lambda: (dpg.set_value("flash_env", dpg.get_item_user_data("flash_env_fit")), refresh_flash(app)))
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("WHAT GOES ON THE DEVICE", color=c.ACCENT))
            dpg.add_button(label="Preview (no compile)", small=True, callback=lambda: preview_build(app))
            c.tip("stages the build and lists what it would carry - the manifest, resolved the way the build resolves it - without compiling")
        with dpg.child_window(tag="flash_manifest", height=px(132), border=True):
            pass
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("EFFECTS TO SHIP", color=c.ACCENT))
            dpg.add_button(label="all", small=True, callback=lambda: _ship_all(app, True))
            dpg.add_button(label="none", small=True, callback=lambda: _ship_all(app, False))
            dpg.add_text("", tag="flash_budget", color=c.DIM)
        with dpg.child_window(tag="flash_fx", height=px(96), border=True):
            pass
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("FEATURES", color=c.ACCENT))
            dpg.add_button(label="Usermods...", small=True, callback=lambda: c.show_usermods(app))
            c.info("what the firmware carries: untick what this device lacks and the build shrinks; Usermods... has WLED's own too")
        with dpg.child_window(tag="flash_features", height=px(118), border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_button(label="Start", tag="flash_start", callback=lambda: start_flash(app))
            weight.primary(dpg.last_item())
            dpg.add_checkbox(label="build", tag="flash_build", default_value=True)
            dpg.add_checkbox(label="send to the device", tag="flash_upload", default_value=True)
            dpg.add_button(label="Cancel", tag="flash_cancel", enabled=False,
                           callback=lambda: app.flash_job and app.flash_job.cancel())
            weight.quiet(dpg.last_item())
            dpg.add_button(label="Open the build folder", callback=lambda: app.reveal(os.path.join(flash.ROOT, ".pio", "build")))
        dpg.add_text("", tag="flash_status", color=c.DIM, wrap=0)
        with dpg.child_window(tag="flash_log", height=-1, border=True):
            typeface.mono(dpg.last_container())         # a log: its lines in the monospace
            pass


# --- a WLED checkout for the flash -----------------------------------------------------------
def build_wled_dialog(app):
    from native import wledtree
    c = _c()
    with dpg.window(tag="wled_dialog", label="A WLED checkout", no_title_bar=True, show=False, width=px(560), height=px(300), no_collapse=True):
        _c().dialog_header("wled_dialog", "A WLED checkout")                 # one window style (C8): the frames' header
        dpg.add_text(f"The fork's {wledtree.BRANCH} branch - the firmware side the studio flashes - into:", color=c.DIM, wrap=px(540))
        dpg.add_input_text(tag="wled_dest", width=-1, default_value=wledtree.default_dest())
        with dpg.group(horizontal=True):
            dpg.add_button(label="Clone" if wledtree.has_git() else "Download", tag="wled_go", callback=lambda: fetch_wled(app))
            weight.primary(dpg.last_item())
            dpg.add_button(label="Restart the studio", tag="wled_restart", show=False, callback=lambda: (wledtree.restart(), dpg.stop_dearpygui()))
            weight.primary(dpg.last_item())
            dpg.add_button(label="Close", callback=lambda: dpg.hide_item("wled_dialog"))
            weight.quiet(dpg.last_item())
            dpg.add_text("" if wledtree.has_git() else "no git on the path: the branch comes as a zip (not a repository, which PlatformIO does not mind)",
                         color=c.DIM)
        with dpg.child_window(tag="wled_log", height=-1, border=True):
            typeface.mono(dpg.last_container())         # a log: its lines in the monospace
            pass
    with dpg.file_dialog(directory_selector=True, show=False, tag="wled_pick_dialog", width=px(640), height=px(420),
                         callback=lambda s, a: use_wled(app, a.get("file_path_name", ""))):
        pass


def show_wled_dialog(app):
    _c()._centre("wled_dialog", 560, 300)
    dpg.show_item("wled_dialog")


def _wled_log(line):
    if dpg.does_item_exist("wled_log"):
        dpg.add_text(line, parent="wled_log", color=_c().DIM, wrap=px(520))
        kids = dpg.get_item_children("wled_log", 1) or []
        for k in kids[:-12]:
            dpg.delete_item(k)
        dpg.set_y_scroll("wled_log", -1.0)                 # the newest line in view


def fetch_wled(app):
    """The clone (or the download) on a thread; its lines into the dialog;
    remembered and offered a restart when it lands."""
    import threading, queue
    from native import wledtree
    dest = (dpg.get_value("wled_dest") or "").strip()
    if not dest:
        return
    dpg.configure_item("wled_go", enabled=False)
    q = app._wled_q = queue.Queue()

    def work():
        try:
            got = wledtree.fetch(dest, log=lambda l: q.put(("line", l)))
            wledtree.remember(got)
            q.put(("done", got))
        except Exception as e:
            q.put(("fail", str(e)))
    threading.Thread(target=work, daemon=True).start()


def use_wled(app, folder):
    """A checkout the user already has, chosen in the file dialog."""
    import os as _os
    if not folder or not _os.path.isdir(_os.path.join(folder, "wled00")):
        app.gp.status(f"{folder or 'that'} is not a WLED checkout (no wled00/)"); return
    _remember_wled(app, folder)
    app.gp.status(f"WLED checkout remembered: {folder} - restart the studio to flash")
    show_wled_dialog(app); _wled_log(f"WLED checkout: {folder}"); dpg.configure_item("wled_restart", show=True)


def _remember_wled(app, folder):
    """Into the prefs file and the app's own prefs (which save_prefs writes whole)."""
    from native import wledtree
    from native.project import save_prefs
    wledtree.remember(folder)
    app.prefs["wled_root"] = folder
    save_prefs(app.prefs)


def poll_wled(app):
    q = getattr(app, "_wled_q", None)
    if q is None:
        return
    for _ in range(20):
        try:
            kind, v = q.get_nowait()
        except Exception:
            break
        if kind == "line":
            _wled_log(v)
        elif kind == "done":
            _remember_wled(app, v)
            _wled_log("remembered; restart the studio and the flash frame has it")
            dpg.configure_item("wled_restart", show=True); app._wled_q = None
        else:
            _wled_log(f"failed: {v}"); dpg.configure_item("wled_go", enabled=True); app._wled_q = None


# --- showing -----------------------------------------------------------------------------
def show(app, which):
    tag, _, w, h = FRAMES[which]
    refresh_send(app)                                # the "to:" lines of both send and flash
    if which == "flash":
        refresh_flash(app)
    elif which == "devices":
        refresh_devices(app)
    elif which == "shape":
        from native import shape_ui
        shape_ui.refresh(app)
    elif which == "sequence":
        from native import sequence_ui
        sequence_ui.refresh(app)
    elif which == "library":
        from native import library_ui
        library_ui.refresh(app)
    elif which == "palettes":
        from native import palette_ui
        palette_ui.refresh(app)
    elif which == "outputs":
        from native import outputs_ui
        outputs_ui.refresh(app)
    elif which == "audioin":
        from native import audioin_ui
        audioin_ui.refresh(app)
    # in the dock, its tab in front - over the panes only if it was floated (C8)
    from native import dock
    dock.open_frame(app, which)
    if which == "send":
        app.probe_active()


# --- the devices frame -------------------------------------------------------------------
def _device_line(d):
    bits = [d.get("arch") or "?"]
    if d.get("ver"):
        bits.append(f"WLED {d['ver']}")
    if d.get("fx"):
        bits.append(f"{d['fx']} effects")
    if d.get("script"):
        bits.append("Studio Script")
    elif d.get("script") is False:
        bits.append("no Studio Script")
    return ", ".join(bits)


def refresh_devices(app):
    if not dpg.does_item_exist("dev_rows"):
        return
    c = _c()
    active = app.active_host()
    dpg.delete_item("dev_rows", children_only=True)
    if not app.devices:
        weight.empty("dev_rows", "No devices yet: Scan the network (above) finds the WLEDs on this network; or type "
                                 "one's address and Add.")
    for d in app.devices:
        host = d["host"]
        on = host == active
        with dpg.group(horizontal=True, parent="dev_rows"):
            dpg.add_checkbox(default_value=on, user_data=host, callback=lambda s, a, u: app.set_active_device(u if a else ""))
            dpg.add_text(d.get("name") or host, color=c.ACCENT if on else c.TEXT)
            dpg.add_text(host, color=c.DIM)
            dpg.add_text(_device_line(d), color=c.TEXT if d.get("reachable", True) else c.RED)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(f"release {d.get('release', '?')}, build {d.get('vid', '?')}, mac {d.get('mac', '?')}\n"
                             f"last answered {d.get('seen', '?')}" + (f"\n{d['script_state']}" if d.get("script_state") else ""))
            if not d.get("reachable", True):
                dpg.add_text("not answering", color=c.RED)
            dpg.add_button(label="use", small=True, user_data=host, callback=lambda s, a, u: app.set_active_device(u), show=not on)
            dpg.add_button(label="remove", small=True, user_data=host, callback=lambda s, a, u: app.remove_device(u))
            weight.danger(dpg.last_item())
    n = len(app.devices)
    if not getattr(app, "_scan", None):
        dpg.set_value("dev_status", f"{n} device(s); active: {active or 'none'}")
    refresh_send(app)
    refresh_flash(app)
    _refresh_active_menu(app)


def _refresh_active_menu(app):
    """Device > Active device: one check item per known device."""
    if not dpg.does_item_exist("menu_active_device"):
        return
    dpg.delete_item("menu_active_device", children_only=True)
    active = app.active_host()
    if not app.devices:
        dpg.add_menu_item(label="none yet - Devices...", parent="menu_active_device", callback=lambda: show(app, "devices"))
    for d in app.devices:
        dpg.add_menu_item(label=f"{d.get('name') or d['host']}  ({d['host']})", check=True, default_value=d["host"] == active,
                          parent="menu_active_device", user_data=d["host"],
                          callback=lambda s, a, u: app.set_active_device(u if a else ""))


def dev_log(app, line):
    c = _c()
    if dpg.does_item_exist("dev_log"):
        dpg.add_text(line, parent="dev_log", color=c.DIM)
        kids = dpg.get_item_children("dev_log", 1) or []
        for k in kids[:-8]:
            dpg.delete_item(k)


# --- the send frame ----------------------------------------------------------------------
def _script_ok(app):
    """A device chosen that can run a script (one read without the Studio
    Script effect cannot)."""
    host = app.active_host()
    if not host:
        return False
    dv = app.active_device()
    return not (dv and dv.get("script") is False)


def refresh_send(app):
    if not dpg.does_item_exist("send_to"):
        return
    c = _c()
    d = app.active_device()
    host = app.active_host()
    if not host:
        line, col = "to: no device chosen - Device > Devices...", c.DIM
    elif d:
        line, col = f"to: {d.get('name') or host}  ({host}) - {_device_line(d)}", c.TEXT
    else:
        line, col = f"to: {host}", c.TEXT
    dpg.set_value("send_to", line); dpg.configure_item("send_to", color=col)
    if dpg.does_item_exist("flash_to"):
        dpg.set_value("flash_to", line); dpg.configure_item("flash_to", color=col)
    st = getattr(app, "_active_state", None)
    if st and host:
        fps = f", {st['fps']} fps" if st.get("fps") is not None else ""
        extra = f" - {st['script_state']}" if st.get("effect") == "Studio Script" and st.get("script_state") else ""
        dpg.set_value("send_running", f"running: {st['effect']}{fps}{' (off)' if st.get('on') is False else ''}{extra}")
    else:
        dpg.set_value("send_running", "")
    if dpg.does_item_exist("send_find"):
        dpg.configure_item("send_find", show=not host)             # no device: the way to one, beside the line that says so


def refresh_live(app):
    if dpg.does_item_exist("live_on"):
        on = getattr(app, "ddp", None) is not None
        dpg.set_value("live_on", on)
        if not on:
            dpg.set_value("live_status", "")


def _wt_step(app, d):
    wt = getattr(app, "wiring", None)
    if wt is None:
        app.wiring_start("index"); wt = app.wiring; dpg.set_value("wt_mode", "index")
    if wt.mode == "chase":
        wt.mode = "index"; dpg.set_value("wt_mode", "index"); wt.index = int(wt.pos)
    wt.index = max(0, wt.index + d)
    dpg.set_value("wt_index", wt.index)


def _wt_set(app, k):
    wt = getattr(app, "wiring", None)
    if wt is None:
        app.wiring_start("index"); wt = app.wiring; dpg.set_value("wt_mode", "index")
    if wt.mode == "chase":
        wt.mode = "index"; dpg.set_value("wt_mode", "index")
    wt.index = max(0, k)


def send_log(app, line):
    c = _c()
    if dpg.does_item_exist("send_status"):
        dpg.set_value("send_status", line)
    if dpg.does_item_exist("send_log"):
        dpg.add_text(line, parent="send_log", color=c.DIM)
        kids = dpg.get_item_children("send_log", 1) or []
        for k in kids[:-6]:
            dpg.delete_item(k)


# --- the flash frame ---------------------------------------------------------------------
def _ship_files(app):
    """The effects ticked to ship: the project's choice, else all of the list."""
    files = app.project.build_files()
    chosen = app.project.options.get("ship")
    return [f for f in files if chosen is None or f in chosen]


def _ship_all(app, on):
    app.project.options["ship"] = list(app.project.build_files()) if on else []
    app.project.save()
    refresh_flash(app)


def _ship_toggle(app, fname, on):
    cur = set(_ship_files(app))
    (cur.add if on else cur.discard)(fname)
    app.project.options["ship"] = [f for f in app.project.build_files() if f in cur]
    app.project.save()
    refresh_flash(app)


def refresh_flash(app):
    """The checklist of effects with their measured sizes, the budget for
    the chosen environment from its last build, and the environment the
    active device's chip suggests."""
    if not dpg.does_item_exist("flash_fx"):
        return
    c = _c()
    c._feature_rows(app)
    env = dpg.get_value("flash_env") or ""
    d = app.active_device()
    fit = devices.env_for(d, dpg.get_item_configuration("flash_env")["items"]) if d else None
    if fit and fit != env:
        dpg.configure_item("flash_env_fit", show=True, label=f"the device is an {d.get('arch')}: use {fit}", user_data=fit)
    else:
        dpg.configure_item("flash_env_fit", show=False)
    refresh_manifest(app, env)
    stats = (app.project.options.get("flash_stats") or {}).get(env) or {}
    sizes = stats.get("sizes") or {}                  # the effects in the last build: they set the base
    known = stats.get("known") or sizes               # every effect this env has ever measured
    ship = set(_ship_files(app))
    files = app.project.build_files()
    dpg.delete_item("flash_fx", children_only=True)
    for f in files:
        with dpg.group(horizontal=True, parent="flash_fx"):
            dpg.add_checkbox(default_value=f in ship, user_data=f, callback=lambda s, a, u: _ship_toggle(app, u, bool(a)))
            dpg.add_text(app.project.effect_title(f))
            kb = known.get(f)
            typeface.small(dpg.add_text(f"{kb / 1024:.1f} KB" if kb else "not measured yet", color=c.DIM))
    if not files:
        weight.empty("flash_fx", "The effects list is empty: the firmware carries the effects on it.",
                     [("Add this effect to the list", lambda: (app.toggle_import_current(), refresh_flash(app)))])
    if stats.get("partition"):
        base = stats["firmware"] - sum(sizes.values())
        avg = (sum(sizes.values()) / len(sizes)) if sizes else 4096
        est = base + sum(known.get(f, avg) for f in ship)
        over = est - stats["partition"]
        if base > stats["partition"]:
            dpg.set_value("flash_budget", f"no selection fits: {base // 1024} KB before any effect, "
                                          f"{stats['partition'] // 1024} KB partition")
            dpg.configure_item("flash_budget", color=c.RED)
        elif over > 0:
            dpg.set_value("flash_budget", f"about {est // 1024} KB of {stats['partition'] // 1024} KB - "
                                          f"{over // 1024} KB over: untick about {max(1, int(-(-over // avg)))} more")
            dpg.configure_item("flash_budget", color=c.RED)
        else:
            dpg.set_value("flash_budget", f"about {est // 1024} KB of {stats['partition'] // 1024} KB "
                                          f"({len(ship)} of {len(files)} effects; base firmware {base // 1024} KB)")
            dpg.configure_item("flash_budget", color=c.GREEN if over < -32768 else c.AMBER)
    else:
        dpg.set_value("flash_budget", f"{len(ship)} of {len(files)} - build once to measure the sizes and the room")
        dpg.configure_item("flash_budget", color=c.DIM)


def refresh_manifest(app, env=None):
    """The manifest lines into the frame: what this flash would carry, and
    what the active device runs now (with the last recorded flash to it)."""
    if not dpg.does_item_exist("flash_manifest"):
        return
    c = _c()
    env = env or dpg.get_value("flash_env") or ""
    dpg.delete_item("flash_manifest", children_only=True)
    from native import paths
    if not paths.has_tree():
        dpg.add_text("Flashing builds the firmware in a checkout of the WLED fork, and there is none here. "
                     "Get one below (a minute), or set WLED_ROOT to one you have; PlatformIO is needed too. "
                     "Everything else - the sim, building effects, every send to the device - needs neither.",
                     parent="flash_manifest", color=c.AMBER, wrap=0)
        with dpg.group(horizontal=True, parent="flash_manifest"):
            dpg.add_button(label="Get the WLED fork...", small=True, callback=lambda: show_wled_dialog(app))
            weight.primary(dpg.last_item())
            c.tip("clones the fork's branch beside the studio (or downloads it as a zip when git is not installed), "
                  "remembers where, and restarts the studio with it")
            dpg.add_button(label="I have one: choose its folder...", small=True, callback=lambda: dpg.show_item("wled_pick_dialog"))
        for t in ("flash_start", "flash_env"):
            if dpg.does_item_exist(t):
                dpg.configure_item(t, enabled=False)
        return
    if not env:
        dpg.add_text("choose an environment", parent="flash_manifest", color=c.DIM); return
    d = app.active_device()
    m = flash.manifest(app.project, env, _ship_files(app))
    for line in flash.manifest_text(m, d):
        col = c.RED if line.startswith("!!") else (c.AMBER if "NOT shipped" in line else c.TEXT)
        dpg.add_text(line, parent="flash_manifest", color=col, wrap=0)
    rec = flash.last_flash(app.project, app.active_host(), (d or {}).get("mac")) if app.active_host() else None
    if rec:
        dpg.add_text(f"last flashed from this project {rec['when']}: {rec['env']}, {len(rec['effects'])} studio effect(s) "
                     f"({', '.join(rec['effects'][:8])}{'...' if len(rec['effects']) > 8 else ''}), audio {rec['audio']}, sha256 {rec.get('sha256', '?')}",
                     parent="flash_manifest", color=c.DIM, wrap=0)
        gone = [e for e in rec["effects"] if e not in [t for _, t, _ in m["effects"]]]
        new = [t for _, t, _ in m["effects"] if t not in rec["effects"]]
        if gone or new:
            dpg.add_text("this flash would " + (f"add {', '.join(new)}" if new else "") + (" and " if new and gone else "")
                         + (f"drop {', '.join(gone)}" if gone else ""), parent="flash_manifest", color=c.AMBER, wrap=0)
    elif app.active_host():
        dpg.add_text("no flash from this project recorded for this device yet", parent="flash_manifest", color=c.DIM)


def preview_build(app):
    """Stage without compiling: the usermod folder written, the environment
    block written to platformio_override.ini, and both shown in the log."""
    c = _c()
    env = dpg.get_value("flash_env")
    from native import paths
    if not paths.has_tree():
        dpg.set_value("flash_status", "no WLED checkout: set WLED_ROOT to one and start the app again"); return
    if not env:
        dpg.set_value("flash_status", "choose an environment"); return
    dpg.delete_item("flash_log", children_only=True)
    lines = []
    try:
        studio_env = flash.stage(app.project, env, lines.append, _ship_files(app))
    except Exception as e:
        dpg.add_text(f"staging failed: {e}", parent="flash_log", color=c.RED); return
    for l in lines:
        dpg.add_text(l, parent="flash_log", color=c.TEXT)
    ini = os.path.join(flash.ROOT, "platformio_override.ini")
    text = open(ini, encoding="utf-8").read() if os.path.exists(ini) else ""
    if flash.MARK_BEGIN in text:
        block = text[text.index(flash.MARK_BEGIN):text.index(flash.MARK_END) + len(flash.MARK_END)]
        dpg.add_text("--- platformio_override.ini, the block the build uses ---", parent="flash_log", color=c.ACCENT)
        for l in block.splitlines():
            dpg.add_text(l, parent="flash_log", color=c.DIM)
    staged = os.path.join(flash.ROOT, "usermods", flash.USERMOD)
    if os.path.isdir(staged):
        names = sorted(os.listdir(staged))
        dpg.add_text(f"--- usermods/{flash.USERMOD}/: {len(names)} files ---", parent="flash_log", color=c.ACCENT)
        dpg.add_text(", ".join(names), parent="flash_log", color=c.DIM, wrap=0)
    dpg.set_value("flash_status", f"staged for {studio_env}; nothing compiled, nothing sent - Start builds this")
    dpg.configure_item("flash_status", color=c.DIM)


def start_flash(app):
    if app.flash_job and not app.flash_job.done:
        return
    c = _c()
    env = dpg.get_value("flash_env")
    host = app.active_host()
    from native import paths
    if not paths.has_tree():
        dpg.set_value("flash_status", "no WLED checkout: set WLED_ROOT to one and start the app again"); return
    if not env:
        dpg.set_value("flash_status", "choose an environment"); return
    if dpg.get_value("flash_upload") and not host:
        dpg.set_value("flash_status", "no device chosen to send to (Device > Devices...), or untick sending"); return
    app.project.options["flash_env"] = env
    app.project.save()
    dpg.delete_item("flash_log", children_only=True)
    done = app.gp.regenerate(app.project.build_files())
    if done:
        dpg.add_text(f"regenerated {len(done)} graph effect(s) with the current compiler", parent="flash_log", color=c.TEXT)
    dpg.set_value("flash_status", "working...")
    dpg.configure_item("flash_start", enabled=False)
    dpg.configure_item("flash_cancel", enabled=True)
    only = _ship_files(app)
    if not only:
        dpg.set_value("flash_status", "tick at least one effect to ship"); return
    app.flash_job = flash.Job(app.project, env, host, build=dpg.get_value("flash_build"),
                              upload=dpg.get_value("flash_upload"), only=only)
    app.flash_job.start()


def poll_flash(app):
    """Every frame: the job's lines into the log, its end into the status."""
    job = getattr(app, "flash_job", None)
    if job is None or not dpg.does_item_exist("flash_log"):
        return
    c = _c()
    n = 0
    while n < 60:
        try:
            line = job.q.get_nowait()
        except Exception:
            break
        dpg.add_text(line, parent="flash_log", color=c.RED if "error" in line.lower() else c.TEXT)
        n += 1
    if n:
        dpg.set_y_scroll("flash_log", -1.0)
    if job.done and not getattr(job, "_shown", False):
        job._shown = True
        dpg.set_value("flash_status", job.result)
        dpg.configure_item("flash_status", color=c.GREEN if job.ok else c.RED)
        dpg.configure_item("flash_start", enabled=True)
        dpg.configure_item("flash_cancel", enabled=False)
        if job.stats:
            st = dict(app.project.options.get("flash_stats") or {})
            st[job.base_env] = job.stats
            app.project.options["flash_stats"] = st
            app.project.save()
            refresh_flash(app)
        if job.ok and job.upload:
            app.refresh_devices_info(only=app.active_host())


# --- per frame ---------------------------------------------------------------------------
def poll(app):
    """Floating frames keep their grip and dock button at the top right
    as they are resized; docked ones are placed by the layout."""
    poll_wled(app)
    for slot, (tag, _, _, _) in FRAMES.items():
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag) and not app.docked(slot):
            w = dpg.get_item_rect_size(tag)[0] or dpg.get_item_configuration(tag).get("width") or 0
            if w:
                place_header(tag, w, False)
    poll_flash(app)
    from native import shape_ui, sequence_ui, library_ui, palette_ui, outputs_ui, audioin_ui
    shape_ui.poll(app)
    sequence_ui.poll(app)
    library_ui.poll(app)
    palette_ui.poll(app)
    outputs_ui.poll(app)
    audioin_ui.poll(app)
