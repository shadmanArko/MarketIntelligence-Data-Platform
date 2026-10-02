"""OpenStreetMap via the Geofabrik Berlin extract: every named POI (nodes, ways, areas) with all its tags."""

from datetime import UTC, datetime

import httpx
import orjson
import osmium
from shapely import wkb as swkb

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, loader, register, sha256_file
from mip.db import connect

GEOFABRIK = "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf"
POI_KEYS = ("amenity", "shop", "cuisine", "tourism", "leisure", "office", "craft", "healthcare", "club",
            "social_facility", "place_of_worship", "religion", "brand", "brand:wikidata")

DDL = """
CREATE TABLE IF NOT EXISTS {t} (
  osm_type   text   NOT NULL,
  osm_id     bigint NOT NULL,
  version    integer,
  timestamp  timestamptz,
  name       text,
  lat        double precision,
  lon        double precision,
  geometry_wkt text,
  tags       jsonb  NOT NULL,
  PRIMARY KEY (osm_type, osm_id)
)"""


class _Handler(osmium.SimpleHandler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink
        self.wkb = osmium.geom.WKBFactory()

    def _keep(self, tags) -> bool:
        return any(k in tags for k in POI_KEYS)

    def _emit(self, otype, obj, lat, lon, wkt):
        tags = {t.k: t.v for t in obj.tags}
        ts = obj.timestamp.replace(tzinfo=UTC) if obj.timestamp else None
        self.sink.append((otype, obj.id, obj.version, ts, tags.get("name"), lat, lon, wkt,
                          orjson.dumps(tags).decode()))

    def node(self, n):
        if self._keep(n.tags) and n.location.valid():
            self._emit("node", n, n.location.lat, n.location.lon, None)

    def area(self, a):
        if not self._keep(a.tags):
            return
        try:
            g = swkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        c = g.representative_point()
        otype = "way" if a.from_way() else "relation"
        self._emit(otype, a, c.y, c.x, g.wkt if g.area < 1e-4 else None)  # keep shapes for buildings-size areas
        # areas carry the original id doubled (+1 for relations) in osmium; normalise
        last = self.sink[-1]
        self.sink[-1] = (last[0], a.orig_id(), *last[2:])

    def way(self, w):
        # open ways (e.g. a food street drawn as a line) that are not areas
        if not self._keep(w.tags) or w.is_closed():
            return
        try:
            g = swkb.loads(self.wkb.create_linestring(w), hex=True)
        except Exception:
            return
        c = g.interpolate(0.5, normalized=True)
        self._emit("way", w, c.y, c.x, g.wkt)


@loader("osm")
def load(market: Market, version: str | None = None) -> None:
    d = bulk_dir("osm")
    head = httpx.head(GEOFABRIK, follow_redirects=True, timeout=60)
    last_mod = head.headers.get("last-modified")
    rel_date = datetime.strptime(last_mod, "%a, %d %b %Y %H:%M:%S %Z").date() if last_mod else datetime.now().date()
    ver = version or rel_date.isoformat()
    name = "osm_berlin_pois"
    if already_loaded(name, ver):
        console.print(f"osm {ver} already loaded")
        return
    pbf = d / f"berlin-{ver}.osm.pbf"
    if not pbf.exists():
        console.print(f"downloading {GEOFABRIK} ...")
        with httpx.stream("GET", GEOFABRIK, follow_redirects=True, timeout=600) as r, pbf.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    rows: list[tuple] = []
    _Handler(rows).apply_file(str(pbf), locations=True, idx="flex_mem")
    t = f"raw.ds_{name}_{ver.replace('-', '_')}"
    console.print(f"{len(rows):,} POIs parsed; writing {t}")
    with connect() as c:
        c.execute(DDL.format(t=t))
        with c.cursor().copy(f"COPY {t} (osm_type, osm_id, version, timestamp, name, lat, lon, geometry_wkt, tags)"
                            " FROM STDIN") as cp:
            seen = set()
            for row in rows:
                if (row[0], row[1]) in seen:
                    continue
                seen.add((row[0], row[1]))
                cp.write_row(row)
    register(name, ver, GEOFABRIK, t, "ODbL 1.0 (derived databases stay open)", release_date=rel_date,
             checksum=sha256_file(pbf), local_path=str(pbf), refresh_cadence="daily")
