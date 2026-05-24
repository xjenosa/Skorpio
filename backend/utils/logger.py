"""
Centralised logger factory for the Skorpio backend.

Idempotent: calling `get_logger(name)` twice for the same `name` returns
the same logger instance without re-installing handlers (re-installation
is the classic cause of "every line printed twice" in long-lived
servers). The first call wires a single stdout StreamHandler with our
shared format; subsequent calls just return the cached logger.
"""

from __future__ import annotations

import logging
import sys

from backend.config import settings


_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level() -> int:
    """Translate the textual setting (e.g. ``"INFO"``) into a logging
    constant, defaulting to INFO when the value is missing or unknown."""
    raw = (settings.log_level or "INFO").upper()
    return logging.getLevelName(raw) if isinstance(logging.getLevelName(raw), int) else logging.INFO


def _install_stdout_handler(target: logging.Logger) -> None:
    """Attach a stdout StreamHandler with the project's format. Caller
    should ensure the logger has no handlers yet to avoid duplicate
    output."""
    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)
    target.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for ``name``. Threadsafe via the logging
    module's own locking; safe to call from import time."""
    log = logging.getLogger(name)
    if log.handlers:
        return log
    _install_stdout_handler(log)
    log.setLevel(_resolve_level())
    # Don't propagate to root — would cause duplicate lines when uvicorn's
    # default root handler is also active.
    log.propagate = False
    return log
