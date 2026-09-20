# Device sessions

Jev scenarios describe intent, not a device transport. The existing `Runner` consumes the normalized interfaces in `jev_ios/protocols.py`; matrix sessions add reset and exclusive lifecycle ownership around that interface.

## Implemented: local Simulator

`NativeSession` in `jev_ios/fleet.py` extends the AXe device adapter. It holds a cross-process simulator lease, waits for boot, relaunches the explicit bundle ID, checks the resulting PID, and uses the existing observation/input validation.

```text
shell-capable coding agent
          |
       jev-ios
          |
    native session
     /         \
  simctl       AXe
     \         /
     iOS Simulator
```

XcodeBuildMCP is not required. Standalone AXe may be on PATH or selected with an explicit path. The scheduler does not install Xcode, download runtimes, create clones, erase devices, or build/install the app.

## Implemented: SSH-connected Mac

`RemoteSession` in `jev_ios/remote.py` starts a device-only worker through an existing authenticated SSH connection. A pool supplies a trusted SSH alias, simulator UUID, and the Python executable containing this same Jev revision.

```text
coordinator: Python scheduler + Jev API clients
                       |
               authenticated SSH
                       |
remote Mac: python -m jev_ios.remote
                       |
             native Simulator session
```

The coordinator retains all model calls, rate limits, and aggregate pricing admission. No Jev API key is sent to the remote Mac. The worker accepts bounded open/reset/observe/execute messages, not shell commands or model prompts. It stores observation tokens locally and uses the native adapter's freshness check before input.

SSH host-key checking is not disabled. Configure trust and credentials outside the scenario. A broken connection after input is uncertain; the lane stops and the action is not retried. Closing the worker releases its device lease. Remote snapshots and trace data travel through SSH to the coordinator's private artifacts.

The remote session currently supplies semantic evidence only, not screenshot/video transfer. Tests cover the protocol and real subprocess pipes with fake device adapters. This is not a claim that a remote Mac or cloud provider was exercised during implementation.

## Extension, not support claim: MobAI and device farms

There is no MobAI runtime adapter, `--device mobai` switch, physical-device driver, Android driver, or vendor device-farm provisioner in this repository. The earlier MobAI document was an architectural proposal. Those transports can be added without a second scenario language, but each requires an implemented adapter and independent qualification.

A remote Mac supplied by a cloud provider can be used today through SSH once it is provisioned with Xcode, AXe, matching Jev code, an appropriate runtime, and the installed fixture app. Jev does not purchase or provision that host.

## Required contracts

An adapter must preserve explicit app/device identity, observed target identity, bounded operations, secure-field redaction, fresh pre-input validation, uncertain-action handling, and independent post-input evidence. Runtime target IDs never become cross-device selectors. Model decisions do not grant permission for purchases, messages, or production mutations.

The local lease protects cooperating Jev processes using the same OS account on a device host. Coordinator resource locks protect cooperating jobs on that coordinator; they do not lock a backend used from unrelated machines. See [parallel testing](parallel-testing.md) for fixture design and operational limits.
