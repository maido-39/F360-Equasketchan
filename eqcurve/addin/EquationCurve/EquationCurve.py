"""EquationCurve add-in entry (MS-2).

Thin entry point: registers the parametric Equation Curve **Custom Feature** and
its Create / Edit / Regenerate commands (see custom_feature.py). The curve becomes
a timeline node that auto-recomputes when a referenced design parameter changes
(FR-8.2), with double-click re-edit (FR-11.2) and a Regenerate fallback (PC-8).

The math/definition layer (eqcurve.core) and the unit/geometry adapter
(eqcurve.adapter) are adsk-light/-free and covered by pytest + the integration
harness; this file only wires them into Fusion's UI.
"""

import os
import sys
import traceback

import adsk.core

# Make both the project root (for `import eqcurve`) and this add-in folder (for
# the sibling `dialog`/`custom_feature` modules) importable when Fusion loads us.
# __file__ = <root>/eqcurve/addin/EquationCurve/EquationCurve.py
_HERE = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in (_PROJECT_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import custom_feature  # noqa: E402  (sibling module in this add-in folder)

_app = None
_ui = None


def run(context):
    global _app, _ui
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    try:
        custom_feature.register(_app, _ui)
    except Exception:
        if _ui:
            _ui.messageBox("Add-in run failed:\n" + traceback.format_exc())


def stop(context):
    try:
        custom_feature.unregister()
    except Exception:
        if _ui:
            _ui.messageBox("Add-in stop failed:\n" + traceback.format_exc())
