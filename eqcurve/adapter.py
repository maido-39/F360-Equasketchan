"""Fusion adapter — the only adsk-dependent part of eqcurve.

Keeps unit conversion (mm -> cm) and all adsk calls in one place so the rest of
the package stays testable without Fusion. Imported only inside Fusion.
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Tuple

import adsk.core
import adsk.fusion

from .core import CurveDef, runs_for, is_effectively_closed, decimate

_ATTR_GROUP = "eqcurve"
_ATTR_DEF = "curvedef_json"
_ATTR_MARK = "is_eqcurve"
MM_TO_CM = 0.1  # Fusion internal unit is cm
# Max fit points per spline handed to Fusion. The solver's cost is strongly
# superlinear for closed/cusped curves (~0.26s @100, 6s @300, 15s @400, minutes
# @800), so cap the fit to keep create/recompute responsive (FR-13.4). Sampling
# is unaffected — only the spline fit is coarsened.
MAX_SPLINE_POINTS = 300


# ---- units (FR-8.5) -------------------------------------------------------

def _is_length_unit(um, unit: str) -> bool:
    """True if `unit` is a length dimension (cm/mm/in/m...), via a convert probe.

    Angle (deg/rad) and unitless ("") raise/short-circuit, so this cleanly
    separates length params (which we rescale to mm) from the rest.
    """
    if not unit:
        return False
    try:
        um.convert(1.0, unit, "mm")
        return True
    except Exception:
        return False


def _param_value_mm(p, um) -> float:
    """A user parameter's value in the curve's working unit (mm) when it is a
    length, else its raw internal value (angles in rad, unitless as-is).

    Length params arrive in internal cm; we convert cm -> mm so an expression
    that writes `D3` for a 50 mm parameter sees `50`, not `5` (decision 2).
    """
    try:
        unit = p.unit
    except Exception:
        unit = ""
    if _is_length_unit(um, unit):
        # internal length unit is cm (PC-4 / R-4); fall back to x10 if needed.
        try:
            return um.convert(p.value, "cm", "mm")
        except Exception:
            return p.value * 10.0
    return p.value


def read_design_params(design: "adsk.fusion.Design") -> dict:
    """Snapshot user parameters as {name: value} for substitution into equations.

    Length params are returned in mm (unit-safe, FR-8.5); angle/unitless params
    keep their internal value. Conversion happens only here, at the adapter
    boundary (ARC-3).
    """
    um = design.unitsManager
    out = {}
    for p in design.userParameters:
        try:
            out[p.name] = _param_value_mm(p, um)
        except Exception:
            try:
                out[p.name] = p.value
            except Exception:
                pass
    return out


def read_design_params_typed(design: "adsk.fusion.Design") -> dict:
    """Like read_design_params but values carry their unit: {name: (value, unit)}."""
    um = design.unitsManager
    out = {}
    for p in design.userParameters:
        try:
            out[p.name] = (_param_value_mm(p, um), p.unit)
        except Exception:
            pass
    return out


# ---- geometry -------------------------------------------------------------

def _add_spline(sketch, run, cd: CurveDef, single_run: bool):
    run = decimate(run, MAX_SPLINE_POINTS)  # FR-13.4 performance guard
    coll = adsk.core.ObjectCollection.create()
    for x, y, z in run:
        coll.add(adsk.core.Point3D.create(x * MM_TO_CM, y * MM_TO_CM, z * MM_TO_CM))
    spline = sketch.sketchCurves.sketchFittedSplines.add(coll)
    if single_run:
        try:
            spline.isClosed = bool(cd.closed or is_effectively_closed(run))
        except Exception:
            pass  # not all spline kinds expose isClosed identically
    # persist definition on EVERY run spline so re-edit works from any selection
    # (ARC-4: stored, never reverse-derived from geometry).
    spline.attributes.add(_ATTR_GROUP, _ATTR_DEF, cd.to_json())
    spline.attributes.add(_ATTR_GROUP, _ATTR_MARK, "1")
    return spline


def build_curve_runs(
    sketch: "adsk.fusion.Sketch",
    cd: CurveDef,
    params: Optional[Mapping[str, float]] = None,
) -> List["adsk.fusion.SketchFittedSpline"]:
    """Evaluate `cd` and create one fitted spline per run (segmented at
    singularities/jumps, so e.g. tan never bridges its asymptotes)."""
    runs = runs_for(cd, params)
    single = len(runs) == 1
    return [_add_spline(sketch, run, cd, single) for run in runs]


def build_curve(
    sketch: "adsk.fusion.Sketch",
    cd: CurveDef,
    params: Optional[Mapping[str, float]] = None,
) -> "adsk.fusion.SketchFittedSpline":
    """Back-compatible single-handle build; returns the first run's spline."""
    return build_curve_runs(sketch, cd, params)[0]


def rebuild_curve(
    splines, cd: CurveDef, params: Optional[Mapping[str, float]] = None,
) -> List["adsk.fusion.SketchFittedSpline"]:
    """Delete the given eqcurve spline(s) and rebuild from `cd` in the same sketch.

    Accepts one spline or an iterable of them (a multi-run curve). Used by the
    MS-1 selection-based re-edit; MS-2 rebuilds inside the base feature instead.
    """
    if not isinstance(splines, (list, tuple)):
        splines = [splines]
    sketch = splines[0].parentSketch
    for sp in splines:
        try:
            sp.deleteMe()
        except Exception:
            pass
    return build_curve_runs(sketch, cd, params)


# ---- definition read-back (re-edit) ---------------------------------------

def is_eqcurve(entity) -> bool:
    """True if `entity` carries the eqcurve marker attribute."""
    try:
        return entity.attributes.itemByName(_ATTR_GROUP, _ATTR_MARK) is not None
    except Exception:
        return False


def read_definition(entity) -> Optional[CurveDef]:
    """Return the CurveDef stored on a sketch entity, if any."""
    attr = entity.attributes.itemByName(_ATTR_GROUP, _ATTR_DEF)
    if attr is None:
        return None
    return CurveDef.from_json(attr.value)


def sibling_eqcurve_splines(spline) -> list:
    """All run splines in the same sketch sharing this spline's stored CurveDef.

    Lets the re-edit delete every arc of a multi-run curve, not just the picked
    one. Matches on the stored JSON (definitions are identical across runs).
    """
    out = []
    try:
        target = spline.attributes.itemByName(_ATTR_GROUP, _ATTR_DEF)
        if target is None:
            return [spline]
        for sp in spline.parentSketch.sketchCurves.sketchFittedSplines:
            a = sp.attributes.itemByName(_ATTR_GROUP, _ATTR_DEF)
            if a is not None and a.value == target.value:
                out.append(sp)
    except Exception:
        return [spline]
    return out or [spline]
