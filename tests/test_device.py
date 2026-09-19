import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from jev_ios.device import AxeDevice, DeviceError, StaleObservation, normalize_snapshot

UDID = "00000000-0000-0000-0000-000000000000"


def tree():
    return [{"type": "Application", "pid": 42, "frame": {"x": 0, "y": 0, "width": 390, "height": 844}, "children": [
        {"type": "Button", "pid": 42, "AXLabel": "Settings", "enabled": True, "frame": {"x": 20, "y": 50, "width": 100, "height": 40}},
        {"type": "TextField", "pid": 42, "AXLabel": "Name", "AXValue": "", "AXUniqueId": "name", "enabled": True, "frame": {"x": 20, "y": 100, "width": 200, "height": 40}},
    ]}]


class FakeCommands:
    def __init__(self, ui=None):
        self.ui = ui or tree()
        self.calls = []
        self.after_tap = None

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if "describe-ui" in args:
            output = json.dumps(self.ui)
        elif "launchctl" in args:
            output = "42 0 UIKitApplication:example.fixture[fixture][rb-legacy]\n99 0 UIKitApplication:exampleXfixture[other]\n98 0 UIKitApplication:example.fixture.extra[other]"
        elif "launch" in args:
            output = "example.fixture: 42"
        else:
            output = ""
        if "tap" in args and self.after_tap:
            self.after_tap(self.ui)
        return subprocess.CompletedProcess(args, 0, output, "")


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCommands()
        self.patches = [patch("jev_ios.device.os.path.isfile", return_value=True), patch("jev_ios.device.os.access", return_value=True), patch("jev_ios.device.subprocess.run", self.fake)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.device = AxeDevice(UDID, "example.fixture", axe_path="/fixture/axe")

    def test_inspect_resolves_exact_bundle_without_launch(self):
        observed = self.device.observe()
        self.assertEqual(observed.pid, 42)
        self.assertEqual(observed.labels, ["Settings", "Name"])
        self.assertFalse(any("launch" in args for args, _ in self.fake.calls))
        for _, kwargs in self.fake.calls:
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["timeout"], 20)

    def test_launch_binds_pid(self):
        self.assertEqual(self.device.launch(), 42)
        self.assertEqual(self.device.observe().pid, 42)

    def test_normalization_visibility_disabled_secure_geometry(self):
        raw = tree()
        children = raw[0]["children"]
        children[0]["enabled"] = False
        for change in ({"hidden": True}, {"frame": {"x": 800, "y": 1, "width": 20, "height": 20}}, {"frame": {"x": 0, "y": 1, "width": float("nan"), "height": 20}}):
            children.append({**copy.deepcopy(children[0]), "AXLabel": "Excluded", **change})
        children.append({**copy.deepcopy(children[1]), "type": "SecureTextField", "AXValue": "secret-fixture"})
        observed = normalize_snapshot(raw, 42)
        self.assertNotIn("Excluded", observed.labels)
        self.assertNotIn("1", observed.targets("tap"))
        self.assertEqual(observed.targets("type"), {"2": "Name"})
        self.assertNotIn("secret-fixture", json.dumps(observed.as_dict()))

    def test_rejects_wrong_app_and_visible_system_modal(self):
        for change in (lambda r: r[0].update(pid=43), lambda r: r[0]["children"][0].update(pid=43), lambda r: r.append(copy.deepcopy(r[0]))):
            raw = tree()
            change(raw)
            with self.assertRaises(DeviceError):
                normalize_snapshot(raw, 42)

    def test_scroll_viewport_excludes_offscreen_targets_and_completion_labels(self):
        for kind in ("ScrollView", "ScrollArea"):
            raw = tree()
            raw[0]["children"] = [{"type": kind, "frame": {"x": 0, "y": 100, "width": 390, "height": 100}, "children": [
                {"type": "Button", "AXLabel": "Hidden save target", "frame": {"x": 20, "y": 400, "width": 150, "height": 44}},
                {"type": "StaticText", "AXLabel": "All done", "frame": {"x": 20, "y": 450, "width": 150, "height": 44}},
            ]}]
            snapshot = normalize_snapshot(raw, 42)
            self.assertEqual(snapshot.targets("tap"), {})
            self.assertNotIn("All done", snapshot.labels)

    def test_nested_clips_limit_actual_tap_to_visible_part(self):
        raw = tree()
        raw[0]["children"] = [{"type": "ScrollArea", "frame": {"x": 0, "y": 100, "width": 390, "height": 100}, "children": [
            {"type": "Group", "clipsToBounds": True, "frame": {"x": 100, "y": 120, "width": 100, "height": 100}, "children": [
                {"type": "Button", "AXLabel": "Partly visible", "frame": {"x": 50, "y": 180, "width": 200, "height": 100}},
            ]},
        ]}]
        self.fake.ui = raw
        snapshot = self.device.observe()
        target = next(element for element in snapshot.elements if element["label"] == "Partly visible")
        self.assertEqual(target["frame"], {"x": 100, "y": 180, "width": 100, "height": 20})
        self.device.execute(snapshot, {"operation": "TAP", "target": target["id"]}, {})
        tap = next(args for args, _ in self.fake.calls if "tap" in args)
        self.assertEqual(tap[2:6], ["-x", "150.0", "-y", "190.0"])

    def test_plain_group_does_not_clip_overflowing_children(self):
        raw = tree()
        raw[0]["children"] = [{"type": "Group", "frame": {"x": 0, "y": 100, "width": 100, "height": 20},
                               "children": [copy.deepcopy(tree()[0]["children"][0])]}]
        self.assertIn("Settings", normalize_snapshot(raw, 42).labels)
        for flag in ("clipsToBounds", "clipsChildren", "masksToBounds", "AXClipsToBounds"):
            clipped = copy.deepcopy(raw)
            clipped[0]["children"][0][flag] = True
            self.assertNotIn("Settings", normalize_snapshot(clipped, 42).labels)

    def test_unknown_clipping_geometry_fails_closed(self):
        for kind in ("ScrollView", "ScrollArea"):
            raw = tree()
            raw[0]["children"] = [{"type": kind, "children": tree()[0]["children"]}]
            with self.assertRaisesRegex(DeviceError, "Clipping container"):
                normalize_snapshot(raw, 42)

    def test_stale_screen_does_not_dispatch(self):
        observed = self.device.observe()
        self.fake.ui[0]["children"][0]["enabled"] = False
        with self.assertRaises(StaleObservation):
            self.device.execute(observed, {"operation": "TAP", "target": "1"}, {})
        self.assertFalse(any("tap" in args for args, _ in self.fake.calls))

    def test_fingerprint_covers_value_geometry_and_pid(self):
        baseline = normalize_snapshot(tree(), 42).screen_hash
        for change in (lambda r: r[0]["children"][1].update(AXValue="changed"), lambda r: r[0]["children"][0]["frame"].update(x=21)):
            raw = tree()
            change(raw)
            self.assertNotEqual(baseline, normalize_snapshot(raw, 42).screen_hash)

    def test_tap_uses_observed_center(self):
        observed = self.device.observe()
        result = self.device.execute(observed, {"operation": "TAP", "target": "1", "x": 900}, {})
        tap = next(args for args, _ in self.fake.calls if "tap" in args)
        self.assertEqual(tap[2:6], ["-x", "70.0", "-y", "70.0"])
        self.assertEqual(tap[6:8], ["--tap-style", "physical"])
        self.assertEqual(result["pid"], 42)

    def test_same_observation_cannot_replay_an_action(self):
        observed = self.device.observe()
        self.device.execute(observed, {"operation": "TAP", "target": "1"}, {})
        with self.assertRaisesRegex(DeviceError, "already dispatched"):
            self.device.execute(observed, {"operation": "TAP", "target": "1"}, {})
        self.assertEqual(sum("tap" in args for args, _ in self.fake.calls), 1)

    def test_failed_action_consumes_observation(self):
        observed = self.device.observe()
        original = self.device._run
        def fail_tap(args, text=None):
            if "tap" in args:
                raise DeviceError("fixture timeout after dispatch")
            return original(args, text)
        with patch.object(self.device, "_run", side_effect=fail_tap):
            with self.assertRaisesRegex(DeviceError, "fixture timeout"):
                self.device.execute(observed, {"operation": "TAP", "target": "1"}, {})
        with self.assertRaisesRegex(DeviceError, "already dispatched"):
            self.device.execute(observed, {"operation": "TAP", "target": "1"}, {})

    def test_model_projection_keeps_coordinates_local(self):
        state = self.device.observe().model_state()
        self.assertTrue(state["elements"])
        self.assertEqual(set(state["elements"][0]), {"id", "kind", "label", "value", "enabled"})

    def test_numeric_zero_value_preserved(self):
        raw = tree()
        raw[0]["children"][1]["AXValue"] = 0
        snapshot = normalize_snapshot(raw, 42)
        self.assertEqual(snapshot.elements[1]["value"], "0")
        self.assertEqual(snapshot.targets("type"), {})

    def test_secure_field_subtree_and_identity_are_redacted(self):
        raw = tree()
        field = raw[0]["children"][1]
        field.update(type="SecureTextField", AXLabel="secret-label", AXUniqueId="secret-identity", AXValue="secret-value")
        field["children"] = [{**copy.deepcopy(raw[0]["children"][0]), "AXLabel": "secret-child-label", "AXUniqueId": "secret-child-id"}]
        snapshot = normalize_snapshot(raw, 42)
        serialized = json.dumps(snapshot.as_dict())
        for secret in ("secret-label", "secret-identity", "secret-value", "secret-child-label", "secret-child-id"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(snapshot.targets("type"), {})
        self.assertNotIn("2", snapshot.targets("tap"))

    def test_credential_field_detected_without_secure_traits(self):
        for label, identity in (("Password", "register_password_field"), ("", "account_passcode"), ("PIN", "code"), ("", "api_secret")):
            raw = tree()
            raw[0]["children"][1].update(AXLabel=label, AXUniqueId=identity, AXValue="sensitive-fixture", traits=[])
            snapshot = normalize_snapshot(raw, 42)
            self.assertEqual(snapshot.targets("type"), {})
            self.assertNotIn("sensitive-fixture", json.dumps(snapshot.as_dict()))

    def test_decorative_image_motion_does_not_invalidate_controls(self):
        raw = tree()
        image = {"type": "Image", "pid": 42, "AXLabel": "Mascot", "frame": {"x": 150, "y": 200, "width": 50, "height": 50}}
        raw[0]["children"].append(image)
        before = normalize_snapshot(raw, 42)
        image["frame"]["y"] += 0.23
        after = normalize_snapshot(raw, 42)
        self.assertEqual(before.screen_hash, after.screen_hash)
        image["AXLabel"] = "Error illustration"
        self.assertNotEqual(before.screen_hash, normalize_snapshot(raw, 42).screen_hash)

    def test_explicit_unhittable_controls_are_not_targets(self):
        for key in ("hittable", "isHittable"):
            raw = tree()
            raw[0]["children"][0][key] = False
            snapshot = normalize_snapshot(raw, 42)
            self.assertNotIn("1", snapshot.targets("tap"))
            self.assertIn("Settings", snapshot.labels)

    def test_modal_rejects_background_label_evidence(self):
        for kind in ("Alert", "Sheet"):
            raw = tree()
            raw[0]["children"].append({"type": kind, "pid": 42, "frame": {"x": 40, "y": 100, "width": 200, "height": 200}, "children": []})
            with self.assertRaisesRegex(DeviceError, "modal"):
                normalize_snapshot(raw, 42)
            raw[0]["children"][-1]["hidden"] = True
            self.assertIn("Settings", normalize_snapshot(raw, 42).labels)

    def test_type_fails_closed_without_focus(self):
        observed = self.device.observe()
        with self.assertRaisesRegex(DeviceError, "focus"):
            self.device.execute(observed, {"operation": "TYPE_TEXT", "target": "2", "text_key": "name"}, {"name": "Fixture"})
        self.assertFalse(any("type" in args for args, _ in self.fake.calls))

    def test_type_passes_exact_text_stdin_after_focus(self):
        self.fake.after_tap = lambda raw: raw[0]["children"][1].update(focused=True)
        self.device.execute(self.device.observe(), {"operation": "TYPE_TEXT", "target": "2", "text_key": "name"}, {"name": "Fixture $(literal)"})
        args, options = next((args, opts) for args, opts in self.fake.calls if "type" in args)
        self.assertIn("--stdin", args)
        self.assertNotIn("Fixture $(literal)", args)
        self.assertEqual(options["input"], "Fixture $(literal)")
        focus_tap = next(args for args, _ in self.fake.calls if "tap" in args)
        self.assertEqual(focus_tap[6:8], ["--tap-style", "physical"])

    def test_type_rejects_nonempty_fields_and_non_ascii(self):
        decision = {"operation": "TYPE_TEXT", "target": "2", "text_key": "name"}
        with self.assertRaises(DeviceError):
            self.device.execute(self.device.observe(), decision, {"name": "é"})
        self.fake.ui[0]["children"][1]["AXValue"] = "existing"
        with self.assertRaises(DeviceError):
            self.device.execute(self.device.observe(), decision, {"name": "Fixture"})
        self.assertFalse(any("tap" in args for args, _ in self.fake.calls))


if __name__ == "__main__":
    unittest.main()
