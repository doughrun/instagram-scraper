"""Group near-identical consecutive frames into segments with a 64-bit dHash."""
from __future__ import annotations

from PIL import Image


def dhash(path: str) -> int:
    im = Image.open(path).convert("L").resize((9, 8), Image.BILINEAR)
    px = list(im.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def colorsig(path: str) -> tuple[int, ...]:
    """4x4 RGB thumbnail. dHash sees structure only; this catches cuts between
    similarly-laid-out scenes with different colors."""
    return tuple(c for px in Image.open(path).convert("RGB").resize((4, 4), Image.BOX).getdata() for c in px)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def color_dist(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def split(hashes: list[int], threshold: int, colors: list[tuple[int, ...]] | None = None,
          color_threshold: float = 40.0) -> list[tuple[int, int]]:
    """Pure: [(start_idx, end_idx_inclusive)]. New segment when the frame differs from
    the segment's FIRST frame (prevents slow pans chaining forever) by structure
    (dHash > threshold) or by color (mean abs diff > color_threshold)."""
    if not hashes:
        return []
    segs, start = [], 0
    for i in range(1, len(hashes)):
        cut = hamming(hashes[i], hashes[start]) > threshold
        if not cut and colors is not None:
            cut = color_dist(colors[i], colors[start]) > color_threshold
        if cut:
            segs.append((start, i - 1))
            start = i
    segs.append((start, len(hashes) - 1))
    return segs


def segment(hashes: list[int], threshold: int = 10, max_segments: int = 32,
            colors: list[tuple[int, ...]] | None = None) -> tuple[list[tuple[int, int]], int]:
    """Split, raising thresholds until there are <= max_segments. Returns (segments, dHash threshold used)."""
    th, cth = threshold, 40.0
    segs = split(hashes, th, colors, cth)
    while len(segs) > max_segments and th < 64:
        th += 2
        cth += 8
        segs = split(hashes, th, colors, cth)
    return segs, th
