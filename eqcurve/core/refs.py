"""refs: extract the external design-parameter names a CurveDef references.

adsk-free and pytest-friendly. Two uses:
  * MS-2 associativity — mirror each referenced User Parameter as a custom
    parameter on the Custom Feature so edits trigger recompute (FR-8.2).
  * Circular-reference detection among design parameters (FR-8.6).
"""

from __future__ import annotations

import ast
from typing import Dict, Set

from .curvedef import CurveDef
from .evaluator import reserved_names
from . import eqlog

# Independent-variable aliases the sampler injects; never design parameters.
_INDEP_ALIASES = {"t", "x", "a"}


def _names_in(expr: str) -> Set[str]:
    """All identifier names appearing in a single expression (parse-failures -> {})."""
    if not isinstance(expr, str) or not expr.strip():
        return set()
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        eqlog.log_caught("refs._names_in", expr=expr)
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def referenced_names(cd: CurveDef) -> Set[str]:
    """Return external design-parameter names referenced by `cd`.

    Scans every component expression, the domain endpoints, and the origin,
    then removes built-in functions/constants and the independent variable.
    """
    exprs = list(cd.exprs.values()) + [cd.t_min, cd.t_max]
    exprs += list((cd.origin or {}).values())

    found: Set[str] = set()
    for e in exprs:
        found |= _names_in(e)

    return found - reserved_names(cd.angle) - (_INDEP_ALIASES | {cd.var})


def circular_reference(param_exprs: Dict[str, str], angle: str = "rad") -> Set[str]:
    """Detect circular references among design parameters.

    `param_exprs` maps a parameter name to its defining expression (which may
    reference other parameters). Returns the set of names involved in a cycle
    (empty if the dependency graph is acyclic). FR-8.6.
    """
    reserved = reserved_names(angle)
    deps: Dict[str, Set[str]] = {
        name: (_names_in(expr) & set(param_exprs)) - reserved - {name}
        for name, expr in param_exprs.items()
    }

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in deps}
    in_cycle: Set[str] = set()

    def visit(node: str, stack: list) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in sorted(deps.get(node, ())):
            if color.get(nxt, BLACK) == GRAY:
                # found a back-edge: everything from nxt up the stack is a cycle
                idx = stack.index(nxt)
                in_cycle.update(stack[idx:])
            elif color.get(nxt, BLACK) == WHITE:
                visit(nxt, stack)
        stack.pop()
        color[node] = BLACK

    for n in sorted(deps):
        if color[n] == WHITE:
            visit(n, [])
    return in_cycle
