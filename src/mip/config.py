"""Market and tenant YAML, validated at startup so a typo fails fast."""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mip.settings import ROOT

CONFIG_DIR = ROOT / "config"


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False

    def opt(self, key: str, default: Any = None) -> Any:
        return (self.model_extra or {}).get(key, default)


class Geography(BaseModel):
    city: str
    country: str
    boundary: str
    h3_resolution: int = 8
    osm_relation_id: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # min_lon, min_lat, max_lon, max_lat


class Discovery(BaseModel):
    hashtags: list[str] = []
    search_terms: list[str] = []
    keywords: str | None = None
    osm_tags: dict[str, list[str]] = {}


class Market(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    vertical: str
    geography: Geography
    sources: dict[str, SourceConfig]
    discovery: Discovery = Field(default_factory=Discovery)
    taxonomy: str

    def source(self, name: str) -> SourceConfig:
        if name not in self.sources:
            raise KeyError(f"source {name!r} is not configured for market {self.id!r}")
        return self.sources[name]

    def path(self, rel: str) -> Path:
        return CONFIG_DIR / rel

    def boundary_path(self) -> Path:
        return ROOT / self.geography.boundary

    def keywords_list(self) -> list[str]:
        if not self.discovery.keywords:
            return []
        lines = (CONFIG_DIR / self.discovery.keywords).read_text().splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


class FirstParty(BaseModel):
    model_config = ConfigDict(extra="allow")


class Tenant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    markets: list[str]
    accounts: dict[str, str] = {}
    watchlist: list[str] = []
    first_party: dict[str, dict[str, Any]] = {}


def _load(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    return yaml.safe_load(text), hashlib.sha256(text.encode()).hexdigest()[:16]


@lru_cache
def load_market(market_id: str) -> Market:
    data, _ = _load(CONFIG_DIR / "markets" / f"{market_id}.yaml")
    return Market.model_validate(data["market"])


def market_config_hash(market_id: str) -> str:
    return _load(CONFIG_DIR / "markets" / f"{market_id}.yaml")[1]


@lru_cache
def load_tenant(tenant_id: str) -> Tenant:
    data, _ = _load(CONFIG_DIR / "tenants" / f"{tenant_id}.yaml")
    return Tenant.model_validate(data["tenant"])
