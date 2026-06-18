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
5. Add the **EquationCurve** plugin **in place** (do NOT copy it): Fusion ▸
   Shift+S ▸ the green **+** ▸ pick `eqcurve/addin/EquationCurve` inside the
   project. It imports the `eqcurve` package by walking up to the project root,
   so it must run from the project tree (copying it into AddIns breaks the
   import). Then **Run** it — three commands appear in Sketch ▸ Create:
   *Equation Curve*, *Edit Equation Curve*, *Regenerate Equation Curves*.

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

## 5. Status (against the feature spec)

- **MS-1 — done:** create curve; lossless `CurveDef` store + re-edit; full
  function library incl. native hyperbolics; 2D/3D + all coord systems; closed
  curves; singularity-safe **segmentation** (e.g. `tan` over `[-pi,pi]` builds
  several splines instead of one bridging the asymptotes); deterministic
  curvature-adaptive sampling (opt-in); self-intersection/degenerate diagnostics.
- **MS-2 — done:** parameter-associative **Custom Feature** — a timeline node
  that **auto-recomputes when a referenced design parameter changes** (verified
  live: `AMP` 10→40 mm rescales the curve), built inside a base feature for the
  reliable compute path, double-click **Edit**, and a **Regenerate** fallback
  command (PC-8). See `eqcurve/addin/EquationCurve/custom_feature.py`.
- **MS-3 — done:** preset catalog (14 curves, incl. **cycloidal gear, involute
  gear, conical spiral spring**), real-time preview (transient custom graphics),
  origin + Euler rotation transform, definition import/export (JSON), readable
  error messages, circular-reference guard, chord-deviation fit tolerance
  (FR-10.3), and a tutorial/Help-&-examples panel with a **parameter-insert
  (autofill/suggestion)** dropdown and a function reference (Inventor-style).
- **Interactive placement:** pick a **sketch plane** (or planar face) to build on,
  and an **origin point** (sketch/construction point or vertex) the curve is
  anchored to — constrain or move that point and the curve **follows** it
  (verified live). The generated sketch is fully equation-defined.
- **Verified end-to-end (live):** all coord systems + the full function library
  build real curves; editing a parameter in the **Parameters/Modify panel
  auto-recomputes** the curve (no manual Regenerate); a performance guard caps
  spline fit points so high counts can't freeze Fusion (FR-13.4). The three
  deliverables were **extruded/solidified into 3D** and visually reviewed:
  an involute-style spur gear, a cycloidal/sprocket gear, and a conical spiral
  spring (helix piped into a tapered spring).
- **Future ([S]/[C], out of the current plan):** per-component mixed laws
  (FR-1.3), points-per-unit density (FR-3.4), promote-local-constant-to-parameter
  (FR-8.4), scale/mirror + snap (FR-9.4/9.5), spline degree/fit method (FR-10.5),
  `z=f(x,y)` surface module (FR-1.5).

### Units & limitations

- **Units (FR-8.5):** in equations a **length** parameter is read in **mm** (a
  `50 mm` parameter is `50`), via `unitsManager`; angle/unitless params keep their
  raw value. Conversion lives only in `eqcurve/adapter.py` (`read_design_params`).
- **Add-in residency (PC-7):** the curve is only live while the `EquationCurve`
  add-in is loaded. Opened on a machine without it, the geometry is static (dumb).
- **Recompute (PC-8):** editing a **mirrored** parameter recomputes silently.
  Some model-graph changes may instead leave the feature marked for update — use
  **Regenerate Equation Curves** (or any model recompute) to refresh.
```
