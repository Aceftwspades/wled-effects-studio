"""The in-app help without a window (native/reader.py, and what
reader_ui.py relies on): the three documents parse into the blocks the
reader draws, nothing of the markup is left in the text, the pictures and
links resolve, the search goes both ways round, every node F1 can land on
has its entry, and the help keys are where the menus say.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import reader, nodeface                  # noqa: E402

DOCS = {f: reader.parse(open(os.path.join(ROOT, f), encoding="utf-8").read(), ROOT) for _, f in reader.DOCS}


def test_the_three_documents_are_there_and_shipped():
    spec = open(os.path.join(ROOT, "studio.spec"), encoding="utf-8").read()
    for label, f in reader.DOCS:
        assert os.path.isfile(os.path.join(ROOT, f)), f
        assert f'"{f}"' in spec, f"{f} is not in studio.spec: the packaged app's Help would find nothing"
    assert 'folder("docs")' in spec                   # the tutorial's pictures


def test_every_document_has_headings_and_no_markup_left():
    for f, blocks in DOCS.items():
        assert blocks and blocks[0]["kind"] == "h" and blocks[0]["level"] == 1, f
        assert len(reader.headings(blocks)) >= 5, f
        for b in blocks:
            t = reader.block_text(b)
            if b["kind"] == "code":
                continue
            assert "**" not in t, (f, t[:80])
            assert not re.search(r"\]\([^)]*\)", t), (f, t[:80])          # a link left as written
            assert "\x00" not in t, (f, t[:80])                            # a code span's placeholder


def test_no_wrapped_line_starts_a_block():
    """A paragraph re-wrapped so a line begins "- " or "> " (a dash, a
    menu path) turns that line into a list item or a quote - here and on
    GitHub alike. None does."""
    starts = re.compile(r"^(> |[-*+] |\d+[.)] )")
    block = re.compile(r"^(\s|[-*+] |\d+[.)] |>|\||#)")
    bad = []
    for f in [f for _, f in reader.DOCS if f != "NODES.md"] + ["README.md"]:
        prev, code = "", False
        for n, line in enumerate(open(os.path.join(ROOT, f), encoding="utf-8").read().split("\n"), 1):
            if line.startswith("```"):
                code = not code
            elif not code and prev.strip() and starts.match(line) and not block.match(prev) and not prev.rstrip().endswith(":"):
                bad.append(f"{f}:{n}: {line[:60]}")
            prev = line if not code else ""
    assert not bad, bad


def test_inline_markup():
    t, links = reader.inline("**Coords `u` -> Wave `x`** and *this* and [the guide](GUIDE.md#keys)")
    assert t == "Coords u -> Wave x and this and the guide", t
    assert links == [("the guide", "GUIDE.md#keys")]
    assert reader.inline("`2*pi*x` stays")[0] == "2*pi*x stays"                 # a * in code is maths
    assert reader.inline(r"a \| b \* c")[0] == "a | b * c"
    assert reader.inline("a*b and c*d")[0] == "a*b and c*d"                     # no emphasis inside words


def test_blocks_of_every_kind():
    md = "\n".join(["# Title", "", "Some **bold** text", "over two lines.", "", "- one", "  - nested", "1. first",
                    "", "```cpp", "int x = 2 * 3;", "```", "", "| a | b |", "|---|---|", "| 1 | 2 \\| 3 |", "",
                    "> a quote", "", "---", "", "![alt](nowhere.png)", "<!-- a comment", "still -->", "end"])
    kinds = [b["kind"] for b in reader.parse(md)]
    assert kinds == ["h", "p", "li", "li", "li", "code", "table", "quote", "hr", "img", "p"], kinds
    b = reader.parse(md)
    assert b[1]["text"] == "Some bold text over two lines."
    assert (b[2]["depth"], b[3]["depth"], b[4]["number"]) == (0, 1, 1)
    assert b[5]["text"] == "int x = 2 * 3;" and b[5]["lang"] == "cpp"
    assert b[6]["head"] == ["a", "b"] and b[6]["rows"] == [["1", "2 | 3"]]
    assert b[9]["exists"] is False


def test_a_bold_line_is_a_label():
    b = reader.parse("**Outputs**\n\n- `x` *(float)*: a value\n\n**Bold** and not\n")
    assert b[0]["kind"] == "p" and b[0].get("strong") and b[0]["text"] == "Outputs"
    assert not b[2].get("strong")
    labels = [x["text"] for x in DOCS["NODES.md"] if x.get("strong")]
    assert {"Inputs", "Outputs", "Settings"} <= set(labels), set(labels)


def test_the_tutorial_pictures_exist():
    imgs = [b for b in DOCS["TUTORIAL.md"] if b["kind"] == "img"]
    assert imgs, "the tutorial has no pictures?"
    missing = [b["path"] for b in imgs if not b["exists"]]
    assert not missing, missing


def test_links_resolve():
    """Every link in the three documents (and the README) goes somewhere:
    a document of the three, a heading in it, a file, or the web."""
    bad = []
    for f in [f for _, f in reader.DOCS] + ["README.md"]:
        blocks = DOCS.get(f) or reader.parse(open(os.path.join(ROOT, f), encoding="utf-8").read(), ROOT)
        for b in blocks:
            for label, target in b.get("links", []):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                name, _, frag = target.partition("#")
                doc = f if not name else name
                if not os.path.exists(os.path.join(ROOT, doc)):
                    bad.append((f, target)); continue
                if frag and doc.endswith(".md"):
                    tb = DOCS.get(doc) or reader.parse(open(os.path.join(ROOT, doc), encoding="utf-8").read(), ROOT)
                    if reader.heading_index(tb, frag) is None:
                        bad.append((f, target))
    assert not bad, bad


def test_search_goes_round_both_ways():
    blocks = DOCS["GUIDE.md"]
    hits = reader.find_all(blocks, "snapshot")
    assert len(hits) >= 2, hits
    assert reader.find(blocks, "snapshot", 0) == hits[0]
    assert reader.find(blocks, "snapshot", hits[0] + 1) == hits[1]
    assert reader.find(blocks, "snapshot", hits[-1] + 1) == hits[0]              # round past the end
    assert reader.find(blocks, "snapshot", hits[1] - 1, -1) == hits[0]
    assert reader.find(blocks, "snapshot", hits[0] - 1, -1) == hits[-1]          # round past the top
    assert reader.find(blocks, "SNAPSHOT", 0) == hits[0]                         # any case
    assert reader.find(blocks, "no such words anywhere", 0) is None
    assert reader.find(blocks, "   ", 0) is None


def test_every_mention_is_a_stop():
    """The search steps through each mention - two in one paragraph are
    two stops - and into a table's cells."""
    blocks = reader.parse("# T\n\nsnap here and snap there\n\n| a | b |\n|---|---|\n| x | a snap |\n")
    assert reader.occurrences(blocks, "SNAP") == [(1, None, 0), (1, None, 14), (2, 3, 2)]
    assert reader.cells(blocks[2]) == ["a", "b", "x", "a snap"]
    assert reader.occurrences(blocks, "  ") == []
    g = DOCS["GUIDE.md"]
    assert len(reader.occurrences(g, "snapshot")) >= len(reader.find_all(g, "snapshot"))
    assert any(c is not None for _, c, _ in reader.occurrences(g, "Ctrl+Shift+K"))      # the keys table


def test_the_wrap_is_dear_imguis():
    """Where a found word is drawn: the lines Dear ImGui wraps a paragraph
    into (its comment's own example), and the span across its line."""
    adv = lambda c: 7.0
    t = "aaa bbb, ccc,ddd. eee   fff. ggg!"
    assert [t[a:b] for a, b in reader.wrap_lines(t, 7 * 9, adv)] == ["aaa bbb,", "ccc,ddd.", "eee", "fff. ggg!"]
    assert reader.locate(t, t.index("eee"), 3, 7 * 9, adv) == (2, 0.0, 21.0)
    assert reader.locate(t, t.index("ggg"), 3, 7 * 9, adv) == (3, 35.0, 56.0)
    w = "abcdefghij"
    assert [w[a:b] for a, b in reader.wrap_lines(w, 7 * 4, adv)] == ["abcd", "efgh", "ij"]     # a word too long is cut
    assert reader.locate("ab\ncdef\ng", 5, 2, None, adv) == (1, 14.0, 28.0)       # code: lines at newlines
    assert reader.wrap_lines("", 100, adv) == [(0, 0)]


def test_headings_by_text_and_anchor():
    g = DOCS["GUIDE.md"]
    k = reader.heading_index(g, "Making an effect")
    assert k is not None and g[k]["text"] == "Making an effect"
    assert reader.heading_index(g, "#making-an-effect") == k
    assert reader.heading_index(g, "making AN effect") == k
    assert reader.anchor("A show: the Sequence frame") == "a-show-the-sequence-frame"


def test_every_node_has_an_entry_for_f1():
    """F1 over a node opens NODES.md at its type: every type has one."""
    from native.nodedefs import library
    nodes = DOCS["NODES.md"]
    missing = [t for t in library() if reader.heading_index(nodes, t) is None]
    assert not missing, missing


def test_the_menu_line_is_the_first_sentence():
    fs = nodeface.first_sentence
    assert fs("What the microphone hears, as numbers 0..1. volume is the loudness") == "What the microphone hears, as numbers 0..1."
    assert fs("a cube... This says which part") == "a cube..."
    assert fs("One sentence only") == "One sentence only"
    assert fs("") == ""
    long = "word " * 60
    assert len(fs(long)) <= 150 and fs(long).endswith("...")


def test_the_help_keys():
    """F1 is the guide, and in the graph the node under the pointer; the
    shortcuts moved to Shift+F1; no two actions share a key in one place."""
    from native.keys import ACTIONS, Keymap
    km = Keymap({})
    assert km.lookup("F1", "global") == "guide"
    assert km.lookup("F1", "graph") == "node_help"
    assert km.lookup("Shift+F1", "global") == "shortcuts"
    assert km.lookup("Shift+F1", "graph") == "shortcuts"
    seen = {}
    clash = []
    for a, _, b, ctx in ACTIONS:
        if b and (b, ctx) in seen:
            clash.append((b, ctx, seen[(b, ctx)], a))
        seen[(b, ctx)] = a
    assert not clash, clash


def test_the_help_menu_opens_the_reader():
    src = open(os.path.join(ROOT, "native", "chrome.py"), encoding="utf-8").read()
    help_menu = src[src.index('dpg.menu(label="Help")'):]
    help_menu = help_menu[:help_menu.index("# --- the toolbar")]
    for f in ("GUIDE.md", "TUTORIAL.md", "NODES.md"):
        assert f'open_doc(app, "{f}")' in help_menu, f
    assert "STUDIO.md" not in help_menu            # the development log is not help


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as ex:
                bad += 1; print("FAIL", name, str(ex)[:3000])
    sys.exit(1 if bad else 0)
