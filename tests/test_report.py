import base64
import html
import json
from pathlib import Path
import re
import stat
import tempfile
import unittest

from jev_ios.report import write_report


def result(**changes):
    return {"type": "result", "schema": "jev-ios/run/v1", "status": "verified",
            "reason": "exact_labels_visible", "goal": "Open settings",
            "expected_labels": ["Settings"], "matched_labels": ["Settings"],
            "actions_executed": 1, "model_calls": 1, "elapsed_ms": 1200,
            "model_ms": [120], "usage": [], "final_screen_hash": "fixture",
            "verification": "Exact visible accessibility labels", **changes}


def embedded_data(source):
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', source, re.S)
    if not match:
        raise AssertionError("Report has no embedded JSON data")
    return json.loads(match[1])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "report.html"

    def test_hostile_labels_and_title_cannot_escape_html_or_script(self):
        hostile = '</script><script>alert("fixture")</script><img src=x onerror=alert(1)>&'
        title = '<img src=x onerror="alert(1)">'
        events = [
            {"type": "decision", "step": 0, "model_ms": 120, "probability": 0.9},
            {"type": "action", "step": 0, "operation": "TAP", "target_label": hostile, "elapsed_ms": 200},
            result(goal=hostile, expected_labels=[hostile], matched_labels=[hostile]),
        ]
        write_report(self.output, events, title=title)
        source = self.output.read_text()
        self.assertNotIn(hostile, source)
        self.assertNotIn(title, source)
        self.assertIn(html.escape(title), source)
        self.assertEqual(source.count("</script>"), 2)
        data = embedded_data(source)
        self.assertEqual(data["timeline"][0]["label"], hostile)
        self.assertEqual(data["result"]["goal"], hostile)

    def test_raw_observations_and_unrecognized_result_fields_are_omitted(self):
        marker = "PRIVATE_FIXTURE_SHOULD_NOT_BE_IN_REPORT"
        events = [{"type": "observation", "elements": [{"kind": "SecureTextField", "value": marker}]},
                  {"type": "decision", "step": 0, "raw_response": marker},
                  result(password=marker, text_values={"password": marker},
                         observations=[{"value": marker}], provider_response={"token": marker},
                         usage=[{"inputTokens": 42, "password": marker}])]
        write_report(self.output, events)
        source = self.output.read_text()
        self.assertNotIn(marker, source)
        self.assertEqual(embedded_data(source)["result"]["status"], "verified")
        self.assertEqual(embedded_data(source)["result"]["usage"], [{"inputTokens": 42}])

    def test_result_is_required_and_invalid_data_is_rejected(self):
        cases = ([], [{"type": "observation"}], [None], [{"type": "result"}],
                 [result(model_ms=["invalid"])], [result(elapsed_ms=float("nan"))],
                 [result(status={})], [result(status="verified", matched_labels=[])],
                 [{"type": "action", "step": 0, "operation": []}, result()])
        for index, events in enumerate(cases):
            output = self.root / f"invalid-{index}.html"
            with self.subTest(events=events):
                with self.assertRaises(ValueError):
                    write_report(output, events)
                self.assertFalse(output.exists())

    def test_local_video_is_embedded_without_external_reference(self):
        video = self.root / "fixture.mp4"
        content = b"\x00\x00\x00\x18ftypmp42" + b"fixture" * 20
        video.write_bytes(content)
        write_report(self.output, [result()], video=video, video_offset_ms=140)
        source = self.output.read_text()
        match = re.search(r'src="data:video/mp4;base64,([A-Za-z0-9+/=]+)"', source)
        self.assertIsNotNone(match)
        self.assertEqual(base64.b64decode(match[1]), content)
        self.assertNotIn(str(video), source)
        self.assertEqual(embedded_data(source)["video_offset_ms"], 140)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_missing_video_does_not_write_report(self):
        with self.assertRaises((OSError, ValueError)):
            write_report(self.output, [result()], video=self.root / "missing.mp4")
        self.assertFalse(self.output.exists())

    def test_oversized_video_is_rejected_without_reading_it(self):
        video = self.root / "large.mp4"
        with video.open("wb") as stream:
            stream.seek(40_000_000)
            stream.write(b"x")
        with self.assertRaisesRegex(ValueError, "40 MB"):
            write_report(self.output, [result()], video=video)
        self.assertFalse(self.output.exists())

    def test_existing_report_is_never_overwritten(self):
        self.output.write_text("existing evidence")
        with self.assertRaises(FileExistsError):
            write_report(self.output, [result()])
        self.assertEqual(self.output.read_text(), "existing evidence")

    def test_placeholder_text_is_not_reinterpreted_during_render(self):
        write_report(self.output, [result(goal="Read __TITLE__ and __MEDIA__")], title="Title __DATA__")
        source = self.output.read_text()
        self.assertIn("<title>Title __DATA__</title>", source)
        self.assertEqual(embedded_data(source)["result"]["goal"], "Read __TITLE__ and __MEDIA__")

    def test_invalid_video_header_is_rejected(self):
        video = self.root / "invalid.mp4"
        video.write_bytes(b"not a video" * 30)
        with self.assertRaisesRegex(ValueError, "header"):
            write_report(self.output, [result()], video=video)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
