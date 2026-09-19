import base64
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from jev_ios.comparison_report import PLAYBACK_SCRIPT, TEMPLATE, write_comparison_report


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
                       {"pair": 0}, {"pair": 11}, {"position": 3}, {"video_offset_ms": -1},
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
        too_many = manifest([run(pair=i // 2 + 1, backend="jev" if i % 2 == 0 else "baseline") for i in range(21)])
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

    def test_all_attempts_and_provenance_survive_a_two_cohort_report(self):
        data = manifest([run(backend, pair, cohort=1 if pair <= 3 else 2,
                             status="error" if pair < 6 else "verified",
                             matched_labels=[] if pair < 6 else ["Saved"],
                             error="HTTP 429" if pair < 6 else None)
                         for pair in range(1, 7) for backend in ("jev", "baseline")])
        data["settings"].update(pairs=6, orders=[["jev", "baseline"]] * 6)
        data["provenance"] = {"source_commit": "revision", "notes": "Two fixed cohorts; all attempts retained.",
                              "unknown": "PRIVATE_MARKER", "cohorts": [
                                  {"cohort": 1, "created_at": "fixture-one", "source_pairs": 3},
                                  {"cohort": 2, "created_at": "fixture-two", "source_pairs": 3}]}
        source = self.write(data)
        actual = embedded_data(source)
        self.assertEqual(len(actual["runs"]), 12)
        self.assertEqual(actual["summary"]["paired_verified_count"], 1)
        self.assertEqual(actual["runs"][0]["error"], "HTTP 429")
        self.assertEqual(actual["runs"][-1]["cohort"], 2)
        self.assertEqual(len(actual["provenance"]["cohorts"]), 2)
        self.assertNotIn("PRIVATE_MARKER", source)

    def test_published_trace_hash_does_not_invent_an_attached_trace(self):
        data = manifest()
        for item in data["runs"]:
            del item["trace"]
            item["trace_sha256"] = "a" * 64
            item["first_observation_elements_sha256"] = "b" * 64
        actual = embedded_data(self.write(data))
        self.assertIsNone(actual["runs"][0]["trace"])
        self.assertEqual(actual["runs"][0]["trace_sha256"], "a" * 64)

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser-controller tests")
    def test_browser_script_syntax(self):
        script = re.search(r'<script>\n(.*?)\n</script>', TEMPLATE, re.S)[1]
        result = subprocess.run(["node", "--check", "--input-type=commonjs"], input=script,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser-controller tests")
    def test_playback_readiness_cancellation_alignment_and_end_behavior(self):
        harness = r'''
const assert=require('node:assert/strict');
let nextFrame=0;const frames=new Map();
global.requestAnimationFrame=callback=>{frames.set(++nextFrame,callback);return nextFrame;};
global.cancelAnimationFrame=id=>frames.delete(id);
function tick(){const callbacks=[...frames.values()];frames.clear();callbacks.forEach(callback=>callback());}
async function flush(){for(let i=0;i<8;i++)await Promise.resolve();}
class Video{
  constructor(duration=10,ready=4){this.duration=duration;this.readyState=ready;this.currentTime=0;this.playbackRate=1;this.paused=true;this.seeking=false;this.listeners=new Map();this.defer=false;this.promises=[];}
  addEventListener(name,listener){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(listener);}
  removeEventListener(name,listener){this.listeners.get(name)?.delete(listener);}
  emit(name){[...(this.listeners.get(name)||[])].forEach(listener=>listener());}
  pause(){this.paused=true;}
  play(){this.paused=false;if(!this.defer)return Promise.resolve();return new Promise((resolve,reject)=>this.promises.push({resolve,reject}));}
  advance(seconds){if(!this.paused)this.currentTime=Math.min(this.duration,this.currentTime+seconds);}
}
function setup(){const ui={playButton:{},range:{},clock:{},status:{}};return {ui,control:createPairedPlayback(ui)};}
(async()=>{
  // Metadata and seek readiness gate Play; a later scrub cancels the old seek.
  const pending=setup(),a=new Video(10,0),b=new Video(10,0);
  const firstMount=pending.control.mount([{video:a,offset:.25},{video:b,offset:.75}]);
  assert.equal(pending.ui.playButton.disabled,true);
  a.readyState=b.readyState=1;a.emit('loadedmetadata');b.emit('loadedmetadata');await flush();
  assert.equal(pending.ui.playButton.disabled,true);
  const laterSeek=pending.control.seek(3);
  a.readyState=b.readyState=4;a.emit('canplay');b.emit('canplay');
  assert.equal(await laterSeek,true);assert.equal(await firstMount,false);
  assert.equal(a.currentTime,3.25);assert.equal(b.currentTime,3.75);
  assert.equal(pending.control.state().cursor,3);assert.equal(pending.ui.playButton.disabled,false);
  pending.control.clear();

  // The clock follows decoded frames, pauses on buffering, and never speeds up.
  const active=setup(),c=new Video(),d=new Video();
  await active.control.mount([{video:c,offset:.2},{video:d,offset:.4}]);
  await active.control.toggle();await flush();c.advance(1);d.advance(1);tick();
  assert.ok(Math.abs(active.control.state().cursor-1)<.0001);
  tick();assert.ok(Math.abs(active.control.state().cursor-1)<.0001);
  d.readyState=2;tick();assert.equal(active.control.state().mode,'buffering');assert.equal(c.paused,true);assert.equal(d.paused,true);
  d.readyState=4;tick();await flush();
  c.advance(.4);d.advance(.2);tick();assert.equal(c.paused,true);assert.equal(d.paused,false);
  d.advance(.2);tick();await flush();assert.equal(c.paused,false);
  assert.equal(c.playbackRate,1);assert.equal(d.playbackRate,1);active.control.clear();

  // A stale play promise cannot resume after scrub or pause, or affect a new pair.
  const race=setup(),e=new Video(),f=new Video();e.defer=f.defer=true;
  await race.control.mount([{video:e,offset:.1},{video:f,offset:.2}]);
  await race.control.toggle();await race.control.seek(2);
  e.promises[0].resolve();f.promises[0].resolve();await flush();
  assert.equal(race.control.state().mode,'paused');assert.equal(race.control.state().cursor,2);assert.equal(e.paused,true);
  await race.control.toggle();race.control.pause();e.promises[1].resolve();f.promises[1].resolve();await flush();
  assert.equal(race.control.state().mode,'paused');assert.equal(e.paused,true);
  await race.control.toggle();const g=new Video(),h=new Video();
  await race.control.mount([{video:g,offset:.3},{video:h,offset:.4}]);
  e.promises[2].resolve();f.promises[2].resolve();await flush();
  assert.equal(race.control.state().mode,'paused');assert.equal(race.control.state().cursor,0);assert.equal(e.paused,true);assert.equal(g.paused,true);race.control.clear();

  // Seeking past a short clip holds its final frame; full replay resets offsets.
  const ending=setup(),short=new Video(2),long=new Video(5);
  await ending.control.mount([{video:short,offset:.2},{video:long,offset:.4}]);
  await ending.control.seek(3);await ending.control.toggle();await flush();
  assert.equal(short.currentTime,1.975);assert.equal(short.paused,true);assert.equal(long.paused,false);
  long.advance(2);tick();assert.equal(ending.control.state().mode,'paused');assert.equal(ending.control.state().cursor,4.6);
  await ending.control.toggle();await flush();assert.equal(short.currentTime,.2);assert.equal(long.currentTime,.4);assert.equal(short.paused,false);ending.control.clear();
  assert.equal(frames.size,0);
  console.log('Playback readiness, stale-promise cancellation, buffering, drift, seek, ending, and replay: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(["node", "--input-type=commonjs"], input=PLAYBACK_SCRIPT + harness,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
