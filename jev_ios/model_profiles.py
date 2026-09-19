"""Explicit request settings for measured model variants, without substitution."""
from __future__ import annotations

from dataclasses import dataclass, replace
import re


DEFAULT_BASELINE_MODEL = "openai/gpt-5.4-nano"
MAX_GENERATION_TOKENS = 8192
AUTO_REASONING = object()


@dataclass(frozen=True)
class ModelProfile:
    name: str
    model: str
    reasoning_effort: str | None
    temperature: int | None
    max_output_tokens: int

    def metadata(self):
        return {"profile": self.name, "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "temperature": self.temperature,
                "temperature_policy": "omitted" if self.temperature is None else "explicit",
                "max_output_tokens": self.max_output_tokens,
                "output_token_policy": "Total generation ceiling, including reasoning tokens"}


_PROFILES = {
    DEFAULT_BASELINE_MODEL: ModelProfile("nano", DEFAULT_BASELINE_MODEL, "none", 0, 128),
    "openai/gpt-6-astra": ModelProfile("astra-standard", "openai/gpt-6-astra", "low", None, 1024),
    "openai/gpt-6-astra-fast": ModelProfile("astra-fast", "openai/gpt-6-astra-fast", "low", None, 1024),
}


def resolve_profile(model, *, max_output_tokens=None, reasoning_effort=AUTO_REASONING):
    if not isinstance(model, str) or len(model) > 200 or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]*/[A-Za-z0-9][A-Za-z0-9._:/-]*", model) is None:
        raise ValueError("Baseline model must be a provider/model identifier.")
    profile = _PROFILES.get(model, ModelProfile("compatible-json", model, "none", 0, 128))
    if max_output_tokens is not None:
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= MAX_GENERATION_TOKENS:
            raise ValueError(f"Baseline output token limit must be an integer from 1 to {MAX_GENERATION_TOKENS}.")
        profile = replace(profile, max_output_tokens=max_output_tokens)
    if reasoning_effort is not AUTO_REASONING:
        if reasoning_effort not in (None, "none", "minimal", "low", "medium", "high", "xhigh", "max"):
            raise ValueError("Unsupported baseline reasoning effort.")
        if profile.name.startswith("astra-") and reasoning_effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ValueError("Astra requires an explicit supported reasoning effort, from low to max.")
        profile = replace(profile, reasoning_effort=reasoning_effort)
    return profile
