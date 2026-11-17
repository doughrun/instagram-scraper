# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "platformdirs>=4",
#   "faster-whisper>=1.1",
#   "pillow>=10.1",
#   "rapidocr>=3.4",
#   "onnxruntime>=1.20",
#   "playwright>=1.48",
#   "filelock>=3.12",
#   "httpx>=0.27",
# ]
# ///
"""Instagram skill CLI. Prints JSON on stdout; progress on stderr.

Exit codes: 0 ok, 1 error, 2 bad input, 3 session_expired, 4 rate_limited.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shutil  # noqa: E402

from iglib import browser, frames, paths, session, transcribe, videomap  # noqa: E402


def emit(obj: dict, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return code


def out_dir_for(video: Path, out: str | None) -> Path:
    return Path(out) if out else paths.cache_dir("local") / video.stem


def _video(a) -> Path | None:
    v = Path(a.video)
    return v if v.is_file() else None


def cmd_video(a) -> int:
    v = _video(a)
    if not v:
        return emit({"error": "file_not_found", "path": a.video}, 2)
    res = videomap.analyze(v, out_dir_for(v, a.out), transcribe=not a.no_transcribe, model=a.model,
                           device=a.device, language=a.language, seg_threshold=a.seg_threshold,
                           max_segments=a.max_segments)
    return emit(res)


def cmd_zoom(a) -> int:
    v = _video(a)
    if not v:
        return emit({"error": "file_not_found", "path": a.video}, 2)
    out = out_dir_for(v, a.out)
    if a.start is not None or a.end is not None:
        dur = frames.probe(v)["duration"]
        return emit(videomap.zoom_range(v, out, a.start or 0.0, a.end if a.end is not None else dur))
    if a.t is None:
        return emit({"error": "bad_args", "message": "give --t (crop) or --start/--end (range)"}, 2)
    return emit(videomap.zoom_crop(v, out, a.t, a.region, a.box))


def cmd_thorough(a) -> int:
    v = _video(a)
    if not v:
        return emit({"error": "file_not_found", "path": a.video}, 2)
    res = videomap.thorough(v, out_dir_for(v, a.out), a.yes)
    return emit(res, 2 if "error" in res else 0)


def cmd_transcribe(a) -> int:
    v = _video(a)
    if not v:
        return emit({"error": "file_not_found", "path": a.video}, 2)
    if not frames.probe(v)["has_audio"]:
        return emit({"video": str(v), "has_audio": False, "speech_detected": False})
    return emit({"video": str(v), **transcribe.transcribe(v, out_dir_for(v, a.out), model=a.model,
                                                         device=a.device, language=a.language)})


def prereqs() -> dict:
    tools = {t: bool(shutil.which(t)) for t in ("uv", "ffmpeg", "ffprobe")}
    hints = {}
    if not (tools["ffmpeg"] and tools["ffprobe"]):
        hints["ffmpeg"] = {"windows": "winget install Gyan.FFmpeg", "macos": "brew install ffmpeg",
                           "linux": "sudo apt install ffmpeg  (or your distro's package manager)"}
    return {"tools": tools, "ok": all(tools.values()), "install_hints": hints}


def cmd_setup(a) -> int:
    res: dict = {"data_dir": str(paths.data_dir()), "prereqs": prereqs()}
    if not res["prereqs"]["ok"]:
        return emit({**res, "error": "missing_prereqs"}, 1)
    res["nvidia_gpu"] = transcribe.has_nvidia_gpu()
    res["gpu_pack_installed"] = transcribe.gpu_pack_installed()
    if a.gpu and res["nvidia_gpu"] and not res["gpu_pack_installed"]:
        res["gpu_pack"] = transcribe.install_gpu_pack()
    if a.allow_read:
        from iglib import permissions
        res["read_permission"] = permissions.add_read_rule(paths.data_dir())
    try:
        res["status"] = session.status()
    except browser.SessionExpired:
        if a.no_login:
            res["status"] = {"logged_in": False}
        else:
            res["login"] = session.login_window()
            res["status"] = session.status() if res["login"].get("ok") else {"logged_in": False}
    return emit(res, 0 if res["status"].get("logged_in") else 3)


def cmd_login(a) -> int:
    if a.paste:
        res = session.login_paste()
    else:
        res = session.login_window()
        if res.get("ok"):
            res.update(session.status())
    return emit(res, 0 if res.get("ok") else 3)


def cmd_status(_a) -> int:
    return emit(session.status())


def _post_opts(a) -> dict:
    return {"max_comments": 0 if a.no_comments else a.max_comments, "reply_threads": a.reply_threads,
            "analyze_video": not a.no_video, "transcribe": not a.no_transcribe, "refresh": a.refresh}


def cmd_post(a) -> int:
    from iglib import pipeline
    return emit(pipeline.run_post(a.target, _post_opts(a)))


def cmd_comments(a) -> int:
    """Compact text view of a fetched post's comments (no network)."""
    from iglib import instagram
    code = instagram.parse_shortcode(a.target)
    pj = paths.cache_dir("posts") / (code or "") / "post.json"
    if not code or not pj.exists():
        return emit({"error": "not_fetched", "message": f"run `post {a.target}` first"}, 2)
    post = json.loads(pj.read_text(encoding="utf-8"))
    cs = post.get("comments", [])
    if a.sort == "time":
        cs = sorted(cs, key=lambda c: c.get("created_at") or "")
    if a.grep:
        rx = re.compile(a.grep, re.I)
        cs = [c for c in cs if rx.search(c["text"]) or any(rx.search(r["text"]) for r in c.get("replies", []))]
    total = len(cs)
    lines = [f"# {post['shortcode']} by @{post['owner']['username']}: {post.get('comment_count')} comments on "
             f"Instagram, {post.get('comments_fetched')} fetched, showing {min(total, a.limit)}"
             + (f" matching /{a.grep}/" if a.grep else "")]
    for c in cs[: a.limit]:
        flat = " ".join(c["text"].split())
        lines.append(f"[{c['likes']}] {c['user']}: {flat}" + (f"  (+{c['reply_count']} replies)" if c["reply_count"] else ""))
        if not a.no_replies:
            for r in c.get("replies", []):
                lines.append(f"    ↳ [{r['likes']}] {r['user']}: {' '.join(r['text'].split())}")
    print("\n".join(lines))
    return 0


def cmd_profile(a) -> int:
    from iglib import pipeline
    opts = _post_opts(a)
    if not a.comments:
        opts["max_comments"] = 0
    return emit(pipeline.run_profile(a.target, {**opts, "limit": a.limit, "deep": a.deep}))


def cmd_gpu_setup(_a) -> int:
    if transcribe.gpu_pack_installed():
        return emit({"ok": True, "already_installed": True, "path": str(paths.gpu_pack_dir())})
    res = transcribe.install_gpu_pack()
    return emit(res, 0 if res.get("ok") else 1)


def main(argv: list[str] | None = None) -> int:
    # Windows consoles/pipes default to a legacy code page (e.g. cp1255) and crash on emoji.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="ig.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def base(sp):
        sp.add_argument("video", help="path to a local video file")
        sp.add_argument("--out", help="analysis directory (default: per-user cache/local/<name>)")

    def asr(sp):
        sp.add_argument("--model", help="whisper model override (e.g. small, large-v3-turbo)")
        sp.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
        sp.add_argument("--language", help="force language code (default: auto-detect)")

    sv = sub.add_parser("video", help="build the video map: segments, on-screen text, transcript, contact sheets")
    base(sv); asr(sv)
    sv.add_argument("--no-transcribe", action="store_true")
    sv.add_argument("--seg-threshold", type=int, default=10, help="dHash distance for a new segment")
    sv.add_argument("--max-segments", type=int, default=32)

    sz = sub.add_parser("zoom", help="native-res crop at --t, or contact sheet of every frame in --start..--end")
    base(sz)
    sz.add_argument("--t", type=float)
    sz.add_argument("--region", choices=sorted(videomap.REGIONS), default="full")
    sz.add_argument("--box", help="x,y,w,h as fractions 0-1 (overrides --region)")
    sz.add_argument("--start", type=float)
    sz.add_argument("--end", type=float)

    st = sub.add_parser("thorough", help="every segment at native res in quadrants (estimate first; --yes to run)")
    base(st)
    st.add_argument("--yes", action="store_true")

    stt = sub.add_parser("transcribe", help="transcript only")
    base(stt); asr(stt)

    sub.add_parser("gpu-setup", help="install the optional NVIDIA GPU pack for transcription")

    ss = sub.add_parser("setup", help="check prerequisites, log in if needed, optional GPU pack / read permission")
    ss.add_argument("--gpu", action="store_true", help="install the NVIDIA GPU pack (~1 GB) if a GPU is present")
    ss.add_argument("--allow-read", action="store_true",
                    help="add a Read allow-rule for the data folder to ~/.claude/settings.json")
    ss.add_argument("--no-login", action="store_true", help="don't open the login window")

    sl = sub.add_parser("login", help="log in to Instagram (opens a browser window once)")
    sl.add_argument("--paste", action="store_true", help="manual fallback: paste a sessionid cookie")

    sub.add_parser("status", help="check the Instagram session (one normal hidden page visit)")

    def post_args(sp, comments_default: int):
        sp.add_argument("--max-comments", type=int, default=comments_default)
        sp.add_argument("--reply-threads", type=int, default=10, help="reply threads to open (most-liked first)")
        sp.add_argument("--no-comments", action="store_true")
        sp.add_argument("--no-video", action="store_true", help="download videos but skip the video map")
        sp.add_argument("--no-transcribe", action="store_true")
        sp.add_argument("--refresh", action="store_true", help="redo video analysis even if cached")

    sp = sub.add_parser("post", help="fetch a post/reel: data, comments, media, video maps")
    sp.add_argument("target", help="post/reel URL or shortcode")
    post_args(sp, 200)

    sc = sub.add_parser("comments", help="print a fetched post's comments compactly (no network)")
    sc.add_argument("target", help="post URL or shortcode (must have been fetched with `post`)")
    sc.add_argument("--limit", type=int, default=100)
    sc.add_argument("--sort", choices=["likes", "time"], default="likes")
    sc.add_argument("--grep", help="only comments (or replies) matching this regex, case-insensitive")
    sc.add_argument("--no-replies", action="store_true")

    spr = sub.add_parser("profile", help="profile info + latest posts (+ thumbnail contact sheet)")
    spr.add_argument("target", help="username, @handle or profile URL")
    spr.add_argument("--limit", type=int, default=12)
    spr.add_argument("--deep", action="store_true", help="also run the full post pipeline on every post (slow)")
    spr.add_argument("--comments", action="store_true", help="with --deep: also fetch comments")
    post_args(spr, 50)

    a = p.parse_args(argv)
    handlers = {"video": cmd_video, "zoom": cmd_zoom, "thorough": cmd_thorough,
                "transcribe": cmd_transcribe, "gpu-setup": cmd_gpu_setup, "setup": cmd_setup,
                "login": cmd_login, "status": cmd_status, "post": cmd_post, "profile": cmd_profile,
                "comments": cmd_comments}
    try:
        return handlers[a.cmd](a)
    except browser.IGError as e:
        return emit(e.to_json(), e.code)
    except Exception as e:  # noqa: BLE001
        return emit({"error": type(e).__name__, "message": str(e)}, 1)


if __name__ == "__main__":
    sys.exit(main())
