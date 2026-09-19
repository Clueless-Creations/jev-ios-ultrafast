# Matched simulator comparison

The comparison pairs Jev's indexed choice API with a model that generates a JSON action. Both use the same accessibility observations, offered operations and targets, local execution adapter, and final-label verifier. Results compare two complete decision backends, including their provider formats and model capabilities.

Each baseline uses one structured-output request per decision. The default `openai/gpt-5.4-nano` profile uses temperature `0`, reasoning effort `none`, and a 128-token generation limit. The `openai/gpt-6-astra` and `openai/gpt-6-astra-fast` profiles use reasoning effort `low`, omit temperature, and allow 1,024 generated tokens, including reasoning. Both adapters use a fresh connection per attempt and reuse it between decisions.

The published recordings below compare Jev with GPT-5.4 Nano, selected before measuring those cohorts. Astra has [request profiles and documented access checks](astra-comparison.md), but no recorded iOS benchmark.

The reference cohort schedules three pairs in this order: Jev→baseline, baseline→Jev, Jev→baseline. Every attempt is retained. An error is an outcome, not permission to replace a run. Success requires the same exact final labels. The report only calculates paired task-time ratios when both runs verify and their starting state matches.

## Run a comparison

Use a dedicated booted simulator and an installed app whose initial state is restored by relaunch. For Daybreak, every launch constructs a new trip; the saved trip preference is never read. No preferences or app data are deleted.

```sh
jev-ios compare \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" \
  --bundle-id org.example.jevsimdemo \
  --start-label Daybreak --start-label Lisbon --start-label Kyoto \
  --pairs 3 \
  --vercel-project YOUR_EXISTING_VERCEL_PROJECT \
  --budget-usd 1 \
  --output-dir runs/comparison-01
```

Use environment credentials instead of `--vercel-project` if preferred. The output directory must be new. The command writes each attempt's trace, video, and a durable `comparison.json`, then generates `comparison.html`. Exit code 2 means at least one attempt did not verify; the comparison remains useful and must be reported with that outcome. Recordings are on for both backends by default. `--no-record-video` disables them for both.

For another app, supply its bundle ID, scenario, and distinctive starting labels. Relaunch may not reset that app's state. The harness compares the normalized initial controls and geometry, excluding process IDs and timestamps. Starting-state mismatches invalidate paired timing. Build changes, outside input, and changes to the simulator configuration also invalidate the cohort and must be disclosed.

To regenerate the report without inference:

```sh
jev-ios comparison-report \
  --manifest runs/comparison-01/comparison.json \
  --output runs/comparison-01/review.html
```

Run the baseline on its own with `jev-ios run --engine baseline --min-probability 0`, followed by the ordinary target, scenario, and artifact options. `--baseline-model` selects a model and its request profile. `--baseline-max-output-tokens` overrides its generation limit from 1 to 8,192 tokens. Declare settings before collecting a cohort and retain them in the results. Unknown model IDs use temperature `0`, reasoning `none`, and a 128-token limit; verify compatibility before collecting a cohort.

## What stays equal

- App binary, simulator, appearance, text size, goal, final labels, and action limits.
- One decision request per step, 24,000-byte request ceiling, 10-second network deadline, and 16-step showcase limit.
- Fresh observation before input, local target resolution, no retry after uncertain input, and deterministic completion checks.
- Confidence cutoff **0 for both**. The baseline does not supply calibrated choice probabilities. Its confidence remains `null`; no fabricated 100% score or self-reported probability is used. Jev's default 0.55 cutoff remains unchanged outside comparisons.
- Recording, startup stabilization, and timing boundaries. Trials run sequentially; side-by-side playback is synchronized replay, not simultaneous execution.

## Reading the numbers

Task time includes observations, inference, input, waits, and final verification. Reset, startup stability, credentials, pricing checks, and recording setup/finalization are excluded. Model request times include connection and network wait; they are not GPU inference measurements. Successful request latencies exclude requests with no usable response; the outcome table retains those failed attempts.

The report shows completion counts before speed ratios. Verified-run medians and per-pair ratios have separate labels. A short failed attempt is never treated as faster completion. Three pairs on one local fixture provide a smoke comparison, not a statistically powered benchmark across apps.

Cost is estimated from catalog rates and reported input, output, cache-read, and cache-write usage. Missing required usage makes the cost unknown. For the JSON baseline, the admission estimate reserves the selected generation limit and the higher of ordinary input or cache-write prices, without assuming a cache-read discount. Provider routing, load, and automatic caching are not fully controlled; cached tokens are reported when available. The baseline's JSON prompt and Jev's choice questions expose equivalent information but are different provider formats. Those differences and the models' capabilities are part of this backend comparison.

Vercel documents [structured outputs](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/structured-outputs), [reasoning controls](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/reasoning), and [model discovery](https://vercel.com/docs/ai-gateway/models-and-providers). The live catalog, rather than a promotional claim, supplies the run's rate estimate.

## Recorded results · September 19, 2026

[Interactive paired replay](media/comparison.html) · [Complete result data](media/comparison.json)

Two fixed three-pair cohorts ran on the same Daybreak binary, iOS 26.2 Simulator, Xcode 27.0, Apple Silicon MacBook Pro, light appearance, and Large text. Each cohort used the declared Jev→baseline, baseline→Jev, Jev→baseline order. The second complete cohort was scheduled after the first produced no mutually verified pairs. All twelve attempts are published; none were replaced or omitted.

| Measurement | Jev | GPT-5.4 Nano |
| --- | ---: | ---: |
| Verified / attempted | 5 / 6 | 2 / 6 |
| Median usable-response latency | 242.355 ms | 921.740 ms |
| Requests with timing / attempted | 39 / 40 | 34 / 38 |
| Reported input tokens | 97,592 | 48,011 |
| Reported output tokens | 3,986 | 816 |
| Task time in the sole mutually verified pair | 14.6500 s | 25.6351 s |
| Actions in that pair | 7 | 7 |
| Estimated cost of that pair | $0.000748104 | $0.002147800 |

The paired elapsed ratio is **1.7498×**, based on **one of six pairs**. Successful request latency excludes five requests without usable responses. Four baseline attempts ended in HTTP 429; one Jev attempt ended in a connection failure or timeout. These provider failures confound model-quality and availability comparisons. Total costs remain unknown because failed requests lack usage; no zero-cost assumption is made.

| Cohort / pair | Order | Jev outcome and time | Baseline outcome and time |
| --- | --- | --- | --- |
| 1 / 1 | Jev first | Verified · 15.6827 s | HTTP 429 after 10 actions · 31.1699 s |
| 1 / 2 | Baseline first | Verified · 21.5469 s | HTTP 429 before input · 0.3998 s |
| 1 / 3 | Jev first | Timeout after 4 actions · 19.1370 s | Verified · 27.8271 s |
| 2 / 1 | Jev first | Verified · 18.1145 s | HTTP 429 after 10 actions · 29.5498 s |
| 2 / 2 | Baseline first | Verified · 14.8830 s | HTTP 429 before input · 0.6314 s |
| 2 / 3 | Jev first | Verified · 14.6500 s | Verified · 25.6351 s |

The replay opens pair 6 because it is the sole pair with two verified outcomes; the other ten attempts remain available in the table and pair selector. Baseline attempts that reached ten actions had skipped Walking, saved the wrong preference, and restarted the flow before rate limiting. The verifier correctly rejected that intermediate saved screen. This does not establish what those attempts would have done without throttling.

The public commit with the identical measured source tree is `a021dad2b73f98d7b39381a8f2f086f5479ec3fa`. The manifest records the app binary and scenario SHA-256 values, cohort timestamps, usage, individual request times, and recording fingerprints. All twelve actual first-observation element lists have the same SHA-256, in addition to the matching setup-state hashes. Changes made before publishing this Nano cohort hardened first-observation matching, interruption cleanup, incomplete-cohort exit status, and replay controls; they did not change the measured decision backends or Runner.

Both adapters received one excluded synthetic DONE preflight request before the first cohort; baseline parameter compatibility was checked separately before measurement. No warmup app run was discarded from these cohorts. Credentials, catalog fetches, reset, stable-screen checks, and recording setup are outside the task clock.

All twelve recordings are included. Publication scales them to 660 pixels wide and re-encodes H.264 while preserving every frame's presentation timestamp within 1/600 second; no timeline acceleration or cuts are used. Container end durations can differ by up to 0.119 seconds because of final-frame duration metadata. Simulator recording can omit trailing static time—for example, the timeout recording ends before the request deadline. Playback therefore labels its recording clock separately from measured task time and holds the last available frame. Raw traces stay local; their hashes are published.

At publication of the Nano results, the local suite passed 170 Python tests and 13 Node wrapper tests, including replay-controller mocks. Independent review covered model validation, matching, interruption preservation, cost accounting, publication filtering, and replay synchronization. This remains a small simulator smoke comparison, not a powered benchmark or a claim about other apps, models, devices, or provider accounts.
