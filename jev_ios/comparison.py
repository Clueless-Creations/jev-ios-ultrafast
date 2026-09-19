"""Sequential matched trials using one simulator, runner, and verification rule."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

from .device import AxeDevice, DeviceError
from .model import JevModel, MODEL, ModelError, ModelOptions
from .recording import VideoRecorder
from .runner import Runner
from .scenario import Scenario


SCHEMA = "jev-ios/comparison/v1"


class _InitialStateChanged(DeviceError):
    pass


class _FirstObservationDevice:
    """Validate the actual runner input, after recorder and model setup."""
    def __init__(self, device, initial, row, record):
        self._device, self._initial, self._row, self._record = device, initial, row, record
        self._checked = False

    def observe(self):
        snapshot = self._device.observe()
        if not self._checked:
            self._checked = True
            digest = semantic_state_hash(snapshot)
            self._row["initial_state_hash"] = digest
            self._record({"type": "starting_state", "initial_state_hash": digest,
                          "setup_state_hash": self._row["setup_state_hash"]})
            if snapshot.pid != self._initial.pid or digest != self._row["setup_state_hash"]:
                raise _InitialStateChanged("Starting screen changed after setup; no model request made")
        return snapshot

    def __getattr__(self, name):
        return getattr(self._device, name)


def semantic_state_hash(snapshot):
    """Compare initial controls without process-specific fingerprint metadata."""
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items()
                    if key not in {"pid", "screen_hash", "observed_at", "observation_id"}}
        if isinstance(value, (list, tuple)):
            return [stable(item) for item in value]
        return value
    content = {"elements": snapshot.elements, "frame": snapshot.frame,
               "labels": snapshot.labels}
    return hashlib.sha256(json.dumps(stable(content), sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _ready_snapshot(device, start_labels, timeout=10):
    deadline, previous = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        snapshot = device.observe()
        if time.monotonic() >= deadline:
            break
        if all(label in snapshot.labels for label in start_labels):
            if previous is not None and snapshot.pid == previous.pid and snapshot.screen_hash == previous.screen_hash:
                return snapshot
            previous = snapshot
        else:
            previous = None
        time.sleep(0.1)
    raise DeviceError("App did not reach a stable expected starting screen within 10 seconds")


def _median(values):
    return round(statistics.median(values), 3) if values else None


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _cost_stats(usage, calls, pricing):
    counts = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    complete = len(usage) == calls
    cost = 0.0
    for entry in usage:
        if not isinstance(entry, dict):
            complete = False
            continue
        values = [entry.get("inputTokens"), entry.get("outputTokens"), entry.get("cacheReadInputTokens", 0)]
        if any(type(value) is not int or value < 0 for value in values) or values[2] > values[0]:
            complete = False
            continue
        incoming, outgoing, cached = values
        for key, value in zip(counts, values):
            counts[key] += value
        rates = [pricing.get("input_rate_per_million"), pricing.get("output_rate_per_million", 0),
                 pricing.get("cache_read_rate_per_million") if cached else 0]
        if any(not _finite(rate) for rate in rates):
            complete = False
            continue
        cost += ((incoming - cached) * rates[0] + outgoing * rates[1] + cached * rates[2]) / 1_000_000
    return {**counts, "estimated_cost_usd": round(cost, 9) if complete else None}


def summarize_comparison(manifest):
    """Keep failures in denominators and compare times only for matched successes."""
    runs = manifest.get("runs", [])
    initial_hashes = {run["initial_state_hash"] for run in runs
                      if run.get("setup_status") == "ready" and isinstance(run.get("initial_state_hash"), str)
                      and run["initial_state_hash"]}
    initial_state_consistent = len(initial_hashes) == 1 and not any(
        run.get("reason") == "initial_state_changed" for run in runs)
    backends = {}
    for backend in ("jev", "baseline"):
        group = [run for run in runs if run.get("backend") == backend]
        verified = [run for run in group if run.get("status") == "verified" and run.get("timing_valid") is True]
        costs = [run.get("estimated_cost_usd") for run in group]
        known = [cost for cost in costs if _finite(cost)]
        unknown = len(costs) - len(known)
        backends[backend] = {
            "attempted": len(group), "verified": len(verified), "failed": len(group) - len(verified),
            "setup_failures": sum(run.get("setup_status") != "ready" for run in group),
            "median_verified_elapsed_ms": _median([run["elapsed_ms"] for run in verified if _finite(run.get("elapsed_ms"))]),
            "median_request_ms": _median([value for run in group for value in run.get("model_ms", []) if _finite(value)]),
            "requests_with_timing": sum(sum(_finite(value) for value in run.get("model_ms", [])) for run in group),
            "requests_without_timing": sum(max(0, run.get("model_calls", 0) - sum(_finite(value) for value in run.get("model_ms", []))) for run in group),
            "estimated_cost_usd": round(sum(known), 9) if not unknown else None,
            "known_estimated_cost_usd": round(sum(known), 9), "unknown_cost_runs": unknown,
            **{key: sum(run.get(key, 0) for run in group if type(run.get(key)) is int and run[key] >= 0)
               for key in ("input_tokens", "output_tokens", "cached_input_tokens")},
        }
    pairs, ratios = [], []
    pair_numbers = sorted({run["pair"] for run in runs if type(run.get("pair")) is int})
    for number in pair_numbers:
        group = [run for run in runs if run.get("pair") == number]
        by_backend = {run.get("backend"): run for run in group}
        jev, baseline = by_backend.get("jev"), by_backend.get("baseline")
        comparable, reason, ratio = False, "incomplete_pair", None
        if jev and baseline and Counter(run.get("backend") for run in group) == {"jev": 1, "baseline": 1}:
            if any(run.get("setup_status") != "ready" or run.get("timing_valid") is not True for run in group):
                reason = "setup_or_timing_failed"
            elif not jev.get("initial_state_hash") or jev["initial_state_hash"] != baseline.get("initial_state_hash"):
                reason = "initial_state_mismatch"
            elif not initial_state_consistent:
                reason = "cohort_initial_state_mismatch"
            else:
                comparable, reason = True, "matched_outcomes"
                if all(run.get("status") == "verified" and _finite(run.get("elapsed_ms")) and run["elapsed_ms"] > 0 for run in group):
                    ratio = baseline["elapsed_ms"] / jev["elapsed_ms"]
                    ratios.append(ratio)
                    reason = "matched_verified_pair"
        pairs.append({"pair": number, "jev_id": jev.get("id") if jev else None,
                      "baseline_id": baseline.get("id") if baseline else None,
                      "comparable": comparable, "reason": reason,
                      "baseline_over_jev": round(ratio, 4) if ratio is not None else None})
    return {"backends": backends, "pairs": pairs, "paired_verified_count": len(ratios),
            "initial_state_consistent": initial_state_consistent, "initial_state_hashes_count": len(initial_hashes),
            "median_paired_speedup": _median(ratios)}


def _write_manifest(directory, manifest):
    temporary = directory / ".comparison.json.tmp"
    payload = json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(directory / "comparison.json")


def run_comparison(*, scenario, udid, bundle_id, output_dir, api_key, pricing,
                   baseline_model="openai/gpt-5.4-nano", pairs=3, start_labels,
                   record_video=True, emit=None):
    """Run each scheduled attempt once; callers must first authorize pricing."""
    from .baseline import ChatCompletionModel
    if not isinstance(scenario, Scenario):
        raise ValueError("Comparison requires a validated Scenario")
    if type(pairs) is not int or not 1 <= pairs <= 5:
        raise ValueError("Comparison pairs must be an integer from 1 to 5")
    if not isinstance(start_labels, (list, tuple)) or not start_labels or any(not isinstance(label, str) or not label.strip() for label in start_labels):
        raise ValueError("Comparison requires exact expected starting labels")
    if type(record_video) is not bool:
        raise ValueError("record_video must be a boolean")
    if not isinstance(pricing, dict) or set(pricing) != {"jev", "baseline"} or any(not isinstance(value, dict) for value in pricing.values()):
        raise ValueError("Comparison requires pricing metadata for both backends")
    if not isinstance(baseline_model, str) or not baseline_model.strip():
        raise ValueError("Comparison requires an explicit baseline model")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    portable = {"schema": scenario.schema, "name": scenario.name, "goal": scenario.goal,
                "expect_labels": list(scenario.expect_labels), **scenario.to_runner_kwargs()}
    portable["allow_labels"] = list(portable["allow_labels"])
    portable["min_probability"] = 0
    orders = [["jev", "baseline"] if pair % 2 == 0 else ["baseline", "jev"] for pair in range(pairs)]
    manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "scenario": portable, "settings": {
                    "pairs": pairs, "orders": orders, "start_labels": list(start_labels),
                    "record_video": record_video, "min_probability": 0,
                    "confidence_policy": "Disabled for both backends; generated JSON has no calibrated choice probability",
                    "request_timeout_seconds": 10, "max_request_bytes": 24_000,
                    "baseline_request": {"temperature": 0, "reasoning_effort": "none", "max_output_tokens": 128},
                    "timing_boundary": "Runner start through final label verification; excludes reset, initial stability, credentials, pricing, and recording setup/finalization.",
                    "reset": "simctl launch --terminate-running-process; application data preserved",
                    "model_connections": "Fresh per attempt; reused within an attempt",
                    "cost_basis": "Catalog token rates and reported usage; not a provider billing receipt",
                }, "pricing": pricing, "runs": []}
    _write_manifest(directory, manifest)
    callback = emit or (lambda _event: None)
    options = scenario.to_runner_kwargs()
    options["min_probability"] = 0
    for pair, order in enumerate(orders, 1):
        for position, backend in enumerate(order, 1):
            identifier = f"pair-{pair:02d}-{position}-{backend}"
            model_name = MODEL if backend == "jev" else baseline_model
            row = {"id": identifier, "pair": pair, "position": position, "backend": backend,
                   "model": model_name, "status": "error", "reason": "setup_failed",
                   "setup_status": "failed", "timing_valid": False, "setup_elapsed_ms": None,
                   "elapsed_ms": None, "model_ms": [], "model_calls": 0, "actions_executed": 0,
                   "usage": [], "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
                   "estimated_cost_usd": 0, "initial_state_hash": None,
                   "setup_state_hash": None,
                   "matched_labels": [], "expected_labels": list(scenario.expect_labels),
                   "trace": identifier + ".jsonl", "video": None, "video_offset_ms": 0}
            callback({"type": "attempt_start", "id": identifier, "pair": pair, "position": position,
                      "backend": backend, "model": model_name})
            setup_started, run_started, recorder, model = time.perf_counter(), None, None, None
            events, interrupted = [], False
            trace = directory / row["trace"]
            with trace.open("x", encoding="utf-8") as handle:
                trace.chmod(0o600)
                def record(event):
                    events.append(event)
                    handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                    handle.flush()
                try:
                    device = AxeDevice(udid, bundle_id)
                    device._run(["xcrun", "simctl", "launch", "--terminate-running-process", udid, bundle_id])
                    device.launch()
                    initial = _ready_snapshot(device, start_labels)
                    row["setup_state_hash"] = semantic_state_hash(initial)
                    if all(label in initial.labels for label in scenario.expect_labels):
                        raise DeviceError("Starting screen already contains every expected final label")
                    if record_video:
                        recorder = VideoRecorder(udid, directory / (identifier + ".mp4"))
                        recorder.start()
                    model_options = ModelOptions(max_calls=scenario.max_steps)
                    model = JevModel(options=model_options, api_key=api_key) if backend == "jev" else ChatCompletionModel(
                        model=baseline_model, options=model_options, api_key=api_key)
                    row["setup_status"] = "ready"
                    row["setup_elapsed_ms"] = round((time.perf_counter() - setup_started) * 1000, 1)
                    record({"type": "session", "id": identifier, "backend": backend, "model": model_name,
                            "setup_state_hash": row["setup_state_hash"], "min_probability": 0})
                    with model:
                        run_started = time.perf_counter()
                        row["video_offset_ms"] = round((run_started - recorder.started_at) * 1000, 1) if recorder else 0
                        row["timing_valid"] = True
                        guarded_device = _FirstObservationDevice(device, initial, row, record)
                        result = Runner(guarded_device, model, emit=record, **options).run(scenario.goal, scenario.expect_labels)
                    for key in ("status", "reason", "elapsed_ms", "model_ms", "model_calls", "actions_executed", "usage", "matched_labels"):
                        row[key] = result[key]
                except (Exception, KeyboardInterrupt) as exc:
                    interrupted = isinstance(exc, KeyboardInterrupt)
                    row["status"] = "interrupted" if interrupted else "error"
                    row["reason"] = "interrupted" if interrupted else "run_failed" if run_started is not None else "setup_failed"
                    if run_started is None:
                        row["setup_status"] = "failed"
                    row["elapsed_ms"] = round((time.perf_counter() - run_started) * 1000, 1) if run_started is not None else None
                    if isinstance(exc, _InitialStateChanged):
                        row.update(reason="initial_state_changed", setup_status="failed", timing_valid=False, elapsed_ms=None)
                    row["error"] = str(exc) if isinstance(exc, (ModelError, DeviceError)) else type(exc).__name__
                    record({"type": "error", "error": row["error"], "reason": row["reason"]})
                    decisions = [event for event in events if event.get("type") == "decision"]
                    row["model_ms"] = [event["model_ms"] for event in decisions if _finite(event.get("model_ms"))]
                    row["model_calls"] = max(getattr(model, "calls", 0), len(decisions))
                    row["actions_executed"] = sum(event.get("type") == "action" for event in events)
                    row["usage"] = [event["usage"] for event in decisions if isinstance(event.get("usage"), dict)]
                finally:
                    if row["setup_elapsed_ms"] is None:
                        row["setup_elapsed_ms"] = round((time.perf_counter() - setup_started) * 1000, 1)
                    if recorder:
                        try:
                            recorder.stop()
                            row["video"] = identifier + ".mp4"
                        except KeyboardInterrupt:
                            interrupted = True
                            row["artifact_error"] = "Recording finalization interrupted; video omitted"
                            record({"type": "artifact_error", "error": row["artifact_error"]})
                        except Exception:
                            row["artifact_error"] = "Recording finalization failed; video omitted"
            row.update(_cost_stats(row["usage"], row["model_calls"], pricing[backend]))
            manifest["runs"].append(row)
            manifest["summary"] = summarize_comparison(manifest)
            _write_manifest(directory, manifest)
            callback({"type": "attempt_complete", **{key: row[key] for key in (
                "id", "pair", "position", "backend", "status", "reason", "elapsed_ms",
                "model_calls", "actions_executed", "estimated_cost_usd")}})
            if interrupted:
                return manifest
    return manifest
