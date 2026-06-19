# Change Log

Record here any requirement deltas found during the §24 research-refresh
(SPEC_implementation.md) before/while implementing.

## [unreleased]

### §24 Research re-validation — 2026-06-18 (R-1..R-9)

Host = the Windows Fusion machine itself (`C:\dev\fusion-eqcurve`). Findings are
a mix of **empirical** (probed on this host) and **authoritative** (Autodesk /
vendor docs). Items marked **DELTA** change an assumption in the spec.

| # | Item | Result | Status |
|---|---|---|---|
| R-1 | Fusion bundled Python version (PC-3) | **3.14.0** (`python314.dll` in active build `441fa…`, Fusion `2703.1.20`). Autodesk moved 3.12 → 3.14 in 2026. | **DELTA — documented** |
| R-2 | AddIns folder name (WIN-2) | `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns` **exists**; the `…\Autodesk Fusion\…` variant does **not**. | Resolved → use "Fusion 360" path |
| R-3 | Custom Feature compute scope (PC-5, MS-2) | Still a **preview** API; dependency-driven recompute; base feature for new bodies; narrow reliable path unchanged. | Unchanged |
| R-4 | Internal unit = cm (PC-4, ARC-3) | Unchanged; adapter already converts mm→cm at one boundary. | Unchanged |
| R-5 | Custom params in Change/Parameters dialog (MS-2) | Confirmed: custom-feature input values are saved as custom parameters, visible/editable in the Parameters dialog. | Unchanged |
| R-6 | `mcp` package / FastMCP import (bridge/mcp_server) | `from mcp.server.fastmcp import FastMCP` **still valid**; `mcp` latest 1.28.0 (pin `mcp>=1.2.0` fine). A standalone `fastmcp` v3.x now also exists (`from fastmcp import FastMCP`) — optional, not required. | Unchanged (note) |
| R-7 | `claude mcp add` stdio-over-ssh syntax (WIN-4) | Pattern `claude mcp add NAME -- COMMAND ARGS` still current (stdio is the default transport; `--transport stdio` optional). | Unchanged |
| R-8 | Autodesk official MCP/AI tooling (§20, §21) | **Autodesk released official Fusion MCP servers in 2026** (local "Fusion MCP" + remote "Fusion Data MCP"). They are **command/workflow-oriented**, not arbitrary-Python execution. | **DELTA — decision below** |
| R-9 | VS Code ms-python debug attach (DEV-2) | `ms-python.python` auto-installed on first VS Code launch from Fusion; uncheck **Run on Startup** before debugging. Matches DEV-2. | Unchanged |

### Decisions / actions from the deltas

- **R-1 (Python 3.14):** No code change required. This *reinforces* PC-3 / ARC-2
  (stdlib-only): the 2026 update breaks `.pyc`-shipped add-ins and several pip
  packages (e.g. cryptography, google-auth) for users on 3.14, but our add-ins
  ship `.py` source and import **stdlib only**, so they are unaffected. The core
  imports cleanly under both system Python 3.12 and Fusion's 3.14. Spec PC-3 now
  pinned to "3.14 as of 2026-06".
- **R-8 (official Autodesk MCP):** **Keep the custom `FusionEqBridge`** for the
  dev/test harness. The official servers do not expose the arbitrary-Python
  `execute()` + `list_api()` introspection that the agent test loop (TEST-2,
  TEST-4) depends on, and they carry their own auth/cloud surface. The custom
  bridge remains the right tool for §20–21. Re-evaluate if Autodesk later exposes
  a scripting/exec tool. (The official Fusion MCP could still be added *alongside*
  later for command-level automation — out of scope now.)

### Conformance fix (not a research delta)

- `bridge/addin/FusionEqBridge/FusionEqBridge.manifest` had `runOnStartup: true`,
  which violates **SEC-7** and **DEV-4** ("bridge runs only during dev sessions;
  Run on Startup MUST be disabled"). Changed to `false`. The plugin add-in
  (`EquationCurve`) was already `false`.

### Environment verification (runbook §25 step 3) — 2026-06-18

- OpenSSH Server (`sshd`): **Running**. `ssh.exe` present.
- Fusion 360 installed and **running** (PID live), build `2703.1.20`.
- Bundled Python **3.14.0**; system Python **3.12** (pytest target).
- Bridge **live**: `GET /health` → `{"ok":true,"fusion":true}`; bearer token at
  `%LOCALAPPDATA%\fusion-eqbridge\secret` (present). Bound to `127.0.0.1` (SEC-1 ok).
- `execute` smoke test (read-only) returned Fusion version + active Design doc — the
  full agent test loop (TEST-2) works end-to-end.
- Core acceptance tests: **12 passed** via `pytest` on system Python (DEV-5, TEST-1a).
- Not yet present: **git** (project is not a repo — version control recommended
  before further edits). *(Resolved: portable Git installed, repo initialized.)*

### C0 Custom Features live spike — 2026-06-18 (build 2703.1.20)

Resolved every MS-2 unknown by actually building custom features in scratch
documents via the bridge (read-only to the user's design; scratch docs closed
without saving). **The full parametric auto-recompute path is proven working.**

Confirmed API recipe (use verbatim):
- `cdef = adsk.fusion.CustomFeatureDefinition.create(id, name, iconFolder)` —
  **iconFolder must be a real existing directory** (`""` raises "Invalid argument
  iconFolder"). We pass the add-in folder.
- `cdef.editCommandId = EDIT_ID` — **only valid after that CommandDefinition is
  registered** ("Invalid command Id" otherwise). Register edit/regen commands first.
- compute event = `cdef.customFeatureCompute.add(CustomFeatureEventHandler())`.
- Create: `base = comp.features.baseFeatures.add()` → `base.startEdit()` → add
  sketch + fitted splines → `base.finishEdit()`; then
  `cfin = comp.features.customFeatures.createInput(cdef)`;
  `cfin.addCustomParameter(id, name, ValueInput.createByString(PARAM), units, True)`
  (arity-5; the **createByString expression mirrors the design param** so editing
  it re-fires compute); `cfin.addDependency(id, paramEntity)` (a **UserParameter
  is accepted** as the entity); `cfin.setStartAndEndFeatures(base, base)`;
  `cf = comp.features.customFeatures.add(cfin)`.
- **`cf.baseFeature` is None** and `cf.features` / `base.sketches` are bare vectors
  (no `.count`). So we DON'T use `cf.baseFeature`; instead store
  `base.entityToken` + `sketch.entityToken` in `cf.attributes` at create and
  retrieve via `design.findEntityByToken(tok)[0]` in compute.
- Compute (verified): `base.startEdit()` → delete old splines → rebuild from the
  stored CurveDef + current params → `base.finishEdit()` **works inside the
  compute event**. Changing `AMP` 10 mm → 30 mm + `design.computeAll()` re-fired
  compute and the geometry actually changed (max-y 2.0 → 6.0). **FR-8.2 met.**
- Custom params are auto-named (d1, d2…); the design-param link is the
  expression, not the name. Read live values in compute via
  `adapter.read_design_params(design)` (unit-safe).
- Regenerate fallback (PC-8) = `design.computeAll()` (confirmed).
- `addCustomParameter` first two args are id/name but the resulting
  `ModelParameter.name` is auto-assigned — don't rely on it.

Still to verify when implementing C4 (edit): how the edit command surfaces the
double-clicked feature (activeSelections vs an edit context). Editing may not even
need the PC-6 timeline rollback — updating the stored CurveDef attribute + custom
params and calling `computeAll()` rebuilds via the compute handler.

### Definition of Done — checklist status (2026-06-19)

All §25 DoD items met (MS-1 + MS-2 + MS-3 implemented and live-verified on build
2703.1.20):

- [x] §24 research re-validation done + logged (above).
- [x] v0.1 [M] FR implemented: input modes (explicit/parametric), all 2D/3D
      coordinate systems, full function library incl. native hyperbolics, closed
      curves, domain endpoints as expressions, singularity-safe segmentation.
- [x] pytest green (29 deterministic core tests).
- [x] Integration harness: build + lossless re-open in Fusion (MS-1).
- [x] MS-2: timeline Custom Feature + double-click Edit + auto-recompute on
      referenced-parameter change (AMP 10→40 mm verified) + Regenerate (PC-8).
- [x] Security: bridge 127.0.0.1 + bearer token, no external/auto-update, dev
      session only (`runOnStartup:false`).
- [x] Unit conversion at the adapter boundary only (ARC-3); definition stored as
      a JSON attribute, never reverse-derived (ARC-4).
- [x] PC-7 (add-in residency) + PC-8 (recompute) limits documented in README.

C4 edit: the activeSelections-based discovery + edit-overwrite + computeAll rebuild
are verified; only the literal double-click that fires the edit command is left to
manual UI confirmation (standard Fusion behavior). PC-6 timeline rollback proved
unnecessary — re-storing the CurveDef + computeAll rebuilds in place.

MS-3 (this pass): CurveDef.rotation + sampler rotation; presets.py (11 curves);
errors.py (readable messages); dialog preset picker + rotation fields; preview via
transient CustomGraphics; Import/Export commands; circular-reference guard.

Deferred (spec [S]/[C], not in the approved plan): FR-1.3 per-component laws,
FR-8.4 promote-constant-to-param, FR-9.4/9.5 scale/mirror/snap, FR-1.5 surface
module. (FR-10.3 fit tolerance has since been implemented.)

### Spec re-review (v0.1 + v0.2) vs implementation — gap closure 2026-06-19

Re-read both spec documents end-to-end and audited every requirement against the
code (not the prior DoD checklist). Result: **all [M] (Must) requirements are now
implemented.** The audit found two genuine gaps and a latent associativity miss,
all now fixed; the remaining open items are all [S]/[C]/[W] (documented below).

**Closed this pass**

- **FR-8.3 [M] — sample count may be a parameter/expression.** Previously
  `CurveDef.samples` was a plain `int` (t_min/t_max/origin/rotation already
  accepted expressions, but the count did not). Now `samples` accepts an
  expression string (e.g. `10*N`) resolved through the evaluator at sample time
  (`sampler._resolve_samples`, clamped ≥ 2, deterministic). The dialog field
  changed from an integer spinner to a string input; a plain number still
  round-trips as an `int` (back-compatible). Tests: `test_samples_count_can_be_
  an_expression`, `test_samples_expression_below_two_raises`,
  `test_samples_invalid_expression_raises_sampling_error`,
  `test_samples_expression_roundtrips`, `test_samples_plain_integer_stays_int`.
- **FR-7.3 [S] — real-time expression validation.** The dialog now parses every
  expression field on each change and shows a Validation line: the first syntax
  error (named field + message), or any unrecognized identifier that is neither a
  built-in, the independent variable, nor a known design parameter (a "Note", so
  you see *why it would error* before committing), or "OK". `dialog._validate_
  current` / `_refresh_status`, wired through the existing `on_input_changed`.
  Tests: `test_live_validation_flags_syntax_error / _unknown_name / _ok_for_known_param`.
- **FR-8.2 latent fix — rotation & sample-count params are now mirrored.**
  `refs.referenced_names` previously scanned only component exprs + domain +
  origin; it now also scans `rotation` and a `samples` expression, so a parameter
  that drives only rotation or the point count still registers a dependency and
  triggers recompute. Test: `test_referenced_names_includes_rotation_and_samples`.

**Audited present (sampling of [M] items often assumed missing)**

- Function library complete incl. `cot sec csc` (FR-5.1), `atan2` (FR-5.2),
  native hyperbolics + inverses (FR-5.3/5.4), `cbrt` and two-arg `log(x, base)`
  (FR-5.5), `pi e tau phi` (FR-6.1/6.2), and `arc*` aliases for pasted equations.
- Independent-variable rename `var` (FR-3.2) is a dialog field; closed-curve flag
  (FR-10.4) and degree/radian (FR-2.3) present; origin (FR-9.2) and Euler rotation
  (FR-9.3) are expression fields (parameter-referenceable).

**Still open — all [S]/[C]/[W], intentionally deferred (not [M])**

- FR-1.3 [S] per-component mixed laws (NX-style). *Substantially covered*: in
  parametric mode each of x/y/z is already an independent expression in `t`
  (a constant component is just `5`); the only un-covered NX nuance is defining
  one component explicitly in terms of another axis.
- FR-8.4 [S] promote a local constant to a real design parameter.
- FR-8.5 [S] *auto-suggest* a unit correction (the mm/angle convention is already
  applied; only the interactive "insert 1 mm/1 rad" suggestion is absent).
- FR-10.5 [S] choose spline degree / interpolate-vs-approximate.
- FR-11.6 [S] richer change-impact display (Fusion's native yellow "needs
  compute" marker is the current signal).
- FR-1.4 [C] implicit `f(x,y)=0`, FR-5.7 [C] gamma/Bessel, FR-7.4 [C] long-formula
  editor, FR-9.4 [C] scale/mirror, FR-10.7 [C] arc/line approximation,
  FR-1.5 [W] `z=f(x,y)` surface module.

Verification: 57 `pytest` green (was 48; +9 for the above). Live re-verification in
Fusion deferred while the bridge main thread recovers from the UI-refresh pass.

### Modeling validation + UX pass — 2026-06-19

Built and verified real modeling cases live (small, split calls per PC-9 after a
single oversized call — an 800-pt closed epicycloid — froze Fusion ~10 min):
- **Deliverables**: conical spiral spring (cylindrical r=R0+k*t, theta=t, z=pitch*t),
  involute gear flank, epicycloid cycloidal gear profile — all build correctly and
  are added to the preset catalog (14 presets).
- **Modify-panel reactivity (FR-8.2)**: editing a user parameter's expression (what
  the Parameters dialog does) **auto-recomputes** the curve with NO explicit
  computeAll — confirmed live (R0 5→20 mm rescaled the spring).
- **Phase coverage**: every coord system, explicit+parametric, trig/hyperbolic/
  inverse-hyperbolic/exp/log/atan2/abs/floor, degrees, tan-singularity (3 splines),
  rotation+origin — all build.
- **FR-13.4 performance guard**: adapter caps fit points per spline at 300 via
  deterministic core.decimate(); samples=1000 closed now builds in ~6 s.
- **Segmentation fix**: runs split on parameter speed |dP/dt|, not raw distance, so
  adaptive sampling no longer fragments a smooth curve (sin(5x): 10→1 splines).
- **UI (Inventor-style)**: Help & examples panel (how-to, function reference,
  worked examples), preset autofill, and a parameter-insert (suggestion/autofill)
  dropdown. Edit pre-fills the prior definition (lossless). Dialog logic unit-tested
  with a mocked CommandInputs (no Fusion). 38 pytest green; integration harness green.
