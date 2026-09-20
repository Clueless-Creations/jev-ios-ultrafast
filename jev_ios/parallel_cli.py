"""Agent-facing suite commands; imports do not open devices or call a provider."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import uuid

from .fleet import booted_workers
from .matrix import make_plan, run_matrix
from .matrix_report import load_manifest, summarize, write_json
from .suite import (Case, Suite, WorkerSpec, bundle_identifier, changed_paths, digest, identifier,
                    load_pool, load_suite, scenario_from_data, select_cases, strings, text, validate_workers)


def register(sub):
    for name in ("plan", "matrix"):
        p = sub.add_parser(name, help="Select semantic tests offline" if name == "plan" else "Run semantic tests across exclusive device lanes")
        p.add_argument("--suite", type=Path, default=Path(".jev-ios/suite.json"))
        device = p.add_mutually_exclusive_group(required=True)
        device.add_argument("--pool", type=Path)
        device.add_argument("--udid", action="append", help="Explicit local simulator UUID; repeat for more devices")
        device.add_argument("--devices", choices=("auto",), help="Use already booted local iOS simulators")
        p.add_argument("--mode", choices=("shard", "matrix"), default="shard")
        p.add_argument("--changed-since", help="Include affected, unmapped and critical cases")
        p.add_argument("--project-root", type=Path, default=Path.cwd())
        p.add_argument("--only", action="append", default=[], help="Explicit case ID; restricts coverage")
        p.add_argument("--tag", action="append", default=[])
        p.add_argument("--app-revision", help="Caller-supplied installed build identifier, not inferred from Git")
        if name == "plan":
            p.add_argument("--output", type=Path)
        else:
            execution_args(p)
    verify = sub.add_parser("verify", help="Read a saved matrix manifest; never run inference or device actions")
    verify.add_argument("--manifest", required=True, type=Path)
    reproduce = sub.add_parser("reproduce", help="Prepare or explicitly rerun a frozen semantic scenario, not recorded actions")
    reproduce.add_argument("--manifest", required=True, type=Path)
    reproduce.add_argument("--cell", required=True)
    reproduce.add_argument("--device-name", help="Select another device already present in the saved pool")
    reproduce.add_argument("--execute", action="store_true", help="Authorize the prepared rerun against the selected test device")
    reproduce.add_argument("--acknowledge-uncertain", action="store_true", help="Confirm fixture state was repaired after uncertain execution")
    execution_args(reproduce)


def execution_args(parser):
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--api-concurrency", type=int, default=2)
    parser.add_argument("--requests-per-second", type=float, default=4)
    parser.add_argument("--task-timeout", type=float, default=180)
    parser.add_argument("--budget-usd", type=float, default=1)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--vercel-project")
    parser.add_argument("--output-dir", type=Path)


def source_provenance(root, app_revision):
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        revision = proc.stdout.strip() if proc.returncode == 0 else None
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, timeout=10)
        dirty = bool(status.stdout) if status.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        revision, dirty = None, None
    return {"source_revision": revision, "worktree_dirty": dirty, "installed_app_revision": app_revision,
            "note": "A Git revision is not proof of which binary is installed on the simulator."}


def fresh_output():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("runs") / ("matrix-" + stamp + "-" + uuid.uuid4().hex[:8])


def freeze_case(item):
    scenario = scenario_from_data(item["scenario"])
    if digest(item["scenario"]) != item["scenario_sha256"]:
        raise ValueError("Frozen scenario does not match its digest")
    if type(item["critical"]) is not bool:
        raise ValueError("Invalid frozen case")
    return Case(identifier(item["id"]), scenario, text(item["source"]), strings(item["paths"], "paths", maximum=100),
                strings(item["tags"], "tags"), item["critical"], strings(item["start_labels"], "start labels", minimum=1),
                strings(item["launch_args"], "launch arguments"), strings(item["resource_locks"], "resource locks"))


def handle(args, emit, catalog_loader, token_loader):
    if args.command == "verify":
        summary = summarize(load_manifest(args.manifest))
        emit({"type": "verification", **summary})
        return 0 if summary["status"] == "verified" else 2
    if args.command == "reproduce":
        manifest = load_manifest(args.manifest)
        row = next((r for r in manifest["results"] if r["cell"] == args.cell), None)
        if row is None:
            raise ValueError("Unknown recorded cell")
        saved = manifest["plan"]
        case = freeze_case(next(c for c in saved["cases"] if c["id"] == row["case"]))
        name = args.device_name or row["device"]
        raw_worker = next((w for w in saved["devices"] if w["name"] == name), None)
        if raw_worker is None:
            raise ValueError("Choose --device-name from the recorded pool for an unassigned cell")
        workers = validate_workers([WorkerSpec(**raw_worker)])
        isolation = saved["fixture_isolation"]
        if isolation not in ("shared", "per_device"):
            raise ValueError("Invalid fixture isolation")
        suite = Suite(text(saved["suite"]), bundle_identifier(saved["bundle_id"]), (case,), isolation)
        selected = [(case, "explicit_frozen_reproduction")]
        selection = {"original_manifest": str(args.manifest), "original_cell": args.cell,
                     "original_status": row["status"], "warning": "Reruns intent on current state; does not reinstall the original app or replay input."}
        provenance = saved.get("provenance", {})
        mode = "matrix"
        if not args.execute:
            emit({"type": "reproduction_plan", **make_plan(suite, selected, workers, mode, selection, provenance)})
            return 0
        if row["status"] in ("uncertain", "cancelled") and not args.acknowledge_uncertain:
            raise ValueError("Repair fixture state, then explicitly --acknowledge-uncertain before rerunning")
    else:
        suite = load_suite(args.suite)
        workers = (load_pool(args.pool) if args.pool else booted_workers() if args.devices == "auto" else
                   validate_workers([WorkerSpec(f"local-{i + 1}", u) for i, u in enumerate(args.udid)]))
        changed, base = changed_paths(args.project_root, args.changed_since) if args.changed_since else (None, None)
        selected, selection = select_cases(suite, changed=changed, only=args.only, tags=args.tag)
        provenance = source_provenance(args.project_root, args.app_revision)
        provenance.update(comparison_base=base, changed_paths=changed)
        mode = args.mode
        if args.command == "plan":
            plan = make_plan(suite, selected, workers, mode, selection, provenance)
            if args.output:
                if args.output.exists() or args.output.is_symlink():
                    raise ValueError("Plan output must be new")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                write_json(args.output, plan)
            emit({"type": "plan", **plan})
            return 0
    output = args.output_dir or fresh_output()
    if output.exists() or output.is_symlink():
        raise ValueError("Output directory must be new")
    # Credentials never enter suite files, remote worker messages or reports.
    key = token_loader(args.vercel_project) if args.vercel_project else (os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN"))
    if not isinstance(key, str) or not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError("Set AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN, or use --vercel-project")
    manifest = run_matrix(suite, selected, workers, output_dir=output, catalog=catalog_loader(),
                          budget_usd=args.budget_usd, mode=mode, parallel=args.parallel,
                          api_concurrency=args.api_concurrency, requests_per_second=args.requests_per_second,
                          task_timeout=args.task_timeout, fail_fast=args.fail_fast, api_key=key,
                          selection=selection, provenance=provenance, emit=emit)
    if manifest["interrupted"]:
        return 130
    return 0 if manifest["summary"]["status"] == "verified" else 2
