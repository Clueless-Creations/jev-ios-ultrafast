from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

from jev_ios.scenario import MAX_SCENARIO_BYTES, SCENARIO_SCHEMA, Scenario, ScenarioError, load_scenario


def payload(**changes):
    return {"schema": SCENARIO_SCHEMA, "name": "Open settings", "goal": "Open the settings screen",
            "expect_labels": ["Settings"], **changes}


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "scenario.json"

    def load(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return load_scenario(self.path)

    def test_defaults_and_exact_labels_are_preserved(self):
        scenario = self.load(payload(expect_labels=["Settings", " Exact label "]))
        self.assertEqual(scenario.expect_labels, ("Settings", " Exact label "))
        self.assertEqual(scenario.schema, SCENARIO_SCHEMA)
        self.assertEqual(scenario.to_runner_kwargs(), {"max_steps": 12, "min_probability": 0.55,
                         "allow_labels": (), "allow_scroll": False, "text_values": {}})

    def test_options_are_copied_and_immutable(self):
        texts = {"name": "Fixture person"}
        labels = ["Continue"]
        scenario = Scenario("Fixture", "Enter the fixture name", labels, text_values=texts)
        texts["name"] = "Changed"
        labels.append("Changed")
        self.assertEqual(scenario.text_values["name"], "Fixture person")
        self.assertEqual(scenario.expect_labels, ("Continue",))
        with self.assertRaises(TypeError):
            scenario.text_values["name"] = "Changed"
        with self.assertRaises(FrozenInstanceError):
            scenario.goal = "Changed"
        options = scenario.to_runner_kwargs()
        options["text_values"]["name"] = "Changed"
        self.assertEqual(scenario.to_runner_kwargs()["text_values"]["name"], "Fixture person")

    def test_complete_scenario_maps_only_runner_options(self):
        scenario = self.load(payload(allow_labels=["Continue", "Settings"], allow_scroll=True,
                                     text_values={"query": "fixture"}, max_steps=30, min_probability=1))
        self.assertEqual(scenario.to_runner_kwargs(), {"allow_labels": ("Continue", "Settings"),
                         "allow_scroll": True, "text_values": {"query": "fixture"},
                         "max_steps": 30, "min_probability": 1})

    def test_unknown_host_and_provider_fields_are_rejected(self):
        for field in ("udid", "api_key", "provider", "bundle_id", "plugin", "typo"):
            with self.subTest(field=field), self.assertRaisesRegex(ScenarioError, "unsupported fields"):
                self.load(payload(**{field: "fixture"}))

    def test_missing_and_wrong_schema_rejected(self):
        for field in ("schema", "name", "goal", "expect_labels"):
            data = payload()
            del data[field]
            with self.subTest(field=field), self.assertRaises(ScenarioError):
                self.load(data)
        with self.assertRaises(ScenarioError):
            self.load(payload(schema="jev-ios/scenario/v2"))

    def test_duplicate_keys_rejected_at_every_depth(self):
        for body in ('{"schema":"jev-ios/scenario/v1","schema":"jev-ios/scenario/v1"}',
                     '{"schema":"jev-ios/scenario/v1","name":"Fixture","goal":"Find fixture","expect_labels":["Found"],"text_values":{"name":"one","name":"two"}}'):
            self.path.write_text(body, encoding="utf-8")
            with self.assertRaisesRegex(ScenarioError, "duplicate"):
                load_scenario(self.path)

    def test_invalid_numbers_booleans_and_types_rejected(self):
        invalid = {"max_steps": (0, 31, 1.5, True, "12"),
                   "min_probability": (-0.1, 1.1, True, "0.5", float("nan"), float("inf"), 10 ** 400),
                   "allow_scroll": (0, 1, "false", None), "text_values": ([], "fixture", None),
                   "expect_labels": ([], "Settings", [1], [" "]), "allow_labels": ("Settings", [False])}
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ScenarioError):
                    self.load(payload(**{field: value}))

    def test_all_size_and_empty_limits(self):
        changes = ({"name": ""}, {"name": "x" * 301}, {"goal": " "}, {"goal": "x" * 4001},
                   {"expect_labels": ["x" * 301]}, {"expect_labels": [str(i) for i in range(31)]},
                   {"allow_labels": [str(i) for i in range(31)]},
                   {"text_values": {str(i): "fixture" for i in range(21)}},
                   {"text_values": {"": "fixture"}}, {"text_values": {"name": ""}},
                   {"text_values": {"name": "x" * 501}}, {"text_values": {"name": 4}})
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(ScenarioError):
                self.load(payload(**change))

    def test_boundary_lengths_accepted(self):
        scenario = self.load(payload(name="n" * 300, goal="g" * 4000,
                                     expect_labels=["l" * 300] * 30,
                                     text_values={str(i): "t" * 500 for i in range(20)},
                                     max_steps=1, min_probability=0))
        self.assertEqual(len(scenario.text_values), 20)

    def test_file_size_is_bounded_in_bytes(self):
        encoded = json.dumps(payload()).encode()
        self.path.write_bytes(encoded + b" " * (MAX_SCENARIO_BYTES - len(encoded)))
        self.assertEqual(load_scenario(self.path).name, "Open settings")
        self.path.write_bytes(self.path.read_bytes() + b" ")
        with self.assertRaisesRegex(ScenarioError, "64 KiB"):
            load_scenario(self.path)

    def test_malformed_json_utf8_and_nonobject_rejected(self):
        for raw in (b"{", b"[]", b"null", b'"scenario"', b"\xff"):
            self.path.write_bytes(raw)
            with self.assertRaises(ScenarioError):
                load_scenario(self.path)
        with self.assertRaisesRegex(ScenarioError, "could not be read"):
            load_scenario(self.path.parent / "missing.json")


if __name__ == "__main__":
    unittest.main()
