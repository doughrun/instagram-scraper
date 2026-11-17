"""Local speech-to-text with faster-whisper. GPU if the optional GPU pack is installed, else CPU."""
from __future__ import annotations

import ctypes
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

GPU_MODEL = "large-v3-turbo"
CPU_MODEL = "small"
GPU_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def has_nvidia_gpu() -> bool:
    if sys.platform == "darwin" or not shutil.which("nvidia-smi"):
        return False
    r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True)
    return r.returncode == 0 and "GPU" in r.stdout


def gpu_pack_installed() -> bool:
    return (paths.gpu_pack_dir() / "nvidia").is_dir()


def install_gpu_pack() -> dict:
    """Install CUDA runtime libs (~1 GB) into the per-user data dir with uv."""
    if not has_nvidia_gpu():
        return {"ok": False, "error": "no_nvidia_gpu"}
    target = paths.gpu_pack_dir()
    uv = shutil.which("uv")
    if not uv:
        return {"ok": False, "error": "uv_not_found"}
    log(f"Installing GPU pack into {target} (about 1 GB, one time)...")
    r = subprocess.run([uv, "pip", "install", "--quiet", "--target", str(target),
                        "--python", sys.executable, *GPU_PACKAGES])
    return {"ok": r.returncode == 0 and gpu_pack_installed(), "path": str(target)}


def _activate_gpu_pack() -> bool:
    """Make the GPU pack's CUDA libs loadable by ctranslate2 in this process."""
    if not gpu_pack_installed():
        return False
    root = paths.gpu_pack_dir() / "nvidia"
    if sys.platform == "win32":
        for d in glob.glob(str(root / "*" / "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    else:  # Linux: preload so dlopen by soname succeeds
        for so in sorted(glob.glob(str(root / "*" / "lib" / "*.so*"))):
            try:
                ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass
    return True


def load_audio(video: Path):
    """Decode to 16 kHz mono float32 with ffmpeg (avoids faster-whisper's PyAV path,
    which breaks on newer PyAV releases)."""
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _run(audio, model_name: str, device: str, compute: str, language: str | None):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute,
                         download_root=str(paths.models_dir()))
    segments, info = model.transcribe(audio, language=language, vad_filter=True, beam_size=5)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments]  # generator: decoding happens here
    return segs, info


def transcribe(video: Path, out_dir: Path, model: str | None = None, device: str = "auto",
               language: str | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    want_gpu = device in ("auto", "cuda") and has_nvidia_gpu() and _activate_gpu_pack()
    if device == "cuda" and not want_gpu:
        log("CUDA requested but GPU pack not installed; run `ig.py gpu-setup`. Using CPU.")
    attempts = []
    if want_gpu:
        attempts.append((model or GPU_MODEL, "cuda", "float16"))
    attempts.append((model or CPU_MODEL, "cpu", "int8"))

    audio = load_audio(video)
    last_err = None
    for name, dev, compute in attempts:
        try:
            log(f"Transcribing with {name} on {dev}...")
            segs, info = _run(audio, name, dev, compute, language)
            break
        except Exception as e:  # noqa: BLE001 - fall back to CPU on any CUDA failure
            last_err = e
            log(f"{dev} transcription failed ({type(e).__name__}: {e}); falling back.")
    else:
        raise RuntimeError(f"transcription failed: {last_err}")

    text = " ".join(s["text"] for s in segs).strip()
    result = {
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 2),
        "speech_detected": bool(segs),
        "model": name,
        "device": dev,
        "segments": segs,
    }
    (out_dir / "transcript.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    (out_dir / "transcript.txt").write_text(
        "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segs) or "(no speech detected)",
        encoding="utf-8")
    return {**{k: v for k, v in result.items() if k != "segments"},
            "segment_count": len(segs), "text_preview": text[:300],
            "transcript_json": str(out_dir / "transcript.json"),
            "transcript_txt": str(out_dir / "transcript.txt")}
