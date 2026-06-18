"""Phase-D core tests: rotation transform, presets, error messages.

All adsk-free (run under pytest without Fusion).
"""

import math

import pytest

from eqcurve.core import (
    CurveDef, sample, sample_runs, adaptive_sample_runs, preset_names, curvedef_for,
    describe, ExpressionError, SamplingError,
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
    assert len(names) == 11
    for name in names:
        cd = curvedef_for(name)
        cd.validate()
        runs = sample_runs(cd)            # must not raise
        assert sum(len(r) for r in runs) >= 2, name


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


def test_tolerance_roundtrips_and_old_json_defaults():
    cd = CurveDef(exprs={"x": "t", "y": "t"}, tolerance=0.01)
    assert CurveDef.from_json(cd.to_json()).tolerance == 0.01
    old = '{"mode":"parametric","coord":"cartesian","dim":2,"exprs":{"x":"t","y":"t"}}'
    assert CurveDef.from_json(old).tolerance == 0.0
