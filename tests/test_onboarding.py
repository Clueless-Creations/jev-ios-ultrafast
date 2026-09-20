import json
from pathlib import Path
import tempfile
import unittest

from jev_ios.onboarding import init_project


class OnboardingTests(unittest.TestCase):
    def test_init_creates_valid_agent_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = init_project(root, bundle_id="com.example.app", name="Smoke")
            scenario = json.loads((root / result["scenario"]).read_text())
            self.assertEqual(scenario["schema"], "jev-ios/scenario/v1")
            self.assertEqual(scenario["name"], "Smoke")
            self.assertIn("com.example.app", (root / result["agent_instructions"]).read_text())
            self.assertTrue((root / result["runner"]).stat().st_mode & 0o100)

    def test_init_does_not_replace_existing_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root, bundle_id="com.example.app", name="Smoke")
            with self.assertRaises(ValueError):
                init_project(root, bundle_id="com.example.app", name="Smoke")


if __name__ == "__main__":
    unittest.main()
