"""Private JSON, escaped HTML, JUnit and compact agent summaries."""
from __future__ import annotations

from collections import Counter, defaultdict
import html
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from .suite import read_json


def write_text(path: Path, text: str):
    fd, name = tempfile.mkstemp(prefix=".jev-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def summarize(manifest):
    if manifest.get("schema") != "jev-ios/matrix/v1":
        raise ValueError("Unsupported matrix manifest")
    plan, results = manifest["plan"], manifest["results"]
    expected = plan["expected_cells"]
    ids = [r["cell"] for r in results]
    if not expected or len(set(expected)) != len(expected) or len(ids) != len(set(ids)) or set(ids) - set(expected):
        raise ValueError("Invalid or duplicate matrix cells")
    allowed = {"verified", "blocked", "stopped", "unverified", "uncertain", "error", "skipped", "cancelled"}
    cases = {c["id"]: c for c in plan["cases"]}
    if any(r["status"] not in allowed or r["case"] not in cases for r in results):
        raise ValueError("Invalid cell result")
    devices = {w["name"] for w in plan["devices"]}
    for row in results:
        cell_id = row["case"] + ("@" + str(row.get("device")) if plan["mode"] == "matrix" else "")
        if row["cell"] != cell_id or (row.get("device") is not None and row["device"] not in devices):
            raise ValueError("Cell does not match its scenario and device")
        if row["status"] == "verified":
            outcome = row.get("result") or {}
            labels = cases[row["case"]]["scenario"]["expect_labels"]
            if (not labels or outcome.get("schema") != "jev-ios/run/v1" or outcome.get("status") != "verified"
                    or outcome.get("expected_labels") != labels or not set(labels) <= set(outcome.get("matched_labels", []))):
                raise ValueError("A verified cell is missing its expected-label evidence")
    counts = Counter(r["status"] for r in results)
    missing = sorted(set(expected) - set(ids))
    complete = not missing and not counts["skipped"] and not counts["cancelled"]
    passed = manifest.get("finished") is True and complete and counts["verified"] == len(expected) and not manifest.get("lane_errors") and not manifest.get("interrupted")
    groups = defaultdict(list)
    for row in results:
        if row["status"] != "verified":
            # Group symptoms, never assert a common root cause without evidence.
            outcome = row.get("result") or {}
            absent = sorted(set(cases[row["case"]]["scenario"]["expect_labels"]) - set(outcome.get("matched_labels", [])))
            groups[(row["reason"], tuple(absent))].append(row["cell"])
    return {"status": "verified" if passed else "not_verified", "complete": complete,
            "planned": len(expected), "counts": dict(counts), "missing_cells": missing,
            "failure_groups": [{"reason": key[0], "missing_labels": list(key[1]), "cells": value}
                               for key, value in sorted(groups.items())],
            "model_calls": sum(r.get("model_calls", 0) for r in results),
            "elapsed_ms": manifest.get("elapsed_ms", 0),
            "scope": "Selected explicit scenarios only; similar symptoms are not confirmed root causes."}


def page(title, body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>' + html.escape(title) + '</title><style>body{font:16px system-ui;margin:2rem auto;padding:0 1rem;'
            'max-width:1100px;line-height:1.5}table{border-collapse:collapse;width:100%}th,td{text-align:left;'
            'padding:.7rem;border-bottom:1px solid #aaa}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#1560a8}'
            '</style><h1>' + html.escape(title) + '</h1>' + body + '</html>')


def cell_report(row, events):
    return page(row["cell"], '<p>' + html.escape(row["status"] + ': ' + row["reason"]) + '</p><p>'
                '<a href="trace.jsonl">Trace</a> · <a href="scenario.json">Frozen scenario</a></p>' +
                ''.join('<details><summary>' + html.escape(e.get("type", "event")) + '</summary><pre>' +
                        html.escape(json.dumps(e, ensure_ascii=False, indent=2)) + '</pre></details>' for e in events))


def write_reports(directory, manifest):
    summary = summarize(manifest)
    manifest["summary"] = summary
    write_json(directory / "matrix.json", manifest)
    write_json(directory / "summary.json", summary)
    rows = []
    for row in manifest["results"]:
        link = '<a href="' + html.escape(row["report"], quote=True) + '">Evidence</a>' if row.get("report") else 'Not run'
        rows.append('<tr>' + ''.join('<td>' + html.escape(str(row.get(k) or '')) + '</td>' for k in
                                    ("cell", "device", "status", "reason")) + '<td>' + link + '</td></tr>')
    body = '<p>' + html.escape(f'{summary["counts"].get("verified", 0)} / {summary["planned"]} verified') + '</p>'
    body += '<p>Exact accessibility-label checks, not exhaustive product or backend coverage.</p>'
    body += '<table><tr><th>Case</th><th>Device</th><th>Status</th><th>Reason</th><th>Evidence</th></tr>' + ''.join(rows) + '</table>'
    body += '<h2>Failure symptoms</h2><pre>' + html.escape(json.dumps(summary["failure_groups"], indent=2)) + '</pre>'
    write_text(directory / "index.html", page("Jev parallel verification", body))
    root = ET.Element("testsuite", name=manifest["plan"]["suite"], tests=str(summary["planned"]),
                      failures=str(sum(r["status"] not in ("verified", "skipped", "cancelled") for r in manifest["results"])),
                      skipped=str(sum(r["status"] in ("skipped", "cancelled") for r in manifest["results"])))
    for row in manifest["results"]:
        case = ET.SubElement(root, "testcase", name=row["cell"], classname=row.get("device") or "unassigned",
                             time=str(row.get("elapsed_ms", 0) / 1000))
        if row["status"] != "verified":
            ET.SubElement(case, "skipped" if row["status"] in ("skipped", "cancelled") else "failure",
                          message=row["reason"]).text = row.get("report", "Not executed")
    write_text(directory / "junit.xml", ET.tostring(root, encoding="unicode"))


def load_manifest(path):
    manifest = read_json(Path(path), limit=32_000_000)
    summarize(manifest)
    return manifest
