"""A connector that needs no network: proves the pipeline end to end (gate 0)."""

from collections.abc import Iterator
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.geo.grid import cell_center, h3_cells


class _Point(BaseModel):
    model_config = ConfigDict(extra="allow")
    cell: str
    lat: float
    lon: float
    venues: list[dict]


class _Venue(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str


@register
class SelfTest:
    source: ClassVar[str] = "selftest"
    version: ClassVar[str] = "0.1.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1000, per_seconds=1, jitter=(0, 0))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"grid_point": _Point, "venue": _Venue}

    def __init__(self, market):
        self.market = market

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        for cell in h3_cells(scope.market, 7)[: scope.limit or 5]:
            lat, lon = cell_center(cell)
            yield EntityRef("grid_point", cell, {"lat": lat, "lon": lon})

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        if ref.entity_type == "grid_point":
            venues = [{"id": f"{ref.natural_key}-{i}", "name": f"Test Venue {i}"} for i in range(3)]
            yield RawRecord("grid_point", ref.natural_key, {"cell": ref.natural_key, **ref.params, "venues": venues},
                            {"params": ref.params})
            for v in venues:
                yield EntityRef("venue", v["id"], {"name": v["name"]})
        else:
            if ref.natural_key.endswith("-2"):
                # deliberately violate the contract once per point: proves quarantine works
                yield RawRecord("venue", ref.natural_key, {"id": ref.natural_key}, {"params": ref.params})
            else:
                yield RawRecord("venue", ref.natural_key, {"id": ref.natural_key, "name": ref.params["name"]},
                                {"params": ref.params})

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(True, "no network")
