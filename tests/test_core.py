"""Acceptance tests for the adsk-free core.

These map directly to the spec's acceptance criteria that do not require
Fusion (the math/definition layer). Run with: pytest -q
"""

import math

import pytest

from eqcurve.core import CurveDef, Evaluator, ExpressionError, sample, is_effectively_closed
from eqcurve.core.sampler import SamplingError


# ---- evaluator basics -----------------------------------------------------

def test_constants_and_params():
    ev = Evaluator()
    assert ev.eval("pi", {}) == pytest.approx(math.pi)
    assert ev.eval("D3 * 2", {"D3": 5}) == pytest.approx(10)


def test_hyperbolic_native():
    # SolidWorks lacks cosh natively; we support it directly.
    ev = Evaluator()
    assert ev.eval("cosh(0)", {}) == pytest.approx(1.0)
    assert ev.eval("sinh(0)", {}) == pytest.approx(0.0)


def test_degree_mode():
    ev = Evaluator(angle="deg")
    assert ev.eval("sin(90)", {}) == pytest.approx(1.0)
    assert ev.eval("asin(1)", {}) == pytest.approx(90.0)


def test_rejects_arbitrary_code():
    ev = Evaluator()
    for bad in ["__import__('os')", "open('x')", "(lambda: 1)()", "x if x else 0"]:
        with pytest.raises(ExpressionError):
            ev.eval(bad, {"x": 1})


# ---- AC-1: sine amplitude scales with a parameter -------------------------

def test_sine_amplitude_scales_with_param():
    cd = CurveDef(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "D3 * sin(D4 * x)"},
        var="x", t_min="0", t_max="2*pi", samples=400,
    )
    p1 = sample(cd, {"D3": 10, "D4": 1})
    p2 = sample(cd, {"D3": 20, "D4": 1})
    amp1 = max(abs(y) for _, y, _ in p1)
    amp2 = max(abs(y) for _, y, _ in p2)
    assert amp2 == pytest.approx(2 * amp1, rel=1e-3)


# ---- AC-2: polar closed curve (cardioid) ----------------------------------

def test_cardioid_is_closed():
    cd = CurveDef(
        mode="explicit", coord="polar", dim=2,
        exprs={"r": "1 + cos(a)"},
        var="a", t_min="0", t_max="2*pi", samples=361, closed=True,
    )
    pts = sample(cd)
    assert is_effectively_closed(pts)


# ---- AC-3: cylindrical helix pitch scales with parameter ------------------

def test_helix_pitch_scales():
    cd = CurveDef(
        mode="parametric", coord="cylindrical", dim=3,
        exprs={"r": "D1", "theta": "t", "z": "D2 * t"},
        var="t", t_min="0", t_max="2*pi*3", samples=300,
    )
    a = sample(cd, {"D1": 10, "D2": 1})
    b = sample(cd, {"D1": 10, "D2": 2})
    za = max(z for _, _, z in a)
    zb = max(z for _, _, z in b)
    assert zb == pytest.approx(2 * za, rel=1e-6)


# ---- AC-4: catenary via native cosh ---------------------------------------

def test_catenary_vertex():
    c = 5.0
    cd = CurveDef(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "c * cosh(x / c)"},
        var="x", t_min="-10", t_max="10", samples=201,
    )
    pts = sample(cd, {"c": c})
    ys = [y for x, y, _ in pts if abs(x) < 1e-9]
    assert ys and ys[0] == pytest.approx(c)  # y(0) = c


# ---- AC-5: lossless re-edit round-trip ------------------------------------

def test_curvedef_roundtrip():
    cd = CurveDef(
        mode="parametric", coord="spherical", dim=3,
        exprs={"r": "R", "phi": "t", "theta": "k * t"},
        var="t", t_min="0", t_max="2*pi", samples=120, angle="rad",
        note="spherical spiral",
    )
    restored = CurveDef.from_json(cd.to_json())
    assert restored == cd


# ---- AC-6: singularity safety (tan asymptotes) ----------------------------

def test_tan_singularity_does_not_crash():
    cd = CurveDef(
        mode="explicit", coord="cartesian", dim=2,
        exprs={"y": "tan(x)"},
        var="x", t_min="-pi", t_max="pi", samples=200,
    )
    pts = sample(cd)  # must not raise; asymptote samples are dropped
    assert all(math.isfinite(y) for _, y, _ in pts)


# ---- domain / validation guards -------------------------------------------

def test_empty_domain_raises():
    cd = CurveDef(exprs={"x": "t", "y": "t"}, t_min="1", t_max="1")
    with pytest.raises(SamplingError):
        sample(cd)


def test_domain_endpoints_may_use_params():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"},
        var="t", t_min="0", t_max="N", samples=10,
    )
    pts = sample(cd, {"N": 5})
    assert pts[-1][0] == pytest.approx(5.0)


# ---- FR-8.3: sample count as a parameter/expression -----------------------

def test_samples_count_can_be_an_expression():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"}, var="t", t_min="0", t_max="1",
        samples="3*K",
    )
    pts = sample(cd, {"K": 4})  # 3*4 = 12 points on one straight run
    assert len(pts) == 12


def test_samples_expression_below_two_raises():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"}, var="t", t_min="0", t_max="1",
        samples="K",
    )
    with pytest.raises(SamplingError):
        sample(cd, {"K": 1})


def test_samples_invalid_expression_raises_sampling_error():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"}, var="t", t_min="0", t_max="1",
        samples="nope(",  # not parseable
    )
    with pytest.raises(SamplingError):
        sample(cd, {})


def test_resolve_samples_caps_huge_count():
    # an unbounded count would spin the main thread; it must be clamped (FR-13.4)
    from eqcurve.core.sampler import _resolve_samples, MAX_SAMPLES
    from eqcurve.core import Evaluator
    cd = CurveDef(exprs={"x": "t", "y": "t"}, samples="10000000")
    n = _resolve_samples(cd, Evaluator("rad"), {})
    assert n == MAX_SAMPLES


def test_resolve_samples_wraps_arithmetic_errors():
    # ZeroDivisionError / OverflowError from the samples expr must surface as a
    # diagnostic SamplingError, never escape raw to the caller.
    from eqcurve.core.sampler import _resolve_samples
    from eqcurve.core import Evaluator
    ev = Evaluator("rad")
    for expr in ("1/0", "exp(1000)", "2**4000", "1e308*10"):
        cd = CurveDef(exprs={"x": "t", "y": "t"}, samples=expr)
        with pytest.raises(SamplingError):
            _resolve_samples(cd, ev, {})


def test_samples_expression_tolerates_whitespace():
    cd = CurveDef(
        mode="parametric", coord="cartesian", dim=2,
        exprs={"x": "t", "y": "t"}, var="t", t_min="0", t_max="1",
        samples="  10  ",
    )
    assert len(sample(cd, {})) == 10
