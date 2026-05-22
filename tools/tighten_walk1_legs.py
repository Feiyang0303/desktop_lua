"""Compress the over-stretched legs in walk1 frames.

The AI-generated walk1 poses tend to look mid-lunge instead of mid-step: the
front-right and back-left paws extend way past the body silhouette. This
script applies a continuous horizontal squish that ramps from 1.0x near the
top of the frame down to a smaller scale at the bottom, which pulls the
extreme paws back toward the center without distorting the head much.

Each known style has its own preset because chibi walk1 is far more splayed
than realistic walk1 and needs a stronger squeeze that reaches higher up
the body.

Usage:
    python tools/tighten_walk1_legs.py                  # all known presets
    python tools/tighten_walk1_legs.py realistic        # just one style
    python tools/tighten_walk1_legs.py path/to/img.png  # custom file, default params
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Preset:
    path: Path
    top_keep_frac: float
    bottom_scale: float


# Tuned by eye. `top_keep_frac` is where the squeeze ramp begins (lower =
# more of the dog gets squished). `bottom_scale` is the horizontal scale at
# the very bottom row (smaller = more compression).
PRESETS: dict[str, Preset] = {
    "realistic": Preset(
        path=REPO_ROOT / "assets" / "realistic" / "luca_walk1.png",
        top_keep_frac=0.55,
        bottom_scale=0.78,
    ),
    "chibi": Preset(
        # Chibi walk1 has all four legs splayed and a stretched body, so the
        # ramp starts higher (lower top_keep_frac) and goes further (lower
        # bottom_scale) to noticeably round Luca back up.
        path=REPO_ROOT / "assets" / "chibi" / "luca_walk1.png",
        top_keep_frac=0.30,
        bottom_scale=0.70,
    ),
}


def tighten_legs(
    img: Image.Image,
    *,
    top_keep_frac: float = 0.55,
    bottom_scale: float = 0.78,
    crop: bool = True,
    pad: int = 8,
) -> Image.Image:
    """Return a copy with the bottom of the image horizontally compressed."""
    src = np.asarray(img.convert("RGBA"))
    h, w, _ = src.shape

    out = np.zeros_like(src)
    cx = (w - 1) / 2.0
    top_keep = int(h * top_keep_frac)

    scales = np.ones(h, dtype=np.float32)
    if h > top_keep:
        ramp = np.linspace(0.0, 1.0, h - top_keep, dtype=np.float32)
        # Smoothstep for a gentler shoulder where the body meets the legs.
        ramp = ramp * ramp * (3.0 - 2.0 * ramp)
        scales[top_keep:] = 1.0 + (bottom_scale - 1.0) * ramp

    xs = np.arange(w, dtype=np.float32)
    for y in range(h):
        s = scales[y]
        if s >= 0.999:
            out[y] = src[y]
            continue
        # Inverse map: an output pixel at column `x` samples the input at
        # `cx + (x - cx) / s`. With s < 1 this reaches further from center,
        # pulling outer leg pixels toward the middle of the frame.
        src_xs = cx + (xs - cx) / s
        x0 = np.floor(src_xs).astype(np.int32)
        x1 = x0 + 1
        wx = src_xs - x0

        valid = (x0 >= 0) & (x1 < w)
        x0c = np.clip(x0, 0, w - 1)
        x1c = np.clip(x1, 0, w - 1)

        row = src[y].astype(np.float32)
        left = row[x0c]
        right = row[x1c]
        blended = left * (1.0 - wx[:, None]) + right * wx[:, None]
        blended[~valid] = 0.0
        out[y] = blended.clip(0, 255).astype(np.uint8)

    result = Image.fromarray(out, mode="RGBA")
    if crop:
        result = _crop_to_alpha(result, padding=pad)
    return result


def _crop_to_alpha(img: Image.Image, padding: int = 8) -> Image.Image:
    arr = np.asarray(img)
    alpha = arr[..., 3]
    ys, xs = np.where(alpha > 8)
    if len(xs) == 0:
        return img
    x0 = max(0, int(xs.min()) - padding)
    y0 = max(0, int(ys.min()) - padding)
    x1 = min(arr.shape[1], int(xs.max()) + 1 + padding)
    y1 = min(arr.shape[0], int(ys.max()) + 1 + padding)
    return img.crop((x0, y0, x1, y1))


def _apply(preset: Preset, label: str) -> None:
    if not preset.path.exists():
        print(f"  skip {label}: {preset.path} not found")
        return
    img = Image.open(preset.path)
    fixed = tighten_legs(
        img,
        top_keep_frac=preset.top_keep_frac,
        bottom_scale=preset.bottom_scale,
    )
    fixed.save(preset.path, optimize=True)
    rel = preset.path.relative_to(REPO_ROOT)
    print(
        f"  {label}: {rel} -> {fixed.size} "
        f"(top_keep={preset.top_keep_frac}, bottom_scale={preset.bottom_scale})"
    )


def main() -> None:
    args = sys.argv[1:]
    if not args:
        targets = list(PRESETS.keys())
    else:
        targets = args

    print("Tightening walk1 legs:")
    for arg in targets:
        if arg in PRESETS:
            _apply(PRESETS[arg], arg)
            continue
        # Treat as a path; use realistic defaults.
        path = Path(arg)
        if not path.is_absolute():
            path = REPO_ROOT / path
        preset = Preset(path=path, top_keep_frac=0.55, bottom_scale=0.78)
        _apply(preset, path.name)


if __name__ == "__main__":
    main()
