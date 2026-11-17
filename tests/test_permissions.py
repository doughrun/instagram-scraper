import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/instagram-scraper/skills/instagram-scraper/scripts"))

from iglib import permissions  # noqa: E402


def test_rule_format(tmp_path):
    r = permissions.rule_for(tmp_path)
    assert r.startswith("Read(//") and r.endswith("/**)")
    assert "\\" not in r and ":" not in r


def test_add_rule_preserves_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls)"]}}))
    data = tmp_path / "data"
    data.mkdir()
    r1 = permissions.add_read_rule(data)
    r2 = permissions.add_read_rule(data)
    s = json.loads(sp.read_text())
    assert r1["added"] and r2["already_present"]
    assert s["model"] == "x"
    assert s["permissions"]["allow"] == ["Bash(ls)", permissions.rule_for(data)]


def test_bad_settings_not_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text("{not json")
    r = permissions.add_read_rule(tmp_path)
    assert not r["ok"] and (tmp_path / "settings.json").read_text() == "{not json"
