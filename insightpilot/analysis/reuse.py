"""Bounded, invocation-local aggregate reuse for immutable analysis inputs."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

_cache: ContextVar[dict | None] = ContextVar('insightpilot_aggregate_scope',default=None)

@contextmanager
def aggregate_scope():
    cache={"values":{},"bytes":0}
    token=_cache.set(cache)
    try:
        yield
    finally:
        cache.clear()
        _cache.reset(token)


def aggregate_once(frame, key: tuple, compute: Callable[[], Any]):
    """Retain source identity until scope end; never cache between user requests."""
    cache=_cache.get()
    if cache is None:
        return compute()
    identity=(id(frame),key)
    entries=cache["values"]
    if identity not in entries:
        from insightpilot.performance import PerformanceConfig, estimate_size_bytes
        result=compute()
        size=estimate_size_bytes(result)
        if len(entries)>=64 or cache["bytes"]+size>PerformanceConfig.from_environment().result_max_bytes:
            return result
        entries[identity]=(frame,result)
        cache["bytes"]+=size
    return entries[identity][1]
