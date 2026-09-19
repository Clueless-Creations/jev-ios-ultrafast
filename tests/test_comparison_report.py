import base64
import json
from pathlib import Path
import re
import stat
import tempfile
import unittest

from jev_ios.comparison_report import write_comparison_report


def run(backend="jev", pair=1, **changes):
    return {"id": f"{pair}-{backend}", "pair": pair, "position": 1 if backend == "jev" else 2,
            "backend": backend, "model": "typesafe-ai/jev" if backend == "jev" else "openai/gpt-5.4-nano",
            "status": "verified", "reason": "exact_labels_visible", "elapsed_ms": 1000,
            "model_ms": [150], "model_calls": 1, "actions_executed": 1,
            "usage": [{"inputTokens": 100, "outputTokens": 20}], "input_tokens": 100,
            "output_tokens": 20, "cached_input_tokens": 0, "estimated_cost_usd": .0001,
            "initial_state_hash": "same-controls", "matched_labels": ["Saved"],
            "expected_labels": ["Saved"], "trace": f"{pair}-{backend}.jsonl", "video": None,
            "video_offset_ms": 0, "setup_status": "ready", "setup_elapsed_ms": 123,
            "timing_valid": True, **changes}


def manifest(runs=None):
    return {"schema": "jev-ios/comparison/v1", "scenario": {
        "name": "fixture", "goal": "Save a weekend", "expect_labels": ["Saved"], "max_steps": 10,
        "allow_scroll": False}, "settings": {"pairs": 1, "min_probability": 0,
        "orders": [["jev", "baseline"]], "timing_boundary": "Runner start to final verification.",
        "start_labels": ["Home"], "record_video": True},
        "pricing": {"jev": {"model": "typesafe-ai/jev", "input_rate_per_million": .042},
                    "baseline": {"model": "openai/gpt-5.4-nano", "input_rate_per_million": .2}},
        "runs": runs if runs is not None else [run(), run("baseline", elapsed_ms=2000)]}


def embedded_data(source):
    match = re.search(r'<script type="application/json" id="comparison-data">(.*?)</script>', source, re.S)
    if not match:
        raise AssertionError("No comparison JSON in HTML")
    return json.loads(match[1])


class ComparisonReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "report.html"

    def write(self, data):
        write_comparison_report(self.output, data, media_root=self.root)
        return self.output.read_text()

    def test_report_recomputes_paired_maths_and_counts_every_failure(self):
        data = manifest([run(elapsed_ms=1000), run("baseline", elapsed_ms=2000),
                         run(pair=2, elapsed_ms=2000), run("baseline", pair=2, elapsed_ms=8000),
                         run(pair=3, status="stopped", matched_labels=[], elapsed_ms=10),
                         run("baseline", pair=3, elapsed_ms=10_000)])
        data["settings"]["pairs"] = 3
        data["summary"] = {"median_paired_speedup": 99999, "paired_verified_count": 99}
        actual = embedded_data(self.write(data))
        self.assertEqual(actual["summary"]["paired_verified_count"], 2)
        self.assertEqual(actual["summary"]["median_paired_speedup"], 3)
        self.assertEqual(actual["paired_median_elapsed_ms"], {"jev": 1500, "baseline": 5000})
        self.assertEqual(actual["summary"]["backends"]["jev"]["attempted"], 3)
        self.assertEqual(actual["summary"]["backends"]["jev"]["verified"], 2)
        self.assertEqual(len(actual["runs"]), 6)

    def test_mismatched_states_never_produce_a_speed_ratio(self):
        data = manifest([run(), run("baseline", initial_state_hash="different", elapsed_ms=9000)])
        actual = embedded_data(self.write(data))
        self.assertIsNone(actual["summary"]["median_paired_speedup"])
        self.assertEqual(actual["paired_median_elapsed_ms"], {"jev": None, "baseline": None})
        self.assertEqual(actual["summary"]["pairs"][0]["reason"], "initial_state_mismatch")

    def test_partial_interrupted_run_and_null_measurements_remain_visible(self):
        data = manifest([run(status="interrupted", reason="interrupted", matched_labels=[],
                             setup_status="failed", timing_valid=False, elapsed_ms=None,
                             estimated_cost_usd=None, model_ms=[])])
        actual = embedded_data(self.write(data))
        self.assertEqual(len(actual["runs"]), 1)
        self.assertIsNone(actual["runs"][0]["elapsed_ms"])
        self.assertIsNone(actual["runs"][0]["estimated_cost_usd"])
        self.assertEqual(actual["summary"]["backends"]["baseline"]["attempted"], 0)
        self.assertEqual(actual["summary"]["pairs"][0]["reason"], "incomplete_pair")

    def test_hostile_text_cannot_break_out_of_json(self):
        hostile = '</script><script>alert("fixture")</script><img src=x onerror=alert(1)>&'
        data = manifest([run(model=hostile, expected_labels=[hostile], matched_labels=[hostile]),
                         run("baseline", expected_labels=[hostile], matched_labels=[hostile])])
        data["scenario"].update(goal=hostile, expect_labels=[hostile])
        source = self.write(data)
        self.assertNotIn(hostile, source)
        self.assertEqual(source.count("</script>"), 2)
        self.assertEqual(embedded_data(source)["scenario"]["goal"], hostile)

    def test_unknown_fields_ui_trees_and_credentials_are_not_embedded(self):
        marker = "PRIVATE_FIXTURE_DO_NOT_EMBED"
        data = manifest()
        data["api_key"] = marker
        data["scenario"]["text_values"] = {"password": marker}
        data["settings"]["udid"] = marker
        data["settings"]["environment"] = {"token": marker}
        data["pricing"]["jev"]["auth"] = marker
        data["runs"][0].update(observations=[{"value": marker}], provider_response=marker)
        data["runs"][0]["usage"][0]["secret"] = marker
        source = self.write(data)
        self.assertNotIn(marker, source)
        self.assertEqual(embedded_data(source)["pricing"]["jev"]["input_rate_per_million"], .042)

    def test_video_is_embedded_at_original_bytes_and_offset(self):
        content = b"\x00\x00\x00\x18ftypmp42" + b"fixture" * 20
        (self.root / "fixture.mp4").write_bytes(content)
        source = self.write(manifest([run(video="fixture.mp4", video_offset_ms=150), run("baseline")]))
        match = re.search(r'src="data:video/mp4;base64,([A-Za-z0-9+/=]+)"', source)
        self.assertEqual(base64.b64decode(match[1]), content)
        self.assertEqual(embedded_data(source)["runs"][0]["video_offset_ms"], 150)
        self.assertNotIn(str(self.root), source)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_unsafe_paths_are_rejected_before_output(self):
        for value in ("../outside.mp4", "/tmp/outside.mp4", "nested/../outside.mp4", "./video.mp4",
                      "nested//video.mp4", "C:\\video.mp4", "https://example.com/video.mp4", "bad\x00.mp4"):
            for key in ("video", "trace"):
                with self.subTest(value=value, key=key):
                    data = manifest([run(**{key: value}), run("baseline")])
                    with self.assertRaises(ValueError):
                        self.write(data)
                    self.assertFalse(self.output.exists())

    def test_symlink_cannot_escape_media_root(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"\x00\x00\x00\x18ftypmp42fixture")
        media = self.root / "media"
        media.mkdir()
        (media / "link.mp4").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "within its media root"):
            write_comparison_report(self.output, manifest([run(video="link.mp4"), run("baseline")]), media_root=media)
        self.assertFalse(self.output.exists())

    def test_missing_invalid_and_oversized_media_are_rejected(self):
        (self.root / "invalid.mp4").write_bytes(b"not an mp4" * 5)
        (self.root / "wrong.mov").write_bytes(b"\x00\x00\x00\x18ftypmp42fixture")
        with (self.root / "large.mp4").open("wb") as stream:
            stream.seek(40_000_000)
            stream.write(b"x")
        for filename in ("missing.mp4", "invalid.mp4", "wrong.mov", "large.mp4"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    self.write(manifest([run(video=filename), run("baseline")]))
                self.assertFalse(self.output.exists())

    def test_duplicate_ids_backends_and_positions_are_rejected(self):
        for change in ({"id": "1-jev"}, {"backend": "jev"}, {"position": 1}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    baseline = run("baseline")
                    baseline.update(change)
                    self.write(manifest([run(), baseline]))
                self.assertFalse(self.output.exists())

    def test_invalid_numeric_types_and_bounds_are_rejected(self):
        for change in ({"elapsed_ms": float("nan")}, {"model_ms": [float("inf")]},
                       {"model_calls": True}, {"estimated_cost_usd": -.001}, {"model_ms": [1] * 31},
                       {"pair": 0}, {"pair": 6}, {"position": 3}, {"video_offset_ms": -1},
                       {"timing_valid": 1}, {"elapsed_ms": None}, {"backend": []}, {"status": {}}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.write(manifest([run(**change), run("baseline")]))
                self.assertFalse(self.output.exists())

    def test_inconsistent_verification_is_rejected(self):
        for change in ({"matched_labels": []}, {"expected_labels": ["Other"], "matched_labels": ["Other"]},
                       {"matched_labels": ["Saved", "Unrequested"]}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.write(manifest([run(**change), run("baseline")]))
                self.assertFalse(self.output.exists())

    def test_missing_measurement_evidence_is_not_assumed_ready(self):
        for key in ("setup_status", "setup_elapsed_ms", "timing_valid"):
            data = manifest()
            del data["runs"][0][key]
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.write(data)
                self.assertFalse(self.output.exists())

    def test_invalid_manifests_do_not_write_artifacts(self):
        cases = [None, [], {}, {"schema": "wrong"}, manifest([])]
        malformed = manifest()
        malformed["settings"]["orders"] = [[{}, "jev"]]
        cases.append(malformed)
        too_many = manifest([run(pair=i // 2 + 1, backend="jev" if i % 2 == 0 else "baseline") for i in range(11)])
        cases.append(too_many)
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    self.write(data)
                self.assertFalse(self.output.exists())

    def test_existing_report_is_never_overwritten(self):
        self.output.write_text("original evidence")
        with self.assertRaises(FileExistsError):
            self.write(manifest())
        self.assertEqual(self.output.read_text(), "original evidence")

    def test_template_markers_in_data_are_not_reinterpreted(self):
        data = manifest()
        data["scenario"]["goal"] = "Read __MEDIA__ and __DATA__"
        actual = embedded_data(self.write(data))
        self.assertEqual(actual["scenario"]["goal"], "Read __MEDIA__ and __DATA__")


if __name__ == "__main__":
    unittest.main()
