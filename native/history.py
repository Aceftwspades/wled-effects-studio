"""A copy of every version saved, per graph and per code effect.

Live editing rebuilds and saves as you go, so a wrong move is written to
disk within a second. Each save first keeps what the file held under
`<project>/history/<kind>/<stem>/<time>.<ext>`, the newest KEEP of them, and
File > History lists them with a restore.

    keep(project, "graphs", "box_fire", ".json", old_text)
    versions(project, "graphs", "box_fire")   -> [(path, time, size)] newest first
    changes("graphs", old_text, new_text)     -> [(tag, line)]: what changed since a version
"""
import json
import os
import time

KEEP = 40


def _dir(project, kind, stem):
    return os.path.join(project.path, "history", kind, stem)


def keep(project, kind, stem, ext, old_text):
    """Keep the text a file held before a save, unless it is what is being
    saved again (nothing changed) or empty."""
    if not old_text or not old_text.strip():
        return None
    d = _dir(project, kind, stem)
    os.makedirs(d, exist_ok=True)
    vs = versions(project, kind, stem)
    if vs:
        try:
            if open(vs[0][0], encoding="utf-8").read() == old_text:
                return vs[0][0]
        except OSError:
            pass
    path = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + f"-{n}" + ext); n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(old_text)
    for p, _, _ in versions(project, kind, stem)[KEEP:]:
        try:
            os.remove(p)
        except OSError:
            pass
    return path


def versions(project, kind, stem):
    d = _dir(project, kind, stem)
    if not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        p = os.path.join(d, f)
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append((p, st.st_mtime, st.st_size))
    out.sort(key=lambda v: v[1], reverse=True)
    return out


# --- what changed since a version (File > History's "changes") ---------------------------
def _short(v, n=48):
    s = "(none)" if v is None else v if isinstance(v, str) else json.dumps(v)
    return s if len(s) <= n else s[:n - 3] + "..."


def changes(kind, old_text, new_text, limit=400):
    """What changed from a kept version (old) to now (new), as (tag, line)
    rows - tag "+" added, "-" gone, "~" changed, "@" a place in a code
    diff, " " context - so a version can be judged before it is restored.
    A code effect is a unified diff; a graph, its nodes and wires (a
    setting or a typed value as old -> new, the nodes that only moved
    counted); the project's settings, the keys that differ."""
    if old_text == new_text:
        return [(" ", "no change: this version is what is there now")]
    if kind == "effects":
        import difflib
        rows = []
        for line in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), "that version", "now", n=2, lineterm=""):
            if line.startswith(("---", "+++")):
                continue
            rows.append(("@" if line.startswith("@@") else (line[:1] if line[:1] in "+-" else " "), line))
            if len(rows) >= limit:
                rows.append((" ", "... and more"))
                break
        return rows or [(" ", "only the line endings differ")]
    try:
        old, new = json.loads(old_text), json.loads(new_text)
    except ValueError:
        return [("~", "one of the two does not read as JSON: no comparison")]
    if kind == "project":
        for d in (old, new):
            if isinstance(d, dict):
                d.pop("saved", None)                      # when it was written: always differs
        if old == new:
            return [(" ", "no change: only the time it was saved differs")]
    if kind in ("graphs", "subgraphs"):
        return _graph_changes(old, new, limit)
    return _json_changes(old, new, limit)


def _graph_changes(old, new, limit):
    def nodes(g):
        return {int(n["id"]): n for n in g.get("nodes") or [] if "id" in n}

    def name(n):
        return f"{n.get('label') or n.get('type', '?')} #{n.get('id')}"

    def wires(g):
        return {(int(l[0]), str(l[1]), int(l[2]), str(l[3])) for l in g.get("links") or [] if len(l) >= 4}

    def wname(w, ns):
        src, dst = ns.get(w[0]), ns.get(w[2])
        return (f"{name(src) if src else '#' + str(w[0])} {w[1]} -> "
                f"{name(dst) if dst else '#' + str(w[2])} {w[3]}")
    a, b = nodes(old), nodes(new)
    rows = []
    for nid in sorted(b.keys() - a.keys()):
        rows.append(("+", f"{name(b[nid])} added"))
    for nid in sorted(a.keys() - b.keys()):
        rows.append(("-", f"{name(a[nid])} gone"))
    moved = 0
    for nid in sorted(a.keys() & b.keys()):
        na, nb = a[nid], b[nid]
        if na.get("type") != nb.get("type"):
            rows.append(("~", f"{name(na)} is a {nb.get('type')} now"))
        for part in ("params", "inputs"):
            pa, pb = na.get(part) or {}, nb.get(part) or {}
            for key in sorted(set(pa) | set(pb)):
                if pa.get(key) != pb.get(key):
                    rows.append(("~", f"{name(nb)} {key}: {_short(pa.get(key, '(default)'))} -> {_short(pb.get(key, '(default)'))}"))
        for flag in ("label", "muted", "collapsed", "color"):
            if na.get(flag) != nb.get(flag):
                rows.append(("~", f"{name(nb)} {flag}: {_short(na.get(flag))} -> {_short(nb.get(flag))}"))
        if na.get("pos") != nb.get("pos"):
            moved += 1
    wa, wb = wires(old), wires(new)
    for w in sorted(wb - wa):
        rows.append(("+", "wire " + wname(w, b)))
    for w in sorted(wa - wb):
        rows.append(("-", "wire " + wname(w, a)))
    if moved:
        rows.append((" ", f"{moved} node(s) moved"))
    for key in sorted((set(old) | set(new)) - {"nodes", "links"}):
        if old.get(key) != new.get(key):
            rows.append(("~", f"{key}: {_short(old.get(key))} -> {_short(new.get(key))}"))
    if len(rows) > limit:
        rows = rows[:limit] + [(" ", f"... and {len(rows) - limit} more")]
    return rows or [(" ", "the same graph, written differently")]


def _json_changes(old, new, limit, path=""):
    """The keys of two JSON values that differ, as dotted paths (the project's settings)."""
    rows = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new), key=str):
            p = f"{path}.{key}" if path else str(key)
            if key not in new:
                rows.append(("-", f"{p}: {_short(old[key])}"))
            elif key not in old:
                rows.append(("+", f"{p}: {_short(new[key])}"))
            elif old[key] != new[key]:
                rows += _json_changes(old[key], new[key], limit, p)
    elif old != new:
        rows.append(("~", f"{path or '(the whole)'}: {_short(old)} -> {_short(new)}"))
    if not path and len(rows) > limit:
        rows = rows[:limit] + [(" ", f"... and {len(rows) - limit} more")]
    return rows
