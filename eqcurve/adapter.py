"""Fusion adapter — the only adsk-dependent part of eqcurve.

Keeps unit conversion (mm -> cm) and all adsk calls in one place so the rest of
the package stays testable without Fusion. Imported only inside Fusion.
"""

from __future__ import annotations

from typing import Mapping, Optional

import adsk.core
import adsk.fusion

from .core import CurveDef, sample, is_effectively_closed

_ATTR_GROUP = "eqcurve"
_ATTR_DEF = "curvedef_json"
MM_TO_CM = 0.1  # Fusion internal unit is cm


def read_design_params(design: "adsk.fusion.Design") -> dict:
    """Snapshot all user parameters as a {name: value_in_internal_units} dict.

    Values are taken from each parameter's `.value` (internal units). Length
    params therefore arrive in cm; expose them as-is and let equations be
    written consistently. For most curve work users pass dimensionless or
    mm-intent constants, so this is usually fine; document the convention.
    """
    out = {}
    for p in design.userParameters:
        try:
            out[p.name] = p.value
        except Exception:
            pass
    return out


def build_curve(
    sketch: "adsk.fusion.Sketch",
    cd: CurveDef,
    params: Optional[Mapping[str, float]] = None,
) -> "adsk.fusion.SketchFittedSpline":
    """Evaluate `cd` and create a fitted spline in `sketch`.

    Stores the CurveDef JSON as an attribute on the resulting spline so it can
    be re-opened/edited losslessly later.
    """
    pts_mm = sample(cd, params)
    coll = adsk.core.ObjectCollection.create()
    for x, y, z in pts_mm:
        coll.add(adsk.core.Point3D.create(x * MM_TO_CM, y * MM_TO_CM, z * MM_TO_CM))

    spline = sketch.sketchCurves.sketchFittedSplines.add(coll)
    try:
        spline.isClosed = bool(cd.closed or is_effectively_closed(pts_mm))
    except Exception:
        pass  # not all spline kinds expose isClosed identically

    # persist definition for re-edit (FR-11.4: lossless, stored not re-derived)
    spline.attributes.add(_ATTR_GROUP, _ATTR_DEF, cd.to_json())
    return spline


def read_definition(entity) -> Optional[CurveDef]:
    """Return the CurveDef stored on a sketch entity, if any."""
    attr = entity.attributes.itemByName(_ATTR_GROUP, _ATTR_DEF)
    if attr is None:
        return None
    return CurveDef.from_json(attr.value)
