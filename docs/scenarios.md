# Reusable scenarios

A scenario describes a goal and its permitted actions without tying it to a
device or model account. Use it with any installed simulator app that exposes
usable accessibility labels and controls. Supply the simulator, app, credentials,
and provider configuration when constructing the adapters.

```json
{
  "schema": "jev-ios/scenario/v1",
  "name": "Open settings",
  "goal": "Open the settings screen",
  "expect_labels": ["Settings", "Notifications"],
  "allow_labels": ["Profile", "Settings"],
  "allow_scroll": false,
  "max_steps": 12,
  "min_probability": 0.55
}
```

All expected labels must match visible accessibility labels exactly. Matching
does not prove backend behavior, visual quality, accessibility compliance, or
release readiness. A model's `DONE` response cannot replace these checks.

`allow_labels` limits tap candidates. Omitting it or using an empty array allows
all supported observed tap targets. Scrolling defaults to disabled. Optional
`text_values` maps names to exact fixture strings, for example
`{"search_query": "blue jacket"}`. The model selects a value; it cannot invent
text. Keep passwords, API keys, real personal data, device identifiers, and
provider configuration out of scenario files. Fixture strings and observed UI
text may be sent to the selected model.

Files must contain a UTF-8 JSON object of at most 64 KiB. The loader rejects
unknown fields, duplicate JSON keys, and unsupported schema versions. Limits are
300 characters for names and labels, 4,000 for goals, 30 labels per list, 20 text
values with keys up to 300 characters and values up to 500, 1–30 steps, and a
finite confidence threshold from 0 to 1. Required strings cannot be blank.
Whitespace in valid labels and fixture values is preserved.

## Python adapters

`jev_ios.protocols` declares structural `Device`, `Model`, and `Snapshot`
interfaces. Adapters need the matching methods; inheritance is optional. Import
custom implementations directly in Python and use the existing runner:

```python
from jev_ios.protocols import Device, Model
from jev_ios.runner import Runner
from jev_ios.scenario import load_scenario

def run_saved_scenario(path: str, device: Device, model: Model):
    scenario = load_scenario(path)
    runner = Runner(device, model, **scenario.to_runner_kwargs())
    return runner.run(scenario.goal, scenario.expect_labels)

# Construct these with your own local configuration, then pass them above:
# from my_adapters import MyDevice, MyModel
```

A device observes a snapshot, executes a selected action, and captures a
screenshot. Snapshots expose elements, exact labels, a screen fingerprint, target
IDs, and a bounded model projection. A model implements
`decide(state, actions, tap_targets, type_targets, text_values)` and returns a
dictionary containing `operation` and a finite `probability` from 0 to 1. Taps
and typing also return an offered `target` ID; typing returns a supplied
`text_key`. Timing and usage fields are optional.

The protocols describe method shapes, not a sandbox or a plugin registry.
Scenario files never import or execute code. Custom adapters retain target
identity, fresh observations, bounded commands, and uncertain-effect handling.
Raise `StaleObservation` before dispatch when the screen changed, and
`DeviceError` when an action may have landed but its result is uncertain. Do not
retry that action automatically or treat model output as execution authority.

The included AXe adapter excludes secure fields and requires observed focus
before typing into an empty field. Missing focus evidence blocks typing. Custom
overlays and incomplete accessibility trees can limit what it observes; a custom
adapter must state its own limits. These interfaces are local extension points
and do not register operations in Brigade.
