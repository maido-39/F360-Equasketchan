"""EquationCurve add-in entry (MVP).

Adds a 'Equation Curve' button to Sketch > Create. The command collects a
CurveDef from a dialog, evaluates it against current user parameters, and draws
a fitted spline. The CurveDef is stored on the spline so it can be re-edited.

SCOPE NOTE
----------
This MVP creates the curve and stores its definition (re-openable). FULL
associativity — auto-recompute when a referenced parameter (e.g. D3) changes,
exposed as a timeline Custom Feature — is the next milestone. Per our research,
that requires the Custom Features API and only its narrow base-feature/sketch
compute path is reliable, so it is implemented separately once the MVP geometry
path is validated through the bridge.
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

# make the package importable when run as an add-in
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from eqcurve.core import CurveDef  # noqa: E402
from eqcurve import adapter  # noqa: E402

_app = None
_ui = None
_handlers = []
CMD_ID = "eqcurve_create"


class _CreateHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            inputs.addDropDownCommandInput("mode", "Mode", adsk.core.DropDownStyles.TextListDropDownStyle)
            m = inputs.itemById("mode").listItems
            m.add("parametric", True)
            m.add("explicit", False)

            inputs.addDropDownCommandInput("coord", "Coordinates", adsk.core.DropDownStyles.TextListDropDownStyle)
            c = inputs.itemById("coord").listItems
            for name in ("cartesian", "polar", "cylindrical", "spherical"):
                c.add(name, name == "cartesian")

            inputs.addStringValueInput("ex", "x(t) / —", "t")
            inputs.addStringValueInput("ey", "y(t) / r(a)", "sin(t)")
            inputs.addStringValueInput("ez", "z(t)", "0")
            inputs.addStringValueInput("tmin", "t min", "0")
            inputs.addStringValueInput("tmax", "t max", "2*pi")
            inputs.addIntegerSpinnerCommandInput("samples", "Samples", 2, 5000, 1, 200)
            inputs.addBoolValueInput("closed", "Closed", True, "", False)
            inputs.addBoolValueInput("deg", "Degrees", True, "", False)

            on_exec = _ExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            _ui.messageBox("Create failed:\n" + traceback.format_exc())


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            mode = inputs.itemById("mode").selectedItem.name
            coord = inputs.itemById("coord").selectedItem.name
            deg = inputs.itemById("deg").value
            dim = 3 if coord in ("cylindrical", "spherical") else 2

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

            cd = CurveDef(
                mode=mode, coord=coord, dim=dim,
                angle="deg" if deg else "rad",
                exprs=exprs,
                var="a" if (mode == "explicit" and coord == "polar") else "t",
                t_min=inputs.itemById("tmin").value,
                t_max=inputs.itemById("tmax").value,
                samples=inputs.itemById("samples").value,
                closed=inputs.itemById("closed").value,
            )

            design = adsk.fusion.Design.cast(_app.activeProduct)
            sk = design.activeEditObject
            if not isinstance(sk, adsk.fusion.Sketch):
                sk = design.rootComponent.sketches.add(
                    design.rootComponent.xYConstructionPlane
                )
            params = adapter.read_design_params(design)
            adapter.build_curve(sk, cd, params)
        except Exception:
            _ui.messageBox("Equation Curve failed:\n" + traceback.format_exc())


def run(context):
    global _app, _ui
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    try:
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            cmd_def = _ui.commandDefinitions.addButtonDefinition(
                CMD_ID, "Equation Curve", "Create a math-driven curve"
            )
        h = _CreateHandler()
        cmd_def.commandCreated.add(h)
        _handlers.append(h)

        panel = _ui.allToolbarPanels.itemById("SketchCreatePanel")
        if panel and not panel.controls.itemById(CMD_ID):
            panel.controls.addCommand(cmd_def)
    except Exception:
        if _ui:
            _ui.messageBox("Add-in run failed:\n" + traceback.format_exc())


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById("SketchCreatePanel")
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        if _ui:
            _ui.messageBox("Add-in stop failed:\n" + traceback.format_exc())
