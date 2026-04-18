# Engine Smoke Fixtures and CI Hook Templates (C7 / C8)

This document provides minimal fixtures and optional CI wiring for
`scripts/engine_smoke_bpmn.py` proof runs.

## Minimal Proof Fixtures

- [scripts/engine_smoke_fixtures/c7_smoke_min.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c7_smoke_min.bpmn)
  - Camunda 7 executable-shape minimum: `startEvent -> external serviceTask -> endEvent`
  - Uses required Camunda 7 service-task profile:
    - `camunda:type="external"`
    - `camunda:topic="..."`
- [scripts/engine_smoke_fixtures/c7_happy_path.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c7_happy_path.bpmn)
  - Same as `c7_smoke_min` but explicit happy-path naming for deployability fixtures.
- [scripts/engine_smoke_fixtures/c7_failing.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c7_failing.bpmn)
  - Negative fixture for profile-aware C7 pre-checks (external serviceTask without `camunda:topic`).

- [scripts/engine_smoke_fixtures/c8_smoke_min.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c8_smoke_min.bpmn)
  - Camunda 8 executable-shape minimum: `startEvent -> serviceTask -> endEvent`
  - Uses required Camunda 8 profile:
    - `zeebe:taskDefinition` with `type`
- [scripts/engine_smoke_fixtures/c8_happy_path.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c8_happy_path.bpmn)
  - Same as `c8_smoke_min` but explicit happy-path naming for readability.
- [scripts/engine_smoke_fixtures/c8_message_wait.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c8_message_wait.bpmn)
  - Message wait happy-path with top-level `<bpmn:message>` and `zeebe:subscription`.
- [scripts/engine_smoke_fixtures/c8_timer_path.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c8_timer_path.bpmn)
  - Intermediate timer wait path using valid `timeDuration`.
- [scripts/engine_smoke_fixtures/c8_failing.bpmn](/Users/kkitanin/.codex/skills/camunda-bpmn-from-context/scripts/engine_smoke_fixtures/c8_failing.bpmn)
  - Negative fixture for runtime-aware C8 checks (`priorityDefinition` out of range).

## Engine Smoke Invocation Contract (Script-Level)

`engine_smoke_bpmn.py` supports:

- `--import-cmd`
- `--deploy-cmd`
- `--process-test-cmd`
- optional `--shell` / `BPMN_SMOKE_SHELL`
- command placeholders: `{input}`, `{input_path}`, `{camunda_version}`

Example usage:

```bash
python3 scripts/engine_smoke_bpmn.py scripts/engine_smoke_fixtures/c8_smoke_min.bpmn \
  --camunda-version 8 \
  --deploy-profile 8 \
  --report .artifacts/engine-smoke-c8.json
```

## Fixture-Backed Acceptance Matrix

`scripts/engine_smoke_matrix.py` now supports a fixture-backed acceptance mode on top of the legacy engine-smoke mode.

Key acceptance inputs:

- `scripts/fixtures/fixture_inventory.json`
- `scripts/fixtures/fixture_lineage.json`
- pipeline entrypoint (`scripts/run_bpmn_pipeline.py` by default)
- manifest validator (`scripts/validate_run_manifest.py` by default)
- preview builder (`scripts/build_preview_artifacts.py` by default)

Gate profiles:

- `pr`: required fixtures, selector repeatability, negative exclusions, manifest schema, lineage, and preview smoke must pass.
- `release_candidate`: same required gates as `pr`, including mandatory preview smoke.
- `nightly`: fixture gates and lineage are required; preview smoke is optional.

Example PR gate invocation:

```bash
python3 scripts/engine_smoke_matrix.py \
  --mode acceptance \
  --gate-profile pr \
  --report-dir .artifacts/acceptance-pr \
  --preview-smoke-cmd "cd node_tooling && PREVIEW_DIR=\"$PREVIEW_DIR\" npm run preview:smoke"
```

Example nightly invocation (preview smoke optional):

```bash
python3 scripts/engine_smoke_matrix.py \
  --mode acceptance \
  --gate-profile nightly \
  --report-dir .artifacts/acceptance-nightly
```

The acceptance summary is emitted to `<report-dir>/matrix_summary.json` and includes per-fixture records with:

- `fixture_id`, `scenario_id`, `manifest_id`
- backend transition fields (`initial_backend`, `final_backend`, `fallback_happened`)
- deterministic gate booleans and per-fixture errors

## Unified Release Gate

For release decisions, run the acceptance matrix in `release_candidate` mode so the harness evaluates the full surface in one pass:

```bash
python3 scripts/engine_smoke_matrix.py \
  --mode acceptance \
  --gate-profile release_candidate \
  --report-dir .artifacts/release-candidate \
  --preview-smoke-cmd "cd node_tooling && PREVIEW_DIR=\"$PREVIEW_DIR\" npm run preview:smoke"
```

This invocation also runs governance validation through `scripts/validate_governance_docs.py` and writes:

- `matrix_summary.json`
- `governance_validation.json`

The matrix summary is the single release-gate record for the run.

Gate behavior:

- `pr` and `nightly` report governance status but do not fail the existing pass path unless governance is explicitly required.
- `release_candidate` requires governance, manifest schema, preview smoke, and acceptance gates to pass together.

## Optional CI Hook (GitHub Actions, placeholder-only)

Commands must be provided via environment and not hardcoded to a specific host.
Use repository variables/secrets for host, tenant, and auth details.

> For Camunda 7/8 deployability proof, treat `SKIPPED`, `MISCONFIGURED`, and `NOT_VERIFIED` as **not deployable**. Only `PASS` is considered sufficient for `deploy profile` proof.

```yaml
name: Engine Smoke Proof

on:
  workflow_dispatch:
  schedule:
    - cron: "0 2 * * *"

jobs:
  camunda8-smoke:
    runs-on: ubuntu-latest
    env:
      BPMN_SMOKE_IMPORT_CMD: ${{ vars.C8_SMOKE_IMPORT_CMD }}
      BPMN_SMOKE_DEPLOY_CMD: ${{ vars.C8_SMOKE_DEPLOY_CMD }}
      BPMN_SMOKE_PROCESS_TEST_CMD: ${{ vars.C8_SMOKE_PROCESS_TEST_CMD }}
      BPMN_SMOKE_SHELL: ${{ vars.C8_SMOKE_SHELL }} # optional
      BPMN_SMOKE_PROFILE: "8"
    steps:
      - uses: actions/checkout@v4
      - name: Run Camunda 8 engine smoke
        run: |
          mkdir -p .artifacts
          python3 scripts/engine_smoke_bpmn.py \
            scripts/engine_smoke_fixtures/c8_smoke_min.bpmn \
            --camunda-version "${BPMN_SMOKE_PROFILE}" \
            --deploy-profile "${BPMN_SMOKE_PROFILE}" \
            --report .artifacts/engine-smoke-c8.json

  camunda7-smoke:
    runs-on: ubuntu-latest
    env:
      BPMN_SMOKE_IMPORT_CMD: ${{ vars.C7_SMOKE_IMPORT_CMD }}
      BPMN_SMOKE_DEPLOY_CMD: ${{ vars.C7_SMOKE_DEPLOY_CMD }}
      BPMN_SMOKE_PROCESS_TEST_CMD: ${{ vars.C7_SMOKE_PROCESS_TEST_CMD }}
      BPMN_SMOKE_SHELL: ${{ vars.C7_SMOKE_SHELL }} # optional
      BPMN_SMOKE_PROFILE: "7"
    steps:
      - uses: actions/checkout@v4
      - name: Run Camunda 7 engine smoke
        run: |
          mkdir -p .artifacts
          python3 scripts/engine_smoke_bpmn.py \
            scripts/engine_smoke_fixtures/c7_smoke_min.bpmn \
            --camunda-version "${BPMN_SMOKE_PROFILE}" \
            --deploy-profile "${BPMN_SMOKE_PROFILE}" \
            --report .artifacts/engine-smoke-c7.json
```

## Reproducible Proof Command Templates

Use these templates only as examples; they are environment-injected and may call local CLI,
REST API clients, or remote runners for your stack.

- **Camunda 7 import/open**
  - `camunda7-client process import --tenant ${TENANT_ID} --name smoke --file {input_path}`
- **Camunda 7 deploy**
  - `camunda7-client process deploy --tenant ${TENANT_ID} --name smoke --file {input}`
- **Camunda 7 process smoke**
  - `camunda7-client process test --tenant ${TENANT_ID} --process-id SmokeProcess7Happy`

- **Camunda 8 import/open**
  - `zbctl deploy {input_path} --tenant ${TENANT_ID}`
- **Camunda 8 deploy**
  - `zbctl deploy {input} --tenant ${TENANT_ID}`
- **Camunda 8 process smoke**
  - `zbctl create instance --tenant ${TENANT_ID} SmokeProcess8Happy --withResult`

### Recommended command templates for env vars

Set these repository variables/secrets so they can be reused by both local and CI runs.

- `C8_SMOKE_IMPORT_CMD`, `C8_SMOKE_DEPLOY_CMD`, `C8_SMOKE_PROCESS_TEST_CMD`
- `C7_SMOKE_IMPORT_CMD`, `C7_SMOKE_DEPLOY_CMD`, `C7_SMOKE_PROCESS_TEST_CMD`

Each command should consume `{input}`/`{input_path}` and return a non-zero exit code on failure, for example:

- `... -f {input_path} --tenant "${TENANT_ID}"`
- `... --model "{input}" ... --runtime "{camunda_version}"`

Only use placeholders supported by the smoke script (`{input}`, `{input_path}`, `{camunda_version}`).

## Exit Semantics

- Script PASS = all 3 engine steps succeeded (import/deploy/process-test).
- Any failure or missing step configuration means the proof is not deployability-verified.
