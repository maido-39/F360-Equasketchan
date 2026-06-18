"""MS-2: Equation Curve as a parametric timeline Custom Feature.

Recipe verified live on build 2703.1.20 (see docs/CHANGES.md, C0 spike):
  create  -> baseFeatures.add -> startEdit -> sketch + fitted splines ->
             finishEdit; then customFeatures.createInput(cdef),
             addCustomParameter(ValueInput.createByString(<param>)) to mirror each
             referenced design parameter (its expression references the param, so
             editing the param re-fires compute) + addDependency(<param>);
             setStartAndEndFeatures(base, base); customFeatures.add(input).
             CurveDef JSON + base/sketch entityTokens are stored on cf.attributes.
  compute -> findEntityByToken(base/sketch) -> base.startEdit -> clear splines ->
             rebuild from the stored CurveDef + live params -> base.finishEdit.
  edit    -> editCommandId command restores the dialog from cf.attributes; on OK
             it overwrites the stored CurveDef and computeAll() rebuilds.
  regen   -> design.computeAll() (PC-8 fallback).
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

import dialog
from eqcurve import adapter
from eqcurve.core import CurveDef, referenced_names

CF_DEF_ID = "eqcurve_customfeature"
CREATE_ID = "eqcurve_create"
EDIT_ID = "eqcurve_edit"
REGEN_ID = "eqcurve_regen"
PANEL_ID = "SketchCreatePanel"

_GRP = "eqcurve"
ATTR_DEF = "curvedef_json"
ATTR_BASE = "base_token"
ATTR_SK = "sketch_token"
_ICON_FOLDER = os.path.dirname(__file__)  # any existing dir (create() requires one)

_app = None
_ui = None
_handlers = []
_cdef = None


# ---- helpers --------------------------------------------------------------

def _design():
    return adsk.fusion.Design.cast(_app.activeProduct)


def _clear_splines(sketch):
    sps = sketch.sketchCurves.sketchFittedSplines
    for i in range(sps.count - 1, -1, -1):
        sps.item(i).deleteMe()


def _find_eqcurve_feature():
    """The selected eqcurve custom feature (for the double-click Edit command)."""
    sels = _ui.activeSelections
    for i in range(sels.count):
        ent = sels.item(i).entity
        cf = adsk.fusion.CustomFeature.cast(ent)
        if cf and cf.attributes.itemByName(_GRP, ATTR_DEF) is not None:
            return cf
    return None


# ---- compute --------------------------------------------------------------

class _ComputeHandler(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        base = None
        try:
            cf = args.customFeature
            design = _design()
            da = cf.attributes.itemByName(_GRP, ATTR_DEF)
            ba = cf.attributes.itemByName(_GRP, ATTR_BASE)
            sa = cf.attributes.itemByName(_GRP, ATTR_SK)
            if not (da and ba and sa):
                return
            cd = CurveDef.from_json(da.value)
            base = design.findEntityByToken(ba.value)[0]
            sketch = design.findEntityByToken(sa.value)[0]
            params = adapter.read_design_params(design)
            base.startEdit()
            _clear_splines(sketch)
            adapter.build_curve_runs(sketch, cd, params)
            base.finishEdit()
        except Exception:
            try:
                if base is not None:
                    base.finishEdit()
            except Exception:
                pass


# ---- create ---------------------------------------------------------------

class _CreateCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            dialog.build_inputs(cmd.commandInputs, None)
            h = _CreateExecute()
            cmd.execute.add(h)
            _handlers.append(h)
        except Exception:
            _ui.messageBox("Create dialog failed:\n" + traceback.format_exc())


class _CreateExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            create_feature(_design(), cd)
        except Exception:
            _ui.messageBox("Equation Curve failed:\n" + traceback.format_exc())


def create_feature(design, cd, params=None):
    """Build the curve inside a base feature and wrap it in a Custom Feature.

    Factored out of the command handler so the integration harness can drive it
    without the dialog. Returns the created CustomFeature.
    """
    comp = design.activeComponent
    if params is None:
        params = adapter.read_design_params(design)

    # geometry inside a base feature (PC-5 supported compute path)
    base = comp.features.baseFeatures.add()
    base.startEdit()
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    adapter.build_curve_runs(sketch, cd, params)
    base.finishEdit()
    base_tok, sk_tok = base.entityToken, sketch.entityToken

    cfin = comp.features.customFeatures.createInput(_cdef)
    _mirror_params(design, cfin, cd)
    cfin.setStartAndEndFeatures(base, base)
    cf = comp.features.customFeatures.add(cfin)

    cf.attributes.add(_GRP, ATTR_DEF, cd.to_json())
    cf.attributes.add(_GRP, ATTR_BASE, base_tok)
    cf.attributes.add(_GRP, ATTR_SK, sk_tok)
    return cf


def _mirror_params(design, cfin, cd):
    """Mirror each referenced design param as a custom param whose expression
    references it, plus a dependency — so editing the param re-fires compute
    (FR-8.2). Best-effort: a missing/odd-unit param is skipped, not fatal."""
    for nm in sorted(referenced_names(cd)):
        try:
            p = design.allParameters.itemByName(nm)
        except Exception:
            p = None
        if p is None:
            continue
        unit = ""
        try:
            unit = p.unit or ""
        except Exception:
            unit = ""
        try:
            cfin.addCustomParameter(
                "mir_" + nm, nm,
                adsk.core.ValueInput.createByString(nm), unit, True,
            )
        except Exception:
            pass
        try:
            cfin.addDependency("dep_" + nm, p)
        except Exception:
            pass


# ---- edit (double-click via editCommandId) --------------------------------

class _EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cf = _find_eqcurve_feature()
            if cf is None:
                cmd.commandInputs.addTextBoxCommandInput(
                    "hint", "", "Select the equation-curve feature, then Edit.", 2, True)
                return
            cd = CurveDef.from_json(cf.attributes.itemByName(_GRP, ATTR_DEF).value)
            dialog.build_inputs(cmd.commandInputs, cd)
            h = _EditExecute(cf)
            cmd.execute.add(h)
            _handlers.append(h)
        except Exception:
            _ui.messageBox("Edit dialog failed:\n" + traceback.format_exc())


class _EditExecute(adsk.core.CommandEventHandler):
    def __init__(self, cf):
        super().__init__()
        self._cf = cf

    def notify(self, args):
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            # overwrite the stored definition; compute rebuilds geometry. No PC-6
            # timeline rollback needed — the feature stays in place, only its
            # definition changes (validated: computeAll re-fires compute).
            self._cf.attributes.add(_GRP, ATTR_DEF, cd.to_json())
            _design().computeAll()
        except Exception:
            _ui.messageBox("Edit Equation Curve failed:\n" + traceback.format_exc())


# ---- regenerate fallback (PC-8) -------------------------------------------

class _RegenCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            h = _RegenExecute()
            args.command.execute.add(h)
            _handlers.append(h)
        except Exception:
            _ui.messageBox("Regenerate failed:\n" + traceback.format_exc())


class _RegenExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _design().computeAll()
        except Exception:
            _ui.messageBox("Regenerate failed:\n" + traceback.format_exc())


# ---- registration ---------------------------------------------------------

def _button(cmd_id, name, tooltip, handler, add_to_panel=True):
    cmd_def = _ui.commandDefinitions.itemById(cmd_id)
    if not cmd_def:
        cmd_def = _ui.commandDefinitions.addButtonDefinition(cmd_id, name, tooltip)
    cmd_def.commandCreated.add(handler)
    _handlers.append(handler)
    if add_to_panel:
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        if panel and not panel.controls.itemById(cmd_id):
            panel.controls.addCommand(cmd_def)
    return cmd_def


def register(app, ui):
    global _app, _ui, _cdef
    _app, _ui = app, ui
    # edit + regen commands must exist BEFORE editCommandId is set
    _button(EDIT_ID, "Edit Equation Curve",
            "Edit the selected equation-curve feature", _EditCreated(), add_to_panel=False)
    _button(REGEN_ID, "Regenerate Equation Curves",
            "Recompute all equation curves (PC-8 fallback)", _RegenCreated())
    _button(CREATE_ID, "Equation Curve",
            "Create a parametric math-driven curve", _CreateCreated())

    # A CustomFeatureDefinition cannot be deleted and create() rejects a
    # duplicate id, so cache it (and its compute handler, to keep it alive)
    # across add-in reloads / dev Stop-Run cycles via the never-reloaded `sys`.
    _key = "_eqcurve_cdef_" + CF_DEF_ID
    cached = getattr(sys, _key, None)
    if cached is not None:
        _cdef = cached
    else:
        _cdef = adsk.fusion.CustomFeatureDefinition.create(
            CF_DEF_ID, "Equation Curve", _ICON_FOLDER)
        ch = _ComputeHandler()
        _cdef.customFeatureCompute.add(ch)
        setattr(sys, _key, _cdef)
        setattr(sys, _key + "_handler", ch)
    _cdef.editCommandId = EDIT_ID


def unregister():
    panel = _ui.allToolbarPanels.itemById(PANEL_ID)
    for cmd_id in (CREATE_ID, EDIT_ID, REGEN_ID):
        try:
            if panel:
                ctrl = panel.controls.itemById(cmd_id)
                if ctrl:
                    ctrl.deleteMe()
            cd = _ui.commandDefinitions.itemById(cmd_id)
            if cd:
                cd.deleteMe()
        except Exception:
            pass
