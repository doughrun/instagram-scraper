"""On-screen text via RapidOCR (ONNX, CPU), parallel across processes, cleaned into time spans.

Real reels have stylized overlays that OCR misreads slightly differently on every frame.
Pipeline: per-frame reads -> global fuzzy clustering (canonical = most frequent variant)
-> gap-tolerant spans -> singleton-noise filter -> persistent overlays split out.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher

MIN_SCORE = 0.6
SINGLETON_MIN_SCORE = 0.9   # a reading seen in only one sample must be this confident...
SINGLETON_MIN_LEN = 4       # ...and this long, or it's treated as noise
CLUSTER_RATIO = 0.75
PERSISTENT_SHARE = 0.5      # text on screen for >= 50% of the video = overlay/watermark
_engine = None

Read = tuple[str, float]


def _get_engine():
    global _engine
    if _engine is None:
        logging.disable(logging.WARNING)
        from rapidocr import RapidOCR
        _engine = RapidOCR(params={
            "Global.use_cls": False,
            "Global.log_level": "error",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        })
    return _engine


def _ocr_one(path: str) -> list[Read]:
    r = _get_engine()(path)
    if not r.txts:
        return []
    # drop low-confidence and symbol-only reads (shapes misread as "●", "-", etc.)
    return [(t.strip(), float(s)) for t, s in zip(r.txts, r.scores)
            if s >= MIN_SCORE and any(ch.isalnum() for ch in t)]


def ocr_frames(paths: list[str], skip: list[bool], workers: int | None = None) -> list[list[Read]]:
    """OCR each path; where skip[i] is True, reuse the previous frame's result."""
    todo = [p for p, s in zip(paths, skip) if not s]
    workers = workers or max(1, min(8, (os.cpu_count() or 2) // 2))
    print(f"OCR on {len(todo)} frames with {workers} workers...", file=sys.stderr, flush=True)
    if workers == 1:
        done = [_ocr_one(p) for p in todo]
    else:
        with ProcessPoolExecutor(workers) as ex:
            done = list(ex.map(_ocr_one, todo, chunksize=4))
    it = iter(done)
    out: list[list[Read]] = []
    for s in skip:
        if s:
            out.append(out[-1] if out else [])
        else:
            out.append(next(it))
    return out


_CONFUSABLE = str.maketrans({"o": "0", "l": "1", "i": "1", "|": "1"})


def _norm(s: str) -> str:
    """Comparison key only (never shown): lowercase alnum with OCR-confusable chars unified."""
    return re.sub(r"[^0-9a-z]+", "", s.lower().translate(_CONFUSABLE))


FRAGMENT_MIN_LEN = 4        # a partial read this long can join a longer text's cluster
FRAGMENT_RATIO = 0.8
MIN_LEN = 3                 # reads shorter than this (normalized) need a confident score


def _sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 1.0 if a == b else 0.0
    return 1.0 if na == nb else SequenceMatcher(None, na, nb).ratio()


def _fragment_of(short: str, long: str) -> bool:
    """True if `short` is a (slightly misread) piece of `long`, e.g. 'TIE GRECORY' of
    'WITH BERTIE GREGORY' or 'hulu' of 'Disney+ hulu'."""
    ns, nl = _norm(short), _norm(long)
    if len(ns) < FRAGMENT_MIN_LEN or len(ns) >= len(nl):
        return False
    w = len(ns)
    best = max(SequenceMatcher(None, ns, nl[i:i + w]).ratio() for i in range(len(nl) - w + 1))
    return best >= FRAGMENT_RATIO


def canonicalize(texts: list[list[Read]]) -> tuple[list[list[Read]], dict[str, int]]:
    """Pure. Cluster all readings across the video; replace each with its cluster's
    canonical form (most frequent variant, ties -> longer). Returns (texts, cluster sizes)."""
    freq = Counter(t for lines in texts for t, _ in lines)
    canon_of: dict[str, str] = {}
    clusters: list[list[str]] = []
    # pass 1: whole-string clusters, most frequent variant first
    for variant, _ in sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        for cl in clusters:
            if _sim(variant, cl[0]) >= CLUSTER_RATIO:
                cl.append(variant)
                canon_of[variant] = cl[0]
                break
        else:
            clusters.append([variant])
            canon_of[variant] = variant
    # pass 2: fold clusters whose head is a fragment of a longer, more frequent cluster's head
    weight = {cl[0]: sum(freq[v] for v in cl) for cl in clusters}
    heads = sorted(weight, key=lambda h: -weight[h])
    parent = {h: h for h in heads}
    for h in heads:
        for big in heads:
            if big != h and weight[big] >= weight[h] and _fragment_of(h, big):
                parent[h] = big
                break
    def root(h):
        while parent[h] != h:
            h = parent[h]
        return h
    for v in canon_of:
        canon_of[v] = root(canon_of[v])
    clusters = [[h] + [v for v in canon_of if canon_of[v] == h and v != h] for h in heads if root(h) == h]
    sizes = {cl[0]: sum(freq[v] for v in cl) for cl in clusters}
    out = []
    for lines in texts:
        seen: dict[str, float] = {}
        for t, s in lines:
            c = canon_of[t]
            seen[c] = max(seen.get(c, 0.0), s)
        out.append(list(seen.items()))
    return out, sizes


def spans(times: list[float], texts: list[list[Read]], step: float, max_gap: int = 2) -> list[dict]:
    """Pure: [{start, end, text, samples, score}]. Text must already be canonical.
    A span survives up to `max_gap` consecutive samples where OCR missed it."""
    open_: dict[str, dict] = {}
    closed: list[dict] = []
    for t, lines in zip(times, texts):
        present = dict(lines)
        for txt in list(open_):
            sp = open_[txt]
            if txt in present:
                sp["end"] = round(t + step, 2)
                sp["samples"] += 1
                sp["score"] = max(sp["score"], present[txt])
                sp["miss"] = 0
            else:
                sp["miss"] += 1
                if sp["miss"] > max_gap:
                    closed.append(open_.pop(txt))
        for txt, sc in lines:
            if txt not in open_:
                open_[txt] = {"start": t, "end": round(t + step, 2), "text": txt,
                              "samples": 1, "score": sc, "miss": 0}
    closed.extend(open_.values())
    for sp in closed:
        sp.pop("miss", None)
        sp["score"] = round(sp["score"], 3)
    return sorted(closed, key=lambda s: (s["start"], s["text"]))


def clean(times: list[float], raw: list[list[Read]], step: float, duration: float) -> dict:
    """Full cleanup. Returns {'spans': [...], 'persistent': [texts]}."""
    texts, sizes = canonicalize(raw)
    sp = spans(times, texts, step)
    keep = []
    for s in sp:
        n = len(_norm(s["text"]))
        if n < MIN_LEN and s["score"] < SINGLETON_MIN_SCORE:
            continue
        singleton = s["samples"] == 1 and sizes.get(s["text"], 0) <= 1
        if singleton and (s["score"] < SINGLETON_MIN_SCORE or n < SINGLETON_MIN_LEN):
            continue
        keep.append(s)
    cover: dict[str, float] = {}
    for s in keep:
        cover[s["text"]] = cover.get(s["text"], 0.0) + (s["end"] - s["start"])
    persistent = sorted(t for t, c in cover.items() if duration > 0 and c / duration >= PERSISTENT_SHARE)

    def overlay_misread(t: str) -> bool:
        # heavy misreads of a known overlay that escaped clustering ("MIN BERTIE GRESONT")
        return any(_sim(t, p) >= 0.6 for p in persistent)

    spans_out = [s for s in keep if s["text"] not in persistent and not overlay_misread(s["text"])]
    return {"spans": spans_out, "persistent": persistent}
