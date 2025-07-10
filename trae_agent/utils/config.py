# Copyright (c) 2025 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

# TODO: remove these annotations by defining fine-grained types
# pyright: reportAny=false
# pyright: reportUnannotatedClassAttribute=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, override


# data class for model parameters
@dataclass
class ModelParameters:
    """Model parameters for a model provider."""

    model: str
    api_key: str
    max_tokens: int
    temperature: float
    top_p: float
    top_k: int
    parallel_tool_calls: bool
    max_retries: int
    base_url: str | None = None
    api_version: str | None = None
    candidate_count: int | None = None  # Gemini specific field
    stop_sequences: list[str] | None = None


@dataclass
class LakeviewConfig:
    """Configuration for Lakeview."""

    model_provider: str
    model_name: str


@dataclass
class Config:
    """Configuration manager for Trae Agent."""

    default_provider: str
    max_steps: int
    model_providers: dict[str, ModelParameters]
    lakeview_config: LakeviewConfig | None = None
    enable_lakeview: bool = True

    def __init__(self, config_or_config_file: str | dict = "trae_config.json"):
        # Accept either file path or direct config dict
        if isinstance(config_or_config_file, dict):
            self._config = config_or_config_file
        else:
            config_path = Path(config_or_config_file)
            if config_path.exists():
                try:
                    with open(config_path, "r") as f:
                        self._config = json.load(f)
                except Exception as e:
                    print(f"Warning: Could not load config file {config_or_config_file}: {e}")
                    self._config = {}
            else:
                self._config = {}

        self.default_provider = self._config.get("default_provider", "anthropic")
        self.max_steps = self._config.get("max_steps", 20)
        self.model_providers = {}
        self.enable_lakeview = self._config.get("enable_lakeview", True)

        if len(self._config.get("model_providers", [])) == 0:
            self.model_providers = {
                "anthropic": ModelParameters(
                    model="claude-sonnet-4-20250514",
                    api_key="",
                    base_url="https://api.anthropic.com",
                    max_tokens=4096,
                    temperature=0.5,
                    top_p=1,
                    top_k=0,
                    parallel_tool_calls=True,
                    max_retries=10,
                ),
            }
        else:
            for provider in self._config.get("model_providers", {}):
                provider_config: dict[str, Any] = self._config.get("model_providers", {}).get(
                    provider, {}
                )

                candidate_count = provider_config.get("candidate_count")
                self.model_providers[provider] = ModelParameters(
                    model=str(provider_config.get("model", "")),
                    api_key=str(provider_config.get("api_key", "")),
                    base_url=str(provider_config.get("base_url"))
                    if "base_url" in provider_config
                    else None,
                    max_tokens=int(provider_config.get("max_tokens", 1000)),
                    temperature=float(provider_config.get("temperature", 0.5)),
                    top_p=float(provider_config.get("top_p", 1)),
                    top_k=int(provider_config.get("top_k", 0)),
                    max_retries=int(provider_config.get("max_retries", 10)),
                    parallel_tool_calls=bool(provider_config.get("parallel_tool_calls", False)),
                    api_version=str(provider_config.get("api_version"))
                    if "api_version" in provider_config
                    else None,
                    candidate_count=int(candidate_count) if candidate_count is not None else None,
                    stop_sequences=provider_config.get("stop_sequences")
                    if "stop_sequences" in provider_config
                    else None,
                )

        if "lakeview_config" in self._config:
            self.lakeview_config = LakeviewConfig(
                model_provider=str(
                    self._config.get("lakeview_config", {}).get("model_provider", "anthropic")
                ),
                model_name=str(
                    self._config.get("lakeview_config", {}).get(
                        "model_name", "claude-sonnet-4-20250514"
                    )
                ),
            )

        return

    @override
    def __str__(self) -> str:
        return f"Config(default_provider={self.default_provider}, max_steps={self.max_steps}, model_providers={self.model_providers})"


def load_config(config_file: str = "trae_config.json") -> Config:
    """Load configuration from file."""
    return Config(config_file)


def resolve_config_value(
    cli_value: int | str | float | None,
    config_value: int | str | float | None,
    env_var: str | None = None,
) -> int | str | float | None:
    """Resolve configuration value with priority: CLI > ENV > Config > Default."""
    if cli_value is not None:
        return cli_value

    if env_var and os.getenv(env_var):
        return os.getenv(env_var)

    if config_value is not None:
        return config_value

    return None
