"""Offline tests for the execution/evidence boundary, independent of AXe."""

import copy
import io
import json
import math
import unittest
from unittest.mock import Mock, patch

from jev_ios.device import DeviceError, StaleObservation, normalize_snapshot
from jev_ios.runner import Runner


class FakeSnapshot:
    def __init__(self, screen_hash="screen-a", labels=(), taps=None, types=None):
        self.screen_hash = screen_hash
        self.labels = list(labels)
        self.taps = taps or {}
        self.types = types or {}
        self.elements = [{"id": key, "label": label} for key, label in {**self.taps, **self.types}.items()]

    def targets(self, kind):
        return dict(self.taps if kind == "tap" else self.types)

    def model_state(self):
        return {"labels": self.labels, "elements": self.elements}


class FakeDevice:
    def __init__(self, snapshots, effects=()):
        self.snapshots = list(snapshots)
        self.effects = list(effects)
        self.observe_count = 0
        self.execute_calls = []

    def observe(self):
        index = min(self.observe_count, len(self.snapshots) - 1)
        self.observe_count += 1
        return self.snapshots[index]

    def execute(self, snapshot, decision, text_values):
        self.execute_calls.append((snapshot.screen_hash, copy.deepcopy(decision), dict(text_values)))
        if self.effects:
            effect = self.effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            return effect
        return {key: decision[key] for key in ("operation", "target") if key in decision}


class FakeModel:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = []

    def decide(self, state, actions, tap_targets, type_targets, text_values):
        self.calls.append(copy.deepcopy((state, actions, tap_targets, type_targets, text_values)))
        if not self.decisions:
            raise AssertionError("Unexpected extra model call")
        return self.decisions.pop(0)


def decision(operation, target=None, probability=0.99, **extra):
    result = {"operation": operation, "probability": probability, "model_ms": 4, "usage": {"inputTokens": 10}}
    if target is not None:
        result["target"] = target
    return {**result, **extra}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch("jev_ios.runner.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def run_fixture(self, snapshots, decisions=(), effects=(), **options):
        device = FakeDevice(snapshots, effects)
        model = FakeModel(decisions)
        events = []
        result = Runner(device, model, emit=events.append, **options).run("Reach Finished", ["Finished"])
        return result, device, model, events

    def test_already_visible_expectation_needs_no_model_call(self):
        result, device, model, _ = self.run_fixture([FakeSnapshot(labels=["Finished"])])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["actions_executed"], 0)
        self.assertEqual(model.calls, [])
        self.assertEqual(device.execute_calls, [])

    def test_done_claim_does_not_prove_success(self):
        result, device, _, _ = self.run_fixture([FakeSnapshot(labels=["Not Finished"])], [decision("DONE")])
        self.assertEqual((result["status"], result["reason"]), ("unverified", "model_done_without_expected_labels"))
        self.assertEqual(result["matched_labels"], [])
        self.assertEqual(device.observe_count, 2)
        self.assertEqual(device.execute_calls, [])

    def test_done_gets_fresh_local_verification(self):
        result, device, _, _ = self.run_fixture(
            [FakeSnapshot(), FakeSnapshot("screen-b", labels=["Finished"])], [decision("DONE")]
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(device.observe_count, 2)

    def test_last_bounded_action_can_still_verify(self):
        result, device, model, _ = self.run_fixture(
            [FakeSnapshot(taps={"1": "Continue"}), FakeSnapshot("screen-b", labels=["Finished"])],
            [decision("TAP", "1")], max_steps=1,
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["actions_executed"], 1)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(device.observe_count, 2)

    def test_model_calls_and_actions_stay_within_step_limit(self):
        result, device, model, _ = self.run_fixture(
            [FakeSnapshot(taps={"1": "Continue"})],
            [decision("TAP", "1"), decision("TAP", "1")], max_steps=2,
        )
        self.assertEqual((result["status"], result["reason"]), ("stopped", "step_limit"))
        self.assertEqual(result["actions_executed"], 2)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(device.execute_calls), 2)
        self.assertEqual(device.observe_count, 3)

    def test_allow_label_restricts_exact_tap_candidates(self):
        result, device, model, _ = self.run_fixture(
            [FakeSnapshot(taps={"1": "Continue", "2": "Continue purchase", "3": "Cancel"})],
            [decision("TAP", "2")], allow_labels=["Continue"],
        )
        self.assertEqual(model.calls[0][2], {"1": "Continue"})
        self.assertEqual(result["reason"], "unoffered_target")
        self.assertEqual(device.execute_calls, [])

    def test_unoffered_scroll_is_blocked(self):
        result, device, _, _ = self.run_fixture([FakeSnapshot()], [decision("SCROLL_DOWN")])
        self.assertEqual(result["reason"], "unoffered_operation")
        self.assertEqual(device.execute_calls, [])

    def test_type_requires_explicit_caller_strings(self):
        result, device, model, _ = self.run_fixture(
            [FakeSnapshot(types={"1": "Query"})], [decision("TYPE_TEXT", "1", text_key="invented")]
        )
        self.assertNotIn("TYPE_TEXT", model.calls[0][1])
        self.assertEqual(model.calls[0][3], {})
        self.assertEqual(result["reason"], "unoffered_operation")
        self.assertEqual(device.execute_calls, [])

    def test_unreported_confidence_needs_explicit_zero_cutoff(self):
        for cutoff, expected in [(0, "verified"), (.55, "blocked")]:
            with self.subTest(cutoff=cutoff):
                result, device, _, _ = self.run_fixture(
                    [FakeSnapshot(taps={"1":"Continue"}), FakeSnapshot("screen-b", labels=["Finished"])],
                    [decision("TAP", "1", probability=None, confidence_kind="not_reported")],
                    max_steps=1, min_probability=cutoff)
                self.assertEqual(result["status"], expected)
                self.assertEqual(len(device.execute_calls), 1 if cutoff == 0 else 0)

    def test_missing_confidence_without_marker_is_invalid_even_at_zero_cutoff(self):
        result, device, _, _ = self.run_fixture([FakeSnapshot(taps={"1":"Continue"})],
            [decision("TAP", "1", probability=None)], min_probability=0)
        self.assertEqual(result["reason"], "invalid_confidence")
        self.assertEqual(device.execute_calls, [])

    def test_low_probability_blocks_before_device_input(self):
        result, device, _, _ = self.run_fixture(
            [FakeSnapshot(taps={"1": "Continue"})], [decision("TAP", "1", probability=0.2)]
        )
        self.assertEqual(result["reason"], "low_confidence")
        self.assertEqual(device.execute_calls, [])

    def test_invalid_adapter_probabilities_cannot_execute(self):
        for probability in (math.nan, math.inf, -0.1, 1.1, True, "0.99"):
            with self.subTest(probability=probability):
                result, device, _, _ = self.run_fixture(
                    [FakeSnapshot(taps={"1": "Continue"})], [decision("TAP", "1", probability=probability)]
                )
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(device.execute_calls, [])

    def test_stale_decision_is_discarded_before_next_prediction(self):
        result, device, model, events = self.run_fixture(
            [FakeSnapshot(taps={"1": "Continue"}), FakeSnapshot("screen-b", taps={"2": "Continue"}),
             FakeSnapshot("screen-c", labels=["Finished"])],
            [decision("TAP", "1"), decision("TAP", "2")],
            effects=[StaleObservation("stale")], max_steps=2,
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["actions_executed"], 1)
        self.assertEqual([call[1]["target"] for call in device.execute_calls], ["1", "2"])
        self.assertEqual(model.calls[1][0]["recent_actions"][-1]["outcome"], "stale_not_executed")
        self.assertEqual(len([event for event in events if event["type"] == "action"]), 1)

    def test_uncertain_device_failure_is_not_replayed(self):
        result, device, model, events = self.run_fixture(
            [FakeSnapshot(taps={"1": "Continue"})], [decision("TAP", "1")],
            effects=[DeviceError("action outcome unknown")],
        )
        self.assertEqual((result["status"], result["reason"]), ("uncertain", "device_action_failed_no_replay"))
        self.assertEqual(len(device.execute_calls), 1)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(result["actions_executed"], 0)
        self.assertEqual([event for event in events if event["type"] == "action"], [])

    def test_same_scroll_across_different_screens_is_progress(self):
        result, device, _, _ = self.run_fixture(
            [FakeSnapshot("screen-a"), FakeSnapshot("screen-b"), FakeSnapshot("screen-c"),
             FakeSnapshot("screen-d", labels=["Finished"])],
            [decision("SCROLL_DOWN") for _ in range(3)], allow_scroll=True, max_steps=3,
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(device.execute_calls), 3)

    def test_three_no_progress_actions_stop_after_fresh_verification(self):
        result, device, model, _ = self.run_fixture(
            [FakeSnapshot("unchanged")], [decision("SCROLL_DOWN") for _ in range(3)],
            allow_scroll=True, max_steps=10,
        )
        self.assertEqual(result["reason"], "repeated_action_without_progress")
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(len(device.execute_calls), 3)
        self.assertGreaterEqual(device.observe_count, 4)

    def test_third_same_action_can_complete_goal(self):
        result, _, _, _ = self.run_fixture(
            [FakeSnapshot("unchanged"), FakeSnapshot("unchanged"), FakeSnapshot("unchanged"),
             FakeSnapshot("completed", labels=["Finished"])],
            [decision("SCROLL_DOWN") for _ in range(3)], allow_scroll=True, max_steps=10,
        )
        self.assertEqual(result["status"], "verified")


class CliBoundaryTests(unittest.TestCase):
    def test_secure_descendant_strings_do_not_leave_device_boundary(self):
        frame = {"x": 0, "y": 0, "width": 100, "height": 100}
        root = {"type": "Application", "pid": 42, "frame": frame, "children": [
            {"type": "SecureTextField", "AXLabel": "Password", "frame": frame, "children": [
                {"type": "StaticText", "AXLabel": "DUMMY_SECRET_ONLY", "AXUniqueId": "DUMMY_SECRET_ID", "frame": frame}
            ]}
        ]}
        snapshot = normalize_snapshot(root, 42)
        for output in (snapshot.model_state(), snapshot.as_dict(), snapshot.labels):
            serialized = json.dumps(output)
            self.assertNotIn("DUMMY_SECRET_ONLY", serialized)
            self.assertNotIn("DUMMY_SECRET_ID", serialized)

    def test_price_bound_is_checked_without_making_inference_calls(self):
        from jev_ios.cli import pricing_bound
        metadata = {"data": [{"id": "typesafe-ai/jev", "pricing": {"input": "0.000000042", "output": "0"}, "context_window": 32000}]}
        with patch("jev_ios.cli.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(metadata).encode())):
            bound = pricing_bound(1, 0, 0.1)
        self.assertAlmostEqual(bound["reserved_usd"], 0.002688)
        self.assertEqual(bound["max_calls"], 1)
        with patch("jev_ios.cli.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(metadata).encode())):
            with self.assertRaisesRegex(ValueError, "exceeds --budget-usd"):
                pricing_bound(30, 1, 0.1)

    def test_token_provider_error_never_contains_stdout_or_stderr(self):
        from jev_ios.cli import temporary_vercel_token
        result = Mock(returncode=1, stdout="secret-access-token", stderr="secret-provider-details")
        with patch("jev_ios.cli.subprocess.run", return_value=result):
            with self.assertRaises(ValueError) as error:
                temporary_vercel_token("fixture-project")
        self.assertNotIn("secret", str(error.exception))

    def test_malformed_token_response_is_sanitized(self):
        from jev_ios.cli import temporary_vercel_token
        result = Mock(returncode=0, stdout='{"token":42,"details":"secret-provider-details"}')
        with patch("jev_ios.cli.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ValueError, "unrecognized token response") as error:
                temporary_vercel_token("fixture-project")
        self.assertNotIn("secret", str(error.exception))

    def test_temporary_token_is_returned_only_in_memory(self):
        from jev_ios.cli import temporary_vercel_token
        result = Mock(returncode=0, stdout='{"token":"test-temporary-token"}')
        with patch("jev_ios.cli.subprocess.run", return_value=result):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(temporary_vercel_token("fixture-project"), "test-temporary-token")
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
