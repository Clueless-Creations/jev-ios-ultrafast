# Recorded verification · September 19, 2026

The final Daybreak showcase completed through `examples/brigade-call.mjs` against a visible iOS 26.2 Simulator. Hosted Jev chose seven actions from the accessibility tree. No action allowlist or scripted tap sequence was used.

| Measurement | Final showcase |
| --- | --- |
| Goal | Lisbon, Design & coffee, Walking, 10:00, save weekend |
| Result | Both exact final labels observed |
| Actions / model requests | 7 / 7 |
| Runner elapsed time | 16.6088 seconds |
| Median model request | 224.14 ms |
| Model request range | 193.064–433.006 ms |
| Provider-reported input tokens | 17,849 |
| Estimated model cost | $0.000750 at the fetched rate |

Runner time includes observation, inference, input, and final verification. It excludes app launch, authentication setup, recording setup/finalization, and report generation. Model timings include request/response transport. These are individual-run measurements, not a general performance or reliability benchmark. Cost is calculated from the advertised rate of $0.042 per million input tokens, with zero output charge; it is not a billing-ledger readback or confirmation of a free promotion.

The [report](media/showcase.html) embeds the [full recording](media/showcase.mp4), rendered at its original speed. The published video is resized to 660 pixels wide and re-encoded, with no cuts or timeline acceleration. The [result manifest](media/showcase-result.json) includes publication-source fingerprints and provider-reported usage. Initial-connection deadline handling and report captions were finalized after this capture and passed focused tests; the native app and scenario match the recording. Raw accessibility traces remain in ignored local `runs/`.

## Other attempts and checks

An earlier seven-action Daybreak run passed in 15.6247 seconds (256.386 ms median model request). During UI refinement, another run stopped on low confidence after a save tap did not advance the screen. A separate, explicit one-action save check then passed. A dark-mode/larger-text Kyoto experiment stopped on a provider HTTP 503 after three actions; no automatic retry occurred. Those attempts are retained locally and are not represented as completed showcases.

Native light-mode screens and the full recorded flow were inspected. Dark mode with extra-extra-extra-large text was inspected on the home, destination, and mood screens. Compact native navigation titles and the timeline's time column were corrected from simulator evidence. This is not a full accessibility audit, device matrix, or measured frame-rate benchmark.

The installed package's `jev-ios` entry point passed a clean virtual-environment check. The optimized arm64 fixture build and code signing passed. Independent reviews covered model transport, target binding, clipping, stale observations, recording cleanup, report sanitization, CLI interruption, and the Node boundary. Focused regressions cover identified defects. All 99 Python tests and 12 Node tests pass. Run the local suites documented in the README; no hosted GitHub Actions are required.

## Scope

Completion proves exact accessibility labels in the selected app. It does not prove backend effects or visual correctness. Tap navigation is demonstrated live. Scroll dispatch was exercised, but that Kyoto attempt did not complete; typing is covered offline and requires observable focus. Both should be validated against the intended app before broader use. Canvas-only screens and missing semantics remain unsupported.

The standalone wrapper is executable integration for a Brigade host on the simulator's Mac. This repository does not register a native Brigade operation or claim Brigade conformance. The integration guide identifies that remaining adoption work.
