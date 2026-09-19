"""Structural interfaces for adapters used by the existing Runner."""
from __future__ import annotations

import os
from typing import Any, Protocol


class Snapshot(Protocol):
    @property
    def elements(self) -> list[dict[str, Any]]: ...

    @property
    def labels(self) -> list[str]: ...

    @property
    def screen_hash(self) -> str: ...

    @property
    def pid(self) -> int: ...

    def targets(self, kind: str) -> dict[str, str]: ...

    def model_state(self) -> dict[str, Any]: ...

    def as_dict(self) -> dict[str, Any]: ...


class Device(Protocol):
    def observe(self) -> Snapshot: ...

    def execute(
        self, snapshot: Snapshot, decision: dict[str, Any], text_values: dict[str, str]
    ) -> dict[str, Any]: ...

    def screenshot(self, path: str | os.PathLike[str]) -> str: ...


class Model(Protocol):
    def decide(
        self,
        state: dict[str, Any],
        actions: dict[str, str],
        tap_targets: dict[str, str],
        type_targets: dict[str, str],
        text_values: dict[str, str],
    ) -> dict[str, Any]: ...
