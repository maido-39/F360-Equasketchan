"""Shared command-dialog layer for the Equation Curve add-in.

`build_inputs` populates the dialog from a CurveDef (or defaults); `read_inputs`
reconstructs a CurveDef from the dialog; `apply_curvedef` overwrites existing
inputs (used by the preset picker). Create and Edit share all three, so a curve
re-opens with every field exactly as saved (FR-11.2, lossless round-trip).
"""

from __future__ import annotations

import ast

import adsk.core

from eqcurve.core import CurveDef, preset_names, curvedef_for
from eqcurve.core.evaluator import Evaluator, ExpressionError, reserved_names

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
_EXPR_FIELDS = ("ex", "ey", "ez", "tmin", "tmax", "samples",
                "ox", "oy", "oz", "rx", "ry", "rz")
_last_field = {"id": "ey"}
# design-parameter names known to the dialog, for live unknown-name detection
_known_params = {"names": []}
# cached for the per-keystroke validation path: the built-in NAME set and the
# function table are angle-invariant (only the lambda bodies differ rad vs deg),
# so one instance each is correct regardless of the Degrees toggle.
_RESERVED = reserved_names()
_EV = Evaluator(angle="rad")

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
    _known_params["names"] = list(param_names or [])

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
    # samples may be a plain count OR an expression (e.g. 10*N) — FR-8.3
    inputs.addStringValueInput("samples", "Samples (or expr)", str(cd.samples))
    o = cd.origin or {}
    inputs.addStringValueInput("ox", "Origin X", o.get("x", "0"))
    inputs.addStringValueInput("oy", "Origin Y", o.get("y", "0"))
    inputs.addStringValueInput("oz", "Origin Z", o.get("z", "0"))
    r = cd.rotation or {}
    inputs.addStringValueInput("rx", "Rotation X", r.get("x", "0"))
    inputs.addStringValueInput("ry", "Rotation Y", r.get("y", "0"))
    inputs.addStringValueInput("rz", "Rotation Z", r.get("z", "0"))

    # interactive placement: sketch plane + origin point (optional). The curve is
    # anchored to the picked point, so constraining/moving it moves the curve.
    plane_sel = inputs.addSelectionInput("plane", "Sketch plane",
                                         "Construction plane or planar face (optional)")
    plane_sel.addSelectionFilter("ConstructionPlanes")
    plane_sel.addSelectionFilter("PlanarFaces")
    plane_sel.setSelectionLimits(0, 1)
    pt_sel = inputs.addSelectionInput("origin_pt", "Origin point",
                                      "Sketch/construction point or vertex (optional)")
    pt_sel.addSelectionFilter("SketchPoints")
    pt_sel.addSelectionFilter("ConstructionPoints")
    pt_sel.addSelectionFilter("Vertices")
    pt_sel.setSelectionLimits(0, 1)

    inputs.addBoolValueInput("closed", "Closed", True, "", cd.closed)
    inputs.addBoolValueInput("deg", "Degrees", True, "", cd.angle == "deg")
    inputs.addBoolValueInput("adaptive", "Adaptive sampling", True, "", cd.adaptive)
    inputs.addStringValueInput("tol", "Fit tolerance mm (0=off)", str(cd.tolerance))
    # sketch-embed only: fix the spline points so the sketch is fully defined by
    # the equation (untick to leave it movable / under-defined).
    inputs.addBoolValueInput("fixcurve", "Fix to equation (fully define)", True, "", True)

    # live expression validation (FR-7.3): parses every field as you type and
    # flags syntax errors / unknown names before you commit.
    inputs.addTextBoxCommandInput("status", "Validation", "", 2, True)

    # collapsible tutorial / reference (FR-12.4/12.5 — examples + function list)
    grp = inputs.addGroupCommandInput("help", "Help & examples")
    grp.isExpanded = False
    h = grp.children
    h.addTextBoxCommandInput("help_howto", "How to", _HELP_HOWTO, 6, True)
    h.addTextBoxCommandInput("help_funcs", "Functions", _HELP_FUNCS, 5, True)
    h.addTextBoxCommandInput("help_examples", "Examples", _HELP_EXAMPLES, 5, True)

    _refresh_status(inputs)  # initial validation pass


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
    inputs.itemById("samples").value = str(cd.samples)
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
    elif cid == "preset":
        name = inputs.itemById("preset").selectedItem.name
        if name != _CUSTOM:
            apply_curvedef(inputs, curvedef_for(name))
    elif cid == "param_insert":
        sel = inputs.itemById("param_insert").selectedItem
        if sel and sel.name != _INSERT_HINT:
            fld = inputs.itemById(_last_field["id"])
            if fld is not None:
                cur = fld.value or ""
                fld.value = (cur + sel.name) if (not cur or cur[-1:] in " (+-*/^,") else (cur + "*" + sel.name)
            inputs.itemById("param_insert").listItems.item(0).isSelected = True  # reset
    _refresh_status(inputs)  # re-validate after every change (FR-7.3)


# expression-bearing fields validated live, with a friendly label each (FR-7.3)
_VALIDATE_FIELDS = (
    ("x(t)/r(t)", "ex"), ("y/r/theta", "ey"), ("z/phi/theta", "ez"),
    ("t min", "tmin"), ("t max", "tmax"), ("samples", "samples"),
    ("origin X", "ox"), ("origin Y", "oy"), ("origin Z", "oz"),
    ("rotation X", "rx"), ("rotation Y", "ry"), ("rotation Z", "rz"),
)


def _idents(expr: str):
    """Identifier names in an expression ({} on a syntax error)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _selected(inputs, fid: str) -> str:
    """Selected dropdown item name (''  on any failure)."""
    it = inputs.itemById(fid)
    try:
        return it.selectedItem.name if it is not None else ""
    except Exception:
        return ""


def _indep_var(inputs) -> str:
    """Independent variable, resolved EXACTLY as read_inputs does (so validation
    matches what the sampler will actually inject)."""
    vi = inputs.itemById("var")
    v = vi.value.strip() if (vi is not None and vi.value) else ""
    if v:
        return v
    return "a" if (_selected(inputs, "mode") == "explicit"
                   and _selected(inputs, "coord") == "polar") else "t"


def _validate_current(inputs: adsk.core.CommandInputs) -> str:
    """Parse every expression field; return an HTML status line (FR-7.3).

    Reports the first syntax error, else any names that are neither a built-in
    nor a known design parameter nor an injected variable, else OK.
    """
    var = _indep_var(inputs)
    # The sampler always injects x and a (setdefault), plus cd.var; it injects t
    # only when var=='t'. Mirror that exactly so the validator neither over- nor
    # under-reports (e.g. y=sin(t) in explicit mode with var='x' IS unknown).
    known = set(_known_params["names"]) | {var, "x", "a"}
    unknown = set()
    for label, fid in _VALIDATE_FIELDS:
        fld = inputs.itemById(fid)
        expr = (getattr(fld, "value", "") or "").strip() if fld is not None else ""
        if not expr:
            continue
        try:
            _EV.compile(expr)
        except ExpressionError as exc:
            return "<b>Error</b> in %s: %s" % (label, exc)
        for nm in _idents(expr):
            if nm not in _RESERVED and nm not in known:
                unknown.add(nm)
    if unknown:
        return ("<b>Note</b> &mdash; unrecognized name(s): %s. Define them in "
                "Parameters, or check spelling." % ", ".join(sorted(unknown)))
    return "<b>OK</b> &mdash; all expressions parse."


def _refresh_status(inputs: adsk.core.CommandInputs) -> None:
    """Update the Validation textbox; never let validation break the dialog."""
    st = inputs.itemById("status")
    if st is None:
        return
    try:
        st.formattedText = _validate_current(inputs)
    except Exception:
        try:
            st.formattedText = ""
        except Exception:
            pass


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
        samples=_samples_value(inputs.itemById("samples").value),
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


def _samples_value(text):
    """Parse the Samples field: a plain int when numeric, else the expression
    string (so it can reference a design parameter — FR-8.3)."""
    s = str(text).strip()
    try:
        return int(s)
    except (TypeError, ValueError):
        return s or 200
