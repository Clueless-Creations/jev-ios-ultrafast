# Architecture

The Mac owns observation and input. Jev evaluates a compact accessibility snapshot and returns choices from the action space offered for that snapshot. The runner validates those choices, executes one operation, and obtains fresh evidence.

```mermaid
flowchart LR
    App[iOS Simulator] --> Observe[Local accessibility snapshot]
    Observe --> Questions[Permitted actions and indexed targets]
    Questions --> Model[Jev evaluation or baseline JSON request]
    Model --> Validate[Validate selected answers]
    Validate --> Execute[Freshness check and local input]
    Execute --> App
    Observe --> Verify[Exact expected-label check]
    Verify --> Result[Run result and artifacts]
```

## One request, several possible decisions

The model request uses `typesafe-ai/jev` at Vercel's `/v1/evaluate` endpoint. Its state contains the goal, expected labels, compact current controls, and recent actions. Jev accepts text and JSON; it does not consume the screenshot.

One choice question selects an operation. Separate questions speculate about the target for each supported operation. Only the selected operation's target answer can affect execution. For typing, each candidate field also gets a choice among exact caller-supplied strings. After selecting a field, the runner uses only that field's value answer.

For example, an operation answer of `TAP` can select observed target `4`. Unused text-field answers have no effect. A `TYPE_TEXT` answer instead selects an observed empty field and a caller-supplied text key. The device resolves the key locally and enters the exact value; neither model generates text to enter into the app.

The model adapter checks choice IDs, complete probability maps, finite values, and probability consistency. It uses one persistent HTTPS client with request, response, timeout, and call limits. Failed attempts consume the call budget. It never automatically retries a request.

## Baseline and matched comparisons

`ChatCompletionModel` sends the same state and offered choices to Vercel's chat-completions endpoint. GPT-5.4 Nano is the default baseline, with reasoning disabled, temperature zero, and a strict JSON schema. The adapter independently rejects unknown operations, target IDs, text keys, truncation, refusals, and incompatible field combinations. Its response carries no calibrated confidence; the runner permits that explicit absence only with a zero confidence threshold.

The comparison harness uses zero confidence threshold for both engines. Both retain all target, freshness, and completion checks. It alternates engine order, restarts the app for every attempt, records a semantic starting-state fingerprint, and retains failed attempts. Paired ratios require verified outcomes and identical starting fingerprints across the cohort. Request latency, task time, setup time, and estimated token cost remain separate measurements. See the [comparison protocol](comparison.md).

## Observation and execution

The AXe adapter binds the simulator and app process. It normalizes accessible controls, filters unsupported state, and keeps coordinates in the local device layer. The model sees IDs, types, labels, values, and enabled state. Fields identified as secure are redacted before export; ordinary app labels and values may still contain private data.

Before dispatch, the adapter observes again and compares the screen fingerprint. A changed screen makes the decision stale; the runner discards it and asks again within the remaining budget. Coordinates come from the freshly observed target. The adapter consumes a dispatched observation so the same observation cannot replay input.

The runner stops when an action's outcome becomes uncertain. For typing, the adapter taps the chosen field, verifies its identity and focus, then sends the exact text through stdin. If focus cannot be established, it enters no text and returns uncertainty about the preceding tap.

Observation and input are separate OS calls. PID binding and fingerprints reduce races but cannot eliminate them. Accessibility metadata also cannot prove the absence of every custom overlay. Supported apps must expose enough state for both operation and verification.

## Completion and evidence

Expected labels are exact strings defined by the caller or scenario. The runner checks them before making a model request and after the final bounded action. A model `DONE` answer triggers a fresh local check; absent labels produce an unverified result.

`verified` therefore means the required labels were observed in the selected app. The label set must distinguish the intended destination. Use separate checks for server-side effects, visual quality, accessibility quality, and release acceptance.

NDJSON events record observations, model decisions, execution receipts, and the final result. The local HTML report presents those events for review. Screenshots and recordings are optional separate evidence and never substitute for the runtime's label check.

## Extension points

| Component | What an extension supplies |
| --- | --- |
| Scenario | Goal, expected labels, permitted actions, and run limits |
| Model adapter | Decisions over the offered operation and target maps |
| Device adapter | Current snapshots, validated input, and execution receipts |
| Host | Target selection, credentials, scheduling, artifacts, and authority |

The Python interfaces live in `jev_ios/protocols.py`. The validated scenario loader defines the accepted JSON shape. Use these source contracts when adding adapters; the architecture document does not introduce another runtime or competing schema.

A new device adapter must preserve target identity and freshness semantics. A new model adapter must return only offered operations, targets, and text keys, with finite probabilities or an explicit `confidence_kind: "not_reported"` and null probability. Missing confidence cannot pass a positive confidence threshold. Keep the runner's deterministic checks even when a provider promises structured output. The current Node wrapper integrates at the host layer; native Brigade provider registration remains separate work.

## Parallel host and device sessions

The suite scheduler is a host-layer extension around the existing runner, not a new scenario language or a second agent. `suite.py` validates case metadata and pools; `parallel_cli.py` exposes plan/matrix/verify/reproduce; `matrix.py` schedules one exclusive lane per device and preserves the original runner's independent checks.

`shard` consumes a shared case queue; `matrix` schedules the explicit case/device product. All model clients stay on the coordinator behind one request-rate/concurrency gate. Whole-plan pricing admission occurs before sessions open. Every attempted case uses a fresh bounded model client and records its frozen scenario and independent evidence.

`NativeSession` owns a cross-process device lease and explicit app relaunch. `RemoteSession` carries device-only RPC over authenticated SSH to the same native session on a Mac. Remote workers do not receive gateway keys or execute model-generated shell commands. A broken or uncertain lane is not reused. Leases are released only after bounded in-flight commands settle.

Fixture state is separate from process state. The shared-fixture default serializes cases; per-device parallelism requires explicitly independent fixture data. Coordinator resource locks are not a distributed backend lock service. Keep other automation and manual interaction away from test devices while a lane owns them.

Plans record selection reasons and source/build provenance. Unknown source changes select the full suite. Missing, skipped, or interrupted cells cannot become passing evidence. A final report groups failure symptoms without asserting root causes. Reproduction is an explicitly authorized new scenario run, not recorded action replay.

Semantic learning now requires a caller-approved navigation allow-list. Without it, learning observes only. App-map v2 semantic IDs support orientation across sampled screens but are never reusable runtime target IDs. Neither map generation nor source-path selection changes the product's acceptance criteria. Cross-device decision caching, vendor provisioning and MobAI execution are not implemented.

See [parallel testing](parallel-testing.md) for the executable schemas, result contracts, operational limits, and qualification steps.

## Design provenance

Daybreak is a UIKit fixture. Its design work applies [Appllama's app-design skill at the pinned revision](https://github.com/Appllama/appllama-skills/blob/dd5caaec3d5d50ad7fc0324da238119c6b7c3707/skills/appllama-app-design-skill/SKILL.md), including native controls, platform typography, a consistent accent, navigation semantics, and simulator review. The skill allows its default Expo stack to be overridden when the project already uses another stack.

The Appllama MCP was unavailable during this implementation, so use of the skill does not imply access to its design library or completion of an MCP research pass. The app's name, interface, and code are original to this fixture. No Appllama branding or library assets are bundled. [NOTICE.md](../NOTICE.md) records the source revisions and licenses.
