"""FusionEqBridge — minimal, audited localhost bridge for agent-driven testing.

Design (original implementation; security model inspired by barisgit/fusion360-bridge):
  * Binds 127.0.0.1 ONLY. Never 0.0.0.0. Remote access is via SSH tunnel.
  * Bearer-token auth on every request (defense in depth behind SSH).
  * Arbitrary Python runs on Fusion's MAIN THREAD via a CustomEvent (required —
    the Fusion API is not thread-safe off the main thread).
  * Persistent sessions: variables survive across /execute calls (keyed by
    'session') so an agent can build state iteratively.
  * Stdlib only (runs inside Fusion's bundled Python; no pip deps).

Token file (Windows): %LOCALAPPDATA%\\fusion-eqbridge\\secret  (0600 where supported)
Override with env FUSION_BRIDGE_SECRET (path) if you need a custom location.
"""

import io
import json
import os
import queue
import secrets
import threading
import traceback
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import adsk.core
import adsk.fusion

HOST = "127.0.0.1"
PORT = int(os.environ.get("FUSION_BRIDGE_PORT", "7654"))
EVENT_ID = "FusionEqBridgeExec"

_app = None
_ui = None
_server = None
_server_thread = None
_custom_event = None
_handlers = []
_jobs = queue.Queue()
_sessions = {}  # session_name -> namespace dict (persistent)
_TOKEN = None


# ---------------- token ----------------
def _secret_path():
    override = os.environ.get("FUSION_BRIDGE_SECRET")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "fusion-eqbridge", "secret")


def _load_or_create_secret():
    path = _secret_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    token = secrets.token_hex(32)
    # 0600 is honored on POSIX; on Windows ACLs differ but file lives under the
    # user profile. Keep the machine single-user / trusted.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    return token


# ---------------- main-thread execution ----------------
def _run_script(script, session):
    ns = _sessions.setdefault(session, {})
    ns.setdefault("adsk", adsk)
    ns.setdefault("app", adsk.core.Application.get())
    ns["ui"] = adsk.core.Application.get().userInterface
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(script, "<bridge>", "exec"), ns)
        return {"ok": True, "stdout": buf.getvalue(),
                "result": str(ns.get("__result__", ""))}
    except Exception:
        tb = traceback.format_exc()
        try:  # also surface it in Fusion's Text Commands window (main thread)
            if _app:
                _app.log("[FusionEqBridge] execute error in session %r:\n%s" % (session, tb))
        except Exception:
            pass
        return {"ok": False, "stdout": buf.getvalue(), "error": tb}


def _screenshot(width, height):
    import tempfile
    app = adsk.core.Application.get()
    vp = app.activeViewport
    if vp is None:
        return {"ok": False, "error": "no active viewport"}
    fd, path = tempfile.mkstemp(prefix="eqbridge_", suffix=".png")
    os.close(fd)
    try:
        vp.saveAsImageFile(path, width, height)
        with open(path, "rb") as f:
            import base64
            data = base64.b64encode(f.read()).decode("ascii")
        return {"ok": True, "png_b64": data}
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


class _ExecEventHandler(adsk.core.CustomEventHandler):
    """Runs on the main thread when the custom event fires."""
    def notify(self, args):
        while True:
            try:
                job, reply = _jobs.get_nowait()
            except queue.Empty:
                return
            try:
                kind = job.get("kind")
                if kind == "execute":
                    res = _run_script(job["script"], job.get("session", "default"))
                elif kind == "screenshot":
                    res = _screenshot(job.get("width", 0), job.get("height", 0))
                elif kind == "health":
                    res = {"ok": True, "fusion": True}
                else:
                    res = {"ok": False, "error": f"unknown kind {kind}"}
            except Exception:
                res = {"ok": False, "error": traceback.format_exc()}
            reply.put(res)


def _dispatch(job, timeout=30):
    reply = queue.Queue()
    _jobs.put((job, reply))
    _app.fireCustomEvent(EVENT_ID)
    try:
        return reply.get(timeout=timeout)
    except queue.Empty:
        return {"ok": False, "error": "timeout"}


# ---------------- HTTP ----------------
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def _authed(self):
        hdr = self.headers.get("Authorization", "")
        return hdr == f"Bearer {_TOKEN}"

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        if self.path == "/health":
            return self._send(200, _dispatch({"kind": "health"}, timeout=10))
        if self.path.startswith("/screenshot"):
            return self._send(200, _dispatch({"kind": "screenshot"}, timeout=60))
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send(400, {"ok": False, "error": "bad json"})
        if self.path == "/execute":
            job = {"kind": "execute",
                   "script": payload.get("script", ""),
                   "session": payload.get("session", "default")}
            return self._send(200, _dispatch(job, timeout=payload.get("timeout", 30)))
        self._send(404, {"ok": False, "error": "not found"})


def run(context):
    global _app, _ui, _server, _server_thread, _custom_event, _TOKEN
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    try:
        _TOKEN = _load_or_create_secret()
        # register custom event + handler (main-thread execution)
        _custom_event = _app.registerCustomEvent(EVENT_ID)
        h = _ExecEventHandler()
        _custom_event.add(h)
        _handlers.append(h)
        # start HTTP server on a background thread, 127.0.0.1 only
        _server = ThreadingHTTPServer((HOST, PORT), _Handler)
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _server_thread.start()
        _app.log(f"[FusionEqBridge] listening on http://{HOST}:{PORT}  "
                 f"(token at {_secret_path()})")
    except Exception:
        if _ui:
            _ui.messageBox("Bridge run failed:\n" + traceback.format_exc())


def stop(context):
    global _server
    try:
        if _server:
            _server.shutdown()
            _server = None
        _app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        if _ui:
            _ui.messageBox("Bridge stop failed:\n" + traceback.format_exc())
