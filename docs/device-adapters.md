# Device sessions

Jev scenarios describe intent. Jev remains the fast decision engine; the device transport supplies observation, exclusive access, execution, and fresh evidence.

## Recommended: MobAI

For new multi-device, real-device, Android-adjacent, remote, or cloud workflows, prefer MobAI. The repository now has a native MobAI HTTP/DSL adapter rather than requiring an MCP hop.

```text
coding agent
    |
 SKILL.md
    |
Jev scenario + Jev decisions
    |
jev-ios scheduler
    |
MobAI HTTP / DSL v0.2
    |
local simulator | real device | remote MobAI node | cloud device farm
```

MobAI 2.8.0 exposes device claims, bridge lifecycle, compact semantic UI trees, predicate-based actions, batched DSL execution, local/remote/cloud device routing, and reusable .mob tests. Jev uses those capabilities while retaining its own bounded decision and exact-label verification contract.

Configure the MobAI desktop host, then:

```sh
export MOBAI_URL=http://127.0.0.1:8686/api/v1
# Set MOBAI_TOKEN when the host requires remote authentication.
jev-ios mobai-devices
```

A pool can mix transports:

```json
{
  "schema": "jev-ios/pool/v1",
  "devices": [
    {"name":"native-fast","udid":"00000000-0000-0000-0000-000000000000"},
    {"name":"mobai-local","transport":"mobai","udid":"<mobai-device-id>"},
    {"name":"mobai-farm","transport":"mobai","udid":"<cloud-device-id>","mobai_url":"https://your-mobai-host/api/v1"}
  ]
}
```

MobAI workers are explicitly claimed for the Jev lane and released when it closes. The adapter starts the MobAI bridge, observes compact UI trees, maps Jev targets to semantic MobAI predicates, rejects stale observations, executes through DSL v0.2, waits for stability, and obtains fresh evidence. Jev never emits raw DSL or coordinates.

### Why direct HTTP instead of MobAI MCP?

MobAI MCP is excellent when Claude Code, Codex, Cursor, or another agent itself needs device tools. Jev's runtime already has a Python scheduler and device protocol, so an MCP subprocess would add an unnecessary agent/tool hop. The adapter therefore speaks the same MobAI HTTP/DSL surface directly. Developers may still install `mobai-mcp` for interactive agent work.

### Where MobAI should own the problem

Use MobAI rather than rebuilding these in Jev:

- physical iOS and Android device access;
- remote/distributed device hosts;
- cloud device farms;
- device claims and lease enforcement;
- bridge lifecycle;
- predicate-based interaction, OCR fallback and screenshots;
- deterministic reusable `.mob` flows;
- CI sharding and report bundles through `mobai-ci`.

Jev should own dynamic semantic decisions, scenario selection, bounded inference, and evidence aggregation.

### Deterministic flows

Once a Jev-discovered route becomes stable, consider promoting it to a MobAI `.mob` flow. Deterministic flows should not pay an inference tax forever. Keep Jev for uncertain navigation, changed UI, exploration, and dynamic decisions; use MobAI DSL/tests for stable known sequences.

## Native AXe + simctl

The direct local Simulator path remains supported and has the fewest external moving parts. It is useful for contributors who only need a local iOS Simulator or want to compare transports.

XcodeBuildMCP is not required.

## SSH-connected Mac

The existing SSH worker remains supported for a pre-provisioned Mac running this Jev revision. Prefer MobAI remote/distributed devices when MobAI is already deployed because it avoids maintaining a second device RPC stack and can extend to physical/cloud targets.

## Scaling local simulators

MobAI's `simslim` project is designed to reduce unnecessary Simulator background services and increase the number of iOS simulators a Mac can host. Treat it as an optional host optimization, not a Jev dependency. Qualify your own app before relying on a slimmed simulator profile because disabling services can change behavior.

## Required contracts

Every transport must preserve explicit device/app identity, observed target identity, bounded operations, secure-field handling, fresh pre-input validation, uncertain-action handling, and fresh post-input evidence. Model output never grants authority for purchases, messages, destructive production mutations, or arbitrary shell commands.
