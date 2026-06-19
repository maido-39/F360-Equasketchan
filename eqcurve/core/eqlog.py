"""eqlog — stdlib-only structured logging for rich error localization.

adsk-free, so it imports under both pytest and Fusion's bundled Python (PC-3).
Every record carries module.function:lineno + a timestamp, so when something
fails you can see exactly WHERE. Output goes to:

  * a rotating log file at  %LOCALAPPDATA%\\eqcurve\\eqcurve.log  (full DEBUG)
  * stderr                                                        (INFO+)
  * any extra sink you register (e.g. Fusion's Text Commands window) via
    ``add_callback_sink`` — the add-in wires this so logs appear inside Fusion.

Typical use::

    from eqcurve.core import eqlog
    log = eqlog.get_logger()
    log.debug("sampling %d points", n)

    @eqlog.traced            # logs entry/exit + the full traceback on failure
    def build(...): ...

    try:
        ...
    except Exception:
        msg = eqlog.report("custom_feature._CreateExecute", expr=cd.exprs)
        ui.messageBox(msg)   # concise line; full traceback+context is in the log
"""

from __future__ import annotations

import functools
import logging
import logging.handlers
import os
import sys
import traceback

_LOGGER_NAME = "eqcurve"
_FMT = "%(asctime)s %(levelname)-7s %(module)s.%(funcName)s:%(lineno)d | %(message)s"
_DATEFMT = "%H:%M:%S"
_configured = False


def log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "eqcurve")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        folder = os.path.expanduser("~")
    return os.path.join(folder, "eqcurve.log")


def _formatter() -> logging.Formatter:
    return logging.Formatter(_FMT, datefmt=_DATEFMT)


def configure(level: int = logging.DEBUG) -> logging.Logger:
    """Idempotently configure and return the 'eqcurve' logger."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger
    logger.setLevel(level)
    logger.propagate = False
    fmt = _formatter()
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # never let logging setup break the app; stderr still works
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    _configured = True
    logger.debug("eqlog configured (file: %s)", log_path())
    return logger


def get_logger() -> logging.Logger:
    return configure()


class _CallbackHandler(logging.Handler):
    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def emit(self, record):
        try:
            self._fn(self.format(record))
        except Exception:
            pass  # a broken sink must never crash logging


def add_callback_sink(fn, level: int = logging.DEBUG) -> logging.Handler:
    """Route formatted log lines to `fn(str)` — e.g. Fusion's app.log."""
    h = _CallbackHandler(fn)
    h.setLevel(level)
    h.setFormatter(_formatter())
    configure().addHandler(h)
    return h


def _brief(args, kwargs, limit: int = 200) -> str:
    try:
        parts = [repr(a) for a in args] + ["%s=%r" % (k, v) for k, v in kwargs.items()]
        s = ", ".join(parts)
    except Exception:
        s = "<unprintable args>"
    return s if len(s) <= limit else s[:limit] + "…"


def traced(fn):
    """Decorator: DEBUG-log entry/exit; on exception log the full traceback
    (with the function and its args) and re-raise so callers still handle it."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        log = get_logger()
        log.debug("-> %s(%s)", fn.__qualname__, _brief(args, kwargs))
        try:
            result = fn(*args, **kwargs)
            log.debug("<- %s ok", fn.__qualname__)
            return result
        except Exception:
            log.exception("!! %s FAILED  args=(%s)", fn.__qualname__, _brief(args, kwargs))
            raise
    return wrapper


def log_caught(where: str, level: int = logging.WARNING, **context) -> None:
    """Log an exception that is being intentionally swallowed (replaces a silent
    'except: pass'), so it is still recorded with its location and context."""
    ctx = (" | " + ", ".join("%s=%r" % kv for kv in context.items())) if context else ""
    get_logger().log(level, "swallowed in %s%s\n%s", where, ctx, traceback.format_exc())


def report(where: str, **context) -> str:
    """Log the CURRENT exception with full traceback + context, and return a
    concise one-line summary (for a messageBox/UI) that points at the log file."""
    ctx = (" | " + ", ".join("%s=%r" % kv for kv in context.items())) if context else ""
    get_logger().error("ERROR in %s%s\n%s", where, ctx, traceback.format_exc())
    exc = sys.exc_info()[1]
    name = type(exc).__name__ if exc else "Error"
    return "%s: %s\n\n(full details logged to %s)" % (name, exc, log_path())
