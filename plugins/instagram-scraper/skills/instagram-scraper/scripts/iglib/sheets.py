"""Contact sheets: grids of labeled thumbnails, sized to fit one image token budget."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .frames import MAX_PATCHES, est_tokens, fit_budget

COLS = 4
ROWS = 4
GAP = 4


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build(items: list[dict], out_dir: Path, prefix: str = "sheet") -> list[dict]:
    """items: [{'path', 'label'}]. Writes <prefix>_01.jpg ... (16 tiles each).
    Returns [{'path', 'tokens', 'labels'}]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{prefix}_*.jpg"):
        old.unlink()
    if not items:
        return []
    w0, h0 = Image.open(items[0]["path"]).size
    # tile size so a full 4x4 grid lands near the per-image budget
    portrait = h0 >= w0
    tw = 192 if portrait else 340
    th = round(tw * h0 / w0)
    font = _font(max(12, tw // 11))
    per = COLS * ROWS
    sheets = []
    for n, start in enumerate(range(0, len(items), per), 1):
        chunk = items[start:start + per]
        rows = (len(chunk) + COLS - 1) // COLS
        cols = min(COLS, len(chunk))
        sheet = Image.new("RGB", (cols * tw + (cols - 1) * GAP, rows * th + (rows - 1) * GAP), "white")
        draw = ImageDraw.Draw(sheet)
        for i, it in enumerate(chunk):
            x, y = (i % COLS) * (tw + GAP), (i // COLS) * (th + GAP)
            sheet.paste(Image.open(it["path"]).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
            bbox = draw.textbbox((x + 3, y + 3), it["label"], font=font)
            draw.rectangle([bbox[0] - 3, bbox[1] - 2, bbox[2] + 3, bbox[3] + 2], fill="black")
            draw.text((x + 3, y + 3), it["label"], fill="yellow", font=font)
        sheet = fit_budget(sheet, MAX_PATCHES)
        p = out_dir / f"{prefix}_{n:02d}.jpg"
        sheet.save(p, quality=85)
        sheets.append({"path": str(p), "tokens": est_tokens(*sheet.size),
                       "labels": [it["label"] for it in chunk]})
    return sheets
