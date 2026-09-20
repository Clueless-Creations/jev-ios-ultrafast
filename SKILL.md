---
name: jev-ios
description: Use Jev iOS Ultrafast to map an iOS user flow into a bounded simulator scenario, run it, and interpret verification evidence. Use after user-facing iOS changes, for smoke/release flows, or when an agent needs to navigate an app without spending its own reasoning loop on every UI action.
---

# Jev iOS

Jev is the simulator interaction worker underneath the coding agent. Keep ownership clear:

- **You own intent:** what user behavior should work and what observable state proves it.
- **Jev owns navigation:** choosing among controls actually exposed by the app.
- **The local runner owns execution:** taps, typing, scrolling, freshness checks, and final label verification.
- **Do not use Jev as a substitute for unit/integration tests or backend assertions.**

## Start here

If this app has no `.jev-ios/` directory:

```sh
jev-ios init --bundle-id <bundle-id>
```

Then inspect the app:

```sh
jev-ios inspect --udid "$SIMULATOR_UDID" --bundle-id <bundle-id> --launch
```

Use the observation to create or refine `.jev-ios/smoke.json`.

## Turn product intent into a scenario

Do not translate an implementation plan directly into taps. Start from a user-observable contract.

Given a request such as:

> Make sure a user can open notification settings and see the push-notification option.

Map it as:

1. **Goal:** describe the user outcome, not coordinates or a brittle tap script.
2. **Expected labels:** choose exact labels that are visible only when the intended destination/state has been reached.
3. **Allowed labels:** constrain taps when the flow should stay narrow. Leave empty only when broad navigation is intentional.
4. **Scrolling:** enable only when the flow requires it.
5. **Text:** provide fixture values explicitly. Never ask the model to invent sensitive or production data.
6. **Step budget:** choose the smallest reasonable bound with a little recovery room.
7. **Confidence:** keep the default unless there is measured reason to change it.

Example:

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

## Inspect before guessing

Accessibility labels are the contract with the device adapter. Never invent labels from screenshots, source names, or assumptions when the running app can be inspected.

If the desired control is missing from `jev-ios inspect`, first determine whether:

- the app is on the wrong screen,
- the control needs scrolling,
- the UI lacks usable accessibility semantics,
- a modal or overlay is blocking the expected surface.

Fix app semantics when appropriate. Do not weaken verification to accommodate an inaccessible UI.

## Decide what belongs in Jev

Good Jev scenarios are short semantic flows:

- reach a newly implemented screen;
- exercise onboarding/settings/navigation;
- reproduce a UI path around a bug fix;
- verify a release-critical destination is reachable;
- fill deterministic fixture data and verify the resulting UI state.

Keep these elsewhere:

- pure logic → unit tests;
- service/database behavior → integration tests;
- exact pixels/visual regressions → visual tooling;
- backend side effects → backend/API assertions;
- destructive or production actions → do not delegate to this runner.

## Run

Prefer the generated wrapper:

```sh
.jev-ios/run-smoke.sh
```

For a targeted scenario:

```sh
jev-ios run \
  --scenario .jev-ios/smoke.json \
  --udid "$SIMULATOR_UDID" \
  --bundle-id <bundle-id> \
  --launch \
  --trace runs/jev-smoke.jsonl \
  --report runs/jev-smoke.html
```

Exit code 0 means the runner observed all required labels after execution. It does not prove unobserved backend effects.

## Interpret a nonzero result

Do not immediately rewrite code and do not immediately loosen the scenario.

1. Read the terminal JSON event.
2. Inspect `runs/jev-smoke.jsonl` for observations, choices, and execution receipts.
3. Open `runs/jev-smoke.html` when a human-readable replay helps.
4. Classify the problem:
   - product behavior is wrong;
   - scenario intent/labels are wrong;
   - accessibility semantics are insufficient;
   - simulator/device state is wrong;
   - provider/model call failed.
5. Fix the responsible layer.
6. Re-run from a known app state.

A scenario should change because the intended product contract changed or because it encoded that contract incorrectly, never merely because a run failed.

## Python architecture

When extending the tool rather than merely using it, route changes to the narrowest layer:

| Need | Python surface |
| --- | --- |
| CLI command/options, artifacts, credentials | `jev_ios/cli.py` |
| Scenario schema/defaults/validation | `jev_ios/scenario.py` |
| Decision/execution/verification loop | `jev_ios/runner.py` |
| Simulator observation/input | `jev_ios/device.py` |
| Jev provider transport/choice validation | `jev_ios/model.py` |
| Adapter interfaces | `jev_ios/protocols.py` |
| HTML run evidence | `jev_ios/report.py` |
| First-run project scaffold | `jev_ios/onboarding.py` |

Preserve these invariants:

- model output never becomes a shell command or arbitrary coordinate;
- Jev chooses only among observed targets;
- refresh state before executing a decision;
- uncertain execution is not replayed;
- model calls and steps remain bounded;
- final success comes from fresh device observation, not the model saying it is done;
- scenario files contain product intent and constraints, not provider credentials or host configuration.

Read `docs/architecture.md` before changing these boundaries.

## Typing

The current AXe adapter accepts printable US ASCII into verified empty, non-secure fields. Use fixture values. If a requested flow requires unsupported typing, report that boundary rather than silently changing the scenario.

## Before declaring success

For changes to Jev itself, run:

```sh
python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

For changes to an app using Jev, report:

- scenario used;
- app/bundle target;
- whether Jev verified the expected labels;
- any evidence artifact needed to understand the result.

Keep the result concise. The coding agent should consume the verification outcome, not drag the entire simulator transcript into its context.
