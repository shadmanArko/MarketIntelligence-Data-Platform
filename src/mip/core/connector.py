"""The one interface every source implements; pipelines only ever talk to this."""

from collections.abc import Iterator
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel

from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope


@runtime_checkable
class Connector(Protocol):
    source: ClassVar[str]
    version: ClassVar[str]               # bumped on any parsing change
    rate_limit: ClassVar[RateLimitPolicy]
    contracts: ClassVar[dict[str, type[BaseModel]]]  # gate 1: entity_type -> typed contract

    def discover(self, scope: Scope) -> Iterator[EntityRef]: ...

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        """Full raw payloads, nothing dropped. May also yield follow-up work (e.g. venue -> menu)."""
        ...

    def healthcheck(self) -> HealthStatus: ...


_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    _REGISTRY[cls.source] = cls
    return cls


def get_connector_cls(source: str) -> type:
    import mip.connectors  # noqa: F401  (populates the registry)

    if source not in _REGISTRY:
        raise KeyError(f"unknown source {source!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[source]


def registered() -> list[str]:
    import mip.connectors  # noqa: F401

    return sorted(_REGISTRY)
