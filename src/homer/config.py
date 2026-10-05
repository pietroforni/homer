from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


class ConfigurationError(ValueError):
    """Raised when Homer configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    model: str = "qwen2.5:7b"
    ollama_host: str = "http://localhost:11434"
    timeout_seconds: float = 60.0
    context_tokens: int = 8192
    style_guide: Path | None = None


@dataclass(frozen=True)
class LoadedSettings:
    values: Settings
    source: Path | None


_ALLOWED_KEYS = {
    "model",
    "ollama_host",
    "style_guide",
    "timeout_seconds",
    "context_tokens",
}

_REMOVED_KEYS = {"shell", "allow_high_risk"}


def find_config(explicit: Path | None = None, home: Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise ConfigurationError(f"Configuration file does not exist: {candidate}")
        return candidate

    env_path = os.environ.get("HOMER_CONFIG")
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if not candidate.is_file():
            raise ConfigurationError(f"HOMER_CONFIG does not exist: {candidate}")
        return candidate

    user_config = (home or Path.home()) / ".config" / "homer" / "config.yaml"
    return user_config.resolve() if user_config.is_file() else None


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError("The configuration root must be a YAML mapping.")
    removed = set(raw) & _REMOVED_KEYS
    if removed:
        names = ", ".join(sorted(str(item) for item in removed))
        raise ConfigurationError(
            f"Removed configuration option(s): {names}. "
            "Homer now always uses /bin/zsh and blocks high-risk commands."
        )
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        names = ", ".join(sorted(str(item) for item in unknown))
        raise ConfigurationError(f"Unknown configuration option(s): {names}")
    return raw


def _validate(settings: Settings) -> Settings:
    if not settings.model.strip():
        raise ConfigurationError("model cannot be empty")
    parsed = urlparse(settings.ollama_host)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError("ollama_host must be an http:// or https:// URL")
    if settings.timeout_seconds <= 0:
        raise ConfigurationError("timeout_seconds must be greater than zero")
    if not 1024 <= settings.context_tokens <= 131072:
        raise ConfigurationError("context_tokens must be between 1024 and 131072")
    return settings


def load_settings(
    path: Path | None = None,
    *,
    model: str | None = None,
    ollama_host: str | None = None,
    style_guide: Path | None = None,
) -> LoadedSettings:
    source = find_config(path)
    raw = _load_yaml(source) if source else {}
    base = source.parent if source else Path.cwd()

    try:
        configured_style = raw.get("style_guide")
        settings = Settings(
            model=str(raw.get("model", Settings.model)),
            ollama_host=str(raw.get("ollama_host", Settings.ollama_host)).rstrip("/"),
            timeout_seconds=float(raw.get("timeout_seconds", Settings.timeout_seconds)),
            context_tokens=int(raw.get("context_tokens", Settings.context_tokens)),
            style_guide=(
                (base / Path(str(configured_style)).expanduser()).resolve()
                if configured_style is not None
                else None
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid configuration value: {exc}") from exc

    overrides: dict[str, Any] = {}
    if model is not None:
        overrides["model"] = model
    if ollama_host is not None:
        overrides["ollama_host"] = ollama_host.rstrip("/")
    if style_guide is not None:
        overrides["style_guide"] = style_guide.expanduser().resolve()
    return LoadedSettings(_validate(replace(settings, **overrides)), source)


def is_loopback_host(host: str) -> bool:
    hostname = (urlparse(host).hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}
