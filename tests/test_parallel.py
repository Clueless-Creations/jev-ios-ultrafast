"""Offline regression and concurrency tests against the real Runner contract."""
import copy
from dataclasses import replace
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

from jev_ios.cli import main, parser
from jev_ios.device import DeviceError, Snapshot, StaleObservation
from jev_ios.fleet import NativeSession, booted_workers
from jev_ios.lease import Lease, DeviceBusy
from jev_ios.matrix import Cancelled, Gate, GuardedDevice, make_plan, reserve_budget, run_matrix
from jev_ios.matrix_report import load_manifest, summarize, write_json
from jev_ios.model import ModelError
from jev_ios.parallel_cli import handle, freeze_case
from jev_ios.remote import PROTOCOL, RemoteSession, serve
from jev_ios.scenario import Scenario
from jev_ios.suite import (Case, Suite, WorkerSpec, changed_paths, load_pool, load_suite, read_json,
                           scenario_data, select_cases, validate_workers)

CATALOG = [{"id": "typesafe-ai/jev", "pricing": {"input": "0.0000001", "output": "0"}, "context_window": 2048}]
BUNDLE = "com.example.fixture"


def worker(number=1, host=None):
    return WorkerSpec(f"phone-{number}", str(uuid.UUID(int=number)), host=host)


def case(name="smoke", **kwargs):
    return Case(name, Scenario(name=name, goal="Reach Ready", expect_labels=("Ready",),
                               allow_labels=("Next",), max_steps=2), "smoke.json", ("Sources/*",),
                ("smoke",), False, ("Home",), (), (), **kwargs)


def snapshot(ready=False):
    labels = ["Ready"] if ready else ["Home", "Next"]
    elements = [{"id": str(i + 1), "kind": "Button" if label == "Next" else "StaticText", "label": label,
                 "value": "", "enabled": True, "secure": False, "unique_id": label,
                 "frame": {"x": 0, "y": 0, "width": 10, "height": 10}, "focused": False}
                for i, label in enumerate(labels)]
    return Snapshot(elements, labels, "ready" if ready else "home", 123,
                    {"x": 0, "y": 0, "width": 100, "height": 100}, 1.0,
                    observation_id="ready-id" if ready else "home-id")


class Lab:
    def __init__(self, *, model_error=None, uncertain=False, start_wrong=False, bad_choice=False, barrier=None):
        self.lock = threading.Lock()
        self.active = self.peak = self.calls = self.actions = self.resets = self.opened = self.closed = 0
        self.lane_actions = {}
        self.model_error, self.uncertain, self.start_wrong = model_error, uncertain, start_wrong
        self.bad_choice, self.barrier = bad_choice, barrier

    def device(self, spec, bundle):
        lab = self
        class Device:
            def __enter__(self):
                self.ready = False
                with lab.lock:
                    lab.opened += 1
                return self
            def __exit__(self, *_):
                with lab.lock:
                    lab.closed += 1
            def reset(self, launch_args=()):
                self.ready = lab.start_wrong
                with lab.lock:
                    lab.resets += 1
            def observe(self):
                return snapshot(self.ready)
            def execute(self, snap, decision, text_values):
                with lab.lock:
                    lab.actions += 1
                    lab.lane_actions[spec.name] = lab.lane_actions.get(spec.name, 0) + 1
                self.ready = True
                if lab.uncertain:
                    raise DeviceError("An action may already have landed")
                return {"operation": "TAP", "target": decision["target"], "before_hash": "home", "after_hash": "ready"}
        return Device()

    def model(self, selected_case):
        lab = self
        class Model:
            calls = 0
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def decide(self, state, actions, taps, types, values):
                self.calls += 1
                with lab.lock:
                    lab.calls += 1
                    lab.active += 1
                    lab.peak = max(lab.peak, lab.active)
                try:
                    if lab.barrier:
                        lab.barrier.wait(timeout=3)
                    time.sleep(0.015)
                    if lab.model_error:
                        raise ModelError(lab.model_error)
                    return {"operation": "TAP", "target": "not-offered" if lab.bad_choice else next(iter(taps)),
                            "probability": .95, "model_ms": 15, "usage": {"inputTokens": 10}}
                finally:
                    with lab.lock:
                        lab.active -= 1
        return Model()


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def run_lab(self, lab=None, count=4, devices=2, **kwargs):
        lab = lab or Lab()
        cases = tuple(case(f"case-{i}") for i in range(count))
        suite = Suite("Regression", BUNDLE, cases, kwargs.pop("isolation", "per_device"))
        result = run_matrix(suite, [(c, "full_suite") for c in cases], [worker(i + 1) for i in range(devices)],
                            output_dir=self.root / "run", catalog=CATALOG, session_factory=lab.device,
                            model_factory=lab.model, lease_directory=self.root / "locks",
                            requests_per_second=1000, **kwargs)
        return result, lab

    def test_sharding_runs_every_case_once_and_overlaps_api_calls(self):
        result, lab = self.run_lab(Lab(barrier=threading.Barrier(2)), count=4)
        self.assertEqual(lab.calls, 4)
        self.assertEqual(lab.actions, 4)
        self.assertEqual(lab.peak, 2)
        self.assertEqual(result["summary"]["status"], "verified")
        self.assertEqual(len({r["cell"] for r in result["results"]}), 4)
        self.assertEqual(lab.opened, lab.closed)

    def test_matrix_runs_cartesian_product(self):
        result, lab = self.run_lab(count=2, devices=3, parallel=2, mode="matrix")
        self.assertEqual(result["summary"]["planned"], 6)
        self.assertEqual(lab.calls, 6)
        self.assertEqual(lab.lane_actions, {"phone-1": 2, "phone-2": 2, "phone-3": 2})
        self.assertLessEqual(result["api"]["peak_api_concurrency"], 2)

    def test_api_cap_is_separate_from_device_count(self):
        result, lab = self.run_lab(count=4, devices=4, parallel=4, api_concurrency=1)
        self.assertEqual(lab.peak, 1)
        self.assertEqual(result["summary"]["status"], "verified")

    def test_shared_fixture_serializes_parallel_lanes(self):
        result, lab = self.run_lab(count=4, parallel=2, isolation="shared")
        self.assertEqual(lab.peak, 1)
        self.assertEqual(result["summary"]["status"], "verified")

    def test_provider_429_stops_fanout_without_retry(self):
        result, lab = self.run_lab(Lab(model_error="Jev provider returned HTTP 429; secret-token"), count=5,
                                   api_concurrency=1)
        self.assertEqual(lab.calls, 1)
        self.assertEqual(lab.actions, 0)
        self.assertEqual(result["stop_reason"], "provider_http_429")
        self.assertEqual(result["summary"]["status"], "not_verified")
        for path in (self.root / "run").rglob("*"):
            if path.is_file():
                self.assertNotIn("secret-token", path.read_text())

    def test_uncertain_action_quarantines_lane(self):
        result, lab = self.run_lab(Lab(uncertain=True), devices=1, count=3)
        self.assertEqual(lab.actions, 1)
        self.assertEqual(lab.calls, 1)
        self.assertEqual(result["summary"]["counts"]["uncertain"], 1)
        self.assertEqual(result["summary"]["counts"]["skipped"], 2)

    def test_wrong_start_never_calls_model(self):
        result, lab = self.run_lab(Lab(start_wrong=True), count=2, devices=1)
        self.assertEqual(lab.calls, 0)
        self.assertEqual(result["results"][0]["reason"], "start_labels_missing")
        self.assertEqual(result["results"][1]["status"], "skipped")

    def test_unoffered_target_never_executes(self):
        result, lab = self.run_lab(Lab(bad_choice=True), count=1, devices=1)
        self.assertEqual(lab.actions, 0)
        self.assertEqual(result["results"][0]["reason"], "unoffered_target")

    def test_fail_fast_records_unstarted_cells(self):
        result, lab = self.run_lab(Lab(bad_choice=True), count=4, devices=1, fail_fast=True)
        self.assertEqual(lab.calls, 1)
        self.assertEqual(len(result["results"]), 4)
        self.assertEqual(result["summary"]["counts"]["skipped"], 3)

    def test_pre_cancelled_run_has_no_sessions(self):
        event = threading.Event(); event.set()
        result, lab = self.run_lab(count=2, cancel=event)
        self.assertEqual(lab.opened, 0)
        self.assertEqual(result["summary"]["counts"]["skipped"], 2)

    def test_budget_checked_before_devices_and_output(self):
        with self.assertRaises(ValueError):
            self.run_lab(count=5, budget_usd=0.000001)
        self.assertFalse((self.root / "run").exists())

    def test_existing_output_is_not_overwritten(self):
        (self.root / "run").mkdir()
        sentinel = self.root / "run" / "evidence"
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            self.run_lab()
        self.assertEqual(sentinel.read_text(), "keep")

    def test_every_cell_has_private_trace_and_report(self):
        result, _ = self.run_lab(count=2)
        for row in result["results"]:
            self.assertTrue((self.root / "run" / row["report"]).exists())
            path = self.root / "run" / row["trace"]
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('"type": "result"', path.read_text())
        self.assertEqual((self.root / "run").stat().st_mode & 0o777, 0o700)
        tree = ET.parse(self.root / "run" / "junit.xml")
        self.assertEqual(tree.getroot().attrib["tests"], "2")

    def test_verify_rejects_missing_or_fabricated_label_evidence(self):
        result, _ = self.run_lab(count=1, devices=1)
        result["results"][0]["result"]["matched_labels"] = []
        with self.assertRaises(ValueError):
            summarize(result)

    def test_checkpoint_is_never_a_passing_gate(self):
        result, _ = self.run_lab(count=1, devices=1)
        result.pop("finished")
        self.assertEqual(summarize(result)["status"], "not_verified")

    def test_missing_or_duplicate_cells_fail_verification(self):
        result, _ = self.run_lab(count=2)
        omitted = copy.deepcopy(result)
        omitted["results"].pop()
        self.assertEqual(summarize(omitted)["status"], "not_verified")
        result["results"].append(copy.deepcopy(result["results"][0]))
        with self.assertRaises(ValueError):
            summarize(result)

    def test_reproduction_is_dry_by_default(self):
        result, _ = self.run_lab(count=1, devices=1)
        args = parser().parse_args(["reproduce", "--manifest", str(self.root / "run" / "matrix.json"), "--cell", "case-0"])
        events = []
        code = handle(args, events.append, lambda: self.fail("No provider call allowed"), lambda _: self.fail("No token call"))
        self.assertEqual(code, 0)
        self.assertEqual(events[0]["type"], "reproduction_plan")
        self.assertEqual(events[0]["cases"][0]["scenario"], result["plan"]["cases"][0]["scenario"])

    def test_uncertain_reproduction_requires_acknowledgement(self):
        self.run_lab(Lab(uncertain=True), count=1, devices=1)
        args = parser().parse_args(["reproduce", "--manifest", str(self.root / "run" / "matrix.json"),
                                    "--cell", "case-0", "--execute"])
        with self.assertRaisesRegex(ValueError, "acknowledge"):
            handle(args, lambda _: None, lambda: self.fail("No provider"), lambda _: None)

    def test_frozen_scenario_digest_must_match(self):
        frozen = case().as_dict()
        frozen["scenario"]["goal"] = "Changed"
        with self.assertRaises(ValueError):
            freeze_case(frozen)

    def test_empty_selection_not_a_pass(self):
        with self.assertRaises(ValueError):
            self.run_lab(count=0)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.payload = {"schema": "jev-ios/suite/v1", "name": "Smoke", "bundle_id": BUNDLE,
                        "start_labels": ["Home"], "cases": [{"id": "smoke", "scenario": "smoke.json"}]}
        (self.root / "smoke.json").write_text(json.dumps(scenario_data(case().scenario)))
    def tearDown(self): self.tmp.cleanup()
    def load(self):
        (self.root / "suite.json").write_text(json.dumps(self.payload))
        return load_suite(self.root / "suite.json")
    def test_valid_suite_and_safe_shared_default(self):
        self.assertEqual(self.load().fixture_isolation, "shared")
    def test_duplicate_cases_rejected(self):
        self.payload["cases"] *= 2
        with self.assertRaises(ValueError): self.load()
    def test_unknown_field_rejected(self):
        self.payload["shell"] = "arbitrary command"
        with self.assertRaises(ValueError): self.load()
    def test_missing_start_rejected(self):
        self.payload.pop("start_labels")
        with self.assertRaises(ValueError): self.load()
    def test_escaping_scenario_path_rejected(self):
        self.payload["cases"][0]["scenario"] = "../smoke.json"
        with self.assertRaises(ValueError): self.load()
    def test_placeholder_is_not_runnable(self):
        data = scenario_data(case().scenario); data["goal"] = "REPLACE: flow"
        (self.root / "smoke.json").write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.load()
    def test_duplicate_json_keys_rejected(self):
        (self.root / "data.json").write_text('{"schema": 1, "schema": 2}')
        with self.assertRaises(ValueError): read_json(self.root / "data.json")
    def test_non_finite_json_rejected(self):
        (self.root / "data.json").write_text('{"budget": NaN}')
        with self.assertRaises(ValueError): read_json(self.root / "data.json")
    def test_duplicate_physical_device_rejected(self):
        with self.assertRaises(ValueError): validate_workers([worker(), replace(worker(), name="alias")])
    def test_same_uuid_on_distinct_hosts_allowed(self):
        self.assertEqual(len(validate_workers([worker(), replace(worker(), name="remote", host="trusted-mac")])), 2)
    def test_ssh_options_and_shell_injection_rejected(self):
        for value in ("-oProxyCommand=evil", "host;echo evil", "user@host\ncommand"):
            with self.subTest(value=value), self.assertRaises(ValueError): worker(host=value)
    def test_bundle_shell_injection_rejected(self):
        self.payload["bundle_id"] = 'com.example.$(touch /tmp/no)'
        with self.assertRaises(ValueError): self.load()
    def test_matrix_budget_covers_every_device(self):
        one = reserve_budget([case()], [worker(), worker(2)], "shard", CATALOG, 1)
        two = reserve_budget([case()], [worker(), worker(2)], "matrix", CATALOG, 1)
        self.assertEqual(float(two["reserved_usd"]), 2 * float(one["reserved_usd"]))
        self.assertEqual(two["max_model_calls"], 4)
    def test_invalid_pricing_cannot_start_run(self):
        for value in (-1, "NaN", "Infinity"):
            catalog = copy.deepcopy(CATALOG); catalog[0]["pricing"]["input"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): reserve_budget([case()], [worker()], "shard", catalog, 1)
    def test_critical_and_affected_selection(self):
        suite = Suite("S", BUNDLE, (replace(case("a"), paths=("A/*",)), replace(case("b"), paths=("B/*",), critical=True),
                                     replace(case("c"), paths=("C/*",))))
        selected, info = select_cases(suite, changed=["A/file.swift"])
        self.assertEqual([c.id for c, _ in selected], ["a", "b"])
        self.assertEqual(info["omitted"], ["c"])
    def test_unknown_change_selects_everything(self):
        suite = Suite("S", BUNDLE, (case("a"), case("b")))
        selected, info = select_cases(suite, changed=["Package.swift"])
        self.assertEqual(len(selected), 2)
        self.assertEqual(info["unmapped_changed_paths"], ["Package.swift"])
    def test_unmapped_case_is_always_included(self):
        suite = Suite("S", BUNDLE, (replace(case(), paths=()),))
        self.assertEqual(len(select_cases(suite, changed=[])[0]), 1)
    def test_unknown_explicit_case_is_error(self):
        with self.assertRaises(ValueError): select_cases(Suite("S", BUNDLE, (case(),)), only=["typo"])
    def test_plan_needs_neither_credential_nor_provider(self):
        self.load()
        args = parser().parse_args(["plan", "--suite", str(self.root / "suite.json"), "--udid", worker().udid])
        events = []
        with patch.dict(os.environ, {}, clear=True):
            result = handle(args, events.append, lambda: self.fail("No API"), lambda _: self.fail("No token"))
        self.assertEqual(result, 0)
        self.assertEqual(events[0]["expected_cells"], ["smoke"])
    def test_git_selection_includes_all_worktree_states_and_both_rename_paths(self):
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True)
        git("init", "-q"); git("config", "user.name", "Test"); git("config", "user.email", "test@example.com")
        for name in ("old.swift", "delete.swift", "edit.swift"):
            (self.root / name).write_text("initial\n")
        git("add", "."); git("commit", "-qm", "base")
        ref = git("rev-parse", "HEAD").stdout.decode().strip()
        git("mv", "old.swift", "new.swift"); git("rm", "delete.swift")
        git("commit", "-qm", "change")
        (self.root / "edit.swift").write_text("modified\n")
        (self.root / "untracked.swift").write_text("new\n")
        paths, base = changed_paths(self.root, ref)
        self.assertEqual(base, ref)
        self.assertTrue({"old.swift", "new.swift", "delete.swift", "edit.swift", "untracked.swift"} <= set(paths))


class IsolationTests(unittest.TestCase):
    def test_lease_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Lease("device", directory=tmp):
                with self.assertRaises(DeviceBusy):
                    with Lease("device", directory=tmp): pass
            with Lease("device", directory=tmp): pass
    def test_lease_survives_exception_without_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                with Lease("device", directory=tmp): raise ValueError()
            except ValueError: pass
            with Lease("device", directory=tmp): pass
    def test_cross_process_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = 'from jev_ios.lease import Lease; import sys\nwith Lease("device", directory=sys.argv[1]):\n print("locked", flush=True)\n sys.stdin.readline()\n'
            p = subprocess.Popen([sys.executable, "-c", code, tmp], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(p.stdout.readline().strip(), "locked")
                with self.assertRaises(DeviceBusy):
                    with Lease("device", directory=tmp): pass
            finally:
                p.communicate("\n", timeout=5)
            with Lease("device", directory=tmp): pass
    def test_cancelled_gate_does_not_dispatch(self):
        gate = Gate(); gate.abort("cancelled")
        with self.assertRaises(Cancelled): gate.call(None, (), time.monotonic() + 1)
    def test_gate_enforces_start_rate(self):
        starts = []
        class M:
            def decide(self): starts.append(time.monotonic())
        gate = Gate(concurrency=3, rate=20)
        threads = [threading.Thread(target=lambda: gate.call(M(), (), time.monotonic() + 2)) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(starts), 3)
        self.assertGreaterEqual(min(b - a for a, b in zip(starts, starts[1:])), .04)
    def test_native_reset_keeps_arguments_out_of_shell(self):
        spec = replace(worker(), axe="/bin/true")
        device = NativeSession(spec, BUNDLE)
        with patch("jev_ios.fleet.subprocess.run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(device, "_run", return_value=BUNDLE + ": 123") as launch:
            device.reset(["--fixture", "literal; not a command"])
            self.assertEqual(launch.call_args.args[0][-2:], ["--fixture", "literal; not a command"])
            self.assertEqual(device.pid, 123)


class RemoteTests(unittest.TestCase):
    def requests(self, *items):
        return BytesIO(b"".join(json.dumps({"id": i, "protocol": PROTOCOL, **v}).encode() + b"\n" for i, v in enumerate(items)))
    def test_remote_worker_rejects_replayed_observation(self):
        lab = Lab()
        source = self.requests({"op": "open", "worker": worker(host="mac").as_dict(), "bundle_id": BUNDLE},
                               {"op": "observe"},
                               {"op": "execute", "observation_id": "home-id", "decision": {"operation": "TAP", "target": "2"}, "text_values": {}},
                               {"op": "execute", "observation_id": "home-id", "decision": {"operation": "TAP", "target": "2"}, "text_values": {}})
        out = BytesIO(); serve(source, out, session_factory=lab.device)
        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(lab.actions, 1)
        self.assertFalse(rows[-1]["ok"])
        self.assertEqual(lab.closed, 1)
    def test_remote_worker_does_not_accept_shell_commands(self):
        out = BytesIO(); lab = Lab()
        serve(self.requests({"op": "shell", "command": "echo no"}), out, session_factory=lab.device)
        self.assertFalse(json.loads(out.getvalue())["ok"])
        self.assertEqual(lab.opened, 0)
    def test_round_trip_over_real_subprocess_pipes(self):
        script = '''from jev_ios.remote import serve
from jev_ios.device import Snapshot
class Session:
 def __init__(self,*args): self.ready=False
 def __enter__(self): return self
 def __exit__(self,*args): pass
 def reset(self,args): self.ready=False
 def observe(self):
  return Snapshot([], ["Ready" if self.ready else "Home"], "ready" if self.ready else "home", 123, {}, 1.0, observation_id="id")
 def execute(self,s,d,t): self.ready=True; return {"operation":"TAP"}
serve(session_factory=Session)
'''
        captured = []
        def factory(argv, **kwargs):
            captured.append(argv)
            return subprocess.Popen([sys.executable, "-u", "-c", script], **kwargs)
        with RemoteSession(worker(host="trusted-mac"), BUNDLE, process_factory=factory) as session:
            session.reset()
            first = session.observe()
            self.assertEqual(first.labels, ["Home"])
            session.execute(first, {"operation": "TAP", "target": "1"}, {})
            self.assertEqual(session.observe().labels, ["Ready"])
        self.assertIn("BatchMode=yes", captured[0])
        self.assertNotIn("StrictHostKeyChecking=no", captured[0])
        self.assertEqual(captured[0][-1], "python3 -m jev_ios.remote")


if __name__ == "__main__": unittest.main()
