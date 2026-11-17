"""Windows-compatible trigger eval (same logic as skill-creator's run_eval.py, which uses
select() on pipes and so only runs on macOS/Linux).

For each query: expose the skill's name+description as a temporary project command, run
`claude -p <query>` with streaming output, and record whether Claude's FIRST tool call loads
this skill. The process is killed at the first tool call, so nothing is ever executed.

Usage: python evals/trigger_eval.py <SKILL.md> <queries.json> [--model ID] [--runs N] [--timeout S]
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_skill(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    fm = re.search(r"^---\n(.*?)\n---", text, re.S).group(1)
    name = re.search(r"^name:\s*(.+)$", fm, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).strip()
    return name, desc


def run_one(query: str, name: str, desc: str, model: str | None, timeout: int) -> bool | None:
    clean = f"{name}-skill-{uuid.uuid4().hex[:8]}"
    cmd_dir = ROOT / ".claude" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    cmd_file = cmd_dir / f"{clean}.md"
    indented = "\n  ".join(desc.split("\n"))
    cmd_file.write_text(f"---\ndescription: |\n  {indented}\n---\n\n# {name}\n\nThis skill handles: {desc}\n",
                        encoding="utf-8")
    args = ["claude", "-p", query, "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
    if model:
        args += ["--model", model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    # no shell: queries contain &, ?, quotes that a shell would mangle
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=ROOT, env=env)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout] or lines.put(None), daemon=True).start()
    pending, acc = None, ""
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = lines.get(timeout=1)
            except queue.Empty:
                continue
            if raw is None:
                return False
            try:
                ev = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if ev.get("type") == "stream_event":
                se = ev.get("event", {})
                t = se.get("type")
                if t == "content_block_start":
                    cb = se.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        if os.environ.get("TRIGGER_DEBUG"):
                            print(f"  first tool: {cb.get('name')}", file=sys.stderr)
                        if cb.get("name") in ("Skill", "Read"):
                            pending, acc = cb.get("name"), ""
                        else:
                            return False
                elif t == "content_block_delta" and pending:
                    acc += se.get("delta", {}).get("partial_json", "")
                    if clean in acc:
                        return True
                elif t in ("content_block_stop", "message_stop"):
                    if pending:
                        if os.environ.get("TRIGGER_DEBUG"):
                            print(f"  {pending} input: {acc[:200]}", file=sys.stderr)
                        return clean in acc
                    if t == "message_stop":
                        return False
            elif ev.get("type") == "result":
                return False
        return None  # timeout
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
        cmd_file.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("skill_md")
    ap.add_argument("queries")
    ap.add_argument("--model")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=90)
    # Keep 1: parallel runs each add a temp copy of the skill, Claude may pick another run's copy,
    # and that run then (wrongly) scores as "not triggered".
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    name, desc = read_skill(Path(a.skill_md))
    qs = json.loads(Path(a.queries).read_text(encoding="utf-8"))
    jobs = [(i, r) for i in range(len(qs)) for r in range(a.runs)]
    results: dict[int, list] = {i: [] for i in range(len(qs))}
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(run_one, qs[i]["query"], name, desc, a.model, a.timeout): i for i, _ in jobs}
        for f, i in futs.items():
            results[i].append(f.result())
    ok = 0
    for i, q in enumerate(qs):
        rs = results[i]
        rate = sum(1 for r in rs if r) / len(rs)
        passed = (rate >= 0.5) == q["should_trigger"]
        ok += passed
        mark = "PASS" if passed else "FAIL"
        print(f"{mark} want={'T' if q['should_trigger'] else 'F'} got={rate:.0%} {rs} | {q['query'][:90]}")
    print(f"\n{ok}/{len(qs)} correct")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
