"""The Library frame: every graph of the project as a looping thumbnail,
with tags, a search box, and one click to open it.

The thumbnails come from a second engine (the same library copied under
another name, as A/B does), so the one on screen is not disturbed: each
graph's effect is run for a second at the project's geometry and its
frames kept - 24 of them, played round in a dynamic texture. Tags are
read off the graph: the node categories it uses, audio, 3-D, its
dimensions, and whether it runs as a script.

    build(app)       # the window (device_ui.build calls it)
    refresh(app)     # the tiles for the search text; thumbnails made when missing
    poll(app)        # per frame: the next frame into each visible thumbnail
"""
import os
import time
import dearpygui.dearpygui as dpg
import numpy as np

from native import graph as G, render

TAG = "library_win"
FRAMES = 24
TILE = 96


def _c():
    from native import chrome
    return chrome


def build(app):
    c = _c()
    from native import device_ui
    with dpg.window(tag=TAG, show=False, width=640, height=520, no_collapse=True, no_title_bar=True):
        device_ui.header(app, "library")
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="lib_search", hint="search names and tags", width=220, callback=lambda s, v: refresh(app))
            dpg.add_button(label="Remake the thumbnails", small=True, callback=lambda: (app._lib_thumbs.clear() if hasattr(app, "_lib_thumbs") else None, refresh(app)))
            dpg.add_text("", tag="lib_status", color=c.DIM)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Generate previews", tag="lib_gen", callback=lambda: generate_previews(app))
            dpg.add_input_float(tag="lib_gen_secs", width=60, default_value=3.0, step=0, format="%.0f s")
            dpg.add_checkbox(label="only the ones shown", tag="lib_gen_shown", default_value=False)
            dpg.add_button(label="Open the folder", small=True, callback=lambda: app.reveal(os.path.join(app.project.path, "export", "library")))
            dpg.add_text("", tag="lib_gen_status", color=c.DIM)
        dpg.add_text("click a tile to open the graph and run its effect; the tags are what the graph uses. Generate previews renders a "
                     "turn of the 3-D view for every effect on the project's shape - a GIF and a PNG each in export/library, with an index - "
                     "and the tiles show those turns", color=c.DIM, wrap=0)
        with dpg.child_window(tag="lib_tiles", height=-1, border=False):
            pass


# --- tags and thumbnails ------------------------------------------------------------------
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


def _thumb_engine(app):
    if getattr(app, "_lib_eng_src", None) != app.eng.library:
        # a new library (the effects rebuilt): the thumbnails are stale too
        app._lib_thumbs = {}; app._lib_eng_src = app.eng.library
    try:
        eng = app.second_engine("library")
    except Exception as e:
        app.gp.status(f"no second engine for thumbnails: {e}"); return None
    try:
        if eng.cols != app.eng.cols or eng.rows != app.eng.rows:
            eng.set_geometry(app.project.geometry)
    except Exception:
        pass
    return eng


def _make_thumb(app, eng, name):
    """24 frames of the effect, (rows, cols, 3) uint8 each, or None."""
    k = _effect_index(app, eng, name)
    if k is None:
        return None
    try:
        eng.select(k)
        frames = []
        for i in range(FRAMES * 3):
            eng.frame(40)
            if i % 3 == 2:
                frames.append(eng.rgb().copy())
        return frames
    except Exception:
        return None


def refresh(app):
    if not dpg.does_item_exist("lib_tiles"):
        return
    c = _c()
    if not hasattr(app, "_lib_thumbs"):
        app._lib_thumbs = {}
        app._lib_tags = {}
    q = (dpg.get_value("lib_search") or "").strip().lower()
    dpg.delete_item("lib_tiles", children_only=True)
    files = app.gp.files()
    eng = _thumb_engine(app)
    rows = []
    t0 = time.time()
    made = 0
    for fn in files:
        try:
            g = G.load(os.path.join(app.gp.dir, fn), lib=app.gp.lib, resolver=app.gp.resolve_sub)
        except Exception:
            continue
        if fn not in app._lib_tags:
            app._lib_tags[fn] = tags_of(app, g)
        tags = app._lib_tags[fn]
        if q and q not in g.name.lower() and not any(q in t for t in tags):
            continue
        if fn not in app._lib_thumbs and eng is not None and made < 12:
            app._lib_thumbs[fn] = _make_thumb(app, eng, g.name); made += 1
        rows.append((fn, g.name, tags))
    app._lib_shown = [fn for fn, _, _ in rows]
    width = max(TILE + 20, int(dpg.get_item_rect_size("lib_tiles")[0] or 600))
    per_row = max(1, (width - 12) // (TILE + 14))
    app._lib_tex = getattr(app, "_lib_tex", {})
    for i in range(0, len(rows), per_row):
        with dpg.group(horizontal=True, parent="lib_tiles"):
            for fn, name, tags in rows[i:i + per_row]:
                with dpg.group():
                    frames = app._lib_thumbs.get(fn)
                    tex = _texture(app, fn, frames)
                    if tex:
                        dpg.add_image_button(tex, width=TILE, height=TILE, user_data=fn, callback=lambda s, a, u: open_graph(app, u))
                    else:
                        dpg.add_button(label="no\npreview", width=TILE, height=TILE, user_data=fn, callback=lambda s, a, u: open_graph(app, u))
                    dpg.add_text(name[:14], color=c.TEXT)
                    dpg.add_text(", ".join(tags)[:16], color=c.DIM)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text(f"{name}\n{fn}\ntags: {', '.join(tags) or 'none'}", wrap=300)
    if not rows:
        dpg.add_text("nothing matches" if q else "no graphs in this project", parent="lib_tiles", color=c.DIM)
    left = sum(1 for fn, _, _ in rows if fn not in app._lib_thumbs)
    dpg.set_value("lib_status", f"{len(rows)} graph(s)" + (f", {made} thumbnails made in {time.time() - t0:.1f} s" if made else "") + (f", {left} more next refresh" if left else ""))
    if left:
        app._lib_more = True


# --- previews: a turntable GIF for every effect, and the tiles from them ---------------------
def generate_previews(app, seconds=None, only=None):
    """Every graph's effect (or the tiles shown) rendered as a turn of the
    3-D view on a worker: export/library/<stem>.gif and .png each, an
    index README, and the tiles take the turns as they finish."""
    import threading, queue
    from native.shape_preview import turntable, save
    from native.script import settings_of
    if getattr(app, "_lib_job", None) is not None and app._lib_job.is_alive():
        return
    seconds = max(1.0, min(15.0, float(seconds or dpg.get_value("lib_gen_secs") or 3.0)))
    files = list(only) if only else (list(getattr(app, "_lib_shown", [])) if dpg.get_value("lib_gen_shown") else app.gp.files())
    graphs = []
    for fn in files:
        try:
            graphs.append((fn, G.load(os.path.join(app.gp.dir, fn), lib=app.gp.lib, resolver=app.gp.resolve_sub)))
        except Exception:
            pass
    out_dir = os.path.join(app.project.path, "export", "library")
    os.makedirs(out_dir, exist_ok=True)
    app._lib_q = queue.Queue(); app._lib_made = 0
    dpg.configure_item("lib_gen", enabled=False)
    dpg.set_value("lib_gen_status", f"0 of {len(graphs)}")
    geom = app.project.geometry
    try:
        eng = app.second_engine("library_gen")   # made here, used only by the thread
    except Exception as e:
        dpg.configure_item("lib_gen", enabled=True); dpg.set_value("lib_gen_status", f"no second engine: {e}"); return

    def work():
        try:
            eng.set_geometry(geom)
        except Exception as e:
            app._lib_q.put(("done", f"no second engine: {e}")); return
        index = ["# Effects\n", f"Previews of every effect on the project's shape ({geom.describe()}), a turn each.\n"]
        n = 0
        for fn, g in graphs:
            k = _effect_index(app, eng, g.name)
            if k is None:
                app._lib_q.put(("skip", fn, g.name)); continue
            try:
                st = settings_of(g); pal = st.pop("pal")
                frames = turntable(app, "effect", seconds, 15, 320, 1.0, eng=eng, effect=k, params=dict(st, pal=pal))
                stem = os.path.splitext(fn)[0]
                gpath, ppath = save(app, frames, 15, name=os.path.join("library", stem))
                small = [_shrink(f, TILE) for f in frames]
                app._lib_q.put(("made", fn, small, gpath))
                index.append(f"\n## {g.name}\n\n![{g.name}]({stem}.gif)\n\n`{fn}`\n")
                n += 1
            except Exception as e:
                app._lib_q.put(("skip", fn, f"{g.name}: {e}"))
        try:
            open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8", newline="\n").write("".join(index))
        except OSError:
            pass
        app._lib_q.put(("done", f"{n} preview(s) in export/library"))
    app._lib_job = threading.Thread(target=work, daemon=True); app._lib_job.start()


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
    changed = False
    for _ in range(4):
        try:
            item = q.get_nowait()
        except Exception:
            break
        if item[0] == "made":
            _, fn, small, gpath = item
            if not hasattr(app, "_lib_thumbs"):
                app._lib_thumbs = {}; app._lib_tags = {}
            app._lib_thumbs[fn] = small
            tag = f"lib_tex_{abs(hash(fn)) % 10**8}"
            if tag in getattr(app, "_lib_tex", {}):
                app._lib_tex.pop(tag, None)
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            app._lib_made = getattr(app, "_lib_made", 0) + 1
            dpg.set_value("lib_gen_status", f"{app._lib_made} made - {os.path.basename(gpath)}")
            changed = True
        elif item[0] == "skip":
            dpg.set_value("lib_gen_status", f"skipped {item[2]} (no effect of that name in the build)")
        elif item[0] == "done":
            dpg.set_value("lib_gen_status", item[1]); dpg.configure_item("lib_gen", enabled=True)
            app._lib_q = None; changed = True
            app.gp.status(item[1])
            break
    if changed:
        refresh(app)


def _texture(app, fn, frames):
    """A dynamic texture for a graph's thumbnail, made once; None without frames."""
    if not frames:
        return None
    tag = f"lib_tex_{abs(hash(fn)) % 10**8}"
    h, w = frames[0].shape[:2]
    if tag in app._lib_tex and app._lib_tex[tag][1] == (w, h) and dpg.does_item_exist(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.texture_registry():
        dpg.add_dynamic_texture(w, h, _rgba(frames[0]), tag=tag)
    app._lib_tex[tag] = (fn, (w, h), frames)
    return tag


_rgba = render.texture_rgba


def poll(app):
    """The thumbnails loop while the frame shows: the next frame of each every 80 ms."""
    _poll_previews(app)
    if not dpg.does_item_exist(TAG) or not dpg.is_item_shown(TAG):
        return
    now = time.time()
    if now - getattr(app, "_lib_tick", 0.0) < 0.08:
        return
    app._lib_tick = now
    k = int(now * 12.5)
    for tag, (fn, _, frames) in list(getattr(app, "_lib_tex", {}).items()):
        if dpg.does_item_exist(tag) and frames:
            dpg.set_value(tag, _rgba(frames[k % len(frames)]))
    if getattr(app, "_lib_more", False):
        app._lib_more = False
        refresh(app)


def open_graph(app, fn):
    """A tile clicked: its effect runs in the sim and its graph is the one
    the graph pane holds - the layout stays as it is (it used to jump to
    the full-frame graph, which nobody asked for by clicking a tile)."""
    app.gp.open(fn)
    name = None
    try:
        g = G.load(os.path.join(app.gp.dir, fn), lib=app.gp.lib, resolver=app.gp.resolve_sub)
        k = _effect_index(app, app.eng, g.name)
        if k is not None:
            name = app.eng.names[k]
            app.on_effect(None, name); dpg.set_value("fx_combo", name)
    except Exception:
        pass
    if name:
        app.gp.status(f"{name} running; its graph is in the graph pane ({app.keys.label('pane_graph')})")
    else:
        # not built yet (a graph never compiled in this project): compile it and
        # rebuild the sim, which then selects it - the same as F5 on the graph
        app.gp.status(f"building {fn}...")
        app.gp.compile()
