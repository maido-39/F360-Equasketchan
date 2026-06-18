"""EquationCurve add-in entry (MS-1).

Adds two buttons to Sketch > Create:
  * "Equation Curve"      — create a math-driven curve from a dialog.
  * "Edit Equation Curve" — select an existing eqcurve spline, re-open the SAME
    dialog with every field restored losslessly, and rebuild on OK (FR-11.2 /
    AC-5). The CurveDef is read back from the stored attribute, never derived
    from geometry (ARC-4).

Full timeline associativity (a Custom Feature that auto-recomputes when a
referenced parameter changes) is MS-2 — see custom_feature.py.
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

# make the package importable when run as an add-in
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import dialog  # noqa: E402  (sibling module in this add-in folder)
from eqcurve import adapter  # noqa: E402

_app = None
_ui = None
_handlers = []
CREATE_ID = "eqcurve_create"
EDIT_ID = "eqcurve_edit"
PANEL_ID = "SketchCreatePanel"


# ---- helpers --------------------------------------------------------------

def _active_sketch(design):
    sk = design.activeEditObject
    if isinstance(sk, adsk.fusion.Sketch):
        return sk
    return design.rootComponent.sketches.add(design.rootComponent.xYConstructionPlane)


def _selected_eqcurve():
    """Return (spline, CurveDef) for the first selected eqcurve spline, or None."""
    sels = _ui.activeSelections
    for i in range(sels.count):
        ent = sels.item(i).entity
        if adapter.is_eqcurve(ent):
            cd = adapter.read_definition(ent)
            if cd is not None:
                return ent, cd
    return None


# ---- create ---------------------------------------------------------------

class _CreateHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            dialog.build_inputs(cmd.commandInputs, None)
            on_exec = _CreateExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            _ui.messageBox("Create dialog failed:\n" + traceback.format_exc())


class _CreateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            design = adsk.fusion.Design.cast(_app.activeProduct)
            sk = _active_sketch(design)
            params = adapter.read_design_params(design)
            adapter.build_curve_runs(sk, cd, params)
        except Exception:
            _ui.messageBox("Equation Curve failed:\n" + traceback.format_exc())


# ---- edit (selection-based, lossless) -------------------------------------

class _EditHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            sel = _selected_eqcurve()
            if sel is None:
                inputs.addTextBoxCommandInput(
                    "hint", "",
                    "Select an Equation Curve spline first, then run Edit.", 2, True,
                )
                return
            spline, cd = sel
            dialog.build_inputs(inputs, cd)
            on_exec = _EditExecuteHandler(spline)
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            _ui.messageBox("Edit dialog failed:\n" + traceback.format_exc())


class _EditExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, spline):
        super().__init__()
        self._spline = spline

    def notify(self, args):
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            design = adsk.fusion.Design.cast(_app.activeProduct)
            params = adapter.read_design_params(design)
            siblings = adapter.sibling_eqcurve_splines(self._spline)
            adapter.rebuild_curve(siblings, cd, params)
        except Exception:
            _ui.messageBox("Edit Equation Curve failed:\n" + traceback.format_exc())


# ---- add-in lifecycle -----------------------------------------------------

def _ensure_button(cmd_id, name, tooltip, handler):
    cmd_def = _ui.commandDefinitions.itemById(cmd_id)
    if not cmd_def:
        cmd_def = _ui.commandDefinitions.addButtonDefinition(cmd_id, name, tooltip)
    cmd_def.commandCreated.add(handler)
    _handlers.append(handler)
    panel = _ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and not panel.controls.itemById(cmd_id):
        panel.controls.addCommand(cmd_def)
    return cmd_def


def run(context):
    global _app, _ui
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    try:
        _ensure_button(CREATE_ID, "Equation Curve",
                       "Create a math-driven curve", _CreateHandler())
        _ensure_button(EDIT_ID, "Edit Equation Curve",
                       "Re-open the selected equation curve to edit it", _EditHandler())
    except Exception:
        if _ui:
            _ui.messageBox("Add-in run failed:\n" + traceback.format_exc())


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        for cmd_id in (CREATE_ID, EDIT_ID):
            if panel:
                ctrl = panel.controls.itemById(cmd_id)
                if ctrl:
                    ctrl.deleteMe()
            cmd_def = _ui.commandDefinitions.itemById(cmd_id)
            if cmd_def:
                cmd_def.deleteMe()
    except Exception:
        if _ui:
            _ui.messageBox("Add-in stop failed:\n" + traceback.format_exc())
