# Jev iOS Ultrafast

Give an iOS Simulator a goal. Jev picks a control from its accessibility tree, and a local Mac runner checks and executes the choice. One model request per decision, with no screenshots in the model loop.

[Watch the comparison](https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html) · [Try it](#try-it-on-your-mac) · [Use your app](#run-another-app) · [Call from Brigade](#extend-or-call-from-brigade) · [MIT license](LICENSE)

<a href="https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html"><img src="docs/media/comparison-preview.gif" alt="Jev and GPT-5.4 Nano planning the same Lisbon trip in an iOS Simulator at normal speed" width="100%" /></a>

Jev on the left and GPT-5.4 Nano on the right, playing at 1×. The two recordings start at the same point in each run; the attempts ran sequentially on one simulator. [Open the replay](https://clueless-creations.github.io/jev-ios-ultrafast/media/comparison.html) to choose any pair, scrub both recordings, and inspect the results. A [still preview](docs/media/comparison-poster.png) is also available.

## Compare Jev and GPT-5.4 Nano

> Plan a slow Saturday in Lisbon. Choose Design & coffee, walk, start at 10:00, and save the itinerary.

Both engines get the same accessibility state, offered controls, and goal. Both use the same executor and must pass the same local label checks. The runner resets Daybreak before each attempt and alternates which engine goes first.

| Recorded September 19, 2026 | Jev | GPT-5.4 Nano |
| --- | ---: | ---: |
| Task time in the sole pair where both passed | 14.65 s | 25.64 s |
| Actions in that pair | 7 | 7 |
| Verified attempts across all six pairs | 5 / 6 | 2 / 6 |
| Median response time, usable responses only | 242 ms | 922 ms |

The baseline took 1.75× as long in that one pair. Four baseline attempts hit HTTP 429; one Jev attempt ended in a connection failure or timeout. Those failures limit what this small test says about speed and reliability. All 12 attempts remain in the report, including failures.

[All results and measurement limits](docs/comparison.md#recorded-results--september-19-2026) · [Machine-readable results](docs/media/comparison.json) · [Single-run replay with decisions](https://clueless-creations.github.io/jev-ios-ultrafast/media/showcase.html)

## What you can run

This repo includes the Python CLI, the native Daybreak fixture, portable JSON scenarios, and a Node wrapper for calling the runner from Brigade. It uses [TypeSafe's Jev](https://docs.typesafe.ai/introduction) through Vercel AI Gateway and [AXe](https://github.com/cameroncooke/AXe) for simulator input. The Python package has no runtime dependencies and needs no web deployment.

The model chooses among observed target IDs. The runner resolves coordinates locally, checks the screen again before input, and verifies the expected labels afterward. Recordings, per-call timings, and execution receipts go into a local HTML report. [Read the loop](jev_ios/runner.py) or the [architecture](docs/architecture.md).

## Try it on your Mac

You need macOS, Xcode with an iOS Simulator runtime, Python 3.11+, and an installed AXe binary. An AXe binary bundled with XcodeBuildMCP is detected automatically; set `JEV_IOS_AXE` to select another installation. The bundled app's build script targets Apple Silicon.

Clone the repo and install the CLI:

```sh
git clone https://github.com/Clueless-Creations/jev-ios-ultrafast.git
cd jev-ios-ultrafast
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
jev-ios doctor
```

Use `jev-ios devices` to find a simulator, then set `SIMULATOR_UDID` to its UUID. Open that device in Simulator (Device Hub in newer Xcode) to watch the run. Boot the device if needed, then build and launch Daybreak:

```sh
./scripts/build-demo.sh
xcrun simctl install "$SIMULATOR_UDID" runs/JevDemo.app
xcrun simctl launch --terminate-running-process "$SIMULATOR_UDID" org.example.jevsimdemo

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

Daybreak contains local fixture data. The final labels identify both the saved trip and the selected preferences.

Open `runs/daybreak.html` to review the run and its recording. The trace records observations, choices, model timings, execution receipts, and the final label check. Artifact paths are used once; choose new filenames for the next run. Restart Daybreak with the launch command above to return to its home screen.

Authentication accepts `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN` in the process environment. With either set, omit `--vercel-project`. That option instead obtains a temporary development token through an existing Vercel CLI login and project. Tokens stay in memory. See [Vercel's authentication docs](https://vercel.com/docs/ai-gateway/authentication-and-byok/oidc).

Before inference, the CLI reads provider pricing and checks a conservative estimate against `--budget-usd` (default $0.10 for a single run, $1 for a comparison cohort). This admission check is separate from a provider billing cap. Jev uses the [evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation), with no automatic model retries. Published run results and their limits belong in [verification](docs/verification.md).

## Run the comparison yourself

After the setup above, use the same scenario with both engines:

```sh
jev-ios compare \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" --bundle-id org.example.jevsimdemo \
  --start-label Daybreak --start-label Lisbon --start-label Kyoto \
  --pairs 3 --budget-usd 1 \
  --vercel-project YOUR_EXISTING_VERCEL_PROJECT \
  --output-dir runs/comparison-01
```

Open `runs/comparison-01/comparison.html` for synchronized normal-speed replays, every attempt, completion rates, task time, model latency, and estimated cost. The command restarts the app process before each attempt and checks the starting screen. Another app may need a fixture-data reset as well.

The baseline is GPT-5.4 Nano with reasoning disabled and a strict JSON action schema. `--baseline-model` accepts another compatible model; its settings and results belong in a separate comparison. Read the [comparison protocol](docs/comparison.md) before changing models or apps.

## Run another app

Inspect the app to find its exact accessibility labels:

```sh
jev-ios inspect \
  --udid "$SIMULATOR_UDID" --bundle-id com.example.app --launch

jev-ios run \
  --udid "$SIMULATOR_UDID" --bundle-id com.example.app \
  --goal 'Open the settings screen' \
  --expect-label 'Settings' --expect-label 'Notifications' \
  --allow-label 'Settings' --max-steps 6 \
  --trace runs/settings.jsonl --report runs/settings.html
```

Repeat `--expect-label` to require several labels. Choose labels that distinguish the destination from the starting screen. Repeat `--allow-label` to restrict taps; scrolling requires `--allow-scroll`. The app must already be in the foreground unless `--launch` is supplied.

Typing is optional. Supply exact values with `--text KEY=VALUE`; the model selects a key, and the device enters its value only into an empty field whose focus can be verified. The current AXe adapter supports printable US ASCII and excludes secure fields. Use fixture values, since observations and traces can contain app data.

## Extend or call from Brigade

[Scenarios](docs/scenarios.md) hold goals, expected labels, and run constraints in portable JSON. Python protocols separate the model, device, and runner so another adapter can supply the same contracts. See [architecture](docs/architecture.md) for the decision loop and extension points.

The [Node wrapper](examples/brigade-call.mjs) lets a Brigade host invoke the local CLI today. It returns the final run result and rejects failed or interrupted runs. It does not register a native Brigade operation. [Integration notes](docs/brigade-integration.md) describe that boundary and the remaining work.

## Evidence and limits

A `verified` result means every required exact label appeared in a fresh accessibility observation of the selected app. Jev's `DONE` response cannot pass the run by itself. Labels provide a useful check for navigation; backend effects, visual quality, and full product acceptance need their own verification.

The runner checks the app process and screen before input, resolves target coordinates locally, and stops after an uncertain device result. It rejects unsupported modal states and discards stale decisions. These checks reduce races; they do not make observation and input an atomic OS transaction. Keep the simulator dedicated to the run.

Apps need usable accessibility controls. Canvas-only interfaces, missing Flutter semantics, arbitrary keyboard widgets, and custom overlays without useful accessibility state can prevent operation or reliable verification. The supported surface depends on the device adapter and the app, so test a small fixture flow before widening a scenario.

Raw traces, screenshots, and recordings belong in ignored `runs/`. A model-selected action carries no permission to purchase, send messages, or change production data.

## Contribute

Fork the repo, create a branch, and open a pull request. Scenario examples, model and device adapters, and reproducible bug reports are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and evidence to include. Maintainers review changes before merging.

Run the checks locally:

```sh
python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

Tests run without inference or simulator input.

## Credits and license

Inspired by [Browser Use's Jev Ultrafast](https://github.com/browser-use/jev-ultrafast). Daybreak uses UIKit and applies the native controls, typography, navigation, and simulator review guidance in [Appllama's design skill](https://github.com/Appllama/appllama-skills/tree/dd5caaec3d5d50ad7fc0324da238119c6b7c3707). Source and design provenance are in [NOTICE.md](NOTICE.md).

[MIT licensed](LICENSE). You can use, modify, and distribute the code under its terms.
