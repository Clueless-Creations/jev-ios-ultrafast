# Jev iOS Ultrafast

**Give this repo to your coding agent. It can learn the app, create semantic test scenarios, and verify UI work across local, remote, physical, and cloud devices without spawning more coding agents.**

Jev handles the tiny repeated decisions. [MobAI](https://mobai.run/) handles device infrastructure when you need a fleet. Your coding agent keeps the engineering context.

[Agent skill](SKILL.md) · [Agent setup](docs/agent-integration.md) · [MobAI + devices](docs/device-adapters.md) · [Parallel testing](docs/parallel-testing.md) · [Architecture](docs/architecture.md) · [Demo](https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html) · [MIT](LICENSE)

<a href="https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html"><img src="docs/media/comparison-preview.gif" alt="Jev controlling an iOS Simulator and verifying the result" width="100%" /></a>

## Give it to your agent

Point Codex, Claude Code, or another shell-capable coding agent at this repository and say:

> Use https://github.com/Clueless-Creations/jev-ios-ultrafast to verify this app. Read its SKILL.md first. Set Jev up non-destructively, learn only the app areas needed for this task, create focused scenarios from observed UI state, and run the relevant verification after user-facing changes. Prefer MobAI when it is already available or when multiple, physical, remote, or cloud devices are useful. Do not weaken acceptance criteria to make a test pass.

The agent should then follow [SKILL.md](SKILL.md). You should not need to teach it Jev's Python internals, MobAI DSL, or a second scenario language.

## What happens

```text
                    coding agent
                         |
                      SKILL.md
                         |
           product intent + code change
                         |
              learn / inspect / plan
                         |
                         v
                        Jev
             small semantic decisions
                         |
                  Python scheduler
                 /                \
        native Simulator          MobAI
         AXe + simctl      claims + compact UI + DSL
                 \                /
                  device / cloud fleet
                         |
                  fresh evidence
                         |
                  compact summary
                         |
                    coding agent
```

There is one engineering agent, not one agent per device. Parallel lanes are Python workers making bounded Jev API calls. The expensive agent gets the result, not forty simulator transcripts.

## Fastest path

### 1. Install Jev

macOS local-only path:

```sh
git clone https://github.com/Clueless-Creations/jev-ios-ultrafast.git
cd jev-ios-ultrafast
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
jev-ios doctor
```

The native iOS Simulator path needs Python 3.11+, Xcode and standalone [AXe](https://github.com/cameroncooke/AXe). XcodeBuildMCP is **not** required.

Set `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN` on the coordinator, or use `--vercel-project` with an existing Vercel CLI login. Credentials do not belong in scenarios or reports.

### 2. Initialize the app repo

From the app you want the agent to work on:

```sh
jev-ios init --bundle-id com.example.app
```

This creates:

```text
.jev-ios/
  AGENT.md       small local handoff for the coding agent
  SKILL.md       the complete Jev operating skill
  smoke.json     first scenario
  suite.json     scenario scheduling + impact mapping
  run-smoke.sh   one-command local verification
  .gitignore     ignores Jev files inside .jev-ios
```

It does not overwrite your existing `AGENTS.md`, `CLAUDE.md`, or root `.gitignore`. Add one pointer to the agent guide and add `/runs/` to the host repo root `.gitignore` so private traces/reports are not accidentally committed:

> For user-facing mobile work, read `.jev-ios/AGENT.md` and `.jev-ios/SKILL.md`, then run the relevant Jev verification before declaring the change complete.

### 3. Let the agent orient itself

For a local Simulator:

```sh
jev-ios devices
jev-ios inspect --udid "$SIMULATOR_UDID" --bundle-id com.example.app --launch
```

For an unfamiliar app area, the agent can use bounded Jev learning after it has inspected and explicitly approved navigation controls:

```sh
jev-ios learn \
  --udid "$SIMULATOR_UDID" --bundle-id com.example.app \
  --allow-label Settings --allow-label Notifications --allow-label Back \
  --max-steps 8 --budget-usd 0.10 \
  --output .jev-ios/app-map-settings.json
```

The map is orientation, not product truth. The agent still defines success from the requested behavior and verifies exact observed labels.

### 4. Verify the change

```sh
.jev-ios/run-smoke.sh
```

Or select tests affected by the current change and fan them out:

```sh
jev-ios plan --suite .jev-ios/suite.json --pool .jev-ios/pool.json --changed-since main

jev-ios matrix \
  --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --changed-since main --mode shard --parallel 4 \
  --api-concurrency 2 --requests-per-second 4 --budget-usd 1
```

The agent reads `summary.json` first and opens individual traces only when needed.

## Jev + MobAI

MobAI is the recommended transport when you want more than the smallest local-Simulator setup.

```sh
export MOBAI_URL=http://127.0.0.1:8686/api/v1
jev-ios mobai-devices
```

Then put the returned device IDs in a pool:

```json
{
  "schema": "jev-ios/pool/v1",
  "devices": [
    {"name": "local-sim", "udid": "11111111-1111-1111-1111-111111111111"},
    {"name": "mobai-phone", "transport": "mobai", "udid": "<mobai-device-id>"},
    {
      "name": "cloud-iphone",
      "transport": "mobai",
      "udid": "<cloud-device-id>",
      "mobai_url": "https://your-mobai-host/api/v1",
      "mobai_app": "<provider-app-ref>"
    }
  ]
}
```

Jev talks directly to MobAI's HTTP/DSL surface. MobAI MCP is optional and useful when the coding agent itself wants interactive device tools. It is not required in the Jev runtime.

The split is deliberate:

| Jev owns | MobAI owns |
| --- | --- |
| Dynamic next-action decisions | Device discovery and reach |
| Bounded app learning | Exclusive device claims |
| Product scenarios | Compact semantic UI + predicates |
| Change-impact selection | Local, physical, remote and cloud devices |
| Result aggregation | Bridge lifecycle and device execution |
| Dynamic verification | Deterministic `.mob` flows and CI infrastructure |

When Jev discovers a route that becomes stable, promote that route to a deterministic MobAI `.mob` flow instead of paying an inference tax forever. Use Jev again when navigation is uncertain or the product changes.

See [device adapters](docs/device-adapters.md).

## Parallel verification

`shard` runs each selected scenario once on an available device:

```sh
jev-ios matrix \
  --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --mode shard --parallel 8 --budget-usd 1
```

`matrix` runs every selected scenario on every selected device:

```sh
jev-ios matrix \
  --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --mode matrix --parallel 8 --budget-usd 2
```

Keep `fixture_isolation: shared` until accounts/data really are independent per device. Parallel devices do not magically make a shared backend fixture safe.

For dense local Simulator hosts, MobAI's `simslim` can be evaluated as an optional host optimization after qualifying your app. It is not required by Jev.

## Scenario contract

A scenario is product intent plus bounded authority:

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

Jev chooses only from controls the device adapter observed. Before input, the adapter checks fresh state again. A model saying `DONE` never makes a run pass. Verification requires the expected labels in fresh device evidence.

A passing scenario proves those observed labels for that run. It does not prove backend state, pixels, accessibility quality, or every possible journey. Keep unit, integration, visual and release checks where they belong.

## Results designed for agents

A matrix run writes:

```text
runs/matrix-.../
  summary.json       read this first
  matrix.json        complete machine-readable manifest
  index.html         human overview
  junit.xml
  <cell>/
    scenario.json    frozen intent
    trace.jsonl      detailed evidence
    result.json
    report.html
```

Verify saved evidence without touching a device:

```sh
jev-ios verify --manifest runs/<run>/matrix.json
```

Prepare a deliberate reproduction:

```sh
jev-ios reproduce --manifest runs/<run>/matrix.json --cell <cell-id>
```

Reproduction is dry by default. Add `--execute` only after the agent has classified the failure and restored the fixture. Jev never blindly replays an action whose outcome is uncertain.

## What is implemented

Today the repo includes:

- native iOS Simulator execution through AXe + simctl;
- native MobAI HTTP/DSL transport with device claims and cloud app refs;
- mixed native, SSH and MobAI pools;
- sharded and full device-matrix execution;
- bounded Jev app learning;
- deterministic source-path impact selection;
- frozen scenarios, summaries, JUnit and HTML evidence;
- deliberate reproduction;
- agent-native `SKILL.md` and non-destructive project scaffolding.

MobAI gives the transport access to physical, remote and cloud devices, but those environments still need to be provisioned and qualified for your app. The repository's offline tests are software-contract tests, not claims about live device-farm throughput.

## Development

```sh
python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

Read [AGENTS.md](AGENTS.md) and [architecture](docs/architecture.md) before changing the runtime. Keep live performance measurements separate from mock-backed tests.

## Reference product dissection

For authorized reference-app research, use [`skills/reference-app-dissection/SKILL.md`](skills/reference-app-dissection/SKILL.md). It produces a versioned observable-product profile. That is a separate research workflow, not the normal verification path.

## Credits and license

Inspired by [Browser Use's Jev Ultrafast](https://github.com/browser-use/jev-ultrafast). Daybreak uses UIKit and pinned [Appllama design guidance](https://github.com/Appllama/appllama-skills/tree/dd5caaec3d5d50ad7fc0324da238119c6b7c3707). See [NOTICE.md](NOTICE.md).

[MIT licensed](LICENSE).
