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
# realpath() resolves a junction in Fusion's AddIns folder back to the real
# project location, so an installed (junctioned) add-in still finds the package.
# __file__ = <root>/eqcurve/addin/EquationCurve/EquationCurve.py
_HERE = os.path.dirname(os.path.realpath(__file__))
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
    # wire rich logging: file + stderr + Fusion's Text Commands window. Failures
    # here must never block startup, so this is its own guarded block.
    try:
        from eqcurve.core import eqlog
        eqlog.configure()
        eqlog.add_callback_sink(_app.log)
        eqlog.get_logger().info("EquationCurve add-in starting (Fusion %s); log: %s",
                                _app.version, eqlog.log_path())
    except Exception:
        pass
    try:
        custom_feature.register(_app, _ui)
    except Exception:
        # NEVER pop a modal here: run() executes on load/reload (incl. headless
        # bridge reloads), and a blocking messageBox with no human to dismiss it
        # wedges Fusion's main thread. Log richly instead (file + Text Commands).
        try:
            from eqcurve.core import eqlog
            eqlog.report("EquationCurve.run")
        except Exception:
            try:
                _app.log("Equation Curve add-in failed to start:\n" + traceback.format_exc())
            except Exception:
                pass


def stop(context):
    try:
        custom_feature.unregister()
    except Exception:
        # log-only (see run): stop() also runs during automated reloads.
        try:
            from eqcurve.core import eqlog
            eqlog.report("EquationCurve.stop")
        except Exception:
            try:
                _app.log("Add-in stop failed:\n" + traceback.format_exc())
            except Exception:
                pass
