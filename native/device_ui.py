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

from native import flash, devices

FRAMES = {"devices": ("devices_win", "DEVICES", 640, 420),
          "flash": ("flash_win", "FLASH FIRMWARE", 720, 700),
          "send": ("send_win", "SEND TO DEVICE", 620, 360)}
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
    dpg.add_text(title, tag=f"{tag}_title", color=c.ACCENT)
    c.grip(tag)
    dpg.add_button(label="dock", tag=f"dock_{tag}", small=True, width=48, pos=(300, 9), user_data=slot,
                   callback=lambda s, a, u: app.undock_slot(u) if app.docked(u) else app.dock_slot(u))
    with dpg.tooltip(f"dock_{tag}"):
        dpg.add_text("dock: into the pane space, under the main pane (or drag the grip onto a pane)\nfloat: out again, over the panes")


def place_header(tag, w, docked):
    """The grip and the dock button at the frame's top right for its width."""
    if dpg.does_item_exist(f"grip_{tag}"):
        dpg.set_item_pos(f"grip_{tag}", [w - 40, 8])
    if dpg.does_item_exist(f"dock_{tag}"):
        dpg.set_item_pos(f"dock_{tag}", [w - 40 - 54, 9])
        dpg.configure_item(f"dock_{tag}", label="float" if docked else "dock")


# --- build --------------------------------------------------------------------------------
def build(app):
    c = _c()
    # DEVICES: the list, a scan, an address typed in
    with dpg.window(tag="devices_win", show=False, width=640, height=420, no_collapse=True, no_title_bar=True):
        header(app, "devices")
        dpg.add_text("WLED devices on the network. The active one (tick) is where every send and the flash go.",
                     color=c.DIM, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Scan the network", tag="dev_scan", callback=lambda: app.scan_devices("all"))
            dpg.add_button(label="Stop", tag="dev_scan_stop", enabled=False, callback=lambda: app.stop_scan())
            dpg.add_input_text(tag="dev_add_host", hint="or an address: 192.168.1.50", width=200,
                               on_enter=True, callback=lambda: app.add_device(dpg.get_value("dev_add_host")))
            dpg.add_button(label="Add", callback=lambda: app.add_device(dpg.get_value("dev_add_host")))
            dpg.add_button(label="Refresh all", callback=lambda: app.refresh_devices_info())
        dpg.add_text("", tag="dev_status", color=c.DIM, wrap=0)
        with dpg.child_window(tag="dev_rows", height=-70, border=True):
            pass
        with dpg.child_window(tag="dev_log", height=-1, border=False):
            pass
    # SEND: the active device, what it runs, the four sends
    with dpg.window(tag="send_win", show=False, width=620, height=360, no_collapse=True, no_title_bar=True):
        header(app, "send")
        dpg.add_text("to: no device chosen - Device > Devices...", tag="send_to", color=c.TEXT, wrap=0)
        dpg.add_text("", tag="send_running", color=c.DIM, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Read the device", small=True, callback=lambda: app.probe_active())
            dpg.add_button(label="Open in the browser", small=True, callback=lambda: app.open_device_page())
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send the graph as a script", tag="send_script_btn", width=250, callback=lambda: app.send_script())
            dpg.add_text("no build: bytecode to Studio Script", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send the current effect's settings", width=250, callback=lambda: app.push_settings())
            dpg.add_text("effect, sliders, palette, colours", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send the ledmap", width=250, callback=lambda: app.send_ledmap())
            dpg.add_button(label="Import the device's", callback=lambda: app.import_ledmap(host=app.active_host()))
            dpg.add_button(label="Import a file...", callback=lambda: dpg.show_item("ledmap_dialog"))
        dpg.add_separator()
        dpg.add_text("", tag="send_status", color=c.DIM, wrap=0)
        with dpg.child_window(tag="send_log", height=-1, border=False):
            pass
    build_flash(app)


def build_flash(app):
    """FLASH: stage, build, send - to the active device, on the environment
    that fits it (the device's chip suggests one)."""
    c = _c()
    app.flash_job = None
    envs, default = flash.read_envs()
    with dpg.window(tag="flash_win", show=False, width=720, height=700, no_collapse=True, no_title_bar=True):
        header(app, "flash")
        dpg.add_text("Stages the project's effects into the WLED tree as a usermod, builds the firmware on an "
                     "environment that extends the one chosen (its usermods plus ours), and sends the binary to "
                     "the active device's /update. The device must have OTA unlocked and be on this subnet.", color=c.DIM, wrap=0)
        dpg.add_text("to: no device chosen - Device > Devices...", tag="flash_to", color=c.TEXT, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_combo(envs, tag="flash_env", width=260, default_value=app.project.options.get("flash_env") or default or "",
                          callback=lambda: refresh_flash(app))
            dpg.add_text("environment", color=c.DIM)
            dpg.add_button(label="", tag="flash_env_fit", small=True, show=False,
                           callback=lambda: (dpg.set_value("flash_env", dpg.get_item_user_data("flash_env_fit")), refresh_flash(app)))
        with dpg.group(horizontal=True):
            dpg.add_text("EFFECTS TO SHIP", color=c.ACCENT)
            dpg.add_button(label="all", small=True, callback=lambda: _ship_all(app, True))
            dpg.add_button(label="none", small=True, callback=lambda: _ship_all(app, False))
            dpg.add_text("", tag="flash_budget", color=c.DIM)
        with dpg.child_window(tag="flash_fx", height=110, border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_text("FEATURES", color=c.ACCENT)
            dpg.add_text("what the firmware carries - untick what this device lacks, the build shrinks", color=c.DIM)
            dpg.add_button(label="Usermods...", small=True, callback=lambda: c.show_usermods(app))
        with dpg.child_window(tag="flash_features", height=232, border=True):
            pass
        with dpg.group(horizontal=True):
            dpg.add_checkbox(label="build", tag="flash_build", default_value=True)
            dpg.add_checkbox(label="send to the device", tag="flash_upload", default_value=True)
            dpg.add_button(label="Start", tag="flash_start", callback=lambda: start_flash(app))
            dpg.add_button(label="Cancel", tag="flash_cancel", enabled=False,
                           callback=lambda: app.flash_job and app.flash_job.cancel())
            dpg.add_button(label="Open the build folder", callback=lambda: app.reveal(os.path.join(flash.ROOT, ".pio", "build")))
        dpg.add_text("", tag="flash_status", color=c.DIM, wrap=0)
        with dpg.child_window(tag="flash_log", height=-1, border=True):
            pass


# --- showing -----------------------------------------------------------------------------
def show(app, which):
    tag, _, w, h = FRAMES[which]
    refresh_send(app)                                # the "to:" lines of both send and flash
    if which == "flash":
        refresh_flash(app)
    elif which == "devices":
        refresh_devices(app)
    if not app.docked(which):
        if not dpg.is_item_shown(tag):
            _c()._centre(tag, w, h)
            # three frames opened one after another cascade rather than stack
            k = list(FRAMES).index(which)
            x, y = dpg.get_item_pos(tag)
            dpg.set_item_pos(tag, [max(0, x + (k - 1) * 60), max(0, y + (k - 1) * 40)])
        dpg.show_item(tag)
        dpg.focus_item(tag)
    else:
        dpg.focus_item(tag)
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
        dpg.add_text("none yet - scan the network, or type an address", parent="dev_rows", color=c.DIM)
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
    if dpg.does_item_exist("send_script_btn"):
        dpg.configure_item("send_script_btn", enabled=not (d and d.get("script") is False))


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
            dpg.add_text(f"{kb / 1024:.1f} KB" if kb else "not measured yet", color=c.DIM)
    if not files:
        dpg.add_text("the effects list is empty - File > Add to the effects list", parent="flash_fx", color=c.DIM)
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


def start_flash(app):
    if app.flash_job and not app.flash_job.done:
        return
    c = _c()
    env = dpg.get_value("flash_env")
    host = app.active_host()
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
    for slot, (tag, _, _, _) in FRAMES.items():
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag) and not app.docked(slot):
            w = dpg.get_item_rect_size(tag)[0] or dpg.get_item_configuration(tag).get("width") or 0
            if w:
                place_header(tag, w, False)
    poll_flash(app)
