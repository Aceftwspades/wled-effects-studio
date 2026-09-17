"""A copy of every version saved, per graph and per code effect.

Live editing rebuilds and saves as you go, so a wrong move is written to
disk within a second. Each save first keeps what the file held under
`<project>/history/<kind>/<stem>/<time>.<ext>`, the newest KEEP of them, and
File > History lists them with a restore.

    keep(project, "graphs", "box_fire", ".json", old_text)
    versions(project, "graphs", "box_fire")   -> [(path, time, size)] newest first
"""
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
