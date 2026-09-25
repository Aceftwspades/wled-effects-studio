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


def test_guide_has_the_reference_section():
    g = _guide()
    assert "## reference: every menu, key and button" in g and "<!-- uiref end -->" in g, "run python tests/make_uiref.py"


def test_every_menu_item_is_in_the_guide():
    guide = _guide()
    labels = []
    for f in ("chrome.py", "app.py", "graph_ui.py"):
        s = _source(f)
        labels += re.findall(r'add_menu_item\(label="([^"]+)"', s) + re.findall(r'_mi\(app, "([^"]+)"', s)
    missing = sorted({l for l in labels if len(l) >= 3 and not _has(guide, l)})
    assert not missing, "menu items the guide does not name (run tests/make_uiref.py): " + ", ".join(missing)


def test_every_key_action_is_in_the_guide():
    from native.keys import ACTIONS
    guide = _guide()
    missing = [label for _, label, _, _ in ACTIONS if not _has(guide, label)]
    assert not missing, "actions the guide does not name (run tests/make_uiref.py): " + ", ".join(missing)


def test_every_frame_button_is_in_the_guide():
    guide = _guide()
    missing = []
    for f in sorted(os.listdir(os.path.join(ROOT, "native"))):
        if f.endswith("_ui.py") or f in ("chrome.py", "app.py", "messages.py", "view3d.py", "shape_view.py"):
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
