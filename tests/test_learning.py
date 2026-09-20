import math
import unittest
from jev_ios.device import DeviceError, Snapshot, StaleObservation
from jev_ios.learning import learn_app
from jev_ios.model import ModelError


def snap(which="a", label="Explore", kind="Button"):
    return Snapshot([{"id": "1", "kind": kind, "label": label, "value": "private value",
                      "enabled": True, "secure": False}], [label], which, 123, {}, 1.0)


class Device:
    def __init__(self, label="Explore", error=None): self.i, self.actions, self.label, self.error = 0, 0, label, error
    def observe(self): return snap("a" if self.i == 0 else "b", self.label if self.i == 0 else "Done")
    def execute(self, snapshot, decision, text_values):
        self.actions += 1
        if self.error: raise self.error
        self.i = 1
        return {"operation": "TAP", "before_hash": "a", "after_hash": "b"}


class Model:
    def __init__(self, decision=None, error=None): self.calls, self.decision, self.error = 0, decision, error
    def decide(self, state, actions, tap, type_targets, text_values):
        self.calls += 1
        if self.error: raise self.error
        return self.decision or {"operation": "TAP", "target": "1", "probability": .9}


class LearningTests(unittest.TestCase):
    def test_learning_records_observed_transition(self):
        result = learn_app(Device(), Model(), goal="learn", max_steps=3, allow_labels=["Explore"])
        self.assertEqual(result["schema"], "jev-ios/app-map/v2")
        self.assertEqual(len(result["screens"]), 2)
        ids = {s["id"] for s in result["screens"]}
        self.assertIn(result["transitions"][0]["from"], ids)
        self.assertIn(result["transitions"][0]["to"], ids)
    def test_last_bounded_destination_is_recorded(self):
        result = learn_app(Device(), Model(), goal="learn", max_steps=1, allow_labels=["Explore"])
        self.assertEqual(len(result["screens"]), 2)
    def test_default_is_observe_only_not_deny_list(self):
        for label in ("Explore", "Place order", "Transfer", "Post", "Borrar", "★"):
            device, model = Device(label), Model()
            result = learn_app(device, model, goal="learn")
            self.assertEqual((device.actions, model.calls), (0, 0))
            self.assertEqual(result["reason"], "observe_only_no_approved_navigation")
    def test_low_and_invalid_confidence_cannot_dispatch(self):
        for value in (0.1, -1, 2, float("nan"), float("inf"), True, None):
            device = Device()
            result = learn_app(device, Model({"operation": "TAP", "target": "1", "probability": value}),
                               goal="learn", allow_labels=["Explore"])
            self.assertEqual(device.actions, 0)
            self.assertEqual(result["status"], "blocked")
    def test_model_cannot_widen_targets_or_operations(self):
        for decision in ({"operation": "TYPE_TEXT", "target": "1", "probability": 1},
                         {"operation": "TAP", "target": "999", "probability": 1}):
            device = Device()
            learn_app(device, Model(decision), goal="learn", allow_labels=["Explore"])
            self.assertEqual(device.actions, 0)
    def test_uncertain_input_is_not_replayed(self):
        device = Device(error=DeviceError("uncertain"))
        result = learn_app(device, Model(), goal="learn", allow_labels=["Explore"])
        self.assertEqual(device.actions, 1)
        self.assertEqual(result["status"], "uncertain")
    def test_model_failure_keeps_partial_map(self):
        result = learn_app(Device(), Model(error=ModelError("API failure")), goal="learn", allow_labels=["Explore"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["screens"]), 1)
    def test_map_does_not_store_control_values(self):
        result = learn_app(Device(), Model(), goal="learn")
        self.assertNotIn("private value", str(result))
    def test_switches_and_fields_cannot_be_exploration_targets(self):
        for kind in ("Switch", "TextField", "SearchField"):
            device = Device()
            device.observe = lambda: snap(kind=kind)
            model = Model()
            learn_app(device, model, goal="learn", allow_labels=["Explore"])
            self.assertEqual(model.calls, 0)
    def test_invalid_limits_fail_before_observing(self):
        for value in (0, -1, 21, True):
            with self.assertRaises(ValueError): learn_app(None, None, goal="learn", max_steps=value)
    def test_string_is_not_a_label_sequence(self):
        with self.assertRaises(ValueError): learn_app(None, None, goal="learn", allow_labels="Explore")
    def test_duplicate_labels_are_not_automatically_authorized(self):
        device = Device(); state = snap()
        state.elements.append(dict(state.elements[0], id="2"))
        device.observe = lambda: state
        model = Model()
        learn_app(device, model, goal="learn", allow_labels=["Explore"])
        self.assertEqual(model.calls, 0)


if __name__ == "__main__": unittest.main()
