"""The studio's documents as blocks a window can draw - the reader behind
Help > User guide, Tutorial and Node reference (reader_ui.py draws them).

Markdown as these documents use it: headings, paragraphs, bullet and
numbered lists (nested by indent), pipe tables, fenced code, standalone
images, block quotes, rules; inline **bold**, *italic*, `code` and
[links](target) are reduced to their text, the links kept beside it.

    blocks = parse(open("GUIDE.md").read(), base_dir)
    [b for b in blocks if b["kind"] == "h"]        # the contents
    find(blocks, "snapshot", start=0)              # the next block that mentions it
"""
import os
import re

# what Help offers, in its order: (menu label, file)
DOCS = [("User guide", "GUIDE.md"), ("Tutorial", "TUTORIAL.md"), ("Node reference", "NODES.md")]

_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMG = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def inline(text):
    """(plain text, [(label, target)]): the markup taken off, links kept.
    Code spans are left exactly as written (a * in `2*pi` is maths)."""
    links = []
    codes = []

    def keep(m):
        codes.append(m.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    def link(m):
        links.append((m.group(1), m.group(2)))
        return m.group(1)
    # the code spans set aside first, so markup round them still pairs up:
    # **Coords `u` -> Wave `x`** is one bold run with two spans inside
    t = re.sub(r"`([^`]*)`", keep, text)
    t = _LINK.sub(link, t)
    t = _BOLD.sub(r"\1", t)
    t = _ITAL.sub(r"\1", t)
    t = t.replace("\\|", "|").replace("\\*", "*").replace("\\_", "_")
    t = re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], t)
    links = [(re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], a), b) for a, b in links]
    return t, links


def anchor(text):
    """A heading's anchor as GitHub makes it: lower case, spaces to dashes,
    punctuation dropped."""
    t = inline(text)[0].strip().lower()
    t = re.sub(r"[^\w\- ]", "", t)
    return re.sub(r"\s", "-", t)


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [inline(c.strip())[0] for c in cells]


def parse(text, base_dir="."):
    """The document as a list of blocks, each a dict with a "kind":
    h (level, text, anchor), p (text, links; strong when it is all
    bold - a label on its own line), li (text, links, depth,
    number - None for a bullet), code (text, lang), table (head, rows),
    img (alt, path, exists), quote (text, links), hr."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    para = []
    i = 0

    def flush():
        if para:
            raw = " ".join(s.strip() for s in para)
            t, links = inline(raw)
            b = {"kind": "p", "text": t, "links": links}
            if re.fullmatch(r"\*\*[^*]+\*\*:?", raw):
                b["strong"] = True                   # a label on its own line: "**Outputs**"
            blocks.append(b)
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush(); i += 1; continue
        if s.startswith("<!--"):                    # an HTML comment: the guide's generated-section markers
            flush()
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1; continue
        if s.startswith("```"):
            flush()
            lang = s[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i]); i += 1
            blocks.append({"kind": "code", "text": "\n".join(body), "lang": lang})
            i += 1; continue
        m = _HEAD.match(s)
        if m:
            flush()
            t = inline(m.group(2))[0]
            blocks.append({"kind": "h", "level": len(m.group(1)), "text": t, "anchor": anchor(m.group(2))})
            i += 1; continue
        m = _IMG.match(s)
        if m:
            flush()
            path = m.group(2)
            full = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
            blocks.append({"kind": "img", "alt": m.group(1), "path": full, "exists": os.path.isfile(full)})
            i += 1; continue
        if _RULE.match(s) and not para:
            blocks.append({"kind": "hr"}); i += 1; continue
        if s.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            head = _cells(s)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i])); i += 1
            blocks.append({"kind": "table", "head": head, "rows": rows})
            continue
        if s.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip()[1:].strip()); i += 1
            t, links = inline(" ".join(q))
            blocks.append({"kind": "quote", "text": t, "links": links})
            continue
        mb, mn = _BULLET.match(line), _NUMBER.match(line)
        if mb or mn:
            flush()
            indent = len((mb or mn).group(1).replace("\t", "    "))
            body = [mb.group(2) if mb else mn.group(3)]
            number = None if mb else int(mn.group(2))
            i += 1
            # the item's continuation: indented lines that start no block of their own
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    break
                if _BULLET.match(nxt) or _NUMBER.match(nxt) or _HEAD.match(nxt.strip()) or nxt.strip().startswith(("```", "|", ">")):
                    break
                if len(nxt) - len(nxt.lstrip()) <= indent and not nxt.startswith(" "):
                    break
                body.append(nxt.strip()); i += 1
            t, links = inline(" ".join(body))
            blocks.append({"kind": "li", "text": t, "links": links, "depth": indent // 2, "number": number})
            continue
        para.append(line)
        i += 1
    flush()
    return blocks


def headings(blocks, deepest=3):
    """[(block index, level, text)] for the contents list."""
    return [(k, b["level"], b["text"]) for k, b in enumerate(blocks) if b["kind"] == "h" and b["level"] <= deepest]


def block_text(b):
    """Everything a block says, for the search."""
    if b["kind"] == "table":
        return " ".join(b["head"]) + " " + " ".join(" ".join(r) for r in b["rows"])
    if b["kind"] == "img":
        return b["alt"]
    return b.get("text", "")


def find(blocks, needle, start=0, step=1):
    """The first block at or after `start` that mentions `needle` (any
    case), going round past the end; with step -1, at or before it,
    going round past the top. None when no block does."""
    n = (needle or "").strip().lower()
    if not n or not blocks:
        return None
    start = max(0, min(start, len(blocks) - 1))
    order = list(range(start, len(blocks))) + list(range(0, start)) if step > 0 \
        else list(range(start, -1, -1)) + list(range(len(blocks) - 1, start, -1))
    for k in order:
        if n in block_text(blocks[k]).lower():
            return k
    return None


def cells(b):
    """A table's cells in reading order - the head, then each row cut or
    padded to the head's width - as the reader draws them."""
    n = len(b["head"])
    out = list(b["head"])
    for row in b["rows"]:
        out += (list(row) + [""] * n)[:n]
    return out


def occurrences(blocks, needle):
    """Every place the text appears (any case), in reading order:
    [(block, cell, start)] - cell None but in a table, where it is the
    cell's index in cells(b) and start is in that cell."""
    n = (needle or "").strip().lower()
    out = []
    if not n:
        return out
    for k, b in enumerate(blocks):
        parts = [(i, c) for i, c in enumerate(cells(b))] if b["kind"] == "table" else [(None, block_text(b))]
        for cell, text in parts:
            low = text.lower()
            i = low.find(n)
            while i >= 0:
                out.append((k, cell, i))
                i = low.find(n, i + max(1, len(n)))
    return out


BLANK = " \t\u3000"
BREAK_AFTER = '.,;!?"'


def wrap_eol(text, s, width, adv):
    """Where Dear ImGui ends the line that starts at s, wrapping at `width`
    (its ImFont::CalcWordWrapPositionA, over the same character advances):
    at a blank or after punctuation, a word too long for any line cut
    anywhere, at least one character a line."""
    line_w = word_w = blank_w = 0.0
    word_end, prev_word_end, inside = s, None, True
    i, n = s, len(text)
    while i < n:
        c = text[i]
        cw = adv(c)
        if c in BLANK:
            if inside:
                line_w += blank_w
                blank_w = 0.0
                word_end = i
            blank_w += cw
            inside = False
        else:
            word_w += cw
            if inside:
                word_end = i + 1
            else:
                prev_word_end = word_end
                line_w += word_w + blank_w
                word_w = blank_w = 0.0
            inside = c not in BREAK_AFTER
        if line_w + word_w > width:
            if word_w < width:
                i = prev_word_end if prev_word_end is not None else word_end
            break
        i += 1
    return s + 1 if i == s and s < n else i


def wrap_lines(text, width, adv):
    """[(start, end)]: the lines the text is drawn in at this width, the
    blanks a wrap swallows left out between them."""
    lines, s, n = [], 0, len(text)
    while s < n:
        e = wrap_eol(text, s, width, adv)
        lines.append((s, e))
        s = e
        while s < n and text[s] in BLANK:
            s += 1
    return lines or [(0, 0)]


def locate(text, start, length, width, adv):
    """Where `length` characters at `start` are drawn: (line, x0, x1) -
    the line's number, the span across it (on the first line it reaches,
    when a wrap splits it). width None: no wrapping, lines at newlines."""
    if width is None:
        line = text.count("\n", 0, start)
        a = text.rfind("\n", 0, start) + 1
        b = text.find("\n", start)
        b = len(text) if b < 0 else b
        spans = [(a, b)]
    else:
        spans = wrap_lines(text, width, adv)
        line = max([i for i, (a, _) in enumerate(spans) if a <= start] or [0])
        spans = [spans[line]]
    a, b = spans[0]
    x0 = sum(adv(c) for c in text[a:start])
    x1 = x0 + sum(adv(c) for c in text[start:min(start + length, b)])
    return line, x0, x1


def find_all(blocks, needle):
    """Every block that mentions `needle`, in order (for "3 of 12")."""
    n = (needle or "").strip().lower()
    return [k for k, b in enumerate(blocks) if n and n in block_text(b).lower()]


def heading_index(blocks, target):
    """The block of a heading, by its text (any case) or its anchor."""
    t = (target or "").strip().lstrip("#").lower()
    for k, b in enumerate(blocks):
        if b["kind"] == "h" and (b["text"].lower() == t or b["anchor"] == t):
            return k
    return None
