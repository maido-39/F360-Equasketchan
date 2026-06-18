# fusion-eqcurve

Equation-driven curve plugin for **Fusion 360** + an **audited, localhost-only
bridge** that lets an agent (Claude Code) build, debug, and test it against a
**remote Windows** Fusion over SSH.

This scaffold is structured around two principles from the research phase:

1. **Core / adapter split.** All math (`eqcurve.core`) is `adsk`-free and
   tested with `pytest` *without Fusion*. Only `eqcurve/adapter.py` and the
   add-in touch `adsk`.
2. **Safe remote testing.** The bridge binds `127.0.0.1` only and requires a
   bearer token. Remote access is via **SSH tunnel**, never `0.0.0.0`.

---

## Layout

```
eqcurve/
  core/            # adsk-FREE: evaluator, curvedef, sampler  (pytest target)
  adapter.py       # adsk: sampled points -> sketch spline + stored definition
  addin/EquationCurve/   # the plugin (MVP command)
bridge/
  addin/FusionEqBridge/  # in-Fusion bridge add-in (stdlib only, 127.0.0.1+token)
  mcp_server/            # stdio MCP server (runs OUTSIDE Fusion; httpx -> bridge)
tests/
  test_core.py           # acceptance tests, no Fusion needed
  integration_harness.py # drives the live bridge (Fusion must be running)
```

---

## 1. Local dev: run the math tests (no Fusion)

```bash
pip install -e ".[dev]"
pytest          # 12 acceptance tests for the core
```

---

## 2. Topology A — remote Windows Fusion (recommended)

```
Claude Code (your machine)
   │  stdio over SSH
   ▼
[ Windows host ]  ssh user@winhost  py -m bridge.mcp_server   (MCP stdio server)
                     │  httpx -> 127.0.0.1:7654  (localhost only)
                     ▼
                  Fusion 360  ── FusionEqBridge add-in (exec on main thread)
```

Everything stays on `127.0.0.1` on the Windows box; SSH carries the transport;
the token never leaves the host.

### 2a. On the Windows host
1. **Enable OpenSSH Server** (Settings ▸ Apps ▸ Optional features ▸ OpenSSH
   Server, then `Start-Service sshd`).
2. Copy this project somewhere on the host, e.g. `C:\dev\fusion-eqcurve`.
3. Install the bridge add-in: copy `bridge/addin/FusionEqBridge` into Fusion's
   AddIns folder. The path is one of (depends on version):
   - `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`
   - `%APPDATA%\Autodesk\Autodesk Fusion\API\AddIns\`
4. In Fusion: **Shift+S ▸ Add-Ins ▸ FusionEqBridge ▸ Run**. The Text Commands
   window logs `listening on http://127.0.0.1:7654` and the token path.
5. (For testing the plugin itself) also install `eqcurve/addin/EquationCurve`
   the same way, or just build curves via the bridge `execute` tool.

> The token is auto-created at `%LOCALAPPDATA%\fusion-eqbridge\secret`.

### 2b. On your machine (Claude Code)
Copy `.mcp.json.example` to `.mcp.json`, set `USER@WINHOST`, then register:

```bash
claude mcp add fusion-eqcurve -- ssh USER@WINHOST "py -m bridge.mcp_server"
```

(`py -m bridge.mcp_server` must run from the project root on the host; set the
remote working dir or use an absolute `-C`/`cd` wrapper as needed. Install the
server deps on the host: `py -m pip install "mcp>=1.2.0" httpx`.)

Verify from the client by calling the `health` tool → `{"ok": true, ...}`.

### Alternative: SSH local port-forward (Topology B)
```bash
ssh -L 7654:127.0.0.1:7654 USER@WINHOST
```
Then run the MCP server locally, but you must copy the host's token to your
machine (or point `FUSION_BRIDGE_SECRET` at a synced copy). Topology A avoids
this, so prefer it.

---

## 3. The agent test loop

Once `health` is green, Claude Code can:

- `execute(script, session=...)` — run Python in Fusion (state persists per
  session). Set `__result__` to return a value.
- `screenshot()` — visually verify a generated curve (base64 PNG).
- `list_api(query)` — correct `adsk` signatures for the running version.

Run the bundled integration check on the host (or through the tunnel):

```bash
python tests/integration_harness.py    # builds a curve in Fusion, asserts it exists
```

Recommended loop: edit code → reload the plugin add-in (Stop/Run, or
`execute` an importlib-reload snippet) → `execute` an assertion script →
read `result`/`stdout` → `screenshot` → iterate.

---

## 4. Security checklist

- Bridge bound to `127.0.0.1` only — **never change to `0.0.0.0`**.
- Bearer token required on every request (file under the user profile).
- Remote = SSH only; firewall-block inbound `7654`.
- Run the bridge **only during dev sessions**; Stop it otherwise (do NOT enable
  Run on Startup for the bridge).
- The bridge executes arbitrary Python by design (that is the test harness);
  keep the host single-user / trusted. This is *our own* ~250-line add-in with
  no auto-update and no external network — audit it fully before use.

---

## 5. Roadmap (from the feature spec)

- **MVP (this scaffold):** create curve from a dialog/bridge; store CurveDef for
  re-open; full function library incl. native hyperbolics; 2D/3D + all coord
  systems; closed curves; singularity-safe sampling.
- **Next:** parameter-associative **Custom Feature** (timeline node, double-click
  re-edit, auto-recompute when D-params change) — implement against the narrow
  base-feature/sketch compute path, validated through the bridge.
- **Later:** adaptive (curvature) sampling with deviation tolerance; preset
  catalog UI; import/export of definitions; `z=f(x,y)` surface module.
```
