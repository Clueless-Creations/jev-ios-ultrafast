"""Parallel semantic tests with one exclusive device lane per worker.

Workers are Python threads with separate model clients, not coding agents.
No device input, inference request, or uncertain case is automatically retried.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
from queue import Queue, Empty
import re
import threading
import time

from .device import DeviceError
from .fleet import open_session
from .lease import Lease, DeviceBusy
from .model import JevModel, ModelError, ModelOptions
from .runner import Runner
from .suite import Suite, validate_workers


class Cancelled(RuntimeError):
    pass


class Gate:
    """One account-wide (per coordinator) API concurrency and start-rate gate."""
    def __init__(self, concurrency=2, rate=4.0, cancel=None):
        if type(concurrency) is not int or not 1 <= concurrency <= 32:
            raise ValueError("API concurrency must be 1-32")
        if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 < rate <= 1000:
            raise ValueError("Request rate must be finite and in (0, 1000]")
        self.limit, self.interval = concurrency, 1.0 / rate
        self.cancel = cancel or threading.Event()
        self.condition = threading.Condition()
        self.active = self.peak = self.attempts = 0
        self.next_start = 0.0
        self.reason = None

    def abort(self, reason):
        with self.condition:
            self.reason = self.reason or reason
            self.cancel.set()
            self.condition.notify_all()

    def check(self, deadline=None):
        if self.cancel.is_set():
            raise Cancelled(self.reason or "cancelled")
        if deadline is not None and time.monotonic() >= deadline:
            raise Cancelled("task_timeout")

    def call(self, model, args, deadline):
        with self.condition:
            while True:
                self.check(deadline)
                delay = self.next_start - time.monotonic()
                if self.active < self.limit and delay <= 0:
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                    self.attempts += 1
                    self.next_start = time.monotonic() + self.interval
                    break
                self.condition.wait(min(max(delay, 0.01), 0.05))
        try:
            self.check(deadline)
            value = model.decide(*args)
            self.check(deadline)  # Do not dispatch a decision returned after cancellation.
            return value
        except ModelError as exc:
            match = re.search(r"HTTP (401|403|429)\b", str(exc))
            if match:
                self.abort("provider_http_" + match[1])
            raise
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def metrics(self):
        with self.condition:
            return {"decision_admissions": self.attempts, "peak_api_concurrency": self.peak,
                    "api_concurrency_limit": self.limit, "requests_per_second": 1.0 / self.interval}


class GatedModel:
    def __init__(self, model, gate, deadline):
        self.model, self.gate, self.deadline = model, gate, deadline

    def decide(self, *args):
        return self.gate.call(self.model, args, self.deadline)


class GuardedDevice:
    def __init__(self, device, gate, deadline):
        self.device, self.gate, self.deadline = device, gate, deadline

    def observe(self):
        self.gate.check(self.deadline)
        return self.device.observe()

    def execute(self, *args):
        self.gate.check(self.deadline)
        return self.device.execute(*args)


def reserve_budget(cases, workers, mode, catalog, budget_usd):
    """Reserve full-context pricing for every possible call, including failures."""
    try:
        budget = Decimal(str(budget_usd))
        model = next(m for m in catalog if m["id"] == "typesafe-ai/jev")
        rate = Decimal(str(model["pricing"]["input"]))
        output = Decimal(str(model["pricing"]["output"]))
        context = int(model["context_window"])
        if not budget.is_finite() or budget <= 0 or not rate.is_finite() or rate < 0 or output != 0 or not 1 <= context <= 2_000_000:
            raise ValueError()
    except (KeyError, StopIteration, TypeError, ValueError, InvalidOperation, OverflowError):
        raise ValueError("Cannot establish a finite Jev pricing reservation") from None
    multiplier = len(workers) if mode == "matrix" else 1
    by_case = {c.id: Decimal(c.scenario.max_steps * (123 if c.scenario.text_values else 2) * context) * rate
               for c in cases}
    reserve = sum(by_case.values(), Decimal(0)) * multiplier
    if reserve > budget:
        raise ValueError(f"Conservative suite reservation ${reserve} exceeds --budget-usd ${budget}")
    return {"model": "typesafe-ai/jev", "budget_usd": str(budget), "reserved_usd": str(reserve),
            "per_case_reserved_usd": {k: str(v) for k, v in by_case.items()},
            "max_model_calls": sum(c.scenario.max_steps for c in cases) * multiplier,
            "note": "Admission bound, not a provider billing cap or measured cost. No retries or decision cache."}


def make_plan(suite, selected, workers, mode="shard", selection=None, provenance=None):
    validate_workers(workers)
    if mode not in ("shard", "matrix"):
        raise ValueError("Mode must be shard or matrix")
    cases = [c for c, _ in selected]
    expected = ([c.id + "@" + w.name for c in cases for w in workers] if mode == "matrix" else [c.id for c in cases])
    if len(set(expected)) != len(expected):
        raise ValueError("Duplicate scheduled cell")
    return {"schema": "jev-ios/plan/v1", "suite": suite.name, "bundle_id": suite.bundle_id,
            "fixture_isolation": suite.fixture_isolation, "mode": mode,
            "cases": [dict(c.as_dict(), selected_because=reason) for c, reason in selected],
            "devices": [w.as_dict() for w in workers], "expected_cells": expected,
            "selection": selection or {}, "provenance": provenance or {},
            "verification": "Exact visible accessibility labels; not backend, visual, or exhaustive release coverage."}


def run_matrix(suite: Suite, selected, workers, *, output_dir: Path, catalog, budget_usd=1,
               mode="shard", parallel=2, api_concurrency=2, requests_per_second=4,
               task_timeout=180, fail_fast=False, api_key=None, selection=None, provenance=None,
               session_factory=open_session, model_factory=None, cancel=None, emit=None,
               lease_directory=None):
    from .matrix_report import write_json, write_text, write_reports, cell_report, summarize
    if type(parallel) is not int or not 1 <= parallel <= 32:
        raise ValueError("Parallel lanes must be 1-32")
    if type(task_timeout) not in (int, float) or not math.isfinite(task_timeout) or not 1 <= task_timeout <= 3600:
        raise ValueError("Task timeout must be 1-3600 seconds")
    plan = make_plan(suite, selected, workers, mode, selection, provenance)
    if not plan["expected_cells"]:
        raise ValueError("No scenarios selected; an empty run is not verification")
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Matrix output directory must be new")
    gate = Gate(api_concurrency, requests_per_second, cancel=cancel)
    cases = [c for c, _ in selected]
    pricing = reserve_budget(cases, workers, mode, catalog, budget_usd)
    output_dir.mkdir(parents=True, mode=0o700)
    output_dir.chmod(0o700)
    write_json(output_dir / "plan.json", plan)
    manifest = {"schema": "jev-ios/matrix/v1", "plan": plan, "pricing": pricing,
                "results": [], "lane_errors": [], "complete": False, "interrupted": False,
                "stop_reason": None, "elapsed_ms": 0,
                "execution": {"parallel": parallel, "task_timeout": task_timeout, "fail_fast": fail_fast}}
    write_json(output_dir / "matrix.json", manifest)
    emit = emit or (lambda event: None)
    model_factory = model_factory or (lambda case: JevModel(ModelOptions(max_calls=case.scenario.max_steps), api_key=api_key))
    publication = threading.Lock()
    start = time.monotonic()
    shard_queue = Queue()
    for case in cases:
        shard_queue.put(case)

    def publish(row):
        with publication:
            manifest["results"].append(row)
            manifest["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
            manifest["api"] = gate.metrics()
            write_json(output_dir / "matrix.json", manifest)
            emit({"type": "cell_result", "cell": row["cell"], "device": row["device"],
                  "status": row["status"], "reason": row["reason"]})

    def run_case(device, worker, case):
        cell = case.id + "@" + worker.name if mode == "matrix" else case.id
        folder = output_dir / cell
        folder.mkdir(mode=0o700)
        write_json(folder / "scenario.json", case.as_dict()["scenario"])
        events = []
        started = time.monotonic()
        deadline = started + task_timeout
        result = None
        model = None
        row = {"cell": cell, "case": case.id, "device": worker.name, "status": "error",
               "reason": "setup_error", "trace": cell + "/trace.jsonl", "report": cell + "/report.html"}
        with (folder / "trace.jsonl").open("x", encoding="utf-8") as trace:
            (folder / "trace.jsonl").chmod(0o600)
            def record(event):
                events.append(event)
                import json
                trace.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                trace.flush()
            record({"type": "session", "cell": cell, "device": worker.as_dict(), "bundle_id": suite.bundle_id,
                    "scenario_sha256": case.as_dict()["scenario_sha256"]})
            try:
                with ExitStack() as resources:
                    keys = list(case.resource_locks)
                    if suite.fixture_isolation == "shared":
                        keys.append("shared-fixture:" + suite.bundle_id)
                    for key in sorted(set(keys)):
                        resources.enter_context(Lease("fixture:" + key, directory=lease_directory,
                                                      wait=True, cancel=gate.cancel, wait_timeout=max(.001, deadline - time.monotonic())))
                    gate.check(deadline)
                    device.reset(case.launch_args)
                    guarded = GuardedDevice(device, gate, deadline)
                    snapshot = guarded.observe()
                    record({"type": "start", "labels": snapshot.labels, "screen_hash": snapshot.screen_hash})
                    if not all(label in snapshot.labels for label in case.start_labels):
                        row.update(status="blocked", reason="start_labels_missing")
                    else:
                        model = model_factory(case)
                        with model:
                            result = Runner(guarded, GatedModel(model, gate, deadline), emit=record,
                                            **case.scenario.to_runner_kwargs()).run(case.scenario.goal, case.scenario.expect_labels)
                        row.update(status=result["status"], reason=result["reason"])
            except Cancelled as exc:
                row.update(status="cancelled", reason=str(exc))
            except ModelError as exc:
                match = re.search(r"HTTP (\d{3})\b", str(exc))
                row.update(status="error", reason="provider_http_" + match[1] if match else "model_error")
            except DeviceBusy:
                row.update(status="error", reason="fixture_lease_unavailable")
            except DeviceError:
                row.update(status="uncertain", reason="device_session_failed_no_replay")
            except Exception:
                # Do not leak provider credentials, host stderr or app values in an exception string.
                row.update(status="error", reason="worker_error")
            row.update(elapsed_ms=round((time.monotonic() - started) * 1000, 1),
                       model_calls=getattr(model, "calls", 0), result=result)
            record({"type": "cell_result", **row})
        write_json(folder / "result.json", row)
        write_text(folder / "report.html", cell_report(row, events))
        return row

    def lane(worker):
        if gate.cancel.is_set():
            return
        local = iter(cases)
        def take_case():
            return next(local) if mode == "matrix" else shard_queue.get_nowait()
        # Claim work before acquiring a local lease or opening SSH. In shard
        # mode an unused offline pool member must not invalidate completed work.
        try:
            case = take_case()
        except (StopIteration, Empty):
            return
        if gate.cancel.is_set():
            return
        try:
            with session_factory(worker, suite.bundle_id) as device:
                while not gate.cancel.is_set():
                    row = run_case(device, worker, case)
                    publish(row)
                    if fail_fast and row["status"] != "verified":
                        gate.abort("fail_fast")
                    if row["status"] in ("uncertain", "cancelled") or row["reason"] in ("worker_error", "start_labels_missing", "fixture_lease_unavailable"):
                        # Preserve isolation after any unverified reset or uncertain input.
                        break
                    try:
                        case = take_case()
                    except (StopIteration, Empty):
                        break
        except Exception:
            with publication:
                manifest["lane_errors"].append({"device": worker.name, "reason": "device_lane_unavailable"})
            if fail_fast:
                gate.abort("fail_fast")

    pool = ThreadPoolExecutor(max_workers=min(parallel, len(workers)), thread_name_prefix="jev-device")
    futures = [pool.submit(lane, worker) for worker in workers]
    try:
        for future in as_completed(futures):
            future.result()
    except KeyboardInterrupt:
        gate.abort("interrupted")
        manifest["interrupted"] = True
    finally:
        # Device commands and model I/O already have bounded timeouts. Let an
        # in-flight action settle rather than release its lease prematurely.
        pool.shutdown(wait=True)
    seen = {r["cell"] for r in manifest["results"]}
    for cell in plan["expected_cells"]:
        if cell not in seen:
            case_id, _, device_id = cell.partition("@")
            manifest["results"].append({"cell": cell, "case": case_id, "device": device_id or None,
                                         "status": "skipped", "reason": gate.reason or "device_lane_unavailable",
                                         "model_calls": 0, "elapsed_ms": 0, "result": None})
    manifest["results"].sort(key=lambda r: plan["expected_cells"].index(r["cell"]))
    manifest["complete"] = all(r["status"] not in ("skipped", "cancelled") for r in manifest["results"])
    manifest["stop_reason"] = gate.reason
    manifest["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
    manifest["api"] = gate.metrics()
    manifest["finished"] = True
    manifest["summary"] = summarize(manifest)
    write_reports(output_dir, manifest)
    emit({"type": "matrix_result", **manifest["summary"], "manifest": str(output_dir / "matrix.json"),
          "report": str(output_dir / "index.html")})
    return manifest
