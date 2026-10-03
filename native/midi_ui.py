"""The MIDI window and the learn gesture (midi.py holds the port, the
messages and the maps). Window > MIDI and OSC...: the port, a target
and Learn, the mappings with a range each and a remove. A right-click on
a parameter slider offers Learn there, and so does a node pin's menu; a
learnt knob moves the slider, the picture and - with the sim streamed -
the device. OSC (osc.py) comes in beside it: a phone's or a tablet's
faders, on a UDP port the window turns on, learnt and mapped as the
knobs are.
"""
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import nodeface
from native import num
from native import typeface

from native import midi, osc, weight

TAG = "midi_win"


def _c():
    from native import chrome
    return chrome


def _st(app):
    return midi.state(app.project)


def build(app):
    c = _c()
    app.midi = midi.MidiIn()
    app.osc = osc.OscIn()
    app._midi_learn = None
    app._midi_opened = False
    app._osc_error = ""
    with dpg.window(tag=TAG, label="MIDI and OSC", no_title_bar=True, show=False, width=px(600), height=px(470), no_collapse=True):
        c.dialog_header(TAG, "MIDI and OSC")                    # one window style (C8): the frames' header
        dpg.add_text("", tag="midi_note", color=c.DIM, wrap=px(580))
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("PORT", color=c.ACCENT))
            dpg.add_combo([], tag="midi_port", width=px(300), callback=lambda s, v: open_port(app, v))
            dpg.add_button(label="Rescan", callback=lambda: refresh(app))
            c.tip("the MIDI inputs on this PC, listed again - plug the controller in, then Rescan")
            dpg.add_text("", tag="midi_last", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("OSC", color=c.ACCENT))
            dpg.add_checkbox(label="listen on UDP port", tag="osc_on", default_value=False,
                             callback=lambda s, v: set_osc(app, on=v))
            c.tip("a phone's or a tablet's faders - TouchOSC, Open Stage Control, a DAW's OSC out - sent to this "
                  "machine: Learn takes a fader as it takes a knob. OSC has no password: anyone on the network "
                  "who reaches the port can move what is mapped, so it is off until turned on here")
            typeface.mono(dpg.add_input_int(tag="osc_port", width=px(90), default_value=osc.DEFAULT_PORT, min_value=0,
                                            max_value=65535, min_clamped=True, max_clamped=True, step=0, on_enter=True,
                                            callback=lambda s, v: set_osc(app, port=int(v))))
            c.tip("the port the sender sends to (TouchOSC's outgoing port); Enter to listen there")
            dpg.add_text("", tag="osc_state", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("LEARN", color=c.ACCENT))
            dpg.add_combo([], tag="midi_target", width=px(300))
            dpg.add_button(label="Learn", tag="midi_learn_btn", width=px(80), callback=lambda: learn_from_combo(app))
            weight.primary(dpg.last_item())
            c.tip("then move the knob, the fader (or press the button) that should drive it; Learn again cancels")
            c.info("A target is a parameter slider, a check, the palette or the effect by index, or a typed value "
                   "on a pin of the graph open now (a pin's mapping belongs to that graph). A right-click on a "
                   "parameter slider, or a pin's menu, offers Learn there. One knob may drive several targets. "
                   "An OSC fader sends 0..1 (an int 0..127 is taken as MIDI's); an XY pad's two numbers are two controls.")
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("CLOCK", color=c.ACCENT))
            dpg.add_checkbox(label="the synth's beat follows it", tag="midi_clock_on", default_value=True,
                             callback=lambda s, v: _clock_setting(app, v))
            c.tip("a drum machine's or a DAW's MIDI clock on the port: each beat of it fires the synth's, and its "
                  "tempo is the synth's - while it plays; stopped, the synth keeps its own beat again")
            dpg.add_text("", tag="midi_clock", color=c.DIM)
        typeface.label(dpg.add_text("MAPPINGS", color=c.ACCENT))
        with dpg.child_window(tag="midi_rows", height=-1, border=True):
            pass
    # the right-click menu on a parameter slider
    with dpg.window(tag="midi_ctx", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        pass


def show(app):
    refresh(app)
    _c()._centre(TAG, 600, 470)
    dpg.show_item(TAG)


# --- targets ------------------------------------------------------------------------------
def _fx_labels(app):
    m = app.eng.meta[app.eng.idx]
    generic = {"sx": "Speed", "ix": "Intensity", "c1": "Custom 1", "c2": "Custom 2", "c3": "Custom 3",
               "o1": "Check 1", "o2": "Check 2", "o3": "Check 3"}
    out = {}
    for i, k in enumerate(midi.FX_KEYS + midi.CHECK_KEYS):
        lab = (m["labels"][i] if i < len(m["labels"]) else "").strip()
        out[k] = lab if lab and lab != "!" else generic[k]
    return out


def targets(app):
    """[(label, target)]: the sliders and checks of the effect on screen,
    the palette and the effect by index, the typed pins of the graph."""
    labels = _fx_labels(app)
    out = [(labels[k], {"kind": "fx", "key": k}) for k in midi.FX_KEYS]         # by the effect's own words, no keys (C9)
    m = app.eng.meta[app.eng.idx]
    for i, k in enumerate(midi.CHECK_KEYS):
        if 5 + i < len(m["labels"]) and m["labels"][5 + i].strip():
            out.append((labels[k], {"kind": "check", "key": k}))
    seen = {}
    for j, (lab, t) in enumerate(out):                                            # two the same: told apart by their place
        if lab in seen:
            out[j] = (f"{lab} ({'slider' if t['kind'] == 'fx' else 'check'} {midi.FX_KEYS.index(t['key']) + 1 if t['kind'] == 'fx' else midi.CHECK_KEYS.index(t['key']) + 1})", t)
        seen[lab] = True
    out.append(("the palette, by index", {"kind": "palette"}))
    out.append(("the effect, by index", {"kind": "effect"}))
    g = app.gp.graph
    if g and app.gp.file:
        wired = {(b, i) for _, _, b, i in g.links}
        for nid, n in sorted(g.nodes.items()):
            try:
                d = g.node_def(n)
            except Exception:
                continue
            for i in d["inputs"]:
                if i["type"] in ("float", "bool") and (nid, i["name"]) not in wired and app.gp.pin_read(n, i):
                    out.append((f"{n['type']} #{nid} . {nodeface.label(n['type'], i['name'])}", pin_target(app, nid, i["name"])))
    return out


def pin_target(app, nid, name):
    """A pin as a target: its range from the library where it has one,
    else about the value typed (0..1 for a fraction, 0..twice it otherwise)."""
    g = app.gp.graph
    n = g.nodes[nid]
    i = next(x for x in g.node_def(n)["inputs"] if x["name"] == name)
    t = {"kind": "pin", "graph": app.gp.file, "nid": int(nid), "name": name}
    if i["type"] == "bool":
        t["bool"] = True
        return t
    v = n.get("inputs", {}).get(name, i.get("default", 0.0))
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = 0.0
    if i.get("min") is not None and i.get("max") is not None:
        t["lo"], t["hi"] = float(i["min"]), float(i["max"])
    elif 0.0 <= v <= 1.0:
        t["lo"], t["hi"] = 0.0, 1.0
    else:
        t["lo"], t["hi"] = (0.0, round(2 * v, 4)) if v > 0 else (round(2 * v, 4), 0.0)
    return t


def target_label(app, t):
    kind = t.get("kind")
    if kind in ("fx", "check"):
        return _fx_labels(app).get(t.get("key"), t.get("key"))
    if kind == "palette":
        return "the palette"
    if kind == "effect":
        return "the effect"
    if kind == "pin":
        g = app.gp.graph
        n = g.nodes.get(t.get("nid")) if g and app.gp.file == t.get("graph") else None
        who = f"{n['type']} #{t['nid']}" if n else f"#{t.get('nid')} of {t.get('graph')}"
        return f"{who} . {nodeface.label(n['type'], t.get('name')) if n else t.get('name')}"
    return str(t)


def _same(a, b):
    """Two targets the same thing (a pin's range aside)."""
    keys = ("kind", "key", "graph", "nid", "name")
    return all(a.get(k) == b.get(k) for k in keys)


def mapped_to(app, target):
    """The controls bound to this target: [(k, ctl)]."""
    return [(k, tuple(m["ctl"])) for k, m in enumerate(_st(app)["maps"]) if _same(m["target"], target)]


# --- the window ---------------------------------------------------------------------------
def refresh(app):
    if not dpg.does_item_exist(TAG):
        return
    c = _c()
    st = _st(app)
    names = midi.ports()
    if not midi.available():
        dpg.set_value("midi_note", "python-rtmidi is not installed. In the studio's Python:  pip install python-rtmidi  "
                                   "then start the studio again; the mappings below are kept meanwhile.")
    elif not names:
        dpg.set_value("midi_note", "No MIDI input found. Plug the controller in and Rescan; a mapping learnt here "
                                   "moves the slider, the picture, and (with the sim streamed) the device.")
    else:
        dpg.set_value("midi_note", "Pick the port, pick what a knob should drive, press Learn, move the knob. A mapping "
                                   "moves the slider, the picture, and (with the sim streamed) the device.")
    dpg.configure_item("midi_port", items=names or ["(no MIDI input)"])
    dpg.set_value("midi_port", app.midi.port or st.get("port") or (names[0] if names else "(no MIDI input)"))
    items = [lab for lab, _ in targets(app)]
    dpg.configure_item("midi_target", items=items)
    if dpg.get_value("midi_target") not in items:
        dpg.set_value("midi_target", items[0] if items else "")
    dpg.configure_item("midi_learn_btn", label="cancel" if app._midi_learn else "Learn")
    dpg.set_value("midi_clock_on", bool(st.get("clock", True)))
    dpg.set_value("osc_on", bool(st["osc"].get("on")))
    dpg.set_value("osc_port", int(st["osc"].get("port", osc.DEFAULT_PORT)))
    dpg.set_value("osc_state", app._osc_error or (f"listening on {app.osc.port}" if app.osc.port else ""))
    dpg.delete_item("midi_rows", children_only=True)
    for k, m in enumerate(st["maps"]):
        t = m["target"]
        with dpg.group(horizontal=True, parent="midi_rows"):
            dpg.add_button(label="x", small=True, user_data=k, callback=lambda s_, a_, u: forget(app, u))
            weight.danger(dpg.last_item())
            c.tip("remove this mapping")
            dpg.add_text(f"{midi.ctl_label(tuple(m['ctl']))}  ->  {target_label(app, t)}")
            if t.get("kind") == "pin" and not t.get("bool"):
                for key in ("lo", "hi"):
                    dpg.add_input_float(width=px(80), step=0, format="%g", default_value=float(t.get(key, 0.0)), user_data=(k, key),
                                        callback=lambda s_, v, u: _set_range(app, u[0], u[1], v))
                c.tip("the pin's value at the knob's two ends")
    if not st["maps"]:
        weight.empty("midi_rows", "No knobs on anything yet: pick what above and Learn, then move a knob - or right-click "
                                  "a slider, or a pin in the graph.")
    _last(app)


def _last(app):
    if not dpg.does_item_exist("midi_last"):
        return
    l = max((x for x in (app.midi.last, app.osc.last) if x), key=lambda x: x[2], default=None)
    if l is None:
        dpg.set_value("midi_last", "")
    else:
        dpg.set_value("midi_last", f"last: {midi.ctl_label(l[0])} = " + (f"{l[1]:.3f}" if l[0][0] == "osc" else f"{l[1]}"))


def set_osc(app, on=None, port=None):
    """OSC on or off, or its port: the project's setting, and the listener with it."""
    o = _st(app)["osc"]
    if on is not None:
        o["on"] = bool(on)
    if port is not None:
        o["port"] = max(0, min(65535, int(port)))
    app.project.save()
    open_osc(app)
    refresh(app)


def open_osc(app, quiet=False):
    """The listener as the project has it: on its port, or closed. A port
    another program holds is said, and the setting kept for next time."""
    o = _st(app)["osc"]
    app.osc.close()
    app._osc_error = ""
    if not o.get("on"):
        if not quiet:
            app.gp.status("OSC: off")
        return
    try:
        # every interface, so a phone on the network reaches it ("host" in the project's setting narrows it:
        # the tests listen on the loopback, and a firewall is not asked)
        p = app.osc.open(int(o.get("port", osc.DEFAULT_PORT)), str(o.get("host") or "0.0.0.0"))
    except (OSError, ValueError, OverflowError) as e:
        app._osc_error = f"port {o.get('port')} cannot be opened ({getattr(e, 'strerror', None) or e})"
        app.gp.status(f"OSC: {app._osc_error}", "warn")
        return
    if not quiet:
        app.gp.status(f"OSC: listening on UDP port {p}")


def _set_range(app, k, key, v):
    st = _st(app)
    if 0 <= k < len(st["maps"]):
        st["maps"][k]["target"][key] = float(v)
        app.project.save()


def open_port(app, name):
    st = _st(app)
    if not name or name.startswith("("):
        return
    try:
        app.midi.open(name)
    except Exception as e:
        app.gp.status(f"MIDI: {e}"); return
    st["port"] = name
    app.project.save()
    app.gp.status(f"MIDI: listening on {name}")


def forget(app, k):
    midi.unbind(_st(app), k)
    app.project.save()
    refresh(app)


def learn_from_combo(app):
    lab = dpg.get_value("midi_target")
    t = next((t for l, t in targets(app) if l == lab), None)
    if app._midi_learn or t is None:
        learn(app, None)
    else:
        learn(app, t)


def learn(app, target):
    """The next control moved binds to `target`; None cancels."""
    app._midi_learn = target
    if target is not None:
        app.midi.drain()                                  # "the next control moved": from now, not the queue's past
        app.osc.drain()
    if dpg.does_item_exist("midi_learn_btn"):
        dpg.configure_item("midi_learn_btn", label="cancel" if target else "Learn")
    if target is None:
        app.gp.status("MIDI learn cancelled")
    elif not app.midi.port and not app.osc.port:
        app.gp.status(f"MIDI learn: move the knob for {target_label(app, target)} - no port is open yet (Window > MIDI and OSC)")
    else:
        app.gp.status(f"MIDI learn: move the knob for {target_label(app, target)}")


def slider_menu(app, key):
    """The right-click menu on a parameter slider: Learn, and the
    control(s) already on it to forget."""
    dpg.delete_item("midi_ctx", children_only=True)
    t = {"kind": "fx", "key": key}
    dpg.add_text(target_label(app, t), parent="midi_ctx", color=_c().DIM)
    dpg.add_selectable(label="MIDI learn: move a knob", parent="midi_ctx",
                       callback=lambda: (dpg.hide_item("midi_ctx"), learn(app, t)))
    for k, ctl in mapped_to(app, t):
        dpg.add_selectable(label=f"forget {midi.ctl_label(ctl)}", parent="midi_ctx", user_data=k,
                           callback=lambda s_, a_, u: (dpg.hide_item("midi_ctx"), forget(app, u)))
    x, y = dpg.get_mouse_pos(local=False)
    dpg.configure_item("midi_ctx", show=True)
    dpg.set_item_pos("midi_ctx", [x, y])


def hovered_slider():
    """The parameter slider under the pointer, by key, or None."""
    for k in midi.FX_KEYS:
        tag = f"inp_{k}"
        if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
            return k
    return None


# --- the port's clock ---------------------------------------------------------------------
def _clock_setting(app, on):
    _st(app)["clock"] = bool(on)
    app.project.save()


def _clock(app, st):
    """The port's MIDI clock onto the synth, while it plays and the setting
    is on: its beats fire the synth's, its tempo is the synth's (the tempo
    slider follows). Stopped or gone, the synth's own beat again."""
    n, bpm, playing = app.midi.take_clock()
    syn = getattr(app, "syn", None)
    if syn is None:
        return
    follow = bool(playing and st.get("clock", True))
    if follow != syn.external:
        syn.external = follow
        app.gp.status("MIDI clock: the synth's beat follows it" if follow
                      else "MIDI clock stopped: the synth keeps its own beat again")
    if follow:
        if bpm:
            b = int(round(max(30.0, min(200.0, bpm))))              # the tempo slider's range
            if b != syn.bpm:
                syn.bpm = b
                num.set("inp_bpm", b)
        if n:
            syn.kick_req = True
    if dpg.does_item_exist("midi_clock") and dpg.is_item_shown(TAG):
        if bpm is None:
            words = "a clock, finding its tempo..." if playing else ""
        else:
            words = f"{bpm:.1f} bpm, " + ("playing - the beat follows it" if follow else "playing" if playing else "stopped")
        if dpg.get_value("midi_clock") != words:
            dpg.set_value("midi_clock", words)


# --- each frame ---------------------------------------------------------------------------
def poll(app):
    m = getattr(app, "midi", None)
    if m is None:
        return
    st = _st(app)
    if not app._midi_opened:
        # the project's port, opened once when the studio starts (quietly when it is not there)
        app._midi_opened = True
        if st.get("port") and midi.available() and st["port"] in midi.ports():
            try:
                m.open(st["port"])
            except Exception:
                pass
    _clock(app, st)
    if getattr(app, "_osc_for", None) != app.project.path:
        app._osc_for = app.project.path                   # the project's OSC: opened as the studio starts, and as
        open_osc(app, quiet=True)                         # another project is opened - closed when its is off
    # (control, value, its full scale): a knob's 0..127, an OSC fader's 0..1
    evs = [(ctl, v, 127.0) for ctl, v in m.drain()] + [(ctl, v, 1.0) for ctl, v in app.osc.drain()]
    if not evs:
        return
    if app._midi_learn:
        ctl, v, full = evs[0]
        target = app._midi_learn
        midi.bind(st, ctl, target)
        app.project.save()
        app._midi_learn = None
        app.gp.status(f"MIDI: {midi.ctl_label(ctl)} -> {target_label(app, target)}")
        apply_target(app, target, v, full)
        if dpg.is_item_shown(TAG):
            refresh(app)
        return
    last = {}
    for ctl, v, full in evs:
        last[tuple(ctl)] = (v, full)
    for mp in st["maps"]:
        got = last.get(tuple(mp["ctl"]))
        if got is not None:
            apply_target(app, mp["target"], *got)
    if dpg.is_item_shown(TAG):
        _last(app)


def apply_target(app, t, v, full=127.0):
    """A control's value (0..127; 0..`full`, an OSC fader's 0..1) onto its
    target: the engine, and the widget that shows it."""
    kind = t.get("kind")
    val = midi.value_for(t, v, full)
    if kind == "fx":
        key = t["key"]
        if app.eng.fx.get(key) == val:
            return
        app.eng.fx[key] = val
        app.eng.push()
        num.set(f"inp_{key}", val)
    elif kind == "check":
        key = t["key"]
        if bool(app.eng.fx.get(key)) == val:
            return
        app.eng.fx[key] = 1 if val else 0
        app.eng.push()
        if dpg.does_item_exist("params"):
            for ch in dpg.get_item_children("params", 1):
                if dpg.get_item_user_data(ch) == key:
                    dpg.set_value(ch, val)
    elif kind == "palette":
        from native import app as appmod
        names = [p[0] for p in appmod.PALETTES]
        if not names:
            return
        name = names[int(round(val * (len(names) - 1)))]
        if dict(appmod.PALETTES)[name] != app.eng.pal:
            app.on_palette(None, name)
            if dpg.does_item_exist("pal_combo"):
                dpg.set_value("pal_combo", name)
    elif kind == "effect":
        names = app.eng.names
        idx = int(round(val * (len(names) - 1)))
        if idx != app.eng.idx:
            app.on_effect(None, names[idx])
            if dpg.does_item_exist("fx_combo"):
                dpg.set_value("fx_combo", names[idx])
    elif kind == "pin":
        g = app.gp.graph
        if not g or app.gp.file != t.get("graph") or t.get("nid") not in g.nodes:
            return
        app.gp.set_input_live(t["nid"], t["name"], val)
