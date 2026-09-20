"""Authenticated stdio device RPC over SSH; inference stays at the coordinator.

No listening HTTP server, arbitrary commands, API keys, or decision logic are
sent to the remote Mac. Deploy this same revision on both machines first.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
import select
import shlex
import subprocess
import sys
import time

from .device import DeviceError, Snapshot, StaleObservation
from .suite import WorkerSpec, bundle_identifier, fields, strings

PROTOCOL = "jev-ios/device-rpc/v1"
LIMIT = 1_000_000


class RemoteSession:
    def __init__(self, worker, bundle_id, *, process_factory=subprocess.Popen):
        self.worker, self.bundle_id = worker, bundle_identifier(bundle_id)
        self.process_factory = process_factory
        self.process = None
        self.buffer = b""
        self.sequence = 0

    def __enter__(self):
        command = shlex.join([self.worker.python, "-m", "jev_ios.remote"])
        try:
            self.process = self.process_factory(
                ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", self.worker.host, command],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            response = self._request("open", worker=self.worker.as_dict(), bundle_id=self.bundle_id)
            if response != {"protocol": PROTOCOL}:
                raise DeviceError("Remote worker protocol mismatch; install the same Jev revision")
            return self
        except BaseException:
            self.__exit__()
            raise

    def _request(self, op, **params):
        self.sequence += 1
        request = json.dumps({"id": self.sequence, "op": op, "protocol": PROTOCOL, **params},
                             allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(request) > LIMIT:
            raise DeviceError("Remote request exceeds the size limit")
        deadline = time.monotonic() + (100 if op == "reset" else 65)
        try:
            offset = 0
            while offset < len(request):
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([], [self.process.stdin], [], left)[1]:
                    raise TimeoutError()
                try:
                    offset += os.write(self.process.stdin.fileno(), request[offset:])
                except BlockingIOError:
                    continue
            while b"\n" not in self.buffer:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([self.process.stdout], [], [], left)[0]:
                    raise TimeoutError()
                part = os.read(self.process.stdout.fileno(), 65536)
                if not part:
                    raise EOFError()
                self.buffer += part
                if len(self.buffer) > LIMIT:
                    raise ValueError()
            line, self.buffer = self.buffer.split(b"\n", 1)
            message = json.loads(line)
            if not isinstance(message, dict) or message.get("id") != self.sequence:
                raise ValueError()
            if message.get("error") == "stale":
                raise StaleObservation("Remote observation changed; no action dispatched")
            if message.get("ok") is not True:
                raise DeviceError("Remote device request failed; do not replay an uncertain action")
            return message["result"]
        except (OSError, EOFError, ValueError, KeyError, TypeError):
            raise DeviceError("SSH device transport did not complete; check trusted host and installed Jev revision") from None

    def reset(self, launch_args=()):
        self._request("reset", launch_args=list(launch_args))

    def observe(self):
        data = self._request("observe")
        try:
            fields(data, {"elements", "labels", "screen_hash", "pid", "frame", "observed_at", "observation_id"},
                   {"elements", "labels", "screen_hash", "pid", "frame", "observed_at", "observation_id"})
            if not isinstance(data["elements"], list) or len(data["elements"]) > 120:
                raise ValueError()
            return Snapshot(**data)
        except (TypeError, ValueError, KeyError):
            raise DeviceError("Invalid remote snapshot") from None

    def execute(self, snapshot, decision, text_values):
        return self._request("execute", observation_id=snapshot.observation_id,
                             decision=decision, text_values=text_values)

    def screenshot(self, path):
        raise DeviceError("SSH matrix lanes return semantic traces; screenshot transfer is not implemented")

    def __exit__(self, *_):
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            finally:
                if self.process.stdout:
                    self.process.stdout.close()
                self.process = None


def serve(source=None, sink=None, session_factory=None):
    """Run one bound device session until EOF. Exceptions expose no app data."""
    from .fleet import NativeSession
    source = source or sys.stdin.buffer
    sink = sink or sys.stdout.buffer
    session_factory = session_factory or NativeSession
    session, snapshots = None, {}
    try:
        while True:
            raw = source.readline(LIMIT + 1)
            if not raw:
                return
            if len(raw) > LIMIT or not raw.endswith(b"\n"):
                return
            request_id = None
            try:
                message = json.loads(raw)
                if not isinstance(message, dict) or message.get("protocol") != PROTOCOL:
                    raise ValueError()
                request_id = message["id"]
                if type(request_id) is not int:
                    raise ValueError()
                operation = message["op"]
                if operation == "open" and session is None:
                    worker = WorkerSpec(**message["worker"])
                    session = session_factory(worker, bundle_identifier(message["bundle_id"]))
                    session.__enter__()
                    result = {"protocol": PROTOCOL}
                elif session is None:
                    raise ValueError()
                elif operation == "reset":
                    args = strings(message["launch_args"], "launch arguments")
                    session.reset(args)
                    snapshots.clear()
                    result = None
                elif operation == "observe":
                    snapshot = session.observe()
                    snapshots[snapshot.observation_id] = snapshot
                    if len(snapshots) > 4:
                        del snapshots[next(iter(snapshots))]
                    result = asdict(snapshot)
                elif operation == "execute":
                    snapshot = snapshots.pop(message["observation_id"])
                    result = session.execute(snapshot, message["decision"], message["text_values"])
                else:
                    raise ValueError()
                response = {"id": request_id, "ok": True, "result": result}
            except StaleObservation:
                response = {"id": request_id, "ok": False, "error": "stale"}
            except Exception:
                # The adapter may have dispatched input. Close the channel so
                # the caller cannot continue using an uncertain device session.
                sink.write(json.dumps({"id": request_id, "ok": False, "error": "device"}).encode() + b"\n")
                sink.flush()
                return
            encoded = json.dumps(response, allow_nan=False).encode() + b"\n"
            if len(encoded) > LIMIT:
                return
            sink.write(encoded)
            sink.flush()
    finally:
        if session:
            session.__exit__(None, None, None)


if __name__ == "__main__":
    serve()
