"""Messages that stay (the critique's C10).

Build results, errors, modulation, MIDI learn, expression errors and hints
all went to one line beside the graph's file name - whole sentences the
pane cut off, replaced by the next, with no history; and in the other
layouts nothing showed them at all. Now:

- every message is logged, the last fifty (Help > Message log, or the
  footer's log button, opens the log; it goes into a problem report too);
- the footer's line, in every layout, shows the latest one short - its
  first part, cut at a word - and the whole of it on hover, coloured by
  kind: a problem red, a warning amber. A note leaves the line after a
  while, a warning later; an error stays until the next message;
- a problem with a key stays until it is fixed: a node the graph cannot
  use (hold() keeps a graph's set as it is judged again), the graph that
  does not compile, a build that failed. The footer counts them, and a
  click opens the log at them;
- a message that is about a place says where: a node (its graph, its id,
  whether a sub-graph), or a line of code - the log's "go to" opens it
  there;
- a readout that moves (a value dragged on a running effect) is one line
  that changes, not fifty (merge).

    messages.post(app, "box_fire.json: a loop without a Delay", "error", key="graph:box_fire.json")
    messages.clear(app, "graph:box_fire.json")
"""
import re
import time
from collections import deque

import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface

KEEP = 50
LOG = deque(maxlen=KEEP)
HELD = {}                 # key -> entry: problems that stay until fixed
SHORT = 96                # the footer line's length, in characters
LINGER = {"info": 12.0, "warn": 30.0}      # seconds on the footer's line; an error stays until the next message
MERGE_S = 2.0             # a readout this soon after its last one replaces it in place
REFILL_S = 0.25           # the open log is filled again at most this often (a drag posts every frame)
# a message that says something went wrong, when its caller did not say so: amber in the line and the log
_WARNY = re.compile(r"^(error|failed|could not|cannot|can't|no such|not found)\b"
                    r"|\b(failed|error|refused|timed out|could not|cannot|did not|dropped"
                    r"|not (read|restored|written|sent|saved|found|scriptable))\b", re.I)
_seq = 0                  # every post counts: a test reads what came since a mark
_st = {"shown": None, "dirty": False, "filled": 0.0}
_line_themes = {}         # (kind, colours) -> the footer line's theme


def _chrome():
    from native import chrome
    return chrome


def _project(app):
    p = getattr(app, "project", None)
    return getattr(p, "path", None)


def seq():
    return _seq


def short(text, n=SHORT):
    """What a line has room for: the message's first part - up to its
    first "; " or ". " past a few words - cut at a word with "..."."""
    from native.nodeface import fit_words
    t = " ".join(str(text).split())
    for sep in ("; ", ". "):
        k = t.find(sep)
        if 24 <= k < n:
            t = t[:k]
            break
    return fit_words(t, n)


def post(app, text, kind="info", node=None, key=None, code=None, merge=None):
    """A message: logged (the last fifty), shown in the footer's line -
    short, the whole on hover. `kind` is "info", "warn" or "error" (an info
    that reads like a failure is shown as a warning). With `key` it is a
    problem, held until clear(key): posted again unchanged, it is counted,
    not logged twice. `node` (graph file, node id, in a sub-graph) or
    `code` (file, line) is where it is about. `merge` names a readout: the
    next one of that name within two seconds replaces it in place."""
    global _seq
    text = str(text or "").strip()
    if not text:
        return
    if key and kind == "info":
        kind = "error"                                              # a problem held until fixed is one
    elif kind == "info" and _WARNY.search(text):
        kind = "warn"
    now = time.time()
    _seq += 1
    last = LOG[-1] if LOG else None
    held = HELD.get(key) if key else None
    if held is not None and held["text"] == text:
        e = held                                                    # the same problem again (a compile tried again)
        e["n"] += 1; e["t"] = now
        _to_end(e)
    elif last is not None and merge and last.get("merge") == merge and now - last["t"] < MERGE_S:
        e = last                                                    # a readout that moves: one line that changes
        e.update(t=now, text=text, kind=kind, node=node or e.get("node"), code=code or e.get("code"))
    elif last is not None and not key and not last.get("key") and last["text"] == text and last["kind"] == kind:
        e = last                                                    # the same again: counted, not repeated
        e["n"] += 1; e["t"] = now
    else:
        e = {"t": now, "text": text, "kind": kind, "node": node, "key": key, "code": code, "n": 1,
             "merge": merge, "project": _project(app)}
        LOG.append(e)
    e["seq"] = _seq
    if key:
        HELD[key] = e
    _show(app, e)


def _to_end(e):
    """A held problem posted again is the newest: to the end of the log
    (back in it, when fifty newer ones had pushed it out)."""
    for k, x in enumerate(LOG):
        if x is e:
            del LOG[k]
            break
    LOG.append(e)


def clear(app, prefix):
    """Problems fixed: every one held under a key that starts with `prefix` goes."""
    gone = [k for k in HELD if k.startswith(prefix)]
    for k in gone:
        del HELD[k]
    if gone:
        _show(app, None)
    return len(gone)


def hold(app, prefix, items):
    """The problems under `prefix` as they are judged now - {key: (text,
    node)}: one no longer there goes, a new one (or one that reads
    differently now) is logged and held, one still there is left as it
    was - judged again on every change, it is not logged again."""
    gone = [k for k in HELD if k.startswith(prefix) and k not in items]
    for k in gone:
        del HELD[k]
    for k, (text, node) in items.items():
        e = HELD.get(k)
        if e is None or e["text"] != text:
            post(app, text, "error", node=node, key=k)
    if gone:
        _show(app, None)


def held(prefix=""):
    return [e for k, e in HELD.items() if k.startswith(prefix)]


def _colour(kind):
    """A kind's colour, readable on the theme in force: a problem red, a warning amber, a note dim."""
    c = _chrome()
    light = c.TEXT[0] < 128
    if kind == "error":
        return (176, 38, 30, 255) if light else (235, 110, 100, 255)
    if kind == "warn":
        return (146, 96, 8, 255) if light else (225, 180, 90, 255)
    return tuple(c.DIM[:3]) + (255,)


def _line_theme(kind):
    """The footer line: a button with no slab (a click opens the log), its
    words in the kind's colour. A button, not a text: a text after a small
    button sits its frame padding lower than the button's words."""
    c = _chrome()
    key = (kind, tuple(c.TEXT), tuple(c.DIM))
    t = _line_themes.get(key)
    if t is not None and dpg.does_item_exist(t):
        return t
    tx = tuple(c.TEXT[:3])
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, tx + (22,), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, tx + (40,), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Text, _colour(kind), category=dpg.mvThemeCat_Core)
    _line_themes[key] = t
    return t


def rebind(app):
    """After a theme change: the line in the new colours."""
    if dpg.does_item_exist("msg_line"):
        e = _st["shown"]
        dpg.bind_item_theme("msg_line", _line_theme(e["kind"] if e else "info"))


# --- the footer's line ---------------------------------------------------------------------------
def build(app, parent):
    """The footer's row: the problems held (a click opens the log at them),
    the log, the latest message, short (the whole on hover)."""
    from native import weight
    c = _chrome()
    with dpg.group(horizontal=True, parent=parent, tag="msg_row"):
        # Hidden while there are none - and its tooltip with it: Dear PyGui
        # keeps a tooltip as the next item in the row, and a row whose first
        # item drawn is a tooltip is put on the line above (the log button
        # sat at the end of the stats line, and the footer measured a row
        # short, so the panes above hid the row).
        b = dpg.add_button(label="", tag="msg_problems", small=True, show=False, callback=lambda: show_log(app))
        weight.danger(b)
        with dpg.tooltip(b, tag="msg_problems_tip", show=False):
            dpg.add_text("the problems that stay until they are fixed - a click opens the log at them", wrap=px(360))
        dpg.add_button(label="log", tag="msg_log_btn", small=True, callback=lambda: show_log(app))
        c.tip("the last fifty messages, the problems first; each that is about a node or a line goes to it")
        dpg.add_button(label="", tag="msg_line", small=True, show=False, callback=lambda: show_log(app))
        dpg.bind_item_theme("msg_line", _line_theme("info"))
        with dpg.tooltip("msg_line"):
            dpg.add_text("", tag="msg_line_tip", wrap=px(520))


def _show(app, e):
    if not dpg.does_item_exist("msg_line"):
        return
    n = sum(1 for x in HELD.values() if x["kind"] == "error")
    dpg.configure_item("msg_problems", show=n > 0, label=f"{n} problem{'s' if n != 1 else ''}" if n else "problems")
    dpg.configure_item("msg_problems_tip", show=n > 0)
    if e is not None:
        _st["shown"] = e
        # "##" would end a Dear PyGui label (the rest is its id): a C++ token paste in a build error
        dpg.configure_item("msg_line", label=(short(e["text"]) + _times(e)).replace("##", "# #"), show=True)
        dpg.bind_item_theme("msg_line", _line_theme(e["kind"]))
        dpg.set_value("msg_line_tip", e["text"] + "\n\n(a click opens the log)")
    _st["dirty"] = True


def _blank():
    """The line empty: nothing to hover or click."""
    _st["shown"] = None
    if dpg.does_item_exist("msg_line"):
        dpg.configure_item("msg_line", label="", show=False)
        dpg.set_value("msg_line_tip", "")


def poll(app):
    """Each frame: a note or a warning that has had its time leaves the
    footer's line (the log keeps it); the open log follows what came."""
    e = _st["shown"]
    if e is not None and e["kind"] in LINGER and time.time() - e["t"] > LINGER[e["kind"]]:
        _blank()
    if _st["dirty"] and time.time() - _st["filled"] >= REFILL_S:
        _st["dirty"] = False
        if dpg.does_item_exist("log_win") and dpg.is_item_shown("log_win"):
            fill_log(app)


# --- the log --------------------------------------------------------------------------------------
def build_log(app):
    """The log's window (made with the dialogs, not inside the footer)."""
    c = _chrome()
    with dpg.window(tag="log_win", label="Message log", show=False, no_title_bar=True, width=px(640), height=px(480),
                    no_collapse=True):
        c.dialog_header("log_win", "Message log")
        dpg.add_text("The last fifty, newest first. The problems at the top stay until they are fixed; "
                     "go to opens the node or the line one is about.", color=c.DIM, wrap=px(600))
        with dpg.group(horizontal=True):
            dpg.add_button(label="copy all", tag="log_copy", callback=lambda: copy_all(app))
            c.tip("the log as text, to paste into an issue or a note")
            dpg.add_button(label="clear", tag="log_clear", callback=lambda: clear_recent(app))
            c.tip("empties the recent messages; the problems stay until they are fixed")
        with dpg.child_window(tag="log_rows", height=-1, border=True):
            pass


def show_log(app):
    fill_log(app)
    _chrome()._centre("log_win", 640, 480)
    dpg.show_item("log_win")
    dpg.focus_item("log_win")


def _when(e):
    return time.strftime("%H:%M:%S", time.localtime(e["t"]))


def _times(e):
    return f"  (x{e['n']})" if e.get("n", 1) > 1 else ""


def fill_log(app):
    """The problems held, then the messages newest first: when, what, and a
    go to for one about a node or a line."""
    c = _chrome()
    _st["filled"] = time.time()
    if not dpg.does_item_exist("log_rows"):
        return
    dpg.delete_item("log_rows", children_only=True)

    def row(e):
        with dpg.group(horizontal=True, parent="log_rows"):
            typeface.mono(dpg.add_text(_when(e), color=c.DIM))
            if e.get("node") or e.get("code"):
                dpg.add_button(label="go to", small=True, user_data=e, callback=lambda s, a, u: goto(app, u))
                where = e.get("node") or e.get("code")
                c.tip(f"{where[0]}, node #{where[1]}" if e.get("node") else f"{where[0]}, line {where[1]}")
            dpg.add_text(e["text"] + _times(e), color=_colour(e["kind"]) if e["kind"] != "info" else c.TEXT,
                         wrap=px(500))

    problems = [e for e in HELD.values() if e["kind"] == "error"]
    if problems:
        typeface.label(dpg.add_text("PROBLEMS", parent="log_rows", color=_colour("error")))
        for e in problems:
            row(e)
        dpg.add_separator(parent="log_rows")
    typeface.label(dpg.add_text("RECENT", parent="log_rows", color=c.ACCENT))
    if not LOG:
        dpg.add_text("nothing yet", parent="log_rows", color=c.DIM)
    for e in reversed(LOG):
        row(e)


def dump():
    """The log as text: the problems, then every message oldest first."""
    out = []
    problems = [e for e in HELD.values() if e["kind"] == "error"]
    if problems:
        out.append("problems:")
        out += [f"  {_when(e)}  {e['text']}{_times(e)}" for e in problems]
        out.append("messages:")
    out += [f"{_when(e)}  {e['kind']:<5}  {e['text']}{_times(e)}" for e in LOG]
    return "\n".join(out)


def copy_all(app):
    dpg.set_clipboard_text(dump())
    post(app, f"the log copied: {len(LOG)} message{'s' if len(LOG) != 1 else ''}")


def clear_recent(app):
    """The recent messages gone; the problems stay, held until fixed."""
    keep = [e for e in LOG if e.get("key") and e.get("key") in HELD and HELD[e["key"]] is e]
    LOG.clear()
    LOG.extend(keep)
    _blank()
    fill_log(app)


def goto(app, e):
    """To the place a message is about: its node in its graph, framed and
    selected - or its line in the code pane. One from another project says so."""
    if e.get("project") and e["project"] != _project(app):
        post(app, "that message is about another project"); return
    if e.get("node"):
        f, nid, *sub = e["node"]
        app.gp.goto_node(f, nid, bool(sub and sub[0]))
    elif e.get("code"):
        f, line = e["code"]
        app.goto_code(f, line)
