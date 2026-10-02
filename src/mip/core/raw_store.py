"""Gate 1 and the raw layer: validate against the contract, then store content-addressed and immutable."""

import hashlib
from typing import Any
from uuid import UUID

import orjson
import psycopg
from pydantic import BaseModel, ValidationError

from mip.core.types import RawRecord
from mip.db import Jsonb

MAX_DRIFT_DEPTH = 3


def payload_hash(payload: Any) -> tuple[bytes, bytes]:
    blob = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS)
    return hashlib.sha256(blob).digest(), blob


def field_paths(obj: Any, prefix: str = "", depth: int = 0) -> set[str]:
    """Shape fingerprint: dotted key paths, lists collapsed to [] — used for schema-drift detection."""
    out: set[str] = set()
    if depth >= MAX_DRIFT_DEPTH:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            out |= field_paths(v, p, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:50]:
            out |= field_paths(item, f"{prefix}[]", depth + 1)
    return out


class RawWriter:
    """Per-connection writer. Known-field cache avoids a query per record."""

    def __init__(self, c: psycopg.Connection, market_id: str, source: str, connector_ver: str, run_id: UUID,
                 contracts: dict[str, type[BaseModel]]):
        self.c = c
        self.market_id = market_id
        self.source = source
        self.connector_ver = connector_ver
        self.run_id = run_id
        self.contracts = contracts
        self.known: dict[str, set[str]] = {}
        self.baseline: set[str] = set()  # entity types seen for the first time in this run: no drift alerts
        self.stats = {"stored": 0, "deduped_payloads": 0, "quarantined": 0, "drift_fields": 0, "bytes": 0}

    def _known_fields(self, entity_type: str) -> set[str]:
        if entity_type not in self.known:
            rows = self.c.execute(
                "SELECT field_path FROM ops.schema_known_fields WHERE source=%s AND entity_type=%s",
                (self.source, entity_type),
            ).fetchall()
            self.known[entity_type] = {r["field_path"] for r in rows}
            if not rows:
                self.baseline.add(entity_type)
        return self.known[entity_type]

    def _drift(self, rec: RawRecord) -> None:
        paths = field_paths(rec.payload)
        known = self._known_fields(rec.entity_type)
        new = sorted(paths - known)
        if not new:
            return
        baseline = rec.entity_type in self.baseline
        with self.c.cursor() as cur:
            cur.executemany(
                "INSERT INTO ops.schema_known_fields (source, entity_type, field_path) VALUES (%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                [(self.source, rec.entity_type, p) for p in new],
            )
            if not baseline:
                cur.executemany(
                    "INSERT INTO ops.schema_drift (run_id, source, entity_type, field_path, kind, example)"
                    " VALUES (%s,%s,%s,%s,'new_field',%s)",
                    [(self.run_id, self.source, rec.entity_type, p, {"natural_key": rec.natural_key}) for p in new],
                )
                self.stats["drift_fields"] += len(new)
        known.update(new)

    def quarantine(self, rec: RawRecord, reason: str, errors: Any = None) -> None:
        self.c.execute(
            "INSERT INTO ops.quarantine (run_id, source, entity_type, natural_key, reason, errors, request_meta,"
            " http_status, payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (self.run_id, self.source, rec.entity_type, rec.natural_key, reason, Jsonb(errors), rec.request_meta,
             rec.http_status, Jsonb(rec.payload)),
        )
        self.stats["quarantined"] += 1

    def write_many(self, recs: list[RawRecord], task_id: UUID | None = None) -> int:
        """Validate, then insert payloads in digest order: concurrent workers never deadlock on shared hashes."""
        valid: list[tuple[RawRecord, bytes, bytes]] = []
        for rec in recs:
            contract = self.contracts.get(rec.entity_type)
            # 4xx/5xx tombstones (e.g. a venue that disappeared) skip the contract: the status is the signal.
            if contract is not None and 200 <= rec.http_status < 300:
                try:
                    contract.model_validate(rec.payload)
                except ValidationError as e:
                    self.quarantine(rec, "contract_violation", orjson.loads(e.json(include_url=False)))
                    continue
            self._drift(rec)
            digest, blob = payload_hash(rec.payload)
            valid.append((rec, digest, blob))
        unique = {d: b for _, d, b in valid}
        with self.c.cursor() as cur:
            for digest in sorted(unique):
                blob = unique[digest]
                cur.execute(
                    "INSERT INTO raw.payloads (payload_sha256, payload, byte_size) VALUES (%s, %s::jsonb, %s)"
                    " ON CONFLICT DO NOTHING",
                    (digest, blob.decode(), len(blob)),
                )
                if cur.rowcount == 0:
                    self.stats["deduped_payloads"] += 1
                else:
                    self.stats["bytes"] += len(blob)
            cur.executemany(
                "INSERT INTO raw.observations (market_id, source, entity_type, natural_key, run_id, task_id,"
                " connector_ver, request_meta, http_status, payload_sha256, fetched_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(self.market_id, self.source, rec.entity_type, rec.natural_key, self.run_id, task_id,
                  self.connector_ver, rec.request_meta, rec.http_status, digest, rec.fetched_at)
                 for rec, digest, _ in valid],
            )
        self.stats["stored"] += len(valid)
        return len(valid)

    def write(self, rec: RawRecord, task_id: UUID | None = None) -> bool:
        return self.write_many([rec], task_id) == 1
