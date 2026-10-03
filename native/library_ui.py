"""The Library frame: every effect the sim has, in three banks - the
project's **graphs**, the **usermod** effects (the cube effects of cube_fx
and the project's own code effects) and WLED's **stock** ones - each as a
looping thumbnail, with tags (for the graphs), a search box, and one click
to run it (a graph's opens in the graph pane too).

The thumbnails are made on a worker thread, on a second engine (the same
library copied under another name, as A/B does), so the one on screen is
not disturbed - the bank in front first, then the others. Each effect
starts on a clean cube (Engine.clear: every pixel off, the clock at 0 -
selecting an effect keeps the pixels, as WLED does, and a fading effect
showed the one before it), hears the studio's synthetic beat (an audio
effect is dark without sound), and is kept as 24 frames played round in a
dynamic texture. A bar under the buttons says how far the thumbnails, or
the previews being generated, have got.

    build(app)       # the window (device_ui.build calls it)
    refresh(app)     # the tiles of the bank in front, for the search text
    poll(app)        # per frame: the worker's thumbnails in, the next frame into each tile
"""
import os
import queue
import re
import threading
import time
import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

from native import weight
import numpy as np

from native import graph as G, render, paths

TAG = "library_win"
FRAMES = 24
TILE = 96
BANKS = (("graphs", "Graphs"), ("usermod", "Usermod effects"), ("stock", "Stock"))


def _c():
    from native import chrome
    return chrome


def build(app):
    c = _c()
    from native import device_ui
    app._lib_bank = app.prefs.get("library_bank", "graphs")
    with dpg.window(tag=TAG, show=False, width=px(640), height=px(560), no_collapse=True, no_title_bar=True):
        device_ui.header(app, "library")
        with dpg.tab_bar(tag="lib_banks", callback=lambda s, a: _set_bank(app, dpg.get_item_user_data(a))):
            for key, words in BANKS:
                dpg.add_tab(label=words, tag=f"lib_bank_{key}", user_data=key)
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="lib_search", hint="search names and tags", width=px(220), callback=lambda s, v: refresh(app))
            dpg.add_button(label="Remake the thumbnails", small=True, callback=lambda: remake(app))
            c.info("Every effect of the sim as a looping thumbnail, in three banks: the project's graphs, the usermod effects "
                   "(the cube effects and the project's code effects) and WLED's stock ones. Each is made on a clean cube, "
                   "hearing the synth's beat. Click a tile: its effect runs in the sim; a graph's waits in the graph pane "
                   "(built first if it never was).")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Generate previews", tag="lib_gen", small=True, callback=lambda: generate_previews(app))
            c.tip("a turn of the 3-D view for every effect of the bank in front, on the project's shape - a GIF and a PNG each "
                  "in export/library, with an index; the tiles then show those turns")
            dpg.add_input_float(tag="lib_gen_secs", width=px(60), default_value=3.0, step=0, format="%.0f s")
            dpg.add_checkbox(label="only the ones shown", tag="lib_gen_shown", default_value=False)
            dpg.add_button(label="Cancel", tag="lib_cancel", small=True, show=False, callback=lambda: cancel(app))
            dpg.add_button(label="Open the folder", small=True, callback=lambda: app.reveal(os.path.join(app.project.path, "export", "library")))
        with dpg.group(horizontal=True, tag="lib_progress_row", show=False):
            dpg.add_progress_bar(tag="lib_progress", default_value=0.0, width=px(260), overlay="")
            dpg.add_text("", tag="lib_progress_words", color=c.DIM)
        dpg.add_text("", tag="lib_status", color=c.DIM, wrap=0)      # a line of its own: at a row's end it was cut off
        with dpg.child_window(tag="lib_tiles", height=-1, border=False):
            pass
    if dpg.does_item_exist(f"lib_bank_{app._lib_bank}"):
        dpg.set_value("lib_banks", f"lib_bank_{app._lib_bank}")


def _set_bank(app, key):
    if not key:
        return
    app._lib_bank = key
    app.prefs["library_bank"] = key
    from native.project import save_prefs
    save_prefs(app.prefs)
    refresh(app)


# --- the banks -------------------------------------------------------------------------------
_UM_NAMES = {}


def usermod_names():
    """The names of the effects the usermods compiled into the sim register (cube_fx's), lower case:
    from their metadata in the firmware sources the engine is built of (the checkout's, else runtime/)."""
    dirs = [os.path.join(paths.TREE, "usermods", "cube_fx")] if paths.has_tree() else []
    dirs.append(os.path.join(paths.RUNTIME, "usermods", "cube_fx"))
    d = next((x for x in dirs if os.path.isdir(x)), None)
    if d is None:
        return set()
    key = (d, tuple(sorted(os.listdir(d))))
    if _UM_NAMES.get("key") != key:
        names = set()
        for f in os.listdir(d):
            if f.endswith(".cpp"):
                try:
                    text = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                for m in re.finditer(r'_data_FX_MODE_\w+\[\]\s*PROGMEM\s*=(?:\s|//[^\n]*\n)*"([^"@;]+)', text):
                    names.add(m.group(1).strip().lower())
        _UM_NAMES.update(key=key, names=names)
    return _UM_NAMES["names"]


def banks(app):
    """{"graphs": [(key, name, graph file)], "usermod": [(key, name, None)], "stock": [...]}: every effect of
    the sim's engine in its bank, by the engine's own name (the key the thumbnails are kept by). A graph
    not built yet is in its bank with no effect (key None) - a click builds it."""
    eng = app.eng
    names = list(eng.names)
    low = [n.strip().lower() for n in names]
    taken = set()
    graphs = []
    for fn in app.gp.files():
        name = _graph_name(app, fn)
        if name is None:
            continue
        k = _effect_index(app, eng, name)
        graphs.append((names[k] if k is not None else None, name, fn))
        if k is not None:
            taken.add(k)
    um = usermod_names()
    code = {app.project.effect_title(f).strip().lower() for f in app.project.effect_files()
            if not os.path.exists(os.path.join(app.gp.dir, os.path.splitext(f)[0] + ".json"))}
    usermod, stock = [], []
    for k, n in enumerate(names):
        if k in taken:
            continue
        if low[k] in um or low[k] in code or low[k] == "studio script":
            usermod.append((n, n, None))
        else:
            stock.append((n, n, None))
    return {"graphs": graphs, "usermod": usermod, "stock": stock}


def _graph_name(app, fn):
    cache = app.__dict__.setdefault("_lib_gnames", {})
    path = os.path.join(app.gp.dir, fn)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = cache.get(fn)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        g = G.load(path, lib=app.gp.lib, resolver=app.gp.resolve_sub)
    except Exception:
        return None
    cache[fn] = (mt, g.name)
    app.__dict__.setdefault("_lib_tags", {})[fn] = tags_of(app, g)
    return g.name


# --- tags ------------------------------------------------------------------------------------
def tags_of(app, g):
    from native.nodedefs import NEEDS
    tags = set()
    for n in g.nodes.values():
        d = g.node_def(n) if hasattr(g, "node_def") else None
        if d and d.get("cat"):
            tags.add(d["cat"])
        if NEEDS.get(n["type"]) == "audio":
            tags.add("audio")
        if NEEDS.get(n["type"]) == "imu":
            tags.add("motion")
        if n["type"] in ("Position", "Direction", "Cube face", "Cube ring", "Shape part", "Mirror fold"):
            tags.add("3-D")
        if n["type"] == "Effect settings":
            dim = n.get("params", {}).get("dimensions")
            if dim:
                tags.add(str(dim))
    try:
        from native.script import compile_script
        compile_script(g); tags.add("script")
    except Exception:
        pass
    return sorted(tags)


def _effect_index(app, eng, name):
    """The engine's effect for a graph's name (a family prefix tolerated)."""
    w = name.strip().lower()
    names = [n.split("@")[0].strip().lower() for n in eng.names]
    if w in names:
        return names.index(w)
    return next((i for i, n in enumerate(names) if n.endswith(" " + w) or w.endswith(" " + n)), None)


# --- the thumbnails, on a worker -----------------------------------------------------------------
def clean_frames(eng, k, n_frames, step_ms=40, every=3, syn=None, params=None, warm=0):
    """Effect k from a clean cube: every pixel off, the clock at 0, its own defaults (or `params`), the synth's
    beat heard (`syn`); `warm` frames run first; then every `every`th of n_frames * every frames kept (copies)."""
    eng.select(int(k), params=params)
    eng.clear()                                    # after the select: its effect from nothing, every pixel off
    if syn is not None:
        syn.last_beat = 0.0
    out = []
    for i in range(warm + n_frames * every):
        if syn is not None:
            syn.push(eng)
        eng.frame(step_ms)
        if i >= warm and (i - warm) % every == every - 1:
            out.append(eng.rgb().copy())
    return out


def _thumb_worker(app):
    """Thumbnails for every effect without one, the bank in front first: on a thread, its own engine,
    the frames into app._lib_tq as they are made. Ends when none is left (or the library is rebuilt)."""
    if getattr(app, "_lib_tjob", None) is not None and app._lib_tjob.is_alive():
        return
    try:
        eng = app.second_engine("library")
    except Exception as e:
        app.gp.status(f"no second engine for thumbnails: {e}"); return
    try:
        eng.set_geometry(app.project.geometry)
    except Exception:
        pass
    from native.synth import Synth
    syn = Synth()
    src = app.eng.library
    b = banks(app)
    order = [app._lib_bank] + [k for k, _ in BANKS if k != app._lib_bank]
    left = [key for bank in order for key, _, _ in b[bank] if key and key not in app._lib_thumbs]
    # a graph not built: run as a script in the Studio Script effect when the script has all its nodes
    scripts = {}
    for key, name, fn in b["graphs"]:
        no = app.__dict__.setdefault("_lib_noscript", set())
        if key is None and fn and _script_key(fn) not in app._lib_thumbs and fn not in no:
            prog = _script_of(app, fn)
            if prog is None:
                no.add(fn)                           # tried once: it has a node the script does not
            if prog is not None:
                scripts[_script_key(fn)] = prog
                app.__dict__.setdefault("_lib_scriptable", set()).add(_script_key(fn))
                left.insert(0 if app._lib_bank == "graphs" else len(left), _script_key(fn))
    if not left:
        return
    if getattr(app, "_lib_tq", None) is None:
        app._lib_tq = queue.Queue()
    stop = app._lib_tstop = threading.Event()
    done0 = sum(1 for bank in b.values() for key, _, _ in bank if key and key in app._lib_thumbs)
    total = done0 + len(left)

    def work():
        for i, key in enumerate(left):
            # the previews being generated go first: the two together crawled (a 1 s turn took over 6 s)
            while getattr(app, "_lib_gprog", None) is not None and not stop.is_set():
                stop.wait(0.2)
            if stop.is_set():
                break
            app._lib_tprog = (done0 + i, total, key)
            frames, params = None, None
            if key in scripts:                       # a graph not built: its script on the Studio Script effect
                prog, params = scripts[key]
                k = eng.script_effect() if eng.script(prog) else None
            else:
                k = eng.names.index(key) if key in eng.names else None
            if k is not None:
                try:
                    frames = clean_frames(eng, k, FRAMES, syn=syn, params=params)
                    if max(int(f.max()) for f in frames) < 12:
                        # dark at every third frame: a flash too short to be sampled (Strobe) - every frame, longer
                        frames = clean_frames(eng, k, FRAMES * 3, every=1, syn=syn, params=params)
                except Exception:
                    frames = None
            app._lib_tq.put((src, key, frames or []))
            time.sleep(0.002)                        # the GIL back to the frame now and then
        app._lib_tprog = None
    app._lib_tjob = threading.Thread(target=work, daemon=True)
    app._lib_tjob.start()


def _script_key(fn):
    return "script:" + fn


def _script_of(app, fn):
    """(bytecode, the Script effect's settings) of a graph, or None when the script cannot run it."""
    from native.script import compile_script, settings_of
    try:
        g = G.load(os.path.join(app.gp.dir, fn), lib=app.gp.lib, resolver=app.gp.resolve_sub)
        g.project_dir = app.project.path
        prog = compile_script(g)
    except Exception:
        return None
    st = settings_of(g)
    pal = st.pop("pal")
    return prog, dict(st, pal=pal)


def remake(app):
    """Every thumbnail made again (from clean cubes)."""
    stop = getattr(app, "_lib_tstop", None)
    if stop is not None:
        stop.set()
    job = getattr(app, "_lib_tjob", None)
    if job is not None:
        job.join(timeout=2.0)
    app._lib_thumbs = {}
    refresh(app)


def _poll_thumbs(app):
    q = getattr(app, "_lib_tq", None)
    got = 0
    while q is not None and got < 8:
        try:
            src, key, frames = q.get_nowait()
        except Exception:
            break
        if src == app.eng.library:
            app._lib_thumbs[key] = frames
            got += 1
    if got:
        app._lib_dirty = True


# --- the tiles -------------------------------------------------------------------------------
def refresh(app):
    if not dpg.does_item_exist("lib_tiles"):
        return
    c = _c()
    if not hasattr(app, "_lib_thumbs"):
        app._lib_thumbs, app._lib_tags = {}, {}
    if getattr(app, "_lib_src", None) != app.eng.library:
        app._lib_thumbs = {}; app._lib_src = app.eng.library      # a new build: its effects may have changed
        stop = getattr(app, "_lib_tstop", None)
        if stop is not None:
            stop.set()
    q = (dpg.get_value("lib_search") or "").strip().lower()
    dpg.delete_item("lib_tiles", children_only=True)
    b = banks(app)
    for key, words in BANKS:
        if dpg.does_item_exist(f"lib_bank_{key}"):
            dpg.configure_item(f"lib_bank_{key}", label=f"{words} ({len(b[key])})")
    rows = []
    for key, name, fn in b[app._lib_bank]:
        tags = app.__dict__.get("_lib_tags", {}).get(fn, []) if fn else []
        if q and q not in name.lower() and not any(q in t for t in tags):
            continue
        rows.append((key, name, fn, tags))
    app._lib_shown = rows
    width = max(TILE + 20, int(dpg.get_item_rect_size("lib_tiles")[0] or 600))
    per_row = max(1, (width - 12) // (TILE + 14))
    app._lib_tex = getattr(app, "_lib_tex", {})
    for i in range(0, len(rows), per_row):
        with dpg.group(horizontal=True, parent="lib_tiles"):
            for key, name, fn, tags in rows[i:i + per_row]:
                with dpg.group():
                    tkey = key or (_script_key(fn) if fn else None)
                    frames = app._lib_thumbs.get(tkey) if tkey else None
                    tex = _texture(app, tkey, frames) if frames else None
                    ud = (key, fn)
                    if tex:
                        dpg.add_image_button(tex, width=TILE, height=TILE, user_data=ud, callback=lambda s, a, u: open_tile(app, *u))
                    else:
                        words = ("making..." if tkey and tkey not in app._lib_thumbs and (key or _script_key(fn) in getattr(app, "_lib_scriptable", ()))
                                 else "not built\nyet" if fn and not key else "no picture")
                        dpg.add_button(label=words, width=TILE, height=TILE, user_data=ud, callback=lambda s, a, u: open_tile(app, *u))
                    short = name.replace("Ace 3-D ", "")
                    dpg.add_text(short[:14], color=c.TEXT)
                    if tags:
                        typeface.small(dpg.add_text(", ".join(tags)[:16], color=c.DIM))
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text(f"{name}" + (f"\n{fn}\ntags: {', '.join(tags) or 'none'}" if fn else "")
                                     + ("\nnot built yet: shown as the script runs it; a click builds it" if fn and not key and tex else ""),
                                     wrap=px(300))
    if not rows:
        if q:
            dpg.add_text("nothing matches", parent="lib_tiles", color=c.DIM)
        elif app._lib_bank == "graphs":
            weight.empty("lib_tiles", "No graphs in this project yet.", [("New effect...", lambda: app.new_effect())])
        else:
            dpg.add_text("none in this build", parent="lib_tiles", color=c.DIM)
    unbuilt = sum(1 for key, _, _ in b["graphs"] if key is None)
    dpg.set_value("lib_status", f"{len(rows)} shown; {len(app.eng.names)} effects in the sim - "
                                f"{len(b['graphs']) - unbuilt} graphs, {len(b['usermod'])} usermod, {len(b['stock'])} stock"
                                + (f"; {unbuilt} graph(s) not built - on the effects list they are built" if unbuilt else "")
                                + (f"\nlast run: {app._lib_note}" if getattr(app, "_lib_note", "") else ""))
    _thumb_worker(app)


def _texture(app, key, frames):
    """A dynamic texture for an effect's thumbnail; its frames follow the newest kept."""
    tag = f"lib_tex_{abs(hash(key)) % 10**8}"
    h, w = frames[0].shape[:2]
    old = app._lib_tex.get(tag)
    if old and old[1] == (w, h) and dpg.does_item_exist(tag):
        app._lib_tex[tag] = (key, (w, h), frames)
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    from native.textures import registry
    dpg.add_dynamic_texture(w, h, _rgba(frames[0]), tag=tag, parent=registry())
    app._lib_tex[tag] = (key, (w, h), frames)
    return tag


_rgba = render.texture_rgba


# --- previews: a turntable GIF for every effect of the bank, and the tiles from them ---------
def generate_previews(app, seconds=None, only=None):
    """Every effect of the bank in front (or the tiles shown, or `only`: engine names) rendered as a turn of
    the 3-D view on a worker, each from a clean cube hearing the synth: export/library/<name>.gif and .png,
    an index README, and the tiles take the turns as they finish."""
    from native.shape_preview import turntable, save
    from native.synth import Synth
    if getattr(app, "_lib_job", None) is not None and app._lib_job.is_alive():
        return
    seconds = max(1.0, min(15.0, float(seconds or dpg.get_value("lib_gen_secs") or 3.0)))
    if only:
        items = [(k, k, None) for k in only]
    elif dpg.get_value("lib_gen_shown"):
        items = [(key, name, fn) for key, name, fn, _ in getattr(app, "_lib_shown", [])]
    else:
        items = banks(app)[app._lib_bank]
    items = [it for it in items if it[0]]
    out_dir = os.path.join(app.project.path, "export", "library")
    os.makedirs(out_dir, exist_ok=True)
    app._lib_q = queue.Queue(); app._lib_made = 0
    app._lib_gstop = stop = threading.Event()
    app._lib_gprog = (0, len(items), "")
    dpg.configure_item("lib_gen", enabled=False)
    dpg.configure_item("lib_cancel", show=True)
    dpg.set_value("lib_progress_words", "")
    geom = app.project.geometry
    try:
        eng = app.second_engine("library_gen")   # made here, used only by the thread
    except Exception as e:
        dpg.configure_item("lib_gen", enabled=True); dpg.configure_item("lib_cancel", show=False)
        dpg.set_value("lib_status", f"no second engine: {e}"); app._lib_gprog = None; return

    def work():
        try:
            eng.set_geometry(geom)
        except Exception as e:
            app._lib_q.put(("done", f"no second engine: {e}")); return
        syn = Synth()
        index = ["# Effects\n", f"Previews of every effect on the project's shape ({geom.describe()}), a turn each.\n"]
        n = 0
        for i, (key, name, fn) in enumerate(items):
            if stop.is_set():
                break
            app._lib_gprog = (i, len(items), name)
            k = eng.names.index(key) if key in eng.names else None
            if k is None:
                app._lib_q.put(("skip", key, name)); continue
            try:
                frames = turntable(app, "effect", seconds, 15, 320, 1.0, eng=eng, effect=k, syn=syn)
                stem = os.path.splitext(fn)[0] if fn else re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
                gpath, ppath = save(app, frames, 15, name=os.path.join("library", stem))
                small = [_shrink(f, TILE) for f in frames]
                app._lib_q.put(("made", key, small, gpath))
                index.append(f"\n## {name}\n\n![{name}]({stem}.gif)\n" + (f"\n`{fn}`\n" if fn else ""))
                n += 1
            except Exception as e:
                app._lib_q.put(("skip", key, f"{name}: {e}"))
        try:
            open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8", newline="\n").write("".join(index))
        except OSError:
            pass
        app._lib_q.put(("done", (f"cancelled - {n} preview(s)" if stop.is_set() else f"{n} preview(s)") + " in export/library"))
    app._lib_job = threading.Thread(target=work, daemon=True); app._lib_job.start()


def cancel(app):
    """The previews being generated stop after the one in hand."""
    stop = getattr(app, "_lib_gstop", None)
    if stop is not None:
        stop.set()
        dpg.set_value("lib_progress_words", "stopping after this one...")


def _shrink(frame, size):
    """A frame to size x size (the tiles)."""
    try:
        from PIL import Image
        return np.asarray(Image.fromarray(frame).resize((size, size), Image.BILINEAR))
    except Exception:
        h, w = frame.shape[:2]
        k = max(1, min(h, w) // size)
        return frame[::k, ::k][:size, :size]


def _poll_previews(app):
    q = getattr(app, "_lib_q", None)
    if q is None:
        return
    for _ in range(4):
        try:
            item = q.get_nowait()
        except Exception:
            break
        if item[0] == "made":
            _, key, small, gpath = item
            app._lib_thumbs[key] = small
            app._lib_made = getattr(app, "_lib_made", 0) + 1
            app._lib_dirty = True
        elif item[0] == "skip":
            app.gp.status(f"preview skipped: {item[2]}")
        elif item[0] == "done":
            app._lib_note = item[1]                      # kept under the summary the redraw writes
            dpg.set_value("lib_status", item[1]); dpg.configure_item("lib_gen", enabled=True)
            dpg.configure_item("lib_cancel", show=False)
            app._lib_q = None; app._lib_gprog = None; app._lib_dirty = True
            app.gp.status(item[1])
            break


def _poll_progress(app):
    """The bar: the previews being generated, else the thumbnails being made; hidden when neither runs."""
    g, t = getattr(app, "_lib_gprog", None), getattr(app, "_lib_tprog", None)
    if g:
        i, n, name = g
        frac, words = (i / max(1, n)), f"previews: {i} of {n}" + (f" - {name.replace('Ace 3-D ', '')}" if name else "")
    elif t:
        i, n, name = t
        frac, words = (i / max(1, n)), f"thumbnails: {i} of {n} - {name.replace('Ace 3-D ', '')}"
    else:
        if dpg.is_item_shown("lib_progress_row"):
            dpg.configure_item("lib_progress_row", show=False)
        return
    if not dpg.is_item_shown("lib_progress_row"):
        dpg.configure_item("lib_progress_row", show=True)
    dpg.set_value("lib_progress", frac)
    dpg.configure_item("lib_progress", overlay=f"{int(frac * 100)}%")
    cur = dpg.get_value("lib_progress_words") or ""
    if cur != words and not cur.startswith("stopping"):
        dpg.set_value("lib_progress_words", words)


def poll(app):
    """Per frame: the worker's thumbnails and previews in; the tiles redrawn when some came (at most twice a
    second and a half); the bar; and, while the frame shows, the next frame into each tile every 80 ms."""
    if not hasattr(app, "_lib_thumbs"):
        app._lib_thumbs, app._lib_tags = {}, {}
    _poll_thumbs(app)
    _poll_previews(app)
    if dpg.does_item_exist("lib_progress_row"):
        _poll_progress(app)
    if not dpg.does_item_exist(TAG) or not dpg.is_item_shown(TAG):
        return
    now = time.time()
    if getattr(app, "_lib_dirty", False) and now - getattr(app, "_lib_redraw", 0.0) > 1.5:
        app._lib_dirty = False; app._lib_redraw = now
        refresh(app)
    if now - getattr(app, "_lib_tick", 0.0) < 0.08:
        return
    app._lib_tick = now
    k = int(now * 12.5)
    for tag, (key, _, frames) in list(getattr(app, "_lib_tex", {}).items()):
        if dpg.does_item_exist(tag) and frames:
            dpg.set_value(tag, _rgba(frames[k % len(frames)]))


def open_tile(app, key, fn):
    """A tile clicked: its effect runs in the sim; a graph's graph is the one the graph pane holds (the layout
    stays as it is) - a graph never built is built, as F5 would."""
    if fn:
        app.gp.open(fn)
    if key and key in app.eng.names:
        app.on_effect(None, key); dpg.set_value("fx_combo", key)
        app.gp.status(f"{key} running" + (f"; its graph is in the graph pane ({app.keys.label('pane_graph')})" if fn else ""))
    elif fn:
        app.gp.status(f"building {fn}...")
        app.gp.compile()


def open_graph(app, fn):
    """A graph's tile (kept for callers by file)."""
    name = _graph_name(app, fn)
    k = _effect_index(app, app.eng, name) if name else None
    open_tile(app, app.eng.names[k] if k is not None else None, fn)
