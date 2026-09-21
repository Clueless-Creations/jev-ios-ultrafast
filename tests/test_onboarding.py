import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from jev_ios.onboarding import init_project
from jev_ios.scenario import load_scenario


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def init(self, **kwargs):
        return init_project(self.root, bundle_id="com.example.app", name="Smoke", **kwargs)
    def test_init_creates_valid_agent_scaffold(self):
        result = self.init()
        scenario = load_scenario(self.root / result["scenario"])
        self.assertEqual(scenario.name, "Smoke")
        self.assertIn("com.example.app", (self.root / result["agent_instructions"]).read_text())
        self.assertTrue((self.root / result["runner"]).stat().st_mode & 0o100)
        self.assertEqual(json.loads((self.root / result["suite"]).read_text())["schema"], "jev-ios/suite/v1")
    def test_init_does_not_replace_existing_scenario(self):
        self.init()
        with self.assertRaises(ValueError): self.init()
    def test_generated_wrapper_passes_shell_syntax(self):
        result = self.init()
        subprocess.run(["sh", "-n", str(self.root / result["runner"])], check=True)
    def test_force_preserves_user_edits(self):
        self.init()
        path = self.root / ".jev-ios" / "smoke.json"
        path.write_text('{"custom": true}')
        with self.assertRaises(ValueError): self.init(force=True)
        self.assertEqual(path.read_text(), '{"custom": true}')
    def test_force_can_refresh_unmodified_generated_files(self):
        self.init(); self.init(force=True)
        load_scenario(self.root / ".jev-ios/smoke.json")
    def test_late_collision_cannot_partially_scaffold(self):
        (self.root / ".jev-ios").mkdir()
        (self.root / ".jev-ios/run-smoke.sh").write_text("keep")
        with self.assertRaises(ValueError): self.init()
        self.assertFalse((self.root / ".jev-ios/smoke.json").exists())
    def test_symlinked_directory_rejected(self):
        outside = self.root / "outside"; outside.mkdir()
        (self.root / ".jev-ios").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): self.init()
        self.assertEqual(list(outside.iterdir()), [])
    def test_invalid_bundle_cannot_inject_shell(self):
        with self.assertRaises(ValueError):
            init_project(self.root, bundle_id='com.example.$(touch /tmp/never)', name="Smoke")
        self.assertFalse((self.root / ".jev-ios").exists())
    def test_no_existing_app_agent_guidance_is_overwritten(self):
        guide = self.root / "AGENTS.md"; guide.write_text("app rules")
        self.init()
        self.assertEqual(guide.read_text(), "app rules")
    def test_generated_script_preserves_old_evidence(self):
        result = self.init()
        self.assertNotIn("rm -f", (self.root / result["runner"]).read_text())
    def test_maps_are_ignored_and_skill_is_local(self):
        self.init()
        self.assertIn("app-map", (self.root / ".jev-ios/.gitignore").read_text())
        self.assertTrue((self.root / ".jev-ios/SKILL.md").is_file())\n        self.assertIn("host repo root .gitignore", self.init(force=True)["next"])


if __name__ == "__main__": unittest.main()
