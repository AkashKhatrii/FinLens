"""Dead-simple TTL disk cache.

Market data providers are slow (2-5 s/ticker) and rate-limited, and a single
analysis touches the same ticker from six different engines. Without this the
app is unusable during development.
"""
from __future__ import annotations

import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from .config import CACHE_DIR

T = TypeVar("T")


def _path(namespace: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    return CACHE_DIR / f"{namespace}__{digest}.pkl"


def get(namespace: str, key: str, ttl: int) -> Any | None:
    p = _path(namespace, key)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > ttl:
        return None
    try:
        with p.open("rb") as fh:
            return pickle.load(fh)
    except Exception:
        # A corrupt/half-written entry should never take the request down.
        p.unlink(missing_ok=True)
        return None


def put(namespace: str, key: str, value: Any) -> None:
    p = _path(namespace, key)
    tmp = p.with_suffix(".tmp")
    try:
        with tmp.open("wb") as fh:
            pickle.dump(value, fh)
        tmp.replace(p)  # atomic - avoids readers seeing a partial file
    except Exception:
        tmp.unlink(missing_ok=True)


def memoize(namespace: str, key: str, ttl: int, fn: Callable[[], T]) -> T:
    hit = get(namespace, key, ttl)
    if hit is not None:
        return hit
    value = fn()
    if value is not None:
        put(namespace, key, value)
    return value


def clear(namespace: str | None = None) -> int:
    pattern = f"{namespace}__*.pkl" if namespace else "*.pkl"
    n = 0
    for p in CACHE_DIR.glob(pattern):
        p.unlink(missing_ok=True)
        n += 1
    return n
