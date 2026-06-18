"""Sampler: evaluate a CurveDef over its domain into a list of 3D points.

Output points are in MILLIMETRES. The Fusion adapter converts mm -> cm
(Fusion's internal unit) at the boundary, keeping unit handling in exactly one
place. adsk-free and pytest-friendly.

Coordinate conventions
----------------------
polar (2D):        x = r*cos(theta), y = r*sin(theta), z = 0
cylindrical (3D):  x = r*cos(theta), y = r*sin(theta), z = z
spherical (3D):    x = r*sin(phi)*cos(theta), y = r*sin(phi)*sin(theta), z = r*cos(phi)
Angles (theta/phi and the inputs to trig functions) honor CurveDef.angle.
"""

from __future__ import annotations

import math
from typing import Dict, List, Mapping, Tuple

from .curvedef import CurveDef
from .evaluator import Evaluator, ExpressionError

Point = Tuple[float, float, float]


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


def sample(cd: CurveDef, params: Mapping[str, float] | None = None) -> List[Point]:
    """Evaluate the curve. Returns a list of finite (x,y,z) points in mm.

    Non-finite samples (domain singularities such as tan() asymptotes, log of
    a non-positive number, division by zero) are skipped rather than crashing,
    so e.g. tan over [-pi, pi] yields a valid (gapped) point set.
    """
    cd.validate()
    params = dict(params or {})
    ev = Evaluator(angle=cd.angle)

    # domain endpoints may themselves be expressions referencing params
    t0 = ev.eval(cd.t_min, params)
    t1 = ev.eval(cd.t_max, params)
    if not math.isfinite(t0) or not math.isfinite(t1):
        raise SamplingError("domain endpoints are not finite")
    if t0 == t1:
        raise SamplingError("t_min == t_max (empty domain)")

    # independent variable: 't' for parametric; for explicit cartesian it's the
    # x sweep, for explicit polar it's the angle 'a'. We expose it under cd.var
    # AND under 'x'/'a' so explicit expressions can use the natural name.
    keys = _component_keys(cd)
    ox = ev.eval(cd.origin.get("x", "0"), params)
    oy = ev.eval(cd.origin.get("y", "0"), params)
    oz = ev.eval(cd.origin.get("z", "0"), params)

    pts: List[Point] = []
    n = cd.samples
    for i in range(n):
        u = t0 + (t1 - t0) * (i / (n - 1))
        scope = dict(params)
        scope[cd.var] = u
        scope.setdefault("x", u)  # explicit cartesian convenience
        scope.setdefault("a", u)  # explicit polar convenience
        try:
            comps: Dict[str, float] = {}
            if cd.mode == "explicit":
                # independent var supplies the first coordinate directly
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
            continue
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        pts.append((x + ox, y + oy, z + oz))

    if len(pts) < 2:
        raise SamplingError("fewer than 2 finite points produced")

    if cd.closed and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def is_effectively_closed(pts: List[Point], tol: float = 1e-6) -> bool:
    if len(pts) < 3:
        return False
    a, b = pts[0], pts[-1]
    return all(abs(a[i] - b[i]) <= tol for i in range(3))
