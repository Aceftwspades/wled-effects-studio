"""The node tutorials (native/tutorials.py, docs/nodes): every lesson sound -
its node there, its graph compiling, its changes naming real pins, its words
covering every input and setting - with its picture made and not dark,
NODES.md carrying it, and its links the reader can follow. Which nodes have
no tutorial yet is reported; once every node has one, ALL_REQUIRED makes a
missing one a failure. Run with  python tests/test_tutorials.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import tutorials, nodedocs, reader          # noqa: E402
from native.nodedefs import library                     # noqa: E402

ALL_REQUIRED = False         # True once every node has its tutorial: then a node without one fails


def test_every_lesson_is_sound():
    lib = library()
    lessons = tutorials.all_lessons()
    assert len(lessons) >= 5
    bad = [p for les in lessons.values() for p in tutorials.problems(les, lib)]
    assert not bad, "\n".join(bad)
    for node in lessons:
        assert os.path.basename(tutorials.path(node)) == tutorials.ident(node) + ".json"


def test_every_lesson_has_its_picture():
    from PIL import Image, ImageSequence
    for node in tutorials.all_lessons():
        p = tutorials.picture(node)
        assert os.path.exists(p), f"{node}: no picture - python tests/make_tutorials.py {node}"
        with Image.open(p) as im:
            frames = [f.convert("RGB") for f in ImageSequence.Iterator(im)]
        assert len(frames) >= 2, node
        assert max(max(c[1] for c in f.getextrema()) for f in frames) > 60, f"{node}: the picture is dark"


def test_nodes_md_carries_the_tutorials():
    text = open(os.path.join(ROOT, "NODES.md"), encoding="utf-8").read()
    assert text == nodedocs.markdown(), "NODES.md is stale - python tests/make_tutorials.py (or native/nodedocs.py)"
    blocks = reader.parse(text, ROOT)
    for node, les in tutorials.all_lessons().items():
        k = reader.heading_index(blocks, node)
        assert k is not None, node
        end = next((i for i in range(k + 1, len(blocks)) if blocks[i]["kind"] == "h"), len(blocks))
        sec = blocks[k:end]
        assert any(b["kind"] == "img" and b["exists"] for b in sec), f"{node}: no picture in its entry"
        links = [t for b in sec for _, t in b.get("links", [])]
        assert f"studio:try/{node}" in links, f"{node}: no Try it"
        for i in range(1, len(les["try"]) + 1):
            assert f"studio:try/{node}/{i}" in links, f"{node}: try {i} has no link"


def test_the_links_name_lessons():
    """Every studio: link in NODES.md names a node with a lesson and a change it has."""
    text = open(os.path.join(ROOT, "NODES.md"), encoding="utf-8").read()
    lessons = tutorials.all_lessons()
    for node, k in re.findall(r"\(studio:try/([^)/]+)(?:/(\d+))?\)", text):
        assert node in lessons, node
        if k:
            assert 1 <= int(k) <= len(lessons[node]["try"]), (node, k)


def test_which_nodes_have_none():
    lib = library()
    missing = sorted(n for n in lib if tutorials.load(n) is None)
    print(f"     {len(lib) - len(missing)} of {len(lib)} nodes have a tutorial")
    if ALL_REQUIRED:
        assert not missing, "no tutorial: " + ", ".join(missing)


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, repr(ex)[:3000])
    sys.exit(1 if bad else 0)
