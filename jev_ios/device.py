"""Bounded, PID-bound iOS Simulator interaction using an existing AXe binary."""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


class DeviceError(RuntimeError):
    """An observation failed, or an action may have incomplete effects."""


class StaleObservation(DeviceError):
    """The observed screen changed before dispatch; no action was dispatched."""


def _frame(value):
    if not isinstance(value, dict):
        return None
    numbers = [value.get(k) for k in ("x", "y", "width", "height")]
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in numbers):
        return None
    if numbers[2] <= 0 or numbers[3] <= 0 or not math.isfinite(numbers[0] + numbers[2]) or not math.isfinite(numbers[1] + numbers[3]):
        return None
    return dict(zip(("x", "y", "width", "height"), numbers))


def _hidden(node):
    return any(node.get(key) is True for key in ("hidden", "isHidden", "AXHidden")) or any(node.get(k) is False for k in ("visible", "isVisible", "AXVisible"))


def _intersect(frame, clip):
    x, y = max(frame["x"], clip["x"]), max(frame["y"], clip["y"])
    right = min(frame["x"] + frame["width"], clip["x"] + clip["width"])
    bottom = min(frame["y"] + frame["height"], clip["y"] + clip["height"])
    return {"x": x, "y": y, "width": right - x, "height": bottom - y} if right > x and bottom > y else None


def _text(value):
    return "" if value is None else str(value)


def _flags(node):
    traits = node.get("traits", [])
    if isinstance(traits, str):
        traits = [traits]
    return {str(t).lower().replace("_", "").replace(" ", "") for t in traits} if isinstance(traits, list) else set()


@dataclass(frozen=True)
class Snapshot:
    elements: list[dict]
    labels: list[str]
    screen_hash: str
    pid: int
    frame: dict
    observed_at: float
    observation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def targets(self, kind):
        if kind not in ("tap", "type"):
            raise ValueError("Target kind must be tap or type")
        kinds = {"TextField", "TextView", "SearchField"} if kind == "type" else {"Button", "Link", "Cell", "TextField", "TextView", "SearchField", "Switch"}
        return {e["id"]: e["label"] or e["kind"] for e in self.elements
                if e["enabled"] and not e["secure"] and e["kind"] in kinds and (kind != "type" or e["value"] == "")}

    def model_state(self):
        compact = [{k: e[k] for k in ("id", "kind", "label", "value", "enabled")} for e in self.elements]
        return {"screen_hash": self.screen_hash, "elements": compact,
                "tap_targets": self.targets("tap"), "type_targets": self.targets("type")}

    def as_dict(self):
        return {**self.model_state(), "elements": self.elements, "labels": self.labels, "pid": self.pid,
                "frame": self.frame, "observed_at": self.observed_at}


def normalize_snapshot(raw, expected_pid):
    roots = raw if isinstance(raw, list) else [raw]
    roots = [r for r in roots if isinstance(r, dict) and not _hidden(r)]
    if len(roots) != 1 or roots[0].get("type") != "Application":
        raise DeviceError("Expected one visible application; system modal or ambiguous UI")
    root = roots[0]
    if type(root.get("pid")) is not int or root["pid"] != expected_pid:
        raise DeviceError("Observed application PID does not match the selected app")
    screen = _frame(root.get("frame"))
    if not screen:
        raise DeviceError("Application has invalid screen geometry")
    elements = []

    def visit(node, inherited_secure=False, inherited_enabled=True, clip=screen):
        if not isinstance(node, dict) or _hidden(node):
            return
        if "pid" in node and node["pid"] != expected_pid:
            raise DeviceError("Visible UI belongs to another application or system modal")
        kind = str(node.get("type", "Unknown"))
        flags = _flags(node)
        secure = inherited_secure or "secure" in kind.lower() or any("secure" in f for f in flags) or any(node.get(k) is True for k in ("secure", "isSecure", "AXSecure", "secureTextEntry", "isSecureTextEntry"))
        identity_text = " ".join(_text(node.get(k)) for k in ("AXLabel", "AXUniqueId")).lower()
        editable = kind in {"TextField", "TextView", "SearchField", "SecureTextField"}
        secure = secure or bool(editable and re.search(r"password|passcode|secret|(?:^|[^a-z])pin(?:code)?(?:[^a-z]|$)", identity_text))
        enabled = inherited_enabled and node.get("enabled", True) is True
        hittable = not any(node.get(k) is False for k in ("hittable", "isHittable", "AXHittable"))
        frame = _frame(node.get("frame"))
        if kind in {"Alert", "Sheet"} and not frame:
            raise DeviceError("Modal UI has unknown visibility; background labels are not evidence")
        clips_children = kind in {"ScrollArea", "ScrollView"} or any(
            node.get(key) is True for key in ("clipsToBounds", "clipsChildren", "masksToBounds", "AXClipsToBounds")
        )
        if clips_children and not frame:
            raise DeviceError("Clipping container has invalid geometry; child visibility cannot be verified")
        visible_frame = _intersect(frame, clip) if frame else None
        if clips_children and visible_frame is None:
            return
        if visible_frame:
            if kind in {"Alert", "Sheet"}:
                raise DeviceError("Visible modal UI blocks background-label verification")
            if not (kind == "Group" and not node.get("AXLabel") and node.get("AXValue") is None):
                elements.append({"id": str(len(elements) + 1), "label": "[secure field]" if secure else _text(node.get("AXLabel")),
                                 "value": "[redacted]" if secure else _text(node.get("AXValue")),
                                 "kind": kind, "enabled": enabled and hittable,
                                 "frame": visible_frame,
                                 "secure": secure, "unique_id": "" if secure else _text(node.get("AXUniqueId")),
                                 "focused": any(node.get(k) is True for k in ("focused", "isFocused", "AXFocused")) or bool(flags & {"focused", "keyboardfocused"})})
        if not secure:
            for child in node.get("children", []) or []:
                # Only actual clipping containers constrain descendants. AX groups
                # may have a small frame while their visible children overflow it.
                visit(child, secure, enabled, visible_frame if clips_children else clip)

    for child in root.get("children", []) or []:
        visit(child)
    # Decorative image animation does not change an actionable target. Keep all
    # labels/values and control geometry in the dispatch fingerprint.
    fingerprint_elements = [{k: v for k, v in e.items() if not (e["kind"] == "Image" and k == "frame")} for e in elements]
    identity = {"pid": expected_pid, "frame": screen, "elements": fingerprint_elements}
    if len(elements) > 120:
        raise DeviceError("Visible UI exceeds the 120-element inference budget; use a narrower fixture screen")
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Snapshot(elements, [e["label"] for e in elements if e["label"]], digest, expected_pid, screen, time.time())


def find_axe(explicit=None):
    selected = explicit or os.environ.get("JEV_IOS_AXE")
    if selected:
        return selected if os.path.isfile(selected) and os.access(selected, os.X_OK) else None
    candidates = [shutil.which("axe")]
    candidates += sorted(glob.glob(str(Path.home() / ".npm/_npx/*/node_modules/xcodebuildmcp/bundled/axe")))
    return next((p for p in candidates if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)


class AxeDevice:
    def __init__(self, udid, bundle_id, axe_path=None):
        if not isinstance(udid, str) or not re.fullmatch(r"[A-Fa-f0-9-]{36}", udid):
            raise DeviceError("A simulator UUID is required")
        if not isinstance(bundle_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", bundle_id):
            raise DeviceError("An explicit bundle ID is required")
        self.udid, self.bundle_id, self.pid = udid, bundle_id, None
        # AXe treats simulator UUIDs as case-sensitive even though simctl does
        # not. WorkerSpec normalizes UUIDs for stable pool keys, so keep an
        # uppercase form for every AXe invocation.
        self._axe_udid = udid.upper()
        self._consumed = set()
        # An explicit path is a binding, so never silently replace an invalid one.
        self.axe = find_axe(axe_path)
        if not self.axe:
            raise DeviceError("AXe unavailable; set JEV_IOS_AXE to an already installed executable")

    def _run(self, args, text=None):
        try:
            result = subprocess.run(args, input=text, capture_output=True, text=True, timeout=20, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeviceError("Device command failed or timed out; do not automatically retry an action") from exc
        if result.returncode:
            raise DeviceError("Device command failed; effects may be incomplete")
        return result.stdout.strip()

    def launch(self):
        output = self._run(["xcrun", "simctl", "launch", self.udid, self.bundle_id])
        match = re.fullmatch(re.escape(self.bundle_id) + r":\s*([1-9][0-9]*)", output)
        if not match:
            raise DeviceError("Launch returned no matching application PID")
        self.pid = int(match[1])
        return self.pid

    def _resolve_pid(self):
        output = self._run(["xcrun", "simctl", "spawn", self.udid, "launchctl", "list"])
        pattern = re.compile(r"^\s*([1-9][0-9]*)\s+\S+\s+UIKitApplication:" + re.escape(self.bundle_id) + r"(?:\[[^\]]+\])+\s*$")
        pids = {int(m[1]) for line in output.splitlines() if (m := pattern.fullmatch(line))}
        if len(pids) != 1:
            raise DeviceError("Selected app is not running with one unambiguous PID")
        self.pid = pids.pop()

    def observe(self):
        if self.pid is None:
            self._resolve_pid()
        try:
            raw = json.loads(self._run([self.axe, "describe-ui", "--udid", self._axe_udid]))
        except (ValueError, TypeError) as exc:
            raise DeviceError("AXe returned invalid UI JSON") from exc
        return normalize_snapshot(raw, self.pid)

    def screenshot(self, path):
        before = self.observe()
        self._run(["xcrun", "simctl", "io", self.udid, "screenshot", "--type=png", str(path)])
        after = self.observe()
        if before.screen_hash != after.screen_hash:
            raise StaleObservation("UI changed during capture; screenshot is not stable-state evidence")
        return str(path)

    def execute(self, snapshot, decision, text_values):
        started = time.monotonic()
        if snapshot.observation_id in self._consumed:
            raise DeviceError("This observation already dispatched an action; observe again instead of replaying")
        current = self.observe()
        if current.screen_hash != snapshot.screen_hash or current.pid != snapshot.pid:
            raise StaleObservation("UI changed before action; no action dispatched")
        operation = decision.get("operation")
        if operation in ("TAP", "TYPE_TEXT"):
            target_id = str(decision.get("target", ""))
            kind = "tap" if operation == "TAP" else "type"
            if target_id not in current.targets(kind):
                raise DeviceError("Decision does not select an observed enabled target")
            target = next(e for e in current.elements if e["id"] == target_id)
            text = None
            if operation == "TYPE_TEXT":
                text = text_values.get(decision.get("text_key"))
                if not isinstance(text, str) or not text or any(ord(c) < 32 or ord(c) > 126 for c in text):
                    raise DeviceError("Typing requires a nonempty caller-supplied printable US ASCII value")
            frame = target["frame"]
            self._consumed.add(snapshot.observation_id)
            # Explicit HID down/up works with the visible Xcode Device Hub window;
            # its simulator-tap path can report success without delivering input.
            self._run([self.axe, "tap", "-x", str(frame["x"] + frame["width"] / 2), "-y", str(frame["y"] + frame["height"] / 2), "--tap-style", "physical", "--udid", self._axe_udid])
            if operation == "TYPE_TEXT":
                focused = self.observe()
                matches = [e for e in focused.elements if e["id"] == target_id and e["label"] == target["label"] and e["unique_id"] == target["unique_id"]]
                if len(matches) != 1 or target_id not in focused.targets("type") or not matches[0]["focused"]:
                    raise DeviceError("Field focus or identity could not be verified after tap; no text entered")
                self._run([self.axe, "type", "--stdin", "--udid", self._axe_udid], text=text)
        elif operation in ("SCROLL_UP", "SCROLL_DOWN"):
            frame = current.frame
            x = frame["x"] + frame["width"] * 0.5
            high, low = frame["y"] + frame["height"] * 0.3, frame["y"] + frame["height"] * 0.7
            start, end = (low, high) if operation == "SCROLL_DOWN" else (high, low)
            self._consumed.add(snapshot.observation_id)
            self._run([self.axe, "swipe", "--start-x", str(x), "--start-y", str(start), "--end-x", str(x), "--end-y", str(end), "--duration", "0.2", "--udid", self._axe_udid])
        else:
            raise DeviceError("Unsupported operation")
        after = self.observe()
        return {"operation": operation, "target": decision.get("target"),
                "target_label": target["label"] if operation in ("TAP", "TYPE_TEXT") else None,
                "before_hash": current.screen_hash, "after_hash": after.screen_hash,
                "pid": after.pid, "duration_ms": round((time.monotonic() - started) * 1000), "observed_at": after.observed_at}
