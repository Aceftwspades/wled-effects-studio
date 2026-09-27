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


def test_what_used_to_escape_is_an_expr_error():
    """Ordinary inputs that raised something other than ExprError - which
    the shape editor's formula parts did not catch (issue #6): a negative
    number to a fractional power (complex), an overflow inside a function,
    a nesting the walk could not go down, a NaN hidden by sign() or clamp()."""
    cases = ["(-8)^(1/3)", "(t-0.5)^0.5", "exp(1000)", "cosh(1000)", "sinh(1000)", "pow(10, 400)",
             "floor(inf)", "round(inf)", "ceil(1e308*10)", "-" * 5000 + "1", "+".join(["1"] * 20000),
             "sign(inf-inf)", "clamp(inf-inf)", "min(inf-inf, 1)", "fract(inf)", "inf*0", "x", "1" * 400,
             "sqrt(-1)", "log(0)", "(" * 300 + "1" + ")" * 300, "0^-1",
             "-" * 1990 + "1", "+".join(["1"] * 999)]                  # under the length cap, past the walk's depth
    for bad in cases:
        try:
            v = evaluate(bad, {"t": 0.0, "x": float("nan")})
        except ExprError:
            continue
        raise AssertionError(f"{bad[:40]!r}: gave {v!r}, not an ExprError")
    # what still works: inf where it is meant, a big but finite power, the names
    assert evaluate("clamp(x, -inf, inf)", {"x": 3}) == 3.0 and evaluate("min(x, inf)", {"x": 2}) == 2.0
    assert evaluate("2^1000") == 2.0 ** 1000 and evaluate("(-8)^2") == 64.0 and evaluate("(-8)^3") == -512.0


def test_formula_parts_say_what_is_wrong():
    """A formula part whose expression fails says so in the shape editor -
    even where it fails only past the LEDs formula_error samples (cosh(i)
    at LED 711) - and its points are made regardless."""
    from native import shapes
    part = shapes.new_part("formula", n=50, x="(t-0.5)^0.5", y="t", z="0")
    assert "x:" in shapes.formula_error(part) and "real" in shapes.formula_error(part)
    pos, _ = shapes.part_points(part)
    assert pos.shape == (50, 3)
    far = shapes.new_part("formula", n=1000, x="cosh(i)", y="0", z="0")
    err = shapes.formula_error(far)
    assert err.startswith("x:") and "too big" in err, err
    # a failure at none of the three LEDs tried up front: found as the points were made
    assert shapes.formula_error(shapes.new_part("formula", n=50, x="1/(i-7)", y="0", z="0")) == "x: at LED 7: division by zero"
    assert shapes.formula_error(shapes.new_part("formula", n=50, x="sin(t*tau)", y="cos(t*tau)", z="t")) == ""


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
