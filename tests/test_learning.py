import unittest
from jev_ios.learning import learn_app


class Snapshot:
    def __init__(self, h, label):
        self.screen_hash = h
        self.labels = [label]
        self.elements = [{"kind":"Button","label":label,"value":"","enabled":True}]
    def targets(self, kind):
        return {"1": self.labels[0]} if kind == "tap" else {}
    def model_state(self):
        return {"screen_hash": self.screen_hash, "elements": self.elements, "tap_targets": self.targets("tap"), "type_targets": {}}


class Device:
    def __init__(self):
        self.i = 0
    def observe(self):
        return Snapshot("a" if self.i == 0 else "b", "Explore" if self.i == 0 else "Done")
    def execute(self, snapshot, decision, text_values):
        self.i = 1
        return {"operation":"TAP"}


class Model:
    def __init__(self):
        self.calls = 0
    def decide(self, state, actions, tap, type_targets, text_values):
        self.calls += 1
        if self.calls == 1:
            return {"operation":"TAP","target":"1","probability":0.9}
        return {"operation":"DONE","probability":0.9}


class LearningTests(unittest.TestCase):
    def test_learning_records_observed_transition(self):
        result = learn_app(Device(), Model(), goal="learn", max_steps=3)
        self.assertEqual(result["schema"], "jev-ios/app-map/v1")
        self.assertEqual(len(result["screens"]), 2)
        self.assertEqual(result["transitions"][0]["from"], "a")
        self.assertEqual(result["transitions"][0]["to"], "b")


if __name__ == "__main__":
    unittest.main()
