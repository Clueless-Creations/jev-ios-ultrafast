"""Cross-process leases shared by the CLI, matrix lanes and remote workers."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import stat
import threading
import time

from .device import DeviceError


class DeviceBusy(DeviceError):
    """Another cooperating process owns this simulator or fixture resource."""


class Lease:
    def __init__(self, key: str, *, directory=None, wait=False, cancel=None, wait_timeout=None):
        self.key = key
        self.directory = Path(directory) if directory else Path.home() / ".cache" / "jev-ios" / "locks"
        self.wait = wait
        self.wait_timeout = wait_timeout
        self.cancel = cancel or threading.Event()
        self.fd = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():
            raise DeviceBusy("Lease directory must not be a symlink")
        path = self.directory / (hashlib.sha256(self.key.encode()).hexdigest() + ".lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DeviceBusy("Invalid lease file")
            deadline = time.monotonic() + self.wait_timeout if self.wait_timeout is not None else None
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise DeviceBusy("Fixture lease wait timed out")
                if self.cancel.is_set():
                    raise DeviceBusy("Lease acquisition cancelled")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not self.wait:
                        raise DeviceBusy("Selected simulator is already leased by another Jev process") from None
                    self.cancel.wait(0.05)
            self.fd = fd
            return self
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, *_):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        # Do not unlink: a waiter must lock the same inode as the next caller.


def device_lease(udid, **kwargs):
    return Lease("simulator:" + str(udid).lower(), **kwargs)
