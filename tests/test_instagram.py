"""Offline tests on synthetic, Instagram-shaped data (no real user data in the repo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/instagram-scraper/skills/instagram-scraper/scripts"))

from iglib.instagram import (collect_comments, find_media, find_posts, find_profile,  # noqa: E402
                             normalize_media, parse_shortcode, parse_username, thread_comments)


def test_parse_shortcode():
    assert parse_shortcode("https://www.instagram.com/p/Dfa5-jix5gw/") == "Dfa5-jix5gw"
    assert parse_shortcode("https://instagram.com/reel/ABC_123xyz/?igsh=x") == "ABC_123xyz"
    assert parse_shortcode("https://www.instagram.com/someuser/reel/ABC_123xyz/") == "ABC_123xyz"
    assert parse_shortcode("Dfa5-jix5gw") == "Dfa5-jix5gw"
    assert parse_shortcode("not a link!") is None


def test_parse_username():
    assert parse_username("@natgeo") == "natgeo"
    assert parse_username("https://www.instagram.com/nat.geo_1/") == "nat.geo_1"
    assert parse_username("https://www.instagram.com/p/Dfa5-jix5gw/") is None
    assert parse_username("has space") is None


ITEM = {
    "code": "ABC123", "media_type": 8, "taken_at": 1794063603, "like_count": 10, "comment_count": 3,
    "user": {"username": "owner1", "full_name": "Owner", "is_verified": True},
    "caption": {"text": "Reef day #coral #reef with @friend.one.", "created_at": 1, "pk": "9",
                "user": {"username": "owner1"}},
    "location": {"name": "Eilat", "lat": 29.5, "lng": 34.9},
    "clips_metadata": {"original_sound_info": {"original_audio_title": "Original audio",
                                               "ig_artist": {"username": "owner1"}}},
    "carousel_media": [
        {"media_type": 1, "image_versions2": {"candidates": [{"url": "u_small", "width": 320, "height": 400},
                                                             {"url": "u_big", "width": 1080, "height": 1350}]},
         "usertags": {"in": [{"user": {"username": "tagged.a"}}]}, "accessibility_caption": "Photo of coral"},
        {"media_type": 2, "video_versions": [{"url": "v1", "width": 720, "height": 1280}], "video_duration": 9.5},
    ],
}


def test_normalize_media_carousel():
    n = normalize_media(ITEM)
    assert n["type"] == "carousel" and n["owner"]["username"] == "owner1"
    assert n["hashtags"] == ["coral", "reef"] and n["mentions"] == ["friend.one"]
    assert n["tagged_users"] == ["tagged.a"]
    assert [m["type"] for m in n["media"]] == ["image", "video"]
    assert n["media"][0]["url"] == "u_big" and n["media"][0]["alt_text"] == "Photo of coral"
    assert n["audio"] == {"kind": "original", "title": "Original audio", "artist": "owner1"}
    assert n["taken_at"].startswith("2026-")


def _c(pk, text, likes=0, parent=None, replies=0):
    c = {"pk": pk, "text": text, "created_at": 1700000000 + int(pk), "user": {"username": f"u{pk}"},
         "comment_like_count": likes, "child_comment_count": replies}
    if parent:
        c["parent_comment_id"] = parent
    return c


def test_collect_and_thread_comments_skips_caption():
    blob = {"data": {"media": ITEM, "comments": [_c("1", "nice", 5, replies=1), _c("2", "wow", 9),
                                                  _c("3", "thanks!", 1, parent="1")]}}
    flat = collect_comments([blob], exclude_text=ITEM["caption"]["text"])
    assert set(flat) == {"1", "2", "3"}  # caption object excluded
    t = thread_comments(flat)
    assert [c["id"] for c in t] == ["2", "1"]
    assert [r["id"] for r in t[1]["replies"]] == ["3"]


def test_find_media_profile_posts():
    blobs = [{"x": [ITEM, {"code": "ABC123", "media_type": 8}]},
             {"data": {"user": {"username": "Owner1", "follower_count": 5}}}]
    assert find_media(blobs, "ABC123") is ITEM  # richest candidate wins
    assert find_profile(blobs, "owner1")["follower_count"] == 5
    assert list(find_posts(blobs, "owner1")) == ["ABC123"]
