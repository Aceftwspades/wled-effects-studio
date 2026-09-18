"""The scripted runtime's compiler: a graph to bytecode for the Studio
Script effect (usermods/cube_fx/cube_fx_98_script.cpp), which runs it on
the device from a file sent over the network - no firmware build.

The node library's templates are C. This is a compiler for the subset they
use: expressions over floats, colours and 3-vectors, calls into a table of
known functions, if/else and ternaries, local declarations, assignments to
outputs and state. Constant parameters are folded, so a node's `if
(!strcmp("$p.mode", "add"))` chain becomes one branch; an `if` on a live
value becomes a select of both sides. A node the subset cannot express -
loops, per-pixel fields, the codegen nodes, Expression - makes the graph
"not scriptable", with the node named.

    prog = compile_script(graph)     # bytes, or ScriptError(node, why)

Registers: F[] floats, C[] colours (uint32). The first 48 floats are the
VM's own each pixel (u, v, cx, cy, r, ang, px, py, W, H, N, t, dt, the
sliders, the checks, volume, beat, first, X3 Y3 Z3, the sixteen bands...);
programs use the rest. State is a float array the VM keeps between frames.
Bytecode: op u8, then u16 register operands or an f32 immediate.
"""
import re
import struct

from native.graph import GraphError, SUB


class ScriptError(GraphError):
    pass


# --- the VM's fixed registers ------------------------------------------------------
FIXED = ["u", "v", "cx", "cy", "r", "ang", "px", "py", "W", "H", "N", "t", "dt",
         "sx", "ix", "c1", "c2", "c3", "o1", "o2", "o3", "vol", "beat", "first",
         "X3", "Y3", "Z3", "nx", "ny", "nz", "B", "cube", "hit", "bass", "mid", "treb", "call"]
FIXED_INDEX = {n: i for i, n in enumerate(FIXED)}
BAND0 = 36                                   # 16 bands follow
USER0 = 56                                   # programs allocate from here

OPS = {                                      # name: (code, operands) f=float reg, c=colour reg, i=u16 int, k=f32 immediate
    "END": (0, ""), "CONST": (1, "fk"), "MOV": (2, "ff"),
    "ADD": (3, "fff"), "SUB": (4, "fff"), "MUL": (5, "fff"), "DIV": (6, "fff"), "MIN": (7, "fff"), "MAX": (8, "fff"),
    "POW": (9, "fff"), "MOD": (10, "fff"), "ATAN2": (11, "fff"),
    "ABS": (12, "ff"), "FLOOR": (13, "ff"), "FRACT": (14, "ff"), "SIN": (15, "ff"), "COS": (16, "ff"), "SQRT": (17, "ff"),
    "EXP": (18, "ff"), "LOG": (19, "ff"), "SAT": (20, "ff"), "SIGN": (21, "ff"), "ROUND": (22, "ff"), "NOT": (23, "ff"),
    "TAN": (24, "ff"), "TRUNC": (25, "ff"), "CEIL": (26, "ff"),
    "LT": (27, "fff"), "LE": (28, "fff"), "GT": (29, "fff"), "GE": (30, "fff"), "EQ": (31, "fff"), "NE": (32, "fff"),
    "AND": (33, "fff"), "OR": (34, "fff"),
    "SEL": (35, "ffff"),
    "NOISE": (36, "ffff"), "HASH": (37, "ffff"), "FBM": (38, "fffffff"),
    "PAL": (39, "cff"), "HSV": (40, "cfff"), "RGB": (41, "cfff"), "CR": (42, "fc"), "CG": (43, "fc"), "CB": (44, "fc"),
    "CMIX": (45, "cccf"), "CSCALE": (46, "ccf"), "CADD": (47, "ccc"), "CMUL": (48, "ccc"), "CMAX": (49, "ccc"),
    "CMIN": (50, "ccc"), "CSEL": (51, "cfcc"), "SEGCOL": (52, "ci"), "CMOV": (53, "cc"), "CCONST": (54, "ci"),
    "OUT": (55, "c"), "STLD": (56, "fi"), "STST": (57, "if"), "RND": (58, "f"), "BLEND": (59, "cccfi"),
    "RINGUV": (60, "ffff"), "POSUV": (61, "fffff"), "FOLD": (62, "ffffffi"), "KNOT": (63, "ffffffffffffff"),
    "MANDEL": (64, "ffffff"), "EASE": (65, "fff"), "LOUDEST": (66, "ffii"),
}
# how many leading operands an op writes (the rest it reads), and the ops
# that are not a pure function of their operands
DESTS = {"END": 0, "OUT": 0, "STST": 0, "RINGUV": 2, "POSUV": 2, "FOLD": 3, "KNOT": 6, "LOUDEST": 2}
IMPURE = {"END", "OUT", "STST", "STLD", "RND", "LOUDEST"}
# the fixed registers that change from pixel to pixel; the rest hold for a frame
PIXEL_FIXED = {FIXED_INDEX[n] for n in ("u", "v", "cx", "cy", "r", "ang", "px", "py", "X3", "Y3", "Z3", "nx", "ny", "nz")}
MAGIC = b"STUV"
VERSION = 1


class Asm:
    """Two op streams (frame, pixel) and the register books.

    Registers are written once (every op's destination is fresh), so a
    constant is one register set once per frame in the frame stream and
    read from either stream after: 0.5 costs a CONST once, not once per
    node per pixel."""
    def __init__(self):
        self.frame, self.pixel = [], []
        self.nf, self.nc = USER0, 0
        self.stream = self.pixel
        self._consts = {}                            # value -> register
        self.made = {}                               # float register -> the op that set it

    def freg(self):
        self.nf += 1
        return self.nf - 1

    def creg(self):
        self.nc += 1
        return self.nc - 1

    def emit(self, op, *args):
        self.stream.append((op, args))
        if args and DESTS.get(op, 1) == 1 and OPS[op][1][0] == "f":
            self.made[args[0]] = op                  # which op wrote a float register, for the peepholes

    def const(self, k):
        k = float(k)
        r = self._consts.get(k)
        if r is None:
            r = self._consts[k] = self.freg()
            self.frame.append(("CONST", (r, k)))
        return r

    def hoist(self):
        """Loop-invariant code motion: a pixel-stream op whose sources all
        hold for the whole frame (constants, sliders, time, frame-stream
        results) moves to the frame stream and runs once instead of once
        per pixel. Sound because every register is written once and the
        frame stream runs first; a node's `speed / 255 * 4` goes."""
        pixel = set(PIXEL_FIXED)                 # ("f", n) as plain n; colours as ("c", n)
        kept = []
        for op, args in self.pixel:
            code, kinds = OPS[op]
            nd = DESTS.get(op, 1)
            srcs = [(k, int(a)) for k, a in list(zip(kinds, args))[nd:] if k in "fc"]
            dsts = [(k, int(a)) for k, a in list(zip(kinds, args))[:nd]]
            movable = op not in IMPURE and not any((n if k == "f" else ("c", n)) in pixel for k, n in srcs)
            if movable:
                self.frame.append((op, args))
            else:
                kept.append((op, args))
                for k, n in dsts:
                    pixel.add(n if k == "f" else ("c", n))
        self.pixel = kept

    def encode(self, nstate):
        self.hoist()
        def ops(stream):
            out = bytearray()
            for op, args in stream:
                code, kinds = OPS[op]
                out.append(code)
                for kind, a in zip(kinds, args):
                    if kind == "k":
                        out += struct.pack("<f", float(a))
                    else:
                        out += struct.pack("<H", int(a) & 0xFFFF)
            out.append(0)
            return bytes(out)
        f, p = ops(self.frame), ops(self.pixel)
        head = MAGIC + struct.pack("<BHHHII", VERSION, self.nf, max(1, self.nc), nstate, len(f), len(p))
        return head + f + p


# --- the C subset: tokens, expressions, statements ----------------------------------
TOK = re.compile(r"""\s*(?:
    (?P<num>0[xX][0-9a-fA-F]+[uUlL]*|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[fFuUlL]*) |
    (?P<str>"(?:[^"\\]|\\.)*") | (?P<chr>'(?:[^'\\]|\\.)') |
    (?P<id>[A-Za-z_][A-Za-z0-9_]*) |
    (?P<op>\+=|-=|\*=|/=|==|!=|<=|>=|&&|\|\||->|[-+*/%!<>=?:()\[\]{},;.&|^~])
)""", re.X)


def tokenize(src):
    out, i = [], 0
    src = src.replace("\r", "")
    while i < len(src):
        m = TOK.match(src, i)
        if not m or m.end() == i:
            if src[i:].strip() == "":
                break
            raise ScriptError(f"cannot read {src[i:i + 20]!r}")
        i = m.end()
        kind = m.lastgroup
        if kind is None:
            continue
        text = m.group(kind)
        if kind == "num":
            t = text.rstrip("fFuUlL")
            val = float(int(t, 16)) if t.lower().startswith("0x") else float(t)
            out.append(("num", val))
        elif kind == "str":
            out.append(("str", bytes(text[1:-1], "utf-8").decode("unicode_escape")))
        elif kind == "chr":
            out.append(("num", float(ord(bytes(text[1:-1], "utf-8").decode("unicode_escape")))))
        elif kind == "id":
            out.append(("id", text))
        else:
            out.append(("op", text))
    out.append(("eof", None))
    return out


CASTS = {"float", "int", "uint8_t", "uint16_t", "uint32_t", "int32_t", "unsigned", "bool", "const"}
DECL_TYPES = {"float", "int", "uint8_t", "uint16_t", "uint32_t", "bool", "const", "char", "GcVec", "unsigned", "static"}
BIN_PREC = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("+", "-"), ("*", "/", "%")]


class Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def accept(self, kind, val=None):
        tok = self.peek()
        if tok[0] == kind and (val is None or tok[1] == val):
            self.i += 1
            return tok
        return None

    def expect(self, kind, val=None):
        tok = self.accept(kind, val)
        if tok is None:
            raise ScriptError(f"expected {val or kind}, got {self.peek()[1]!r}")
        return tok

    # statements -> a list of ("block", [...]) / ("if", cond, then, else) / ("decl", type, name, expr)
    #               / ("assign", op, target, expr) / ("expr", expr)
    def block(self):
        out = []
        while self.peek()[0] != "eof" and not (self.peek()[0] == "op" and self.peek()[1] == "}"):
            st = self.statement()
            if st is not None:
                out.append(st)
        return ("block", out)

    def statement(self):
        tok = self.peek()
        if tok == ("op", ";"):
            self.take(); return None
        if tok == ("op", "{"):
            self.take(); b = self.block(); self.expect("op", "}"); return b
        if tok == ("id", "if"):
            self.take(); self.expect("op", "("); cond = self.expr(); self.expect("op", ")")
            then = self.statement()
            els = None
            if self.accept("id", "else"):
                els = self.statement()
            return ("if", cond, then, els)
        if tok == ("id", "for") or tok == ("id", "while"):
            raise ScriptError("a loop")
        if tok[0] == "id" and tok[1] in DECL_TYPES:
            # a declaration: qualifiers and type words, then name [= expr] {, name [= expr]}
            static = False
            while self.peek()[0] == "id" and self.peek()[1] in DECL_TYPES:
                static = static or self.take()[1] == "static"
            while self.accept("op", "*"):
                pass
            decls = []
            while True:
                name = self.expect("id")[1]
                if self.accept("op", "["):
                    raise ScriptError("an array")
                init = self.expr() if self.accept("op", "=") else None
                decls.append(("static", name, init) if static else ("decl", name, init))
                if not self.accept("op", ","):
                    break
            self.expect("op", ";")
            return ("block", decls)
        e = self.expr()
        if self.peek()[0] == "op" and self.peek()[1] in ("=", "+=", "-=", "*=", "/="):
            op = self.take()[1]
            rhs = self.expr()
            self.expect("op", ";")
            return ("assign", op, e, rhs)
        self.expect("op", ";")
        return ("expr", e)

    # expressions
    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.binary(0)
        if self.accept("op", "?"):
            a = self.expr(); self.expect("op", ":"); b = self.ternary()
            return ("?", c, a, b)
        return c

    def binary(self, level):
        if level >= len(BIN_PREC):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in BIN_PREC[level]:
            op = self.take()[1]
            right = self.binary(level + 1)
            left = ("bin", op, left, right)
        return left

    def unary(self):
        tok = self.peek()
        if tok[0] == "op" and tok[1] in ("-", "!", "+", "~", "*", "&"):
            self.take()
            return ("un", tok[1], self.unary())
        # a cast: ( type words ) unary
        if tok == ("op", "(") and self.peek(1)[0] == "id" and self.peek(1)[1] in CASTS:
            j = self.i + 1
            while self.t[j][0] == "id" and self.t[j][1] in CASTS | {"unsigned", "signed", "long", "short", "char"}:
                j += 1
            while self.t[j] == ("op", "*"):
                j += 1
            if self.t[j] == ("op", ")"):
                types = [self.t[k][1] for k in range(self.i + 1, j) if self.t[k][0] == "id"]
                self.i = j + 1
                return ("cast", types, self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.accept("op", "("):
                args = []
                if not self.accept("op", ")"):
                    while True:
                        args.append(self.expr())
                        if self.accept("op", ")"):
                            break
                        self.expect("op", ",")
                e = ("call", e, args)
            elif self.accept("op", "["):
                idx = self.expr(); self.expect("op", "]")
                e = ("index", e, idx)
            elif self.accept("op", ".") or self.accept("op", "->"):
                e = ("member", e, self.expect("id")[1])
            else:
                return e

    def primary(self):
        tok = self.take()
        if tok[0] == "num":
            return ("k", tok[1])
        if tok[0] == "str":
            return ("s", tok[1])
        if tok[0] == "id":
            return ("id", tok[1])
        if tok == ("op", "("):
            e = self.expr(); self.expect("op", ")")
            return e
        raise ScriptError(f"unexpected {tok[1]!r}")


# --- values ---------------------------------------------------------------------------
# ("k", float) a constant; ("s", str) a constant string; ("f", reg) a float in a
# register; ("c", reg) a colour; ("v", (r, r, r)) a vector; ("p", (base, is_const)) a
# pointer-ish (unsupported beyond the few helpers that take one).
class Lower:
    """Lowers one node's statements into ops against an environment."""
    FUN1 = {"sinf": "SIN", "cosf": "COS", "tanf": "TAN", "sqrtf": "SQRT", "fabsf": "ABS", "floorf": "FLOOR",
            "ceilf": "CEIL", "expf": "EXP", "logf": "LOG", "gc_sat": "SAT", "gc_fract": "FRACT", "roundf": "ROUND",
            "cfx_sinf16": "SIN", "cfx_cosf16": "COS", "sin": "SIN", "cos": "COS", "sqrt": "SQRT", "fabs": "ABS",
            "floor": "FLOOR", "truncf": "TRUNC"}
    FUN2 = {"fminf": "MIN", "fmaxf": "MAX", "powf": "POW", "fmodf": "MOD", "atan2f": "ATAN2", "cfx_atan2f": "ATAN2",
            "fmin": "MIN", "fmax": "MAX", "pow": "POW", "fmod": "MOD"}
    BLENDS = {"gc_blend_over": 0, "gc_blend_add": 1, "gc_blend_multiply": 2, "gc_blend_screen": 3, "gc_blend_max": 4,
              "gc_blend_min": 5, "gc_blend_overlay": 6, "gc_blend_difference": 7, "gc_blend_softlight": 8,
              "gc_blend_hue": 9, "gc_blend_saturation": 10, "gc_blend_colour": 11, "gc_blend_luminosity": 12}

    def __init__(self, asm, env, node_label, alloc_state=None):
        self.asm = asm
        self.env = env                        # name -> value
        self.label = node_label
        self.alloc_state = alloc_state        # () -> a state slot, for statics
        self.statics = []                     # (name, slot) to write back at the end

    def fail(self, why):
        raise ScriptError(f"{self.label}: {why}")

    # -- helpers ----------------------------------------------------------------------
    def to_f(self, v):
        """A float register (constants get one)."""
        if v[0] == "f":
            return v[1]
        if v[0] == "k":
            return self.asm.const(v[1])
        if v[0] == "v":
            return v[1][0]
        if v[0] == "c":
            self.fail("a colour where a number is needed")
        self.fail(f"cannot use {v[0]} as a number")

    def to_c(self, v):
        if v[0] == "c":
            return v[1]
        if v[0] == "v":
            r = self.asm.creg()
            self.asm.emit("RGB", r, *[self.to_f(("f", x)) for x in v[1]])
            return r
        if v[0] == "k":
            r = self.asm.creg()
            self.asm.emit("CCONST", r, int(v[1]) & 0xFFFF)     # low half only; colours are made by RGB()/PAL
            return r
        self.fail("a number where a colour is needed")

    def to_v(self, v):
        if v[0] == "v":
            return v[1]
        if v[0] in ("f", "k"):
            r = self.to_f(v)
            return (r, r, r)
        if v[0] == "c":
            rs = tuple(self.asm.freg() for _ in range(3))
            for op, r in zip(("CR", "CG", "CB"), rs):
                self.asm.emit(op, r, v[1])
            return rs
        self.fail("cannot use that as a vector")

    def f1(self, op, a):
        if op == "TRUNC" and a[0] == "f" and self.asm.made.get(a[1]) == "TRUNC":
            return a                                   # (int)(int)x: the cast chains the templates write
        r = self.asm.freg(); self.asm.emit(op, r, self.to_f(a)); return ("f", r)

    def f2(self, op, a, b):
        if op == "DIV" and b[0] == "k" and b[1] != 0.0:
            op, b = "MUL", ("k", 1.0 / b[1])           # a divide is software on an ESP32, twice a multiply
        r = self.asm.freg(); self.asm.emit(op, r, self.to_f(a), self.to_f(b)); return ("f", r)

    # -- expressions ------------------------------------------------------------------
    def ev(self, e):
        kind = e[0]
        if kind == "k":
            return ("k", e[1])
        if kind == "s":
            return ("s", e[1])
        if kind == "id":
            name = e[1]
            if name in self.env:
                return self.env[name]
            if name in ("true",):
                return ("k", 1.0)
            if name in ("false", "nullptr", "NULL"):
                return ("k", 0.0)
            if name in ("M_PI", "PI"):
                return ("k", 3.14159265)
            self.fail(f"unknown name {name}")
        if kind == "member":
            base = self.ev(e[1]) if not (e[1][0] == "id" and e[1][1] in ("SEGMENT", "SEGENV", "strip", "um")) else ("obj", e[1][1])
            m = e[2]
            if base[0] == "obj":
                key = f"{base[1]}.{m}"
                if key in self.env:
                    return self.env[key]
                self.fail(f"{key} is not available to a script")
            if base[0] == "v" and m in ("x", "y", "z"):
                return ("f", base[1]["xyz".index(m)])
            if base[0] == "k" and m in ("x", "y", "z"):
                return base
            self.fail(f"no member .{m}")
        if kind == "index":
            base, idx = self.ev(e[1]), self.ev(e[2])
            if base[0] == "s" and idx[0] == "k":
                i = int(idx[1])
                return ("k", float(ord(base[1][i])) if i < len(base[1]) else 0.0)
            self.fail("indexing is only for constant strings")
        if kind == "un":
            op, a = e[1], self.ev(e[2])
            if op == "+":
                return a
            if a[0] == "k":
                return ("k", {"-": -a[1], "!": float(not a[1]), "~": float(~int(a[1]))}[op])
            if op == "-":
                if a[0] == "v":
                    z = self.asm.const(0.0)
                    return ("v", tuple(self.f2("SUB", ("f", z), ("f", x))[1] for x in a[1]))
                return self.f2("SUB", ("k", 0.0), a)
            if op == "!":
                return self.f1("NOT", a)
            self.fail(f"operator {op}")
        if kind == "cast":
            types, a = e[1], self.ev(e[2])
            if a[0] == "k":
                v = a[1]
                if "int" in types or "uint8_t" in types or "uint16_t" in types or "uint32_t" in types:
                    v = float(int(v))
                    if "uint8_t" in types: v = float(int(v) & 255)
                    if "uint16_t" in types: v = float(int(v) & 65535)
                return ("k", v)
            if a[0] == "c" or a[0] == "s" or a[0] == "v":
                return a
            if "uint8_t" in types:
                t = self.f1("TRUNC", a)
                return self.f2("MOD", t, ("k", 256.0))
            if "uint16_t" in types:
                t = self.f1("TRUNC", a)
                return self.f2("MOD", t, ("k", 65536.0))
            if "int" in types or "uint32_t" in types or "int32_t" in types or "unsigned" in types:
                return self.f1("TRUNC", a)
            if "bool" in types:
                return self.f2("NE", a, ("k", 0.0))
            return a
        if kind == "bin":
            return self.binop(e[1], self.ev(e[2]), self.ev(e[3]))
        if kind == "?":
            c = self.ev(e[1])
            if c[0] == "k":
                return self.ev(e[2] if c[1] else e[3])
            a, b = self.ev(e[2]), self.ev(e[3])
            return self.select(c, a, b)
        if kind == "call":
            return self.call(e[1], e[2])
        self.fail(f"cannot lower {kind}")

    def select(self, c, a, b):
        if a[0] == "c" or b[0] == "c":
            r = self.asm.creg(); self.asm.emit("CSEL", r, self.to_f(c), self.to_c(a), self.to_c(b)); return ("c", r)
        if a[0] == "v" or b[0] == "v":
            av, bv = self.to_v(a), self.to_v(b)
            cr = self.to_f(c)
            rs = []
            for x, y in zip(av, bv):
                r = self.asm.freg(); self.asm.emit("SEL", r, cr, x, y); rs.append(r)
            return ("v", tuple(rs))
        r = self.asm.freg(); self.asm.emit("SEL", r, self.to_f(c), self.to_f(a), self.to_f(b)); return ("f", r)

    def binop(self, op, a, b):
        if a[0] == "k" and b[0] == "k":
            x, y = a[1], b[1]
            try:
                v = {"+": x + y, "-": x - y, "*": x * y, "/": (x / y if y else 0.0), "%": (x % y if y else 0.0),
                     "<": float(x < y), ">": float(x > y), "<=": float(x <= y), ">=": float(x >= y),
                     "==": float(x == y), "!=": float(x != y), "&&": float(bool(x) and bool(y)),
                     "||": float(bool(x) or bool(y)), "&": float(int(x) & int(y)), "|": float(int(x) | int(y)),
                     "^": float(int(x) ^ int(y))}[op]
            except KeyError:
                self.fail(f"operator {op}")
            return ("k", v)
        if a[0] == "s" or b[0] == "s":
            self.fail("string arithmetic")
        if a[0] == "v" or b[0] == "v":
            if op in ("+", "-", "*", "/"):
                av, bv = self.to_v(a), self.to_v(b)
                opn = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}[op]
                return ("v", tuple(self.f2(opn, ("f", x), ("f", y))[1] for x, y in zip(av, bv)))
            self.fail(f"vector {op}")
        if a[0] == "c" or b[0] == "c":
            if op in ("|", "+"):
                r = self.asm.creg(); self.asm.emit("CADD", r, self.to_c(a), self.to_c(b)); return ("c", r)
            if op in ("==", "!="):
                # colours compare as packed numbers: rarely in templates; via their red for the mask nodes
                return self.f2("EQ" if op == "==" else "NE", self.f1("CR", a), self.f1("CR", b))
            self.fail(f"colour {op}")
        opn = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE",
               "==": "EQ", "!=": "NE", "&&": "AND", "||": "OR"}.get(op)
        if opn is None:
            self.fail(f"operator {op}")
        return self.f2(opn, a, b)

    def call(self, fn, args):
        if fn[0] == "member":
            base = fn[1]
            name = f"{base[1] if base[0] == 'id' else '?'}.{fn[2]}"
        elif fn[0] == "id":
            name = fn[1]
        else:
            self.fail("a call through an expression")
        if name in ("gc_ring_uv", "gc_pos_uv", "gc_fold", "gc_knot"):
            nval = {"gc_ring_uv": 6, "gc_pos_uv": 7, "gc_fold": 1, "gc_knot": 8}[name]
            A = [self.ev(a) for a in args[:nval]] + [None] * (len(args) - nval)
            return self.byref(name, args, A)
        A = [self.ev(a) for a in args]
        if name in self.FUN1 and len(A) == 1:
            if A[0][0] == "k":
                import math
                x = A[0][1]
                f = {"SIN": math.sin, "COS": math.cos, "TAN": math.tan, "SQRT": lambda v: math.sqrt(max(0.0, v)),
                     "ABS": abs, "FLOOR": math.floor, "CEIL": math.ceil, "EXP": math.exp,
                     "LOG": lambda v: math.log(v) if v > 0 else 0.0, "SAT": lambda v: min(1.0, max(0.0, v)),
                     "FRACT": lambda v: v - math.floor(v), "ROUND": round, "TRUNC": math.trunc}[self.FUN1[name]]
                return ("k", float(f(x)))
            return self.f1(self.FUN1[name], A[0])
        if name in self.FUN2 and len(A) == 2:
            return self.f2(self.FUN2[name], A[0], A[1])
        if name == "strcmp" and len(A) == 2:
            if A[0][0] == "s" and A[1][0] == "s":
                return ("k", 0.0 if A[0][1] == A[1][1] else 1.0)
            self.fail("strcmp on a live string")
        if name in ("perlin8", "inoise8") and len(A) == 3:
            # fixed-point 8.8 in, 0..255 out: the NOISE op takes units, gives 0..1
            xs = [self.f2("DIV", a, ("k", 256.0)) for a in A]
            r = self.asm.freg(); self.asm.emit("NOISE", r, *[self.to_f(x) for x in xs])
            return self.f2("MUL", ("f", r), ("k", 255.0))
        if name == "gc_fbm" and len(A) == 6:
            r = self.asm.freg(); self.asm.emit("FBM", r, *[self.to_f(a) for a in A]); return ("f", r)
        if name == "gc_hash" and len(A) == 3:
            r = self.asm.freg(); self.asm.emit("HASH", r, *[self.to_f(a) for a in A]); return ("f", r)
        if name == "gc_hsv" and len(A) == 3:
            r = self.asm.creg(); self.asm.emit("HSV", r, *[self.to_f(a) for a in A]); return ("c", r)
        if name == "RGBW32" and len(A) == 4:
            r = self.asm.creg(); self.asm.emit("RGB", r, *[self.to_f(self.f2("DIV", a, ("k", 255.0))) for a in A[:3]]); return ("c", r)
        if name == "mq_scale" and len(A) == 2:
            r = self.asm.creg(); self.asm.emit("CSCALE", r, self.to_c(A[0]), self.to_f(self.f2("DIV", A[1], ("k", 255.0)))); return ("c", r)
        if name == "SEGMENT.color_from_palette" and len(A) >= 1:
            idx = self.f2("DIV", A[0], ("k", 255.0))
            bri = self.f2("DIV", A[3], ("k", 255.0)) if len(A) >= 4 and A[3][0] != "k" else ("k", 1.0)
            if len(A) >= 4 and A[3][0] == "k" and A[3][1] != 0:
                bri = ("k", A[3][1] / 255.0)
            r = self.asm.creg(); self.asm.emit("PAL", r, self.to_f(idx), self.to_f(bri)); return ("c", r)
        if name == "SEGCOLOR" and len(A) == 1 and A[0][0] == "k":
            r = self.asm.creg(); self.asm.emit("SEGCOL", r, int(A[0][1])); return ("c", r)
        if name in self.BLENDS and len(A) == 3:
            r = self.asm.creg(); self.asm.emit("BLEND", r, self.to_c(A[0]), self.to_c(A[1]), self.to_f(A[2]), self.BLENDS[name]); return ("c", r)
        if name == "gc_v3" and len(A) == 3:
            return ("v", tuple(self.to_f(a) for a in A))
        if name == "gc_vadd" and len(A) == 2:
            return self.binop("+", ("v", self.to_v(A[0])), ("v", self.to_v(A[1])))
        if name == "gc_vsub" and len(A) == 2:
            return self.binop("-", ("v", self.to_v(A[0])), ("v", self.to_v(A[1])))
        if name == "gc_vmul" and len(A) == 2:
            return self.binop("*", ("v", self.to_v(A[0])), ("v", self.to_v(A[1])))
        if name == "gc_vscale" and len(A) == 2:
            s = self.to_f(A[1])
            return ("v", tuple(self.f2("MUL", ("f", x), ("f", s))[1] for x in self.to_v(A[0])))
        if name == "gc_vdot" and len(A) == 2:
            a, b = self.to_v(A[0]), self.to_v(A[1])
            acc = self.f2("MUL", ("f", a[0]), ("f", b[0]))
            for k in (1, 2):
                acc = self.f2("ADD", acc, self.f2("MUL", ("f", a[k]), ("f", b[k])))
            return acc
        if name == "gc_vlen" and len(A) == 1:
            return self.f1("SQRT", self.call(("id", "gc_vdot"), [args[0], args[0]]))
        if name == "gc_vnorm" and len(A) == 1:
            v = self.to_v(A[0])
            L = self.f1("SQRT", self.call(("id", "gc_vdot"), [args[0], args[0]]))
            inv = self.f2("DIV", ("k", 1.0), self.f2("MAX", L, ("k", 1e-6)))
            return ("v", tuple(self.f2("MUL", ("f", x), inv)[1] for x in v))
        if name == "gc_col2v" and len(A) == 1:
            return ("v", self.to_v(A[0]))
        if name == "gc_v2col" and len(A) == 1:
            return ("c", self.to_c(("v", self.to_v(A[0]))))
        if name == "gc_mandel" and len(A) == 5:
            r = self.asm.freg(); self.asm.emit("MANDEL", r, *[self.to_f(a) for a in A]); return ("f", r)
        if name == "gc_ease" and len(A) == 2:
            r = self.asm.freg(); self.asm.emit("EASE", r, self.to_f(A[0]), self.to_f(A[1])); return ("f", r)
        if name == "gc_rnd" and not A:
            r = self.asm.freg(); self.asm.emit("RND", r); return ("f", r)
        if name == "gc_ease" and len(A) == 2:
            self.fail("Ease's curve table")
        self.fail(f"{name}() is not available to a script")

    def byref(self, name, args, A):
        """Helpers that fill arguments passed by reference."""
        def target(e):
            return self.assign_target(e)
        if name == "gc_ring_uv" and len(A) == 8:            # (around, depth, W, H, B, cube, &u, &v)
            ru, rv = self.asm.freg(), self.asm.freg()
            self.asm.emit("RINGUV", ru, rv, self.to_f(A[0]), self.to_f(A[1]))
            self.store(target(args[6]), ("f", ru)); self.store(target(args[7]), ("f", rv))
            return ("k", 0.0)
        if name == "gc_pos_uv" and len(A) == 9:             # (X, Y, Z, W, H, B, cube, &u, &v)
            ru, rv = self.asm.freg(), self.asm.freg()
            self.asm.emit("POSUV", ru, rv, self.to_f(A[0]), self.to_f(A[1]), self.to_f(A[2]))
            self.store(target(args[7]), ("f", ru)); self.store(target(args[8]), ("f", rv))
            return ("k", 0.0)
        if name == "gc_fold" and len(A) == 4:               # (sym, &x, &y, &z): in place
            if A[0][0] != "k":
                self.fail("gc_fold with a live symmetry")
            ins = [self.ev(e) for e in args[1:4]]
            rx, ry, rz = self.asm.freg(), self.asm.freg(), self.asm.freg()
            self.asm.emit("FOLD", rx, ry, rz, self.to_f(ins[0]), self.to_f(ins[1]), self.to_f(ins[2]), int(A[0][1]))
            for e, r in zip(args[1:4], (rx, ry, rz)):
                self.store(target(e), ("f", r))
            return ("k", 0.0)
        if name == "gc_knot" and len(A) == 13:              # (nx, ny, nz, P, Q, R, r, tube, &along, &edge, &Nx, &Ny, &Nz)
            outs = [self.asm.freg() for _ in range(6)]        # on, along, edge, Nx, Ny, Nz
            self.asm.emit("KNOT", *outs, *[self.to_f(a) for a in A[:8]])
            for e, r in zip(args[8:13], outs[1:]):
                self.store(target(e), ("f", r))
            return ("f", outs[0])
        self.fail(f"{name}() with those arguments")

    # -- statements -------------------------------------------------------------------
    def assign_target(self, e):
        if e[0] == "id":
            return e[1]
        if e[0] == "member" and e[1][0] == "id" and e[2] in ("x", "y", "z"):
            return (e[1][1], e[2])
        self.fail("an assignment to something that is not a name")

    def store(self, name, val, cond=None):
        """name = val, under a condition (a select against the old value)."""
        if isinstance(name, tuple):                           # vec.x = ...
            base, comp = name
            cur = self.env.get(base)
            if not cur or cur[0] != "v":
                self.fail(f"{base}.{comp}: not a vector")
            k = "xyz".index(comp)
            new = self.to_f(val)
            if cond is not None:
                r = self.asm.freg(); self.asm.emit("SEL", r, self.to_f(cond), new, cur[1][k]); new = r
            regs = list(cur[1]); regs[k] = new
            self.env[base] = ("v", tuple(regs))
            return
        old = self.env.get(name)
        if cond is not None and old is not None:
            val = self.select(cond, val, old)
        elif cond is not None and old is None:
            val = self.select(cond, val, ("k", 0.0))
        # values are stored as registers so later reads see one thing
        if val[0] == "k":
            val = ("f", self.asm.const(val[1]))
        self.env[name] = val

    def run(self, st, cond=None):
        kind = st[0]
        if kind == "block":
            for s in st[1]:
                self.run(s, cond)
        elif kind == "decl":
            name, init = st[1], st[2]
            self.store(name, self.ev(init) if init is not None else ("k", 0.0), None)
        elif kind == "static":
            # a static local keeps its value between frames: a state slot,
            # loaded here, set to its initialiser on the first frame, written
            # back after the node's statements
            if self.alloc_state is None:
                self.fail("a static variable")
            name, init = st[1], st[2]
            slot = self.alloc_state()
            loaded = self.asm.freg(); self.asm.emit("STLD", loaded, slot)
            first = self.env.get("gc_first", ("k", 0.0))
            val = self.select(first, self.ev(init) if init is not None else ("k", 0.0), ("f", loaded))
            self.store(name, val, None)
            self.statics.append((name, slot))
        elif kind == "assign":
            op, target, rhs = st[1], self.assign_target(st[2]), self.ev(st[3])
            if op != "=":
                cur = self.env.get(target) if not isinstance(target, tuple) else ("f", self.env[target[0]][1]["xyz".index(target[1])])
                if cur is None:
                    self.fail(f"{target} used before it is set")
                rhs = self.binop(op[0], cur, rhs)
            self.store(target, rhs, cond)
        elif kind == "if":
            c = self.ev(st[1])
            if c[0] == "k":
                branch = st[2] if c[1] else st[3]
                if branch is not None:
                    self.run(branch, cond)
                return
            both = c if cond is None else self.f2("AND", cond, c)
            self.run(st[2], both)
            if st[3] is not None:
                notc = self.f1("NOT", c)
                self.run(st[3], notc if cond is None else self.f2("AND", cond, notc))
        elif kind == "expr":
            self.ev(st[1])


# --- the graph ------------------------------------------------------------------------
def _lit(t, v):
    if t == "color":
        rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
        return ("k3", [float(c) / 255.0 for c in rgb])
    if t == "vector":
        vv = list(v)[:3] if isinstance(v, (list, tuple)) else [float(v)] * 3
        return ("k3", [float(c) for c in vv])
    if t == "bool":
        return ("k", 1.0 if v else 0.0)
    return ("k", float(v))


def _preprocess(code):
    """#ifdef / #ifndef / #else / #endif on the template's own lines, with
    nothing defined - a script has no IMU, no build flags."""
    out, keep, stack = [], True, []
    for line in code.split("\n"):
        t = line.strip()
        if t.startswith("#ifdef") or t.startswith("#if "):
            stack.append(keep); keep = False; continue
        if t.startswith("#ifndef"):
            stack.append(keep); continue
        if t.startswith("#else"):
            keep = (stack[-1] if stack else True) and not keep; continue
        if t.startswith("#endif"):
            keep = stack.pop() if stack else True; continue
        if t.startswith("#"):
            continue
        if keep:
            out.append(line)
    return "\n".join(out)


def compile_script(graph):
    """The graph as bytecode for the Studio Script effect. ScriptError names
    the first node the subset cannot express."""
    if any(n["type"].startswith(SUB) for n in graph.nodes.values()):
        return compile_script(graph.flatten())
    outs = [n for n in graph.nodes.values() if n["type"] == "Output"]
    if len(outs) != 1:
        raise ScriptError("the graph needs exactly one Output node")
    order, defs, scope, src_of, slots, nstate = graph.plan()
    asm = Asm()
    values = {}                                   # (nid, out) -> value
    extra = [nstate]                              # state slots for static locals

    def alloc_state():
        extra[0] += 1
        return extra[0] - 1

    def fixed(name):
        return ("f", FIXED_INDEX[name])

    # The names every node's code can use: the fixed registers, and the
    # sliders in WLED's 0..255 units, made once a frame in the frame stream
    # and shared by every node (they used to be remade per node, per pixel).
    shared = {k: fixed(k) for k in FIXED}
    shared["dt"] = fixed("dt")
    shared["gc_first"] = fixed("first")
    shared["SEGENV.call"] = fixed("call")
    for k, name in (("o1", "check1"), ("o2", "check2"), ("o3", "check3")):
        shared[f"SEGMENT.{name}"] = fixed(k)
    asm.stream = asm.frame
    for k, name, scale in (("sx", "SEGMENT.speed", 255.0), ("ix", "SEGMENT.intensity", 255.0), ("c1", "SEGMENT.custom1", 255.0),
                           ("c2", "SEGMENT.custom2", 255.0), ("c3", "SEGMENT.custom3", 31.0), ("t", "strip.now", 1000.0)):
        r = asm.freg(); asm.emit("MUL", r, FIXED_INDEX[k], asm.const(scale)); shared[name] = ("f", r)

    for nid in order:
        n, d = graph.nodes[nid], defs[nid]
        label = f"{d.get('label') or n['type']} #{nid}"
        if d.get("codegen") or d.get("field") or d.get("fields"):
            raise ScriptError(f"{label}: not scriptable ({'per-pixel fields' if not d.get('codegen') else 'a table the device cannot hold'})")
        if n["type"] in ("Expression", "Colour expression"):
            raise ScriptError(f"{label}: hand-written C++ cannot run as a script")
        asm.stream = asm.frame if scope[nid] == "frame" else asm.pixel
        env = dict(shared)
        code = _preprocess(d["code"])
        # the Audio node reads the usermod's data straight; it gets the VM's registers instead
        if n["type"] == "Audio":
            for o in d["outputs"]:
                src = {"volume": "vol", "bass": "bass", "mid": "mid", "treble": "treb", "beat": "beat", "hit": "hit"}.get(o["name"])
                if src:
                    values[(nid, o["name"])] = fixed(src)
            continue
        if n["type"] == "Loudest bin":
            rb, rl = asm.freg(), asm.freg()
            asm.emit("LOUDEST", rb, rl, int(n["params"].get("from", 0)), int(n["params"].get("to", 15)))
            values[(nid, "bin")] = ("f", rb); values[(nid, "level")] = ("f", rl)
            continue
        if n["type"] == "Mirror fold":
            syms = ["dihedral 3", "dihedral 4", "dihedral 5", "dihedral 6", "dihedral 7", "dihedral 8", "dihedral 9",
                    "dihedral 10", "tetrahedral", "octahedral", "icosahedral"]
            sym = syms.index(n["params"].get("symmetry")) if n["params"].get("symmetry") in syms else 9
            src = src_of.get((nid, "v"))
            L = Lower(asm, env, label)
            vin = L.to_v(values[src]) if src and src in values else tuple(asm.const(c) for c in _lit("vector", n.get("inputs", {}).get("v", [0, 0, 1]))[1])
            rx, ry, rz = asm.freg(), asm.freg(), asm.freg()
            asm.emit("FOLD", rx, ry, rz, vin[0], vin[1], vin[2], sym)
            values[(nid, "v")] = ("v", (rx, ry, rz))
            continue
        if n["type"] == "Output":
            src = src_of.get((nid, "color"))
            if not src:
                raise ScriptError("Output has no colour wired in")
            asm.stream = asm.pixel
            L = Lower(asm, env, label)
            asm.emit("OUT", L.to_c(values[src]))
            continue
        if n["type"] in ("Effect settings", "Graph input", "Graph output"):
            continue
        # inputs, params and state into the environment under the template's names
        subst = code
        for i in d["inputs"]:
            key = (nid, i["name"])
            if key in src_of and src_of[key] in values:
                val = values[src_of[key]]
            else:
                v = n.get("inputs", {}).get(i["name"], i.get("default", 0))
                val = _lit(i["type"], v)
            name = f"__in_{i['name']}"
            if val[0] == "k3":
                if i["type"] == "color":
                    r = asm.creg(); asm.emit("RGB", r, *[asm.const(c) for c in val[1]]); val = ("c", r)
                else:
                    val = ("v", tuple(asm.const(c) for c in val[1]))
            elif i["type"] == "bool" and val[0] == "c":
                raise ScriptError(f"{label}: a colour into a switch")
            elif i["type"] == "bool" and val[0] in ("f", "k") and src_of.get((nid, i["name"])) in values:
                # a number on a switch: true above a half, as the C++ coerces it
                src_nid, src_out = src_of[(nid, i["name"])]
                src_t = next((o["type"] for o in defs[src_nid]["outputs"] if o["name"] == src_out), "float")
                if src_t == "float":
                    r = asm.freg(); asm.emit("GT", r, asm.const(0.5) if val[0] == "k" else val[1], asm.const(0.5))
                    if val[0] == "k":
                        val = ("k", 1.0 if val[1] > 0.5 else 0.0)
                    else:
                        val = ("f", r)
            elif i["type"] == "color" and val[0] in ("f", "k"):
                raise ScriptError(f"{label}: a number into a colour")
            env[name] = val
            subst = re.sub(r"\$in\." + re.escape(i["name"]) + r"(?![A-Za-z0-9_])", name, subst)
        for o in d["outputs"]:
            subst = re.sub(r"\$out\." + re.escape(o["name"]) + r"(?![A-Za-z0-9_])", f"__out_{o['name']}", subst)
        for p in d["params"]:
            v = n["params"].get(p["name"], p["default"])
            if p["type"] == "color":
                rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
                for k, c in zip("rgb", rgb):
                    subst = re.sub(r"\$p\." + re.escape(p["name"] + "_" + k) + r"(?![A-Za-z0-9_])", str(int(c)), subst)
            elif p["type"] in ("choice", "text", "file"):
                subst = re.sub(r"\$p\." + re.escape(p["name"]) + r"(?![A-Za-z0-9_])", str(v).replace('"', "'"), subst)
            elif p["type"] in ("ramp", "curve"):
                raise ScriptError(f"{label}: a table the device cannot hold")
            elif p["type"] == "bool":
                subst = re.sub(r"\$p\." + re.escape(p["name"]) + r"(?![A-Za-z0-9_])", "1" if v else "0", subst)
            else:
                subst = re.sub(r"\$p\." + re.escape(p["name"]) + r"(?![A-Za-z0-9_])", repr(float(v)), subst)
        st = d.get("state")
        if st:
            base = slots[nid]
            names = list(st) if isinstance(st, (list, tuple)) else [f"s{k}" for k in range(int(st))]
            if not isinstance(st, (list, tuple)):
                raise ScriptError(f"{label}: keeps a block of state the script cannot address")
            for k, sname in enumerate(names):
                r = asm.freg(); asm.emit("STLD", r, base + k)
                env[f"__st_{sname}"] = ("f", r)
                subst = re.sub(r"\$st\." + re.escape(sname) + r"(?![A-Za-z0-9_])", f"__st_{sname}", subst)
        subst = subst.replace("$first", "gc_first").replace("$$", "$")
        if "$" in subst:
            m = re.search(r"\$\w+\.?\w*", subst)
            raise ScriptError(f"{label}: template refers to {m.group(0)}")
        if n.get("muted"):
            # bypass: each output takes the first input of its type
            subst = ""
            for o in d["outputs"]:
                src = next((i for i in d["inputs"] if i["type"] == o["type"]), None)
                if src:
                    subst += f"__out_{o['name']} = __in_{src['name']};"
        try:
            tokens = tokenize(subst)
            tree = Parser(tokens).block()
            L = Lower(asm, env, label, alloc_state)
            L.run(tree)
            for sname, slot in L.statics:
                asm.emit("STST", slot, L.to_f(env[sname]))
        except ScriptError as e:
            raise ScriptError(str(e) if str(e).startswith(label) else f"{label}: {e}")
        for o in d["outputs"]:
            val = env.get(f"__out_{o['name']}")
            if val is None:
                val = ("k", 0.0)
            if o["type"] == "color" and val[0] != "c":
                val = ("c", L.to_c(val))
            elif o["type"] == "vector" and val[0] != "v":
                val = ("v", L.to_v(val))
            elif o["type"] in ("float", "bool") and val[0] == "v":
                val = ("f", val[1][0])
            elif o["type"] in ("float", "bool") and val[0] == "c":
                raise ScriptError(f"{label}: a colour on a number output")
            values[(nid, o["name"])] = val
        if st:
            for k, sname in enumerate(names):
                v = env.get(f"__st_{sname}")
                asm.emit("STST", base + k, L.to_f(v))
    return asm.encode(extra[0])


def settings_of(graph):
    """The sliders, checks and palette the graph's control nodes and Effect
    settings default to - what the Script effect should be given so the
    script runs as its C++ build would with the same metadata."""
    dkey = {"Speed": "sx", "Intensity": "ix", "Custom 1": "c1", "Custom 2": "c2", "Custom 3": "c3",
            "Check 1": "o1", "Check 2": "o2", "Check 3": "o3"}
    out = {"sx": 128, "ix": 128, "c1": 128, "c2": 128, "c3": 16, "o1": 0, "o2": 0, "o3": 0}
    for n in graph.nodes.values():
        if n["type"] in dkey and "default" in n["params"]:
            v = n["params"]["default"]
            out[dkey[n["type"]]] = int(bool(v)) if isinstance(v, bool) else int(v)
    st = next((n["params"] for n in graph.nodes.values() if n["type"] == "Effect settings"), {})
    out["pal"] = int(st.get("palette", 11))
    return out


def scriptable(graph):
    """(True, size) or (False, why)."""
    try:
        return True, len(compile_script(graph))
    except GraphError as e:
        return False, str(e)


# --- the helpers header the VM effect includes -----------------------------------------
def write_helpers(path=None):
    """usermods/cube_fx/cube_fx_studio_helpers.h from the node library's
    HELPERS block, so the Studio Script effect has the same gc_* functions
    the generated effects carry. Regenerated by the check and by staging."""
    import os
    from native.nodedefs import HELPERS
    from native.project import ROOT
    path = path or os.path.join(ROOT, "usermods", "cube_fx", "cube_fx_studio_helpers.h")
    text = ("// GENERATED by studio/native/script.py from native/nodedefs.py HELPERS - do not edit.\n"
            "// The helper functions the WLED Effects Studio's generated effects carry, for the\n"
            "// Studio Script effect (cube_fx_98_script.cpp), which runs the studio's bytecode.\n"
            "#pragma once\n#include \"wled.h\"\n#include \"cube_fx_common.h\"\n" + HELPERS + "\n")
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old != text:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return path


if __name__ == "__main__":
    import sys
    if "--helpers" in sys.argv:
        print("wrote", write_helpers())
