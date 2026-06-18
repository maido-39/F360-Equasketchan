"""MS-2 + MS-3: Equation Curve as a parametric timeline Custom Feature.

Create / compute / edit recipe verified live on build 2703.1.20 (docs/CHANGES.md
C0 spike). MS-3 additions: preset picker, real-time preview, origin+rotation,
import/export, readable error messages, circular-reference guard.
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

import dialog
from eqcurve import adapter
from eqcurve.core import (
    CurveDef, referenced_names, circular_reference, runs_for,
)
from eqcurve.core import describe as _describe  # readable error text (FR-12.5)

CF_DEF_ID = "eqcurve_customfeature"
CREATE_ID = "eqcurve_create"
EDIT_ID = "eqcurve_edit"
REGEN_ID = "eqcurve_regen"
EXPORT_ID = "eqcurve_export"
IMPORT_ID = "eqcurve_import"
PANEL_ID = "SketchCreatePanel"

_GRP = "eqcurve"
ATTR_DEF = "curvedef_json"
ATTR_BASE = "base_token"
ATTR_SK = "sketch_token"
_ICON_FOLDER = os.path.dirname(__file__)
_MM_TO_CM = 0.1

_app = None
_ui = None
_handlers = []
_cdef = None
_preview_group = None


# ---- helpers --------------------------------------------------------------

def _design():
    return adsk.fusion.Design.cast(_app.activeProduct)


def _clear_splines(sketch):
    sps = sketch.sketchCurves.sketchFittedSplines
    for i in range(sps.count - 1, -1, -1):
        sps.item(i).deleteMe()


def _find_eqcurve_feature():
    sels = _ui.activeSelections
    for i in range(sels.count):
        cf = adsk.fusion.CustomFeature.cast(sels.item(i).entity)
        if cf and cf.attributes.itemByName(_GRP, ATTR_DEF) is not None:
            return cf
    return None


def _check_circular(design, cd):
    """Raise ValueError if the referenced design params form a cycle (FR-8.6)."""
    exprs = {}
    for p in design.userParameters:
        try:
            exprs[p.name] = p.expression
        except Exception:
            pass
    cyc = circular_reference(exprs, cd.angle) & referenced_names(cd)
    if cyc:
        raise ValueError("Circular parameter reference involving: " + ", ".join(sorted(cyc)))


def _clear_preview():
    global _preview_group
    if _preview_group is not None:
        try:
            _preview_group.deleteMe()
        except Exception:
            pass
        _preview_group = None


def _draw_preview(design, cd):
    """Transient custom-graphics polyline preview of the curve (FR-12.3)."""
    global _preview_group
    _clear_preview()
    runs = runs_for(cd, adapter.read_design_params(design))
    grp = design.rootComponent.customGraphicsGroups.add()
    for run in runs:
        flat = []
        for x, y, z in run:
            flat += [x * _MM_TO_CM, y * _MM_TO_CM, z * _MM_TO_CM]
        coords = adsk.fusion.CustomGraphicsCoordinates.create(flat)
        grp.addLines(coords, [], True)  # connected line strip
    _preview_group = grp


# ---- compute (verified) ---------------------------------------------------

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
            ic = _PresetChanged()
            cmd.inputChanged.add(ic)
            _handlers.append(ic)
            pv = _PreviewHandler()
            cmd.executePreview.add(pv)
            _handlers.append(pv)
            ex = _CreateExecute()
            cmd.execute.add(ex)
            _handlers.append(ex)
            de = _DestroyHandler()
            cmd.destroy.add(de)
            _handlers.append(de)
        except Exception:
            _ui.messageBox("Create dialog failed:\n" + traceback.format_exc())


class _PresetChanged(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            dialog.on_preset_changed(args.inputs, args.input)
        except Exception:
            pass  # preset fill is best-effort


class _PreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            _draw_preview(_design(), cd)
        except Exception:
            _clear_preview()  # invalid in-progress input -> no preview, no crash


class _DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _clear_preview()


class _CreateExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        _clear_preview()
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            create_feature(_design(), cd)
        except Exception as exc:
            _ui.messageBox("Equation Curve: " + _describe(exc))


def create_feature(design, cd, params=None):
    """Build the curve inside a base feature and wrap it in a Custom Feature.

    Factored out so the integration harness can drive it without the dialog.
    Returns the created CustomFeature.
    """
    _check_circular(design, cd)
    comp = design.activeComponent
    if params is None:
        params = adapter.read_design_params(design)

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
    for nm in sorted(referenced_names(cd)):
        try:
            p = design.allParameters.itemByName(nm)
        except Exception:
            p = None
        if p is None:
            continue
        try:
            unit = p.unit or ""
        except Exception:
            unit = ""
        try:
            cfin.addCustomParameter("mir_" + nm, nm,
                                    adsk.core.ValueInput.createByString(nm), unit, True)
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
            ic = _PresetChanged()
            cmd.inputChanged.add(ic)
            _handlers.append(ic)
            ex = _EditExecute(cf)
            cmd.execute.add(ex)
            _handlers.append(ex)
        except Exception:
            _ui.messageBox("Edit dialog failed:\n" + traceback.format_exc())


class _EditExecute(adsk.core.CommandEventHandler):
    def __init__(self, cf):
        super().__init__()
        self._cf = cf

    def notify(self, args):
        try:
            cd = dialog.read_inputs(args.command.commandInputs)
            self._cf.attributes.add(_GRP, ATTR_DEF, cd.to_json())
            _design().computeAll()
        except Exception as exc:
            _ui.messageBox("Edit Equation Curve: " + _describe(exc))


# ---- regenerate (PC-8) ----------------------------------------------------

class _RegenCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        h = _RegenExecute()
        args.command.execute.add(h)
        _handlers.append(h)


class _RegenExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _design().computeAll()
        except Exception as exc:
            _ui.messageBox("Regenerate: " + _describe(exc))


# ---- import / export (FR-12.6) --------------------------------------------

class _ExportCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cf = _find_eqcurve_feature()
            if cf is None:
                _ui.messageBox("Select an equation-curve feature to export.")
                return
            dlg = _ui.createFileDialog()
            dlg.title = "Export equation curve definition"
            dlg.filter = "JSON (*.json)"
            dlg.initialFilename = "equation_curve.json"
            if dlg.showSave() != adsk.core.DialogResults.DialogOK:
                return
            text = cf.attributes.itemByName(_GRP, ATTR_DEF).value
            with open(dlg.filename, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            _ui.messageBox("Export failed:\n" + traceback.format_exc())


class _ImportCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            dlg = _ui.createFileDialog()
            dlg.title = "Import equation curve definition"
            dlg.filter = "JSON (*.json)"
            if dlg.showOpen() != adsk.core.DialogResults.DialogOK:
                return
            with open(dlg.filename, "r", encoding="utf-8") as f:
                cd = CurveDef.from_json(f.read())
            create_feature(_design(), cd)
        except Exception as exc:
            _ui.messageBox("Import failed: " + _describe(exc))


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
    # edit/regen/import/export must exist before editCommandId references EDIT_ID
    _button(EDIT_ID, "Edit Equation Curve",
            "Edit the selected equation-curve feature", _EditCreated(), add_to_panel=False)
    _button(REGEN_ID, "Regenerate Equation Curves",
            "Recompute all equation curves (PC-8 fallback)", _RegenCreated())
    _button(EXPORT_ID, "Export Equation Curve",
            "Export the selected curve definition to JSON", _ExportCreated())
    _button(IMPORT_ID, "Import Equation Curve",
            "Create a curve from a JSON definition file", _ImportCreated())
    _button(CREATE_ID, "Equation Curve",
            "Create a parametric math-driven curve", _CreateCreated())

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
    _clear_preview()
    panel = _ui.allToolbarPanels.itemById(PANEL_ID)
    for cmd_id in (CREATE_ID, EDIT_ID, REGEN_ID, EXPORT_ID, IMPORT_ID):
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
