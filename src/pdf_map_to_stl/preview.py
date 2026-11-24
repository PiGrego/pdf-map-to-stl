"""Images of the tactile model: a shaded relief (quick look without a slicer) and the
tactile check overlay. Both are for sighted helpers; description.txt says the same in
text."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry.base import BaseGeometry

from .model3d import TactileModel
from .validate import rasterize

BACKGROUND = (255, 255, 255)
PLATE = (205, 205, 198)
TEXTURE_SHADE = 0.8  # textures drawn a little darker than their class
BRAILLE = (40, 40, 40)

# Okabe-Ito colours: distinguishable with colour-vision deficiencies.
CHECK_COLOURS = {
    "thin_parts": ((213, 94, 0), "thin part"),
    "narrow_gaps": ((230, 159, 0), "narrow gap"),
    "low_steps": ((0, 114, 178), "areas that feel the same"),
    "hidden_objects": ((204, 121, 167), "object barely raised"),
    "small_areas": ((86, 180, 233), "small isolated area"),
}


def _mask(g: BaseGeometry, size: tuple[int, int], px_per_mm: float) -> np.ndarray:
    # Model y points up; rasterize with y down, then flip rows.
    return rasterize(g, size, px_per_mm)[::-1]


def relief_image(t: TactileModel, colours: dict, px_per_mm: float = 8.0) -> Image.Image:
    w, h = round(t.width_mm * px_per_mm), round(t.height_mm * px_per_mm)
    plate = _mask(t.plate, (w, h), px_per_mm)
    z = np.zeros((h, w), np.float32)
    rgb = np.full((h, w, 3), BACKGROUND, np.float32)
    rgb[plate] = PLATE
    for layer in sorted(t.layers, key=lambda lyr: lyr.height_mm):
        mask = _mask(layer.geom, (w, h), px_per_mm) & plate
        top = layer.height_mm
        sel = mask & (top >= z) if top >= 0 else mask
        z[sel] = top
        if layer.role in ("braille", "north", "frame", "edge", "pin"):
            rgb[sel] = BRAILLE
        elif layer.role == "texture":
            rgb[sel] = np.array(colours.get(layer.on, (255, 255, 255))) * TEXTURE_SHADE
        else:
            rgb[sel] = colours.get(layer.cls, (255, 255, 255))
    # Lambertian hillshade, light from the north-west.
    gy, gx = np.gradient(z * px_per_mm)
    nx, ny, nz = -gx, gy, np.ones_like(z)
    n = np.sqrt(nx**2 + ny**2 + nz**2)
    light = np.array([-1.0, 1.0, 1.2])
    light /= np.linalg.norm(light)
    shade = np.clip((nx * light[0] + ny * light[1] + nz * light[2]) / n, 0, 1)
    out = rgb * np.where(plate, 0.45 + 0.55 * shade, 1.0)[..., None]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def check_image(t: TactileModel, problems: dict[str, BaseGeometry], px_per_mm: float = 8.0) -> Image.Image:
    """Grey relief with problem spots in colour, and a key at the bottom."""
    grey = relief_image(t, {}, px_per_mm).convert("L").convert("RGB")
    arr = (np.asarray(grey, np.float32) * 0.6 + 100).clip(0, 255)
    size = (grey.width, grey.height)
    for key, (rgb, _) in CHECK_COLOURS.items():
        g = problems.get(key)
        if g is not None and not g.is_empty:
            arr[_mask(g.buffer(0.3), size, px_per_mm)] = rgb
    img = Image.fromarray(arr.astype(np.uint8))
    key_h = 22 * len(CHECK_COLOURS) + 10
    out = Image.new("RGB", (img.width, img.height + key_h), BACKGROUND)
    out.paste(img, (0, 0))
    dw = ImageDraw.Draw(out)
    for i, (rgb, label) in enumerate(CHECK_COLOURS.values()):
        y = img.height + 8 + 22 * i
        dw.rectangle([10, y, 26, y + 14], fill=rgb)
        dw.text((34, y), label, fill=(0, 0, 0))
    return out
