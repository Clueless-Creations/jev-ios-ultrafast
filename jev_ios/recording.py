"""Original-rate simulator capture, started before the runner clock."""
import signal
import subprocess
import threading
import time
from pathlib import Path


class VideoRecorder:
    def __init__(self, udid, path):
        self.udid, self.path = udid, Path(path)
        self.process = None
        self.started_at = None
        self._attempted = False
        self._failure = None
        self._reader = None

    def start(self):
        if self._attempted or self.process is not None:
            raise ValueError("A recorder can start only once; create a new recorder for another run")
        if self.path.exists():
            raise ValueError("Recording path already exists")
        if self.path.suffix.lower() != ".mp4":
            raise ValueError("Recording path must end in .mp4")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ready = threading.Event()
        self._attempted = True
        try:
            self.process = subprocess.Popen(
                ["xcrun", "simctl", "io", self.udid, "recordVideo", "--codec=h264", str(self.path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, shell=False, umask=0o077,
            )
        except OSError:
            self._failure = "Simulator recording process could not start"
            raise ValueError(self._failure) from None
        process = self.process
        def read():
            try:
                for line in process.stderr:
                    if "Recording started" in line and self.started_at is None:
                        self.started_at = time.perf_counter()
                        ready.set()
            except (OSError, ValueError):
                pass
            finally:
                process.stderr.close()
        self._reader = threading.Thread(target=read, daemon=True)
        self._reader.start()
        if not ready.wait(10):
            try:
                self.stop()
            finally:
                self._failure = "Simulator recording did not start within 10 seconds"
            raise ValueError(self._failure)
        if process.poll() is not None:
            try:
                self.stop()
            finally:
                self._failure = "Simulator recorder exited before the run began"
            raise ValueError(self._failure)
        return self

    def stop(self):
        process = self.process
        if process is not None:
            kill_attempted = False
            try:
                if process.poll() is None:
                    try:
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass
                try:
                    status = process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        kill_attempted = True
                        process.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
                    raise ValueError("Recording could not be finalized") from None
                if status != 0:
                    raise ValueError("Simulator recorder exited unsuccessfully; capture is incomplete")
            except KeyboardInterrupt:
                # A host SIGTERM handler may also raise KeyboardInterrupt. Kill
                # and reap before dropping ownership of the recorder process.
                # Defer additional interruption signals only during this bounded
                # cleanup; the original interruption is re-raised below.
                previous_handlers = {}
                if threading.current_thread() is threading.main_thread():
                    for signum in (signal.SIGINT, signal.SIGTERM):
                        previous_handlers[signum] = signal.getsignal(signum)
                        signal.signal(signum, lambda *_args: None)
                try:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                finally:
                    for signum, handler in previous_handlers.items():
                        signal.signal(signum, handler)
                self._failure = "Recording finalization interrupted"
                raise
            except OSError:
                if not kill_attempted:
                    try:
                        process.kill()
                    except OSError:
                        pass
                try:
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                self._failure = "Recording could not be finalized"
                raise ValueError(self._failure) from None
            except ValueError:
                self._failure = "Recording could not be finalized"
                raise ValueError(self._failure) from None
            finally:
                self.process = None
                if self._reader:
                    self._reader.join(timeout=0.5)
                # The reader closes its pipe on EOF. Do not block on its I/O lock
                # if an unreaped process still has the pipe open.
                if process.stderr and (not self._reader or not self._reader.is_alive()):
                    process.stderr.close()
        if self._failure:
            raise ValueError(self._failure)
        if self.started_at is not None:
            valid = self.path.is_file() and self.path.stat().st_size >= 100
            if valid:
                with self.path.open("rb") as handle:
                    valid = handle.read(12)[4:8] == b"ftyp"
            if not valid:
                self._failure = "Simulator did not produce a usable recording"
                raise ValueError(self._failure)
        if self.path.exists():
            self.path.chmod(0o600)
