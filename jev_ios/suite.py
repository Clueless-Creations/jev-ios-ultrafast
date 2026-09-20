"""Versioned suites, device pools, and deterministic change-impact selection.

Scenarios remain the product contract. Scheduling metadata never reaches Jev.
All paths in a suite are relative to the suite file; source globs are relative
to the app repository. Unknown changed paths select the full suite.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

from .scenario import Scenario, SCENARIO_SCHEMA, load_scenario, _unique_object, _reject_constant

SUITE_SCHEMA = "jev-ios/suite/v1"
POOL_SCHEMA = "jev-ios/pool/v1"


def read_json(path: Path, limit: int = 1_000_000):
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON document exceeds its size limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Expected bounded UTF-8 JSON") from None


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or not set(required) <= data.keys():
        raise ValueError("Missing or unsupported configuration fields")


def text(value, name="value", limit=300):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be a bounded nonempty string without control characters")
    return value


def strings(value, name, *, minimum=0, maximum=30):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"Invalid {name} list length")
    return tuple(text(item, name) for item in value)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("IDs must use 1-64 ASCII letters, digits, underscores or hyphens")
    return value


def bundle_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", value):
        raise ValueError("Invalid application bundle identifier")
    return value


def scenario_data(scenario: Scenario):
    return {"schema": SCENARIO_SCHEMA, "name": scenario.name, "goal": scenario.goal,
            "expect_labels": list(scenario.expect_labels),
            **{k: list(v) if isinstance(v, tuple) else v for k, v in scenario.to_runner_kwargs().items()}}


def scenario_from_data(data):
    fields(data, {"schema", "name", "goal", "expect_labels", "allow_labels", "allow_scroll",
                  "text_values", "max_steps", "min_probability"}, {"schema", "name", "goal", "expect_labels"})
    if data["schema"] != SCENARIO_SCHEMA:
        raise ValueError("Unsupported scenario schema")
    return Scenario(**{k: v for k, v in data.items() if k != "schema"})


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Case:
    id: str
    scenario: Scenario
    source: str
    paths: tuple[str, ...]
    tags: tuple[str, ...]
    critical: bool
    start_labels: tuple[str, ...]
    launch_args: tuple[str, ...]
    resource_locks: tuple[str, ...]

    def as_dict(self):
        return {"id": self.id, "scenario": scenario_data(self.scenario), "source": self.source,
                "scenario_sha256": digest(scenario_data(self.scenario)), "paths": list(self.paths),
                "tags": list(self.tags), "critical": self.critical, "start_labels": list(self.start_labels),
                "launch_args": list(self.launch_args), "resource_locks": list(self.resource_locks)}


@dataclass(frozen=True)
class Suite:
    name: str
    bundle_id: str
    cases: tuple[Case, ...]
    fixture_isolation: str = "shared"


def load_suite(path: Path) -> Suite:
    data = read_json(path)
    fields(data, {"schema", "name", "bundle_id", "cases", "start_labels", "launch_args", "fixture_isolation"},
           {"schema", "name", "bundle_id", "cases"})
    if data["schema"] != SUITE_SCHEMA:
        raise ValueError("Unsupported suite schema")
    name = text(data["name"], "suite name")
    bundle = bundle_identifier(data["bundle_id"])
    isolation = data.get("fixture_isolation", "shared")
    if isolation not in ("shared", "per_device"):
        raise ValueError("fixture_isolation must be shared or per_device")
    raw_cases = data["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 500:
        raise ValueError("A suite requires 1-500 cases")
    cases, ids = [], set()
    for item in raw_cases:
        fields(item, {"id", "scenario", "paths", "tags", "critical", "start_labels", "launch_args", "resource_locks"},
               {"id", "scenario"})
        case_id = identifier(item["id"])
        if case_id in ids:
            raise ValueError("Duplicate case ID")
        ids.add(case_id)
        relative = text(item["scenario"], "scenario path")
        source = (path.parent / relative).resolve()
        if Path(relative).is_absolute() or not source.is_relative_to(path.parent.resolve()):
            raise ValueError("Scenario paths must stay inside the suite directory")
        scenario = load_scenario(source)
        if scenario.goal.startswith("REPLACE:") or any(v.startswith("REPLACE:") for v in scenario.expect_labels):
            raise ValueError("Replace scaffold goals and labels before planning or running")
        critical = item.get("critical", False)
        if type(critical) is not bool:
            raise ValueError("critical must be a boolean")
        paths = strings(item.get("paths", []), "source patterns", maximum=100)
        if any(p.startswith("/") or ".." in p.split("/") for p in paths):
            raise ValueError("Source patterns must be repository-relative")
        start = strings(item.get("start_labels", data.get("start_labels", [])), "start labels", minimum=1)
        if any(label.startswith("REPLACE:") for label in start):
            raise ValueError("Replace scaffold starting labels before planning or running")
        cases.append(Case(case_id, scenario, relative, paths, strings(item.get("tags", []), "tags"), critical,
                          start,
                          strings(item.get("launch_args", data.get("launch_args", [])), "launch arguments"),
                          strings(item.get("resource_locks", []), "resource locks")))
    return Suite(name, bundle, tuple(cases), isolation)


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    udid: str
    host: str | None = None
    python: str = "python3"
    axe: str | None = None
    transport: str = "native"
    mobai_url: str | None = None

    def __post_init__(self):
        identifier(self.name)
        if self.transport not in ("native", "mobai"):
            raise ValueError("Device transport must be native or mobai")
        if self.transport == "native":
            try:
                object.__setattr__(self, "udid", str(uuid.UUID(self.udid)))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("A native device requires a simulator UUID") from None
        else:
            text(self.udid, "MobAI device ID", 300)
            if self.host or self.axe:
                raise ValueError("MobAI workers use MobAI routing, not SSH/AXe fields")
            if self.mobai_url is not None:
                text(self.mobai_url, "MobAI URL", 1000)
                if not re.fullmatch(r"https?://[^\\s]+", self.mobai_url):
                    raise ValueError("MobAI URL must be an http(s) API base URL")
        if self.host is not None and (not isinstance(self.host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,252}", self.host)):
            raise ValueError("Use a trusted SSH host alias or user@host, without options")
        text(self.python, "Python executable")
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", self.python) or self.python.startswith("-"):
            raise ValueError("Invalid remote Python executable")
        if self.axe is not None:
            text(self.axe, "AXe executable", 4096)

    @property
    def key(self):
        return (self.transport, self.mobai_url or self.host or "local", self.udid)

    def as_dict(self):
        return {"name":self.name,"udid":self.udid,"host":self.host,"python":self.python,
                "axe":self.axe,"transport":self.transport,"mobai_url":self.mobai_url}


def validate_workers(workers):
    if not 1 <= len(workers) <= 32:
        raise ValueError("Select 1-32 devices")
    if len({w.name for w in workers}) != len(workers) or len({w.key for w in workers}) != len(workers):
        raise ValueError("Device names and transport/device pairs must be unique")
    return tuple(workers)


def load_pool(path: Path):
    data = read_json(path)
    fields(data, {"schema", "devices"}, {"schema", "devices"})
    if data["schema"] != POOL_SCHEMA or not isinstance(data["devices"], list):
        raise ValueError("Unsupported device pool")
    workers = []
    for item in data["devices"]:
        fields(item, {"name","udid","host","python","axe","transport","mobai_url"}, {"name","udid"})
        workers.append(WorkerSpec(**item))
    return validate_workers(workers)

def changed_paths(root: Path, ref: str):
    """Committed, staged, unstaged, untracked, deleted and both sides of renames."""
    def git(*args):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=20, check=False)
        if result.returncode:
            raise ValueError("Could not resolve the comparison revision or read the app Git worktree")
        return result.stdout
    base = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    if not re.fullmatch(r"[a-f0-9]{40,64}", base):
        raise ValueError("Invalid comparison revision")
    paths = set()
    for raw in (git("diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--"),
                git("diff", "--name-only", "--no-renames", "-z", "HEAD", "--"),
                git("ls-files", "--others", "--exclude-standard", "-z")):
        paths.update(p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p)
    return sorted(paths), base


def select_cases(suite: Suite, *, changed=None, only=(), tags=()):
    ids = {c.id for c in suite.cases}
    if set(only) - ids:
        raise ValueError("Unknown case selection")
    unmapped = [] if changed is None else [p for p in changed if not any(
        fnmatchcase(p, pattern) for c in suite.cases for pattern in c.paths)]
    selected, omitted = [], []
    for case in suite.cases:
        reason = ("full_suite" if changed is None else "unmapped_change_full_suite" if unmapped else
                  "critical" if case.critical else "unmapped_case" if not case.paths else
                  "affected" if any(fnmatchcase(p, pat) for p in changed for pat in case.paths) else None)
        if only and case.id not in only:
            reason = None
        if tags and not set(tags).intersection(case.tags):
            reason = None
        if reason:
            selected.append((case, reason))
        else:
            omitted.append(case.id)
    return selected, {"unmapped_changed_paths": unmapped, "omitted": omitted,
                      "selection_is_exhaustive": changed is None and not only and not tags,
                      "note": "Explicit source mappings, not proof of complete change impact or all possible scenarios."}
