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
ATTR_PT = "origin_pt_token"     # selected origin point (interactive, movable)
ATTR_PLANE = "plane_token"      # selected sketch plane
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


def _point_world(ent):
    """World-space Point3D of a sketch point / construction point / vertex."""
    for attr in ("worldGeometry", "geometry"):
        g = getattr(ent, attr, None)
        if g is not None:
            return g
    return None


def _off_cm(sketch, pt_ent):
    """Placement offset (cm, in `sketch` space) from the chosen origin point.

    The curve is anchored here, so moving/constraining the point moves the curve.
    Returns (0,0,0) when no point is chosen (curve sits at the sketch origin)."""
    if pt_ent is None:
        return (0.0, 0.0, 0.0)
    try:
        w = _point_world(pt_ent)
        sp = sketch.modelToSketchSpace(w)
        return (sp.x, sp.y, 0.0)
    except Exception:
        return (0.0, 0.0, 0.0)


def _fix_spline(sp):
    """Fix a fitted spline's points so the sketch is fully defined by the
    equation (the curve can no longer be dragged out of shape)."""
    try:
        fp = sp.fitPoints
        for i in range(fp.count):
            fp.item(i).isFixed = True
    except Exception:
        try:
            sp.isFixed = True
        except Exception:
            pass


def _resolve(design, token):
    if not token:
        return None
    try:
        ents = design.findEntityByToken(token)
        return ents[0] if ents else None
    except Exception:
        return None


def _param_names():
    try:
        ups = _design().userParameters
        return [ups.item(i).name for i in range(ups.count)]
    except Exception:
        return []


def _find_eqcurve_feature():
    sels = _ui.activeSelections
    for i in range(sels.count):
        cf = adsk.fusion.CustomFeature.cast(sels.item(i).entity)
        if cf and cf.attributes.itemByName(_GRP, ATTR_DEF) is not None:
            return cf
    return None


def _find_eqcurve_spline():
    """A selected sketch-embedded equation-curve spline (re-editable in place)."""
    sels = _ui.activeSelections
    for i in range(sels.count):
        ent = sels.item(i).entity
        if adsk.fusion.SketchFittedSpline.cast(ent) and adapter.is_eqcurve(ent):
            return ent
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
            # the origin point comes from the custom-feature DEPENDENCY (Fusion
            # keeps that reference valid across moves/edits, unlike a raw token).
            pt_ent = None
            try:
                dep = cf.dependencies.itemById("dep_origin_pt")
                pt_ent = dep.entity if dep else None
            except Exception:
                pt_ent = None
            if pt_ent is None:
                pa = cf.attributes.itemByName(_GRP, ATTR_PT)
                pt_ent = _resolve(design, pa.value) if pa else None
            off = _off_cm(sketch, pt_ent)
            base.startEdit()
            _clear_splines(sketch)
            adapter.build_curve_runs(sketch, cd, params, off_cm=off)
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
            dialog.build_inputs(cmd.commandInputs, None, _param_names())
            ic = _PresetChanged()
            cmd.inputChanged.add(ic)
            _handlers.append(ic)
            pv = _PreviewHandler()
            cmd.executePreview.add(pv)
            _handlers.append(pv)
            # If a sketch is being edited, embed the curve INTO it; otherwise
            # create a parametric timeline Custom Feature.
            aeo = _design().activeEditObject
            active_sk = aeo if isinstance(aeo, adsk.fusion.Sketch) else None
            ex = _CreateExecute(active_sk)
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
            dialog.on_input_changed(args.inputs, args.input)
        except Exception:
            pass  # preset/insert helpers are best-effort


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


def _sel_entity(inputs, input_id):
    si = inputs.itemById(input_id)
    try:
        if si is not None and si.selectionCount > 0:
            return si.selection(0).entity
    except Exception:
        pass
    return None


class _CreateExecute(adsk.core.CommandEventHandler):
    def __init__(self, active_sketch=None):
        super().__init__()
        self._sk = active_sketch

    def notify(self, args):
        _clear_preview()
        try:
            inputs = args.command.commandInputs
            cd = dialog.read_inputs(inputs)
            design = _design()
            pt = _sel_entity(inputs, "origin_pt")
            if self._sk is not None:
                # SKETCH-EMBED: draw the equation curve into the active sketch.
                # build_curve_runs stamps the CurveDef + marker on each spline, so
                # the sketch is fully equation-defined and re-editable (select a
                # spline -> Edit Equation Curve). Origin point offset honored.
                splines = adapter.build_curve_runs(
                    self._sk, cd, adapter.read_design_params(design),
                    off_cm=_off_cm(self._sk, pt))
                fix = inputs.itemById("fixcurve")
                if fix is None or fix.value:  # default: fully define (fix points)
                    for sp in splines:
                        _fix_spline(sp)
            else:
                create_feature(design, cd,
                               plane_ent=_sel_entity(inputs, "plane"),
                               origin_pt_ent=pt)
        except Exception as exc:
            _ui.messageBox("Equation Curve: " + _describe(exc))


def create_feature(design, cd, params=None, plane_ent=None, origin_pt_ent=None):
    """Build the curve inside a base feature and wrap it in a Custom Feature.

    `plane_ent`     : construction plane / planar face to sketch on (default XY).
    `origin_pt_ent` : a sketch/construction point or vertex the curve is anchored
                      to — moving or constraining it moves the curve (FR-9.2/9.5).
    Factored out so the integration harness can drive it without the dialog.
    """
    _check_circular(design, cd)
    comp = design.activeComponent
    if params is None:
        params = adapter.read_design_params(design)

    plane = plane_ent or comp.xYConstructionPlane
    base = comp.features.baseFeatures.add()
    base.startEdit()
    sketch = comp.sketches.add(plane)
    adapter.build_curve_runs(sketch, cd, params, off_cm=_off_cm(sketch, origin_pt_ent))
    base.finishEdit()
    base_tok, sk_tok = base.entityToken, sketch.entityToken

    cfin = comp.features.customFeatures.createInput(_cdef)
    _mirror_params(design, cfin, cd)
    for dep_id, ent in (("plane", plane_ent), ("origin_pt", origin_pt_ent)):
        if ent is not None:
            try:
                cfin.addDependency("dep_" + dep_id, ent)
            except Exception:
                pass
    cfin.setStartAndEndFeatures(base, base)
    cf = comp.features.customFeatures.add(cfin)

    cf.attributes.add(_GRP, ATTR_DEF, cd.to_json())
    cf.attributes.add(_GRP, ATTR_BASE, base_tok)
    cf.attributes.add(_GRP, ATTR_SK, sk_tok)
    if origin_pt_ent is not None:
        cf.attributes.add(_GRP, ATTR_PT, origin_pt_ent.entityToken)
    if plane_ent is not None:
        cf.attributes.add(_GRP, ATTR_PLANE, plane_ent.entityToken)
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
            inputs = cmd.commandInputs
            # Double-click on a Custom Feature pre-selects it -> load directly.
            cf = _find_eqcurve_feature()
            if cf is not None:
                cd = CurveDef.from_json(cf.attributes.itemByName(_GRP, ATTR_DEF).value)
                dialog.build_inputs(inputs, cd, _param_names())
                ic = _PresetChanged()
                cmd.inputChanged.add(ic)
                _handlers.append(ic)
                ex = _EditExecute(cf)
                cmd.execute.add(ex)
                _handlers.append(ex)
                return
            # Manual Edit: pick the equation-curve spline inside the command (so it
            # works even when nothing is pre-selected — the reliable way).
            sel = inputs.addSelectionInput("target", "Equation curve",
                                           "Select an equation-curve spline to edit")
            sel.addSelectionFilter("SketchCurves")
            sel.setSelectionLimits(1, 1)
            dialog.build_inputs(inputs, None, _param_names())
            pre = _find_eqcurve_spline()
            if pre is not None:
                try:
                    sel.addSelection(pre)
                except Exception:
                    pass
                cd = adapter.read_definition(pre)
                if cd:
                    dialog.apply_curvedef(inputs, cd)
            ic = _EditInputChanged()
            cmd.inputChanged.add(ic)
            _handlers.append(ic)
            ex = _EditSplineExecute()
            cmd.execute.add(ex)
            _handlers.append(ex)
        except Exception:
            _ui.messageBox("Edit dialog failed:\n" + traceback.format_exc())


class _EditInputChanged(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id == "target":
                si = args.inputs.itemById("target")
                if si.selectionCount > 0 and adapter.is_eqcurve(si.selection(0).entity):
                    cd = adapter.read_definition(si.selection(0).entity)
                    if cd:
                        dialog.apply_curvedef(args.inputs, cd)
            else:
                dialog.on_input_changed(args.inputs, args.input)
        except Exception:
            pass


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


class _EditSplineExecute(adsk.core.CommandEventHandler):
    """Re-edit the selected sketch-embedded equation spline (rebuild all runs)."""
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            si = inputs.itemById("target")
            if si is None or si.selectionCount == 0:
                return
            sp = si.selection(0).entity
            cd = dialog.read_inputs(inputs)
            design = _design()
            sibs = adapter.sibling_eqcurve_splines(sp)
            new = adapter.rebuild_curve(sibs, cd, adapter.read_design_params(design))
            for sp2 in new:          # keep it fully defined after the edit
                _fix_spline(sp2)
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
            "Edit the selected equation-curve feature or spline", _EditCreated(), add_to_panel=True)
    _button(REGEN_ID, "Regenerate Equation Curves",
            "Recompute all equation curves (PC-8 fallback)", _RegenCreated())
    _button(EXPORT_ID, "Export Equation Curve",
            "Export the selected curve definition to JSON", _ExportCreated())
    _button(IMPORT_ID, "Import Equation Curve",
            "Create a curve from a JSON definition file", _ImportCreated())
    _button(CREATE_ID, "Equation Curve",
            "Create a parametric math-driven curve", _CreateCreated())

    # A CustomFeatureDefinition can't be deleted and create() rejects a duplicate
    # id, so cache the cdef on `sys` (survives module reloads). Re-attach a FRESH
    # compute handler every register (removing the stale one) so edited compute
    # logic actually takes effect on a dev Stop/Run — without this the first
    # handler loaded in a Fusion session would be frozen in place.
    _key = "_eqcurve_cdef_" + CF_DEF_ID
    _hkey = _key + "_handler"
    cached = getattr(sys, _key, None)
    ch = _ComputeHandler()
    if cached is not None:
        _cdef = cached
        old = getattr(sys, _hkey, None)
        if old is not None:
            try:
                _cdef.customFeatureCompute.remove(old)
            except Exception:
                pass
    else:
        _cdef = adsk.fusion.CustomFeatureDefinition.create(
            CF_DEF_ID, "Equation Curve", _ICON_FOLDER)
        setattr(sys, _key, _cdef)
    _cdef.customFeatureCompute.add(ch)
    setattr(sys, _hkey, ch)
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
