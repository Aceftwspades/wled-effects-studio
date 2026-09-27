"""Arithmetic typed into a field: `2*pi`, `1/3`, `x*2`, `sqrt(2)`,
`min(a, 4)`. The text is parsed to Python's AST and walked - numbers,
names given, the operators, a table of maths functions - and nothing
else runs: no attributes, no subscripts, no calls but the table's.

    evaluate("2*pi")                  6.283...
    evaluate("x*2", {"x": 3.0})       6.0
    evaluate("clamp(x, 0, 1)", ...)   with the table's helpers
"""
import ast
import math
import operator
import random

CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}

FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "sqrt": math.sqrt, "abs": abs, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil, "round": round,
    "exp": math.exp, "log": math.log, "log2": math.log2, "log10": math.log10, "pow": math.pow, "hypot": math.hypot,
    "fract": lambda v: v - math.floor(v), "sign": lambda v: (v > 0) - (v < 0), "deg": math.degrees, "rad": math.radians,
    "clamp": lambda v, lo=0.0, hi=1.0: min(hi, max(lo, v)), "lerp": lambda a, b, t: a + (b - a) * t,
    "rand": lambda lo=0.0, hi=1.0: random.uniform(lo, hi),
}

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class ExprError(ValueError):
    pass


def evaluate(text, names=None):
    """The value of `text`, a float; ExprError says what was wrong."""
    return compile(text)(names)


MAX_LEN = 2000        # characters: far past any formula, short of a nesting that exhausts the stack


def compile(text):
    """`text` parsed once: a function of the names ({name: number}) giving
    the value - for an expression worked out many times (a formula part's
    x, y and z for every LED). ExprError on a text that does not parse; a
    call raises it for what only the numbers show (division by zero)."""
    text = (text or "").strip().replace("^", "**")
    if not text:
        raise ExprError("nothing to work out")
    if len(text) > MAX_LEN:
        raise ExprError(f"too long: {len(text)} characters, {MAX_LEN} at most")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"not an expression: {e.msg}")
    except (ValueError, RecursionError, MemoryError):           # a null byte; a nesting too deep to parse
        raise ExprError("not an expression: nested too deeply, or not text")
    return lambda names=None: _value(tree, names)


def _real(v, what):
    """A result as a float - or ExprError for what is not a real number: a
    negative number to a fractional power (Python makes that complex), a
    NaN (inf - inf), a value too big for a float. A NaN is caught where it
    is made, not at the end: sign(), clamp(), min() would hide it."""
    if isinstance(v, complex):
        raise ExprError(f"{what}: not a real number")
    try:
        v = float(v)
    except OverflowError:
        raise ExprError(f"{what}: too big")
    if math.isnan(v):
        raise ExprError(f"{what}: not a number")
    return v


def _value(tree, names):
    env = dict(CONSTANTS)
    env.update({k: float(v) for k, v in (names or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)})

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ExprError("numbers only")
            return _real(node.value, "a number")
        if isinstance(node, ast.Name):
            if node.id in env:
                return _real(env[node.id], node.id)
            raise ExprError(f"unknown name {node.id!r}" + (f" - the names here: {', '.join(sorted(k for k in env if k not in CONSTANTS))}"
                                                           if any(k not in CONSTANTS for k in env) else ""))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            a, b = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(b) > 1e4 and abs(a) > 1.0:
                raise ExprError("too big")
            try:
                r = _BIN[type(node.op)](a, b)
            except ZeroDivisionError:
                raise ExprError("division by zero")
            except OverflowError:
                raise ExprError("too big")
            return _real(r, "the sum" if isinstance(node.op, (ast.Add, ast.Sub)) else "the result")
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _real(_UN[type(node.op)](walk(node.operand)), "the result")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                raise ExprError("the functions here: " + ", ".join(sorted(FUNCTIONS)))
            args = [walk(a) for a in node.args]
            try:
                r = FUNCTIONS[node.func.id](*args)
            except (TypeError, ValueError, ZeroDivisionError) as e:
                raise ExprError(f"{node.func.id}: {e}")
            except OverflowError:                                    # exp(1000), floor(inf), pow(10, 400)
                raise ExprError(f"{node.func.id}: too big")
            return _real(r, node.func.id)
        raise ExprError("only numbers, + - * / ^ %, brackets and the maths functions")
    try:
        v = walk(tree)
    except RecursionError:                                           # 1+1+1... twenty thousand terms deep
        raise ExprError("too long, or nested too deeply")
    if isinstance(v, complex) or math.isnan(v):
        raise ExprError("not a number")
    if math.isinf(v):
        raise ExprError("infinite: too big")
    return v
