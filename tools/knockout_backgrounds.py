# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow", "numpy", "scipy"]
# ///
"""Make the white studio background of product photos transparent.

Usage: uv run tools/knockout_backgrounds.py [--bridge N] IMAGE [IMAGE ...]

Each image is rewritten in place as a lossless RGBA WebP. Pixels count as
background when they are almost pure white and either touch the image border
or form an enclosed, almost pure-white region such as a key bow's hole. Only a
thin band along the product's outline is faded, so glare on bright metal stays
opaque instead of turning translucent.

--bridge N closes horizontal gaps up to N pixels wide in the product. Use it
for thin shiny tools whose glare is indistinguishable from the backdrop and
would otherwise cut the tool in two.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

BACKGROUND_MAX = 10  # distance from pure white below which a pixel may be backdrop
FADE_END = 70  # outline pixels this far from white are fully opaque
EDGE_BAND = 2  # how many pixels into the product the outline fade reaches
HOLE_MAX_MEAN = 6  # enclosed regions this close to white are holes, not product


def knock_out(path: Path, bridge: int = 0) -> float:
    """Rewrite one image and return the fraction of pixels made transparent."""
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    distance = 255 - rgb.min(axis=2)
    labels, count = ndimage.label(distance < BACKGROUND_MAX)
    edges = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    background = set(np.unique(edges)) - {0}
    means = ndimage.mean(distance, labels, index=np.arange(1, count + 1))
    background |= {i + 1 for i, mean in enumerate(means) if mean < HOLE_MAX_MEAN}
    mask = np.isin(labels, list(background))
    if bridge:
        product = ~mask
        structure = np.ones((1, bridge), dtype=bool)
        closed = ndimage.binary_closing(product, structure=structure)
        mask &= ~closed
    inside = ndimage.distance_transform_edt(~mask)
    band = (inside > 0) & (inside <= EDGE_BAND)
    alpha = np.full(distance.shape, 255.0, dtype=np.float32)
    alpha[mask] = 0
    faded = np.clip(distance / FADE_END, 0, 1) * 255
    alpha[band] = np.maximum(faded[band], alpha[band] * (inside[band] / (EDGE_BAND + 1)))
    rgba = np.dstack([rgb.astype(np.uint8), alpha.astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(path, "WEBP", lossless=True, quality=100)
    return float(mask.mean())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bridge", type=int, default=0, metavar="N", help="close horizontal gaps up to N px")
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args(argv)
    for path in args.images:
        print(f"{path.name}: {knock_out(path, args.bridge):.0%} background")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
