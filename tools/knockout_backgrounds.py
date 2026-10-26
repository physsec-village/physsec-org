# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow", "numpy", "scipy"]
# ///
"""Make the white studio background of product photos transparent.

Usage: uv run tools/knockout_backgrounds.py IMAGE [IMAGE ...]

Each image is rewritten in place as a lossless RGBA WebP. Pixels are treated
as background when they are near white and either touch the image border or
form an enclosed, almost pure-white region such as a key bow's hole. Soft
shadows fade out instead of being cut, so edges keep their anti-aliasing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

FADE_START = 18  # distance from pure white below which a pixel is fully clear
FADE_END = 70  # distance above which a pixel is fully opaque
HOLE_MAX_MEAN = 12  # enclosed regions this close to white are holes, not product


def knock_out(path: Path) -> float:
    """Rewrite one image and return the fraction of pixels made transparent."""
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    distance = 255 - rgb.min(axis=2)
    labels, count = ndimage.label(distance < FADE_END)
    edges = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    background = set(np.unique(edges)) - {0}
    means = ndimage.mean(distance, labels, index=np.arange(1, count + 1))
    background |= {i + 1 for i, mean in enumerate(means) if mean < HOLE_MAX_MEAN}
    mask = np.isin(labels, list(background))
    alpha = np.full(distance.shape, 255.0, dtype=np.float32)
    faded = np.clip((distance - FADE_START) / (FADE_END - FADE_START), 0, 1) * 255
    alpha[mask] = faded[mask]
    rgba = np.dstack([rgb.astype(np.uint8), alpha.astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(path, "WEBP", lossless=True, quality=100)
    return float(mask.mean())


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    for name in argv:
        path = Path(name)
        print(f"{path.name}: {knock_out(path):.0%} background")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
