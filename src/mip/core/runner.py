"""Drives connectors: discover -> tasks, tasks -> raw. A crash or sleeping laptop never loses work."""

import os
import socket
import threading
import time
import traceback
from collections import Counter
from typing import Any
from uuid import UUID

import structlog
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from mip.config import Market
from mip.core import queue
from mip.core.connector import get_connector_cls
from mip.core.ratelimit import backoff_delay
from mip.core.raw_store import RawWriter
from mip.core.runs import end_run, record_health, start_run
from mip.core.types import EntityRef, RawRecord, Scope, SourceBlocked, SourceGone
from mip.db import connect

log = structlog.get_logger()
console = Console(stderr=True)


def make_connector(market: Market, source: str):
    cls = get_connector_cls(source)
    return cls(market)


def healthcheck(market: Market, source: str) -> bool:
    conn = make_connector(market, source)
    t0 = time.monotonic()
    try:
        h = conn.healthcheck()
    except Exception as e:
        h_ok, detail = False, f"{type(e).__name__}: {e}"
    else:
        h_ok, detail = h.ok, h.detail
    ms = int((time.monotonic() - t0) * 1000)
    record_health(source, h_ok, ms, detail)
    (console.print if h_ok else console.print)(
        f"[{'green' if h_ok else 'red'}]healthcheck {source}: {'ok' if h_ok else 'FAILED'}[/] {detail} ({ms} ms)"
    )
    return h_ok


def discover(market: Market, source: str, limit: int | None = None, refresh: bool = False,
             options: dict[str, Any] | None = None) -> int:
    run_id = start_run(market.id, source, "discover", {"limit": limit, "refresh": refresh, **(options or {})})
    try:
        conn = make_connector(market, source)
        refs = list(conn.discover(Scope(market=market, limit=limit, options=options or {})))
        with connect() as c:
            n = queue.enqueue(c, market.id, source, refs, refresh=refresh)
        end_run(run_id, "succeeded", {"discovered": len(refs), "enqueued": n})
        console.print(f"[green]discover {source}[/]: {len(refs)} units, {n} new/refreshed tasks")
        return n
    except Exception as e:
        end_run(run_id, "failed", {}, f"{type(e).__name__}: {e}")
        raise


class _Worker(threading.Thread):
    def __init__(self, idx: int, ctx: "_FetchCtx"):
        super().__init__(daemon=True, name=f"worker-{idx}")
        self.ctx = ctx
        self.name_id = f"{socket.gethostname()}:{os.getpid()}:{idx}"

    def run(self) -> None:
        ctx = self.ctx
        connector = make_connector(ctx.market, ctx.source)
        with connect(autocommit=False) as c:
            writer = RawWriter(c, ctx.market.id, ctx.source, connector.version, ctx.run_id, connector.contracts)
            while not ctx.stop.is_set():
                if ctx.max_tasks and ctx.claimed >= ctx.max_tasks:
                    break
                tasks = queue.claim(c, ctx.market.id, ctx.source, self.name_id, ctx.run_id, 1, ctx.entity_types)
                c.commit()
                if not tasks:
                    if ctx.idle_wait():
                        continue
                    break
                with ctx.lock:
                    ctx.claimed += 1
                    ctx.active += 1
                try:
                    self._process(c, connector, writer, tasks[0])
                finally:
                    with ctx.lock:
                        ctx.active -= 1
            ctx.merge_stats(writer.stats, getattr(getattr(connector, "http", None), "stats", {}))

    def _process(self, c, connector, writer: RawWriter, t: dict) -> None:
        ctx = self.ctx
        ref = EntityRef(t["entity_type"], t["natural_key"], t["params"] or {}, t["priority"])
        structlog.contextvars.bind_contextvars(task_id=str(t["task_id"]), source=ctx.source,
                                               entity_type=ref.entity_type, key=ref.natural_key)
        try:
            children: list[EntityRef] = []
            stored = 0
            for item in connector.fetch(ref):
                if isinstance(item, RawRecord):
                    stored += writer.write(item, t["task_id"])
                elif isinstance(item, EntityRef):
                    children.append(item)
            if children:
                queue.enqueue(c, ctx.market.id, ctx.source, children, parent_task_id=t["task_id"],
                              refresh=ctx.refresh_children)
            queue.complete(c, t["task_id"])
            c.commit()  # raw rows, child tasks and task completion land atomically: idempotent retries
            ctx.count("done")
            ctx.count("children", len(children))
        except SourceGone as e:
            c.rollback()
            writer.write(RawRecord(ref.entity_type, ref.natural_key, {"_gone": True, "detail": str(e)},
                                   {"params": ref.params}, http_status=404), t["task_id"])
            queue.complete(c, t["task_id"])
            c.commit()
            ctx.count("gone")
        except SourceBlocked as e:
            c.rollback()
            queue.fail(c, t["task_id"], str(e), backoff_delay(connector.rate_limit, t["attempts"] + 2))
            c.commit()
            ctx.count("blocked")
            if "circuit breaker open" in str(e):
                console.print(f"[red]{ctx.source}: circuit breaker open — stopping run[/]")
                ctx.breaker_open = True
                ctx.stop.set()
        except Exception as e:
            c.rollback()
            tb = traceback.format_exc(limit=6)
            log.error("task.error", error=str(e)[:500], tb=tb)
            queue.fail(c, t["task_id"], f"{type(e).__name__}: {e}\n{tb}", backoff_delay(connector.rate_limit,
                                                                                           t["attempts"]))
            c.commit()
            ctx.count("errors")
        finally:
            structlog.contextvars.clear_contextvars()
            ctx.progress_tick()


class _FetchCtx:
    def __init__(self, market: Market, source: str, run_id: UUID, max_tasks: int | None,
                 entity_types: list[str] | None, refresh_children: bool):
        self.market, self.source, self.run_id = market, source, run_id
        self.max_tasks, self.entity_types, self.refresh_children = max_tasks, entity_types, refresh_children
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.claimed = 0
        self.active = 0
        self.counter: Counter = Counter()
        self.writer_stats: Counter = Counter()
        self.http_stats: Counter = Counter()
        self.breaker_open = False
        self.progress = None
        self.ptask = None

    def count(self, k: str, n: int = 1) -> None:
        with self.lock:
            self.counter[k] += n

    def merge_stats(self, w: dict, h: dict) -> None:
        with self.lock:
            self.writer_stats.update(w)
            self.http_stats.update(h)

    def idle_wait(self) -> bool:
        """No claimable task: wait while siblings may still produce children."""
        with self.lock:
            if self.active == 0:
                return False
        time.sleep(0.5)
        return True

    def progress_tick(self) -> None:
        if self.progress is not None:
            self.progress.update(self.ptask, advance=1, description=f"{self.source} {dict(self.counter)}")


def fetch(market: Market, source: str, workers: int = 4, max_tasks: int | None = None,
          entity_types: list[str] | None = None, skip_health: bool = False,
          refresh_children: bool = False) -> dict[str, Any]:
    if not skip_health and not healthcheck(market, source):
        raise SystemExit(f"{source}: healthcheck failed — not starting 10,000 doomed tasks")
    run_id = start_run(market.id, source, "fetch", {"workers": workers, "max_tasks": max_tasks,
                                                    "entity_types": entity_types})
    ctx = _FetchCtx(market, source, run_id, max_tasks, entity_types, refresh_children)
    with connect() as c:
        pending = c.execute(
            "SELECT count(*) AS n FROM ops.tasks WHERE market_id=%s AND source=%s AND status IN"
            " ('pending','failed','running') AND (%s::text[] IS NULL OR entity_type = ANY(%s))",
            (market.id, source, entity_types, entity_types),
        ).fetchone()["n"]
    status, err = "succeeded", None
    try:
        with Progress(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
                      console=console, transient=False) as progress:
            ctx.progress = progress
            ctx.ptask = progress.add_task(source, total=max_tasks or pending or None)
            ws = [_Worker(i, ctx) for i in range(workers)]
            for w in ws:
                w.start()
            for w in ws:
                while w.is_alive():
                    w.join(timeout=1)
    except KeyboardInterrupt:
        ctx.stop.set()
        status, err = "aborted", "KeyboardInterrupt"
    if ctx.breaker_open:
        status, err = "failed", "circuit breaker open"
    metrics = {"tasks": dict(ctx.counter), "raw": dict(ctx.writer_stats), "http": dict(ctx.http_stats)}
    end_run(run_id, status, metrics, err)
    console.print(f"[bold]{source}[/] run {run_id} {status}: {metrics}")
    return metrics
