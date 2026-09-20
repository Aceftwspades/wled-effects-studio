"""
The node graph, and its compiler to a WLED effect.

A graph is nodes and links:

    {"name": "Aurora", "nodes": [{"id": 3, "type": "Noise", "pos": [x, y],
                                  "params": {...}}, ...],
     "links": [[from_id, "out", to_id, "in"], ...]}

compile() turns it into ONE ordinary effect file - the same shape as a
hand-written one, so it drops into a firmware build unchanged:

    helpers
    static FX_RET mode_<ident>() {
      guard, dimensions
      frame scope: t, dt, then every node that needs no coordinate, in order
      per pixel: the prologue (u, v, cx, cy, r, ang, nx, ny, nz), then every
                 remaining node in order, then the Output
    }
    metadata, registration

The order is a topological sort of the links, so a node is always emitted
after the nodes it reads. A cycle is an error - feedback is the Previous node,
which reads last frame's buffer rather than this frame's graph.

HOISTING is the one optimisation, and it matters: a Multiply of two sliders
computed per pixel is 1,280 multiplies a frame for nothing. Any node whose
template reads no per-pixel name and whose inputs are all frame-scope is
emitted at frame scope. Coords, Direction, Pixel, Previous, Ripple and
Sparkle read the prologue and stay per pixel; everything downstream of them
does too.

Type rules are small: float and bool coerce both ways (0/1, > 0.5), colour
converts to nothing. An unconnected input takes the value typed on the node,
else the definition's default.
"""
import json
import re

from native.nodedefs import library, HELPERS, CODEGEN

PIXEL_NAMES = re.compile(r"\b(px|py|u|v|cx|cy|r|ang|nx|ny|nz|X3|Y3|Z3|W|H|N|gc_out|part|along|nparts)\b")
TYPES = {"float": "float", "color": "uint32_t", "bool": "bool", "vector": "GcVec"}
ZERO = {"float": "0", "color": "0", "bool": "false", "vector": "GcVec{0.0f, 0.0f, 0.0f}"}


class GraphError(ValueError):
    pass


def _ident(name):
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    if not s or s[0].isdigit():
        s = "fx_" + s
    return s


def _lit(t, v):
    """A C++ literal of type t for default/param value v."""
    if t == "float":
        return f"{float(v)}f"
    if t == "bool":
        return "true" if v else "false"
    if t == "color":
        if isinstance(v, (list, tuple)):
            r, g, b = (int(x) for x in v[:3])
            return f"0x{(r << 16) | (g << 8) | b:06X}u"
        return f"{int(v)}u"
    if t == "int":
        return str(int(v))
    if t == "vector":
        if isinstance(v, (list, tuple)):
            x, y, z = (float(c) for c in (list(v) + [0, 0, 0])[:3])
        else:
            x = y = z = float(v)
        return f"GcVec{{{x}f, {y}f, {z}f}}"
    return str(v)


def _coerce(expr, have, want):
    """One type into another on a wire. float and bool both ways; a float
    into a vector fills all three; a vector into a float is its x; colour
    and vector convert as r, g, b in 0..1."""
    if have == want:
        return expr
    if have == "bool" and want == "float":
        return f"({expr} ? 1.0f : 0.0f)"
    if have == "float" and want == "bool":
        return f"({expr} > 0.5f)"
    if have == "float" and want == "vector":
        return f"gc_v3({expr}, {expr}, {expr})"
    if have == "bool" and want == "vector":
        return f"gc_v3({expr} ? 1.0f : 0.0f, {expr} ? 1.0f : 0.0f, {expr} ? 1.0f : 0.0f)"
    if have == "vector" and want == "float":
        return f"({expr}).x"
    if have == "vector" and want == "bool":
        return f"(({expr}).x > 0.5f)"
    if have == "color" and want == "vector":
        return f"gc_col2v({expr})"
    if have == "vector" and want == "color":
        return f"gc_v2col({expr})"
    raise GraphError(f"cannot connect {have} to {want}")


def feature_note(need, feats):
    """Why a node wanting `need` is worse off under these features, or None."""
    if not need or not feats:
        return None
    if need == "imu" and feats.get("imu") is False:
        return "needs the IMU feature, off in this project (Flash > Features): its sensor output stays false"
    if need == "audio" and feats.get("audio") == "none":
        return "audio is off in this project's features (Flash > Features): this reads WLED's simulated sound"
    return None


def compatible(a, b):
    """Can a pin of type a feed a pin of type b? Everything but colour into
    float/bool - and that one only through Split."""
    if a == b:
        return True
    return not ({a, b} == {"color", "float"} or {a, b} == {"color", "bool"})


def _sub(code, kind, name, repl):
    """Replace $kind.name in a template, whole-name only: $in.burst must not
    eat the front of $in.burst_count."""
    return re.sub(r"\$" + kind + r"\." + re.escape(name) + r"(?![A-Za-z0-9_])", lambda m: repl, code)


SUB = "sub:"          # node type prefix for a sub-graph used as a node


def boundary_def(base, n):
    """The definition of a Graph input / Graph output node with its pin typed
    by its own `type` param - the one place a node's pins depend on its
    settings."""
    t = n.get("params", {}).get("type", "float")
    d = dict(base)
    if base["name"] == "Graph input":
        d["outputs"] = [{"name": "value", "type": t}]
        if t == "float":    d["code"] = "$out.value = $p.default;"
        elif t == "bool":   d["code"] = "$out.value = $p.default > 0.5f;"
        elif t == "vector": d["code"] = "$out.value = gc_v3($p.default, $p.default, $p.default);"
        else:               d["code"] = "$out.value = mq_scale(0xFFFFFFu, (uint8_t)(gc_sat($p.default) * 255.0f));"
    else:
        d["inputs"] = [{"name": "value", "type": t, "default": 0}]
    return d


EXPOSABLE = {"float": "float", "int": "float", "bool": "bool", "color": "color"}


def exposable(d):
    """The params of a definition that can be pins: numbers, switches and
    colours, on a node whose code is a template (a codegen reads its params
    itself)."""
    if d.get("codegen"):
        return []
    return [p["name"] for p in d["params"] if p["type"] in EXPOSABLE]


def exposed_def(base, n):
    """The definition with the node's exposed params turned into inputs: a
    slider's worth of setting becomes a pin, wired or left at the value it
    had. The template reads `$in.name` where it read `$p.name`."""
    names = [x for x in n.get("expose") or [] if x in exposable(base)]
    if not names:
        return base
    d = dict(base)
    d["params"] = [p for p in base["params"] if p["name"] not in names]
    ins = list(base["inputs"])
    code = base["code"]
    for p in base["params"]:
        if p["name"] in names:
            v = n.get("params", {}).get(p["name"], p["default"])
            if p["type"] == "color" and isinstance(v, (list, tuple)):
                v = list(v)
            ins.append({"name": p["name"], "type": EXPOSABLE[p["type"]], "default": v,
                        "doc": (p.get("doc") or "") + " (a setting, exposed as a pin)"})
            code = _sub(code, "p", p["name"], "$in." + p["name"])
    d["inputs"] = ins
    d["code"] = code
    return d


def sub_def(name, sub):
    """The definition of a sub-graph as a node: one pin per boundary node,
    and one setting per inner setting the sub-graph promotes (a node's
    "promote" list) - set on the sub node in the parent, applied to the
    inner node when the sub-graph is inlined."""
    ins, outs, params = [], [], []
    for n in sorted(sub.nodes.values(), key=lambda n: (n["pos"][1], n["pos"][0])):
        if n["type"] == "Graph input":
            ins.append({"name": n["params"].get("name", "in"), "type": n["params"].get("type", "float"),
                        "default": n["params"].get("default", 0.0)})
        elif n["type"] == "Graph output":
            outs.append({"name": n["params"].get("name", "out"), "type": n["params"].get("type", "float")})
        for pname in n.get("promote") or []:
            try:
                d = sub.node_def(n)
            except GraphError:
                continue
            p = next((q for q in d["params"] if q["name"] == pname), None)
            if p is None:
                continue
            label = d.get("label") or n["type"]
            entry = dict(p)
            entry["name"] = f"{pname} of {label} #{n['id']}"
            entry["default"] = n["params"].get(pname, p["default"])
            entry["promote"] = (n["id"], pname)
            entry["doc"] = f"{label}'s {pname}, set from outside: " + (p.get("doc") or "")
            params.append(entry)
    return dict(name=SUB + name, cat="subgraphs", scope="pixel", inputs=ins, outputs=outs, params=params,
                code="", doc=f"sub-graph {sub.name}: {len(ins)} in, {len(outs)} out"
                + (f", {len(params)} setting(s)" if params else ""), label=sub.name)


class Graph:
    def __init__(self, d=None, lib=None, resolver=None):
        self.lib = lib or library()
        # name -> Graph, for sub-graph nodes; supplied by the project
        self.resolver = resolver
        self.project_dir = None       # where relative file params resolve; the panel sets it
        d = d or {}
        self.name = d.get("name", "Untitled")
        self.nodes = {int(n["id"]): dict(n, id=int(n["id"])) for n in d.get("nodes", [])}
        self.links = [tuple(l[:4]) for l in d.get("links", [])]
        # per-link decoration, keyed by the input it lands on: {"color": [r,g,b]}
        self.link_meta = {(int(l[2]), l[3]): dict(l[4]) for l in d.get("links", []) if len(l) > 4 and l[4]}
        self._next = max(self.nodes.keys(), default=0) + 1
        self.stray = self.prune_links()

    def prune_links(self):
        """Wires with an end that is not there - a node or a pin missing,
        as a hand-edited or half-written file can have - dropped, and
        listed, so the graph loads and compiles instead of failing on
        them. A node whose definition cannot be resolved keeps its wires:
        that is its own problem to report."""
        keep, stray = [], []
        for l in self.links:
            a, out, b, inp = l[:4]
            ok = a in self.nodes and b in self.nodes
            if ok:
                try:
                    ad, bd = self.node_def(self.nodes[a]), self.node_def(self.nodes[b])
                    ok = any(o["name"] == out for o in ad["outputs"]) and any(i["name"] == inp for i in bd["inputs"])
                except GraphError:
                    pass
            (keep if ok else stray).append(l)
        self.links = keep
        for l in stray:
            self.link_meta.pop((l[2], l[3]), None)
        return stray

    # --- definitions -----------------------------------------------------------
    def node_def(self, n):
        """The definition that applies to THIS node: the library's, typed by
        the node's params for a boundary node, derived for a sub-graph."""
        t = n["type"]
        if t.startswith(SUB):
            if t in self.lib:
                return self.lib[t]
            sub = self.resolver(t[len(SUB):]) if self.resolver else None
            if sub is None:
                raise GraphError(f"node {n['id']}: sub-graph {t[len(SUB):]!r} not found")
            return sub_def(t[len(SUB):], sub)
        d = self.lib.get(t)
        if d is None:
            raise GraphError(f"node {n['id']}: unknown type {t!r}")
        if t in ("Graph input", "Graph output"):
            return boundary_def(d, n)
        if n.get("expose"):
            return exposed_def(d, n)
        return d

    # --- editing -----------------------------------------------------------
    def add(self, type_, pos=(0, 0), params=None):
        if type_ not in self.lib and not type_.startswith(SUB):
            raise GraphError(f"no node type {type_!r}")
        d = self.lib[type_] if type_ in self.lib else {"params": []}
        p = {q["name"]: q["default"] for q in d["params"]}
        if params:
            p.update(params)
        nid = self._next; self._next += 1
        self.nodes[nid] = {"id": nid, "type": type_, "pos": list(pos), "params": p, "inputs": {}}
        return nid

    def remove(self, nid):
        self.nodes.pop(nid, None)
        self.links = [l for l in self.links if l[0] != nid and l[2] != nid]
        self.link_meta = {k: v for k, v in self.link_meta.items() if k[0] != nid}

    def link(self, a, out, b, inp):
        # one link per input
        self.links = [l for l in self.links if not (l[2] == b and l[3] == inp)]
        self.links.append((a, out, b, inp))

    def unlink(self, b, inp):
        self.links = [l for l in self.links if not (l[2] == b and l[3] == inp)]
        self.link_meta.pop((b, inp), None)

    def unlink_out(self, a, out):
        """Every link leaving this output."""
        for l in [l for l in self.links if l[0] == a and l[1] == out]:
            self.unlink(l[2], l[3])

    def duplicate(self, nid, offset=(40, 40), with_links=False):
        """A copy beside the node; with_links, the copy is fed by the same
        wires (Blender's Shift+D)."""
        n = self.nodes.get(nid)
        if not n:
            return None
        import copy
        pos = (n["pos"][0] + offset[0], n["pos"][1] + offset[1])
        new = self.add(n["type"], pos, copy.deepcopy(n.get("params", {})))
        self.nodes[new]["inputs"] = copy.deepcopy(n.get("inputs", {}))
        for k in ("color", "collapsed", "hide_pins", "muted"):
            if k in n:
                self.nodes[new][k] = n[k]
        if with_links:
            for a, o, b, i in list(self.links):
                if b == nid:
                    self.link(a, o, new, i)
        return new

    def arrange(self, col_w=260, row_gap=30, only=None):
        """Lay the nodes out in columns by depth - each node one column right
        of the furthest node that feeds it - stacked in their current order.
        Frames and notes stay where they are. With `only`, just those nodes,
        by their depth among themselves, anchored at their top-left corner."""
        ids_ = set(only) if only else set(self.nodes)
        deps = {nid: set() for nid in self.nodes if nid in ids_}
        for a, _, b, _ in self.links:
            if a in deps and b in deps and not self._late(b):
                deps[b].add(a)
        ox, oy = 40, 40
        if only:
            ox = min(self.nodes[i]["pos"][0] for i in ids_ if i in self.nodes)
            oy = min(self.nodes[i]["pos"][1] for i in ids_ if i in self.nodes)
        depth = {}
        def dep(n, seen=()):
            if n in depth:
                return depth[n]
            if n in seen:
                return 0
            d = 0
            for m in deps[n]:
                d = max(d, dep(m, seen + (n,)) + 1)
            depth[n] = d
            return d
        for nid in deps:
            dep(nid)
        cols = {}
        for nid, n in self.nodes.items():
            if n["type"] in ("Frame", "Note") or nid not in deps:
                continue
            cols.setdefault(depth[nid], []).append(nid)
        for c, ids in cols.items():
            ids.sort(key=lambda i: self.nodes[i]["pos"][1])
            y = oy
            for nid in ids:
                n = self.nodes[nid]
                n["pos"] = [ox + c * col_w, y]
                try:
                    d = self.node_def(n)
                    rows = len(d["inputs"]) + len(d["outputs"]) + (0 if n.get("collapsed") else len(d["params"]))
                except GraphError:
                    rows = 3
                y += 56 + 27 * max(1, rows) + row_gap

    def to_json(self):
        links = []
        for l in self.links:
            m = self.link_meta.get((l[2], l[3]))
            links.append(list(l) + ([m] if m else []))
        return {"name": self.name,
                "nodes": [dict(n) for n in self.nodes.values()],
                "links": links}

    # --- compile -------------------------------------------------------------
    def _late(self, nid):
        try:
            return bool(self.node_def(self.nodes[nid]).get("late"))
        except GraphError:
            return False

    def _order(self):
        deps = {nid: set() for nid in self.nodes}
        for a, _, b, _ in self.links:
            if a in deps and b in deps and not self._late(b):
                deps[b].add(a)
        out, seen, temp = [], set(), set()

        def visit(n):
            if n in seen:
                return
            if n in temp:
                raise GraphError(f"cycle through node {n} ({self.nodes[n]['type']}) - loop a value back through a Delay node (or Previous, for colour)")
            temp.add(n)
            for d in sorted(deps[n]):
                visit(d)
            temp.discard(n); seen.add(n); out.append(n)
        for n in sorted(self.nodes):
            visit(n)
        return out

    def problems(self):
        """What would stop, or should worry, a compile: {node id: message}.
        Errors: a cycle, more than one Output, a missing sub-graph, an
        unknown type. Warnings: an output that feeds nothing, and no Output
        at all (reported on every node that could have fed one)."""
        out = {}
        defs = {}
        for nid, n in self.nodes.items():
            try:
                defs[nid] = self.node_def(n)
            except GraphError as e:
                out[nid] = "error: " + str(e).split(": ", 1)[-1]
        # a node leaning on a feature the project's firmware leaves out
        feats = getattr(self, "features", None) or {}
        for nid, d in defs.items():
            msg = feature_note(d.get("needs"), feats)
            if msg:
                out.setdefault(nid, "warn: " + msg)
        # cycles: every node still on the stack when one is found
        deps = {nid: set() for nid in self.nodes}
        for a, _, b, _ in self.links:
            if a in deps and b in deps and not self._late(b):
                deps[b].add(a)
        seen, stack = set(), []
        def visit(n):
            if n in seen:
                return
            if n in stack:
                for m in stack[stack.index(n):]:
                    out[m] = "error: in a cycle - use Previous for feedback"
                return
            stack.append(n)
            for d in sorted(deps[n]):
                visit(d)
            stack.pop(); seen.add(n)
        for n in sorted(self.nodes):
            visit(n)
        outs = [nid for nid, n in self.nodes.items() if n["type"] == "Output"]
        if len(outs) > 1:
            for nid in outs:
                out.setdefault(nid, "error: more than one Output")
        # a wire between types that do not convert (a colour into a number)
        for a, o, b, i in self.links:
            if a in defs and b in defs and b not in out:
                at = next((x["type"] for x in defs[a]["outputs"] if x["name"] == o), None)
                it = next((x["type"] for x in defs[b]["inputs"] if x["name"] == i), None)
                if at and it and not compatible(at, it):
                    out[b] = f"error: {i} cannot take a {at} (from {defs[a]['name']} #{a})"
        # an input that reads another node's state must be wired, or the C++ would not build
        linked = {(b, i) for _, _, b, i in self.links}
        for nid, d in defs.items():
            w = d.get("wired")
            if w and (nid, w[0]) not in linked:
                out[nid] = f"error: {w[0]} must be wired from {w[1]}"
        fed = {a for a, _, _, _ in self.links}
        for nid, d in defs.items():
            if nid in out or d.get("decor") or not d["outputs"]:
                continue
            if nid not in fed and self.nodes[nid]["type"] != "Graph output":
                out[nid] = "feeds nothing"
        return out

    def flatten(self, depth=0):
        """A copy with every sub-graph node replaced by its contents.

        A sub node's input pin X is the sub-graph's "Graph input" named X:
        whatever fed the pin now feeds everything that read that input node,
        and an unconnected pin leaves the sub-graph's default in place. The
        pin Y is the "Graph output" named Y: whatever fed it inside now feeds
        everything the pin fed outside. The boundary nodes themselves vanish.
        Recursive, so a sub-graph may use sub-graphs; twelve deep is a loop.
        """
        if depth > 12:
            raise GraphError("sub-graphs nested more than twelve deep - is one inside itself?")
        flat = Graph({"name": self.name}, lib=self.lib, resolver=self.resolver)
        flat.project_dir = getattr(self, "project_dir", None)
        flat.nodes = {}
        flat.link_meta = dict(self.link_meta)
        idmap = {}
        # plain nodes first, keeping ids where possible
        for nid, n in self.nodes.items():
            if not n["type"].startswith(SUB):
                flat.nodes[nid] = dict(n, id=nid, params=dict(n.get("params", {})), inputs=dict(n.get("inputs", {})))
                idmap[nid] = nid
        flat._next = max(flat.nodes.keys(), default=0) + 1
        links = list(self.links)
        for nid, n in self.nodes.items():
            if not n["type"].startswith(SUB):
                continue
            name = n["type"][len(SUB):]
            sub = self.resolver(name) if self.resolver else None
            if sub is None:
                raise GraphError(f"sub-graph {name!r} not found")
            sub = sub.flatten(depth + 1)
            # bring the sub-graph's nodes in under fresh ids
            smap = {}
            for sid, sn in sub.nodes.items():
                new = flat._next; flat._next += 1
                smap[sid] = new
                flat.nodes[new] = dict(sn, id=new, params=dict(sn.get("params", {})), inputs=dict(sn.get("inputs", {})),
                                       pos=[sn["pos"][0] + n["pos"][0], sn["pos"][1] + n["pos"][1]])
            inner = [(smap[a], o, smap[b], i) for a, o, b, i in sub.links]
            # promoted settings: the sub node's values onto the inner nodes
            try:
                sdef = self.node_def(n)
            except GraphError:
                sdef = {"params": []}
            for p in sdef["params"]:
                if p.get("promote") and p["promote"][0] in smap:
                    sid, pname = p["promote"]
                    flat.nodes[smap[sid]]["params"][pname] = n.get("params", {}).get(p["name"], p["default"])
            # where each boundary pin lands
            src_in = {}    # pin name -> what feeds it from OUTSIDE (a, out), if anything
            for a, o, b, i in links:
                if b == nid:
                    src_in[i] = (a, o)
            out_src = {}   # pin name -> what feeds the Graph output INSIDE (a, out)
            for a, o, b, i in inner:
                bn = flat.nodes[b]
                if bn["type"] == "Graph output":
                    out_src[bn["params"].get("name", "out")] = (a, o)
            # rewire: links inside from a Graph input -> from the outside source (or keep the
            # boundary node, which then yields its default)
            rewired = []
            for a, o, b, i in inner:
                an = flat.nodes[a]
                if an["type"] == "Graph input":
                    pin = an["params"].get("name", "in")
                    if pin in src_in:
                        a, o = src_in[pin]
                if flat.nodes[b]["type"] == "Graph output":
                    continue
                rewired.append((a, o, b, i))
            # links outside from the sub node's outputs -> from the inner source
            outer = []
            for a, o, b, i in links:
                if a == nid:
                    if o in out_src:
                        a, o = out_src[o]
                        outer.append((a, o, b, i))
                    # an output nothing feeds inside just goes unconnected
                elif b == nid:
                    continue
                else:
                    outer.append((a, o, b, i))
            links = outer + rewired
            # boundary nodes that still feed something keep their defaults; the
            # rest and every Graph output are dropped
            used = {a for a, _, _, _ in links}
            for sid, new in smap.items():
                t = flat.nodes[new]["type"]
                if t == "Graph output" or (t == "Graph input" and new not in used):
                    flat.nodes.pop(new, None)
        flat.links = [l for l in links if l[0] in flat.nodes and l[2] in flat.nodes]
        return flat

    def plan(self):
        """What both back ends need: the nodes in order with their
        definitions, each one's scope (frame or pixel), the source of every
        wired input, and the state slots. Raises GraphError as compile does."""
        defs = {nid: self.node_def(n) for nid, n in self.nodes.items()}
        order = [nid for nid in self._order() if not defs[nid].get("decor")]
        src_of = {(b, inp): (a, out) for a, out, b, inp in self.links}
        for nid, d in defs.items():
            w = d.get("wired")
            if w and (nid, w[0]) not in src_of:
                raise GraphError(f"{d['name']} #{nid}: {w[0]} must be wired from {w[1]}")
        scope = {}
        for nid in order:
            d = defs[nid]
            ups = [src_of[(nid, i["name"])][0] for i in d["inputs"] if (nid, i["name"]) in src_of]
            per_pixel_in = any(scope.get(u) == "pixel" for u in ups)
            if d.get("late") and per_pixel_in:
                raise GraphError(f"{d['name']} #{nid} remembers one value for the next frame, so its input "
                                 f"cannot come from a per-pixel node")
            if d["scope"] == "frame":
                if per_pixel_in and d.get("state"):
                    raise GraphError(f"{d['name']} #{nid} keeps one value per frame, so its inputs "
                                     f"cannot come from a per-pixel node (Coords, Noise...)")
                scope[nid] = "pixel" if per_pixel_in else "frame"; continue
            bare = re.sub(r"\$(in|out|p|st)\.[\w ]+", "", d["code"])
            if PIXEL_NAMES.search(bare) or d.get("codegen"):
                scope[nid] = "pixel"; continue
            scope[nid] = "pixel" if per_pixel_in else "frame"
        slots, nstate = {}, 0
        for nid in order:
            st = defs[nid].get("state")
            if st:
                slots[nid] = nstate
                nstate += len(st) if isinstance(st, (list, tuple)) else int(st)
        return order, defs, scope, src_of, slots, nstate

    def compile(self, title=None):
        """The effect as C++ text. Raises GraphError with a message worth
        showing when the graph cannot be compiled."""
        if any(n["type"].startswith(SUB) for n in self.nodes.values()):
            return self.flatten().compile(title or self.name)
        title = title or self.name
        ident = _ident(title)
        outs = [n for n in self.nodes.values() if n["type"] == "Output"]
        if not outs:
            # a sub-graph previewed on its own: its first colour output is
            # what the LEDs show, so it can be built and watched in place
            gouts = [n for n in self.nodes.values()
                     if n["type"] == "Graph output" and n["params"].get("type", "float") == "color"]
            if gouts:
                src = next(((a, o) for a, o, b, i in self.links if b == gouts[0]["id"]), None)
                if src:
                    prev = Graph(self.to_json(), lib=self.lib, resolver=self.resolver)
                    o = prev.add("Output", gouts[0]["pos"])
                    prev.link(src[0], src[1], o, "color")
                    return prev.compile(title)
        if len(outs) != 1:
            raise GraphError("the graph needs exactly one Output node" + (f" (it has {len(outs)})" if outs else ""))
        defs = {nid: self.node_def(n) for nid, n in self.nodes.items()}
        order = [nid for nid in self._order() if not defs[nid].get("decor")]
        src_of = {(b, inp): (a, out) for a, out, b, inp in self.links}
        for nid, d in defs.items():
            w = d.get("wired")
            if w and (nid, w[0]) not in src_of:
                raise GraphError(f"{d['name']} #{nid}: {w[0]} must be wired from {w[1]}")

        # scope: frame nodes, then anything hoistable whose inputs are all frame
        scope = {}
        for nid in order:
            d = defs[nid]
            ups = [src_of[(nid, i["name"])][0] for i in d["inputs"] if (nid, i["name"]) in src_of]
            per_pixel_in = any(scope.get(u) == "pixel" for u in ups)
            if d.get("late") and per_pixel_in:
                raise GraphError(f"{d['name']} #{nid} remembers one value for the next frame, so its input "
                                 f"cannot come from a per-pixel node")
            if d["scope"] == "frame":
                # a frame node fed a per-pixel value follows it down, unless it
                # keeps state - one value for the whole effect cannot be per pixel
                if per_pixel_in and d.get("state"):
                    raise GraphError(f"{d['name']} #{nid} keeps one value per frame, so its inputs "
                                     f"cannot come from a per-pixel node (Coords, Noise...)")
                scope[nid] = "pixel" if per_pixel_in else "frame"; continue
            # the template's own words decide, not its pins: a pin called v or r
            # is not the pixel's v or r
            bare = re.sub(r"\$(in|out|p|st)\.[\w ]+", "", d["code"])
            if PIXEL_NAMES.search(bare) or d.get("codegen"):
                scope[nid] = "pixel"; continue
            scope[nid] = "pixel" if per_pixel_in else "frame"

        def var(nid, out):
            return f"n{nid}_{re.sub(r'[^A-Za-z0-9]', '_', out)}"

        # Persistent state: a node's definition names how many floats it keeps
        # between frames ("state": ["acc"] or "state": 16). They live in one
        # array in SEGENV.data; $st.name and $st[k] address a node's own slots.
        slots, nstate = {}, 0
        for nid in order:
            st = defs[nid].get("state")
            if st:
                slots[nid] = nstate
                nstate += len(st) if isinstance(st, (list, tuple)) else int(st)
        # Fields: a float per pixel kept between frames, double-buffered (read
        # last frame's, write this frame's), as many as the Field nodes name.
        nfields = 0
        for nid in order:
            names = defs[nid].get("fields") or (["field"] if defs[nid].get("field") else [])
            for pn in names:
                nfields = max(nfields, int(self.nodes[nid]["params"].get(pn, 0)) + 1)

        def expand(nid, late=False):
            n = self.nodes[nid]; d = defs[nid]
            code = d["late_code"] if late else d["code"]
            if n.get("muted") and not late:
                # bypassed: each output takes the first input of its type, else nothing
                parts = []
                for o in d["outputs"]:
                    src = next((i for i in d["inputs"] if i["type"] == o["type"]), None)
                    if src is None:
                        src = next((i for i in d["inputs"] if compatible(i["type"], o["type"])), None)
                    if src is not None:
                        parts.append(f"$out.{o['name']} = $in.{src['name']};")
                code = " ".join(parts) or "/* muted */"
                d = dict(d, state=None, fields=None, field=None, codegen=None)
            elif d.get("codegen") and not late:
                try:
                    code = CODEGEN[d["codegen"]](n, getattr(self, "project_dir", None))
                except Exception as e:
                    raise GraphError(f"{d['name']} #{nid}: {e}")
            # inputs
            for i in d["inputs"]:
                key = (nid, i["name"])
                if key in src_of:
                    a, out = src_of[key]
                    ad = defs[a]
                    at = next((o["type"] for o in ad["outputs"] if o["name"] == out), None)
                    if at is None:
                        raise GraphError(f"node {a} has no output {out!r}")
                    try:
                        expr = _coerce(var(a, out), at, i["type"])
                    except GraphError:
                        raise GraphError(f"{d['name']} #{nid}: {i['name']} cannot take a {at} (from {ad['name']} #{a})")
                else:
                    # the value typed on the node stands in for the wire
                    v = n.get("inputs", {}).get(i["name"], i.get("default", 0))
                    expr = _lit(i["type"], v)
                code = _sub(code, "in", i["name"], expr)
            for o in d["outputs"]:
                code = _sub(code, "out", o["name"], var(nid, o["name"]))
            for p in d["params"]:
                v = n["params"].get(p["name"], p["default"])
                if p["type"] == "color":
                    rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
                    for k, c in zip("rgb", rgb):
                        code = _sub(code, "p", f"{p['name']}_{k}", str(int(c)))
                elif p["type"] in ("text", "file"):
                    code = _sub(code, "p", p["name"], str(v).replace('"', "'"))
                elif p["type"] in ("ramp", "curve"):
                    pass                                      # the codegen reads it whole
                elif p["type"] == "choice":
                    code = _sub(code, "p", p["name"], str(v))
                else:
                    code = _sub(code, "p", p["name"], _lit(p["type"], v))
            st = d.get("state")
            if st:
                base = slots[nid]
                if isinstance(st, (list, tuple)):
                    for k, name in enumerate(st):
                        code = _sub(code, "st", name, f"gc_st[{base + k}]")
                code = re.sub(r"\$st(?![.\w])", f"(gc_st + {base})", code)
            code = code.replace("$first", "gc_first")
            if "$in." in code or "$out." in code or "$p." in code or "$st." in code:
                m = re.search(r"\$(in|out|p|st)\.\w+", code)
                raise GraphError(f"node {n['type']}: template refers to unknown {m.group(0)}")
            code = code.replace("$$", "$")
            decl = "" if late else "".join(f"{TYPES[o['type']]} {var(nid, o['name'])} = {ZERO[o['type']]}; " for o in d["outputs"])
            tag = f"{n['type']} #{nid}" + (" (for next frame)" if late else "")
            return f"      // {tag}\n      {decl}\n      " + code.replace("\n", "\n      ") + "\n"

        # Probes: every number-like output reports its value to the sim -
        # frame-scope ones as they are, per-pixel ones at the centre pixel.
        # GC_PROBE is nothing in the firmware.
        self.probes = {}
        self.last_scope = dict(scope)

        def probe(nid, guard=""):
            out = ""
            for o in defs[nid]["outputs"]:
                if o["type"] in ("float", "bool", "int") and len(self.probes) < 256:
                    k = len(self.probes)
                    self.probes[k] = (nid, o["name"])
                    out += f"      {guard}GC_PROBE({k}, (float)({var(nid, o['name'])}));\n"
            return out

        frame = "".join(expand(nid) + probe(nid) for nid in order if scope[nid] == "frame")
        frame += "".join(expand(nid, late=True) for nid in order if defs[nid].get("late"))
        pixel = "".join(expand(nid) + probe(nid, "if (px == W / 2 && py == H / 2) ")
                        for nid in order if scope[nid] == "pixel")

        # metadata: slider labels from the control nodes that are present
        labels = ["", "", "", "", "", "", "", ""]
        slot = {"Speed": 0, "Intensity": 1, "Custom 1": 2, "Custom 2": 3, "Custom 3": 4,
                "Check 1": 5, "Check 2": 6, "Check 3": 7}
        dkey = {"Speed": "sx", "Intensity": "ix", "Custom 1": "c1", "Custom 2": "c2", "Custom 3": "c3",
                "Check 1": "o1", "Check 2": "o2", "Check 3": "o3"}
        defaults = {"sx": 128, "ix": 128}
        for n in self.nodes.values():
            if n["type"] in slot:
                labels[slot[n["type"]]] = str(n["params"].get("label", n["type"])).replace(",", " ").replace(";", " ")
                if "default" in n["params"]:
                    v = n["params"]["default"]
                    defaults[dkey[n["type"]]] = int(bool(v)) if isinstance(v, bool) else int(v)
        settings = next((n["params"] for n in self.nodes.values() if n["type"] == "Effect settings"), {})
        defaults["pal"] = int(settings.get("palette", 11))
        dims = {"both": "12", "1-D": "1", "2-D": "2"}.get(str(settings.get("dimensions", "both")), "12")
        aud = {"volume": "v", "frequency": "f"}.get(str(settings.get("audio", "none")), "")
        cols = str(settings.get("colours", "")).replace(";", " ")
        meta = (f'{title.replace(chr(34), chr(39))}@{",".join(labels)};{cols};!;{dims}{aud};'
                + ",".join(f"{k}={v}" for k, v in defaults.items()))

        state = ""
        if nstate or nfields:
            state = (f"  // --- state kept between frames: {nstate} floats, {nfields} field(s) of N ------\n"
                     f"  const bool gc_first = (SEGENV.call == 0);\n"
                     f"  float *gc_st = nullptr;\n"
                     f"  if (SEGENV.allocateData(({nstate} + 2 * {nfields} * N) * sizeof(float))) gc_st = (float *)SEGENV.data;\n")
            if nfields:
                state += "  if (!gc_st) { SEGMENT.fill(0); FX_DONE; }   // no room for the fields\n"
                for k in range(nfields):
                    state += (f"  float *gc_fr{k} = gc_st + {nstate} + (2 * {k} + (SEGENV.call & 1)) * N;\n"
                              f"  float *gc_fw{k} = gc_st + {nstate} + (2 * {k} + ((SEGENV.call + 1) & 1)) * N;\n"
                              f"  if (gc_first) memset(gc_fr{k}, 0, N * sizeof(float));\n")
            elif nstate <= 64:
                # A few floats: a static fallback keeps the effect running
                # when the segment has no room. More would be DRAM spent for
                # every effect in the build whether it runs or not - the
                # firmware would not link with two of the big ones.
                state += f"  static float gc_st_fallback[{max(1, nstate)}]; if (!gc_st) gc_st = gc_st_fallback;\n"
            else:
                state += "  if (!gc_st) { SEGMENT.fill(0); FX_DONE; }   // no room for the state\n"
            state += "  (void)gc_first;\n"
        return GENERATED.format(title=title, ident=ident, upper=ident.upper(), helpers=HELPERS,
                                frame=frame, pixel=pixel, meta=meta, state=state)


GENERATED = r'''#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"
#ifdef CFX_SIM
extern "C" void simProbeSet(int i, float v);    // the studio reads pin values back (sim only)
#define GC_PROBE(i, v) simProbeSet((i), (v))
#else
#define GC_PROBE(i, v) ((void)0)
#endif

// ===========================================================================
// {title} - generated by the WLED Effects Studio node editor
// ===========================================================================
// An ordinary effect: drop it into a usermod folder that has cube_fx_common.h
// and cube_fx_bank.h beside it and it compiles into the firmware unchanged.
// Edit the graph and regenerate, or edit this file by hand from here on.
// ===========================================================================
{helpers}
static FX_RET mode_{ident}() {{
  if (!strip.isMatrix && !SEGMENT.is2D() && SEGLEN < 1) {{ FX_DONE; }}
  const bool is2d = SEGMENT.is2D();
  const int W = is2d ? SEG_W : SEGLEN, H = is2d ? SEG_H : 1;
  const int N = W * H;
  const bool cube = is2d && cfx_isCube(W, H);
  const int  B    = cube ? (W / 3) : 1;
  static uint8_t clk_[2] = {{0, 0}};
  const uint16_t dt = fx_dt8(clk_);
  const float t = (float)strip.now * 0.001f;
  (void)N; (void)dt; (void)t;
{state}
  // --- frame scope -----------------------------------------------------------
{frame}
  // --- per pixel ---------------------------------------------------------------
  const int cols = W, rows = H; (void)rows;          // the net-skip macros' names
  CFX_NET_PREP();
  for (int py = 0; py < H; py++) {{
    CFX_NET_ROW(py);
    for (int px = 0; px < W; px++) {{
      CFX_NET_SKIP(px);
      const float u = (W > 1) ? (float)px / (float)(W - 1) : 0.5f;
      const float v = (H > 1) ? (float)py / (float)(H - 1) : 0.5f;
      const float cx = u * 2.0f - 1.0f, cy = 1.0f - v * 2.0f;
      const float r = sqrtf(cx * cx + cy * cy);
      const float ang = cfx_atan2f(cy, cx);
      float nx, ny, nz, X3, Y3, Z3;                 // direction (unit) and position (-1..1 box)
      if (cfx_geomFor(W, H)) {{                      // a shape table: the real positions and normals
        cfx_pos(px, py, W, H, B, false, X3, Y3, Z3);
        cfx_geomNormal(px, py, W, X3, Y3, Z3, nx, ny, nz);
      }} else if (cube) {{
        cfx_pos(px, py, W, H, B, true, X3, Y3, Z3);
        const float L = sqrtf(X3 * X3 + Y3 * Y3 + Z3 * Z3); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
        nx = X3 * iL; ny = Y3 * iL; nz = Z3 * iL;
      }} else {{
        X3 = cx; Y3 = cy; Z3 = 0.0f;
        const float Z = 1.0f - (cx * cx + cy * cy) * 0.5f;
        const float L = sqrtf(cx * cx + cy * cy + Z * Z); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
        nx = cx * iL; ny = cy * iL; nz = Z * iL;
      }}
      int part, nparts; float along;                 // the shape's part this pixel is in (0 of 1 without a shape table)
      cfx_geomPartOf(px, py, W, part, along, nparts);
      (void)u; (void)v; (void)r; (void)ang; (void)nx; (void)ny; (void)nz; (void)X3; (void)Y3; (void)Z3; (void)part; (void)along; (void)nparts;
      uint32_t gc_out = 0;
{pixel}
      if (is2d) SEGMENT.setPixelColorXY(px, py, gc_out); else SEGMENT.setPixelColor(px, gc_out);
    }}
  }}
  FX_DONE;
}}

static const char _data_FX_MODE_{upper}[] PROGMEM = "{meta}";
static CfxBankReg {ident}_reg(&mode_{ident}, _data_FX_MODE_{upper});
'''


# Pins that became one vector pin: (node type, old float pin) -> (vector pin, component).
# A saved graph that wired the three floats gets a Vector node put in for them.
MIGRATE = {}
for _t, _v, _pins in (("Dot 3", "a", ("ax", "ay", "az")), ("Dot 3", "b", ("bx", "by", "bz")),
                      ("Length", "v", ("x", "y", "z")), ("Mirror fold", "v", ("x", "y", "z")),
                      ("Torus knot", "dir", ("nx", "ny", "nz")), ("Shells", "pos", ("x", "y", "z")),
                      ("Emitters", "pos", ("x", "y", "z")), ("Position to uv", "pos", ("x", "y", "z"))):
    for _c, _p in zip("xyz", _pins):
        MIGRATE[(_t, _p)] = (_v, _c)
MIGRATE_OUT = {("Mirror fold", "x"): ("v", "x"), ("Mirror fold", "y"): ("v", "y"), ("Mirror fold", "z"): ("v", "z")}


def migrate(g):
    """Rewire a graph saved before the vector type: three float wires into
    what is now one vector pin go through a Vector node; a float read from
    what is now a vector output goes through a Vector split."""
    if "Vector" not in g.lib:
        return g
    joins, splits = {}, {}
    new_links = []
    for a, o, b, i in list(g.links):
        bt = g.nodes.get(b, {}).get("type"); at = g.nodes.get(a, {}).get("type")
        if (bt, i) in MIGRATE:
            vpin, comp = MIGRATE[(bt, i)]
            key = (b, vpin)
            if key not in joins:
                pos = g.nodes[b]["pos"]
                joins[key] = g.add("Vector", (pos[0] - 190, pos[1] + 40 * len(joins)))
                g.nodes[b]["inputs"].pop(vpin, None)
                new_links.append((joins[key], "v", b, vpin))
            if (at, o) in MIGRATE_OUT:
                svpin, scomp = MIGRATE_OUT[(at, o)]
                skey = (a, svpin)
                if skey not in splits:
                    pos = g.nodes[a]["pos"]
                    splits[skey] = g.add("Vector split", (pos[0] + 190, pos[1]))
                    new_links.append((a, svpin, splits[skey], "v"))
                new_links.append((splits[skey], scomp, joins[key], comp))
            else:
                new_links.append((a, o, joins[key], comp))
        elif (at, o) in MIGRATE_OUT:
            svpin, scomp = MIGRATE_OUT[(at, o)]
            skey = (a, svpin)
            if skey not in splits:
                pos = g.nodes[a]["pos"]
                splits[skey] = g.add("Vector split", (pos[0] + 190, pos[1]))
                new_links.append((a, svpin, splits[skey], "v"))
            new_links.append((splits[skey], scomp, b, i))
        else:
            new_links.append((a, o, b, i))
    # unwired old float pins with typed values: fold them into the Vector node's inputs
    for nid, n in list(g.nodes.items()):
        t = n["type"]
        for pin, val in list(n.get("inputs", {}).items()):
            if (t, pin) in MIGRATE:
                vpin, comp = MIGRATE[(t, pin)]
                key = (nid, vpin)
                if key not in joins:
                    cur = n["inputs"].get(vpin)
                    v = list(cur) if isinstance(cur, (list, tuple)) else [0.0, 0.0, 0.0]
                    v["xyz".index(comp)] = float(val)
                    n["inputs"][vpin] = v
                else:
                    g.nodes[joins[key]]["inputs"][comp] = float(val)
                n["inputs"].pop(pin, None)
    g.links = new_links
    return g


def load(path, lib=None, resolver=None):
    return migrate(Graph(json.load(open(path, encoding="utf-8")), lib=lib, resolver=resolver))


def save(graph, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph.to_json(), f, indent=1)


def starter(name="New Graph", lib=None, resolver=None):
    """The graph a new file starts as: a palette gradient scrolled by Speed,
    so there is something on the LEDs the moment it compiles."""
    g = Graph({"name": name}, lib=lib, resolver=resolver)
    sp = g.add("Speed", (40, 40))
    tm = g.add("Time", (40, 140))
    mul = g.add("Multiply", (260, 90))
    co = g.add("Coords", (40, 260))
    ad = g.add("Add", (460, 180))
    pal = g.add("Palette", (660, 180))
    out = g.add("Output", (860, 180))
    g.link(sp, "value", mul, "a"); g.link(tm, "t", mul, "b")
    g.link(co, "u", ad, "a"); g.link(mul, "result", ad, "b")
    g.link(ad, "result", pal, "index")
    g.link(pal, "color", out, "color")
    return g
