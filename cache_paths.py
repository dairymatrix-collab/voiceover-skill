"""Resolve Hugging Face cache locations without importing optional ML packages."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def hf_home_path(*, environ: Mapping[str, str] | None = None,
                 home: str | Path | None = None) -> Path:
    """Return Hugging Face's base cache directory using upstream env precedence."""
    env = os.environ if environ is None else environ
    configured = env.get("HF_HOME")
    if configured:
        return Path(configured).expanduser()

    xdg_cache = env.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache).expanduser()
    else:
        user_home = Path.home() if home is None else Path(home).expanduser()
        base = user_home / ".cache"
    return base / "huggingface"


def hf_hub_cache_path(*, environ: Mapping[str, str] | None = None,
                      home: str | Path | None = None) -> Path:
    """Return the effective Hub cache, honoring explicit override first."""
    env = os.environ if environ is None else environ
    configured = env.get("HF_HUB_CACHE")
    if configured:
        return Path(configured).expanduser()
    return hf_home_path(environ=env, home=home) / "hub"
