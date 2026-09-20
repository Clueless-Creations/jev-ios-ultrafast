# Device adapters

Jev's decision loop should not depend on a particular coding agent, MCP server, or mobile automation product.

## Native iOS Simulator

This is the default local path.

```text
Codex / Claude Code / other shell-capable agent
                    |
                 jev-ios
                    |
             Jev decision loop
                    |
               device adapter
              /             \
       xcrun simctl          AXe
              \             /
              iOS Simulator
```

XcodeBuildMCP is not required. The runner already uses Apple's `xcrun simctl` directly for simulator process management, screenshots, and app launch. AXe supplies semantic UI observation and input.

If AXe is present inside another tool installation, discovery may use it as a convenience. That must never turn that tool into a runtime requirement.

## Coding agents

Codex, Claude Code, and other shell-capable coding agents should use the same CLI and SKILL.md contract. Agent-specific integrations may improve installation or discovery, but they must not fork scenario semantics.

The portable contract is:

1. app intent becomes a Jev scenario;
2. the device adapter returns normalized semantic snapshots;
3. Jev selects only offered operations/targets;
4. the adapter executes after freshness validation;
5. the runner verifies fresh observed state.

## MobAI

MobAI is an optional device transport for users who want its broader mobile surface.

As of September 2026, MobAI exposes iOS simulators and real iOS/Android devices to coding agents through MCP and a local HTTP API, and its tooling supports Codex, Claude Code, Cursor, and other agents.

The desired Jev integration is:

```text
                    Jev scenario
                         |
                    Jev decision
                         |
                normalized Device API
                  /               \
          native AXe             MobAI
          + simctl             adapter
              |                   |
       iOS Simulator      simulator / device
```

A MobAI adapter should implement the same device protocol as the native adapter. It should translate MobAI's semantic UI tree into Jev's normalized snapshot and translate a validated Jev action into MobAI execution. Provider-specific IDs and transport details stay inside the adapter.

Do not make MobAI mandatory. Do not make MCP mandatory. Do not teach the model two scenario languages.

## Why both paths

The native adapter is the smallest dependency set for a Mac developer already running Xcode and Simulator.

MobAI adds useful reach where its transport is preferred: real devices, Android, MCP/HTTP integration, CI/device workflows, and cloud-agent workflows. Keeping it behind the device protocol lets Jev gain those surfaces without coupling its reasoning and verification contract to them.

## Adapter requirements

Any device adapter must preserve:

- explicit target identity from a fresh observation;
- app/device identity;
- bounded observations and actions;
- no arbitrary model-generated coordinates or shell commands;
- stale-state rejection before dispatch;
- uncertain-action handling;
- secure-field redaction;
- fresh post-action observation;
- evidence sufficient for the runner to verify scenario expectations.

See `jev_ios/protocols.py` and `docs/architecture.md`.
