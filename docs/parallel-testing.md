# Parallel semantic testing

One coordinator schedules Python workers, not additional coding-agent sessions. Each device has an exclusive lane and each case gets a bounded Jev decision loop. The existing runner still owns target validation, freshness checks, and final exact-label evidence.

## Two scheduling modes

`--mode shard` places selected scenarios in a shared queue. Each available lane takes the next case, so each scenario runs once across the pool. This is the inner-loop option when devices are interchangeable.

`--mode matrix` runs every selected scenario on every selected device. Use an explicit pool when the device/OS combination is part of the intended coverage. Device names are labels you supply; Jev does not infer that a name matches a particular hardware model or runtime.

`--parallel` limits active device lanes. `--api-concurrency` separately limits in-flight Jev decisions, and `--requests-per-second` spaces request starts across the entire coordinator, including SSH devices. Defaults are 2 lanes, 2 model requests, and 4 starts per second. These are configurable client limits, not claims about a provider quota.

## Prepare fixtures first

The app must be built and installed on every selected simulator. The matrix command waits for each device to boot and launches the explicit bundle ID with `--terminate-running-process` before every case. It then checks the configured `start_labels` before making a model request.

Relaunching does not reset persistent storage, authentication, or backend data. Supply app-supported test launch arguments or prepare data externally. A missing start label blocks that case and stops its lane rather than silently attempting to recover by tapping around.

Suites default to `fixture_isolation: shared`. This serializes cases using a shared fixture lock even when several device lanes exist. Set `per_device` only when fixture data and accounts are independent across devices. Individual `resource_locks` can still serialize flows that share something, such as a test account or seeded cart.

Device leases apply to cooperating Jev processes using the same OS account on a device host. Fixture/resource locks apply to cooperating jobs on the coordinator. They are not a distributed lock service for a backend used from other machines. For multiple independent coordinators, partition fixture data or use an external lease service.

## Suite file

Scenarios retain `jev-ios/scenario/v1`. A suite adds scheduling and selection metadata:

```json
{
  "schema": "jev-ios/suite/v1",
  "name": "Release smoke",
  "bundle_id": "com.example.app",
  "fixture_isolation": "shared",
  "start_labels": ["Home", "Settings"],
  "launch_args": ["--ui-testing"],
  "cases": [
    {
      "id": "notifications",
      "scenario": "cases/notifications.json",
      "paths": ["Sources/Settings/*", "Sources/Navigation/*"],
      "tags": ["smoke", "settings"],
      "critical": true,
      "resource_locks": ["notification-fixture-account"]
    }
  ]
}
```

The example labels and `--ui-testing` argument must match your app. Jev does not add a fixture mode to the app for you.

Case IDs are unique ASCII letters, digits, underscores and hyphens, up to 64 characters. A suite has 1-500 cases. Scenario paths must resolve inside the suite directory. Source globs are relative to the app repository and use Python `fnmatchcase` semantics; `*` can span path separators. Put critical shared components in relevant case mappings, or rely on the conservative unmapped-change fallback.

A case may override `start_labels` and `launch_args`. Every case needs at least one exact starting label. Arguments are passed as an argv list, not evaluated as a shell expression. Unknown fields, duplicate JSON keys, non-finite numbers, missing scenarios, and scaffold placeholders are rejected.

## Device pool

```json
{
  "schema": "jev-ios/pool/v1",
  "devices": [
    {"name": "local-phone", "udid": "11111111-1111-1111-1111-111111111111"},
    {
      "name": "remote-phone",
      "udid": "22222222-2222-2222-2222-222222222222",
      "host": "jev-mac",
      "python": "/Users/runner/jev/.venv/bin/python",
      "axe": "/opt/homebrew/bin/axe"
    }
  ]
}
```

Replace the example UUIDs and paths. A pool contains 1-32 unique device names and host/UUID pairs. Without `host`, execution is local. With `host`, it uses a trusted SSH alias or `user@host`. Configure ports and keys in your SSH config, not by putting options in the host field. `python` and `axe` refer to executables on that host.

Alternatively, repeat `--udid` for local simulators. `--devices auto` selects already booted, available local iOS simulators only. It does not create clones, select unavailable runtimes, or provision cloud devices. Use explicit pools for repeatable device-matrix coverage.

### Remote Mac setup

Provision the Mac and its Simulator outside Jev. Install this same repository revision into the remote Python environment, install standalone AXe, and install the fixture app. Verify your normal SSH connection and host-key trust before running a pool.

The coordinator starts `python -m jev_ios.remote` over SSH and exchanges bounded device-only messages. Jev inference remains on the coordinator, so remote workers do not need the gateway API key. Both sides must run matching code. A protocol mismatch or broken connection fails the lane; it does not trigger automatic action replay.

This supports an SSH-accessible hosted Mac, not a vendor device-farm API. Physical devices, Android, MobAI, cloud provisioning, and remote screenshot/video transfer are not implemented. No multi-device hardware benchmark has been collected for this scheduler.

## Inspect the plan

An explicit pool allows planning without a Mac, device connection, credential, or inference request:

```sh
jev-ios plan --suite .jev-ios/suite.json --pool .jev-ios/pool.json --mode matrix
```

With `--devices auto`, planning must list local simulator metadata, but performs no input or model call.

For change impact:

```sh
jev-ios plan --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --changed-since main --project-root .
```

This includes committed changes relative to the requested revision, staged/unstaged changes, untracked files, deletions, and both paths of renames. It selects directly mapped cases, critical cases, and cases without source mappings. If any changed path is not mapped by the suite, it selects the full suite. The plan records reasons, omissions, and the resolved comparison SHA.

`--only <case-id>` and `--tag <tag>` are explicit coverage restrictions. They can exclude critical cases, so do not describe such a run as the full regression suite. An empty selection may be inspected as a plan but cannot return a passing matrix execution.

Selection is deterministic metadata matching, not inferred semantic dependency analysis. App maps help the coding agent author the mappings; no model silently changes coverage or assertions.

## Execute

```sh
jev-ios matrix \
  --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --mode shard --parallel 4 \
  --api-concurrency 2 --requests-per-second 4 \
  --task-timeout 180 --budget-usd 1 \
  --app-revision '<installed build identifier>'
```

Use `--mode matrix` to run all selected cases on all selected devices. `--changed-since`, `--only`, and `--tag` use the same selection rules as `plan`.

Before any device session opens, the coordinator admits the whole plan against current catalog pricing. The reservation covers every possible bounded decision and speculative choice head across all scheduled cells. This is a conservative admission limit, not a provider-enforced billing cap or measured cost. A matrix multiplies work by device count; extra concurrency does not make requests free.

Set `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN` in the coordinator environment, or use an existing Vercel CLI project with `--vercel-project`. Keys never enter suite files, device messages, or reports. Request and device timeouts remain bounded. `--task-timeout` is cooperative: cancellation prevents new actions, but waits for an in-flight bounded command to settle before releasing the device lease.

HTTP 401, 403, and 429 stop further fanout. There are no automatic model retries, scenario retries, or cross-device action cache. A stale pre-input observation may be discarded and observed again within the existing runner's call budget. That is not replaying an action that may already have executed.

`--fail-fast` stops scheduling after the first non-verified result. Otherwise independent lanes continue; an uncertain, timed-out, broken, or invalid-start lane is quarantined. Signal interruption cancels pending work and preserves completed evidence.

## Artifacts and verification

Every run gets a unique directory unless you explicitly provide a new `--output-dir`. Existing output directories are rejected. Per-cell names use validated IDs and each file is private to the OS account.

```text
runs/matrix-<timestamp>-<id>/
  plan.json          Frozen scenarios, digests, pool, selection, provenance
  matrix.json        Checkpoints and final results, including skipped work
  summary.json       Compact result and grouped failure symptoms
  index.html         All cells and evidence links
  junit.xml          Test-runner integration
  <cell-id>/
    scenario.json
    trace.jsonl
    result.json
    report.html
```

In `shard` mode, a cell ID is the case ID. In `matrix` mode, it is `case-id@device-name`.

A final manifest passes only when every planned cell has a `jev-ios/run/v1` verified result with all required exact labels. A checkpoint, missing cell, skipped cell, interrupted job, or unavailable lane cannot be green. `verify` rechecks this saved evidence without running tests:

```sh
jev-ios verify --manifest runs/<run-directory>/matrix.json
```

Matrix/verify exit codes are 0 for verified selected coverage and 2 for not verified. Invalid setup/configuration uses 1; an interrupted matrix uses 130. `plan`, `init`, and observe-only `learn` returning 0 are not test acceptance.

The summary groups common reasons and missing labels to reduce agent context. These are matching symptoms, not a claim about root cause. Open only the relevant cell reports and trace events when diagnosing. App labels and traces may contain private data; keep `runs/` ignored and review evidence before sharing it.

Source Git SHA and dirty status are recorded separately from caller-supplied `--app-revision`. Jev does not prove that a Git checkout matches the installed binary. Starting-label and final-label checks are not backend assertions or visual acceptance.

## Deliberate reproduction

```sh
jev-ios reproduce --manifest runs/<run-directory>/matrix.json --cell notifications@local-phone
```

This emits a dry reproduction plan using the recorded scenario and its digest. It does not call a provider or touch a device. For a skipped shard cell without a device assignment, select `--device-name` from the saved pool.

After inspecting the failure and restoring the fixture:

```sh
jev-ios reproduce --manifest runs/<run-directory>/matrix.json \
  --cell notifications@local-phone --execute --budget-usd 0.10
```

An original `uncertain` or `cancelled` result also requires `--acknowledge-uncertain`. The rerun creates fresh artifacts and goes through pricing admission again. It uses current app state; it does not reinstall the recorded build, restore a database snapshot, or replay recorded input.

## Verification before increasing scale

The offline tests exercise real scheduler threads, process locks, Git selection, and subprocess RPC using fake model/device adapters. They prove these software contracts, not AXe isolation or throughput on real hardware.

Before widening a pool, run one fixture on two real simulators with distinct starting data, confirm actions stay on their assigned UDIDs, check that devices and app accounts do not interfere, and inspect independent final evidence. Repeat for the target remote Mac/runtime. Increase lanes only while host resources and provider limits allow useful progress. Never convert a mocked latency measurement into a product speed claim.
