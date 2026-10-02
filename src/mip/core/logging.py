"""structlog JSON lines (file) plus readable console output; one correlation id per task."""

import logging
import sys

import structlog

from mip.settings import settings


def setup(level: str = "INFO") -> None:
    log_dir = settings().data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler_file = logging.FileHandler(log_dir / "mip.jsonl")
    handler_console = logging.StreamHandler(sys.stderr)
    handler_file.setFormatter(logging.Formatter("%(message)s"))
    handler_console.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler_file]
    root.setLevel(level)
    console = logging.getLogger("mip.console")
    console.handlers = [handler_console]
    console.propagate = False

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    for noisy in ("httpx", "urllib3", "asyncio", "splink"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
