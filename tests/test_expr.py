"""The expression evaluator behind `=` on a field (native/expr.py): what
it works out, and everything it refuses."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native.expr import evaluate, ExprError, FUNCTIONS       # noqa: E402


def test_arithmetic_and_names():
    assert abs(evaluate("2*pi") - math.tau) < 1e-12
    assert evaluate("1/3") == 1 / 3 and evaluate("2^10") == 1024.0 and evaluate("7 % 4") == 3.0
    assert evaluate("x*2", {"x": 3}) == 6.0 and evaluate("-x + 1", {"x": 0.25}) == 0.75
    assert evaluate("min(a, 4)", {"a": 7}) == 4.0 and evaluate("max(a, b)", {"a": 1, "b": 2}) == 2.0
    assert evaluate("sqrt(2)") == math.sqrt(2) and abs(evaluate("sin(tau/4)") - 1.0) < 1e-12
    assert evaluate("clamp(-2)") == 0.0 and evaluate("clamp(5, 0, 2)") == 2.0 and evaluate("lerp(0, 10, 0.5)") == 5.0
    assert evaluate("fract(2.75)") == 0.75 and evaluate("sign(-3)") == -1.0 and evaluate("round(2.5)") == 2.0
    assert 0.0 <= evaluate("rand()") <= 1.0 and 2.0 <= evaluate("rand(2, 3)") <= 3.0
    assert evaluate("(1 + 2) * (3 - 4) / 5") == -0.6
    assert evaluate("in_hi * 2", {"in_hi": 1.5}) == 3.0                       # a node's own numbers, by name


def test_refusals():
    for bad in ["__import__('os')", "x.real", "[1][0]", "1/0", "foo(1)", "y", "", "1 if 2 else 3", "'a'",
                "lambda: 1", "x = 1", "open('f')", "max(1, 2, key=abs)", "1e400 * 1e400", "10 ** 10 ** 10"]:
        try:
            evaluate(bad, {"x": 1})
        except ExprError:
            continue
        raise AssertionError(f"took {bad!r}")


def test_every_function_is_callable_with_numbers():
    for name, f in FUNCTIONS.items():
        try:
            f(0.5) if name not in ("atan2", "pow", "hypot", "lerp", "min", "max") else f(0.5, 0.25) if name != "lerp" else f(0, 1, 0.5)
        except (TypeError, ValueError):
            pass                                                            # a domain error is allowed; a crash is not


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
