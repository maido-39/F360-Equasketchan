"""Phase-B core tests: segmentation, adaptive sampling, refs, diagnostics.

All adsk-free (run under pytest without Fusion).
"""

import math

import pytest

from eqcurve.core import (
    CurveDef, sample_runs, adaptive_sample_runs,
    referenced_names, circular_reference,
    degenerate_points, self_intersections,
)


# ---- B1: discontinuity segmentation ---------------------------------------

def test_segmentation_tan_two_runs():
    # tan over [-pi, pi] has asymptotes at +/- pi/2 -> must split into runs,
    # never one spline bridging the poles.
    cd = CurveDef(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "tan(x)"}, var="x", t_min="-pi", t_max="pi", samples=200,
    )
    runs = sample_runs(cd)
    assert len(runs) >= 2
    for run in runs:
        assert len(run) >= 2
        assert all(math.isfinite(p[1]) for p in run)


def test_segmentation_smooth_single_run():
    cd = CurveDef(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "sin(x)"}, var="x", t_min="0", t_max="2*pi", samples=100,
    )
    assert len(sample_runs(cd)) == 1


# ---- B5: deterministic adaptive sampling ----------------------------------

def test_adaptive_is_deterministic():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "sin(5*t)"}, var="t", t_min="0", t_max="2*pi",
        samples=200, adaptive=True,
    )
    a = adaptive_sample_runs(cd)
    b = adaptive_sample_runs(cd)
    assert a == b  # same input -> byte-identical points (NFR-4)


def test_adaptive_densifies_high_curvature():
    line = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"}, var="t", t_min="0", t_max="1", samples=200,
    )
    wiggly = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "sin(8*t)"}, var="t", t_min="0", t_max="2*pi", samples=200,
    )
    n_line = sum(len(r) for r in adaptive_sample_runs(line))
    n_wiggly = sum(len(r) for r in adaptive_sample_runs(wiggly))
    assert n_wiggly > n_line  # adapts more points to the curvier curve


# ---- B3: referenced design-parameter names --------------------------------

def test_referenced_names():
    cd = CurveDef(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "D3 * sin(D4 * x)"}, var="x", t_min="0", t_max="2*pi*N", samples=10,
    )
    names = referenced_names(cd)
    assert names == {"D3", "D4", "N"}  # excludes x, sin, pi


def test_circular_ref_rejected():
    assert circular_reference({"A": "B + 1", "B": "A + 1"}) == {"A", "B"}
    assert circular_reference({"A": "1", "B": "A + 1"}) == set()  # acyclic


# ---- B6: diagnostics (non-fatal) ------------------------------------------

def test_degenerate_points_detected():
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    assert degenerate_points(pts) == [2]


def test_self_intersection_detected():
    # Lissajous x=sin(2t), y=sin(3t) self-crosses; a convex arc does not.
    liss = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "sin(2*t)", "y": "sin(3*t)"}, var="t",
        t_min="0", t_max="2*pi", samples=400,
    )
    pts = [p for run in sample_runs(liss) for p in run]
    assert len(self_intersections(pts)) > 0

    arc = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "cos(t)", "y": "sin(t)"}, var="t", t_min="0", t_max="pi", samples=200,
    )
    arc_pts = [p for run in sample_runs(arc) for p in run]
    assert self_intersections(arc_pts) == []


# ---- CurveDef.adaptive round-trip / tolerance -----------------------------

def test_curvedef_adaptive_roundtrip():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"}, var="t", t_min="0", t_max="1", adaptive=True,
    )
    assert CurveDef.from_json(cd.to_json()).adaptive is True


def test_from_json_tolerates_unknown_and_missing_keys():
    # Old JSON without 'adaptive' still loads (defaults to False)...
    old = '{"mode":"parametric","coord":"cartesian","dim":2,' \
          '"exprs":{"x":"t","y":"t"},"var":"t","t_min":"0","t_max":"1"}'
    assert CurveDef.from_json(old).adaptive is False
    # ...and an unknown future key is ignored rather than crashing.
    future = '{"mode":"parametric","coord":"cartesian","dim":2,' \
             '"exprs":{"x":"t","y":"t"},"someFutureField":42}'
    cd = CurveDef.from_json(future)
    assert cd.mode == "parametric"
