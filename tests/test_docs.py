"""The guide names what the app has: every menu item, every key action
and every frame button (bar the generic ones) appears in GUIDE.md - its
reference section is written from the running app by
tests/make_uiref.py, so this fails when something was added and the
section not remade. Run with  python tests/test_docs.py  (or pytest).
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

GENERIC = {"OK", "Cancel", "Close", "Save", "Add", "Delete", "Remove", "Read", "Stop", "Start", "Clear", "Copy", "Undo",
           "Not now", "up", "down", "x", "+", "-", ":::", "all", "none", "use", "remove", "restore", "make", "copy", "auto",
           "find", "redo", "undo", "100%", "no\\npreview", "press a key...", "< back", "paste here", "+ stop", "+ point"}


def _guide():
    return io.open(os.path.join(ROOT, "GUIDE.md"), encoding="utf-8").read().lower()


def _has(guide, label):
    return label.lower().strip().rstrip(".…") in guide


def _source(name):
    return io.open(os.path.join(ROOT, "native", name), encoding="utf-8").read()


def _graph_and_show():
    """The mixins app.py's App and graph_ui.py's GraphPanel are made of (app_*.py, graph_*.py) with graph_ui.py, and the
    modules split from sequence_ui.py (seq_*.py)."""
    return sorted(f for f in os.listdir(os.path.join(ROOT, "native")) if f.endswith(".py") and f.startswith(("app_", "graph_", "seq_")))


def test_guide_has_the_reference_section():
    g = _guide()
    assert "## reference: every menu, key and button" in g and "<!-- uiref end -->" in g, "run python tests/make_uiref.py"


def test_every_menu_item_is_in_the_guide():
    guide = _guide()
    labels = []
    for f in ["chrome.py", "app.py"] + _graph_and_show():                 # graph_ui and its mixins, the show's modules
        s = _source(f)
        labels += re.findall(r'add_menu_item\(label="([^"]+)"', s) + re.findall(r'_mi\(app, "([^"]+)"', s)
    missing = sorted({l for l in labels if len(l) >= 3 and not _has(guide, l)})
    assert not missing, "menu items the guide does not name (run tests/make_uiref.py): " + ", ".join(missing)


def test_every_key_action_is_in_the_guide():
    from native.keys import ACTIONS
    guide = _guide()
    missing = [label for _, label, _, _ in ACTIONS if not _has(guide, label)]
    assert not missing, "actions the guide does not name (run tests/make_uiref.py): " + ", ".join(missing)


def test_every_button_in_the_guide_has_a_tooltip():
    """The guide's button list is written from the running app (tests/make_uiref.py): a button there with no words
    after it has no tooltip. 141 of 398 had none; a new one must have one, or be named in walk.UIREF_NO_TIP."""
    import re
    from native import walk
    text = open(os.path.join(ROOT, "GUIDE.md"), encoding="utf-8").read()
    sec = text[text.index("### Buttons"):text.index(walk.UIREF_END)]
    ok = walk.UIREF_NO_TIP
    bare = []
    for line in sec.splitlines():
        m = re.match(r"\*\*(.+?)\*\*: (.*)", line)
        if not m:
            continue
        for item in re.split(r"; (?=`)", m.group(2)):
            mm = re.match(r"`([^`]*)`( — )?", item)
            if mm and not mm.group(2):
                lbl = mm.group(1)
                if lbl in ok or any(k.endswith("*") and lbl.startswith(k[:-1]) for k in ok):
                    continue
                bare.append(f"{m.group(1)}: {lbl}")
    assert not bare, f"{len(bare)} button(s) with no tooltip (add one, or name it in walk.UIREF_NO_TIP): " + "; ".join(bare)


def test_every_frame_button_is_in_the_guide():
    guide = _guide()
    missing = []
    for f in sorted(os.listdir(os.path.join(ROOT, "native"))):
        if f.endswith("_ui.py") or f in _graph_and_show() or f in ("chrome.py", "app.py", "messages.py", "view3d.py", "shape_view.py"):
            for b in re.findall(r'add_button\(label="([^"]+)"', _source(f)):
                if len(b) >= 4 and b not in GENERIC and not _has(guide, b.replace("\\n", " ")):
                    missing.append(f"{f}: {b}")
    assert not missing, "buttons the guide does not name (run tests/make_uiref.py): " + ", ".join(missing)


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                failed += 1; print("FAIL", name, str(e)[:1500])
    sys.exit(1 if failed else 0)
