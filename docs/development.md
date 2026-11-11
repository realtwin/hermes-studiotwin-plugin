# Development and no-spend verification

Run from the plugin checkout. Use a disposable Hermes home **and isolated interpreter/environment**; a new home alone does not protect a shared managed venv from dependency preparation. Never enable a probe plugin or run `validate --install-deps` against a daily/shared install. Keep evidence and virtual environments outside the scanned checkout.

## Local environment

Node.js 24+ and npm are required by the frozen package manifest. Python 3.11+ is declared; final compatibility must include the host-managed interpreter. This POSIX-shell example uses paths you supply, not machine-specific paths or a live profile:

```sh
# Choose new absolute destinations outside the checkout.
export DOCS_TEST_ROOT=/absolute/new-test-root
export HERMES_AGENT_REPO=/absolute/pinned-hermes-agent-checkout
mkdir -p "$DOCS_TEST_ROOT"
python3 -m venv "$DOCS_TEST_ROOT/venv"
"$DOCS_TEST_ROOT/venv/bin/python" -m pip install -r requirements-test.txt
export HERMES_HOME="$DOCS_TEST_ROOT/home"
mkdir -p "$HERMES_HOME"
export PYTHONPATH="$HERMES_AGENT_REPO"

npm ci
npm run typecheck
npx vitest run
# Run separately, sequentially; keep workers bounded by vitest.config.ts.
STUDIOTWIN_WEBGL_TEST=1 npx vitest run
"$DOCS_TEST_ROOT/venv/bin/python" -m pytest -q
```

These are templates: first replace both `/absolute/...` paths with real new destinations and a pinned host checkout. On Windows, adapt shell environment assignment and the venv's `Scripts/python.exe` path. Existing tests may contain historical host-path/SHA assumptions; inspect them when moving host revisions rather than treating import failures as successful coverage. Do not satisfy a missing host with a shim and call that host-load proof.

Audio/render golden tests require the **same pinned FFmpeg toolchain used to create the goldens**. Record ffmpeg/ffprobe versions; different codec builds can yield different pixels/bytes. Do not regenerate golden fixtures to hide mismatch. A skipped Blender/WebGL case is not a pass. The complete suites, real Blender checks and extended WebGL gate belong to final integration.

The multiview tests import Pillow (`PIL`) unconditionally; `requirements-test.txt` pins Pillow 13.0.0, matching the tested host's frozen uv lock/override. For an isolated source host, bootstrap with its own `uv sync --frozen --no-default-groups` workflow before adding test requirements: plain pip does not honor the upstream uv override that reconciles browser-harness's older Pillow pin.

After renderer source changes, rebuild and commit the generated bundle:

```sh
npm run build:desktop
```

Only `@hermes/plugin-sdk`, `react` and `react/jsx-runtime` should remain external; source dependencies such as three are bundled. The Python metadata is `[project]` only. Do not add a build system or change frozen package/lock constraints just to make a probe pass.

## Helper recipes

The [local tools reference](../skills/studiotwin/references/local-tools.md) is canonical for executable arguments. Run it through Hermes's `terminal` tool on the host that owns the inputs; choose new output paths and preserve originals. Five entry points exist; `render_harness.mjs` is a supporting module, not a sixth CLI.

```sh
python3 skills/studiotwin/scripts/glb_stats.py /absolute/model.glb
node skills/studiotwin/scripts/render_preview.mjs --help
node skills/studiotwin/scripts/render_multiview.mjs --help
python3 skills/studiotwin/scripts/sfx_tool.py --help
python3 skills/studiotwin/scripts/blender_handoff.py --help
```

`glb_stats.py` takes file paths directly; it has no `--help` option. Blender CLI help above validates arguments without importing bpy; actual handoff/render uses the documented Blender background invocation. Help/parser success is not proof that rendering, encoding, audio conversion or fresh-process reimport succeeded. Check JSON/`HANDOFF_RESULT`, output files, measured metadata and exit status.

## Host gates

On an isolated host installation/interpreter with matching dependencies, the ordinary user-facing commands are:

```sh
hermes plugins validate .
hermes plugins doctor --ci .
```

For a source checkout, an explicit isolated host interpreter avoids accidentally invoking the daily launcher:

```sh
"$DOCS_TEST_ROOT/venv/bin/python" -m hermes_cli.main plugins validate .
"$DOCS_TEST_ROOT/venv/bin/python" -m hermes_cli.main plugins doctor --ci .
```

The latter still needs the actual host's dependencies; the plugin test requirements alone are not a complete Hermes install. Install/load/dependency preparation must use a disposable host runtime. `tools/verify_v07.py` is a historical baseline probe with a hard-coded bundled-skill version and `.verification/` output; it is not the canonical final-v1 gate. Likewise [V01 backend notes](v01-backend.md) describe historical slice verification, not an up-to-date release matrix.

## Locked test toolchain security

The owner-authorized narrow test-runner migration pins `vitest@4.1.12` and `@vitest/mocker@4.1.12`; the resolved graph no longer contains tinypool. This replaces the rejected `vitest@3.2.7 / mocker@3.2.7 / tinypool@1.1.1` chain affected by [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9), [GHSA-qxg6-89mg-rqv8](https://github.com/advisories/GHSA-qxg6-89mg-rqv8), [GHSA-5gmw-xhrv-c9v3](https://github.com/advisories/GHSA-5gmw-xhrv-c9v3) and [GHSA-85c8-ppgw-ccpr](https://github.com/advisories/GHSA-85c8-ppgw-ccpr). Full and production-only npm audits report zero advisories on the verified resolved graph; rerun audits because advisory data can change. No unrelated direct dependency was refreshed.

Vitest 4 removes `poolOptions`: use `vitest run --pool=forks --maxWorkers=1`, or bare `vitest run` with the committed serial configuration. The worker heap remains bounded at 3 GiB. The scaffold gate asserts the actual installed version, fork IPC, single worker and heap configuration; full regression and deterministic production-build gates remain required.

The production build uses Vite/Rollup, not Vitest/mocker. An audit pass does not make test execution a sandbox: use trusted local test/config files only, no public Vitest/browser-mock server or `--api` listener, and no secrets in test processes. The release runner uses sequential suites with credential-stripped fixture environments. Do not execute untrusted tests in this environment.

## Live checks and evidence

No paid operation is necessary to validate documentation. Discover/describe current StudioTwin tools read-only when already available; otherwise label the catalog a snapshot. Do not hunt for another profile's credentials, enroll an account, upload to cloud or mutate Concepts to complete a docs check.

Capture raw command, exact plugin/host revision, tool versions, exit status, full test counts/skips and output paths. Preserve failed attempts separately from passing reruns. Local loopback status-poller tests establish polling semantics under fixture inputs, not a live notification delivered to Telegram. See [compatibility](compatibility.md) for evidence classes and native acceptance gates.
