from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceConfig:
    label: str = "FLYSIGHT"
    fallback_to_first_fat: bool = False
    max_size_gb: int = 64


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 5050


@dataclass(frozen=True)
class UIConfig:
    default_download_root: str = "~/Downloads/flysight"
    browse_poll_seconds: int = 4


@dataclass(frozen=True)
class SecurityConfig:
    sudo_idle_timeout_minutes: int = 30


@dataclass(frozen=True)
class JobsConfig:
    max_history: int = 50
    max_log_lines: int = 500


@dataclass(frozen=True)
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    jobs: JobsConfig = field(default_factory=JobsConfig)
    source_path: str = ""   # which file we loaded from, or "" for defaults


SEARCH_PATHS = (
    Path("./config.toml"),
    Path("~/.config/flysight-local-explorer/config.toml").expanduser(),
)

_cache: Config | None = None


def _from_dict(data: dict[str, Any], source_path: str) -> Config:
    def _sub(section: str, cls):
        return cls(**(data.get(section) or {}))
    return Config(
        device=_sub("device", DeviceConfig),
        server=_sub("server", ServerConfig),
        ui=_sub("ui", UIConfig),
        security=_sub("security", SecurityConfig),
        jobs=_sub("jobs", JobsConfig),
        source_path=source_path,
    )


def load() -> Config:
    """Load and return config from the first matching path, or built-in defaults."""
    for p in SEARCH_PATHS:
        if p.exists():
            with p.open("rb") as f:
                data = tomllib.load(f)
            return _from_dict(data, str(p))
    return Config()


def get() -> Config:
    """Cached accessor — load() on first call, subsequently return the same instance."""
    global _cache
    if _cache is None:
        _cache = load()
    return _cache


def reset_cache() -> None:
    """Test hook: drop the cached Config so the next get() reloads from disk."""
    global _cache
    _cache = None
