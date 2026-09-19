"""CLI and NDJSON interface for local callers, including Brigade host adapters."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

from .device import AxeDevice, DeviceError
from .model import JevModel, ModelError, ModelOptions
from .runner import Runner


BASELINE_MODEL = "openai/gpt-5.4-nano"


def model_catalog():
    with urllib.request.urlopen("https://ai-gateway.vercel.sh/v1/models", timeout=10) as response:
        return json.load(response)["data"]


def pricing_bound(max_steps, text_count, budget, *, engine="jev", model_id=None, models=None):
    """Reserve a full context per question, not an optimistic observed token count."""
    models = model_catalog() if models is None else models
    model_id = "typesafe-ai/jev" if engine == "jev" else model_id or BASELINE_MODEL
    model = next((m for m in models if m["id"] == model_id), None)
    if model is None or engine not in {"jev", "baseline"}:
        raise ValueError("Requested model is unavailable in the provider catalog")
    rate = float(model["pricing"]["input"])
    output = float(model["pricing"]["output"])
    context = int(model["context_window"])
    if not math.isfinite(rate) or rate < 0 or not math.isfinite(output) or output < 0 or not 1 <= context <= 2_000_000:
        raise ValueError("Unknown model pricing; cannot establish test budget")
    # At most 120 visible elements; typing adds a value question per field.
    questions = 123 if text_count else 2
    if engine == "jev":
        if output != 0:
            raise ValueError("Unknown Jev output pricing; cannot establish test budget")
        bound = max_steps * questions * context * rate
    else:
        # The complete request is capped at 24,000 UTF-8 bytes. Reserve one
        # token per byte plus framing, and the full 128-token output ceiling.
        bound = max_steps * (24_512 * rate + 128 * output)
    if not math.isfinite(budget) or budget <= 0 or bound > budget:
        raise ValueError(f"Conservative model budget ${bound:.6f} exceeds --budget-usd ${budget:.6f}; reduce steps or disable typing")
    cache = float(model["pricing"].get("input_cache_read", rate))
    if not math.isfinite(cache) or not 0 <= cache <= rate:
        raise ValueError("Unknown cached-input pricing")
    return {"model": model_id, "input_rate_per_million": rate * 1_000_000,
            "output_rate_per_million": output * 1_000_000, "cache_read_rate_per_million": cache * 1_000_000,
            "reserved_usd": round(bound, 6), "max_calls": max_steps, "question_context_tokens": context}


def temporary_vercel_token(project):
    # Never persist or print the provider response, which contains the token.
    result = subprocess.run(["vercel", "project", "token", project, "--format=json"],
                            capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError("Vercel temporary token request failed; check CLI login and project access")
    try:
        payload = json.loads(result.stdout)
        token = payload["token"]
        if not isinstance(token, str) or not token:
            raise ValueError()
        return token
    except (ValueError, KeyError, TypeError):
        raise ValueError("Vercel returned an unrecognized token response") from None


def parser():
    p = argparse.ArgumentParser(description="Jev picks indexed actions; AXe controls a local iOS Simulator.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local tools and credential presence; no model call")
    sub.add_parser("devices", help="List available simulator identifiers")
    report = sub.add_parser("report", help="Create a portable report from an existing trace")
    report.add_argument("--trace", required=True, type=Path)
    report.add_argument("--output", required=True, type=Path)
    report.add_argument("--video", type=Path)
    report.add_argument("--screenshot", type=Path)
    report.add_argument("--video-offset-ms", type=float, default=0)
    compare = sub.add_parser("compare", help="Run matched Jev and JSON-model attempts on the same simulator")
    compare.add_argument("--scenario", required=True, type=Path)
    compare.add_argument("--udid", required=True)
    compare.add_argument("--bundle-id", required=True)
    compare.add_argument("--start-label", required=True, action="append", help="Required initial labels after relaunch")
    compare.add_argument("--output-dir", required=True, type=Path, help="New directory for all attempts and manifest")
    compare.add_argument("--pairs", type=int, choices=range(1, 6), default=3)
    compare.add_argument("--baseline-model", default=BASELINE_MODEL)
    compare.add_argument("--record-video", action=argparse.BooleanOptionalAction, default=True)
    compare.add_argument("--budget-usd", type=float, default=1.0, help="Total conservative admission budget")
    compare.add_argument("--vercel-project")
    comparison_report = sub.add_parser("comparison-report", help="Render every attempt from a comparison manifest")
    comparison_report.add_argument("--manifest", required=True, type=Path)
    comparison_report.add_argument("--output", required=True, type=Path)
    for command in ("inspect", "run"):
        q = sub.add_parser(command)
        q.add_argument("--udid", required=True)
        q.add_argument("--bundle-id", required=True)
        q.add_argument("--axe")
        q.add_argument("--launch", action="store_true", help="Launch the installed app before observing")
        if command == "run":
            q.add_argument("--engine", choices=("jev", "baseline"), default="jev")
            q.add_argument("--baseline-model", default=BASELINE_MODEL)
            q.add_argument("--scenario", type=Path, help="Portable, versioned JSON scenario")
            q.add_argument("--goal")
            q.add_argument("--expect-label", action="append", help="Exact visible label; repeat to require all")
            q.add_argument("--allow-label", action="append", help="Restrict tap candidates to these exact labels")
            q.add_argument("--allow-scroll", action=argparse.BooleanOptionalAction, default=None)
            q.add_argument("--text", action="append", default=[], metavar="KEY=VALUE")
            q.add_argument("--max-steps", type=int, choices=range(1, 31))
            q.add_argument("--min-probability", type=float)
            q.add_argument("--budget-usd", type=float, default=0.1)
            q.add_argument("--vercel-project", help="Use an existing project's temporary development OIDC token")
            q.add_argument("--trace", type=Path)
            q.add_argument("--screenshot", type=Path)
            q.add_argument("--report", type=Path, help="Write a self-contained HTML result report")
            q.add_argument("--record-video", type=Path, help="Capture original-rate simulator video to a new .mp4")
    return p


def scenario_from_args(args):
    from .scenario import Scenario, load_scenario
    if args.scenario:
        if args.goal is not None or args.expect_label is not None:
            raise ValueError("Use either --scenario or --goal with --expect-label")
        base = load_scenario(args.scenario)
    else:
        if not args.goal or not args.expect_label:
            raise ValueError("Supply --scenario or both --goal and --expect-label")
        base = Scenario(name="Simulator run", goal=args.goal, expect_labels=args.expect_label)
    options = base.to_runner_kwargs()
    for key, value in (("max_steps", args.max_steps), ("min_probability", args.min_probability),
                       ("allow_labels", args.allow_label), ("allow_scroll", args.allow_scroll)):
        if value is not None:
            options[key] = value
    for entry in args.text:
        key, sep, value = entry.partition("=")
        if not key or not sep or not value:
            raise ValueError("--text requires a nonempty KEY=VALUE")
        options["text_values"][key] = value
    return Scenario(name=base.name, goal=base.goal, expect_labels=base.expect_labels, **options)


def main(argv=None):
    import signal
    import threading
    import time
    from .report import write_report
    from .recording import VideoRecorder
    args = parser().parse_args(argv)
    handle, recorder = None, None
    previous_term = None
    if threading.current_thread() is threading.main_thread():
        previous_term = signal.getsignal(signal.SIGTERM)
        def interrupt_run(_signum, _frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, interrupt_run)
    events = []
    def emit(event):
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
        events.append(event)
        if handle:
            handle.write(line + "\n")
            handle.flush()
        print(line, flush=True)
    try:
        if args.command == "comparison-report":
            from .comparison_report import write_comparison_report
            if args.manifest.stat().st_size > 16_000_000:
                raise ValueError("Comparison manifest exceeds 16 MB")
            manifest = json.loads(args.manifest.read_text())
            emit({"type": "artifact", "report": write_comparison_report(args.output, manifest, media_root=args.manifest.parent)})
            return 0
        if args.command == "compare":
            from .scenario import load_scenario
            from .comparison import run_comparison
            from .comparison_report import write_comparison_report
            scenario = load_scenario(args.scenario)
            if args.output_dir.exists():
                raise ValueError("Comparison output directory must not already exist")
            models = model_catalog()
            pricing = {engine: pricing_bound(scenario.max_steps, len(scenario.text_values), args.budget_usd,
                       engine=engine, model_id=args.baseline_model, models=models) for engine in ("jev", "baseline")}
            bound = args.pairs * sum(p["reserved_usd"] for p in pricing.values())
            if bound > args.budget_usd:
                raise ValueError(f"Conservative comparison budget ${bound:.6f} exceeds --budget-usd")
            emit({"type": "budget", "reserved_usd": round(bound, 6), "attempts": args.pairs * 2, "pricing": pricing})
            key = temporary_vercel_token(args.vercel_project) if args.vercel_project else None
            manifest = run_comparison(scenario=scenario, udid=args.udid, bundle_id=args.bundle_id,
                output_dir=args.output_dir, api_key=key, pricing=pricing, baseline_model=args.baseline_model,
                pairs=args.pairs, start_labels=args.start_label, record_video=args.record_video, emit=emit)
            report_path = args.output_dir / "comparison.html"
            write_comparison_report(report_path, manifest, media_root=args.output_dir)
            emit({"type": "artifact", "report": str(report_path), "manifest": str(args.output_dir / "comparison.json")})
            return 0 if all(r["status"] == "verified" for r in manifest["runs"]) else 2
        if args.command == "report":
            if args.trace.stat().st_size > 16_000_000:
                raise ValueError("Trace exceeds 16 MB")
            trace_events = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
            emit({"type": "artifact", "report": write_report(args.output, trace_events, video=args.video,
                  screenshot=args.screenshot, video_offset_ms=args.video_offset_ms)})
            return 0
        if args.command == "devices":
            completed = subprocess.run(["xcrun", "simctl", "list", "devices", "available", "--json"],
                                       capture_output=True, text=True, timeout=20, check=True)
            available = json.loads(completed.stdout)["devices"]
            emit({"type": "devices", "devices": [dict(name=d["name"], udid=d["udid"], state=d["state"], runtime=runtime)
                 for runtime, group in available.items() for d in group]})
            return 0
        if args.command == "doctor":
            import shutil
            from .device import find_axe
            emit({"type": "doctor", "axe": find_axe(), "xcrun": bool(shutil.which("xcrun")),
                  "gateway_credential_present": bool(os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN")),
                  "vercel_cli_present": bool(shutil.which("vercel")), "platform": sys.platform})
            return 0
        scenario = scenario_from_args(args) if args.command == "run" else None
        if scenario and args.engine == "baseline" and scenario.min_probability != 0:
            raise ValueError("The baseline does not report confidence; explicitly set --min-probability 0")
        # Validate all artifact destinations before launching or making a model call.
        if scenario:
            paths = [p.resolve() for p in (args.trace, args.screenshot, args.report, args.record_video) if p]
            if len(paths) != len(set(paths)) or any(p.exists() for p in paths):
                raise ValueError("Artifact paths must be distinct and must not already exist")
            if args.record_video and args.record_video.suffix.lower() != ".mp4":
                raise ValueError("--record-video requires a .mp4 path")
        device = AxeDevice(args.udid, args.bundle_id, axe_path=args.axe)
        if args.launch:
            device.launch()
        if args.command == "inspect":
            emit({"type": "observation", **device.observe().as_dict()})
            return 0
        if args.trace:
            args.trace.parent.mkdir(parents=True, exist_ok=True)
            handle = args.trace.open("x", encoding="utf-8")
            os.chmod(args.trace, 0o600)
        bound = pricing_bound(scenario.max_steps, len(scenario.text_values), args.budget_usd,
                              engine=args.engine, model_id=args.baseline_model)
        emit({"type": "budget", **bound})
        key = temporary_vercel_token(args.vercel_project) if args.vercel_project else None
        if args.record_video:
            recorder = VideoRecorder(args.udid, args.record_video)
            recorder.start()
        video_offset_ms = (time.perf_counter() - recorder.started_at) * 1000 if recorder else 0
        emit({"type": "session", "scenario": scenario.name, "engine": args.engine, "model": bound["model"],
              "video_offset_ms": round(video_offset_ms, 1)})
        from .baseline import ChatCompletionModel
        selected_model = JevModel(ModelOptions(max_calls=scenario.max_steps), api_key=key) if args.engine == "jev" else ChatCompletionModel(
            args.baseline_model, ModelOptions(max_calls=scenario.max_steps), api_key=key)
        with selected_model as model:
            result = Runner(device, model, emit=emit, **scenario.to_runner_kwargs()).run(scenario.goal, scenario.expect_labels)
        if recorder:
            recorder.stop()
            recorder = None
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            device.screenshot(args.screenshot)
        if args.report:
            emit({"type": "artifact", "report": write_report(args.report, events, video=args.record_video,
                  screenshot=args.screenshot, title=scenario.name, video_offset_ms=video_offset_ms)})
        return 0 if result["status"] == "verified" else 2
    except (Exception, KeyboardInterrupt) as exc:
        safe = str(exc) if isinstance(exc, (ValueError, DeviceError, ModelError)) else type(exc).__name__
        emit({"type": "error", "error": safe})
        return 1
    finally:
        if recorder:
            try:
                recorder.stop()
            except Exception:
                emit({"type": "error", "error": "Recording finalization failed"})
        if handle:
            handle.close()
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
