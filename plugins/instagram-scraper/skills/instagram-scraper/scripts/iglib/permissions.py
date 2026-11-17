"""Opt-in: let Claude Code Read the skill's data folder without a prompt per file.

Rule format per Claude Code permission docs: `//` = absolute from filesystem root; Windows paths
are matched in POSIX form, so C:\\Users\\x becomes //c/Users/x.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PureWindowsPath


def rule_for(path: Path) -> str:
    p = str(path.resolve())
    if os.name == "nt":
        w = PureWindowsPath(p)
        drive = w.drive.rstrip(":").lower()
        rest = "/".join(w.parts[1:])
        posix = f"/{drive}/{rest}"
    else:
        posix = Path(p).as_posix()
    return f"Read(/{posix}/**)"


def settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "settings.json"


def add_read_rule(data_dir: Path) -> dict:
    rule = rule_for(data_dir)
    sp = settings_path()
    try:
        settings = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except ValueError:
        return {"ok": False, "error": "settings_unparseable", "path": str(sp), "rule": rule,
                "message": "settings.json isn't valid JSON; add the rule by hand"}
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    if rule in allow:
        return {"ok": True, "already_present": True, "rule": rule, "path": str(sp)}
    allow.append(rule)
    sp.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=sp.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, sp)  # atomic: never leaves a half-written settings file
    return {"ok": True, "added": True, "rule": rule, "path": str(sp)}
