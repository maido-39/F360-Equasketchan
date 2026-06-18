"""Human-readable messages for curve errors (FR-12.5). adsk-free.

Maps the evaluator/sampler exceptions to specific, actionable text the UI can
show instead of a raw traceback (unknown function, domain singularity, empty
domain, too few points, etc.).
"""

from __future__ import annotations

from .evaluator import ExpressionError
from .sampler import SamplingError


def describe(exc: Exception) -> str:
    """A concise, user-facing explanation of a curve build failure."""
    msg = str(exc).strip()
    if isinstance(exc, ExpressionError):
        low = msg.lower()
        if "unknown function" in low:
            return f"Unsupported function — {msg}. See the function library."
        if "unknown name" in low:
            return f"Undefined identifier — {msg}. Use a design parameter or a known constant."
        if "disallowed syntax" in low or "only direct function" in low:
            return f"Unsupported syntax in the expression — {msg}."
        return f"Could not parse the expression: {msg}"
    if isinstance(exc, SamplingError):
        low = msg.lower()
        if "t_min == t_max" in low or "empty domain" in low:
            return "Empty domain: t min equals t max."
        if "not finite" in low:
            return "The domain endpoints did not evaluate to finite numbers."
        if "fewer than 2" in low:
            return ("The expression produced fewer than 2 valid points — it may be "
                    "undefined across the whole domain (check for singularities).")
        return f"Sampling failed: {msg}"
    if isinstance(exc, ZeroDivisionError):
        return "Division by zero while evaluating the curve."
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def warnings_text(self_intersections, degenerate) -> str:
    """One-line non-fatal summary for the dialog (empty if nothing to report)."""
    parts = []
    if self_intersections:
        parts.append(f"{len(self_intersections)} self-intersection(s)")
    if degenerate:
        parts.append(f"{len(degenerate)} degenerate/duplicate point(s)")
    return ("Warning: " + ", ".join(parts) + ".") if parts else ""
