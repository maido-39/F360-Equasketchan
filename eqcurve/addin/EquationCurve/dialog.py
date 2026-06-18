"""Shared command-dialog layer for the Equation Curve add-in.

`build_inputs` populates the dialog from a CurveDef (or sensible defaults);
`read_inputs` reconstructs a CurveDef from the dialog. Both the Create and Edit
commands use these, so a curve re-opens with every field exactly as saved
(FR-11.2, lossless round-trip).
"""

from __future__ import annotations

import adsk.core

from eqcurve.core import CurveDef

_TEXTLIST = adsk.core.DropDownStyles.TextListDropDownStyle

# Defaults shown when creating a new curve (no CurveDef to restore).
_DEFAULT = CurveDef(
    mode="parametric", coord="cartesian", dim=2,
    exprs={"x": "t", "y": "sin(t)"}, var="t", t_min="0", t_max="2*pi", samples=200,
)

_MODES = ("parametric", "explicit")
_COORDS = ("cartesian", "polar", "cylindrical", "spherical")


def _exprs_to_fields(cd: CurveDef):
    """Map a CurveDef's component expressions back to the (ex, ey, ez) fields."""
    e = cd.exprs or {}
    if cd.mode == "explicit":
        return ("", e.get("y" if cd.coord == "cartesian" else "r", ""), "")
    if cd.coord == "cartesian":
        return (e.get("x", ""), e.get("y", ""), e.get("z", ""))
    if cd.coord == "polar":
        return (e.get("r", ""), e.get("theta", ""), "")
    if cd.coord == "cylindrical":
        return (e.get("r", ""), e.get("theta", ""), e.get("z", ""))
    if cd.coord == "spherical":
        return (e.get("r", ""), e.get("phi", ""), e.get("theta", ""))
    return ("", "", "")


def build_inputs(inputs: adsk.core.CommandInputs, cd: CurveDef = None) -> None:
    cd = cd or _DEFAULT
    ex, ey, ez = _exprs_to_fields(cd)

    mode_in = inputs.addDropDownCommandInput("mode", "Mode", _TEXTLIST)
    for name in _MODES:
        mode_in.listItems.add(name, name == cd.mode)
    coord_in = inputs.addDropDownCommandInput("coord", "Coordinates", _TEXTLIST)
    for name in _COORDS:
        coord_in.listItems.add(name, name == cd.coord)

    inputs.addStringValueInput("ex", "x(t) / r(t)", ex)
    inputs.addStringValueInput("ey", "y(t) / r(a) / theta(t)", ey)
    inputs.addStringValueInput("ez", "z(t) / phi(t) / theta(t)", ez)
    inputs.addStringValueInput("var", "Independent var", cd.var)
    inputs.addStringValueInput("tmin", "t min", cd.t_min)
    inputs.addStringValueInput("tmax", "t max", cd.t_max)
    inputs.addIntegerSpinnerCommandInput("samples", "Samples", 2, 20000, 1, cd.samples)
    origin = cd.origin or {}
    inputs.addStringValueInput("ox", "Origin X", origin.get("x", "0"))
    inputs.addStringValueInput("oy", "Origin Y", origin.get("y", "0"))
    inputs.addStringValueInput("oz", "Origin Z", origin.get("z", "0"))
    inputs.addBoolValueInput("closed", "Closed", True, "", cd.closed)
    inputs.addBoolValueInput("deg", "Degrees", True, "", cd.angle == "deg")
    inputs.addBoolValueInput("adaptive", "Adaptive sampling", True, "", cd.adaptive)


def read_inputs(inputs: adsk.core.CommandInputs) -> CurveDef:
    mode = inputs.itemById("mode").selectedItem.name
    coord = inputs.itemById("coord").selectedItem.name
    deg = inputs.itemById("deg").value
    dim = 2 if mode == "explicit" else (3 if coord in ("cylindrical", "spherical") else 2)

    ex = inputs.itemById("ex").value
    ey = inputs.itemById("ey").value
    ez = inputs.itemById("ez").value
    if mode == "explicit":
        exprs = {"y": ey} if coord == "cartesian" else {"r": ey}
    elif coord == "cartesian":
        exprs = {"x": ex, "y": ey} if dim == 2 else {"x": ex, "y": ey, "z": ez}
    elif coord == "polar":
        exprs = {"r": ex, "theta": ey}
    elif coord == "cylindrical":
        exprs = {"r": ex, "theta": ey, "z": ez}
    else:  # spherical
        exprs = {"r": ex, "phi": ey, "theta": ez}

    var = inputs.itemById("var").value.strip() or (
        "a" if (mode == "explicit" and coord == "polar") else "t"
    )
    return CurveDef(
        mode=mode, coord=coord, dim=dim, angle="deg" if deg else "rad",
        exprs=exprs, var=var,
        t_min=inputs.itemById("tmin").value, t_max=inputs.itemById("tmax").value,
        samples=inputs.itemById("samples").value,
        origin={
            "x": inputs.itemById("ox").value,
            "y": inputs.itemById("oy").value,
            "z": inputs.itemById("oz").value,
        },
        closed=inputs.itemById("closed").value,
        adaptive=inputs.itemById("adaptive").value,
    )
