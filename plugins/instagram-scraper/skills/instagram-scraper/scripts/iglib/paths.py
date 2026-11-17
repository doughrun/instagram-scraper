"""Per-user data locations. Nothing is ever written inside the skill/repo folder."""
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP = "instagram-scraper"
OLD_APP = "instagram-skill"  # pre-rename folder; moved over once so logins and caches survive


def data_dir() -> Path:
    override = os.environ.get("IG_SKILL_DATA_DIR")
    if override:
        d = Path(override)
    else:
        d = Path(user_data_dir(APP, appauthor=False))
        old = Path(user_data_dir(OLD_APP, appauthor=False))
        if not d.exists() and old.is_dir():
            try:
                old.rename(d)
            except OSError:
                pass  # e.g. a browser still has the old profile open; fall back to a fresh folder
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def gpu_pack_dir() -> Path:
    return data_dir() / "gpu-pack"


def cache_dir(kind: str) -> Path:
    d = data_dir() / "cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d
