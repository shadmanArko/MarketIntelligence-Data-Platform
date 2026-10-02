"""City boundary and H3 grid: the coordinate points coordinate-based sources are queried at."""

import json
from functools import lru_cache
from pathlib import Path

import h3
import orjson
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from mip.config import Market

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
USER_AGENT = "mip-market-intel/0.1 (data platform; contact via repo owner)"


def overpass(query: str, timeout: int = 600) -> dict:
    import httpx

    last = None
    for url in OVERPASS_MIRRORS:
        try:
            r = httpx.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"{url}: HTTP {r.status_code} {r.text[:200]}")
        except httpx.HTTPError as e:
            last = e
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def fetch_boundary(osm_relation_id: int, out: Path) -> Path:
    """Download an administrative boundary from OpenStreetMap as GeoJSON."""
    q = f"[out:json][timeout:180];relation({osm_relation_id});out geom;"
    rel = overpass(q)["elements"][0]
    from shapely.geometry import LineString, Polygon
    from shapely.ops import linemerge, polygonize

    outer = [m for m in rel["members"] if m["type"] == "way" and m.get("role") == "outer"]
    lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in outer]
    polys = list(polygonize(linemerge(lines)))
    geom = unary_union([Polygon(p.exterior) for p in polys])
    feature = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"osm_relation_id": osm_relation_id,
                                                        "name": rel.get("tags", {}).get("name")},
                      "geometry": mapping(geom)}],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feature))
    return out


@lru_cache
def boundary(path: Path):
    data = orjson.loads(path.read_bytes())
    feats = data["features"] if data.get("type") == "FeatureCollection" else [data]
    return unary_union([shape(f["geometry"]) for f in feats])


def h3_cells(market: Market, res: int | None = None, buffer_rings: int = 0) -> list[str]:
    geom = boundary(market.boundary_path())
    res = res or market.geography.h3_resolution
    cells = set(h3.geo_to_cells(geom.__geo_interface__, res))
    if buffer_rings:
        cells = {n for c in cells for n in h3.grid_disk(c, buffer_rings)}
    return sorted(cells)


def cell_center(cell: str) -> tuple[float, float]:
    lat, lon = h3.cell_to_latlng(cell)
    return round(lat, 6), round(lon, 6)


def bbox(market: Market) -> tuple[float, float, float, float]:
    if market.geography.bbox:
        return market.geography.bbox
    minx, miny, maxx, maxy = boundary(market.boundary_path()).bounds
    return minx, miny, maxx, maxy


def contains(market: Market, lat: float, lon: float) -> bool:
    from shapely.geometry import Point

    return boundary(market.boundary_path()).contains(Point(lon, lat))
