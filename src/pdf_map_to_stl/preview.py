"""Shaded relief preview of the tactile model (a quick look without a slicer)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .model3d import TactileModel
from .validate import rasterize


def relief_image(t: TactileModel, colours: dict, px_per_mm: float = 8.0) -> Image.Image:
    w, h = round(t.width_mm * px_per_mm), round(t.height_mm * px_per_mm)
    z = np.zeros((h, w), np.float32)
    rgb = np.full((h, w, 3), 242, np.float32)
    for layer in sorted(t.layers, key=lambda lyr: lyr.height_mm):
        # Model y points up; rasterize with y down, then flip rows.
        mask = rasterize(layer.geom, (w, h), px_per_mm)[::-1]
        top = layer.height_mm
        sel = mask & (top >= z) if top >= 0 else mask
        z[sel] = top
        rgb[sel] = colours.get(layer.cls, (255, 255, 255))
    # Lambertian hillshade, light from the north-west.
    gy, gx = np.gradient(z * px_per_mm)
    nx, ny, nz = -gx, gy, np.ones_like(z)
    n = np.sqrt(nx**2 + ny**2 + nz**2)
    light = np.array([-1.0, 1.0, 1.2])
    light /= np.linalg.norm(light)
    shade = np.clip((nx * light[0] + ny * light[1] + nz * light[2]) / n, 0, 1)
    out = rgb * (0.45 + 0.55 * shade[..., None])
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))
