"""Portable paired benchmark playback, with only explicitly public data embedded."""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import statistics


MAX_VIDEO_BYTES = 40_000_000
MAX_RUNS = 20
STATUSES = {"verified", "blocked", "uncertain", "unverified", "stopped", "error", "interrupted", "setup_failed"}


def _text(value, name, maximum=4000, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"Comparison {name} must be a bounded string")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"Comparison {name} must be valid Unicode") from None
    return value


def _number(value, name, *, integer=False, maximum=2 ** 53 - 1):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"Comparison {name} must be a bounded finite nonnegative number")
    return value


def _labels(value, name):
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError(f"Comparison {name} must be a bounded label list")
    return [_text(label, name, 300) for label in value]


def _relative_path(value, name):
    value = _text(value, name, 400)
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or ":" in value or "\x00" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"Comparison {name} must be a safe relative path")
    return value


def _run(raw):
    if not isinstance(raw, dict):
        raise ValueError("Comparison runs must be objects")
    if not isinstance(raw.get("backend"), str) or not isinstance(raw.get("status"), str) or raw["backend"] not in {"jev", "baseline"} or raw["status"] not in STATUSES:
        raise ValueError("Comparison run backend or status is invalid")
    timings = raw.get("model_ms")
    usage = raw.get("usage", [])
    if not isinstance(timings, list) or len(timings) > 30 or not isinstance(usage, list) or len(usage) > 30:
        raise ValueError("Comparison model timings and usage must be bounded lists")
    normalized = {
        "id": _text(raw.get("id"), "run id", 100),
        "pair": _number(raw.get("pair"), "pair", integer=True, maximum=10),
        "position": _number(raw.get("position"), "position", integer=True, maximum=2),
        "backend": raw["backend"], "model": _text(raw.get("model"), "model", 200),
        "status": raw["status"], "reason": _text(raw.get("reason"), "reason", 4000),
        "elapsed_ms": None if raw.get("elapsed_ms") is None else _number(raw["elapsed_ms"], "elapsed time"),
        "model_ms": [_number(value, "request latency") for value in timings],
        "model_calls": _number(raw.get("model_calls"), "model calls", integer=True, maximum=30),
        "actions_executed": _number(raw.get("actions_executed"), "actions", integer=True, maximum=30),
        "input_tokens": _number(raw.get("input_tokens", 0), "input tokens", integer=True),
        "output_tokens": _number(raw.get("output_tokens", 0), "output tokens", integer=True),
        "cached_input_tokens": _number(raw.get("cached_input_tokens", 0), "cached input tokens", integer=True),
        "estimated_cost_usd": None if raw.get("estimated_cost_usd") is None else _number(raw["estimated_cost_usd"], "estimated cost"),
        "initial_state_hash": None if raw.get("initial_state_hash") is None else _text(raw["initial_state_hash"], "initial state hash", 200),
        "expected_labels": _labels(raw.get("expected_labels"), "expected labels"),
        "matched_labels": _labels(raw.get("matched_labels"), "matched labels"),
        "trace": None if raw.get("trace") is None else _relative_path(raw["trace"], "trace"),
        "video": None if raw.get("video") is None else _relative_path(raw["video"], "video"),
        "video_offset_ms": _number(raw.get("video_offset_ms", 0), "video offset"),
    }
    if normalized["pair"] < 1 or normalized["position"] < 1:
        raise ValueError("Comparison pair and position are one-based")
    if not normalized["expected_labels"] or any(label not in normalized["expected_labels"] for label in normalized["matched_labels"]):
        raise ValueError("Comparison expected and matched labels are inconsistent")
    if normalized["status"] == "verified" and set(normalized["matched_labels"]) != set(normalized["expected_labels"]):
        raise ValueError("Verified comparison run must match every expected label")
    normalized["usage"] = []
    for item in usage:
        if not isinstance(item, dict):
            raise ValueError("Comparison usage must contain objects")
        normalized["usage"].append({key: _number(item[key], "usage tokens", integer=True)
                                    for key in ("inputTokens", "outputTokens", "totalTokens", "cachedInputTokens", "cacheReadInputTokens", "cacheWriteInputTokens", "reasoningOutputTokens") if key in item})
    setup_status = raw.get("setup_status")
    if not isinstance(setup_status, str) or setup_status not in {"ready", "failed", "error", "not_started"}:
        raise ValueError("Comparison setup status is invalid")
    normalized["setup_status"] = setup_status
    normalized["setup_elapsed_ms"] = _number(raw.get("setup_elapsed_ms"), "setup time")
    if type(raw.get("timing_valid")) is not bool:
        raise ValueError("Comparison timing_valid must be a boolean")
    normalized["timing_valid"] = raw["timing_valid"]
    if normalized["timing_valid"] and normalized["elapsed_ms"] is None:
        raise ValueError("A timed comparison run must include elapsed time")
    if len(normalized["model_ms"]) > normalized["model_calls"] or normalized["cached_input_tokens"] > normalized["input_tokens"]:
        raise ValueError("Comparison call or cached-token counts are inconsistent")
    if raw.get("artifact_error") is not None:
        normalized["artifact_error"] = _text(raw["artifact_error"], "artifact error", 4000)
    if raw.get("error") is not None:
        normalized["error"] = _text(raw["error"], "run error", 4000)
    for key in ("trace_sha256", "first_observation_elements_sha256"):
        if key in raw:
            value = _text(raw[key], key, 64)
            if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise ValueError(f"Comparison {key} must be a SHA-256 digest")
            normalized[key] = value
    if "cohort" in raw:
        normalized["cohort"] = _number(raw["cohort"], "cohort", integer=True, maximum=10)
        if normalized["cohort"] < 1:
            raise ValueError("Comparison cohort is one-based")
    return normalized


def _metadata(raw, allowed_text, allowed_numbers):
    if not isinstance(raw, dict):
        raise ValueError("Comparison metadata must be an object")
    public = {key: _text(raw[key], key, 4000) for key in allowed_text if key in raw}
    public.update({key: None if raw[key] is None else _number(raw[key], key) for key in allowed_numbers if key in raw})
    return public


def _manifest(raw):
    if not isinstance(raw, dict) or raw.get("schema") != "jev-ios/comparison/v1":
        raise ValueError("Comparison manifest schema is invalid")
    runs = raw.get("runs")
    if not isinstance(runs, list) or not 1 <= len(runs) <= MAX_RUNS:
        raise ValueError("Comparison needs one to twenty run attempts")
    scenario = raw.get("scenario")
    if not isinstance(scenario, dict):
        raise ValueError("Comparison scenario must be an object")
    public = {"schema": raw["schema"], "scenario": {
        "name": _text(scenario.get("name"), "scenario name", 300),
        "goal": _text(scenario.get("goal"), "goal"),
        "expect_labels": _labels(scenario.get("expect_labels"), "scenario expected labels"),
        "max_steps": _number(scenario.get("max_steps"), "max steps", integer=True, maximum=30),
    }, "runs": [_run(run) for run in runs]}
    if public["scenario"]["max_steps"] < 1 or not public["scenario"]["expect_labels"]:
        raise ValueError("Comparison scenario needs labels and a positive step limit")
    ids = [run["id"] for run in public["runs"]]
    keys = [(run["pair"], run["backend"]) for run in public["runs"]]
    positions = [(run["pair"], run["position"]) for run in public["runs"]]
    if len(set(ids)) != len(ids) or len(set(keys)) != len(keys) or len(set(positions)) != len(positions):
        raise ValueError("Comparison contains duplicate run ids, backends, or positions")
    for run in public["runs"]:
        if run["expected_labels"] != public["scenario"]["expect_labels"]:
            raise ValueError("Comparison run labels must match its scenario")
    settings = raw.get("settings", {})
    public["settings"] = _metadata(settings, {"timing_boundary", "reset_policy", "reset", "state_comparison", "model_connections", "cost_basis", "confidence_policy"},
                                    {"max_steps", "min_probability", "confidence_gate", "pairs", "settle_seconds", "temperature", "request_timeout_seconds", "max_request_bytes"})
    if "pairs" in settings:
        count = _number(settings["pairs"], "scheduled pairs", integer=True, maximum=10)
        if count < 1 or any(run["pair"] > count for run in public["runs"]):
            raise ValueError("Comparison attempts must fit within the scheduled pairs")
    if "baseline_request" in settings:
        public["settings"]["baseline_request"] = _metadata(settings["baseline_request"],
            {"reasoning_effort", "profile", "model", "temperature_policy", "output_token_policy"}, {"temperature", "max_output_tokens"})
    for key in ("allow_scroll",):
        if key in scenario:
            if type(scenario[key]) is not bool:
                raise ValueError(f"Comparison scenario {key} must be a boolean")
            public["scenario"][key] = scenario[key]
    if "start_labels" in settings:
        public["settings"]["start_labels"] = _labels(settings["start_labels"], "starting labels")
    if "record_video" in settings:
        if type(settings["record_video"]) is not bool:
            raise ValueError("Comparison record_video must be a boolean")
        public["settings"]["record_video"] = settings["record_video"]
    if "allow_scroll" in settings:
        if type(settings["allow_scroll"]) is not bool:
            raise ValueError("Comparison allow_scroll must be a boolean")
        public["settings"]["allow_scroll"] = settings["allow_scroll"]
    if "orders" in settings:
        orders = settings["orders"]
        if not isinstance(orders, list) or len(orders) > 10 or any(not isinstance(order, list) or len(order) != 2 or any(not isinstance(item, str) for item in order) or sorted(order) != ["baseline", "jev"] for order in orders):
            raise ValueError("Comparison orders must contain paired backend orders")
        public["settings"]["orders"] = orders
    pricing = raw.get("pricing", {})
    if not isinstance(pricing, dict):
        raise ValueError("Comparison pricing must be an object")
    public["pricing"] = {}
    for backend in ("jev", "baseline"):
        if backend in pricing:
            public["pricing"][backend] = _metadata(pricing[backend], {"model", "source", "retrieved_at", "currency", "note"},
                {"input", "output", "cached_input", "input_per_token", "output_per_token", "cached_input_per_token", "context_window", "maximum_output_tokens", "input_rate_per_million", "output_rate_per_million", "cache_read_rate_per_million", "cache_write_rate_per_million", "reserved_usd", "max_calls", "context"})
    for key in ("created_at", "source_revision"):
        if key in raw:
            public[key] = _text(raw[key], key, 200)
    if "provenance" in raw:
        provenance = raw["provenance"]
        public["provenance"] = _metadata(provenance, {"source_commit", "app_binary_sha256", "scenario_sha256", "ios_runtime", "appearance", "content_size", "preflight", "notes"}, set())
        if "cohorts" in provenance:
            if not isinstance(provenance["cohorts"], list) or len(provenance["cohorts"]) > 10:
                raise ValueError("Comparison provenance cohorts must be a bounded list")
            public["provenance"]["cohorts"] = []
            for cohort in provenance["cohorts"]:
                if not isinstance(cohort, dict):
                    raise ValueError("Comparison provenance cohorts must be objects")
                entry = {"cohort": _number(cohort.get("cohort"), "cohort", integer=True, maximum=10),
                         "source_pairs": _number(cohort.get("source_pairs"), "source pairs", integer=True, maximum=5),
                         "created_at": _text(cohort.get("created_at"), "cohort creation", 200)}
                if not entry["cohort"] or not entry["source_pairs"]:
                    raise ValueError("Comparison cohort and source pair counts must be positive")
                public["provenance"]["cohorts"].append(entry)
    return public


def _video_bytes(root, relative):
    if not relative.lower().endswith(".mp4"):
        raise ValueError("Comparison video must be an MP4 file")
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError("Comparison video must stay within its media root")
    if not path.is_file():
        raise ValueError("Comparison video must be an existing file")
    if path.stat().st_size > MAX_VIDEO_BYTES:
        raise ValueError("Comparison video must be at most 40 MB")
    with path.open("rb") as handle:
        data = handle.read(MAX_VIDEO_BYTES + 1)
    if len(data) > MAX_VIDEO_BYTES:
        raise ValueError("Comparison video grew beyond 40 MB")
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise ValueError("Comparison video has an invalid media header")
    return data


def write_comparison_report(path, manifest, *, media_root=Path(".")):
    """Write a new self-contained report; never overwrite an existing artifact."""
    from .comparison import summarize_comparison

    public = _manifest(manifest)
    public["summary"] = summarize_comparison(public)
    paired = [pair for pair in public["summary"]["pairs"] if pair.get("baseline_over_jev") is not None]
    lookup = {run["id"]: run for run in public["runs"]}
    public["paired_median_elapsed_ms"] = {backend: statistics.median([lookup[pair[f"{backend}_id"]]["elapsed_ms"] for pair in paired]) if paired else None
                                         for backend in ("jev", "baseline")}
    try:
        root = Path(media_root).resolve()
        output = Path(path)
    except (TypeError, ValueError):
        raise ValueError("Comparison media root or output path is invalid") from None
    if not root.is_dir():
        raise ValueError("Comparison media root must be an existing directory")
    media = []
    for index, run in enumerate(public["runs"]):
        run["media_id"] = None
        if run["video"] is not None:
            payload = base64.b64encode(_video_bytes(root, run["video"])).decode("ascii")
            run["media_id"] = f"media-{index}"
            media.append(f'<template id="media-{index}"><video playsinline preload="metadata" muted src="data:video/mp4;base64,{payload}"></video></template>')
    encoded = json.dumps(public, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    replacements = {"__DATA__": encoded, "__MEDIA__": "".join(media)}
    content = re.sub(r"__(?:DATA|MEDIA)__", lambda match: replacements[match[0]], TEMPLATE)
    output.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        handle.write(content)
    return str(output)


TEMPLATE = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jev / iOS — the same task, twice</title>
<style>
:root{color-scheme:dark;--bg:#131411;--panel:#1c1e19;--border:#34382e;--ink:#f2f3e8;--muted:#a4aa99;--lime:#d7f68a;--blue:#c3d4ef;--warn:#f3c7a1}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased}button,input{font:inherit}button{cursor:pointer}header{padding:25px 5vw;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border)}.brand{font-size:24px;font-weight:650;letter-spacing:-.7px}.brand span{font-weight:400;color:var(--muted)}.pill{border:1px solid #465431;border-radius:30px;padding:8px 13px;color:var(--lime);font:11px ui-monospace,monospace;letter-spacing:1px}main{max-width:1460px;margin:auto;padding:45px 5vw 65px}.eyebrow{font:11px ui-monospace,monospace;color:var(--lime);letter-spacing:2px;margin-bottom:14px}h1{font-size:clamp(35px,4.5vw,65px);font-weight:580;letter-spacing:-2.7px;line-height:1.02;margin:0 0 22px;max-width:980px}h2{font-size:23px;font-weight:550;letter-spacing:-.6px;margin:0}p{line-height:1.65}.lede{color:var(--muted);font-size:16px;max-width:890px;margin:0 0 30px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:22px;padding:25px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}.metric-value{font-size:clamp(28px,3vw,44px);font-variant-numeric:tabular-nums;letter-spacing:-1.8px}.lime{color:var(--lime)}.blue{color:var(--blue)}.metric-label{font-size:12px;color:var(--muted);line-height:1.6;margin-top:5px}.note{font-size:12px;color:var(--muted);line-height:1.7;margin:13px 0 30px}.section-heading{display:flex;justify-content:space-between;align-items:center;gap:15px;margin:34px 0 20px}.pairs{display:flex;gap:7px;flex-wrap:wrap}.pairs button,.button{color:var(--ink);border:1px solid var(--border);background:var(--panel);border-radius:9px;padding:10px 13px}.pairs button[aria-pressed=true]{border-color:var(--lime);color:var(--lime)}.players{display:grid;grid-template-columns:1fr 1fr;gap:24px}.player{background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:21px}.player-heading{display:flex;justify-content:space-between;gap:10px;margin-bottom:8px}.backend{font-size:19px;font-weight:600}.player-meta{font:11px ui-monospace,monospace;color:var(--muted);line-height:1.6;margin-bottom:20px;overflow-wrap:anywhere}.status{font:10px ui-monospace,monospace;border:1px solid var(--border);border-radius:20px;padding:6px 8px;height:fit-content;color:var(--warn)}.status.verified{color:var(--lime);border-color:#465431}.device{max-width:295px;margin:0 auto;background:#080907;padding:8px;border:1px solid #515648;border-radius:35px;overflow:hidden;box-shadow:0 15px 40px #0004;aspect-ratio:0.462}.device video{display:block;width:100%;border-radius:26px;background:#080907}.empty{font-size:13px;color:var(--muted);display:grid;align-content:center;text-align:center;height:100%;padding:25px;line-height:1.8}.player-results{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:22px;text-align:center}.small-value{font-size:21px;font-variant-numeric:tabular-nums}.small-label{font-size:10px;color:var(--muted);line-height:1.5;margin-top:5px}.playback{display:flex;align-items:center;gap:14px;margin-top:20px;padding:18px;border:1px solid var(--border);border-radius:12px}.playback input{flex:1;accent-color:var(--lime);min-width:70px}.clock{font:12px ui-monospace,monospace;color:var(--muted);min-width:83px}.pair-note{font-size:12px;color:var(--muted);line-height:1.7;margin:12px 0}.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:13px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;padding:14px 13px;border-bottom:1px solid var(--border);vertical-align:top;white-space:nowrap}th{font:10px ui-monospace,monospace;color:var(--muted);letter-spacing:.4px;background:var(--panel)}tbody tr:last-child td{border-bottom:0}.run-cell{font-weight:550}.sub{font-size:10px;color:var(--muted);margin-top:5px;line-height:1.6;white-space:normal;max-width:350px}.failure{color:var(--warn)}.methods{display:grid;grid-template-columns:1fr 1fr;gap:30px;border-top:1px solid var(--border);padding-top:28px;margin-top:35px}.methods h3{font-size:14px;margin:0 0 10px}.methods p{font-size:12px;color:var(--muted);margin:8px 0}.mono{font-family:ui-monospace,monospace}.footer{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:25px}.footer p{color:var(--muted);font-size:11px}.compare-note{color:var(--warn)}@media(max-width:760px){main{padding:30px 18px}header{padding:20px}.pill{font-size:9px}.metrics{grid-template-columns:1fr 1fr;gap:24px}.section-heading{align-items:flex-start;flex-direction:column}.players{gap:10px}.player{padding:13px 9px;border-radius:14px}.backend{font-size:16px}.player-heading{flex-direction:column;gap:7px}.status{align-self:flex-start}.player-meta{font-size:9px;min-height:30px}.device{padding:4px;border-radius:25px}.device video{border-radius:20px}.player-results{grid-template-columns:1fr;gap:12px}.small-value{font-size:20px}.methods{grid-template-columns:1fr;gap:15px}.playback{gap:9px;padding:12px}.button{padding:9px}.clock{font-size:10px;min-width:65px}.footer{align-items:flex-start;flex-direction:column}.metric-value{font-size:34px}h1{letter-spacing:-1.6px}.table-wrap{margin:0 -2px}}
</style>
<header><div class="brand">jev<span> / iOS</span></div><div class="pill">PAIRED SIMULATOR RUNS</div></header>
<main><div class="eyebrow">SAME APP. SAME GOAL. SAME LOCAL RUNNER.</div><h1>The same task.<br>Two decision engines.</h1><p class="lede" id="goal"></p>
<div class="metrics"><div><div id="jev-total" class="metric-value lime"></div><div class="metric-label">Jev · paired median full run</div></div><div><div id="baseline-total" class="metric-value blue"></div><div class="metric-label">Baseline · paired median full run</div></div><div><div id="paired-ratio" class="metric-value"></div><div class="metric-label">Baseline time ÷ Jev time<br>Median of verified pair ratios</div></div><div><div id="verified" class="metric-value"></div><div class="metric-label">Verified attempts · Jev / baseline</div></div></div>
<p class="note" id="summary-note"></p>
<div class="section-heading"><h2>Watch the difference</h2><div class="pairs" id="pairs" aria-label="Choose a recorded pair"></div></div>
<p class="pair-note" id="replay-selection"></p>
<div class="players" id="players"></div>
<div class="playback"><button class="button" id="play">Play pair</button><button class="button" id="restart">Restart</button><input id="scrub" type="range" min="0" max="100" value="0" step="0.01" aria-label="Playback time"><span class="clock" id="clock">0.0 / 0.0 s</span></div><p class="pair-note" id="playback-status" aria-live="polite"></p>
<p class="pair-note" id="pair-note"></p><p class="pair-note">Each recording was captured separately. Playback starts at runner-zero, stays at 1×, and pauses to preserve alignment if decoding stalls. The shorter video holds its final frame. The clock shows recording time, including any captured tail. Simulator captures can omit a trailing static wait and end before the measured task; measured task duration appears above.</p>
<div class="section-heading"><h2>Every attempt is counted</h2><span class="note" style="margin:0">Failures remain in the table and success rate.</span></div>
<div class="table-wrap"><table><thead><tr><th>PAIR / ORDER</th><th>ENGINE / OUTCOME</th><th>FULL RUN</th><th>MEDIAN REQUEST</th><th>ACTIONS / CALLS</th><th>REPORTED INPUT / OUTPUT</th><th>EST. COST</th></tr></thead><tbody id="attempts"></tbody></table></div>
<div class="methods"><div><h3>What is held constant</h3><p id="shared-settings"></p><p>The goal, expected labels, observed accessibility state, action menu, local freshness checks, input execution, and final verification are shared. Each attempt restarts the app; stored application data is preserved. Starting labels and a stable accessibility snapshot are checked. Any initial-state mismatch excludes the cohort from speed comparison.</p><p>Jev chooses from categorical answers. The baseline generates a structured decision using the same offered operations and targets. Their transports and output formats differ.</p></div><div><h3>How to read these numbers</h3><p id="timing-boundary"></p><p>Full-run times include model calls and local device work. Request latency is measured at the client and includes network and provider processing. Its median is calculated over available call timings, including failed attempts; it is a separate measure from full-run speed.</p><p>Only pairs where both runs verified and shared the same initial state contribute speed ratios. This small local experiment measures these models, this scenario, and this machine. It does not establish a general winner. Costs are estimates from recorded usage and provider pricing, not billing readback.</p></div></div>
<div class="footer"><p id="inference-summary"></p><button class="button" id="download">Download comparison data</button></div>
</main>__MEDIA__<script type="application/json" id="comparison-data">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('comparison-data').textContent),summary=data.summary;
const $=id=>document.getElementById(id),set=(id,value)=>$(id).textContent=value;
const sec=ms=>ms===null?'—':(ms/1000).toFixed(2)+' s',ms=t=>t===null?'—':Math.round(t)+' ms',median=a=>a.length?[...a].sort((x,y)=>x-y).reduce((_,v,i,b)=>i===Math.floor(b.length/2)?(b.length%2?v:(b[i-1]+v)/2):_,0):null;
set('goal',data.scenario.goal);set('jev-total',sec(data.paired_median_elapsed_ms.jev));set('baseline-total',sec(data.paired_median_elapsed_ms.baseline));set('paired-ratio',summary.median_paired_speedup===null?'—':summary.median_paired_speedup.toFixed(2)+'×');
set('verified',summary.backends.jev.verified+'/'+summary.backends.jev.attempted+' · '+summary.backends.baseline.verified+'/'+summary.backends.baseline.attempted);
set('summary-note',summary.paired_verified_count+' pair'+(summary.paired_verified_count===1?'':'s')+' verified by both engines contribute to the elapsed-time comparison. '+data.runs.length+' of '+(2*(data.settings.pairs??Math.max(...data.runs.map(r=>r.pair))))+' scheduled attempts recorded. Failed, incomplete, or mismatched pairs do not become fast winners.');
set('shared-settings','Scenario: '+data.scenario.name+' · '+data.scenario.max_steps+' maximum steps · '+((data.scenario.allow_scroll??data.settings.allow_scroll)?'scrolling allowed':'no scrolling')+'. Shared confidence gate: '+(data.settings.confidence_gate??data.settings.min_probability??'not recorded')+'.');
if(data.settings.baseline_request){const request=data.settings.baseline_request;set('shared-settings',$('shared-settings').textContent+' Baseline reasoning: '+request.reasoning_effort+'; temperature: '+(request.temperature===null?'omitted':request.temperature)+'; generation cap: '+request.max_output_tokens+' tokens including reasoning.');}
set('timing-boundary',data.settings.timing_boundary||'Timing begins with the runner and ends at its final result. Setup and app reset are outside that boundary.');
set('inference-summary','Recorded-call median latency — Jev: '+ms(summary.backends.jev.median_request_ms)+'; baseline: '+ms(summary.backends.baseline.median_request_ms)+'. Requests without recorded timing: Jev '+(summary.backends.jev.requests_without_timing??0)+', baseline '+(summary.backends.baseline.requests_without_timing??0)+'.');
const element=(tag,className,text)=>{const e=document.createElement(tag);if(className)e.className=className;if(text!==undefined)e.textContent=text;return e;};
data.runs.forEach(r=>{const tr=element('tr');tr.append(element('td','',(r.cohort?'Cohort '+r.cohort+' · ':'')+'Pair '+r.pair+' · #'+r.position));const who=element('td');who.append(element('div','run-cell '+(r.backend==='jev'?'lime':'blue'),r.backend==='jev'?'Jev':'Baseline'),element('div','sub',r.model),element('div','sub '+(r.status==='verified'?'':'failure'),r.status+' · '+r.reason));if(r.error)who.append(element('div','sub failure',r.error));if(r.setup_status!=='ready')who.append(element('div','sub failure','Setup: '+r.setup_status));if(r.artifact_error)who.append(element('div','sub failure','Recording/report: '+r.artifact_error));tr.append(who,element('td','',r.timing_valid?sec(r.elapsed_ms):'Not timed'),element('td','',ms(median(r.model_ms))),element('td','',r.actions_executed+' / '+r.model_calls));const tokens=element('td','',r.input_tokens.toLocaleString()+' / '+r.output_tokens.toLocaleString());if(r.cached_input_tokens)tokens.append(element('div','sub',r.cached_input_tokens.toLocaleString()+' cached input'));tr.append(tokens,element('td','',r.estimated_cost_usd===null?'Unknown':'$'+r.estimated_cost_usd.toFixed(6)));$('attempts').append(tr);});
/*PAIRED_PLAYBACK*/
const playback=createPairedPlayback({playButton:$('play'),range:$('scrub'),clock:$('clock'),status:$('playback-status')});
function selectPair(pair){
  playback.clear();$('players').replaceChildren();
  const rows=data.runs.filter(r=>r.pair===pair.pair),entries=[];
  document.querySelectorAll('#pairs button').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.pair)===pair.pair)));
  for(const backend of ['jev','baseline']){
    const r=rows.find(r=>r.backend===backend),card=element('section','player'),heading=element('div','player-heading');
    heading.append(element('div','backend '+(backend==='jev'?'lime':'blue'),backend==='jev'?'Jev':'Without Jev'),element('span','status '+(r?.status==='verified'?'verified':''),r?.status||'not attempted'));
    card.append(heading,element('div','player-meta',r?r.model+' · execution #'+r.position:'No attempt recorded'));
    const device=element('div','device');
    if(r?.media_id){const fragment=$(r.media_id).content.cloneNode(true),video=fragment.querySelector('video');device.append(fragment);entries.push({video,offset:r.video_offset_ms/1000});}
    else device.append(element('div','empty',r?'No recording attached. This attempt still counts.':'No attempt was recorded for this engine.'));
    card.append(device);const stats=element('div','player-results');
    for(const [value,label] of [[r&&r.timing_valid?sec(r.elapsed_ms):'—','measured task'],[r?ms(median(r.model_ms)):'—','median request'],[r?r.actions_executed:'—','actions']]){const stat=element('div');stat.append(element('div','small-value',value),element('div','small-label',label));stats.append(stat);}
    card.append(stats);$('players').append(card);
  }
  set('pair-note','Pair '+pair.pair+' · '+(pair.comparable?'Same initial state. ':'Excluded from speed comparison. ')+pair.reason+(pair.baseline_over_jev!==null?' · Baseline / Jev elapsed time: '+pair.baseline_over_jev.toFixed(2)+'×.':''));
  playback.mount(entries);
}
summary.pairs.forEach(pair=>{const b=element('button','','Pair '+pair.pair);b.dataset.pair=pair.pair;b.setAttribute('aria-pressed','false');b.onclick=()=>selectPair(pair);$('pairs').append(b);});
$('play').onclick=()=>playback.toggle();$('restart').onclick=()=>playback.seek(0);$('scrub').oninput=event=>playback.seek(Number(event.target.value));
$('download').onclick=()=>{const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),a=element('a');a.href=URL.createObjectURL(blob);a.download='jev-ios-comparison.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
if(summary.pairs.length){const first=summary.pairs.find(pair=>pair.baseline_over_jev!==null)||summary.pairs[0];set('replay-selection',first.baseline_over_jev!==null?'Replay opens on Pair '+first.pair+', a pair verified by both engines. '+summary.paired_verified_count+' of '+summary.pairs.length+' recorded pairs passed on both sides; every attempt remains below.':'No mutually verified pair is available. Replay opens on the first recorded pair; every attempt remains below.');selectPair(first);}
</script></html>'''


PLAYBACK_SCRIPT = r'''
function createPairedPlayback(ui){
  let entries=[],generation=0,mode='empty',cursor=0,duration=0,frame=null;
  const cancellations=new Set(),epsilon=.03;
  const progress=item=>Math.max(0,item.video.currentTime-item.offset);
  const endpoint=item=>Math.max(0,item.video.duration-item.offset-.025);
  const atEnd=item=>Number.isFinite(item.video.duration)&&progress(item)>=endpoint(item);
  function render(){
    ui.clock.textContent=cursor.toFixed(1)+' / '+duration.toFixed(1)+' s';
    ui.range.max=String(duration);ui.range.value=String(cursor);
    ui.range.disabled=['empty','loading','error'].includes(mode);
    ui.playButton.disabled=['empty','loading','error'].includes(mode);
    ui.playButton.textContent=['playing','starting','buffering'].includes(mode)?'Pause':'Play pair';
    ui.status.textContent=({empty:'No recording is attached.',loading:'Preparing recording playback…',error:'Playback unavailable. The recorded measurements remain in the table.',buffering:'Playback paused while a recording buffers.',starting:'Starting both recordings…'})[mode]||'Playback time · recording duration, not the task timer · 1×';
  }
  function invalidate(){
    generation++;if(frame!==null)cancelAnimationFrame(frame);frame=null;
    for(const cancel of [...cancellations])cancel();
    entries.forEach(item=>{item.video.pause();item.pending=false;});
    return generation;
  }
  function pause(){invalidate();mode=entries.length?'paused':'empty';render();}
  function clear(){invalidate();entries=[];cursor=0;duration=0;mode='empty';render();}
  function waitFor(item,predicate,token){
    if(token!==generation)return Promise.resolve(false);
    if(predicate())return Promise.resolve(true);
    return new Promise(resolve=>{
      let timer;const events=['loadedmetadata','loadeddata','canplay','seeked','progress'];
      const finish=value=>{clearTimeout(timer);events.forEach(name=>item.video.removeEventListener(name,check));item.video.removeEventListener('error',failed);cancellations.delete(cancel);resolve(value);};
      const cancel=()=>finish(false),failed=()=>finish(false),check=()=>{if(token!==generation)finish(false);else if(predicate())finish(true);};
      events.forEach(name=>item.video.addEventListener(name,check));item.video.addEventListener('error',failed);cancellations.add(cancel);timer=setTimeout(failed,15000);check();
    });
  }
  async function seek(seconds){
    const token=invalidate();cursor=Math.max(0,Number.isFinite(seconds)?seconds:0);mode=entries.length?'loading':'empty';render();
    if(!entries.length)return false;
    const metadata=await Promise.all(entries.map(item=>waitFor(item,()=>item.video.readyState>=1&&Number.isFinite(item.video.duration),token)));
    if(token!==generation)return false;
    if(metadata.some(ready=>!ready)||entries.some(item=>item.offset<0||item.offset>=item.video.duration)){mode='error';render();return false;}
    duration=Math.max(...entries.map(item=>item.video.duration-item.offset));cursor=Math.min(duration,cursor);
    for(const item of entries){item.video.playbackRate=1;item.video.currentTime=Math.min(Math.max(0,item.video.duration-.025),Math.max(0,cursor+item.offset));}
    const ready=await Promise.all(entries.map(item=>waitFor(item,()=>!item.video.seeking&&item.video.readyState>=(atEnd(item)?2:3),token)));
    if(token!==generation)return false;
    mode=ready.every(Boolean)?'paused':'error';render();return mode==='paused';
  }
  function requestPlay(item,token){
    if(item.pending||!item.video.paused||atEnd(item)||token!==generation)return;
    item.pending=true;item.video.playbackRate=1;
    let attempt;try{attempt=item.video.play();}catch(_error){attempt=Promise.reject(_error);}
    Promise.resolve(attempt).then(()=>{
      if(token!==generation){if(!entries.some(current=>current.video===item.video))item.video.pause();return;}item.pending=false;
    },error=>{if(token!==generation)return;item.pending=false;if(error?.name==='AbortError')return;invalidate();mode='error';render();});
  }
  function tick(token){
    if(token!==generation||!['starting','playing','buffering'].includes(mode))return;
    if(entries.some(item=>item.video.error)){invalidate();mode='error';render();return;}
    const active=entries.filter(item=>!atEnd(item));
    if(!active.length){cursor=duration;pause();return;}
    // The common clock follows decoded media, never independent wall time.
    const slowest=Math.min(...active.map(progress));cursor=Math.min(duration,slowest);
    if(active.some(item=>item.video.seeking||item.video.readyState<3)){
      entries.forEach(item=>item.video.pause());mode='buffering';
    }else{
      mode='playing';
      for(const item of active){
        // Pause an early recording until its partner catches up. Do not skip
        // frames or change playback speed to conceal a decoding delay.
        if(progress(item)>slowest+.08)item.video.pause();
        else if(progress(item)<=slowest+epsilon)requestPlay(item,token);
      }
    }
    entries.filter(atEnd).forEach(item=>item.video.pause());render();frame=requestAnimationFrame(()=>tick(token));
  }
  async function toggle(){
    if(['starting','playing','buffering'].includes(mode)){pause();return;}
    if(mode!=='paused'||!entries.length)return;
    if(cursor>=duration-.03){if(!await seek(0))return;}
    const token=generation;mode='starting';render();
    entries.filter(item=>!atEnd(item)).forEach(item=>requestPlay(item,token));
    frame=requestAnimationFrame(()=>tick(token));
  }
  function mount(items){clear();entries=items.map(item=>({...item,pending:false}));return seek(0);}
  render();
  return {mount,clear,pause,seek,toggle,state:()=>({mode,cursor,duration,generation})};
}
'''

TEMPLATE = TEMPLATE.replace("/*PAIRED_PLAYBACK*/", PLAYBACK_SCRIPT)
