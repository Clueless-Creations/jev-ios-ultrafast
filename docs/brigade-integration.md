# Call from Brigade

A Brigade host can run this package as a bounded local subprocess on a Mac with a simulator. The supplied Node wrapper invokes the CLI and returns its final NDJSON result. Native Brigade operation registration, scheduling, and acceptance remain separate integration work.

Install the package in a local Python environment, then call the wrapper from the host:

```js
import { runSimulatorGoal } from './examples/brigade-call.mjs';

const result = await runSimulatorGoal({
  root: process.env.JEV_IOS_ROOT,
  python: process.env.JEV_IOS_PYTHON || 'python3',
  udid: process.env.SIMULATOR_UDID,
  bundleId: 'com.example.app',
  goal: 'Open the settings screen',
  expectLabels: ['Settings', 'Notifications'],
  allowLabels: ['Settings'],
  maxSteps: 6,
  timeoutMs: 120_000,
  tracePath: 'runs/settings.jsonl',
});
```

`root` points to this checkout. `python` must identify the environment where the package is available. Gateway credentials come from the inherited process environment. An optional `vercelProject` requests an in-memory development OIDC token through an existing Vercel CLI login. Keep credentials out of invocation arguments and scenario files.

The wrapper passes an argument array without a shell, parses NDJSON, and rejects invalid output, missing results, nonzero exits, and timeouts. An interrupted child may have dispatched an action. Observe the simulator before scheduling another attempt; never replay the last input automatically.

The CLI also accepts a portable scenario:

```sh
jev-ios run \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" \
  --bundle-id org.example.jevsimdemo \
  --trace runs/daybreak.jsonl --report runs/daybreak.html
```

Pass the same scenario through the wrapper by replacing `goal` and `expectLabels` with `scenarioPath`:

```js
const result = await runSimulatorGoal({
  root: process.env.JEV_IOS_ROOT,
  python: process.env.JEV_IOS_PYTHON || 'python3',
  udid: process.env.SIMULATOR_UDID,
  bundleId: 'org.example.jevsimdemo',
  scenarioPath: 'scenarios/showcase.json',
  tracePath: 'runs/daybreak.jsonl',
  recordVideoPath: 'runs/daybreak.mp4',
  screenshotPath: 'runs/daybreak.png',
  reportPath: 'runs/daybreak.html',
});
```

`scenarioPath` is mutually exclusive with `goal` and `expectLabels`. Omit `maxSteps` to retain the scenario's limit; a direct goal uses the CLI's default of 12. An explicit `maxSteps` must be an integer from 1 to 30. Nonempty `allowLabels` replaces the scenario's tap allowlist. All artifact paths must be distinct, and video paths must end in `.mp4`. Relative paths resolve under `root`.

`timeoutMs` defaults to 120,000 and accepts integers from 1 to 600,000. At timeout, the wrapper sends SIGTERM and allows `killGraceMs` for recording cleanup before SIGKILL. The grace period defaults to 20,000 ms and accepts 1–20,000; keep the default when recording. Rejection waits for process closure, so allow the timeout plus cleanup grace in the calling worker's budget. The wrapper requires exactly one result with schema `jev-ios/run/v1` and status `verified`, and never copies arbitrary stderr or error-event content into its error message.

Use the [architecture notes](architecture.md) and the source protocols when embedding the Python runner directly. The host should retain the target identity, approved scenario, and trace location alongside the returned result. `status: "verified"` means the scenario's exact labels were observed; it does not approve the app, its backend, or a release.

## Native provider integration

A native Brigade adapter would translate its mobile-operation requests into this runner's device operations and return receipts through Brigade's transport contract. The host remains responsible for authority, target/build binding, scheduling, retries, and acceptance. Jev selects among offered actions; it does not grant authority to perform them.

Before advertising that adapter as supported, register its operations in Brigade, map only implemented capabilities, preserve observation provenance, and run Brigade's current mobile-operation conformance checks against a real target. Pin the source version and obtain independent review. A callable subprocess alone does not establish those guarantees.
