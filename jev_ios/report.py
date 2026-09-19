"""Portable local playback report. No remote scripts, no unsanitized HTML."""
from __future__ import annotations

import base64
import html
import json
import math
import os
import re
import statistics
from pathlib import Path


def _text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Report {name} must be a nonempty bounded string")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"Report {name} must be valid Unicode") from None
    return value


def _number(value, name, *, integer=False, maximum=2 ** 53 - 1, signed=False):
    types = (int,) if integer else (int, float)
    if type(value) not in types or not (-maximum if signed else 0) <= value <= maximum or not math.isfinite(value):
        raise ValueError(f"Report {name} must be a finite {'integer' if integer else 'number'} within bounds")
    return value


def _labels(value, name):
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError(f"Report {name} must be a list of at most 30 labels")
    return [_text(label, name, 300) for label in value]


def _result(raw):
    if raw.get("schema") != "jev-ios/run/v1" or not isinstance(raw.get("status"), str) or raw["status"] not in {"verified", "blocked", "uncertain", "unverified", "stopped"}:
        raise ValueError("Report result has an invalid schema or status")
    timings = raw.get("model_ms")
    if not isinstance(timings, list) or len(timings) > 30:
        raise ValueError("Report model timings must be a list of at most 30 values")
    # Copy only established public fields; never embed arbitrary provider data,
    # input strings, UI trees or credentials attached by a caller.
    result = {"type": "result", "schema": raw["schema"], "status": raw["status"],
              "goal": _text(raw.get("goal"), "goal"), "reason": _text(raw.get("reason"), "reason", 300),
              "expected_labels": _labels(raw.get("expected_labels"), "expected labels"),
              "matched_labels": _labels(raw.get("matched_labels"), "matched labels"),
              "elapsed_ms": _number(raw.get("elapsed_ms"), "elapsed time"),
              "actions_executed": _number(raw.get("actions_executed"), "action count", integer=True),
              "model_calls": _number(raw.get("model_calls"), "model call count", integer=True),
              "model_ms": [_number(t, "model time") for t in timings]}
    if not result["expected_labels"] or any(label not in result["expected_labels"] for label in result["matched_labels"]):
        raise ValueError("Report result has inconsistent expected or matched labels")
    if result["status"] == "verified" and any(label not in result["matched_labels"] for label in result["expected_labels"]):
        raise ValueError("Verified report result must include every expected label")
    usage = raw.get("usage", [])
    if not isinstance(usage, list) or len(usage) > 30 or any(not isinstance(item, dict) for item in usage):
        raise ValueError("Report usage must be a bounded list of token-count objects")
    result["usage"] = [{key: _number(value, "token count", integer=True) for key, value in item.items()
                        if key in {"inputTokens", "outputTokens", "totalTokens", "cacheReadInputTokens", "cacheWriteInputTokens", "reasoningOutputTokens"}} for item in usage]
    for key in ("verification", "final_screen_hash"):
        if raw.get(key) is not None:
            result[key] = _text(raw[key], key)
    return result


def _media_bytes(path, limit, name):
    try:
        source = Path(path)
    except (TypeError, ValueError):
        raise ValueError(f"Report {name} path is invalid") from None
    if not source.is_file():
        raise ValueError(f"Report {name} must be an existing local file")
    if source.stat().st_size > limit:
        raise ValueError(f"{name.capitalize()} must be at most {limit // 1_000_000} MB for a portable report")
    with source.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{name.capitalize()} grew beyond its report size limit")
    if (name == "video" and (len(data) < 12 or data[4:8] != b"ftyp")) or (name == "screenshot" and not data.startswith(b"\x89PNG\r\n\x1a\n")):
        raise ValueError(f"Report {name} has an invalid media header")
    return data


def write_report(path, events, *, video=None, screenshot=None, title="Jev · iOS run", video_offset_ms=0):
    if not isinstance(events, (list, tuple)) or len(events) > 10_000 or any(not isinstance(e, dict) or not isinstance(e.get("type"), str) for e in events):
        raise ValueError("Report events must be a bounded list of event objects")
    title = _text(title, "title", 300)
    video_offset_ms = _number(video_offset_ms, "video offset", signed=True)
    results = [e for e in events if e["type"] == "result"]
    if not results:
        raise ValueError("A report needs a completed result event")
    result = _result(results[-1])
    # Report data contains only the operation timeline, never the full UI tree.
    timeline = []
    decisions = {}
    for e in events:
        if e.get("type") == "decision":
            step = _number(e.get("step"), "decision step", integer=True)
            probability = None if e.get("probability") is None and e.get("confidence_kind") == "not_reported" else _number(e.get("probability", 0), "probability", maximum=1)
            decisions[step] = {"model_ms": _number(e.get("model_ms", 0), "decision time"),
                               "probability": probability}
        if e.get("type") == "action":
            step = _number(e.get("step"), "action step", integer=True)
            operation = e.get("operation")
            if not isinstance(operation, str) or operation not in {"TAP", "TYPE_TEXT", "SCROLL_UP", "SCROLL_DOWN", "WAIT"}:
                raise ValueError("Report action has an unsupported operation")
            d = decisions.get(step, {})
            timeline.append({"step": step, "operation": operation,
                             "label": _text(e.get("target_label") or operation, "action label"),
                             "elapsed_ms": _number(e.get("elapsed_ms", 0), "action elapsed time"),
                             "model_ms": d.get("model_ms", 0), "probability": d.get("probability", 0)})
    timings = result.get("model_ms", [])
    data = {"result": result, "timeline": timeline, "video_offset_ms": video_offset_ms,
            "median_ms": round(statistics.median(timings), 1) if timings else 0}
    # Escaping '<' also prevents script-end breakout via hostile app labels.
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    media = "<div class='empty'>Screen recording was not attached.<br>The trace below is the original run.</div>"
    if video is not None:
        media = '<video id="recording" controls playsinline preload="metadata" src="data:video/mp4;base64,' + base64.b64encode(_media_bytes(video, 40_000_000, "video")).decode() + '"></video>'
    elif screenshot is not None:
        media = '<img alt="Final simulator screen" src="data:image/png;base64,' + base64.b64encode(_media_bytes(screenshot, 10_000_000, "screenshot")).decode() + '">'
    badge = "Recorded execution · 1×" if video is not None else "Final screenshot" if screenshot is not None else "Trace evidence"
    caption = "Simulator capture at original speed. No accelerated playback." if video is not None else "Final simulator screenshot." if screenshot is not None else "No screenshot or recording attached."
    replacements = {"__TITLE__": html.escape(title), "__MEDIA__": media, "__DATA__": encoded,
                    "__BADGE__": badge, "__CAPTION__": caption}
    content = re.sub(r"__(?:TITLE|MEDIA|DATA|BADGE|CAPTION)__", lambda match: replacements[match[0]], TEMPLATE)
    try:
        output = Path(path)
    except (TypeError, ValueError):
        raise ValueError("Report output path is invalid") from None
    output.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        handle.write(content)
    return str(output)


TEMPLATE = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;--bg:#131411;--panel:#1c1e19;--border:#34382e;--ink:#f2f3e8;--muted:#a4aa99;--accent:#d7f68a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased}button{font:inherit}header{padding:26px 4vw;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}.brand{letter-spacing:-.8px;font-size:24px;font-weight:700}.brand span{font-weight:400;color:var(--muted)}.badge{font:12px ui-monospace,monospace;text-transform:uppercase;letter-spacing:1px;color:var(--accent);border:1px solid #465431;border-radius:30px;padding:9px 13px}main{max-width:1400px;margin:auto;padding:42px 4vw;display:grid;grid-template-columns:minmax(320px,430px) minmax(400px,1fr);gap:60px}.device{background:#080907;border:1px solid #4a4e40;border-radius:38px;padding:10px;box-shadow:0 26px 65px #0006;max-width:390px;margin:0 auto;overflow:hidden}.device video,.device img{display:block;width:100%;border-radius:28px;background:#111}.empty{min-height:650px;display:grid;place-content:center;text-align:center;color:var(--muted);line-height:1.7}.caption{text-align:center;color:var(--muted);font-size:12px;margin:16px 0}.eyebrow{font:11px ui-monospace,monospace;color:var(--accent);letter-spacing:2px;margin:0 0 13px}h1{font-size:clamp(36px,4vw,62px);letter-spacing:-2.5px;line-height:1.02;margin:0 0 18px;font-weight:650}.goal{font-size:16px;line-height:1.5;color:var(--muted);max-width:650px;margin:0 0 28px}.stats{display:grid;grid-template-columns:1fr 1fr 1fr;border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:23px 0;gap:20px}.number{font-size:37px;font-weight:550;letter-spacing:-1.5px;font-variant-numeric:tabular-nums}.unit{font-size:16px;color:var(--muted);letter-spacing:0;margin-left:3px}.stat-label{color:var(--muted);font-size:12px;margin-top:5px}.section{display:flex;align-items:center;justify-content:space-between;margin:29px 0 12px}.section h2{font-size:15px;margin:0}.section span{font:11px ui-monospace,monospace;color:var(--muted)}.row{display:grid;grid-template-columns:33px 1fr 80px;align-items:center;gap:10px;padding:14px 12px;border:1px solid transparent;border-top-color:var(--border);background:transparent;color:var(--ink);width:100%;text-align:left;cursor:pointer;transition:background .12s,border .12s}.row:hover,.row.active{background:var(--panel);border:1px solid #52613a;border-radius:10px}.index{color:var(--muted);font:12px ui-monospace,monospace}.label{font-size:14px;font-weight:500}.detail{font-size:11px;color:var(--muted);margin-top:5px}.time{font-size:14px;text-align:right;font-variant-numeric:tabular-nums;color:var(--accent)}.bar{height:2px;background:#333c28;margin-top:9px;border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent)}.outcome{margin-top:24px;padding:18px;border:1px solid #465431;border-radius:12px;font-size:14px;line-height:1.6}.outcome strong{color:var(--accent)}.foot{color:var(--muted);font-size:12px;line-height:1.6;margin-top:16px}.controls{display:flex;gap:8px;margin-top:18px}.controls button{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:9px 14px;color:var(--ink);cursor:pointer}.controls button:hover{border-color:var(--accent)}@media(max-width:800px){main{grid-template-columns:1fr;gap:28px;padding:28px 20px}.visual{order:2}.device{max-width:330px}header{padding:20px}.badge{font-size:9px}.stats{gap:10px}.number{font-size:31px}h1{font-size:40px}}
</style>
<header><div class="brand">jev<span> / iOS</span></div><div class="badge">__BADGE__</div></header>
<main><section class="visual"><div class="device">__MEDIA__</div><p class="caption">__CAPTION__</p></section><section>
<p class="eyebrow">ONE GOAL. OBSERVED CONTROLS. REAL TAPS.</p><h1 id="headline">A plan, at the<br>speed of a thought.</h1><p class="goal" id="goal"></p>
<div class="stats"><div><div class="number" id="total"></div><div class="stat-label">Full run · including device work</div></div><div><div class="number" id="median"></div><div class="stat-label">Median model decision</div></div><div><div class="number" id="actions"></div><div class="stat-label">Executed actions</div></div></div>
<div class="section"><h2>Decision trace</h2><span>MODEL TIME / ACTION</span></div><div id="timeline"></div>
<div class="outcome"><strong id="status"></strong><br><span id="proof"></span></div>
<div class="controls"><button id="replay">Replay from start</button><button id="download">Download result</button></div>
<p class="foot">The model reads the accessibility tree and selects an operation and a compatible target. The Mac verifies fresh state before every tap. Final labels are checked locally. Timings describe this run only; no general benchmark claim.</p>
</section></main>
<script type="application/json" id="data">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),r=data.result,v=document.getElementById('recording');
const set=(id,s)=>document.getElementById(id).textContent=s;
set('goal',r.goal);set('total',(r.elapsed_ms/1000).toFixed(2)+' s');set('median',Math.round(data.median_ms)+' ms');set('actions',r.actions_executed);
set('headline',r.status==='verified'?'From intent to done.':'Every attempt, visible.');set('status',r.status==='verified'?'Verified on the simulator':r.status.toUpperCase()+' · '+r.reason);set('proof',(r.matched_labels||[]).join(' · ')||'Required labels were not all observed.');
const peak=Math.max(1,...data.timeline.map(a=>a.model_ms));
data.timeline.forEach((a,i)=>{const b=document.createElement('button');b.className='row';const n=document.createElement('span');n.className='index';n.textContent=String(i+1).padStart(2,'0');const c=document.createElement('div');const l=document.createElement('div');l.className='label';l.textContent=a.label;const d=document.createElement('div');d.className='detail';d.textContent=a.operation+' · '+(a.probability===null?'Confidence not reported':Math.round(a.probability*100)+'% choice probability');const bar=document.createElement('div');bar.className='bar';const fill=document.createElement('i');fill.style.width=(a.model_ms/peak*100)+'%';bar.append(fill);c.append(l,d,bar);const t=document.createElement('span');t.className='time';t.textContent=Math.round(a.model_ms)+' ms';b.append(n,c,t);b.onclick=()=>{if(v){v.currentTime=Math.max(0,(a.elapsed_ms+data.video_offset_ms)/1000-1);v.play();}};document.getElementById('timeline').append(b);});
if(v)v.ontimeupdate=()=>{const ms=v.currentTime*1000-data.video_offset_ms;let i=data.timeline.findIndex(a=>a.elapsed_ms>ms);if(i<0)i=data.timeline.length-1;document.querySelectorAll('.row').forEach((e,j)=>e.classList.toggle('active',j===i));};
document.getElementById('replay').onclick=()=>{if(v){v.playbackRate=1;v.currentTime=0;v.play();}};document.getElementById('download').onclick=()=>{const blob=new Blob([JSON.stringify(r,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='jev-ios-result.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
</script></html>'''
