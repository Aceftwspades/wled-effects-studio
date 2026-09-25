"""The documents inside the studio (reader.py parses them): Help > User
guide, Tutorial and Node reference open here - headings, lists, tables,
code, the tutorial's pictures - with the contents down the left (the
section on screen marked), a search, links between them and a Back.
F1 over a node opens its own entry in the node reference.

Set in the interface's faces (typeface.py: Segoe UI, else Helvetica or
DejaVu Sans), which have the punctuation the guide uses; the reader's
body is the interface's, and shares its font. Also the first-run panel:
the tutorial, the guide, the examples, a device.
"""
import os

import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

from native import reader, weight

TAG = "reader_win"
WELCOME = "welcome_win"

# the reading roles: (face, size at 100%); code at the monospace's 13, which matches the body's x-height
SIZES = {"body": ("body", 16), "b": ("bold", 16), "h1": ("bold", 28), "h2": ("bold", 22), "h3": ("bold", 18),
         "mono": ("mono", 13)}
_fonts = {}


def _c():
    from native import chrome
    return chrome


def fonts():
    """{"body", "b", "h1", "h2", "h3", "mono"}: the reading faces, made once;
    a role whose file is missing is None (the default font stands in, and
    the text is kept to what it can draw)."""
    if _fonts:
        return _fonts
    # every character the file has, loaded as it is first drawn (Dear PyGui 2 has no ranges to ask
    # for): the guide's dashes, arrows and pi come with it
    for key, (face, size) in SIZES.items():
        _fonts[key] = typeface.at(face, px(size))
    return _fonts


def _bind(item, key):
    f = fonts().get(key)
    if f:
        dpg.bind_item_font(item, f)


def plain(text):
    """What the default font can draw: without a reading face, the
    guide's punctuation as ASCII (the bitmap font has only Latin-1)."""
    if fonts().get("body"):
        return text
    for a, b in (("\u203a", ">"), ("\u2014", "-"), ("\u2013", "-"), ("\u2026", "..."), ("\u2192", "->"), ("\u2190", "<-"),
                 ("\u2264", "<="), ("\u2265", ">="), ("\u2260", "!="), ("\u00d7", "x"), ("\u03c0", "pi"), ("\u2022", "-"),
                 ("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"')):
        text = text.replace(a, b)
    return text


# --- the reader --------------------------------------------------------------------------------------
class _State:
    def __init__(self):
        self.doc = None          # the file shown
        self.blocks = []
        self.items = {}          # block index -> the item to scroll to
        self.texts = {}          # block index -> its text item (where a search hit is marked)
        self.fontkey = {}        # block index -> the face its text is set in (the hit's measure)
        self.frames = {}         # block index -> the pane its text sits in, when not the page (a code block's)
        self.cells = {}          # table's block index -> its cells' text items, in reader.cells order
        self.hit = None          # the mark drawn over the found words
        self.toc = []            # [(block index, selectable)] down the left
        self.here = None         # the contents row marked: the section on screen
        self.found = None        # which of the occurrences the search last landed on
        self.needle = ""
        self.pending = None      # {"k" or "y", "tries"}: a scroll that waits for a frame to lay the items out
        self.textures = {}       # image path -> texture
        self.history = []        # [(doc, y)]: where Back goes
        self.keys = False        # the last click landed in the window: its keys are the reader's
        self.pics = {}           # picture item -> (path, caption): a click shows it at full size
        self.tick = 0


S = _State()


def build(app):
    c = _c()
    with dpg.window(tag=TAG, label="Help", no_title_bar=True, show=False, width=px(980), height=px(720), no_collapse=True,
                    on_close=lambda: setattr(S, "keys", False)):
        _c().dialog_header(TAG, "Help")                 # one window style (C8): the frames' header
        with dpg.group(horizontal=True):
            dpg.add_button(label="< Back", tag="reader_back", enabled=False, callback=lambda: back(app))
            c.tip("where you were before the last link (Alt+Left, or Backspace)")
            dpg.add_spacer(width=px(6))
            for label, f in reader.DOCS:
                dpg.add_button(label=label, tag=f"reader_doc_{f}", callback=lambda s, a, u: open_doc(app, u), user_data=f)
            dpg.add_spacer(width=px(16))
            dpg.add_input_text(tag="reader_find", hint="search this page", width=px(220), on_enter=True,
                               callback=lambda: search(app))
            dpg.add_button(label="Next", callback=lambda: search(app))
            c.tip("the next place on this page that mentions it (Enter in the box, or F3)")
            dpg.add_button(label="Previous", callback=lambda: search(app, -1))
            c.tip("the place before (Shift+F3)")
            dpg.add_text("", tag="reader_found", color=c.DIM)
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="reader_toc", width=px(240), height=-1, border=True):
                pass
            with dpg.child_window(tag="reader_body", width=-1, height=-1, border=False):
                pass
    _bind(TAG, "body")
    with dpg.theme() as th:                  # a page's own rhythm: the gaps are the page's spacers, not the theme's
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 3)
    dpg.bind_item_theme("reader_body", th)
    with dpg.item_handler_registry(tag="reader_pic_click"):
        dpg.add_item_clicked_handler(callback=lambda s, a: _pic_clicked(app, a))
    # a picture at its full size, to read what the page had to shrink
    with dpg.window(tag="reader_pic", label="Picture", no_title_bar=True, show=False, width=px(900), height=px(600), no_collapse=True):
        _c().dialog_header("reader_pic", "Picture")                 # one window style (C8): the frames' header
        with dpg.group(horizontal=True):
            dpg.add_button(label="Fit the window", callback=lambda: _pic_zoom("fit"))
            dpg.add_button(label="Full size", callback=lambda: _pic_zoom(1.0))
            dpg.add_text("", tag="reader_pic_size", color=c.DIM)
        with dpg.child_window(tag="reader_pic_body", horizontal_scrollbar=True, border=False, width=-1, height=-1):
            pass
    _bind("reader_pic", "body")
    _build_welcome(app)


def _build_welcome(app):
    c = _c()
    with dpg.window(tag=WELCOME, label="Welcome", no_title_bar=True, show=False, width=px(600), height=px(400), no_collapse=True, no_resize=True,
                    on_close=lambda: welcome_closed(app)):
        _c().dialog_header(WELCOME, "Welcome")                 # one window style (C8): the frames' header
        t = dpg.add_text("WLED Effects Studio")
        _bind(t, "h1")
        dpg.add_text("Make LED effects from nodes or from code, watch them run on any shape in 3-D, and send them "
                     "to your WLED devices. Where would you like to start?", wrap=px(560), color=c.DIM)
        dpg.add_spacer(height=px(6))
        for label, why, fn in (
                ("Start the tutorial", "a first effect from nothing, step by step", lambda: open_doc(app, "TUTORIAL.md")),
                ("Read the user guide", "every part of the studio, and every key", lambda: open_doc(app, "GUIDE.md")),
                ("Browse the examples", "every graph in the project, running", lambda: _frame(app, "library")),
                ("Find a device", "the WLED devices on the network", lambda: _frame(app, "devices"))):
            with dpg.group(horizontal=True):
                b = dpg.add_button(label=label, width=px(230), height=px(36), user_data=fn,
                                   callback=lambda s, a, u: (welcome_closed(app), u()))
                if label == "Start the tutorial":
                    weight.primary(b)
                dpg.add_text(why, color=c.DIM)
        dpg.add_spacer(height=px(8))
        dpg.add_text("Help > User guide (F1) has all of it later; F1 over a node explains that node.", color=c.DIM, wrap=px(560))
        dpg.add_spacer(height=px(4))
        with dpg.group(horizontal=True):
            dpg.add_checkbox(label="Show this when the studio starts", tag="welcome_always",
                             default_value=bool(app.prefs.get("welcome_always")))
            dpg.add_spacer(width=px(40))
            dpg.add_button(label="Close", width=px(90), callback=lambda: welcome_closed(app))
            weight.quiet(dpg.last_item())
    _bind(WELCOME, "body")


def _frame(app, which):
    from native import device_ui
    device_ui.show(app, which)


def welcome_closed(app):
    """The panel put away: not shown again unless asked for."""
    from native.project import save_prefs
    if dpg.does_item_exist(WELCOME):
        dpg.hide_item(WELCOME)
        app.prefs["welcome_always"] = bool(dpg.get_value("welcome_always"))
    app.prefs["welcome_done"] = True
    save_prefs(app.prefs)


def show_welcome(app):
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    dpg.set_item_pos(WELCOME, [max(0, (vw - px(600)) // 2), max(20, (vh - px(400)) // 3)])
    dpg.set_value("welcome_always", bool(app.prefs.get("welcome_always")))
    dpg.show_item(WELCOME)
    dpg.focus_item(WELCOME)


def maybe_welcome(app):
    """At start: the first run's panel, and every run's when asked for.
    The tests set STUDIO_NO_WELCOME."""
    if os.environ.get("STUDIO_NO_WELCOME"):
        return
    if not app.prefs.get("welcome_done") or app.prefs.get("welcome_always"):
        show_welcome(app)


def doc_path(name):
    from native import paths
    return os.path.join(paths.RES, name)


def shown():
    return dpg.does_item_exist(TAG) and dpg.is_item_shown(TAG)


def open_doc(app, name, heading=None):
    """A document in the reader, at a heading (its text or its anchor)
    when one is given. Where the reader was goes on the Back list."""
    if S.doc is not None and (S.doc != name or heading):
        _remember()                                  # Back returns here, the window closed in between or not
    fresh = S.doc != name
    if fresh:
        render(app, name)
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    if not dpg.is_item_shown(TAG):
        w, h = min(px(1180), vw - 40), min(px(840), vh - 60)
        dpg.configure_item(TAG, width=w, height=h)
        dpg.set_item_pos(TAG, [max(0, (vw - w) // 2), max(20, (vh - h) // 3)])
    dpg.show_item(TAG)
    dpg.focus_item(TAG)
    S.keys = True
    k = reader.heading_index(S.blocks, heading) if heading else None
    if k is not None:
        S.pending = {"k": k, "tries": 0}
    elif fresh:
        S.pending = {"y": 0.0, "tries": 0}
    _refresh_back()
    return k is not None or not heading


def _remember():
    y = dpg.get_y_scroll("reader_body") if dpg.does_item_exist("reader_body") else 0.0
    if S.history and S.history[-1][0] == S.doc and abs(S.history[-1][1] - y) < 4:
        return
    S.history.append((S.doc, y))
    del S.history[:-50]


def _refresh_back():
    if dpg.does_item_exist("reader_back"):
        dpg.configure_item("reader_back", enabled=bool(S.history))


def back(app):
    if not S.history:
        return False
    doc, y = S.history.pop()
    if doc != S.doc:
        render(app, doc)
    S.pending = {"y": y, "tries": 0}
    _refresh_back()
    return True


def on_theme_change(app):
    """The headings are drawn in the accent: the page again, where it was."""
    if S.doc is None or not dpg.does_item_exist("reader_body"):
        return
    y = dpg.get_y_scroll("reader_body")
    render(app, S.doc)
    S.pending = {"y": y, "tries": 0}


def render(app, name):
    """The document as items, parsed afresh (the files are small); the
    contents rebuilt; each picture loaded once."""
    c = _c()
    path = doc_path(name)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        text = f"# {name}\n\nThe file could not be read: {e}"
    S.doc, S.blocks = name, reader.parse(plain(text), os.path.dirname(path))
    S.items, S.texts, S.toc, S.here, S.found, S.pics = {}, {}, [], None, None, {}
    S.fontkey, S.frames, S.cells, S.hit = {}, {}, {}, None
    dpg.set_value("reader_found", "")
    for label, f in reader.DOCS:
        if dpg.does_item_exist(f"reader_doc_{f}"):
            dpg.configure_item(f"reader_doc_{f}", enabled=(f != name))
    title = next((lab for lab, f in reader.DOCS if f == name), name)
    _c().set_dialog_title(TAG, title)
    dpg.delete_item("reader_body", children_only=True)
    dpg.delete_item("reader_toc", children_only=True)
    accent, dim = c.ACCENT, c.DIM
    B = "reader_body"
    for k, b in enumerate(S.blocks):
        kind = b["kind"]
        col = None
        if kind == "h":
            if k:
                dpg.add_spacer(height=18 if b["level"] <= 2 else 12, parent=B)
            col = accent if b["level"] >= 2 else None
            it = dpg.add_text(b["text"], parent=B, wrap=0, color=col or (-255, 0, 0, 255))
            S.fontkey[k] = {1: "h1", 2: "h2"}.get(b["level"], "h3")
            _bind(it, S.fontkey[k])
            S.texts[k] = it
            if b["level"] <= 2:
                dpg.add_separator(parent=B)
        elif kind == "p":
            it = S.texts[k] = dpg.add_text(b["text"], parent=B, wrap=0)
            S.fontkey[k] = "b" if b.get("strong") else "body"
            if b.get("strong"):
                _bind(it, "b")
            _links(app, b, B)
        elif kind == "li":
            with dpg.group(horizontal=True, parent=B) as it:
                dpg.add_spacer(width=8 + 20 * b["depth"])
                dpg.add_text(f"{b['number']}." if b["number"] is not None else plain("\u2022"), color=dim)
                S.texts[k] = dpg.add_text(b["text"], wrap=0)
            _links(app, b, B)
        elif kind == "quote":
            col = dim
            with dpg.group(horizontal=True, parent=B) as it:
                dpg.add_spacer(width=px(6))
                dpg.add_text("|", color=accent)
                S.texts[k] = dpg.add_text(b["text"], wrap=0, color=dim)
            _links(app, b, B)
        elif kind == "code":
            # set in the mono face, scrolled sideways rather than wrapped; a copy button for the lot
            n = b["text"].count("\n") + 1
            with dpg.group(parent=B) as it:
                with dpg.group(horizontal=True):
                    dpg.add_button(label="copy", small=True, user_data=b["text"],
                                   callback=lambda s, a, u: (dpg.set_clipboard_text(u), _say("copied to the clipboard")))
                    if b.get("lang"):
                        dpg.add_text(b["lang"], color=dim)
                with dpg.child_window(width=-1, height=min(440, 20 + 17 * n + 16), horizontal_scrollbar=True,
                                      border=True) as S.frames[k]:
                    S.texts[k] = dpg.add_text(b["text"])
                    S.fontkey[k] = "mono"
                    _bind(S.texts[k], "mono")
        elif kind == "table":
            with dpg.table(parent=B, header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True,
                           borders_outerV=True, row_background=True, resizable=True,
                           policy=dpg.mvTable_SizingStretchProp) as it:
                for h in b["head"]:
                    dpg.add_table_column(label=h)
                S.cells[k] = [None] * len(b["head"])                 # the head's labels: no item of their own
                for row in b["rows"]:
                    with dpg.table_row():
                        for cell in (row + [""] * len(b["head"]))[:len(b["head"])]:
                            S.cells[k].append(dpg.add_text(cell, wrap=0))
        elif kind == "img":
            it = _image(b, B)
        elif kind == "hr":
            it = dpg.add_separator(parent=B)
        else:
            continue
        S.items[k] = it
        S.fontkey.setdefault(k, "body")
        nxt = S.blocks[k + 1]["kind"] if k + 1 < len(S.blocks) else None
        if kind == "li" and nxt == "li":
            dpg.add_spacer(height=px(1), parent=B)                   # a list holds together
        elif kind in ("p", "li", "quote", "code", "table", "img"):
            dpg.add_spacer(height=6 if kind in ("p", "li", "quote") else 10, parent=B)
    dpg.add_spacer(height=px(200), parent=B)                     # the last heading can come to the top too
    # the contents: every heading down to the third level
    for k, level, text in reader.headings(S.blocks):
        sel = dpg.add_selectable(label=("   " * max(0, level - 1)) + text, parent="reader_toc", width=px(220), user_data=k,
                                 callback=lambda s, a, u: (_remember(), _refresh_back(), scroll_to(u)))
        S.toc.append((k, sel))


def _links(app, b, parent):
    """A block's links as buttons under it: another document opens here,
    a heading scrolls to it, a web address opens the browser."""
    if not b.get("links"):
        return
    with dpg.group(horizontal=True, parent=parent):
        dpg.add_spacer(width=px(18))
        for label, target in b["links"][:6]:
            dpg.add_button(label=f"{label} \u203a" if fonts().get("body") else f"{label} >", small=True,
                           user_data=target, callback=lambda s, a, u: follow(app, u))
            _c().tip(target)


def follow(app, target):
    """A link: web addresses to the browser, the documents here."""
    t = (target or "").strip()
    if t.startswith(("http://", "https://", "mailto:")):
        app.open_url(t)
        return "web"
    if t.startswith("#"):
        k = reader.heading_index(S.blocks, t[1:])
        if k is None:
            return None
        _remember(); _refresh_back()
        scroll_to(k)
        return "here"
    name, _, frag = t.partition("#")
    base = os.path.basename(name)
    if base.lower().endswith(".md") and os.path.exists(doc_path(base)):
        open_doc(app, base, frag or None)
        return "doc"
    if os.path.exists(os.path.join(os.path.dirname(doc_path("GUIDE.md")), name)):
        app.reveal(os.path.join(os.path.dirname(doc_path("GUIDE.md")), name))
        return "file"
    return None


def _image(b, parent):
    """A picture, scaled down to the page (at most 760 px across), loaded once."""
    c = _c()
    if not b["exists"]:
        return dpg.add_text(f"[picture missing: {os.path.basename(b['path'])}]", parent=parent, color=c.DIM)
    got = S.textures.get(b["path"])
    if got is None or not dpg.does_item_exist(got[0]):
        try:
            w, h, ch, data = dpg.load_image(b["path"])
            from native.textures import registry
            got = S.textures[b["path"]] = (dpg.add_static_texture(w, h, data, parent=registry()), w, h)
        except Exception as e:
            return dpg.add_text(f"[picture unreadable: {e}]", parent=parent, color=c.DIM)
    tex, w, h = got
    s = min(1.0, px(880) / max(1, w))
    with dpg.group(parent=parent) as g:
        img = dpg.add_image(tex, width=int(w * s), height=int(h * s))
        dpg.bind_item_handler_registry(img, "reader_pic_click")
        S.pics[img] = (b["path"], b["alt"])
        c.tip("click: the picture at full size" if s < 1.0 else "click: the picture in a window of its own", item=img)
        cap = (b["alt"] + "  -  " if b["alt"] else "") + ("click for full size" if s < 1.0 else "")
        if cap:
            dpg.add_text(cap.strip(" -"), color=c.DIM, wrap=int(w * s))
    return g


def _pic_clicked(app, a):
    """A picture on the page, clicked: in the viewer at its full size."""
    item = a[1] if isinstance(a, (list, tuple)) and len(a) > 1 else a
    if item not in S.pics:
        return
    show_picture(*S.pics[item])


_pic = {"tex": None, "w": 0, "h": 0}


def show_picture(path, caption=""):
    got = S.textures.get(path)
    if got is None:
        return False
    tex, w, h = got
    _pic.update(tex=tex, w=w, h=h)
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    ww, wh = min(w + 40, vw - 60), min(h + 110, vh - 60)
    _c().set_dialog_title("reader_pic", caption or os.path.basename(path))
    dpg.configure_item("reader_pic", width=ww, height=wh)
    dpg.set_item_pos("reader_pic", [max(0, (vw - ww) // 2), max(20, (vh - wh) // 2)])
    _pic_zoom(1.0)
    dpg.show_item("reader_pic")
    dpg.focus_item("reader_pic")
    return True


def _pic_zoom(z):
    if _pic["tex"] is None:
        return
    w, h = _pic["w"], _pic["h"]
    if z == "fit":
        aw, ah = dpg.get_item_rect_size("reader_pic") or [w, h]
        z = max(0.1, min(1.0, (aw - 30) / max(1, w), (ah - 90) / max(1, h)))
    dpg.delete_item("reader_pic_body", children_only=True)
    dpg.add_image(_pic["tex"], width=int(w * z), height=int(h * z), parent="reader_pic_body")
    dpg.set_value("reader_pic_size", f"{w} x {h} px, at {z * 100:.0f}%")


def _say(text):
    dpg.set_value("reader_found", text)


def scroll_to(k):
    S.pending = {"k": k, "tries": 0}


def _y(it):
    """Where an item sits down its pane's content (its "pos": the scroll
    does not move it), or None before it has been laid out once. A child
    window has no rect of its own to measure against - this needs none."""
    if it is None or not dpg.does_item_exist(it):
        return None
    pos = dpg.get_item_state(it).get("pos")
    return None if not pos else pos[1]


def _top_block():
    """The first block whose top is on screen, for a search to start at."""
    top = dpg.get_y_scroll("reader_body")
    for k in sorted(S.items):
        y = _y(S.items[k])
        if y is not None and y >= top:
            return k
    return 0


def search(app, step=1, needle=None):
    """The next (or, step -1, the previous) place the text appears - each
    mention, not each paragraph; a new text starts from what is on screen.
    The words are marked where they are drawn, the page scrolled so their
    line sits a third of the way down. Returns the block."""
    needle = dpg.get_value("reader_find") if needle is None else needle
    needle = (needle or "").strip()
    if not needle:
        return None
    occ = reader.occurrences(S.blocks, needle)
    _unmark()
    if not occ:
        S.found = None
        dpg.set_value("reader_found", "not on this page")
        return None
    if needle != S.needle or S.found is None or S.found >= len(occ):
        S.needle = needle
        top = _top_block()
        after = [i for i, o in enumerate(occ) if o[0] >= top]
        if step > 0:
            i = after[0] if after else 0
        else:
            i = (after[0] - 1) % len(occ) if after else len(occ) - 1
    else:
        i = (S.found + step) % len(occ)
    S.found = i
    k, cell, start = occ[i]
    dpg.set_value("reader_found", f"{i + 1} of {len(occ)}")
    if not _show_hit(k, cell, start, len(needle)):
        scroll_to(k)
    return k


_adv = {}


def _advance(fkey):
    """A face's advance for a character, as Dear ImGui lays it out: 64 of
    them measured at once (a width comes back rounded up), kept."""
    f = fonts().get(fkey) or fonts().get("body")

    def adv(ch):
        a = _adv.get((fkey, ch))
        if a is None:
            w = (dpg.get_text_size(ch * 64, font=f) if f else dpg.get_text_size(ch * 64)) or [0.0, 0.0]
            a = _adv[(fkey, ch)] = float(w[0]) / 64.0
        return a
    return adv


def _pos(it):
    if it is None or not dpg.does_item_exist(it):
        return None
    st = dpg.get_item_state(it)
    return st.get("pos"), st.get("rect_size")


def _show_hit(k, cell, start, length):
    """The found words marked where they are drawn: a tinted box over
    them (a table's whole cell), and the page scrolled to their line."""
    frame = S.frames.get(k, "reader_body")
    if cell is not None:
        cl = S.cells.get(k) or []
        it = cl[cell] if cell < len(cl) else None
        got = _pos(it)
        if not got or not got[0]:
            return False
        (x, y), (w, h) = got
        box = (x - 3, y - 1, w + 6, h + 2)
    else:
        it = S.texts.get(k)
        got = _pos(it)
        if not got or not got[0]:
            return False
        (x, y), _ = got
        text = dpg.get_value(it) or ""
        fkey = S.fontkey.get(k, "body")
        adv = _advance(fkey)
        f = fonts().get(fkey)
        lh = float((dpg.get_text_size("Ag", font=f) if f else dpg.get_text_size("Ag"))[1])
        if frame == "reader_body":
            body = dpg.get_item_state("reader_body")
            pad = _y_first_x()
            width = pad + (body.get("content_region_avail") or [700, 0])[0] - x
        else:
            width = None                                  # code: not wrapped, scrolled sideways
        line, x0, x1 = reader.locate(text, start, length, width, adv)
        box = (x + x0 - 2, y + line * lh, max(4.0, x1 - x0) + 4, lh)
    # a group carries the position (Dear PyGui puts a drawlist given one in the flow, at the page's end)
    S.hit = dpg.add_group(parent=frame, pos=[int(box[0]), int(box[1])])
    dl = dpg.add_drawlist(width=int(box[2]) + 1, height=int(box[3]) + 1, parent=S.hit)
    light = _c().TEXT[0] < 128
    dpg.draw_rectangle([0, 0], [box[2], box[3]], parent=dl, rounding=3,
                       fill=(255, 170, 0, 90) if light else (255, 200, 60, 80),
                       color=(230, 140, 0, 220) if light else (255, 205, 80, 200))
    # the line a third of the way down the page
    top = box[1] if frame == "reader_body" else (_y(frame) or 0) + box[1]
    view = (dpg.get_item_state("reader_body").get("rect_size") or [0, 600])[1]
    S.pending = {"y": max(0.0, top - view / 3.0), "tries": 1}
    return True


def _y_first_x():
    """The page's left edge in its own coordinates: the x of its first item."""
    kids = dpg.get_item_children("reader_body", 1) or []
    for kid in kids:
        pos = dpg.get_item_state(kid).get("pos")
        if pos:
            return pos[0]
    return 8


def _unmark():
    if S.hit is not None and dpg.does_item_exist(S.hit):
        dpg.delete_item(S.hit)
    S.hit = None


def clicked(app):
    """Every left click: whether it landed in the reader or its picture
    (their keys then)."""
    if not shown():
        S.keys = False
        return
    x, y = dpg.get_mouse_pos(local=False)
    S.keys = False
    for tag in (TAG, "reader_pic"):
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
            px, py = dpg.get_item_pos(tag)
            w, h = dpg.get_item_rect_size(tag)
            S.keys = S.keys or (px <= x <= px + w and py <= y <= py + h)


def key(app, code, binding):
    """The reader's keys while it has them: Esc closes it, the find keys
    search it, Alt+Left or Backspace goes back, Page Up/Down, Home and End
    scroll it. True when the key was the reader's."""
    if not shown() or not S.keys:
        return False
    if code == dpg.mvKey_Escape:
        if dpg.is_item_shown("reader_pic"):
            dpg.hide_item("reader_pic")              # the picture first, then the reader
            return True
        dpg.hide_item(TAG); S.keys = False
        return True
    b = app.keys.label
    if binding and binding == b("find"):
        dpg.focus_item("reader_find"); return True
    if binding and binding == b("find_next"):
        search(app); return True
    if binding and binding == b("find_prev"):
        search(app, -1); return True
    if binding in ("Alt+Left", "Backspace"):
        back(app); return True
    body_h = (dpg.get_item_rect_size("reader_body") or [0, 400])[1]
    y, most = dpg.get_y_scroll("reader_body"), dpg.get_y_scroll_max("reader_body")
    to = {"PageDown": y + body_h - 40, "PageUp": y - body_h + 40, "Space": y + body_h - 40, "Home": 0.0, "End": most,
          "Down": y + 48, "Up": y - 48}.get(binding)
    if to is not None:
        dpg.set_y_scroll("reader_body", max(0.0, min(most, to)))
        return True
    return False


def _mark_here():
    """The contents row of the section on screen, marked (and scrolled
    into view down the left)."""
    if not S.toc:
        return
    top = dpg.get_y_scroll("reader_body") + 60
    here = S.toc[0][0]
    for k, _ in S.toc:
        y = _y(S.items.get(k))
        if y is None:
            continue
        if y <= top:
            here = k
        else:
            break
    if here == S.here:
        return
    S.here = here
    for k, sel in S.toc:
        if not dpg.does_item_exist(sel):
            continue
        dpg.set_value(sel, k == here)
        y = _y(sel)
        if k == here and y is not None:
            t = dpg.get_y_scroll("reader_toc")
            h = (dpg.get_item_state("reader_toc").get("rect_size") or [0, 400])[1]
            if y < t + 4 or y > t + h - 28:
                dpg.set_y_scroll("reader_toc", max(0.0, y - 60))


def poll(app):
    """A scroll asked for before the items were laid out, done once they
    are; the contents' mark kept on the section on screen."""
    if not shown():
        return
    S.tick += 1
    p = S.pending
    if p is not None:
        p["tries"] += 1
        if p["tries"] < 2:
            return                                           # a frame for the new items to be laid out
        y = p["y"] if "y" in p else _y(S.items.get(p["k"]))
        if y is not None and "k" in p:
            y = y - 8 + p.get("off", 0.0)
        # A page's height (so how far it scrolls) is known a frame after its
        # items are: a new page's target past the old page's end waits for it,
        # or it would stop where the last page ended (F1 on Noise stopped at
        # Loudest bin, the tutorial's length down the reference).
        most = dpg.get_y_scroll_max("reader_body")
        if y is None or (y > most + 1 and p["tries"] < 30):
            if p["tries"] >= 30:
                S.pending = None
            return
        dpg.set_y_scroll("reader_body", max(0.0, min(y, most)))
        S.pending = None
        S.here = None
        return
    if S.tick % 6 == 0:
        _mark_here()
