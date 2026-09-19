import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jev_ios.comparison import (
    _cost_stats, _ready_snapshot, run_comparison, semantic_state_hash, summarize_comparison,
)
from jev_ios.device import DeviceError
from jev_ios.model import ModelError
from jev_ios.runner import Runner
from jev_ios.scenario import Scenario


class FakeSnapshot:
    def __init__(self, pid=1, completed=False, label="Home"):
        self.pid, self.screen_hash = pid, f"{pid}:{completed}:{label}"
        self.labels = ["Finished"] if completed else [label, "Continue"]
        self.frame = {"x": 0, "y": 0, "width": 100, "height": 200}
        self.elements = [{"id": "1", "kind": "Button", "label": self.labels[-1], "enabled": True,
                          "value": "", "frame": self.frame}]

    def targets(self, kind):
        return {"1": "Continue"} if kind == "tap" else {}

    def model_state(self):
        return {"elements": self.elements, "screen_hash": self.screen_hash}


class FakeDevice:
    instances, plans = [], []

    def __init__(self, udid, bundle_id):
        self.pid, self.completed = len(self.instances) + 1, False
        self.commands, self.launches = [], 0
        self.observations = 0
        self.plan = self.plans.pop(0) if self.plans else None
        self.instances.append(self)

    def _run(self, args):
        self.commands.append(args)
        if isinstance(self.plan, BaseException):
            raise self.plan
        return f"org.example.fixture: {self.pid}"

    def launch(self):
        self.launches += 1

    def observe(self):
        self.observations += 1
        label = "Changed after setup" if self.plan == "change_after_setup" and self.observations > 2 else "Home"
        return FakeSnapshot(self.pid, self.completed, label=label)

    def execute(self, snapshot, decision, text_values):
        self.completed = True
        return {"operation": "TAP", "target": "1"}


class FakeModel:
    instances, plans = [], []

    def __init__(self, **kwargs):
        self.calls, self.kwargs, self.closed = 0, kwargs, False
        self.plan = self.plans.pop(0) if self.plans else None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def decide(self, *args):
        self.calls += 1
        if isinstance(self.plan, BaseException):
            raise self.plan
        return {"operation": self.plan or "TAP", "target": "1", "probability": 0.8,
                "model_ms": 100.0, "usage": {"inputTokens": 100, "outputTokens": 10,
                                            "cacheReadInputTokens": 20}}


class FakeRecorder:
    instances, fail_stop = [], False

    def __init__(self, udid, path):
        self.path, self.started_at = Path(path), 0
        self.stopped = False
        self.instances.append(self)

    def start(self):
        self.path.write_bytes(b"fixture")

    def stop(self):
        self.stopped = True
        if isinstance(self.fail_stop, BaseException):
            raise self.fail_stop
        if self.fail_stop:
            raise ValueError("private recorder response")


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "cohort"
        self.scenario = Scenario(name="fixture", goal="Finish", expect_labels=["Finished"], max_steps=2,
                                 allow_labels=["Continue"], text_values={"fixture": "Hello"})
        self.pricing = {key: {"input_rate_per_million": 1, "output_rate_per_million": 2,
                             "cache_read_rate_per_million": 0.5} for key in ("jev", "baseline")}
        FakeDevice.instances, FakeDevice.plans = [], []
        FakeModel.instances, FakeModel.plans = [], []
        FakeRecorder.instances, FakeRecorder.fail_stop = [], False
        for mocked in (patch("jev_ios.comparison.AxeDevice", FakeDevice),
                       patch("jev_ios.comparison.JevModel", FakeModel),
                       patch("jev_ios.baseline.ChatCompletionModel", FakeModel),
                       patch("jev_ios.comparison.VideoRecorder", FakeRecorder),
                       patch("jev_ios.comparison.time.perf_counter", side_effect=itertools.count(step=0.01).__next__),
                       patch("jev_ios.comparison.time.sleep")):
            mocked.start()
            self.addCleanup(mocked.stop)

    def run_fixture(self, **options):
        defaults = dict(scenario=self.scenario, udid="fixture-device", bundle_id="org.example.fixture",
                        output_dir=self.output, api_key="private-fixture-token", pricing=self.pricing,
                        start_labels=["Home"], record_video=False)
        return run_comparison(**(defaults | options))

    def test_six_attempts_alternate_and_reset_without_clearing_data(self):
        with patch("jev_ios.comparison.Runner", wraps=Runner) as factory:
            result = self.run_fixture()
        self.assertEqual([r["backend"] for r in result["runs"]], ["jev", "baseline", "baseline", "jev", "jev", "baseline"])
        self.assertEqual([r["position"] for r in result["runs"]], [1, 2, 1, 2, 1, 2])
        self.assertEqual({r["status"] for r in result["runs"]}, {"verified"})
        self.assertEqual(len({r["initial_state_hash"] for r in result["runs"]}), 1)
        self.assertEqual(len(FakeDevice.instances), 6)
        for device in FakeDevice.instances:
            self.assertEqual(device.commands, [["xcrun", "simctl", "launch", "--terminate-running-process", "fixture-device", "org.example.fixture"]])
            self.assertEqual(device.launches, 1)
        for invocation in factory.call_args_list:
            self.assertEqual(invocation.kwargs["min_probability"], 0)
            self.assertEqual(invocation.kwargs["max_steps"], 2)
            self.assertEqual(invocation.kwargs["allow_labels"], ("Continue",))
            self.assertEqual(invocation.kwargs["text_values"], {"fixture": "Hello"})
        for model in FakeModel.instances:
            self.assertTrue(model.closed)
            self.assertEqual(model.kwargs["options"].timeout_seconds, 10)
            self.assertEqual(model.kwargs["options"].max_calls, 2)
        self.assertEqual(result["summary"]["paired_verified_count"], 3)
        self.assertTrue(result["summary"]["initial_state_consistent"])
        self.assertEqual(result["summary"]["initial_state_hashes_count"], 1)
        self.assertNotIn("private-fixture-token", (self.output / "comparison.json").read_text())

    def test_failed_request_stays_in_cohort_with_unknown_cost(self):
        FakeModel.plans = [ModelError("Provider request failed safely")]
        result = self.run_fixture(pairs=1)
        first = result["runs"][0]
        self.assertEqual(first["status"], "error")
        self.assertEqual(first["model_calls"], 1)
        self.assertEqual(first["model_ms"], [])
        self.assertIsNone(first["estimated_cost_usd"])
        self.assertTrue(first["timing_valid"])
        self.assertEqual(len(result["runs"]), 2)
        self.assertTrue(result["summary"]["pairs"][0]["comparable"])
        self.assertIsNone(result["summary"]["pairs"][0]["baseline_over_jev"])
        self.assertEqual(result["summary"]["backends"]["jev"]["unknown_cost_runs"], 1)
        self.assertEqual(result["summary"]["backends"]["jev"]["requests_without_timing"], 1)

    def test_setup_failure_invalidates_pair_and_does_not_call_model(self):
        FakeDevice.plans = [DeviceError("App reset failed safely")]
        result = self.run_fixture(pairs=1)
        first = result["runs"][0]
        self.assertEqual(first["setup_status"], "failed")
        self.assertFalse(first["timing_valid"])
        self.assertEqual(first["model_calls"], 0)
        self.assertEqual(first["estimated_cost_usd"], 0)
        self.assertIsNone(first["elapsed_ms"])
        self.assertFalse(result["summary"]["pairs"][0]["comparable"])
        self.assertEqual(len(FakeModel.instances), 1)

    def test_actual_first_runner_snapshot_must_match_setup_before_inference(self):
        FakeDevice.plans = ["change_after_setup"]
        result = self.run_fixture(pairs=1)
        first = result["runs"][0]
        self.assertEqual(first["reason"], "initial_state_changed")
        self.assertEqual(first["setup_status"], "failed")
        self.assertFalse(first["timing_valid"])
        self.assertNotEqual(first["initial_state_hash"], first["setup_state_hash"])
        self.assertEqual(FakeModel.instances[0].calls, 0)
        self.assertFalse(FakeDevice.instances[0].completed)
        self.assertIsNone(result["summary"]["pairs"][0]["baseline_over_jev"])

    def test_unknown_error_detail_is_not_persisted(self):
        FakeModel.plans = [RuntimeError("private-token-in-error")]
        self.run_fixture(pairs=1)
        files = "".join(path.read_text() for path in self.output.iterdir())
        self.assertNotIn("private-token-in-error", files)
        self.assertIn("RuntimeError", files)

    def test_manifest_is_durable_before_next_attempt(self):
        persisted = []
        def event(event):
            if event["type"] == "attempt_start":
                persisted.append(len(json.loads((self.output / "comparison.json").read_text())["runs"]))
        self.run_fixture(pairs=1, emit=event)
        self.assertEqual(persisted, [0, 1])
        manifest = self.output / "comparison.json"
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in self.output.glob("*.jsonl")))

    def test_interrupt_keeps_attempt_and_stops_scheduling(self):
        FakeModel.plans = [KeyboardInterrupt()]
        result = self.run_fixture()
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(result["runs"][0]["status"], "interrupted")
        self.assertEqual(len(json.loads((self.output / "comparison.json").read_text())["runs"]), 1)
        self.assertEqual(len(FakeDevice.instances), 1)

    def test_recordings_are_symmetric_and_original_paths_are_relative(self):
        result = self.run_fixture(pairs=1, record_video=True)
        self.assertEqual(len(FakeRecorder.instances), 2)
        self.assertTrue(all(recorder.stopped for recorder in FakeRecorder.instances))
        self.assertTrue(all(run["video"].endswith(".mp4") and not Path(run["video"]).is_absolute() for run in result["runs"]))

    def test_recording_finalization_failure_preserves_runner_result(self):
        FakeRecorder.fail_stop = True
        result = self.run_fixture(pairs=1, record_video=True)
        for run in result["runs"]:
            self.assertEqual(run["status"], "verified")
            self.assertIsNone(run["video"])
            self.assertIn("artifact_error", run)
        self.assertNotIn("private recorder response", (self.output / "comparison.json").read_text())

    def test_teardown_interrupt_preserves_completed_attempt_and_stops_schedule(self):
        FakeRecorder.fail_stop = KeyboardInterrupt()
        result = self.run_fixture(record_video=True)
        self.assertEqual(len(result["runs"]), 1)
        first = result["runs"][0]
        self.assertEqual(first["status"], "verified")
        self.assertTrue(first["timing_valid"])
        self.assertIsNone(first["video"])
        self.assertEqual(first["artifact_error"], "Recording finalization interrupted; video omitted")
        self.assertEqual(len(FakeDevice.instances), 1)
        self.assertEqual(len(json.loads((self.output / "comparison.json").read_text())["runs"]), 1)
        trace = [json.loads(line) for line in (self.output / first["trace"]).read_text().splitlines()]
        self.assertEqual([event["status"] for event in trace if event["type"] == "result"], ["verified"])

    def test_existing_output_directory_never_replaced_or_runs_started(self):
        self.output.mkdir()
        sentinel = self.output / "evidence"
        sentinel.write_text("prior evidence")
        with self.assertRaises(FileExistsError):
            self.run_fixture()
        self.assertEqual(sentinel.read_text(), "prior evidence")
        self.assertEqual(FakeDevice.instances, [])

    def test_invalid_settings_rejected_before_device_access(self):
        for options in ({"pairs": 0}, {"pairs": True}, {"pairs": 6}, {"start_labels": []},
                        {"start_labels": [""]}, {"record_video": 1}, {"pricing": {}},
                        {"baseline_model": ""}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_fixture(**options)
        self.assertFalse(self.output.exists())
        self.assertEqual(FakeDevice.instances, [])


class SummaryTests(unittest.TestCase):
    def run_row(self, backend, elapsed, **extras):
        return {"id": backend, "pair": 1, "backend": backend, "status": "verified",
                "elapsed_ms": elapsed, "timing_valid": True, "setup_status": "ready",
                "initial_state_hash": "same", "model_ms": [100, 200], "estimated_cost_usd": 0.01,
                "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0, **extras}

    def test_only_matched_verified_pairs_produce_speed_ratios(self):
        rows = [self.run_row("jev", 1000), self.run_row("baseline", 2000)]
        summary = summarize_comparison({"runs": rows})
        self.assertEqual(summary["paired_verified_count"], 1)
        self.assertEqual(summary["median_paired_speedup"], 2)
        for changed in ({"initial_state_hash": "different"}, {"setup_status": "failed"},
                        {"timing_valid": False}, {"status": "error"}, {"elapsed_ms": 0}):
            with self.subTest(changed=changed):
                altered = [rows[0], {**rows[1], **changed}]
                self.assertIsNone(summarize_comparison({"runs": altered})["median_paired_speedup"])

    def test_failures_remain_in_denominator_and_unknown_cost_is_explicit(self):
        rows = [self.run_row("jev", 1000), self.run_row("jev", 10, status="error", estimated_cost_usd=None, pair=2)]
        summary = summarize_comparison({"runs": rows})["backends"]["jev"]
        self.assertEqual((summary["attempted"], summary["verified"], summary["failed"]), (2, 1, 1))
        self.assertEqual(summary["median_verified_elapsed_ms"], 1000)
        self.assertIsNone(summary["estimated_cost_usd"])
        self.assertEqual(summary["known_estimated_cost_usd"], 0.01)
        self.assertEqual(summary["unknown_cost_runs"], 1)

    def test_duplicate_backend_cannot_form_a_valid_pair(self):
        rows = [self.run_row("jev", 1000), self.run_row("baseline", 2000), self.run_row("jev", 10)]
        self.assertIsNone(summarize_comparison({"runs": rows})["median_paired_speedup"])

    def test_changed_starting_state_invalidates_cohort_time_ratios(self):
        rows = [self.run_row("jev", 1000), self.run_row("baseline", 2000),
                self.run_row("jev", 1000, pair=2, initial_state_hash="other"),
                self.run_row("baseline", 2000, pair=2, initial_state_hash="other")]
        summary = summarize_comparison({"runs": rows})
        self.assertFalse(summary["initial_state_consistent"])
        self.assertEqual(summary["initial_state_hashes_count"], 2)
        self.assertEqual(summary["paired_verified_count"], 0)
        self.assertEqual(summary["pairs"][0]["reason"], "cohort_initial_state_mismatch")

    def test_usage_estimate_accounts_for_cache_and_unknown_requests(self):
        usage = [{"inputTokens": 100, "outputTokens": 20, "cacheReadInputTokens": 40}]
        pricing = {"input_rate_per_million": 2, "output_rate_per_million": 4, "cache_read_rate_per_million": 0.5}
        result = _cost_stats(usage, 1, pricing)
        self.assertAlmostEqual(result["estimated_cost_usd"], 0.00022)
        self.assertEqual((result["input_tokens"], result["output_tokens"], result["cached_input_tokens"]), (100, 20, 40))
        self.assertIsNone(_cost_stats(usage, 2, pricing)["estimated_cost_usd"])
        self.assertIsNone(_cost_stats(usage, 1, {"input_rate_per_million": 2, "output_rate_per_million": 4})["estimated_cost_usd"])
        self.assertIsNone(_cost_stats([{"inputTokens": 10}], 1, pricing)["estimated_cost_usd"])

    def test_start_change_rejected_before_inference_invalidates_other_pairs(self):
        rows = [self.run_row("jev", 1000), self.run_row("baseline", 2000),
                self.run_row("jev", None, pair=2, status="error", setup_status="failed",
                             timing_valid=False, reason="initial_state_changed")]
        summary = summarize_comparison({"runs": rows})
        self.assertFalse(summary["initial_state_consistent"])
        self.assertEqual(summary["paired_verified_count"], 0)
        self.assertIsNone(summary["median_paired_speedup"])

    def test_semantic_hash_excludes_pid_but_keeps_control_geometry_and_labels(self):
        one, two = FakeSnapshot(1), FakeSnapshot(2)
        self.assertNotEqual(one.screen_hash, two.screen_hash)
        self.assertEqual(semantic_state_hash(one), semantic_state_hash(two))
        two.elements[0]["label"] = "Different"
        self.assertNotEqual(semantic_state_hash(one), semantic_state_hash(two))
        two = copy.deepcopy(one)
        two.elements[0]["frame"]["height"] += 1
        self.assertNotEqual(semantic_state_hash(one), semantic_state_hash(two))

    def test_start_readiness_requires_two_same_process_observations(self):
        device = unittest.mock.Mock()
        device.observe.side_effect = [FakeSnapshot(1), FakeSnapshot(2), FakeSnapshot(2)]
        with patch("jev_ios.comparison.time.sleep"):
            observed = _ready_snapshot(device, ["Home"])
        self.assertEqual(observed.pid, 2)
        self.assertEqual(device.observe.call_count, 3)

    def test_start_readiness_expires_with_missing_expected_labels(self):
        device = unittest.mock.Mock()
        device.observe.return_value = FakeSnapshot()
        with patch("jev_ios.comparison.time.monotonic", side_effect=[0, 0, 0, 11]), patch("jev_ios.comparison.time.sleep"):
            with self.assertRaises(DeviceError):
                _ready_snapshot(device, ["Other app"])


if __name__ == "__main__":
    unittest.main()
