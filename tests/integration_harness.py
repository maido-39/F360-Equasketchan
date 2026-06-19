"""Integration harness — drives the LIVE bridge (Fusion must be running with
FusionEqBridge loaded). This is the adsk-dependent half of the 2-tier test
strategy; the math half is in tests/test_core.py + test_phase_b.py (no Fusion).

Usage (from the Windows host, or through an SSH tunnel):
    python tests/integration_harness.py

Stdlib only (urllib) so it runs under any Python without extra deps. It builds
in a SCRATCH document and closes it without saving, so the user's open design is
never touched. It is excluded from pytest (needs a live Fusion).

Checks:
  * MS-1 round-trip  — build a curve, read back the stored CurveDef, assert the
    definition is restored losslessly (AC-5 / ARC-4).
  * unit-safe params — a 50 mm parameter is seen as 50 in equations (FR-8.5).
  * segmentation     — tan over [-pi, pi] builds several splines, not one that
    wrongly bridges the asymptotes (FR-13.1).
"""

import json
import os
import sys
import urllib.request

HOST = os.environ.get("FUSION_BRIDGE_HOST", "http://127.0.0.1:7654")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _token():
    p = os.environ.get("FUSION_BRIDGE_SECRET")
    if not p:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        p = os.path.join(base, "fusion-eqbridge", "secret")
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


def _request(path, payload=None):
    url = f"{HOST}{path}"
    headers = {"Authorization": f"Bearer {_token()}"}
    if payload is None:
        req = urllib.request.Request(url, headers=headers, method="GET")
    else:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Fusion-side script: fresh-imports eqcurve, builds in a scratch doc, returns a
# JSON summary, then closes the scratch doc without saving.
_FUSION_SCRIPT = r'''
import sys, os, json, traceback
proj = {proj!r}
if proj not in sys.path:
    sys.path.insert(0, proj)
for _m in list(sys.modules):
    if _m == "eqcurve" or _m.startswith("eqcurve."):
        sys.modules.pop(_m, None)
import adsk.core, adsk.fusion
app = adsk.core.Application.get()
res = {{}}
doc = None
try:
    from eqcurve.core import CurveDef
    from eqcurve import adapter
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    sk = root.sketches.add(root.xYConstructionPlane)
    cd = CurveDef(mode="explicit", coord="cartesian", dim=2,
                  exprs={{"y": "D3 * sin(x)"}}, var="x", t_min="0", t_max="2*pi", samples=120)
    design.userParameters.add("D3", adsk.core.ValueInput.createByString("50 mm"), "mm", "")
    params = adapter.read_design_params(design)
    res["d3"] = params.get("D3")
    splines = adapter.build_curve_runs(sk, cd, params)
    res["sine_splines"] = len(splines)
    cd2 = adapter.read_definition(splines[0])
    res["roundtrip"] = (cd2.to_json() == cd.to_json())
    res["marker"] = adapter.is_eqcurve(splines[0])

    sk2 = root.sketches.add(root.xYConstructionPlane)
    cdt = CurveDef(mode="explicit", coord="cartesian", dim=2,
                   exprs={{"y": "tan(x)"}}, var="x", t_min="-pi", t_max="pi", samples=200)
    res["tan_splines"] = len(adapter.build_curve_runs(sk2, cdt, {{}}))
    res["ok"] = True
except Exception:
    res["ok"] = False
    res["error"] = traceback.format_exc()
finally:
    if doc is not None:
        try:
            doc.close(False)
        except Exception:
            pass
__result__ = json.dumps(res)
'''


# Fusion-side MS-2 script: register the Custom Feature, create one in a scratch
# doc, change a referenced parameter, computeAll, and confirm the geometry
# auto-recomputed (FR-8.2). Closes the scratch doc without saving.
_FUSION_MS2_SCRIPT = r'''
import sys, os, json, traceback
proj = {proj!r}
addin = os.path.join(proj, "eqcurve", "addin", "EquationCurve")
for p in (proj, addin):
    if p not in sys.path:
        sys.path.insert(0, p)
for _m in list(sys.modules):
    if _m in ("eqcurve", "dialog", "custom_feature", "EquationCurve") or _m.startswith("eqcurve."):
        sys.modules.pop(_m, None)
import adsk.core, adsk.fusion
app = adsk.core.Application.get()
ui = app.userInterface
res = {{}}
doc = None
registered = False
try:
    import custom_feature as cf
    from eqcurve.core import CurveDef
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    cf.register(app, ui)
    registered = True
    design.userParameters.add("AMP", adsk.core.ValueInput.createByString("10 mm"), "mm", "")
    cd = CurveDef(mode="explicit", coord="cartesian", dim=2,
                  exprs={{"y": "AMP * sin(x)"}}, var="x", t_min="0", t_max="2*pi", samples=80)
    feat = cf.create_feature(design, cd)

    def maxy():
        sk = design.findEntityByToken(feat.attributes.itemByName("eqcurve", "sketch_token").value)[0]
        sps = sk.sketchCurves.sketchFittedSplines
        ys = []
        for i in range(sps.count):
            fp = sps.item(i).fitPoints
            for j in range(fp.count):
                ys.append(abs(fp.item(j).geometry.y))
        return max(ys) if ys else 0.0

    res["timeline"] = feat.timelineObject.index >= 0
    before = maxy()
    design.userParameters.itemByName("AMP").expression = "40 mm"
    design.computeAll()
    after = maxy()
    res["before"] = round(before, 4)
    res["after"] = round(after, 4)
    res["recomputed"] = after > before * 2
    res["ok"] = True
except Exception:
    res["ok"] = False
    res["error"] = traceback.format_exc()
finally:
    try:
        if registered:
            cf.unregister()
    except Exception:
        pass
    if doc is not None:
        try:
            doc.close(False)
        except Exception:
            pass
__result__ = json.dumps(res)
'''


def main():
    # ?deep=1 round-trips through Fusion's main thread, so this gate verifies
    # Fusion is actually responsive (a plain /health only confirms the HTTP
    # server thread and would pass even against a wedged main thread).
    h = _request("/health?deep=1")
    assert h.get("ok"), f"bridge health failed: {h}"
    assert h.get("fusion"), f"Fusion main thread not responding (wedged?): {h}"
    print("health ok (server + fusion main thread)")

    script = _FUSION_SCRIPT.format(proj=PROJECT_ROOT)
    out = _request("/execute", {"script": script, "session": "harness"})
    assert out.get("ok"), f"bridge execute failed: {out.get('error')}"
    res = json.loads(out["result"])
    assert res.get("ok"), f"in-Fusion build failed:\n{res.get('error')}"

    assert abs(res["d3"] - 50.0) < 1e-6, f"unit-safe param wrong: D3={res['d3']} (want 50)"
    assert res["sine_splines"] == 1, f"expected 1 sine spline, got {res['sine_splines']}"
    assert res["roundtrip"] is True, "CurveDef did not round-trip losslessly"
    assert res["marker"] is True, "eqcurve marker attribute missing"
    assert res["tan_splines"] >= 2, f"tan must segment, got {res['tan_splines']} spline(s)"

    print(f"MS-1 round-trip ok (lossless, D3={res['d3']} mm, marker set)")
    print(f"segmentation ok (tan -> {res['tan_splines']} splines)")

    # MS-2: Custom Feature auto-recompute
    ms2 = _request("/execute",
                   {"script": _FUSION_MS2_SCRIPT.format(proj=PROJECT_ROOT), "session": "harness"})
    assert ms2.get("ok"), f"bridge execute (MS-2) failed: {ms2.get('error')}"
    r2 = json.loads(ms2["result"])
    assert r2.get("ok"), f"in-Fusion MS-2 failed:\n{r2.get('error')}"
    assert r2["timeline"] is True, "custom feature did not create a timeline node"
    assert r2["recomputed"] is True, (
        f"curve did not auto-recompute on param change: {r2['before']} -> {r2['after']}")
    print(f"MS-2 auto-recompute ok (AMP 10->40 mm: max-y {r2['before']} -> {r2['after']} cm)")

    print("ALL INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    sys.exit(main())
