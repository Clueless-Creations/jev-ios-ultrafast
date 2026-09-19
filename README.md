# Jev iOS Ultrafast

Give an iOS Simulator a goal. Jev chooses an action and a control from the current accessibility tree; a local Mac runner checks and executes the choice. Each decision takes one model request. Screenshots stay outside the model loop.

Inspired by [Browser Use's Jev Ultrafast](https://github.com/browser-use/jev-ultrafast), this standalone Python package includes a native trip-planning app, reusable scenarios, NDJSON traces, and a local HTML run report. It uses Vercel AI Gateway for Jev and [AXe](https://github.com/cameroncooke/AXe) for simulator input. The runner has no Python runtime dependencies and needs no web deployment.

## Compare with a standard model

The same runner can use GPT-5.4 Nano to generate a validated JSON action instead of Jev's choice evaluation. Both receive the same accessibility state and offered controls, execute through the same device adapter, and must pass the same local checks. Run a fixed, alternating three-pair comparison with recordings:

```sh
jev-ios compare \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" --bundle-id org.example.jevsimdemo \
  --start-label Daybreak --start-label Lisbon --start-label Kyoto \
  --pairs 3 --budget-usd 1 \
  --vercel-project YOUR_EXISTING_VERCEL_PROJECT \
  --output-dir runs/comparison-01
```

Open `runs/comparison-01/comparison.html` for synchronized normal-speed replays, every attempt, completion rates, task time, model latency, and estimated cost. The command resets the app process before each attempt and checks the starting screen. An arbitrary app may need its own fixture-data reset. Read the [comparison protocol](docs/comparison.md) before comparing another app.

**Recorded comparison:** Jev passed 5/6 attempts; GPT-5.4 Nano passed 2/6. The sole pair where both passed took **14.65 s versus 25.64 s** (1.75×). Four baseline attempts hit HTTP 429; one Jev attempt timed out. This is one local fixture, with one mutually successful pair—not a general speed claim. [Open the paired replay](docs/media/comparison.html) · [All results and measurement limits](docs/comparison.md#recorded-results--september-19-2026).

## Watch it run

**Seven native actions in 16.61 seconds. Median Jev response: 224 ms.** One recorded run on iOS 26.2 Simulator, including observation, input, and final verification. Model response time is only part of the total.

[Normal-speed video](docs/media/showcase.mp4) · [Downloadable interactive report](docs/media/showcase.html) · [Measurements and limits](docs/verification.md)

The report embeds the video, with clickable decisions and per-call timings. Download it and open it locally. The goal names the desired trip; it contains no sequence of target IDs or hardcoded tap coordinates.

## Run the showcase

You need macOS, Xcode with an iOS Simulator runtime, Python 3.11+, and an installed AXe binary. An AXe binary bundled with XcodeBuildMCP is detected automatically; set `JEV_IOS_AXE` to select another installation. The bundled app's build script targets Apple Silicon.

From this checkout:

```sh
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

The scenario asks Jev to plan a slow Saturday in Lisbon, choose Design & coffee, walk, start at 10:00, and save the itinerary. Daybreak contains local fixture data. The final labels identify both the saved trip and the selected preferences.

Open `runs/daybreak.html` to review the run and its recording. The trace records observations, choices, model timings, execution receipts, and the final label check. Artifact paths are used once; choose new filenames for the next run. Restart Daybreak with the launch command above to return to its home screen.

Authentication accepts `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN` in the process environment. With either set, omit `--vercel-project`. That option instead obtains a temporary development token through an existing Vercel CLI login and project. Tokens stay in memory. See [Vercel's authentication docs](https://vercel.com/docs/ai-gateway/authentication-and-byok/oidc).

Before inference, the CLI reads provider pricing and checks a conservative estimate against `--budget-usd` (default $0.10 for a single run, $1 for a comparison cohort). This admission check is separate from a provider billing cap. Jev uses the [evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation), with no automatic model retries. Published run results and their limits belong in [verification](docs/verification.md).

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

## Development

```sh
python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

Tests run locally without inference or simulator input. Daybreak uses UIKit and applies the native controls, typography, navigation, and simulator review guidance in [Appllama's design skill](https://github.com/Appllama/appllama-skills/tree/dd5caaec3d5d50ad7fc0324da238119c6b7c3707). Source and design provenance are in [NOTICE.md](NOTICE.md).
