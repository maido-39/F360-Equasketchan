"""Safe expression evaluator for equation-driven curves.

Pure stdlib (ast + math) so it imports under BOTH Fusion's bundled Python
(inside the add-in) and a normal system Python (for pytest). No `eval` of
arbitrary code: only a whitelisted AST is permitted.

Angle handling: the evaluator is created with angle='rad' or 'deg'. In 'deg'
mode the trig functions accept degrees and the inverse-trig functions return
degrees, so the user can write equations consistently in one unit.
"""

from __future__ import annotations

import ast
import math
from typing import Dict, Mapping


class ExpressionError(ValueError):
    """Raised for unparseable or disallowed expressions."""


# --- constants available inside expressions -------------------------------
_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "phi": (1.0 + 5.0 ** 0.5) / 2.0,
    "tau": math.tau,
}


def _build_functions(angle: str):
    """Return the function table honoring the angle unit for trig funcs."""
    if angle not in ("rad", "deg"):
        raise ExpressionError("angle must be 'rad' or 'deg'")

    to_rad = math.radians if angle == "deg" else (lambda x: x)
    from_rad = math.degrees if angle == "deg" else (lambda x: x)

    def _sign(x):
        return (x > 0) - (x < 0)

    return {
        # trig (input honors angle unit)
        "sin": lambda x: math.sin(to_rad(x)),
        "cos": lambda x: math.cos(to_rad(x)),
        "tan": lambda x: math.tan(to_rad(x)),
        "cot": lambda x: 1.0 / math.tan(to_rad(x)),
        "sec": lambda x: 1.0 / math.cos(to_rad(x)),
        "csc": lambda x: 1.0 / math.sin(to_rad(x)),
        # inverse trig (output honors angle unit)
        "asin": lambda x: from_rad(math.asin(x)),
        "acos": lambda x: from_rad(math.acos(x)),
        "atan": lambda x: from_rad(math.atan(x)),
        "atan2": lambda y, x: from_rad(math.atan2(y, x)),
        # arc* aliases so equations copied from other tools/CAD just work
        "arcsin": lambda x: from_rad(math.asin(x)),
        "arccos": lambda x: from_rad(math.acos(x)),
        "arctan": lambda x: from_rad(math.atan(x)),
        "arctan2": lambda y, x: from_rad(math.atan2(y, x)),
        # hyperbolic (native — the SolidWorks gap)
        "sinh": math.sinh,
        "cosh": math.cosh,
        "tanh": math.tanh,
        "asinh": math.asinh,
        "acosh": math.acosh,
        "atanh": math.atanh,
        "arcsinh": math.asinh,
        "arccosh": math.acosh,
        "arctanh": math.atanh,
        # exp / log
        "exp": math.exp,
        "ln": math.log,
        "log": lambda x, base=10.0: math.log(x, base),  # log(x)=log10; log(x,b)
        "log10": math.log10,
        "log2": math.log2,
        "sqrt": math.sqrt,
        "cbrt": lambda x: math.copysign(abs(x) ** (1.0 / 3.0), x),
        "pow": math.pow,
        # misc (supported here, unlike Inventor — note: cause discontinuities)
        "abs": abs,
        "floor": math.floor,
        "ceil": math.ceil,
        "round": round,
        "sign": _sign,
        "min": min,
        "max": max,
        "hypot": math.hypot,
        "lerp": lambda a, b, t: a + (b - a) * t,
    }


def reserved_names(angle: str = "rad") -> set:
    """Names that are built into the evaluator (functions + constants).

    Anything an expression references that is NOT in here and not an independent
    variable is treated as an external design parameter (see core.refs).
    """
    return set(_CONSTANTS) | set(_build_functions(angle))


_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load,
    ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
)


class Evaluator:
    """Compiles and evaluates a single scalar expression safely."""

    def __init__(self, angle: str = "rad"):
        self.angle = angle
        self.functions = _build_functions(angle)

    def _validate(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if not isinstance(child, _ALLOWED_NODES):
                raise ExpressionError(
                    f"disallowed syntax: {type(child).__name__}"
                )
            if isinstance(child, ast.Call):
                if not isinstance(child.func, ast.Name):
                    raise ExpressionError("only direct function calls allowed")
                if child.func.id not in self.functions:
                    raise ExpressionError(f"unknown function: {child.func.id}")
                if child.keywords:
                    raise ExpressionError("keyword arguments not allowed")

    def compile(self, expr: str) -> ast.Expression:
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"syntax error in '{expr}': {exc}") from exc
        self._validate(tree)
        return tree

    def eval(self, expr: str, variables: Mapping[str, float]) -> float:
        """Evaluate `expr` with the given variables (e.g. {'t':..,'D3':..})."""
        tree = self.compile(expr)
        names: Dict[str, object] = dict(_CONSTANTS)
        names.update(self.functions)
        names.update(variables)  # variables/params override constants if named so
        return self._eval_node(tree.body, names)

    # recursive evaluation (kept explicit; no builtins exposed)
    def _eval_node(self, node: ast.AST, names: Dict[str, object]) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ExpressionError(f"non-numeric constant: {node.value!r}")
        if isinstance(node, ast.Name):
            if node.id in names and not callable(names[node.id]):
                return float(names[node.id])
            raise ExpressionError(f"unknown name: {node.id}")
        if isinstance(node, ast.UnaryOp):
            val = self._eval_node(node.operand, names)
            return +val if isinstance(node.op, ast.UAdd) else -val
        if isinstance(node, ast.BinOp):
            a = self._eval_node(node.left, names)
            b = self._eval_node(node.right, names)
            op = node.op
            if isinstance(op, ast.Add):
                return a + b
            if isinstance(op, ast.Sub):
                return a - b
            if isinstance(op, ast.Mult):
                return a * b
            if isinstance(op, ast.Div):
                return a / b
            if isinstance(op, ast.FloorDiv):
                return a // b
            if isinstance(op, ast.Mod):
                return a % b
            if isinstance(op, ast.Pow):
                return a ** b
        if isinstance(node, ast.Call):
            func = names[node.func.id]
            args = [self._eval_node(a, names) for a in node.args]
            return float(func(*args))
        raise ExpressionError(f"cannot evaluate node: {type(node).__name__}")
