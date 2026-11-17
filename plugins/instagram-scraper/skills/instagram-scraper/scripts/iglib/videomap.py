"""Video "map, then zoom": scan -> segments -> OCR spans -> transcript -> map + contact sheets.
Plus zoom (native-res crops, dense ranges) and thorough (all segments, quadrants)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from . import frames, ocr, segments, sheets
from . import transcribe as tr

OCR_EVERY = 2          # OCR every 2nd scan frame -> 5 fps
SEGMENTS_PER_SECOND = 0.75
OCR_SKIP_DIST = 2      # reuse OCR result if frame hash this close to previous OCR'd frame
REGIONS = {
    "full": (0, 0, 1, 1), "center": (0.25, 0.25, 0.5, 0.5),
    "top": (0, 0, 1, 0.5), "bottom": (0, 0.5, 1, 0.5),
    "left": (0, 0, 0.5, 1), "right": (0.5, 0, 0.5, 1),
    "tl": (0, 0, 0.5, 0.5), "tr": (0.5, 0, 0.5, 0.5),
    "bl": (0, 0.5, 0.5, 0.5), "br": (0.5, 0.5, 0.5, 0.5),
}


def log(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def _fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def _overlap(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def _assign(speech: list[dict], bounds: list[tuple[float, float]]) -> list[list[str]]:
    """Pure: each transcript line goes to the one video segment it overlaps most."""
    out: list[list[str]] = [[] for _ in bounds]
    for s in speech:
        best, best_ov = None, 0.0
        for i, (t0, t1) in enumerate(bounds):
            ov = min(s["end"], t1) - max(s["start"], t0)
            if ov > best_ov:
                best, best_ov = i, ov
        if best is not None:
            out[best].append(s["text"])
    return out


def analyze(video: Path, out: Path, transcribe: bool = True, model=None, device="auto",
            language=None, seg_threshold: int = 10, max_segments: int = 32) -> dict:
    import time
    timings: dict[str, float] = {}
    clock = [time.perf_counter()]

    def lap(name: str) -> None:
        now = time.perf_counter()
        timings[name] = round(now - clock[0], 1)
        clock[0] = now
        log(f"  {name}: {timings[name]}s")

    info = frames.probe(video)
    out.mkdir(parents=True, exist_ok=True)
    log("Scanning at 10 fps...")
    scan = frames.scan(video, out / "scan")
    step = 1 / frames.SCAN_FPS
    lap("scan")
    hashes = [segments.dhash(f["path"]) for f in scan]
    colors = [segments.colorsig(f["path"]) for f in scan]
    # budget tied to length: continuous motion (water, foliage) otherwise splits every few frames
    budget = min(max_segments, max(6, math.ceil(info["duration"] * SEGMENTS_PER_SECOND)))
    segs, th = segments.segment(hashes, seg_threshold, budget, colors)
    lap("segment")

    # OCR at 5 fps, skipping near-identical frames
    idx = list(range(0, len(scan), OCR_EVERY))
    skip, last = [], None
    for i in idx:
        s = last is not None and segments.hamming(hashes[i], hashes[last]) <= OCR_SKIP_DIST
        skip.append(s)
        if not s:
            last = i
    raw_cache = out / "ocr_raw.json"
    paths_ = [scan[i]["path"] for i in idx]
    cached = json.loads(raw_cache.read_text(encoding="utf-8")) if raw_cache.exists() else None
    if cached and cached.get("paths") == paths_:
        raw = [[tuple(x) for x in lines] for lines in cached["raw"]]
    else:
        raw = ocr.ocr_frames(paths_, skip)
        raw_cache.write_text(json.dumps({"paths": paths_, "raw": raw}, ensure_ascii=False), encoding="utf-8")
    lap("ocr")
    cleaned = ocr.clean([scan[i]["t"] for i in idx], raw, step * OCR_EVERY, info["duration"])
    text_spans, persistent = cleaned["spans"], cleaned["persistent"]

    transcript = None
    speech = []
    if transcribe and info["has_audio"]:
        transcript = tr.transcribe(video, out, model=model, device=device, language=language)
        speech = json.loads((out / "transcript.json").read_text(encoding="utf-8"))["segments"]
    lap("transcribe")

    bounds = [(scan[a]["t"], round(scan[b]["t"] + step, 2)) for a, b in segs]
    speech_by_seg = _assign(speech, bounds)
    seg_rows = []
    for n, ((a, b), (t0, t1)) in enumerate(zip(segs, bounds), 1):
        rep = scan[(a + b) // 2]
        seg_rows.append({
            "n": n, "start": t0, "end": t1, "rep_t": rep["t"], "rep_frame": rep["path"],
            # text that STARTS in this segment (continuing text was listed where it began)
            "text": [s["text"] for s in text_spans if t0 <= s["start"] < t1],
            "speech": " ".join(speech_by_seg[n - 1]),
        })

    sheet_list = sheets.build(
        [{"path": r["rep_frame"], "label": f"#{r['n']} {r['rep_t']:.1f}s"} for r in seg_rows], out, "sheet")

    vmap = {"video": str(video), **info, "segment_threshold": th, "segments": seg_rows,
            "persistent_text": persistent, "text_spans": text_spans, "transcript": transcript,
            "sheets": sheet_list}
    (out / "video_map.json").write_text(json.dumps(vmap, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "video_map.md").write_text(_render_md(vmap), encoding="utf-8")
    lap("map+sheets")
    return {
        "timings_s": timings,
        "video": str(video), **info, "out_dir": str(out),
        "map": str(out / "video_map.md"), "segment_count": len(seg_rows),
        "text_span_count": len(text_spans), "speech_detected": bool(speech),
        "sheets": sheet_list,
        "est_tokens_default_view": sum(s["tokens"] for s in sheet_list),
    }


def _render_md(m: dict) -> str:
    L = [f"# Video map — {Path(m['video']).name}",
         f"duration {m['duration']:.1f}s · {m['width']}x{m['height']} · {len(m['segments'])} segments · "
         f"audio: {'yes' if m['has_audio'] else 'no'}"
         + (f" · speech lang: {m['transcript']['language']}" if m.get("transcript") else ""),
         "", "Contact sheets: " + ", ".join(f"`{s['path']}` (~{s['tokens']} tok)" for s in m["sheets"]),
         "", "Persistent on-screen text (≥50% of the video, e.g. watermark/show title): "
         + (" | ".join(f"\"{t}\"" for t in m["persistent_text"]) or "none"),
         "", "## Segments", "", "_text = on-screen text that appears in that segment (OCR, may contain misreads)_", ""]
    for r in m["segments"]:
        line = f"- **#{r['n']}** [{_fmt(r['start'])}–{_fmt(r['end'])}]"
        if r["text"]:
            line += " · text: " + " | ".join(f"\"{t}\"" for t in r["text"])
        if r["speech"]:
            line += f" · speech: \"{r['speech']}\""
        L.append(line)
    L += ["", "## On-screen text timeline", ""]
    L += [f"- [{_fmt(s['start'])}–{_fmt(s['end'])}] {s['text']}" for s in m["text_spans"]] or ["- (none)"]
    return "\n".join(L) + "\n"


def zoom_crop(video: Path, out: Path, t: float, region: str = "full", box: str | None = None) -> dict:
    img = frames.grab_native(video, t)
    W, H = img.size
    x, y, w, h = [float(v) for v in box.split(",")] if box else REGIONS[region]
    crop = img.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)))
    crop = frames.fit_budget(crop)
    d = out / "zoom"
    d.mkdir(parents=True, exist_ok=True)
    tag = box.replace(",", "_") if box else region
    p = d / f"z_t{t:07.2f}_{tag}.jpg"
    crop.save(p, quality=90)
    return {"path": str(p), "t": t, "region": tag, "size": crop.size,
            "source_size": [W, H], "tokens": frames.est_tokens(*crop.size)}


def zoom_range(video: Path, out: Path, start: float, end: float) -> dict:
    scan = frames.scan(video, out / "scan")
    sel = [f for f in scan if start <= f["t"] <= end]
    tag = f"range_{start:07.2f}_{end:07.2f}"
    sh = sheets.build([{"path": f["path"], "label": f"{f['t']:.1f}s"} for f in sel], out / "zoom", tag)
    return {"start": start, "end": end, "frames": len(sel), "sheets": sh,
            "tokens": sum(s["tokens"] for s in sh)}


def thorough(video: Path, out: Path, confirm: bool) -> dict:
    vm_path = out / "video_map.json"
    if not vm_path.exists():
        return {"error": "no_map", "message": "run `video` first"}
    vm = json.loads(vm_path.read_text(encoding="utf-8"))
    info = frames.probe(video)
    qw, qh = info["width"] // 2, info["height"] // 2
    per = 4 * frames.est_tokens(qw, qh)
    est = per * len(vm["segments"])
    if not confirm:
        return {"estimate_only": True, "segments": len(vm["segments"]), "tokens_per_segment": per,
                "est_tokens": est, "hint": "re-run with --yes to generate"}
    d = out / "thorough"
    d.mkdir(parents=True, exist_ok=True)
    items = []
    for r in vm["segments"]:
        img = frames.grab_native(video, r["rep_t"])
        W, H = img.size
        for q, (x, y) in {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1)}.items():
            c = frames.fit_budget(img.crop((x * W // 2, y * H // 2, (x + 1) * W // 2, (y + 1) * H // 2)))
            p = d / f"seg{r['n']:02d}_t{r['rep_t']:07.2f}_{q}.jpg"
            c.save(p, quality=90)
            items.append({"segment": r["n"], "quadrant": q, "path": str(p)})
    return {"segments": len(vm["segments"]), "images": items, "est_tokens": est}
