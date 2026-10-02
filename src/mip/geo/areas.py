"""Postcodes and administrative areas inside a market boundary (from OpenStreetMap)."""

from pathlib import Path

import orjson
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import linemerge, polygonize, unary_union

from mip.config import Market
from mip.geo.grid import boundary, overpass


def _relation_polygon(rel: dict):
    outer = [m for m in rel.get("members", []) if m["type"] == "way" and m.get("role") in ("outer", "")]
    lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in outer if len(m.get("geometry", [])) > 1]
    polys = list(polygonize(linemerge(lines))) if lines else []
    return unary_union([Polygon(p.exterior) for p in polys]) if polys else None


def fetch_areas(market: Market, kind: str) -> list[dict]:
    """kind: postcode | district (admin_level 9 Bezirke) | locality (admin_level 10 Ortsteile)."""
    rid = market.geography.osm_relation_id
    filt = {
        "postcode": '["boundary"="postal_code"]',
        "district": '["boundary"="administrative"]["admin_level"="9"]',
        "locality": '["boundary"="administrative"]["admin_level"="10"]',
    }[kind]
    q = f"[out:json][timeout:300];rel({rid});map_to_area->.a;rel{filt}(area.a);out geom;"
    city = boundary(market.boundary_path())
    out = []
    for rel in overpass(q)["elements"]:
        geom = _relation_polygon(rel)
        if geom is None or geom.is_empty:
            continue
        inter = geom.intersection(city)
        if inter.is_empty or inter.area / geom.area < 0.05:
            continue
        tags = rel.get("tags", {})
        c = geom.representative_point()
        out.append({
            "kind": kind,
            "osm_id": rel["id"],
            "code": tags.get("postal_code") or tags.get("de:amtlicher_gemeindeschluessel") or str(rel["id"]),
            "name": tags.get("name") or tags.get("note"),
            "lat": round(c.y, 6),
            "lon": round(c.x, 6),
            "share_in_market": round(inter.area / geom.area, 4),
            "tags": tags,
            "geometry": mapping(geom),
        })
    return out


def areas(market: Market, kind: str) -> list[dict]:
    path = Path(market.boundary_path()).with_name(f"{market.id}_{kind}.json")
    if not path.exists():
        path.write_bytes(orjson.dumps(fetch_areas(market, kind)))
    return orjson.loads(path.read_bytes())
