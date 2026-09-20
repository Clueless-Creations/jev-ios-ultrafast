# Jev iOS Ultrafast

Fast, accessibility-native AI control for iOS Simulator.

Give the runner a goal. Jev reads the app's accessibility tree, chooses an observed control, and a local Mac runner validates and executes the action. No screenshots in the model loop. One model request per decision.

[Agent skill](SKILL.md) · [Watch the demo](https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html) · [Quick start](#quick-start) · [Run your app](#run-your-app) · [Add it to your coding agent](docs/agent-integration.md) · [Architecture](docs/architecture.md) · [MIT](LICENSE)

### Install

```sh
curl -fsSL https://raw.githubusercontent.com/Clueless-Creations/jev-ios-ultrafast/main/scripts/install.sh | sh
jev-ios doctor
```

Then, from your iOS app repository:

```sh
jev-ios init --bundle-id com.yourcompany.yourapp
```

That creates `.jev-ios/smoke.json`, a runnable smoke-test script, and a short instruction file for coding agents. Inspect your app once, replace the placeholder goal and success label, and your agent has a repeatable simulator verification loop.

<a href="https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html"><img src="docs/media/comparison-preview.gif" alt="Jev controlling an iOS Simulator at normal speed" width="100%" /></a>

## Why this exists

AI coding agents can write an iOS feature quickly. Closing the loop on the running app is slower.

Jev iOS Ultrafast gives agents a small, deterministic interface for interacting with an iOS Simulator:

```text
goal
  ↓
accessibility tree
  ↓
Jev chooses a target
  ↓
local validation
  ↓
tap / type / scroll
  ↓
fresh accessibility state
  ↓
verify
```

That makes it useful for agent-driven development, UI smoke tests, release validation, and fast feedback loops where screenshot-heavy computer-use agents are unnecessary.

## What you get

- **Accessibility-first control.** The model reasons over compact semantic state instead of screenshots.
- **Fast decisions.** Jev is designed for small structured decisions inside tight loops.
- **Local execution.** Coordinates, freshness checks, input, and verification stay on the Mac.
- **Portable scenarios.** Goals, expected labels, allowed controls, and limits live in JSON.
- **Run artifacts.** Recordings, traces, timings, receipts, screenshots, and HTML reports are generated locally.
- **Pluggable boundaries.** Model, device, and runner contracts are separated so the system can be embedded in larger agent workflows.
- **A real iOS fixture.** Daybreak is included so the complete loop can be run immediately.

The current device adapter uses [AXe](https://github.com/cameroncooke/AXe). Jev is provided by [TypeSafe](https://docs.typesafe.ai/introduction) through Vercel AI Gateway.

## Example

The included Daybreak scenario asks the agent to configure and save a Lisbon itinerary:

> Plan a slow Saturday in Lisbon. Choose Design & coffee, walk, start at 10:00, and save the itinerary.

The runner observes only the controls exposed by the app, gives Jev their target IDs, validates the selected target against a fresh observation, performs the action, and verifies the final state from accessibility labels.

[Open the synchronized replay](https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html) · [Inspect the decision loop](jev_ios/runner.py)

## Quick start

### Requirements

- Apple Silicon Mac (the bundled Daybreak fixture currently targets arm64)
- Xcode with an iOS Simulator runtime
- Python 3.11+
- AXe

An AXe binary bundled with XcodeBuildMCP is detected automatically. Set `JEV_IOS_AXE` to select another installation.

### Install

```sh
git clone https://github.com/Clueless-Creations/jev-ios-ultrafast.git
cd jev-ios-ultrafast
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
jev-ios doctor
```

Find a simulator and build the included fixture:

```sh
jev-ios devices
export SIMULATOR_UDID="<your simulator UUID>"
xcrun simctl boot "$SIMULATOR_UDID" 2>/dev/null || true
open -a Simulator

./scripts/build-demo.sh
xcrun simctl install "$SIMULATOR_UDID" runs/JevDemo.app
xcrun simctl launch --terminate-running-process "$SIMULATOR_UDID" org.example.jevsimdemo
```

Run it:

```sh
jev-ios run \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" \
  --bundle-id org.example.jevsimdemo \
  --vercel-project YOUR_EXISTING_VERCEL_PROJECT \
  --trace runs/daybreak.jsonl \
  --record-video runs/daybreak.mp4 \
  --screenshot runs/daybreak.png \
  --report runs/daybreak.html
```

Open `runs/daybreak.html` for the recording, decisions, timings, execution receipts, and final verification.

Authentication also accepts `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN`. With either set, omit `--vercel-project`. Tokens stay in memory.

## Run your app

Inspect the foreground app:

```sh
jev-ios inspect \
  --udid "$SIMULATOR_UDID" \
  --bundle-id com.example.app \
  --launch
```

Then give it a goal and define success:

```sh
jev-ios run \
  --udid "$SIMULATOR_UDID" \
  --bundle-id com.example.app \
  --goal 'Open the settings screen' \
  --expect-label 'Settings' \
  --expect-label 'Notifications' \
  --allow-label 'Settings' \
  --max-steps 6 \
  --trace runs/settings.jsonl \
  --report runs/settings.html
```

Repeat `--expect-label` for multiple required labels and `--allow-label` to constrain available taps. Scrolling requires `--allow-scroll`.

Typing values can be supplied explicitly with `--text KEY=VALUE`. The model selects the key and the runner supplies its value to a verified empty field. The current AXe typing adapter accepts printable US ASCII and intentionally excludes secure or already-populated fields.

## Use it in an agent loop

The useful primitive is a fast verification loop that another agent can call after making a change.

A coding or release agent can:

1. build and launch the app,
2. invoke a scenario,
3. let Jev navigate the semantic UI,
4. verify the expected state,
5. inspect the resulting trace or report,
6. continue working from the result.

This keeps high-capability coding agents focused on engineering while delegating routine UI navigation to a smaller decision loop.

[Scenario format](docs/scenarios.md) · [Architecture](docs/architecture.md) · [Brigade integration](docs/brigade-integration.md)

The included Node wrapper at [`examples/brigade-call.mjs`](examples/brigade-call.mjs) demonstrates invoking the CLI from another agent host.

## How verification works

A run succeeds when its required labels appear in a fresh accessibility observation of the selected app. A model saying `DONE` is not sufficient.

Before input, the runner checks the app and current screen again and resolves the selected target locally. The model chooses among observed actions while the executor owns device interaction and verification.

For workflows that need stronger proof, add application-specific verification for backend effects, visual output, or other product acceptance criteria.

## Compare decision engines

The repo includes a reproducible comparison harness:

```sh
jev-ios compare \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" \
  --bundle-id org.example.jevsimdemo \
  --start-label Daybreak \
  --start-label Lisbon \
  --start-label Kyoto \
  --pairs 3 \
  --budget-usd 1 \
  --vercel-project YOUR_EXISTING_VERCEL_PROJECT \
  --output-dir runs/comparison-01
```

Open `runs/comparison-01/comparison.html` for synchronized normal-speed replays and measurements.

The harness can evaluate Jev against other structured decision engines while holding the scenario, observed controls, executor, and verification contract constant.

[Comparison protocol](docs/comparison.md) · [Machine-readable example](docs/media/comparison.json)

## Design principles

**Keep the model's job tiny.** The model chooses from observed controls. Device mechanics stay deterministic.

**Prefer semantic state.** Accessibility trees are compact, structured, and already describe the UI in terms users and assistive technologies can act on.

**Verify after acting.** Execution is not success. The runner observes the app again and checks explicit expectations.

**Make runs inspectable.** Decisions and device actions leave evidence that can be reviewed.

**Compose instead of monolith.** The runner is useful as a CLI, but its contracts are separable so other agents and orchestration systems can call it.

## Repository

```text
jev_ios/        Python runner and adapters
scenarios/      Portable task definitions
examples/       Integration examples
docs/           Architecture, protocols, and evidence
scripts/        Demo build tooling
tests/          Offline test suite
```

## Development

```sh
python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

The test suite runs without model inference or simulator input.

## Contributing

Contributions are welcome, especially additional device and model adapters, reusable scenarios, stronger verification primitives, agent integrations, and reproducible performance work.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Safety and privacy

Accessibility observations and local traces can contain application data. Use fixture data when possible and keep generated artifacts out of source control.

A model-selected action does not grant permission to purchase, send messages, modify production data, or perform other consequential actions. The host remains responsible for defining the allowed action surface.

## Credits

Inspired by [Browser Use's Jev Ultrafast](https://github.com/browser-use/jev-ultrafast).

Daybreak uses UIKit and incorporates native design guidance from [Appllama's design skill](https://github.com/Appllama/appllama-skills/tree/dd5caaec3d5d50ad7fc0324da238119c6b7c3707).

See [NOTICE.md](NOTICE.md) for source and design provenance.

## License

[MIT](LICENSE)
