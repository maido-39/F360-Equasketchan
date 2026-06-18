"""Integration harness — drives the LIVE bridge (Fusion must be running with
FusionEqBridge loaded). This is the adsk-dependent half of the 2-tier test
strategy; the math half is in tests/test_core.py (no Fusion needed).

Usage (from the Windows host, or through an SSH tunnel):
    python tests/integration_harness.py

It does NOT run under pytest by default because it requires Fusion. Wire it
into CI only on a machine that has Fusion + the bridge running.
"""

import os
import sys
import httpx

HOST = os.environ.get("FUSION_BRIDGE_HOST", "http://127.0.0.1:7654")


def _token():
    p = os.environ.get("FUSION_BRIDGE_SECRET")
    if not p:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        p = os.path.join(base, "fusion-eqbridge", "secret")
    return open(p, encoding="utf-8").read().strip()


def _exec(script, session="harness"):
    r = httpx.post(f"{HOST}/execute",
                   headers={"Authorization": f"Bearer {_token()}"},
                   json={"script": script, "session": session}, timeout=40)
    return r.json()


def main():
    # 1) sanity: bridge + Fusion reachable
    h = httpx.get(f"{HOST}/health",
                  headers={"Authorization": f"Bearer {_token()}"}, timeout=15).json()
    assert h.get("ok"), f"bridge health failed: {h}"
    print("health ok")

    # 2) build a curve via the package adapter, then verify the sketch has a spline
    script = r"""
import os, sys
sys.path.insert(0, r'PROJECT_ROOT')
from eqcurve.core import CurveDef
from eqcurve import adapter
import adsk.fusion
design = adsk.fusion.Design.cast(app.activeProduct)
sk = design.rootComponent.sketches.add(design.rootComponent.xYConstructionPlane)
cd = CurveDef(mode='explicit', coord='cartesian', dim=2,
              exprs={'y': 'D3 * sin(x)'}, var='x', t_min='0', t_max='2*pi', samples=200)
adapter.build_curve(sk, cd, {'D3': 10})
__result__ = str(sk.sketchCurves.sketchFittedSplines.count)
print('splines:', __result__)
""".replace("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    res = _exec(script)
    assert res.get("ok"), f"build failed: {res.get('error')}"
    assert res.get("result") == "1", f"expected 1 spline, got {res}"
    print("curve built inside Fusion:", res["result"])
    print("ALL INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    sys.exit(main())
