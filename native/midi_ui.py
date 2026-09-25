"""The MIDI window and the learn gesture (midi.py holds the port, the
messages and the maps). Window > MIDI controller...: the port, a
target and Learn, the mappings with a range each and a remove. A
right-click on a parameter slider offers Learn there, and so does a
node pin's menu; a learnt knob moves the slider, the picture and - with
the sim streamed - the device.
"""
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import nodeface
from native import num
from native import typeface

from native import midi, weight

TAG = "midi_win"


def _c():
    from native import chrome
    return chrome


def _st(app):
    return midi.state(app.project)


def build(app):
    c = _c()
    app.midi = midi.MidiIn()
    app._midi_learn = None
    app._midi_opened = False
    with dpg.window(tag=TAG, label="MIDI controller", no_title_bar=True, show=False, width=px(600), height=px(440), no_collapse=True):
        c.dialog_header(TAG, "MIDI controller")                 # one window style (C8): the frames' header
        dpg.add_text("", tag="midi_note", color=c.DIM, wrap=px(580))
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("PORT", color=c.ACCENT))
            dpg.add_combo([], tag="midi_port", width=px(300), callback=lambda s, v: open_port(app, v))
            dpg.add_button(label="Rescan", callback=lambda: refresh(app))
            c.tip("the MIDI inputs on this PC, listed again - plug the controller in, then Rescan")
            dpg.add_text("", tag="midi_last", color=c.DIM)
        with dpg.group(horizontal=True):
            typeface.label(dpg.add_text("LEARN", color=c.ACCENT))
            dpg.add_combo([], tag="midi_target", width=px(300))
            dpg.add_button(label="Learn", tag="midi_learn_btn", width=px(80), callback=lambda: learn_from_combo(app))
            weight.primary(dpg.last_item())
            c.tip("then move the knob (or press the button) that should drive it; Learn again cancels")
            c.info("A target is a parameter slider, a check, the palette or the effect by index, or a typed value "
                   "on a pin of the graph open now (a pin's mapping belongs to that graph). A right-click on a "
                   "parameter slider, or a pin's menu, offers Learn there. One knob may drive several targets.")
        typeface.label(dpg.add_text("MAPPINGS", color=c.ACCENT))
        with dpg.child_window(tag="midi_rows", height=-1, border=True):
            pass
    # the right-click menu on a parameter slider
    with dpg.window(tag="midi_ctx", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        pass


def show(app):
    refresh(app)
    _c()._centre(TAG, 600, 440)
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
                if i["type"] in ("float", "bool") and (nid, i["name"]) not in wired:
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
    l = app.midi.last
    dpg.set_value("midi_last", f"last: {midi.ctl_label(l[0])} = {l[1]}" if l else "")


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
    if dpg.does_item_exist("midi_learn_btn"):
        dpg.configure_item("midi_learn_btn", label="cancel" if target else "Learn")
    if target is None:
        app.gp.status("MIDI learn cancelled")
    elif not app.midi.port:
        app.gp.status(f"MIDI learn: move the knob for {target_label(app, target)} - no port is open yet (Window > MIDI controller)")
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
    evs = m.drain()
    if not evs:
        return
    if app._midi_learn:
        ctl, v = evs[0]
        target = app._midi_learn
        midi.bind(st, ctl, target)
        app.project.save()
        app._midi_learn = None
        app.gp.status(f"MIDI: {midi.ctl_label(ctl)} -> {target_label(app, target)}")
        apply_target(app, target, v)
        if dpg.is_item_shown(TAG):
            refresh(app)
        return
    last = {}
    for ctl, v in evs:
        last[ctl] = v
    for mp in st["maps"]:
        v = last.get(tuple(mp["ctl"]))
        if v is not None:
            apply_target(app, mp["target"], v)
    if dpg.is_item_shown(TAG):
        _last(app)


def apply_target(app, t, v):
    """A control's value (0..127) onto its target: the engine, and the
    widget that shows it."""
    kind = t.get("kind")
    val = midi.value_for(t, v)
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
