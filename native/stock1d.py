"""
Lift WLED's 1-D effects out of FX.cpp for the simulator - discovered, not
listed, and PROBED: whatever fails to compile against the shim is dropped
automatically and named, rather than one effect's missing helper taking the
other hundred and fifty down with it.

The 2-D extraction in build.py takes every mode_2D*; this takes every other
mode_* up to the first particle-system block. The particle effects are left
behind on purpose - they are a subsystem the shim has no business hosting.

The probe: generate one translation unit, compile it, map each error to the
effect whose body it landed in, drop those effects, and go again until it
compiles. The result is cached in gen/stock1d_skip.json keyed on FX.cpp and the
shim, so a routine build costs nothing; a change to either re-probes. The
skipped list is printed with the first error for each, because a simulator
that silently omits things is worse than one that says what it left out.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
GEN = os.path.join(HERE, "gen")

LIT = r'\[\]\s*PROGMEM\s*=\s*"(?:[^"\\]|\\.)*"\s*;'

# Never worth trying.
ALWAYS_SKIP = {
    "mode_static": "trivial; the segment's colour is the segment's colour",
    "mode_copy_segment": "copies another segment - there is only one here",
}


def _balance(text):
    out, depth = [], 0
    for line in text.splitlines(keepends=True):
        st = line.lstrip()
        if st.startswith("#if"):
            depth += 1
        elif st.startswith("#endif"):
            if depth == 0:
                continue
            depth -= 1
        elif st.startswith(("#else", "#elif")) and depth == 0:
            continue
        out.append(line)
    return "".join(out) + ("\n#endif\n" * depth)


def _fn_end(src, brace):
    """Index just past the brace matching src[brace] == '{', skipping strings,
    chars and comments well enough for FX.cpp."""
    depth, i, n = 0, brace, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            i = src.find('\n', i); i = n if i < 0 else i; continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2); i = n if j < 0 else j + 2; continue
        if c == '"' or c == "'":
            q = c; i += 1
            while i < n and src[i] != q:
                if src[i] == '\\': i += 1
                i += 1
            i += 1; continue
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: return i + 1
        i += 1
    return n


def _strip_defs(text, names):
    """Remove the file-scope definition of each named thing: a function (brace
    matched) or a declaration (to the semicolon)."""
    for nm in names:
        # A DEFINITION line: optional static, a type, the name, then ( = or ;
        # - not a mention in a comment, which is where the first version found
        # getAudioData() and removed a line of documentation instead.
        m = re.search(r"^[ \t]*(?:static[ \t]+)?[\w:<>\*&][\w:<>\*& \t]*\b" + re.escape(nm)
                      + r"\b[ \t]*(?:\(|=|;)[^\n]*$", text, re.M)
        if not m:
            continue
        line = m.group(0)
        if "{" in line and "}" not in line[line.find("{"):]:
            end = _fn_end(text, m.start() + line.find("{"))
        else:
            end = text.find(";", m.start())
            end = len(text) if end < 0 else end + 1
        text = text[:m.start()] + text[end:]
    return text


def discover(fxsrc):
    """(top, [(name, sym, meta_literal, preamble, body)]) for every 1-D effect.

    `top` is FX.cpp's own head - its #defines and the small static helpers
    (sin_gap, tristate_square8, the PALETTE_*_WRAP macros) that sit above the
    first effect - with the includes removed. Each effect carries a PREAMBLE,
    the file-scope declarations between the previous function's closing brace
    and its own, and a BODY, the function itself found by brace matching. The
    split matters: a skipped effect gives up only its body, so the helper it
    happened to be sitting next to stays available to the effects that need
    it. The first version dropped whole spans and lost blink() with
    mode_static.
    """
    ps = fxsrc.find("#ifndef WLED_DISABLE_PARTICLESYSTEM")
    region = fxsrc[:ps] if ps > 0 else fxsrc
    # An EFFECT takes no arguments. mode_puddles_base(bool) and friends are
    # helpers that happen to share the prefix; matched as effects they were
    # registered with a metadata string found nearby and failed to link.
    fn = re.compile(r"^\s*(?:static\s+)?(?:uint16_t|void)\s+(mode_\w+)\s*\(\s*(?:void)?\s*\)\s*\{", re.M)
    allhits = [(m.start(), m.group(1), m.end() - 1) for m in fn.finditer(region)]
    if not allhits:
        return "", []
    first = allhits[0][0]
    head = region[:first]
    inc_end = 0
    for m in re.finditer(r'^\s*#include[^\n]*\n', head, re.M):
        inc_end = m.end()
    top = "\n".join(l for l in head[inc_end:].splitlines()
                    if not l.lstrip().startswith(("#include", "#error")))
    # The shim already provides these; FX.cpp's own copies would be
    # redefinitions. prng is the shim's random source, getAudioData() is the
    # simulator's audio, and both are what the effects should be reaching.
    top = _strip_defs(top, ("prng", "getAudioData"))
    items = []
    prev_end = first
    for k, (pos, name, brace) in enumerate(allhits):
        end = _fn_end(region, brace)
        pre = region[prev_end:pos]
        body = region[pos:end]
        prev_end = end
        if name.startswith("mode_2D"):
            continue                      # taken by build.py's 2-D extraction
        sym = "_data_FX_MODE_" + name[len("mode_"):].upper()
        mm = re.search(r'static const char ' + sym + LIT, region)
        if not mm:
            near = re.search(r'static const char (_data_FX_MODE_\w+)' + LIT, region[pos:pos + 4000])
            if near:
                sym = near.group(1)
                mm = re.search(r'static const char ' + sym + LIT, region)
        pre = re.sub(r'static const char _data_FX_MODE_\w+' + LIT, "", pre)
        if not mm:
            items.append((name, None, None, pre, body))
            continue
        items.append((name, sym, mm.group(0), pre, body))
    return _balance(top), items


_DEF = re.compile(r"^([ \t]*)((?:uint16_t|uint8_t|uint32_t|int|void|bool|float|CRGB|static)\b[^;{()=]*?\b\w+\s*\([^;{]*\)\s*(?:const\s*)?\{)", re.M)

def _staticise(text):
    """Give every free function DEFINED in a preamble internal linkage. The 2-D
    extraction compiles some of the same helpers inside its own spans -
    mode_gravcenter_base, mode_puddles_base - and two external definitions
    of one function is a link error; two static ones are two copies, which
    is what a helper next to an effect always was in spirit."""
    def fix(m):
        if m.group(2).startswith("static"):
            return m.group(0)
        return m.group(1) + "static " + m.group(2)
    return _DEF.sub(fix, text)


def _emit(top, items, skip, skip_pre, already):
    """The generated TU. `already` are 1-D effects the 2-D extraction happened
    to compile inside one of its spans - those are declared and registered,
    not redefined, or the link sees them twice."""
    metas, chunks, reg, seen = [], [], [], set()
    for name, sym, meta, pre, body in items:
        if name not in skip_pre and pre.strip():
            chunks.append(f"\n// @@PRE {name}\n" + _staticise(_balance(pre)))
        if name in skip or sym is None:
            continue
        if sym not in seen:                  # two effects can share a literal
            metas.append(meta); seen.add(sym)
        if name in already:
            chunks.append(f"\n// @@FX {name}\nvoid {name}(void);\n")
        else:
            chunks.append(f"\n// @@FX {name}\n" + _balance(body))
        reg.append((name, sym))
    text = ('// GENERATED by native/stock1d.py - do not edit.\n'
            '// Stock WLED 1-D effects, lifted verbatim from FX.cpp.\n'
            '#include "../shim/wled.h"\n'
            '#include "../../usermods/cube_fx/cube_fx_bank.h"\n\n'
            "// @@PRE (top of FX.cpp)\n" + _staticise(top) + "\n"
            + "\n".join(metas) + "\n" + "".join(chunks) + "\n"
            "void simRegisterStock1D() {\n"
            + "\n".join(f"  cfxBankAdd(&{fn}, {sym});" for fn, sym in reg)
            + "\n}\n")
    return text, reg


def _line_owner(text, line):
    """(kind, effect) owning a 1-based line of the generated file."""
    owner = (None, None)
    for i, l in enumerate(text.splitlines(), 1):
        if l.startswith("// @@FX "):
            owner = ("fx", l[8:].strip())
        elif l.startswith("// @@PRE "):
            owner = ("pre", l[9:].strip())
        if i == line:
            return owner
    return owner


def extract(log=print):
    """Write gen/wled_fx1d.cpp; returns its path. Probes when the inputs changed."""
    from native.toolchain import find_compiler, compile_tu, ToolchainError
    fxpath = os.path.join(ROOT, "wled00", "FX.cpp")
    shim = os.path.join(HERE, "shim", "wled.h")
    fxsrc = open(fxpath, encoding="utf-8", errors="surrogateescape").read()
    top, items = discover(fxsrc)
    # effects the 2-D extraction already compiled (they sat inside its spans)
    already = set()
    fx2d = os.path.join(GEN, "wled_fx.cpp")
    if os.path.exists(fx2d):
        t2 = open(fx2d, encoding="utf-8").read()
        for name, *_ in items:
            if re.search(r"\b(?:uint16_t|void)\s+" + name + r"\s*\(", t2):
                already.add(name)
    out = os.path.join(GEN, "wled_fx1d.cpp")
    cache = os.path.join(GEN, "stock1d_skip.json")
    key = f"{os.path.getmtime(fxpath)}|{os.path.getmtime(shim)}|{os.path.getmtime(__file__)}"

    skip = dict(ALWAYS_SKIP)
    skip_pre = set()
    if os.path.exists(cache):
        try:
            d = json.load(open(cache, encoding="utf-8"))
            if d.get("key") == key:
                skip.update(d.get("skip", {}))
                skip_pre = set(d.get("skip_pre", []))
                text, reg = _emit(top, items, skip, skip_pre, already)
                prev = open(out, encoding="utf-8").read() if os.path.exists(out) else None
                if prev != text:
                    open(out, "w", encoding="utf-8").write(text)
                log(f"  stock 1-D: {len(reg)} effects ({len(skip) - len(ALWAYS_SKIP)} skipped, cached)")
                return out
        except Exception:
            pass

    try:
        compiler, env = find_compiler()
    except ToolchainError as e:
        log(f"  stock 1-D: cannot probe ({e}); emitting nothing")
        allnames = {n for n, *_ in items}
        text, reg = _emit(top, items, allnames, allnames, already)
        open(out, "w", encoding="utf-8").write(text)
        return out

    inc = [os.path.join(HERE, "shim"), os.path.join(ROOT, "usermods", "cube_fx"), GEN]
    probe_obj = os.path.join(HERE, "build", "obj", "_probe_fx1d.o")
    for it in range(24):
        text, reg = _emit(top, items, skip, skip_pre, already)
        open(out, "w", encoding="utf-8").write(text)
        ok, txt = compile_tu(compiler, env, out, probe_obj, inc)
        if ok:
            break
        dropped = 0
        for line in txt.splitlines():
            m = re.match(r"(.+?):(\d+):\d+:\s*error:\s*(.*)", line)
            if not m:
                continue
            if os.path.basename(m.group(1)) != os.path.basename(out):
                continue
            kind, owner = _line_owner(text, int(m.group(2)))
            if not owner:
                continue
            if kind == "pre" and owner not in skip_pre:
                # a helper that will not compile: drop it, and the effect after
                # it, which is the one that needed it
                skip_pre.add(owner); dropped += 1
                if owner not in skip and owner != "(top of FX.cpp)":
                    skip[owner] = "its preamble: " + m.group(3).strip()[:80]
            elif kind == "fx" and owner not in skip:
                skip[owner] = m.group(3).strip()[:90]
                dropped += 1
        if not dropped:
            log("  stock 1-D: unattributable errors, emitting nothing:")
            log("    " + "\n    ".join(txt.splitlines()[:8]))
            allnames = {n for n, *_ in items}
            text, reg = _emit(top, items, allnames, allnames, already)
            open(out, "w", encoding="utf-8").write(text)
            return out
    try:
        os.remove(probe_obj)
    except OSError:
        pass
    json.dump({"key": key, "skip": {k: v for k, v in skip.items() if k not in ALWAYS_SKIP},
               "skip_pre": sorted(skip_pre)},
              open(cache, "w", encoding="utf-8"), indent=1)
    auto = {k: v for k, v in skip.items() if k not in ALWAYS_SKIP}
    log(f"  stock 1-D: {len(reg)} effects lifted, {len(auto)} skipped:")
    for k, v in sorted(auto.items()):
        log(f"    {k}: {v}")
    return out
