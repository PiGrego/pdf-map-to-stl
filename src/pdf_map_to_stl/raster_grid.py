from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class RasterGrid:
    dpi: int
    zoom: float
    ix0: int
    iy0: int
    ix1: int
    iy1: int

    @property
    def width(self): return self.ix1 - self.ix0
    @property
    def height(self): return self.iy1 - self.iy0

    def pdf_to_local(self, x, y):
        return x * self.zoom - self.ix0, y * self.zoom - self.iy0

    def local_to_pdf(self, x, y):
        return (x + self.ix0) / self.zoom, (y + self.iy0) / self.zoom


def grid_from_bounds(bounds, dpi, image_width=None, image_height=None):
    x0, y0, x1, y1 = bounds
    z = dpi / 72.0
    ix0 = max(0, math.floor(x0 * z))
    iy0 = max(0, math.floor(y0 * z))
    ix1 = math.ceil(x1 * z)
    iy1 = math.ceil(y1 * z)
    if image_width is not None: ix1 = min(image_width, ix1)
    if image_height is not None: iy1 = min(image_height, iy1)
    return RasterGrid(dpi, z, ix0, iy0, ix1, iy1)
