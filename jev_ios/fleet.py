"""Native and SSH-connected Mac simulator sessions. No cloud provisioning."""
from __future__ import annotations

import json
import re
import subprocess

from .device import AxeDevice, DeviceError
from .lease import device_lease
from .suite import WorkerSpec, validate_workers


def booted_workers():
    try:
        proc = subprocess.run(["xcrun", "simctl", "list", "devices", "available", "--json"],
                              capture_output=True, text=True, timeout=20, check=True)
        devices = json.loads(proc.stdout)["devices"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        raise ValueError("Cannot list local simulators; select explicit devices or an SSH pool") from None
    found = [d for runtime, group in sorted(devices.items()) if ".iOS-" in runtime
             for d in group if d.get("isAvailable", True) and d.get("state") == "Booted"]
    return validate_workers([WorkerSpec(f"local-{i + 1}", d["udid"]) for i, d in enumerate(found)])


class NativeSession(AxeDevice):
    def __init__(self, worker: WorkerSpec, bundle_id: str, *, lease_directory=None):
        super().__init__(worker.udid, bundle_id, axe_path=worker.axe)
        self._lease = device_lease(worker.udid, directory=lease_directory)

    def __enter__(self):
        self._lease.__enter__()
        return self

    def __exit__(self, *exc):
        self._lease.__exit__(*exc)

    def reset(self, launch_args=()):
        # Relaunch is not a data wipe. The app must implement caller-supplied
        # fixture flags or start from another explicitly prepared test fixture.
        try:
            boot = subprocess.run(["xcrun", "simctl", "bootstatus", self.udid, "-b"],
                                  capture_output=True, timeout=90, check=False)
        except (OSError, subprocess.SubprocessError):
            raise DeviceError("Simulator boot did not complete") from None
        if boot.returncode:
            raise DeviceError("Simulator boot did not complete")
        # Keep termination separate from launch. On some Xcode/CoreSimulator
        # runtimes, simctl's combined --terminate-running-process form can
        # hang even though the equivalent native operations complete.
        try:
            subprocess.run(["xcrun", "simctl", "terminate", self.udid, self.bundle_id],
                           capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            raise DeviceError("Simulator app termination did not complete") from None
        output = self._run(["xcrun", "simctl", "launch", self.udid, self.bundle_id, *launch_args])
        match = re.fullmatch(re.escape(self.bundle_id) + r":\s*([1-9][0-9]*)", output)
        if not match:
            raise DeviceError("Relaunch did not identify the selected application")
        self.pid = int(match[1])
        self._consumed.clear()


def open_session(worker: WorkerSpec, bundle_id: str):
    if worker.transport == "mobai":
        from .mobai import MobAIDevice
        return MobAIDevice(worker.udid, bundle_id, base_url=worker.mobai_url, app_ref=worker.mobai_app, holder="jev-ios-"+worker.name)
    if worker.host:
        from .remote import RemoteSession
        return RemoteSession(worker, bundle_id)
    return NativeSession(worker, bundle_id)
