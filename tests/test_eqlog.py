"""Tests for the eqlog rich-logging helper (stdlib-only, no Fusion)."""

import logging

import pytest

from eqcurve.core import eqlog


def test_logger_configures_and_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # force a fresh configuration against the temp dir
    eqlog._configured = False
    logging.getLogger("eqcurve").handlers.clear()
    log = eqlog.configure()
    log.info("hello-eqlog-test")
    for h in log.handlers:
        h.flush()
    p = eqlog.log_path()
    assert p.startswith(str(tmp_path))
    assert "hello-eqlog-test" in open(p, encoding="utf-8").read()


def test_traced_logs_and_reraises():
    @eqlog.traced
    def boom(x):
        raise ValueError("kaboom %s" % x)

    with pytest.raises(ValueError):
        boom(7)


def test_report_returns_concise_summary():
    try:
        raise KeyError("missing")
    except Exception:
        msg = eqlog.report("test.where", detail="abc")
    assert "KeyError" in msg and "logged to" in msg


def test_log_caught_does_not_raise():
    try:
        raise RuntimeError("oops")
    except Exception:
        eqlog.log_caught("test.swallow", note="ignored")  # must not raise


def test_callback_sink_receives_lines():
    seen = []
    h = eqlog.add_callback_sink(seen.append)
    try:
        eqlog.get_logger().warning("sink-line")
        assert any("sink-line" in s for s in seen)
    finally:
        eqlog.get_logger().removeHandler(h)
