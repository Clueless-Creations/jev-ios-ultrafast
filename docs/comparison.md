# Matched simulator comparison

This compares Jev's indexed choice API with GPT-5.4 Nano generating a JSON action. Both use the same accessibility observations, offered operations and targets, local execution adapter, and final-label verifier. It is a comparison of two complete decision backends, not an isolated test of decoding architecture.

The baseline uses one structured-output request per decision, temperature 0, reasoning effort `none`, and at most 128 output tokens. The selected model is `openai/gpt-5.4-nano` through Vercel AI Gateway. The catalog lists it as a small model intended for classification, extraction, ranking, and subagents; it was selected before measuring the cohort. Both adapters use a fresh connection per attempt and reuse it between decisions.

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

Run the baseline on its own with `jev-ios run --engine baseline --min-probability 0`, followed by the ordinary target, scenario, and artifact options. `--baseline-model` selects another compatible structured-output model; the configured settings require temperature 0 and reasoning effort `none` support.

## What stays equal

- App binary, simulator, appearance, text size, goal, final labels, and action limits.
- One decision request per step, 24,000-byte request ceiling, 10-second network deadline, and 16-step showcase limit.
- Fresh observation before input, local target resolution, no retry after uncertain input, and deterministic completion checks.
- Confidence cutoff **0 for both**. The baseline does not supply calibrated choice probabilities. Its confidence remains `null`; no fabricated 100% score or self-reported probability is used. Jev's default 0.55 cutoff remains unchanged outside comparisons.
- Recording, startup stabilization, and timing boundaries. Trials run sequentially; side-by-side playback is synchronized replay, not simultaneous execution.

## Reading the numbers

Task time includes observations, inference, input, waits, and final verification. Reset, startup stability, credentials, pricing checks, and recording setup/finalization are excluded. Model request times include connection and network wait; they are not GPU inference measurements. Successful request latencies exclude requests with no usable response; the outcome table retains those failed attempts.

The report shows completion counts before speed ratios. Verified-run medians and per-pair ratios have separate labels. A short failed attempt is never treated as faster completion. Three pairs on one local fixture provide a smoke comparison, not a statistically powered benchmark across apps.

Cost is estimated from catalog rates and reported input/output/cache usage. Missing usage makes the cost unknown, not zero. Provider routing, load, and automatic caching are not fully controlled; cached tokens are reported when available. The baseline's JSON prompt and Jev's choice questions expose equivalent information but are different provider formats. Those differences and the models' capabilities are part of this backend comparison.

Vercel documents [structured outputs](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/structured-outputs), [reasoning controls](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/reasoning), and [model discovery](https://vercel.com/docs/ai-gateway/models-and-providers). The live catalog, rather than a promotional claim, supplies the run's rate estimate.
