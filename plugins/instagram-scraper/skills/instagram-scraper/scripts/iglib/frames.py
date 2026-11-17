"""ffmpeg helpers: probe, 10 fps scan, native-resolution frame grabs, token-cost math."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from PIL import Image

SCAN_FPS = 10
SCAN_LONG_EDGE = 768
PATCH = 28            # Claude vision: ~1 token per 28x28 px patch
MAX_PATCHES = 1568    # per-image budget; larger images get downscaled


def probe(video: Path) -> dict:
    """Return {'duration', 'has_audio', 'width', 'height'}."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration": float(d.get("format", {}).get("duration") or 0.0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": v.get("width"),
        "height": v.get("height"),
    }


def _scale_filter(long_edge: int) -> str:
    return (f"scale='if(gt(iw,ih),min({long_edge},iw),-2)'"
            f":'if(gt(iw,ih),-2,min({long_edge},ih))'")


def scan(video: Path, out_dir: Path, fps: int = SCAN_FPS) -> list[dict]:
    """Decode every 1/fps second to out_dir. Returns [{'path','t'}] in order. Cached."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("s*.jpg"))
    if not existing:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
             "-vf", f"fps={fps},{_scale_filter(SCAN_LONG_EDGE)}", "-q:v", "4",
             str(out_dir / "s%05d.jpg")],
            check=True)
        existing = sorted(out_dir.glob("s*.jpg"))
    return [{"path": str(p), "t": round(i / fps, 2)} for i, p in enumerate(existing)]


def grab_native(video: Path, t: float) -> Image.Image:
    """One frame at original resolution."""
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(raw)).convert("RGB")


def patches(w: int, h: int) -> int:
    return math.ceil(w / PATCH) * math.ceil(h / PATCH)


def est_tokens(w: int, h: int) -> int:
    return min(patches(w, h), MAX_PATCHES)


def fit_budget(img: Image.Image, max_patches: int = MAX_PATCHES) -> Image.Image:
    """Downscale (never upscale) so the image costs <= max_patches."""
    w, h = img.size
    if patches(w, h) <= max_patches:
        return img
    s = math.sqrt(max_patches / patches(w, h))
    while True:
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        if patches(nw, nh) <= max_patches:
            return img.resize((nw, nh), Image.LANCZOS)
        s *= 0.97
