import io
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from jev_ios.recording import VideoRecorder


class ImmediateThread:
    def __init__(self, *, target, daemon):
        self.target = target

    def start(self):
        self.target()

    def join(self, timeout):
        pass

    def is_alive(self):
        return False


class FakeEvent:
    def __init__(self):
        self.ready = False
        self.waited = []

    def set(self):
        self.ready = True

    def wait(self, timeout):
        self.waited.append(timeout)
        return self.ready


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fixture.mp4"
        self.stream = io.StringIO("Recording started\n")
        self.process = Mock(stderr=self.stream)
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        self.process.returncode = 0
        self.event = FakeEvent()
        self.popen = Mock(return_value=self.process)
        for mocked in (patch("jev_ios.recording.subprocess.Popen", self.popen),
                       patch("jev_ios.recording.threading.Thread", ImmediateThread),
                       patch("jev_ios.recording.threading.Event", return_value=self.event)):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.recorder = VideoRecorder("fixture-device", self.path)

    def usable_video(self):
        self.path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"fixture" * 20)

    def test_starts_only_after_readiness_and_stops_once_with_sigint(self):
        self.assertIs(self.recorder.start(), self.recorder)
        self.assertIsNotNone(self.recorder.started_at)
        self.assertEqual(self.event.waited, [10])
        args, kwargs = self.popen.call_args
        self.assertEqual(args[0], ["xcrun", "simctl", "io", "fixture-device", "recordVideo", "--codec=h264", str(self.path)])
        self.assertFalse(kwargs.get("shell", False))
        self.usable_video()
        self.recorder.stop()
        self.recorder.stop()
        self.process.send_signal.assert_called_once_with(signal.SIGINT)
        self.process.wait.assert_called_once_with(timeout=15)
        self.process.kill.assert_not_called()
        self.assertTrue(self.stream.closed)
        self.assertIsNone(self.recorder.process)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_existing_path_and_wrong_extension_never_start(self):
        self.path.write_bytes(b"prior evidence")
        with self.assertRaises(ValueError):
            self.recorder.start()
        self.assertEqual(self.path.read_bytes(), b"prior evidence")
        with self.assertRaises(ValueError):
            VideoRecorder("fixture-device", self.path.with_suffix(".mov")).start()
        self.popen.assert_not_called()

    def test_start_without_readiness_cleans_up_without_real_wait(self):
        self.process.stderr = io.StringIO("recording startup error\n")
        self.process.poll.return_value = 1
        self.process.wait.return_value = 1
        self.process.returncode = 1
        with self.assertRaises(ValueError):
            self.recorder.start()
        self.assertIsNone(self.recorder.started_at)
        self.assertEqual(self.event.waited, [10])
        self.process.send_signal.assert_not_called()
        self.process.wait.assert_called_once_with(timeout=15)
        self.assertTrue(self.process.stderr.closed)
        self.assertIsNone(self.recorder.process)

    def test_start_failure_does_not_retry_process(self):
        self.popen.side_effect = OSError("fixture process failure")
        with self.assertRaises((OSError, ValueError)):
            self.recorder.start()
        self.popen.assert_called_once()
        self.assertIsNone(self.recorder.process)

    def test_double_start_cannot_lose_active_process(self):
        self.recorder.start()
        with self.assertRaises(ValueError):
            self.recorder.start()
        self.popen.assert_called_once()

    def test_missing_and_tiny_recordings_are_not_usable(self):
        self.recorder.start()
        with self.assertRaisesRegex(ValueError, "usable"):
            self.recorder.stop()
        self.path.write_bytes(b"partial")
        with self.assertRaisesRegex(ValueError, "usable"):
            self.recorder.stop()

    def test_nonzero_recorder_exit_rejects_even_sized_partial_video(self):
        self.recorder.start()
        self.usable_video()
        self.process.wait.return_value = 1
        self.process.returncode = 1
        with self.assertRaises(ValueError):
            self.recorder.stop()
        self.assertTrue(self.stream.closed)
        self.assertIsNone(self.recorder.process)

    def test_stop_timeout_kills_and_reaps_with_bounded_waits(self):
        self.recorder.start()
        self.process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 15), 0]
        with self.assertRaises(ValueError):
            self.recorder.stop()
        self.process.send_signal.assert_called_once_with(signal.SIGINT)
        self.process.kill.assert_called_once()
        self.assertEqual(self.process.wait.call_args_list, [call(timeout=15), call(timeout=3)])
        self.assertTrue(self.stream.closed)
        self.assertIsNone(self.recorder.process)

    def test_failed_reap_is_bounded_and_still_cleans_up(self):
        self.recorder.start()
        self.process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 15), subprocess.TimeoutExpired("fixture", 3)]
        with self.assertRaises(ValueError):
            self.recorder.stop()
        self.assertEqual(self.process.wait.call_args_list, [call(timeout=15), call(timeout=3)])
        self.process.kill.assert_called_once()
        self.assertTrue(self.stream.closed)
        self.assertIsNone(self.recorder.process)

    def test_signal_error_attempts_one_kill_and_bounded_reap(self):
        self.recorder.start()
        self.process.send_signal.side_effect = OSError("fixture signal failure")
        with self.assertRaises(ValueError):
            self.recorder.stop()
        self.process.kill.assert_called_once()
        self.process.wait.assert_called_once_with(timeout=3)
        self.assertTrue(self.stream.closed)
        self.assertIsNone(self.recorder.process)
        with self.assertRaises(ValueError):
            self.recorder.stop()
        self.process.kill.assert_called_once()
        self.process.send_signal.assert_called_once()

    def test_sized_nonvideo_file_is_not_usable(self):
        self.recorder.start()
        self.path.write_bytes(b"not video" * 30)
        with self.assertRaisesRegex(ValueError, "usable"):
            self.recorder.stop()


if __name__ == "__main__":
    unittest.main()
