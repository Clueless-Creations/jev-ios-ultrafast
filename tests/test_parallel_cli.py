"""Public CLI admission checks without a provider, Xcode, or a remote Mac."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jev_ios.cli import main
from jev_ios.device import Snapshot
from jev_ios.suite import load_suite

UUID = "11111111-1111-1111-1111-111111111111"


class PublicCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def learn(self, *extra):
        return main(["learn", "--udid", UUID, "--bundle-id", "com.example.app",
                     "--output", str(self.root / "map.json"), *extra])

    def test_existing_map_rejected_before_auth_provider_or_device(self):
        (self.root / "map.json").write_text("keep")
        with patch("jev_ios.cli.AxeDevice") as device, patch("jev_ios.cli.model_catalog") as catalog, \
             patch("jev_ios.cli.temporary_vercel_token") as token, redirect_stdout(io.StringIO()):
            self.assertEqual(self.learn("--allow-label", "Settings", "--vercel-project", "example"), 1)
        device.assert_not_called()
        catalog.assert_not_called()
        token.assert_not_called()
        self.assertEqual((self.root / "map.json").read_text(), "keep")

    def test_learning_pricing_rejected_before_device_and_auth(self):
        with patch("jev_ios.cli.AxeDevice") as device, patch("jev_ios.cli.pricing_bound", side_effect=ValueError("budget")), \
             patch("jev_ios.cli.temporary_vercel_token") as token, redirect_stdout(io.StringIO()):
            self.assertEqual(self.learn("--allow-label", "Settings", "--vercel-project", "example"), 1)
        device.assert_not_called()
        token.assert_not_called()

    def test_observe_only_learning_needs_no_pricing_or_credential(self):
        snap = Snapshot([], ["Home"], "home", 123, {}, 1.0)
        with patch("jev_ios.cli.AxeDevice") as device, patch("jev_ios.cli.model_catalog") as catalog, \
             patch("jev_ios.cli.temporary_vercel_token") as token, redirect_stdout(io.StringIO()):
            device.return_value.observe.return_value = snap
            self.assertEqual(self.learn(), 0)
        catalog.assert_not_called()
        token.assert_not_called()
        device.return_value.execute.assert_not_called()
        result = json.loads((self.root / "map.json").read_text())
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["schema"], "jev-ios/app-map/v2")
        self.assertEqual((self.root / "map.json").stat().st_mode & 0o777, 0o600)

    def test_invalid_learning_confidence_rejected_before_output_or_device(self):
        with patch("jev_ios.cli.AxeDevice") as device, redirect_stdout(io.StringIO()):
            self.assertEqual(self.learn("--min-probability", "nan"), 1)
        device.assert_not_called()
        self.assertFalse((self.root / "map.json").exists())

    def test_placeholder_start_label_is_not_a_plan(self):
        (self.root / "smoke.json").write_text(json.dumps({"schema": "jev-ios/scenario/v1", "name": "smoke",
            "goal": "Open settings", "expect_labels": ["Settings"]}))
        path = self.root / "suite.json"
        path.write_text(json.dumps({"schema": "jev-ios/suite/v1", "name": "smoke", "bundle_id": "com.example.app",
            "start_labels": ["REPLACE: home"], "cases": [{"id": "smoke", "scenario": "smoke.json"}]}))
        with self.assertRaises(ValueError):
            load_suite(path)

    def test_example_plans_through_real_cli_subprocess_without_credentials(self):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-m", "jev_ios", "plan", "--suite",
            str(repo / "examples/parallel/daybreak-suite.json"), "--pool", str(repo / "examples/parallel/pool.local.json"),
            "--mode", "matrix"], capture_output=True, text=True, timeout=10, check=True)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["type"], "plan")
        self.assertEqual(len(plan["expected_cells"]), 4)
        self.assertEqual(plan["fixture_isolation"], "per_device")

    def test_package_and_module_versions_agree(self):
        import tomllib
        from jev_ios import __version__
        project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
        self.assertEqual(project["project"]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
