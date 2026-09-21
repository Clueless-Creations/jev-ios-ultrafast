# Agent setup

This is the shortest path from “here is my app” to repeatable Jev verification.

The intended user experience is that a person points a shell-capable coding agent at this repository. The agent reads `SKILL.md`, uses the app's existing build workflow, scaffolds Jev non-destructively, learns only what it needs, and verifies its own user-facing work.

## Prompt to give an agent

> Use https://github.com/Clueless-Creations/jev-ios-ultrafast for mobile UI verification in this repo. Read its SKILL.md first. Do not replace our build/test workflow. Set Jev up non-destructively, inspect the installed app before writing scenarios, use bounded Jev learning only where useful, and run the smallest relevant verification after user-facing changes. Prefer MobAI if it is already configured or if multiple/physical/remote/cloud devices are useful. Keep product acceptance criteria independent of Jev.

That is enough. The rest of this document explains what the agent should do.

## 1. Understand the host app

Read the host repo's `AGENTS.md`, `CLAUDE.md`, build scripts, existing tests and product requirements.

Resolve:

- bundle/application ID;
- how the app is built;
- how it is installed on a test device;
- what fixture/test mode already exists;
- what user outcome the current task changes.

Do not invent a new build system or fixture mechanism just for Jev.

## 2. Check Jev and devices

```sh
jev-ios doctor
```

If MobAI is available:

```sh
jev-ios mobai-devices
```

Prefer MobAI for fleets, physical devices, remote hosts and cloud farms. For the smallest local iOS setup, use:

```sh
jev-ios devices
```

Native execution requires Xcode/Simulator and AXe. XcodeBuildMCP is not required.

## 3. Scaffold once

From the host app repository:

```sh
jev-ios init --bundle-id com.example.app
```

Init creates `.jev-ios/AGENT.md`, `.jev-ios/SKILL.md`, a starter scenario/suite and a wrapper. It preserves existing agent files and refuses to overwrite edited generated files.

Add this pointer to the host repo's existing agent guide:

> For user-facing mobile work, read `.jev-ios/AGENT.md` and `.jev-ios/SKILL.md` and run the relevant Jev verification before declaring the change complete.

## 4. Observe before writing assertions

For native Simulator:

```sh
jev-ios inspect --udid "$SIMULATOR_UDID" --bundle-id com.example.app --launch
```

Do not derive accessibility labels from Swift symbol names, screenshots or guesses.

If the relevant area is unfamiliar, inspect the first screen, approve only safe navigation labels, and use bounded learning:

```sh
jev-ios learn \
  --udid "$SIMULATOR_UDID" --bundle-id com.example.app \
  --allow-label Settings --allow-label Notifications --allow-label Back \
  --max-steps 8 --budget-usd 0.10 \
  --output .jev-ios/app-map-settings.json
```

The app map saves the expensive coding agent from manually exploring routine navigation. It does not define requirements.

## 5. Encode the product contract

A good scenario says “reach notification controls and observe these labels,” not “tap at X/Y” and not “tap Settings, then row 3.”

Use exact observed final labels, bounded allowed controls and explicit fixture text. Keep the scenario short.

Also set suite `start_labels` to labels that establish the prepared initial state after relaunch.

## 6. Run the smallest relevant scope

Single local smoke:

```sh
.jev-ios/run-smoke.sh
```

Affected tests:

```sh
jev-ios plan --suite .jev-ios/suite.json --pool .jev-ios/pool.json --changed-since main
jev-ios matrix --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --changed-since main --mode shard --parallel 4 --budget-usd 1
```

Full device coverage:

```sh
jev-ios matrix --suite .jev-ios/suite.json --pool .jev-ios/pool.json \
  --mode matrix --parallel 8 --budget-usd 2
```

Use `matrix` only when every scenario/device pair is intentionally part of the requested coverage.

## 7. Let MobAI do the infrastructure work

A MobAI worker in a pool is simply:

```json
{"name":"device-a","transport":"mobai","udid":"<mobai-device-id>"}
```

For a provider-backed device:

```json
{
  "name":"cloud-iphone",
  "transport":"mobai",
  "udid":"<cloud-device-id>",
  "mobai_url":"https://host.example/api/v1",
  "mobai_app":"<provider-app-ref>"
}
```

Keep `MOBAI_TOKEN` in the environment.

The Jev runtime calls MobAI HTTP/DSL directly. Install/use MobAI MCP separately only when the coding agent wants interactive MobAI tooling.

If Jev repeatedly follows the same stable route, move that route into a deterministic MobAI `.mob` flow. Jev is most valuable where a decision is actually needed.

## 8. Consume evidence like an agent

Read `summary.json` first. Do not pour every trace into model context.

A matrix exit code of 0 means every selected cell has the expected semantic label evidence. It does not mean the backend mutation happened or the pixels are correct.

On failure, classify before changing anything:

1. product bug;
2. bad scenario intent;
3. accessibility gap;
4. fixture/start-state issue;
5. device/MobAI transport;
6. model/provider;
7. wrong verification tool.

Then inspect only the relevant cell evidence.

## 9. Reproduce deliberately

```sh
jev-ios reproduce --manifest runs/<run>/matrix.json --cell <cell-id>
```

This is dry by default. It shows the frozen intent. Restore the fixture and use `--execute` only when a fresh rerun is appropriate. Never blindly replay an uncertain action.

## Definition of done for the agent

For a user-facing app change, the agent should be able to report:

- what scenario(s) represented the requested behavior;
- what device(s) were exercised;
- whether all selected semantic checks verified;
- any unresolved product, fixture, accessibility, device or provider issue;
- what was **not** proven by Jev.

That is the contract. The person using the agent should not need to understand Jev internals to get useful verification.
