"""Sampler: evaluate a CurveDef over its domain into 3D points (in MILLIMETRES).

The Fusion adapter converts mm -> cm (Fusion's internal unit) at the boundary,
keeping unit handling in exactly one place. adsk-free and pytest-friendly.

Two output shapes:
  * ``sample_runs`` / ``adaptive_sample_runs`` -> a list of *runs* (each a list
    of points). A new run starts at every domain singularity (tan asymptote,
    ln of a non-positive number, division by zero) and at every large positional
    jump between two finite neighbours. Each run becomes one fitted spline, so a
    curve like ``tan(x)`` over ``[-pi, pi]`` is drawn as several arcs instead of
    one spline wrongly bridging the asymptotes (FR-13.1, FR-4.2).
  * ``sample`` -> a single flat point list (back-compatible wrapper).

Sampling is deterministic (NFR-4); the adaptive mode refines by a fixed
midpoint-bisection rule, so identical input always yields identical points.

Coordinate conventions
----------------------
polar (2D):        x = r*cos(theta), y = r*sin(theta), z = 0
cylindrical (3D):  x = r*cos(theta), y = r*sin(theta), z = z
spherical (3D):    x = r*sin(phi)*cos(theta), y = r*sin(phi)*sin(theta), z = r*cos(phi)
Angles (theta/phi and the inputs to trig functions) honor CurveDef.angle.
"""

from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional, Tuple

from .curvedef import CurveDef
from .evaluator import Evaluator, ExpressionError

Point = Tuple[float, float, float]
Run = List[Point]

# A finite-to-finite step longer than this many times the median step starts a
# new run (catches tan-pole jumps where both neighbours happen to be finite).
_GAP_FACTOR = 8.0


class SamplingError(ValueError):
    pass


def _angle_to_rad(value: float, angle: str) -> float:
    return math.radians(value) if angle == "deg" else value


def _to_cartesian(coord: str, comps: Dict[str, float], angle: str) -> Point:
    if coord == "cartesian":
        return (comps.get("x", 0.0), comps.get("y", 0.0), comps.get("z", 0.0))
    if coord == "polar":
        r = comps["r"]
        th = _angle_to_rad(comps["theta"], angle)
        return (r * math.cos(th), r * math.sin(th), 0.0)
    if coord == "cylindrical":
        r = comps["r"]
        th = _angle_to_rad(comps["theta"], angle)
        return (r * math.cos(th), r * math.sin(th), comps.get("z", 0.0))
    if coord == "spherical":
        r = comps["r"]
        phi = _angle_to_rad(comps["phi"], angle)
        th = _angle_to_rad(comps["theta"], angle)
        return (
            r * math.sin(phi) * math.cos(th),
            r * math.sin(phi) * math.sin(th),
            r * math.cos(phi),
        )
    raise SamplingError(f"unknown coord system: {coord}")


def _component_keys(cd: CurveDef) -> List[str]:
    if cd.mode == "explicit":
        return ["y"] if cd.coord == "cartesian" else ["r"]
    if cd.coord == "cartesian":
        return ["x", "y"] if cd.dim == 2 else ["x", "y", "z"]
    if cd.coord == "polar":
        return ["r", "theta"]
    if cd.coord == "cylindrical":
        return ["r", "theta", "z"]
    if cd.coord == "spherical":
        return ["r", "phi", "theta"]
    raise SamplingError(f"unknown coord system: {cd.coord}")


def _dist(a: Point, b: Point) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _rotate(p: Point, rot: Point) -> Point:
    """Rotate a point by Euler angles (radians), order X then Y then Z."""
    rx, ry, rz = rot
    x, y, z = p
    if rx:
        c, s = math.cos(rx), math.sin(rx)
        y, z = y * c - z * s, y * s + z * c
    if ry:
        c, s = math.cos(ry), math.sin(ry)
        x, z = x * c + z * s, -x * s + z * c
    if rz:
        c, s = math.cos(rz), math.sin(rz)
        x, y = x * c - y * s, x * s + y * c
    return (x, y, z)


def _eval_one(
    cd: CurveDef, params: Mapping[str, float], ev: Evaluator,
    keys: List[str], u: float, origin: Point, rot: Point,
) -> Optional[Point]:
    """Evaluate the curve at one independent value; None at a singularity.

    Applies the local rotation then the origin translation (in mm)."""
    scope = dict(params)
    scope[cd.var] = u
    scope.setdefault("x", u)  # explicit cartesian convenience
    scope.setdefault("a", u)  # explicit polar convenience
    try:
        comps: Dict[str, float] = {}
        if cd.mode == "explicit":
            if cd.coord == "cartesian":
                comps["x"] = u
                comps["y"] = ev.eval(cd.exprs["y"], scope)
            else:  # polar explicit: r = f(a), theta = a
                comps["r"] = ev.eval(cd.exprs["r"], scope)
                comps["theta"] = u
        else:
            for k in keys:
                comps[k] = ev.eval(cd.exprs[k], scope)
        x, y, z = _to_cartesian(cd.coord, comps, cd.angle)
    except (ExpressionError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        return None
    if rot != (0.0, 0.0, 0.0):
        x, y, z = _rotate((x, y, z), rot)
    return (x + origin[0], y + origin[1], z + origin[2])


def _segment(raw: List[Optional[Point]], gap_factor: float = _GAP_FACTOR) -> List[Run]:
    """Split a raw point sequence into runs at None gaps and at large jumps."""
    runs: List[Run] = []
    cur: Run = []
    for p in raw:
        if p is None:
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append(p)
    if cur:
        runs.append(cur)

    out: List[Run] = []
    for run in runs:
        out.extend(_split_on_jumps(run, gap_factor))
    return [r for r in out if len(r) >= 2]


def _split_on_jumps(run: Run, gap_factor: float) -> List[Run]:
    if len(run) < 3:
        return [run]
    dists = [_dist(run[i], run[i + 1]) for i in range(len(run) - 1)]
    sd = sorted(dists)
    n = len(sd)
    median = sd[n // 2] if n % 2 else 0.5 * (sd[n // 2 - 1] + sd[n // 2])
    if median <= 0:
        return [run]
    thresh = gap_factor * median
    segs: List[Run] = []
    cur: Run = [run[0]]
    for i in range(len(run) - 1):
        if dists[i] > thresh:
            segs.append(cur)
            cur = [run[i + 1]]
        else:
            cur.append(run[i + 1])
    segs.append(cur)
    return segs


def _domain(cd: CurveDef, params: Mapping[str, float]):
    cd.validate()
    ev = Evaluator(angle=cd.angle)
    t0 = ev.eval(cd.t_min, params)
    t1 = ev.eval(cd.t_max, params)
    if not math.isfinite(t0) or not math.isfinite(t1):
        raise SamplingError("domain endpoints are not finite")
    if t0 == t1:
        raise SamplingError("t_min == t_max (empty domain)")
    origin = (
        ev.eval(cd.origin.get("x", "0"), params),
        ev.eval(cd.origin.get("y", "0"), params),
        ev.eval(cd.origin.get("z", "0"), params),
    )
    rotd = cd.rotation or {}
    rot = (
        _angle_to_rad(ev.eval(rotd.get("x", "0"), params), cd.angle),
        _angle_to_rad(ev.eval(rotd.get("y", "0"), params), cd.angle),
        _angle_to_rad(ev.eval(rotd.get("z", "0"), params), cd.angle),
    )
    return ev, t0, t1, origin, rot, _component_keys(cd)


def sample_runs(cd: CurveDef, params: Optional[Mapping[str, float]] = None) -> List[Run]:
    """Uniformly sample the curve, returning singularity-split runs (mm)."""
    params = dict(params or {})
    ev, t0, t1, origin, rot, keys = _domain(cd, params)
    n = cd.samples
    raw = [
        _eval_one(cd, params, ev, keys, t0 + (t1 - t0) * (i / (n - 1)), origin, rot)
        for i in range(n)
    ]
    runs = _segment(raw)
    if not runs:
        raise SamplingError("fewer than 2 finite points produced")
    return runs


def _turn_angle(a: Point, m: Point, b: Point) -> float:
    """Turning angle (radians) of the polyline a->m->b at m."""
    v1 = (m[0] - a[0], m[1] - a[1], m[2] - a[2])
    v2 = (b[0] - m[0], b[1] - m[1], b[2] - m[2])
    n1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2 + v1[2] ** 2)
    n2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2 + v2[2] ** 2)
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    dot = (v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]) / (n1 * n2)
    return math.acos(max(-1.0, min(1.0, dot)))


def adaptive_sample_runs(
    cd: CurveDef, params: Optional[Mapping[str, float]] = None,
    angle_tol_deg: float = 8.0, max_depth: int = 7, seed: int = 17,
) -> List[Run]:
    """Curvature-adaptive sampling by deterministic midpoint bisection (FR-10.2).

    Seeds a uniform grid, then recursively inserts the midpoint of any interval
    whose turning angle exceeds the tolerance (or that straddles a singularity),
    up to ``max_depth``. The set of sampled t-values is a pure function of the
    curve and the thresholds, so output is deterministic (NFR-4).
    """
    params = dict(params or {})
    ev, t0, t1, origin, rot, keys = _domain(cd, params)
    seed = max(2, min(seed, cd.samples))
    tol = math.radians(angle_tol_deg)

    def pt(u: float) -> Optional[Point]:
        return _eval_one(cd, params, ev, keys, u, origin, rot)

    ts = {t0 + (t1 - t0) * (i / (seed - 1)) for i in range(seed)}

    def bisect(ta: float, tb: float, depth: int) -> None:
        if depth >= max_depth:
            return
        tm = 0.5 * (ta + tb)
        ts.add(tm)
        pa, pm, pb = pt(ta), pt(tm), pt(tb)
        if pa is None or pm is None or pb is None:
            # straddles a singularity: localize it (bounded by depth)
            bisect(ta, tm, depth + 1)
            bisect(tm, tb, depth + 1)
        elif _turn_angle(pa, pm, pb) > tol:
            bisect(ta, tm, depth + 1)
            bisect(tm, tb, depth + 1)

    seeds = sorted(ts)
    for i in range(len(seeds) - 1):
        bisect(seeds[i], seeds[i + 1], 0)

    raw = [pt(u) for u in sorted(ts)]
    runs = _segment(raw)
    if not runs:
        raise SamplingError("fewer than 2 finite points produced")
    return runs


def runs_for(cd: CurveDef, params: Optional[Mapping[str, float]] = None) -> List[Run]:
    """Dispatch to adaptive or uniform run-sampling per CurveDef.adaptive."""
    return adaptive_sample_runs(cd, params) if cd.adaptive else sample_runs(cd, params)


def sample(cd: CurveDef, params: Optional[Mapping[str, float]] = None) -> List[Point]:
    """Flat point list (mm), back-compatible. Singularity samples are dropped.

    Honors CurveDef.adaptive. When closed, the start point is appended so the
    cloud reads as closed (the adapter also sets the spline's isClosed flag).
    """
    runs = runs_for(cd, params)
    pts: List[Point] = [p for run in runs for p in run]
    if len(pts) < 2:
        raise SamplingError("fewer than 2 finite points produced")
    if cd.closed and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def is_effectively_closed(pts: List[Point], tol: float = 1e-6) -> bool:
    if len(pts) < 3:
        return False
    a, b = pts[0], pts[-1]
    return all(abs(a[i] - b[i]) <= tol for i in range(3))
