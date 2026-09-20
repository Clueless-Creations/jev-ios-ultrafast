---
name: jev-ios
description: Inspect an iOS test app, use bounded Jev learning for orientation, translate product intent into exact-label scenarios, select affected tests, and run local or SSH Simulator pools without spawning additional coding agents.
---

# Jev iOS

You own product intent and acceptance criteria. Jev chooses among observed controls. The Python runner owns device input, freshness checks, and independent final-label verification. The scheduler owns device leases, fixture locks, API limits, and artifacts.

Use this tool for short semantic navigation and smoke flows. Keep logic tests, backend assertions, visual review, and product acceptance in their own tools. Never claim that every possible user journey has been tested.

## Orient once

1. Read the app's requirements, existing tests, and agent guidance. Identify the authorized fixture app, installed build, simulator UUIDs, and expected starting state.
2. Run `jev-ios doctor` and `jev-ios devices`. These do not make model requests. Build and install the app with the project's existing workflow.
3. Run `jev-ios init --bundle-id com.example.app` in the app repo if no Jev scaffold exists. It preserves existing user files. Read `.jev-ios/AGENT.md`; add a pointer from existing AGENTS.md or CLAUDE.md deliberately, not by overwriting it.
4. Inspect the running app with `jev-ios inspect --udid "$SIMULATOR_UDID" --bundle-id com.example.app --launch`. Labels and model target IDs come from observations, not guesses from source names or screenshots.
5. For unfamiliar navigation, use Jev as a scout within an explicitly approved navigation allow-list. Without one, learning is observe-only and makes no model call.

```sh
jev-ios learn \
  --udid "$SIMULATOR_UDID" --bundle-id com.example.app \
  --allow-label Settings --allow-label Notifications --allow-label Back \
  --max-steps 8 --budget-usd 0.10 \
  --output .jev-ios/app-map-settings.json
```

Replace these labels with controls you have inspected and authorized. Do not infer safety from a name or ask Jev to approve its own action surface. Learning does not type, scroll, or operate switches. Use fixture data and read the compact map instead of loading every raw UI dump into your context.

Maps are sampled orientation, not requirements. App-map v2 uses semantic IDs that exclude coordinates, PIDs and control values. Runtime target IDs and screen fingerprints are observation-specific: never replay them across devices or use them as stable selectors. Regenerate v1 maps; do not silently convert their hash semantics.

## Map intent to evidence

Describe a user outcome, not a coordinate script. Select exact final labels that distinguish the intended destination from the starting screen and global navigation. Inspect missing controls, overlays, accessibility semantics, and scrolling before changing expectations.

```json
{
  "schema": "jev-ios/scenario/v1",
  "name": "Notification settings",
  "goal": "Open notification settings and reach the push-notification controls.",
  "expect_labels": ["Notifications", "Push notifications"],
  "allow_labels": ["Settings", "Notifications"],
  "allow_scroll": false,
  "text_values": {},
  "max_steps": 6,
  "min_probability": 0.55
}
```

Keep short step limits and the default confidence threshold unless evidence justifies a change. Use exact fixture strings for typing. The current adapter accepts printable US ASCII only, in empty non-secure fields.

Author scenarios in the app repository. **Do not modify `jev_ios/scenario.py` to add a test.** It validates the shared contract; tests are JSON data. Remove all scaffold placeholders before planning.

## Put scenarios in a suite

Read `docs/parallel-testing.md` in the installed Jev repository for the complete schema. A suite adds case IDs, starting labels, launch arguments, explicit source-path mappings, tags, critical status, and resource locks without changing scenario semantics.

Prepare known fixture state for every case. Relaunching a process is not resetting its database or backend. Use test-only launch arguments already supported by the app or provision fixtures outside Jev. Starting labels must be checked after relaunch before a model call.

Keep `fixture_isolation: shared` until devices truly have independent accounts and data. Only then use `per_device`. Shared resources still need matching `resource_locks` names. These are cooperating locks on the coordinator, not a distributed backend lock service.

Mark release-critical tests explicitly. Map source globs from real ownership knowledge, not imagined dependencies. An unmapped change falls back to the full suite. Explicit `--only` and `--tag` filters restrict coverage and must be disclosed in the result.

## Plan, execute, summarize

Prefer a MobAI pool when the environment has MobAI, especially for multiple devices, physical devices, remote hosts, or cloud farms. Run `jev-ios mobai-devices`, then add `transport: \"mobai\"` workers using the returned MobAI device IDs. Jev keeps making the semantic decisions while MobAI owns claims, bridge/device routing, predicates, and execution. Use the native AXe/simctl path for the smallest local-only setup or transport comparison. `--devices auto` still selects booted native iOS simulators only. XcodeBuildMCP is not required.

```sh
jev-ios plan --suite .jev-ios/suite.json --pool .jev-ios/pool.json --changed-since main
jev-ios matrix --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --mode shard --parallel 4 --api-concurrency 2 --requests-per-second 4 --budget-usd 1
```

`shard` runs each selected case once on an available lane. `matrix` runs each selected case on every selected device. Always inspect a plan before a large matrix. A four-device matrix reserves for four executions per case; more lanes do not reduce the total inference work.

The coordinator applies one conservative aggregate pricing admission, one request-rate limit, and one API-concurrency gate. Each device has a lease and independent model client. No extra frontier-agent sessions are launched. Provider authentication/rate-limit errors stop further fanout rather than retrying requests automatically.

Read `summary.json` or the final `matrix_result` event first. Load individual traces only for relevant failures. Similar failure groups are shared symptoms, not established root causes. Report the selection scope, installed build provenance if supplied, devices, verified count, and unresolved outcomes.

## Diagnose without erasing evidence

Exit codes for matrix/verify: 0 means every selected cell has label evidence; 2 means not verified; setup/configuration errors use 1. Interrupted matrix runs use 130. Planning, init and observe-only learning returning 0 do not mean the app passed tests.

Use the returned unique run directory. Never delete a previous trace just to reuse its filename. A failed or incomplete run is not made green by hiding a skipped cell or weakening an assertion.

```sh
jev-ios verify --manifest runs/<run-directory>/matrix.json
jev-ios reproduce --manifest runs/<run-directory>/matrix.json --cell <cell-id>
```

Reproduction is dry by default. Classify the failure as product behavior, incorrect scenario intent, accessibility, fixture/start state, device transport, or provider error. Repair the responsible layer, restore the fixture, and add `--execute` only when ready to authorize a fresh run. Uncertain/cancelled input needs `--acknowledge-uncertain` after repair. This reruns intent, not old actions, and does not reinstall the original binary.

## Extend the narrowest layer

| Need | Surface |
| --- | --- |
| Add a user-flow check | Scenario JSON in the app repo |
| Map tests to sources, fixtures, and devices | Suite/pool JSON; `jev_ios/suite.py` validates them |
| CLI options and pricing admission | `jev_ios/cli.py`, `jev_ios/parallel_cli.py` |
| Schedule lanes and bound API concurrency | `jev_ios/matrix.py` |
| Cross-process device or fixture leases | `jev_ios/lease.py` |
| Local Simulator, SSH, or MobAI sessions | `jev_ios/fleet.py`, `jev_ios/remote.py`, `jev_ios/mobai.py` |
| Semantic scouting and onboarding | `jev_ios/learning.py`, `jev_ios/onboarding.py` |
| Device input and fresh observation | `jev_ios/device.py` |
| Bounded action/verification loop | `jev_ios/runner.py` |
| Jev transport and choice validation | `jev_ios/model.py` |
| Aggregation and reports | `jev_ios/matrix_report.py`, `jev_ios/report.py` |

Read `AGENTS.md` and `docs/architecture.md` before runtime changes. Preserve observed target identity, fresh validation, finite confidence, bounded calls, secure-field redaction, and no replay after uncertain execution. No model output becomes a shell command, coordinate, credential, or authorization.

Keep tests offline. Do not describe mock-backed concurrency tests as live Simulator speed benchmarks. Do not add hosted GitHub Actions workflows. Run the repo's Python and Node checks and report exactly which validation was performed.


## Exploit MobAI instead of rebuilding it

When MobAI is available, use its strengths deliberately:

- Let MobAI provide local, physical, remote, distributed, and cloud device reach.
- Let MobAI device claims enforce exclusive lanes in addition to Jev's scheduler.
- Prefer MobAI semantic predicates and compact UI trees over coordinates/screenshots.
- Use MobAI OCR only when the semantic tree is insufficient; do not make screenshots the normal Jev state.
- Promote stable Jev-discovered paths to deterministic MobAI `.mob` flows so known navigation stops consuming inference.
- Use `mobai-ci` for deterministic CI suites, sharding, report bundles, and provider device farms. Use Jev matrix runs where decisions remain dynamic.
- Consider MobAI `simslim` only as an opt-in host optimization for dense local Simulator fleets, after qualifying the app.

Do not route Jev through MobAI MCP inside the runtime. MCP is useful when the coding agent itself needs interactive MobAI tools. The Jev scheduler uses MobAI's HTTP/DSL surface directly, avoiding an extra agent/tool round trip.
