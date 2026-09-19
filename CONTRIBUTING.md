# Contributing

Fork the repository, create a branch in your fork, and open a pull request against `Clueless-Creations/jev-ios-ultrafast:main`. Maintainers review and merge changes. You do not need write access to contribute.

Read [AGENTS.md](AGENTS.md) and the [architecture](docs/architecture.md) before changing the runtime. Keep pull requests focused on one behavior so a reviewer can understand and test the change.

## Set up and check your change

The package needs Python 3.11+. Node.js runs the wrapper tests. Simulator work also needs macOS, Xcode, an iOS runtime, and AXe; the [README](README.md#try-it-on-your-mac) covers that setup.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

python3 -m unittest discover -s tests -v
node --check examples/brigade-call.mjs
node --test tests/test_brigade.mjs
```

Keep automated tests offline. Add regression coverage when changing validation, execution, interruption handling, or result accounting. Include the checks you ran and their results in the pull request. The project runs checks locally and does not use hosted GitHub Actions workflows.

For simulator changes, use Daybreak or an app you are authorized to test. Start with fixture data. A successful label check confirms those labels appeared; separately verify any backend effect your change depends on.

## What to include in a pull request

Describe the problem, the resulting behavior, and how you checked it. For a bug, include a small reproduction and the relevant environment: macOS, Xcode, iOS runtime, Python, and AXe versions. A sanitized trace can help explain a failure.

For a new scenario, include its goal, exact expected labels, supported app state, and reset instructions. For a model or device adapter, preserve observed target identity, screen freshness checks, bounded requests, and uncertain-action handling. Follow the contracts in `jev_ios/protocols.py`; model output must never become a shell command or an unobserved coordinate.

For benchmark claims, include the scenario and source revision, model settings, reset procedure, order of attempts, all outcomes, and timing boundaries. Keep failed attempts. Separate usable-response latency from task time, and measured usage from estimated cost. The [comparison protocol](docs/comparison.md) describes the current method.

## Keep app data and credentials local

Raw traces, screenshots, recordings, and builds belong in ignored `runs/`. Review any excerpt or curated media before adding it to an issue or pull request. Do not include credentials, account data, personal paths, device identifiers, private app content, or provider responses that contain secrets.

Use environment variables for credentials. Live inference can incur charges; tests must not require an API key or call a provider. Do not include real purchases, sent messages, or production mutations in a test fixture.

Contributions are licensed under the repository's [MIT license](LICENSE). Retain third-party notices and add attribution when a contribution includes third-party material.
