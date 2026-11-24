"""Position points: where the map is on Earth, for the reader's navigation app.

One or two points of the map can be given with their latitude and longitude. On the
plate each point is marked by tall pins, higher than anything else so they are easy to
find: point 1 is one pin, point 2 two pins side by side. Their coordinates are written
in Braille in the bottom margin, in decimal degrees ("1: 44.51234, 11.34567"), the form
navigation apps accept (WGS 84, as GPS and web maps use).

Coordinates can be typed in any common form: ``44.51234``, ``44.51234 N``,
``N 44.51234``, ``-11.3``, ``44°30'44.4"N``, ``44 30 44.4 N``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

EARTH_RADIUS_M = 6_371_000.0
MAX_POINTS = 2


@dataclass(frozen=True)
class GeoPoint:
    x_mm: float  # on the PDF page, from its top-left corner (like --crop)
    y_mm: float
    lat: float  # decimal degrees, north positive
    lon: float  # decimal degrees, east positive

    def text(self, decimals: int = 5) -> str:
        return f"{self.lat:.{decimals}f}, {self.lon:.{decimals}f}"


def parse_coordinate(text: str, axis: str) -> float:
    """One latitude (``axis`` "lat") or longitude ("lon") in decimal degrees."""
    t = text.strip().upper().replace(",", ".")
    hemis = re.findall(r"[NSEW]", t)
    numbers = re.findall(r"-?\d+(?:\.\d+)?", t)
    if not numbers or len(numbers) > 3 or len(hemis) > 1:
        raise ValueError(f"cannot read the coordinate {text!r}")
    d, *rest = (float(n) for n in numbers)
    value = abs(d) + sum(v / 60**i for i, v in enumerate(rest, 1))
    if d < 0 or (hemis and hemis[0] in "SW"):
        value = -value
    if hemis and (hemis[0] in "NS") != (axis == "lat"):
        raise ValueError(f"{text!r} is a {'latitude' if hemis[0] in 'NS' else 'longitude'}, expected a "
                         f"{'latitude' if axis == 'lat' else 'longitude'} here (latitude first)")
    limit = 90 if axis == "lat" else 180
    if abs(value) > limit:
        raise ValueError(f"{text!r}: a {'latitude' if axis == 'lat' else 'longitude'} is at most {limit} degrees")
    return value


def parse_geo(text: str) -> GeoPoint:
    """``X,Y,LAT,LON``: a point on the PDF page (mm from its top-left corner) and its
    latitude and longitude."""
    parts = [p for p in re.split(r"[,;]", text) if p.strip()]
    if len(parts) != 4:
        raise ValueError(f"a position point is X,Y,LATITUDE,LONGITUDE, got {text!r}")
    x, y = float(parts[0]), float(parts[1])
    return GeoPoint(x, y, parse_coordinate(parts[2], "lat"), parse_coordinate(parts[3], "lon"))


def pins(index: int, x: float, y: float, diameter_mm: float) -> BaseGeometry:
    """Point ``index`` (1 or 2) as that many round pins, centred on (x, y)."""
    r, step = diameter_mm / 2, diameter_mm * 1.5
    offsets = [(i - (index - 1) / 2) * step for i in range(index)]
    return unary_union([Point(x + dx, y).buffer(r, 16) for dx in offsets])


def ground_distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance between two points (haversine)."""
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def check_points(points: list[GeoPoint], map_scale: float) -> list[str]:
    """Sentences for the description; with two points and a known map scale, a check that
    the coordinates agree with the map (a typing mistake would show here)."""
    if len(points) != 2 or not map_scale:
        return []
    a, b = points
    on_map_m = math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm) / 1000 * map_scale
    ground = ground_distance_m(a, b)
    if ground <= 0:
        return ["The two points have the same coordinates: check them."]
    diff = 100 * abs(on_map_m - ground) / ground
    line = (f"Check: the two points are {ground:.0f} m apart by their coordinates and {on_map_m:.0f} m on the map "
            f"at 1:{map_scale:g} ({diff:.0f} % difference).")
    if diff > 5:
        line += " That is more than 5 %: check the coordinates and the points on the map."
    return [line]
