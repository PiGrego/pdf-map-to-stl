from shapely.geometry import Polygon, MultiPolygon

def enclosed_holes(geom, min_area=0.5, max_area=2500.0):
    """Return true interior rings only. Open background regions are never promoted."""
    if geom is None or geom.is_empty:
        return []
    polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms) if isinstance(geom, MultiPolygon) else []
    out=[]
    for p in polys:
        for ring in p.interiors:
            h=Polygon(ring)
            if min_area <= h.area <= max_area:
                out.append(h)
    return sorted(out,key=lambda g:g.area,reverse=True)

def safe_fill_holes(geom, max_area=0.0):
    if max_area <= 0: return geom
    holes=enclosed_holes(geom,0.0,max_area)
    out=geom
    for h in holes: out=out.union(h)
    return out
