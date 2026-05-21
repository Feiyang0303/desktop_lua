"""Convert raw chroma-keyed sprites into trimmed transparent PNGs.

By default, reads `assets/*_raw.png`, removes the green background, despills
the green fringe, crops tight to the sprite, and writes `assets/<name>.png`.
Pass one or more directories as arguments to process those instead, for
example: `python tools/process_sprites.py assets/chibi assets/realistic`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSETS_DIR = REPO_ROOT / "assets"


def remove_chroma_key(
    img: Image.Image,
    *,
    key_hue_lo: int = 70,
    key_hue_hi: int = 170,
    transparent_threshold: float = 0.10,
    opaque_threshold: float = 0.35,
    despill: bool = True,
) -> Image.Image:
    """Convert green chroma-key pixels to transparent.

    Uses a "greenness" metric (green minus the max of red/blue, normalized)
    to build a soft alpha matte. Pixels well into the key get alpha=0, pixels
    well outside stay alpha=255, and a smooth ramp connects the two so edges
    stay soft. Optional despill subtracts excess green from semi-transparent
    pixels to kill the green fringe.
    """
    rgba = np.asarray(img.convert("RGBA")).astype(np.float32)
    r, g, b, a = rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3]

    greenness = (g - np.maximum(r, b)) / 255.0
    greenness = np.clip(greenness, 0.0, 1.0)

    alpha = np.where(
        greenness <= transparent_threshold,
        1.0,
        np.where(
            greenness >= opaque_threshold,
            0.0,
            1.0 - (greenness - transparent_threshold)
            / (opaque_threshold - transparent_threshold),
        ),
    )

    if despill:
        spill = np.clip(g - np.maximum(r, b), 0.0, 255.0)
        spill_strength = (1.0 - alpha) * 0.0 + alpha * (greenness > 0.04)
        g = g - spill * spill_strength
        g = np.clip(g, 0.0, 255.0)

    out_a = (a / 255.0) * alpha * 255.0
    out = np.stack([r, g, b, out_a], axis=-1).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


def crop_to_alpha(img: Image.Image, padding: int = 8) -> Image.Image:
    arr = np.asarray(img)
    alpha = arr[..., 3]
    ys, xs = np.where(alpha > 8)
    if len(xs) == 0:
        return img
    x0, x1 = xs.min(), xs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(arr.shape[1], x1 + padding)
    y1 = min(arr.shape[0], y1 + padding)
    return img.crop((x0, y0, x1, y1))


def process_one(raw_path: Path) -> Path:
    out_name = raw_path.name.replace("_raw", "")
    out_path = raw_path.with_name(out_name)
    img = Image.open(raw_path)
    img = remove_chroma_key(img)
    img = crop_to_alpha(img, padding=10)
    max_edge = 320
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize(
            (int(w * scale), int(h * scale)), Image.Resampling.LANCZOS
        )
    img.save(out_path, optimize=True)
    return out_path


def process_dir(directory: Path) -> None:
    raw_files = sorted(directory.glob("*_raw.png"))
    if not raw_files:
        print(f"  (no *_raw.png in {directory})")
        return
    print(f"[{directory.relative_to(REPO_ROOT)}]")
    for raw in raw_files:
        out = process_one(raw)
        print(f"  {raw.name} -> {out.name}  ({Image.open(out).size})")


def main() -> None:
    if len(sys.argv) > 1:
        targets = [Path(p) for p in sys.argv[1:]]
    else:
        targets = [DEFAULT_ASSETS_DIR]
    for target in targets:
        target = target if target.is_absolute() else REPO_ROOT / target
        process_dir(target)


if __name__ == "__main__":
    main()
