# Astra comparison

Astra Standard and Fast have request profiles in the runner. Vercel AI Gateway rejected the access checks on the tested account, so no iOS benchmark has been recorded for either model.

## Access checks · September 19, 2026

Before scheduling a simulator cohort, we sent one synthetic transport request to each model. These requests were excluded from benchmark results and did not drive an app.

| Check | Model | Result |
| --- | --- | --- |
| One synthetic request | `openai/gpt-6-astra` | HTTP 403 |
| One synthetic request | `openai/gpt-6-astra-fast` | HTTP 403 |
| One separate diagnostic request | `openai/gpt-6-astra` | HTTP 403, `no_providers_available`; free-tier access denied |

The [preflight record](media/astra-preflight.json) includes the request profiles, timestamps, and outcomes. The Gateway diagnostic reported that free-tier users could not access the model and required paid credits. No credits were purchased and no app cohort was started. These access failures provide no measurement of Astra's iOS task speed or reliability. Successful live Astra responses remain unverified on the tested account.

The local suite passed 183 Python tests and 14 Node wrapper tests, including coverage for request profiles and budget handling. The [published Jev/Nano comparison](comparison.md#recorded-results--september-19-2026) retains its original recordings and results.

## Request profiles

The JSON adapter has explicit profiles for three Vercel AI Gateway model IDs:

| Model | Reasoning effort | Temperature | Default generation limit |
| --- | --- | --- | --- |
| `openai/gpt-5.4-nano` | `none` | `0` | 128 tokens |
| `openai/gpt-6-astra` | `low` | Omitted | 1,024 tokens |
| `openai/gpt-6-astra-fast` | `low` | Omitted | 1,024 tokens |

These are request settings, not benchmark results. Astra requires reasoning and does not accept temperature. The limit covers all generated tokens, including reasoning. The adapter retains the same strict JSON action schema, state, offered choices, validation, and 10-second request deadline. It never substitutes another model. [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model), [Vercel reasoning API](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/reasoning)

Select either Astra ID with `--baseline-model` on `run` or `compare`. Use `--baseline-max-output-tokens` to declare a different limit from 1 to 8,192 before collecting a cohort. Unknown model IDs retain the legacy settings of reasoning `none`, temperature `0`, and 128 tokens; their compatibility must be verified separately.

Use credentials for a Gateway account with paid model access. Vercel states that purchasing Gateway credits moves an account to the paid tier and ends its monthly free-credit allowance. Review its [pricing terms](https://vercel.com/docs/ai-gateway/pricing) before changing an account.

Once access is available, install Daybreak and set the simulator and credentials before running:

```sh
jev-ios compare \
  --scenario scenarios/showcase.json \
  --udid "$SIMULATOR_UDID" --bundle-id org.example.jevsimdemo \
  --start-label Daybreak --start-label Lisbon --start-label Kyoto \
  --baseline-model openai/gpt-6-astra \
  --pairs 1 --budget-usd 6 \
  --output-dir runs/astra-standard-01
```

The CLI reads current catalog prices before admitting a run. Its estimate reserves the full request bound, the selected generation limit, and the higher of ordinary input or cache-write prices. It assumes no cache-read discount. At the catalog rates checked on September 19, 2026, a 16-step Jev/Astra pair reserves $5.764608 for Standard or $11.486208 for Fast; an 8-step pair reserves $2.882304 or $5.743104. The estimate is a conservative admission limit, not a provider billing cap. Actual usage can be lower; missing cache-write usage makes the reported cost unknown.

Record Standard and Fast in separate cohorts with the complete model ID and request profile. First verify a successful response with an excluded transport request. Keep unsuccessful attempts, follow the [comparison protocol](comparison.md), and report completion as well as speed. Determining which engine finishes an iOS flow fastest requires completed, matched runs.

The Brigade wrapper accepts `baselineModel` and optional `baselineMaxOutputTokens` with `engine: "baseline"` and `minProbability: 0`.
