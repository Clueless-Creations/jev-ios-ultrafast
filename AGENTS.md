# Repository guide

This repository contains a local iOS Simulator runner and the Daybreak fixture app. Read `README.md` and `docs/architecture.md` before extending the runtime. Code and validated scenario schemas define behavior; documentation describes them.

For app usage and scenario authoring, read `SKILL.md`. For parallel work, also read `docs/parallel-testing.md`. For reference-led design research and design-language extraction, read `skills/reference-app-dissection/SKILL.md`. Runtime target IDs are never cross-device selectors.

## Code map

| Path | Responsibility |
| --- | --- |
| `jev_ios/cli.py` | CLI options, credentials, pricing admission, run artifacts |
| `jev_ios/parallel_cli.py`, `jev_ios/suite.py` | Suite/pool validation, impact selection, and parallel commands |
| `jev_ios/matrix.py`, `jev_ios/matrix_report.py` | Device lanes, shared API gates, frozen evidence, and aggregation |
| `jev_ios/lease.py`, `jev_ios/fleet.py`, `jev_ios/remote.py` | Local/SSH device ownership and bounded device-only transport |
| `jev_ios/onboarding.py`, `jev_ios/learning.py` | Non-destructive setup and allow-listed semantic discovery |
| `jev_ios/runner.py` | Bounded decisions, execution, final label verification |
| `jev_ios/model.py` | Vercel evaluation transport and strict choice validation |
| `jev_ios/baseline.py` | Standard model transport and strict JSON action validation |
| `jev_ios/comparison.py` | Matched reset, alternating pairs, timing and cost summaries |
| `jev_ios/comparison_report.py` | Self-contained paired replay and all-attempt results |
| `jev_ios/device.py` | AXe snapshots, app identity, local input and receipts |
| `jev_ios/protocols.py` | Device, model, and snapshot adapter interfaces |
| `jev_ios/scenario.py` | Portable scenario validation and defaults |
| `jev_ios/report.py` | Local HTML artifact from recorded run events |
| `scenarios/` | Portable goals and expected outcomes |
| `examples/brigade-call.mjs` | Local host subprocess integration |
| `demo/`, `scripts/build-demo.sh` | Native fixture app and local build |
| `tests/` | Offline regression tests |
| `skills/reference-app-dissection/` | Evidence-backed reference app study and reusable design-grammar handoff |

Keep provider transport, device execution, and run policy separate. New adapters must preserve observed target identity, decision freshness, bounded calls, and uncertain-action handling. Model output must never become a shell command or unobserved coordinate.

Raw traces, screenshots, recordings, and build output stay under ignored `runs/`. Do not commit tokens or machine-specific settings. Review any curated media for private app data before adding it to documentation.

Use the fixture app or another explicitly authorized test target. Untrusted model intent does not authorize real purchases, messages, or production mutations. Do not replay an action whose outcome is uncertain.

## Local verification

```sh
python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

Keep automated tests offline. Use live inference only for an authorized bounded run after the pricing check. Record the exact scenario, target, source revision, and measurement boundaries with reported results. A label check is evidence of those labels; it does not establish backend success or design acceptance. Do not add hosted GitHub Actions workflows.

For Daybreak UI changes, apply the pinned Appllama guidance in `NOTICE.md` using the existing UIKit stack. Inspect the running app and record the full flow before claiming visual or motion quality. Do not claim performance measurements that were not collected.


## Reference app studies

Keep design-study evidence separate from Jev runtime evidence. Jev semantic maps can orient the agent but do not establish visual, motion, gesture, haptic, audio, accessibility, or product-design claims. When a task asks to study a reference app, route to `skills/reference-app-dissection/SKILL.md`; preserve explicit unknowns and source/target separation.
