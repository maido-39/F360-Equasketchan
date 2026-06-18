"""Shared command-dialog layer for the Equation Curve add-in.

`build_inputs` populates the dialog from a CurveDef (or defaults); `read_inputs`
reconstructs a CurveDef from the dialog; `apply_curvedef` overwrites existing
inputs (used by the preset picker). Create and Edit share all three, so a curve
re-opens with every field exactly as saved (FR-11.2, lossless round-trip).
"""

from __future__ import annotations

import adsk.core

from eqcurve.core import CurveDef, preset_names, curvedef_for

_TEXTLIST = adsk.core.DropDownStyles.TextListDropDownStyle
_CUSTOM = "(custom)"

_DEFAULT = CurveDef(
    mode="parametric", coord="cartesian", dim=2,
    exprs={"x": "t", "y": "sin(t)"}, var="t", t_min="0", t_max="2*pi", samples=200,
)

_MODES = ("parametric", "explicit")
_COORDS = ("cartesian", "polar", "cylindrical", "spherical")

_INSERT_HINT = "(insert parameter…)"
# expression-bearing fields; the last one edited receives an inserted parameter
_EXPR_FIELDS = ("ex", "ey", "ez", "tmin", "tmax", "ox", "oy", "oz", "rx", "ry", "rz")
_last_field = {"id": "ey"}

# Tutorial / reference text (Inventor Equation-Curve style). FR-12 tutorial+intuitive.
_HELP_HOWTO = (
    "Write each component as a formula in the independent variable "
    "<b>t</b> (parametric) or <b>x</b>/<b>a</b> (explicit). Reference any model "
    "parameter by its name, e.g. <b>D3*sin(t)</b>. Pick a <b>Preset</b> to "
    "autofill a worked example, or use <b>Insert parameter</b> to drop a "
    "parameter name into the last-edited field. Angles follow the Degrees "
    "toggle. t&nbsp;min/max may themselves be formulas (e.g. <b>2*pi*N</b>)."
)
_HELP_FUNCS = (
    "<b>Trig</b>: sin cos tan cot sec csc · asin acos atan atan2<br/>"
    "<b>Hyperbolic</b>: sinh cosh tanh · asinh acosh atanh<br/>"
    "<b>Exp/Log</b>: exp ln log log2 log10 sqrt cbrt pow<br/>"
    "<b>Misc</b>: abs floor ceil round sign min max hypot lerp mod<br/>"
    "<b>Constants</b>: pi e tau phi &nbsp;·&nbsp; <b>Operators</b>: + - * / ^ ( )"
)
_HELP_EXAMPLES = (
    "<b>Sine</b> (explicit cart.): y = D3*sin(D4*x)<br/>"
    "<b>Cardioid</b> (explicit polar): r = 10*(1+cos(a))<br/>"
    "<b>Helix</b> (param. cylindrical): r=10, theta=t, z=2*t<br/>"
    "<b>Catenary</b> (hyperbolic): y = 5*cosh(x/5)<br/>"
    "<b>Spiral spring</b>: r=R0+k*t, theta=t, z=pitch*t"
)


def _exprs_to_fields(cd: CurveDef):
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


def _select(dropdown, name):
    for it in dropdown.listItems:
        it.isSelected = (it.name == name)


def build_inputs(inputs: adsk.core.CommandInputs, cd: CurveDef = None,
                 param_names=None) -> None:
    cd = cd or _DEFAULT
    _last_field["id"] = "ey"

    pin = inputs.addDropDownCommandInput("preset", "Preset", _TEXTLIST)
    pin.listItems.add(_CUSTOM, True)
    for name in preset_names():
        pin.listItems.add(name, False)

    # parameter suggestion / autofill: insert an existing model parameter name
    ins = inputs.addDropDownCommandInput("param_insert", "Insert parameter", _TEXTLIST)
    ins.listItems.add(_INSERT_HINT, True)
    for nm in (param_names or []):
        ins.listItems.add(nm, False)

    mode_in = inputs.addDropDownCommandInput("mode", "Mode", _TEXTLIST)
    for name in _MODES:
        mode_in.listItems.add(name, name == cd.mode)
    coord_in = inputs.addDropDownCommandInput("coord", "Coordinates", _TEXTLIST)
    for name in _COORDS:
        coord_in.listItems.add(name, name == cd.coord)

    ex, ey, ez = _exprs_to_fields(cd)
    inputs.addStringValueInput("ex", "x(t) / r(t)", ex)
    inputs.addStringValueInput("ey", "y(t) / r(a) / theta(t)", ey)
    inputs.addStringValueInput("ez", "z(t) / phi(t) / theta(t)", ez)
    inputs.addStringValueInput("var", "Independent var", cd.var)
    inputs.addStringValueInput("tmin", "t min", cd.t_min)
    inputs.addStringValueInput("tmax", "t max", cd.t_max)
    inputs.addIntegerSpinnerCommandInput("samples", "Samples", 2, 20000, 1, cd.samples)
    o = cd.origin or {}
    inputs.addStringValueInput("ox", "Origin X", o.get("x", "0"))
    inputs.addStringValueInput("oy", "Origin Y", o.get("y", "0"))
    inputs.addStringValueInput("oz", "Origin Z", o.get("z", "0"))
    r = cd.rotation or {}
    inputs.addStringValueInput("rx", "Rotation X", r.get("x", "0"))
    inputs.addStringValueInput("ry", "Rotation Y", r.get("y", "0"))
    inputs.addStringValueInput("rz", "Rotation Z", r.get("z", "0"))
    inputs.addBoolValueInput("closed", "Closed", True, "", cd.closed)
    inputs.addBoolValueInput("deg", "Degrees", True, "", cd.angle == "deg")
    inputs.addBoolValueInput("adaptive", "Adaptive sampling", True, "", cd.adaptive)
    inputs.addStringValueInput("tol", "Fit tolerance mm (0=off)", str(cd.tolerance))

    # collapsible tutorial / reference (FR-12.4/12.5 — examples + function list)
    grp = inputs.addGroupCommandInput("help", "Help & examples")
    grp.isExpanded = False
    h = grp.children
    h.addTextBoxCommandInput("help_howto", "How to", _HELP_HOWTO, 6, True)
    h.addTextBoxCommandInput("help_funcs", "Functions", _HELP_FUNCS, 5, True)
    h.addTextBoxCommandInput("help_examples", "Examples", _HELP_EXAMPLES, 5, True)


def apply_curvedef(inputs: adsk.core.CommandInputs, cd: CurveDef) -> None:
    """Overwrite already-created inputs from a CurveDef (e.g. a chosen preset)."""
    _select(inputs.itemById("mode"), cd.mode)
    _select(inputs.itemById("coord"), cd.coord)
    ex, ey, ez = _exprs_to_fields(cd)
    inputs.itemById("ex").value = ex
    inputs.itemById("ey").value = ey
    inputs.itemById("ez").value = ez
    inputs.itemById("var").value = cd.var
    inputs.itemById("tmin").value = cd.t_min
    inputs.itemById("tmax").value = cd.t_max
    inputs.itemById("samples").value = cd.samples
    o = cd.origin or {}
    inputs.itemById("ox").value = o.get("x", "0")
    inputs.itemById("oy").value = o.get("y", "0")
    inputs.itemById("oz").value = o.get("z", "0")
    r = cd.rotation or {}
    inputs.itemById("rx").value = r.get("x", "0")
    inputs.itemById("ry").value = r.get("y", "0")
    inputs.itemById("rz").value = r.get("z", "0")
    inputs.itemById("closed").value = cd.closed
    inputs.itemById("deg").value = (cd.angle == "deg")
    inputs.itemById("adaptive").value = cd.adaptive
    inputs.itemById("tol").value = str(cd.tolerance)


def on_input_changed(inputs: adsk.core.CommandInputs, changed_input) -> None:
    """Handle the dialog's live interactions (call from inputChanged):

    * remember the last-edited expression field (insert target),
    * apply a chosen Preset, and
    * insert a chosen parameter name into the last-edited field (autofill).
    """
    cid = changed_input.id
    if cid in _EXPR_FIELDS:
        _last_field["id"] = cid
        return
    if cid == "preset":
        name = inputs.itemById("preset").selectedItem.name
        if name != _CUSTOM:
            apply_curvedef(inputs, curvedef_for(name))
        return
    if cid == "param_insert":
        sel = inputs.itemById("param_insert").selectedItem
        if sel and sel.name != _INSERT_HINT:
            fld = inputs.itemById(_last_field["id"])
            if fld is not None:
                cur = fld.value or ""
                fld.value = (cur + sel.name) if (not cur or cur[-1:] in " (+-*/^,") else (cur + "*" + sel.name)
            inputs.itemById("param_insert").listItems.item(0).isSelected = True  # reset


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
        "a" if (mode == "explicit" and coord == "polar") else "t")
    return CurveDef(
        mode=mode, coord=coord, dim=dim, angle="deg" if deg else "rad",
        exprs=exprs, var=var,
        t_min=inputs.itemById("tmin").value, t_max=inputs.itemById("tmax").value,
        samples=inputs.itemById("samples").value,
        origin={"x": inputs.itemById("ox").value,
                "y": inputs.itemById("oy").value,
                "z": inputs.itemById("oz").value},
        rotation={"x": inputs.itemById("rx").value,
                  "y": inputs.itemById("ry").value,
                  "z": inputs.itemById("rz").value},
        closed=inputs.itemById("closed").value,
        adaptive=inputs.itemById("adaptive").value,
        tolerance=_to_float(inputs.itemById("tol").value),
    )


def _to_float(text) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return 0.0
