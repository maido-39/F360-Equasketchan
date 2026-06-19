"""Phase-D core tests: rotation transform, presets, error messages.

All adsk-free (run under pytest without Fusion).
"""

import math

import pytest

from eqcurve.core import (
    CurveDef, Evaluator, sample, sample_runs, adaptive_sample_runs, decimate,
    preset_names, curvedef_for, describe, ExpressionError, SamplingError,
)


# ---- D3: rotation transform -----------------------------------------------

def test_rotation_z_90_degrees_maps_axes():
    # A single point at (1,0); rotate +90 deg about z -> (0,1).
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "1", "y": "0"}, var="t", t_min="0", t_max="1", samples=5,
        angle="deg", rotation={"x": "0", "y": "0", "z": "90"},
    )
    x, y, z = sample(cd)[0]
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(1.0, abs=1e-9)


def test_rotation_default_is_identity():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "2*t"}, var="t", t_min="0", t_max="1", samples=10,
    )
    # no rotation key set -> points unchanged
    pts = sample(cd)
    assert pts[-1][0] == pytest.approx(1.0) and pts[-1][1] == pytest.approx(2.0)


def test_rotation_roundtrips_through_json():
    cd = CurveDef(exprs={"x": "t", "y": "t"}, rotation={"x": "0", "y": "0", "z": "45"})
    assert CurveDef.from_json(cd.to_json()).rotation == {"x": "0", "y": "0", "z": "45"}


# ---- D1: preset catalog ----------------------------------------------------

def test_all_presets_sample_cleanly():
    names = preset_names()
    assert len(names) == 14
    for nm in ("Cycloidal gear", "Involute gear", "Conical spiral spring"):
        assert nm in names
    for name in names:
        cd = curvedef_for(name)
        cd.validate()
        runs = sample_runs(cd)            # must not raise
        assert sum(len(r) for r in runs) >= 2, name


# ---- M6: performance guard (FR-13.4) --------------------------------------

def test_decimate_caps_points_and_keeps_endpoints():
    run = [(float(i), float(i * i), 0.0) for i in range(1000)]
    out = decimate(run, 300)
    assert len(out) == 300
    assert out[0] == run[0] and out[-1] == run[-1]   # endpoints preserved
    assert decimate(run, 0) is run                   # disabled -> unchanged
    assert decimate(run[:50], 300) == run[:50]       # under cap -> unchanged


def test_preset_cardioid_is_known_shape():
    cd = curvedef_for("Cardioid")
    assert cd.coord == "polar" and cd.closed is True


# ---- D5: human-readable error messages ------------------------------------

def test_describe_unknown_function():
    cd = CurveDef(exprs={"y": "wobble(x)"}, mode="explicit", coord="cartesian",
                  dim=2, var="x", t_min="0", t_max="1")
    try:
        sample(cd)
        assert False, "expected failure"
    except (ExpressionError, SamplingError) as exc:
        text = describe(exc)
        assert "function" in text.lower() or "point" in text.lower()


def test_describe_empty_domain():
    msg = describe(SamplingError("t_min == t_max (empty domain)"))
    assert "empty domain" in msg.lower()


# ---- error localization (audit fixes) -------------------------------------

def test_sampling_error_reports_singular_count():
    cd = CurveDef(mode="explicit", coord="cartesian", dim=2,
                  exprs={"y": "ln(x)"}, var="x", t_min="-10", t_max="-1", samples=50)
    with pytest.raises(SamplingError) as ei:
        sample(cd)
    assert "singular" in str(ei.value).lower()


def test_non_numeric_param_error_names_it():
    ev = Evaluator()
    with pytest.raises(ExpressionError) as ei:
        ev.eval("D3 * 2", {"D3": "oops"})
    assert "D3" in str(ei.value) and "numeric" in str(ei.value).lower()


def test_wrong_arity_error_names_function():
    ev = Evaluator()
    with pytest.raises(ExpressionError) as ei:
        ev.eval("sin(1, 2)", {})
    assert "sin" in str(ei.value)


# ---- FR-10.3: adaptive chord-deviation tolerance --------------------------

def test_adaptive_deviation_tolerance_adds_points_and_is_deterministic():
    base = dict(mode="explicit", coord="cartesian", dim=2,
                exprs={"y": "x*x"}, var="x", t_min="0", t_max="4", samples=200, adaptive=True)
    coarse = CurveDef(tolerance=0.0, **base)       # angle criterion only
    fine = CurveDef(tolerance=0.0005, **base)      # add tight chord-deviation
    n_coarse = sum(len(r) for r in adaptive_sample_runs(coarse))
    n_fine = sum(len(r) for r in adaptive_sample_runs(fine))
    assert n_fine >= n_coarse
    assert adaptive_sample_runs(fine) == adaptive_sample_runs(fine)  # deterministic


def test_arc_aliases():
    ev = Evaluator()
    assert ev.eval("arctan(1)", {}) == pytest.approx(math.atan(1))
    assert ev.eval("arcsin(1)", {}) == pytest.approx(math.asin(1))
    assert ev.eval("arccos(0)", {}) == pytest.approx(math.acos(0))


def test_diy_cycloidal_disc_with_params():
    # The user's DIY cycloidal disc (uses arctan + design parameters).
    psi = "arctan(sin((1-N)*t)/((R/(E*N))-cos((1-N)*t)))"
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "(R*cos(t))-(Rr*cos(t+%s))-(E*cos(N*t))" % psi,
               "y": "(-R*sin(t))+(Rr*sin(t+%s))+(E*sin(N*t))" % psi},
        var="t", t_min="0", t_max="2*pi", samples=400, closed=True)
    pts = sample(cd, {"N": 16, "Rr": 6.5, "R": 45, "E": 1.5})
    assert len(pts) > 100
    # max radius ~ R - Rr + E = 40 mm (15-lobe disc)
    rmax = max((x * x + y * y) ** 0.5 for x, y, _ in pts)
    assert 38 < rmax < 42


def test_tolerance_roundtrips_and_old_json_defaults():
    cd = CurveDef(exprs={"x": "t", "y": "t"}, tolerance=0.01)
    assert CurveDef.from_json(cd.to_json()).tolerance == 0.01
    old = '{"mode":"parametric","coord":"cartesian","dim":2,"exprs":{"x":"t","y":"t"}}'
    assert CurveDef.from_json(old).tolerance == 0.0
