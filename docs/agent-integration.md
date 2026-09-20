# Use Jev iOS Ultrafast from a coding agent

Jev iOS Ultrafast is intended to be a small tool inside a larger coding or release loop. The coding agent owns the code. Jev owns routine simulator navigation. The runner verifies the resulting UI state.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/Clueless-Creations/jev-ios-ultrafast/main/scripts/install.sh | sh
```

Or clone the repository and run `python -m pip install -e .`.

Run:

```sh
jev-ios doctor
jev-ios devices
```

## Give this to your agent

Add a scenario to your repository, for example `scenarios/release-smoke.json`:

```json
{
  "name": "Release smoke",
  "goal": "Open Settings and verify Notifications is available.",
  "expect_labels": ["Settings", "Notifications"],
  "allow_labels": ["Settings"],
  "max_steps": 6,
  "min_probability": 0.55,
  "allow_scroll": false,
  "text_values": {}
}
```

Then give your coding agent this instruction:

> After changing user-facing iOS behavior, build and launch the app in iOS Simulator. Run the relevant `jev-ios` scenario. Treat exit code 0 as verified. If it exits nonzero, inspect the JSON output and HTML report before changing code. Do not weaken the scenario merely to make it pass.

Example:

```sh
jev-ios run \
  --scenario scenarios/release-smoke.json \
  --udid "$SIMULATOR_UDID" \
  --bundle-id com.example.app \
  --launch \
  --trace runs/release-smoke.jsonl \
  --report runs/release-smoke.html
```

The CLI returns 0 only when the expected labels are verified after the run. That makes it usable from shell scripts, coding agents, and CI-style orchestration without parsing prose.

## Where it fits

Use Jev for flows such as:

- navigate to a screen after an implementation change;
- exercise a short onboarding or settings path;
- reproduce a UI path before and after a fix;
- run release smoke flows repeatedly;
- let an agent verify its own UI work without spending the coding model on every tap.

Keep ordinary unit and integration tests. Jev is complementary: it covers the semantic interaction loop between "the app built" and "the expected UI state is actually reachable."

## App requirements

The app needs useful accessibility semantics. Standard UIKit and SwiftUI controls generally provide a good starting point. Custom controls should expose meaningful labels and actions.

Start with one short, deterministic flow. Inspect the app first:

```sh
jev-ios inspect --udid "$SIMULATOR_UDID" --bundle-id com.example.app --launch
```

Use the exact labels returned there to define the scenario.

## Credentials

Set either `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN`. An existing Vercel project can instead be supplied with `--vercel-project`.

## Artifacts

For agent workflows, keep a trace and report:

```sh
--trace runs/smoke.jsonl --report runs/smoke.html
```

The trace is machine-readable. The HTML report is for humans. Add `--record-video runs/smoke.mp4` when a replay is useful.

Generated `runs/` artifacts should remain outside source control.
