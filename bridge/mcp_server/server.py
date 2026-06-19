"""MCP stdio server bridging an MCP client (e.g. Claude Code) to the
FusionEqBridge add-in over localhost HTTP.

Topology A (remote Windows Fusion): run THIS server on the Windows host next to
Fusion and launch it from the client over SSH, so 127.0.0.1 stays 127.0.0.1 and
the token never leaves the host. See README.

Env overrides:
  FUSION_BRIDGE_HOST    default http://127.0.0.1:7654
  FUSION_BRIDGE_SECRET  path to the token file (must match the add-in)
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("FUSION_BRIDGE_HOST", "http://127.0.0.1:7654")


def _token() -> str:
    path = os.environ.get("FUSION_BRIDGE_SECRET")
    if not path:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "fusion-eqbridge", "secret")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"bridge token not found at {path} — run the FusionEqBridge add-in "
            f"in Fusion first (it creates the token), or set FUSION_BRIDGE_SECRET.")
    except OSError as exc:
        raise RuntimeError(f"cannot read bridge token {path}: {exc}")


def _headers():
    return {"Authorization": f"Bearer {_token()}"}


def _result(r) -> dict:
    """Parse a bridge response, surfacing HTTP errors instead of masking them as
    a successful result (a 401/500 must not look like ok=True)."""
    if r.status_code >= 400:
        return {"ok": False, "error": f"HTTP {r.status_code} from bridge: {r.text[:500]}"}
    try:
        return r.json()
    except Exception as exc:
        return {"ok": False, "error": f"non-JSON reply from bridge ({exc}): {r.text[:300]}"}


def _guard(fn):
    """Turn token / connection / unexpected errors into a structured error dict."""
    try:
        return fn()
    except httpx.ConnectError:
        return {"ok": False, "error": f"bridge not reachable at {HOST}. "
                "Is FusionEqBridge running in Fusion (and the SSH tunnel up)?"}
    except httpx.TimeoutException:
        return {"ok": False, "error": f"bridge timed out (main thread busy?) at {HOST}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


mcp = FastMCP("fusion-eqcurve")


@mcp.tool()
def health() -> dict:
    """Check that the Fusion bridge is reachable and Fusion is responding."""
    return _guard(lambda: _result(
        httpx.get(f"{HOST}/health", headers=_headers(), timeout=15)))


@mcp.tool()
def execute(script: str, session: str = "default", timeout: int = 30) -> dict:
    """Run Python inside Fusion on the main thread and return stdout/result.

    Variables persist across calls sharing the same `session`. Set `__result__`
    in the script to return a value. `adsk`, `app`, `ui` are pre-bound.
    """
    return _guard(lambda: _result(httpx.post(
        f"{HOST}/execute",
        headers=_headers(),
        json={"script": script, "session": session, "timeout": timeout},
        timeout=timeout + 10,
    )))


@mcp.tool()
def screenshot() -> dict:
    """Capture the active Fusion viewport (returns base64 PNG under 'png_b64')."""
    return _guard(lambda: _result(
        httpx.get(f"{HOST}/screenshot", headers=_headers(), timeout=60)))


@mcp.tool()
def list_api(query: str, limit: int = 12) -> dict:
    """Introspect adsk.core/adsk.fusion/adsk.cam for members matching `query`.

    Runs inside Fusion so signatures are always correct for the running version.
    """
    script = f"""
import inspect, adsk.core, adsk.fusion, adsk.cam
q = {query!r}.lower()
hits = []
for mod in (adsk.core, adsk.fusion, adsk.cam):
    for name in dir(mod):
        if q in name.lower():
            hits.append(mod.__name__ + '.' + name)
hits = hits[:{limit}]
__result__ = '\\n'.join(hits)
print(__result__)
"""
    return execute(script, session="_introspect")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
