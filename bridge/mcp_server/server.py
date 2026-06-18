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
    override = os.environ.get("FUSION_BRIDGE_SECRET")
    if not override:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        override = os.path.join(base, "fusion-eqbridge", "secret")
    with open(override, "r", encoding="utf-8") as f:
        return f.read().strip()


def _headers():
    return {"Authorization": f"Bearer {_token()}"}


mcp = FastMCP("fusion-eqcurve")


@mcp.tool()
def health() -> dict:
    """Check that the Fusion bridge is reachable and Fusion is responding."""
    try:
        r = httpx.get(f"{HOST}/health", headers=_headers(), timeout=15)
        return r.json()
    except httpx.ConnectError:
        return {"ok": False, "error": f"bridge not reachable at {HOST}. "
                "Is FusionEqBridge running in Fusion (and SSH tunnel up)?"}


@mcp.tool()
def execute(script: str, session: str = "default", timeout: int = 30) -> dict:
    """Run Python inside Fusion on the main thread and return stdout/result.

    Variables persist across calls sharing the same `session`. Set `__result__`
    in the script to return a value. `adsk`, `app`, `ui` are pre-bound.
    """
    r = httpx.post(
        f"{HOST}/execute",
        headers=_headers(),
        json={"script": script, "session": session, "timeout": timeout},
        timeout=timeout + 10,
    )
    return r.json()


@mcp.tool()
def screenshot() -> dict:
    """Capture the active Fusion viewport (returns base64 PNG under 'png_b64')."""
    r = httpx.get(f"{HOST}/screenshot", headers=_headers(), timeout=60)
    return r.json()


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
