"""Preset curve catalog (spec v0.1 section 14, FR-12.4).

adsk-free. Each preset is a ready-to-sample CurveDef with concrete constants, so
picking one in the dialog draws immediately. The UI fills the dialog fields from
these; the user can then tweak any value or swap in design parameters.
"""

from __future__ import annotations

from typing import Dict, List

from .curvedef import CurveDef

# (display name, CurveDef kwargs). Order is the dropdown order.
_PRESETS: List[tuple] = [
    ("Sine wave", dict(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "10 * sin(x)"}, var="x", t_min="0", t_max="2*pi", samples=200)),
    ("Archimedean spiral", dict(
        mode="parametric", coord="polar", dim=2,
        exprs={"r": "1 + 0.5*t", "theta": "t"}, var="t", t_min="0", t_max="6*pi", samples=400)),
    ("Logarithmic spiral", dict(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "exp(0.15*t)*cos(t)", "y": "exp(0.15*t)*sin(t)"},
        var="t", t_min="0", t_max="6*pi", samples=400)),
    ("Rose curve", dict(
        mode="explicit", coord="polar", dim=2,
        exprs={"r": "10 * cos(3*a)"}, var="a", t_min="0", t_max="2*pi", samples=400, closed=True)),
    ("Cardioid", dict(
        mode="explicit", coord="polar", dim=2,
        exprs={"r": "10 * (1 + cos(a))"}, var="a", t_min="0", t_max="2*pi", samples=361, closed=True)),
    ("Catenary", dict(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "5 * cosh(x / 5)"}, var="x", t_min="-10", t_max="10", samples=200)),
    ("Involute", dict(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "5*(cos(t) + t*sin(t))", "y": "5*(sin(t) - t*cos(t))"},
        var="t", t_min="0", t_max="4*pi", samples=400)),
    ("Cycloid", dict(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "5*(t - sin(t))", "y": "5*(1 - cos(t))"},
        var="t", t_min="0", t_max="4*pi", samples=300)),
    ("Lissajous", dict(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "10*sin(3*t + pi/2)", "y": "10*sin(2*t)"},
        var="t", t_min="0", t_max="2*pi", samples=400, closed=True)),
    ("Conical spiral", dict(
        mode="parametric", coord="cylindrical", dim=3,
        exprs={"r": "t", "theta": "t", "z": "t"}, var="t", t_min="0", t_max="6*pi", samples=400)),
    ("Spherical spiral", dict(
        mode="parametric", coord="spherical", dim=3,
        exprs={"r": "10", "phi": "t", "theta": "10*t"}, var="t", t_min="0", t_max="pi", samples=400)),
    # --- deliverable showcases: closed gear profiles (extrudable) + a spring ---
    # Gear-shaped radial tooth profiles (single-equation; extrude into a gear).
    ("Cycloidal gear", dict(
        mode="explicit", coord="polar", dim=2,
        exprs={"r": "18 + 4*max(cos(11*a), 0)"},     # 11 rounded sprocket teeth
        var="a", t_min="0", t_max="2*pi", samples=300, closed=True)),
    ("Involute gear", dict(
        mode="explicit", coord="polar", dim=2,
        exprs={"r": "20 + 2.5*tanh(5*cos(16*a))"},   # 16 flat-topped spur teeth
        var="a", t_min="0", t_max="2*pi", samples=300, closed=True)),
    ("Conical spiral spring", dict(
        mode="parametric", coord="cylindrical", dim=3,
        exprs={"r": "8 + 0.5*t", "theta": "t", "z": "0.8*t"},
        var="t", t_min="0", t_max="6*pi", samples=240)),
]

_BY_NAME: Dict[str, dict] = {name: kw for name, kw in _PRESETS}


def preset_names() -> List[str]:
    return [name for name, _ in _PRESETS]


def curvedef_for(name: str) -> CurveDef:
    """Return a fresh CurveDef for the named preset (KeyError if unknown)."""
    return CurveDef(**_BY_NAME[name])
