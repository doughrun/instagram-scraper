"""Read Instagram data from captured page JSON (parse by shape, not by query name).

Pure helpers (parse_*, normalize_*, is_comment) are unit-tested; fetch_* do page visits.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .browser import NotFound, Visit, log, pause, walk

_CODE_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
_USER_RE = re.compile(r"instagram\.com/([A-Za-z0-9._]+)/?(?:\?.*)?$")
_RESERVED = {"p", "reel", "reels", "tv", "explore", "accounts", "stories", "direct", "about", "developer"}
HASHTAG = re.compile(r"#(\w+)", re.UNICODE)
MENTION = re.compile(r"@([A-Za-z0-9._]*[A-Za-z0-9_])")  # usernames can't end with "." (sentence period)


# ---------------- pure parsing ----------------

def parse_shortcode(s: str) -> str | None:
    s = s.strip()
    m = _CODE_RE.search(s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9_-]{5,20}", s) else None


def parse_username(s: str) -> str | None:
    s = s.strip().lstrip("@")
    m = _USER_RE.search(s)
    if m and m.group(1).lower() not in _RESERVED:
        return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9._]{1,30}", s) else None


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _best(cands: list | None, key=lambda c: (c.get("width") or 0) * (c.get("height") or 0)) -> dict | None:
    return max(cands, key=key) if cands else None


TYPE = {1: "image", 2: "video", 8: "carousel"}


def _media_entry(item: dict, index: int) -> dict:
    mt = TYPE.get(item.get("media_type"), "unknown")
    if mt == "video" or item.get("video_versions"):
        v = _best(item.get("video_versions"))
        return {"index": index, "type": "video", "url": v and v.get("url"),
                "width": v and v.get("width"), "height": v and v.get("height"),
                "duration": item.get("video_duration"), "has_audio": item.get("has_audio")}
    img = _best((item.get("image_versions2") or {}).get("candidates"))
    return {"index": index, "type": "image", "url": img and img.get("url"),
            "width": img and img.get("width"), "height": img and img.get("height"),
            "alt_text": item.get("accessibility_caption")}


def _audio(item: dict) -> dict | None:
    cm = item.get("clips_metadata") or {}
    mi = (cm.get("music_info") or {}).get("music_asset_info") or {}
    if mi:
        return {"kind": "music", "title": mi.get("title"), "artist": mi.get("display_artist")}
    osi = cm.get("original_sound_info") or {}
    if osi:
        return {"kind": "original", "title": osi.get("original_audio_title"),
                "artist": (osi.get("ig_artist") or {}).get("username")}
    return None


def normalize_media(item: dict) -> dict:
    cap = (item.get("caption") or {}).get("text") or ""
    owner = item.get("user") or item.get("owner") or {}
    kind = TYPE.get(item.get("media_type"), "unknown")
    if item.get("product_type") == "clips":
        kind = "reel"
    children = item.get("carousel_media") or [item]
    loc = item.get("location") or None
    return {
        "shortcode": item.get("code"),
        "url": f"https://www.instagram.com/p/{item.get('code')}/",
        "type": kind,
        "owner": {"username": owner.get("username"), "full_name": owner.get("full_name"),
                  "verified": owner.get("is_verified")},
        "taken_at": _iso(item.get("taken_at")),
        "caption": cap,
        "hashtags": HASHTAG.findall(cap),
        "mentions": MENTION.findall(cap),
        "tagged_users": sorted({(t.get("user") or {}).get("username")
                                for c in children for t in ((c.get("usertags") or {}).get("in") or [])
                                if (t.get("user") or {}).get("username")}),
        "coauthors": [c.get("username") for c in (item.get("coauthor_producers") or []) if c.get("username")],
        "location": {"name": loc.get("name"), "lat": loc.get("lat"), "lng": loc.get("lng")} if loc else None,
        "likes": None if item.get("like_and_view_counts_disabled") else item.get("like_count"),
        "comment_count": item.get("comment_count"),
        "views": item.get("view_count") or item.get("play_count") or item.get("ig_play_count"),
        "paid_partnership": bool(item.get("is_paid_partnership")),
        "audio": _audio(item),
        "comments_disabled": bool(item.get("comments_disabled")),
        "media": [_media_entry(c, i) for i, c in enumerate(children, 1)],
    }


def is_comment(o: dict) -> bool:
    return (isinstance(o.get("text"), str) and "created_at" in o and isinstance(o.get("user"), dict)
            and ("pk" in o or "id" in o) and "username" in o["user"])


def normalize_comment(c: dict) -> dict:
    return {
        "id": str(c.get("pk") or c.get("id")),
        "user": c["user"].get("username"),
        "verified": c["user"].get("is_verified"),
        "text": c["text"],
        "likes": c.get("comment_like_count") or c.get("like_count") or 0,
        "created_at": _iso(c.get("created_at")),
        "reply_count": c.get("child_comment_count") or 0,
        "parent_id": str(c["parent_comment_id"]) if c.get("parent_comment_id") else None,
    }


def collect_comments(blobs: list, exclude_text: str | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for b in blobs:
        for c in walk(b, is_comment):
            n = normalize_comment(c)
            if exclude_text is not None and n["text"] == exclude_text and n["parent_id"] is None \
                    and not c.get("child_comment_count") and "comment_like_count" not in c:
                continue  # the caption object is comment-shaped; skip it
            out[n["id"]] = n
    return out


def thread_comments(flat: dict[str, dict]) -> list[dict]:
    """Nest replies under parents; top-level sorted by likes desc."""
    tops = {k: {**v, "replies": []} for k, v in flat.items() if not v["parent_id"]}
    orphans = []
    for v in flat.values():
        if v["parent_id"]:
            (tops[v["parent_id"]]["replies"] if v["parent_id"] in tops else orphans).append(v)
    for t in tops.values():
        t["replies"].sort(key=lambda r: r["created_at"] or "")
    res = sorted(tops.values(), key=lambda c: -c["likes"])
    return res + [{**o, "replies": [], "orphan_reply": True} for o in orphans]


def find_media(blobs: list, code: str) -> dict | None:
    cands = [d for b in blobs for d in walk(b, lambda o: o.get("code") == code and "media_type" in o)]
    return max(cands, key=len) if cands else None


def find_profile(blobs: list, username: str) -> dict | None:
    cands = [d for b in blobs for d in walk(
        b, lambda o: str(o.get("username", "")).lower() == username.lower() and "follower_count" in o)]
    return max(cands, key=len) if cands else None


def find_posts(blobs: list, owner: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for b in blobs:
        for d in walk(b, lambda o: "code" in o and "media_type" in o and "taken_at" in o):
            u = (d.get("user") or d.get("owner") or {}).get("username")
            if u is None or u.lower() == owner.lower():
                out.setdefault(d["code"], d)
    return out


# ---------------- page visits ----------------

_PANEL_JS = """() => {
  const els = [...document.querySelectorAll('div, ul, section')].filter(e => {
    const s = getComputedStyle(e);
    return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 40 && e.clientHeight > 150;
  });
  els.sort((a, b) => b.clientHeight * b.clientWidth - a.clientHeight * a.clientWidth);
  const el = els[0];
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {x: r.x + r.width / 2, y: Math.max(10, Math.min(r.y + r.height / 2, innerHeight - 10)),
          atEnd: el.scrollTop + el.clientHeight >= el.scrollHeight - 5};
}"""

_REPLY_BTN_JS = """() => {
  // innermost element whose text is a "View replies" label and that we haven't clicked yet
  const re = /^\\s*(—\\s*)?View (all )?(\\d+ )?(more )?repl(y|ies)/i;
  const all = [...document.querySelectorAll('span, button, div[role="button"]')]
    .filter(e => re.test(e.textContent || '') && !e.dataset.igskillClicked);
  const inner = all.filter(e => !all.some(o => o !== e && e.contains(o)));
  const b = inner[0];
  if (!b) return false;
  let p = b; for (let i = 0; i < 4 && p; i++, p = p.parentElement) p.dataset.igskillClicked = '1';
  b.scrollIntoView({block: 'center'});
  b.click();
  return true;
}"""


def fetch_post(ctx, code: str, max_comments: int = 200, reply_threads: int = 10) -> dict:
    v = Visit(ctx, f"/p/{code}/")
    if v.is_404():
        raise NotFound(f"post {code} not found (deleted, private, or wrong link)")
    item = find_media(v.all_json(), code)
    if not item:
        raise NotFound(f"no data for post {code} on the page (private account, or Instagram changed its page)")
    post = normalize_media(item)
    caption = post["caption"]
    comments = collect_comments(v.all_json(), exclude_text=caption) if max_comments > 0 else {}

    if max_comments > 0 and not post["comments_disabled"]:
        stagnant, rounds = 0, 0
        while len([c for c in comments.values() if not c["parent_id"]]) < max_comments and stagnant < 3 \
                and rounds < max_comments // 5 + 5:
            box = v.page.evaluate(_PANEL_JS)
            if not box:
                break
            v.page.mouse.move(box["x"], box["y"])
            v.page.mouse.wheel(0, 900)
            pause(2.0, 4.0)
            v.check()
            before = len(comments)
            comments.update(collect_comments([d for _, d in v.responses], exclude_text=caption))
            stagnant = stagnant + 1 if len(comments) == before else 0
            rounds += 1
        if reply_threads > 0 and any(c["reply_count"] for c in comments.values()):
            clicked = 0
            while clicked < reply_threads and v.page.evaluate(_REPLY_BTN_JS):
                clicked += 1
                pause(0.8, 1.8)
            if clicked:
                log(f"Opened {clicked} reply threads")
                pause(2.0, 3.5)
                v.check()
                comments.update(collect_comments([d for _, d in v.responses], exclude_text=caption))

    tops = [c for c in comments.values() if not c["parent_id"]]
    post["comments"] = thread_comments(comments) if max_comments > 0 else []
    post["comments_fetched"] = len(tops)
    post["replies_fetched"] = len(comments) - len(tops)
    post["comments_note"] = ("reply_count can include replies Instagram hides (deleted/restricted), "
                             "so fetched replies may be fewer than reply_count")
    post["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return post


def fetch_profile(ctx, username: str, limit: int = 12) -> dict:
    v = Visit(ctx, f"/{username}/")
    if v.is_404():
        raise NotFound(f"profile @{username} not found")
    u = find_profile(v.all_json(), username)
    if not u:
        raise NotFound(f"no profile data for @{username} on the page")
    posts = find_posts(v.all_json(), username)
    stagnant = 0
    while len(posts) < limit and stagnant < 3 and not u.get("is_private"):
        v.page.mouse.move(640, 600)
        v.page.mouse.wheel(0, 2500)
        pause(2.5, 4.5)
        v.check()
        before = len(posts)
        posts.update(find_posts([d for _, d in v.responses], username))
        stagnant = stagnant + 1 if len(posts) == before else 0
    ordered = sorted(posts.values(), key=lambda d: -(d.get("taken_at") or 0))
    pinned = {d["code"] for d in ordered if d.get("timeline_pinned_user_ids")}
    items = [normalize_media(d) | {"pinned": d["code"] in pinned} for d in ordered[:limit]]
    for d, it in zip(ordered[:limit], items):
        thumb = _best((d.get("image_versions2") or {}).get("candidates"),
                      key=lambda c: -abs((c.get("width") or 0) - 480))
        it["thumbnail_url"] = thumb and thumb.get("url")
    links = [bl.get("url") for bl in (u.get("bio_links") or []) if bl.get("url")]
    return {
        "username": u.get("username"),
        "full_name": u.get("full_name"),
        "biography": u.get("biography"),
        "external_url": u.get("external_url"),
        "bio_links": links,
        "category": u.get("category") or u.get("category_name") or None,
        "followers": u.get("follower_count"),
        "following": u.get("following_count"),
        "post_count": u.get("media_count"),
        "verified": u.get("is_verified"),
        "private": u.get("is_private"),
        "business": u.get("is_business"),
        "posts": items,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

