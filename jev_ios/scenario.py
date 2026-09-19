"""Strict, portable scenario files; device and provider configuration stay local."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from types import MappingProxyType
from typing import Mapping


SCENARIO_SCHEMA = "jev-ios/scenario/v1"
MAX_SCENARIO_BYTES = 64 * 1024
_FIELDS = {
    "schema", "name", "goal", "expect_labels", "allow_labels", "allow_scroll",
    "text_values", "max_steps", "min_probability",
}


class ScenarioError(ValueError):
    """A scenario is invalid; messages never include scenario content."""


def _text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ScenarioError(f"{name} must be a nonempty string of at most {limit} characters")
    return value


def _labels(value, name, required=False):
    if not isinstance(value, (list, tuple)) or not (1 if required else 0) <= len(value) <= 30:
        raise ScenarioError(f"{name} must contain {'1 to 30' if required else 'at most 30'} labels")
    return tuple(_text(label, name, 300) for label in value)


@dataclass(frozen=True)
class Scenario:
    name: str
    goal: str
    expect_labels: tuple[str, ...]
    allow_labels: tuple[str, ...] = ()
    allow_scroll: bool = False
    text_values: Mapping[str, str] = field(default_factory=dict)
    max_steps: int = 12
    min_probability: float = 0.55
    schema: str = field(default=SCENARIO_SCHEMA, init=False)

    def __post_init__(self):
        _text(self.name, "name", 300)
        _text(self.goal, "goal", 4000)
        object.__setattr__(self, "expect_labels", _labels(self.expect_labels, "expect_labels", required=True))
        object.__setattr__(self, "allow_labels", _labels(self.allow_labels, "allow_labels"))
        if type(self.allow_scroll) is not bool:
            raise ScenarioError("allow_scroll must be a boolean")
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 30:
            raise ScenarioError("max_steps must be an integer from 1 to 30")
        if type(self.min_probability) not in (int, float) or not 0 <= self.min_probability <= 1 or not math.isfinite(self.min_probability):
            raise ScenarioError("min_probability must be a finite number from 0 to 1")
        if not isinstance(self.text_values, Mapping) or len(self.text_values) > 20:
            raise ScenarioError("text_values must be an object with at most 20 entries")
        copied = {_text(key, "text_values key", 300): _text(value, "text_values value", 500)
                  for key, value in self.text_values.items()}
        object.__setattr__(self, "text_values", MappingProxyType(copied))

    def to_runner_kwargs(self) -> dict:
        """Return a fresh options mapping without scenario goals or host settings."""
        return {
            "max_steps": self.max_steps,
            "min_probability": self.min_probability,
            "allow_labels": self.allow_labels,
            "allow_scroll": self.allow_scroll,
            "text_values": dict(self.text_values),
        }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioError("Scenario contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ScenarioError("Scenario contains a non-finite JSON number")


def load_scenario(path: str | os.PathLike[str]) -> Scenario:
    """Read at most 64 KiB of UTF-8 JSON; never load executable plugin code."""
    try:
        with open(path, "rb") as source:
            raw = source.read(MAX_SCENARIO_BYTES + 1)
    except OSError:
        raise ScenarioError("Scenario file could not be read") from None
    if len(raw) > MAX_SCENARIO_BYTES:
        raise ScenarioError("Scenario file exceeds 64 KiB")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ScenarioError("Scenario must contain a valid UTF-8 JSON object") from None
    if not isinstance(data, dict):
        raise ScenarioError("Scenario must be a JSON object")
    if set(data) - _FIELDS:
        raise ScenarioError("Scenario contains unsupported fields; host and provider settings belong outside scenarios")
    if data.get("schema") != SCENARIO_SCHEMA:
        raise ScenarioError(f"Scenario schema must be {SCENARIO_SCHEMA}")
    if not {"name", "goal", "expect_labels"} <= data.keys():
        raise ScenarioError("Scenario requires name, goal, and expect_labels")
    return Scenario(**{key: value for key, value in data.items() if key != "schema"})
