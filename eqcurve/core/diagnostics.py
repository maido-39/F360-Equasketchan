"""diagnostics: non-fatal curve-quality checks (adsk-free, pytest-friendly).

These never raise (FR-13.5) — they return findings the UI surfaces as warnings
(FR-10.6 self-intersection / degenerate detection). Geometry is still built.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

Point = Tuple[float, float, float]


def _dist(a: Point, b: Point) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def degenerate_points(pts: List[Point], tol: float = 1e-9) -> List[int]:
    """Indices i where pts[i] is a near-duplicate of pts[i-1] (collapsed step)."""
    return [i for i in range(1, len(pts)) if _dist(pts[i], pts[i - 1]) <= tol]


def _orient(a: Point, b: Point, c: Point) -> float:
    """2D (XY) signed area of triangle abc; sign = turn direction."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross_2d(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Proper intersection of segments p1p2 and p3p4 in the XY plane.

    Collinear-overlap is intentionally ignored (a heuristic warning, not exact).
    """
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    return (
        ((d1 > 0) != (d2 > 0)) and (d1 != 0) and (d2 != 0)
        and ((d3 > 0) != (d4 > 0)) and (d3 != 0) and (d4 != 0)
    )


def self_intersections(pts: List[Point], max_segments: int = 4000) -> List[Tuple[int, int]]:
    """Pairs (i, j) of non-adjacent segments that cross in XY.

    Uses a uniform spatial grid so cost stays near-linear for well-behaved
    curves; only segments sharing a grid neighbourhood are pair-tested. For 3D
    curves this is an XY-projection heuristic. Returns [] when there is nothing
    to test or the point count exceeds ``max_segments`` (guard, logged by caller).
    """
    n = len(pts) - 1
    if n < 3 or n > max_segments:
        return []

    # cell size = median segment length (deterministic), min positive.
    lengths = sorted(_dist(pts[i], pts[i + 1]) for i in range(n))
    med = lengths[n // 2] if n % 2 else 0.5 * (lengths[n // 2 - 1] + lengths[n // 2])
    cell = med if med > 0 else 1.0

    def key(x: float, y: float) -> Tuple[int, int]:
        return (int(math.floor(x / cell)), int(math.floor(y / cell)))

    grid: Dict[Tuple[int, int], List[int]] = {}
    for i in range(n):
        a, b = pts[i], pts[i + 1]
        cells = {key(a[0], a[1]), key(b[0], b[1])}
        for c in cells:
            grid.setdefault(c, []).append(i)

    hits = set()
    for i in range(n):
        a, b = pts[i], pts[i + 1]
        cx0, cy0 = key(a[0], a[1])
        cx1, cy1 = key(b[0], b[1])
        neigh = set()
        for cx in range(min(cx0, cx1) - 1, max(cx0, cx1) + 2):
            for cy in range(min(cy0, cy1) - 1, max(cy0, cy1) + 2):
                neigh.update(grid.get((cx, cy), ()))
        for j in neigh:
            if j <= i + 1:  # skip self + adjacent (and already-tested pairs)
                continue
            if _segments_cross_2d(a, b, pts[j], pts[j + 1]):
                hits.add((i, j))
    return sorted(hits)
