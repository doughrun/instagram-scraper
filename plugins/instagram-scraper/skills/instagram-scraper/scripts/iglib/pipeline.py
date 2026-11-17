"""post / profile commands: fetch -> download media -> analyze videos -> write JSON."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from . import browser, instagram, paths, sheets, videomap
from .browser import log, pause


def _download(url: str, dest: Path, ua: str | None) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": ua or "Mozilla/5.0", "Referer": "https://www.instagram.com/"}
    with httpx.stream("GET", url, headers=headers, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    return dest


def _process_post(ctx, code: str, opts: dict) -> dict:
    out = paths.cache_dir("posts") / code
    ua = browser.load_config().get("user_agent")
    post = instagram.fetch_post(ctx, code, max_comments=opts.get("max_comments", 200),
                                reply_threads=opts.get("reply_threads", 10))
    for m in post["media"]:
        if not m.get("url"):
            continue
        ext = "mp4" if m["type"] == "video" else "jpg"
        m["path"] = str(_download(m["url"], out / "media" / f"{m['index']:02d}.{ext}", ua))
        m.pop("url")  # signed CDN URLs expire; the local file is what matters
    if opts.get("analyze_video", True):
        for m in post["media"]:
            if m["type"] != "video" or "path" not in m:
                continue
            adir = out / "analysis" / f"{m['index']:02d}"
            if (adir / "video_map.json").exists() and not opts.get("refresh"):
                log(f"Reusing analysis for media {m['index']}")
                vm = json.loads((adir / "video_map.json").read_text(encoding="utf-8"))
                m["analysis"] = {"map": str(adir / "video_map.md"), "sheets": vm["sheets"],
                                 "segment_count": len(vm["segments"])}
            else:
                res = videomap.analyze(Path(m["path"]), adir, transcribe=opts.get("transcribe", True))
                m["analysis"] = {"map": res["map"], "sheets": res["sheets"],
                                 "segment_count": res["segment_count"], "timings_s": res["timings_s"]}
                m["duration"] = m.get("duration") or round(res["duration"], 2)
                m["has_audio"] = res["has_audio"]
    (out / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"post_dir": str(out), "post_json": str(out / "post.json"), "post": post}


def _summary(post: dict) -> dict:
    """Compact stdout view; full data lives in post.json."""
    top = [{"user": c["user"], "likes": c["likes"], "text": c["text"][:200], "replies": c["reply_count"]}
           for c in post["comments"][:5]]
    return {
        "shortcode": post["shortcode"], "type": post["type"], "owner": post["owner"]["username"],
        "taken_at": post["taken_at"], "likes": post["likes"], "views": post["views"],
        "comment_count": post["comment_count"], "comments_fetched": post["comments_fetched"],
        "replies_fetched": post["replies_fetched"], "caption": post["caption"][:500],
        "hashtags": post["hashtags"], "mentions": post["mentions"], "tagged_users": post["tagged_users"],
        "audio": post["audio"], "paid_partnership": post["paid_partnership"], "location": post["location"],
        "media": [{k: m.get(k) for k in ("index", "type", "path", "duration", "alt_text", "analysis") if m.get(k)}
                  for m in post["media"]],
        "top_comments": top,
    }


def run_post(target: str, opts: dict) -> dict:
    code = instagram.parse_shortcode(target)
    if not code:
        raise browser.NotFound(f"not an Instagram post link or shortcode: {target}")
    with browser.hidden_browser() as ctx:
        res = _process_post(ctx, code, opts)
    return {"post_dir": res["post_dir"], "post_json": res["post_json"], **_summary(res["post"])}


def run_profile(target: str, opts: dict) -> dict:
    user = instagram.parse_username(target)
    if not user:
        raise browser.NotFound(f"not an Instagram username or profile link: {target}")
    out = paths.cache_dir("profiles") / user
    ua = browser.load_config().get("user_agent")
    deep = []
    with browser.hidden_browser() as ctx:
        prof = instagram.fetch_profile(ctx, user, limit=opts.get("limit", 12))
        tiles = []
        for i, p in enumerate(prof["posts"], 1):
            url = p.pop("thumbnail_url", None)
            for m in p["media"]:
                m.pop("url", None)
            if url:
                p["thumbnail"] = str(_download(url, out / "thumbs" / f"{p['shortcode']}.jpg", ua))
                tiles.append({"path": p["thumbnail"], "label": f"#{i} {p['type'][:5]}"})
        prof["thumbnail_sheets"] = sheets.build(tiles, out, "posts_sheet") if tiles else []
        if opts.get("deep"):
            for p in prof["posts"]:
                pause(3.0, 6.0)
                r = _process_post(ctx, p["shortcode"], opts)
                deep.append({"shortcode": p["shortcode"], "post_json": r["post_json"]})
    (out / "profile.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "profile_json": str(out / "profile.json"),
        **{k: prof[k] for k in ("username", "full_name", "biography", "external_url", "bio_links", "category",
                                "followers", "following", "post_count", "verified", "private", "business")},
        "thumbnail_sheets": prof["thumbnail_sheets"],
        "posts": [{"n": i, "shortcode": p["shortcode"], "type": p["type"], "taken_at": p["taken_at"],
                   "likes": p["likes"], "comments": p["comment_count"], "views": p["views"],
                   "pinned": p.get("pinned"), "caption": p["caption"][:160], "hashtags": p["hashtags"]}
                  for i, p in enumerate(prof["posts"], 1)],
        "deep": deep or None,
    }
