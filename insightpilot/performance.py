"""Conservative, session-owned memory budgets. No global data cache or disk persistence."""
from __future__ import annotations
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
import os
import math
import sys
import time
from typing import Any, Callable, Hashable

MiB=1024*1024

@dataclass(frozen=True)
class PerformanceConfig:
    dataset_max_entries: int = 1
    dataset_max_bytes: int = 1024*MiB
    result_max_entries: int = 1
    result_max_bytes: int = 256*MiB
    export_max_entries: int = 6
    export_max_bytes: int = 64*MiB
    chart_max_points: int = 3000
    chart_max_series: int = 20
    table_page_size: int = 100
    session_ttl_seconds: float = 1800.0
    duckdb_threads: int = 4
    duckdb_memory_limit_mb: int = 1024
    computation_version: str = '0.1.0-performance-1'
    export_template_version: str = '0.1.0-performance-1'

    def __post_init__(self):
        for item in fields(self):
            value=getattr(self,item.name)
            if item.name in {'computation_version','export_template_version'}:continue
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError(f'{item.name} 必须为有限正数')
            if item.name!='session_ttl_seconds' and not isinstance(value,int):
                raise ValueError(f'{item.name} 必须为整数')
        if self.table_page_size not in {50,100,200,500}:
            raise ValueError('表格每页行数必须为50、100、200或500')
        if self.duckdb_threads>64:raise ValueError('DuckDB线程上限为64')

    @classmethod
    def from_environment(cls) -> 'PerformanceConfig':
        values={}
        allowed={item.name:item.type for item in fields(cls) if item.name not in {'computation_version','export_template_version'}}
        for name in allowed:
            raw=os.environ.get('INSIGHTPILOT_PERF_'+name.upper())
            if raw is not None:
                values[name]=float(raw) if name=='session_ttl_seconds' else int(raw)
        return cls(**values)

class MemoryBudgetExceeded(ValueError):
    """Reject an over-budget value; never silently truncate statistical inputs."""


def estimate_size_bytes(value: Any, seen: set[int] | None = None) -> int:
    """Estimate retained objects once per insertion, without serializing/copying tables.

    Shared references are counted once. This is an object budget estimate, not an
    RSS hard limit, and excludes transient allocations/native allocator overhead.
    """
    seen=set() if seen is None else seen
    if id(value) in seen:return 0
    seen.add(id(value))
    if value is None:return 0
    if isinstance(value,(bytes,bytearray,memoryview)):return len(value)
    if isinstance(value,str):return sys.getsizeof(value)
    # Avoid importing the analytical stack when only bytes caches are needed.
    pandas=sys.modules.get('pandas')
    if pandas is not None and isinstance(value,pandas.DataFrame):return int(value.memory_usage(index=True,deep=True).sum())
    if pandas is not None and isinstance(value,pandas.Series):return int(value.memory_usage(index=True,deep=True))
    numpy=sys.modules.get('numpy')
    if numpy is not None and isinstance(value,numpy.ndarray):return int(value.nbytes)+sys.getsizeof(value)
    if isinstance(value,Mapping):return sys.getsizeof(value)+sum(estimate_size_bytes(k,seen)+estimate_size_bytes(v,seen) for k,v in value.items())
    if isinstance(value,(tuple,list,set,frozenset,OrderedDict)):return sys.getsizeof(value)+sum(estimate_size_bytes(v,seen) for v in value)
    if is_dataclass(value) and not isinstance(value,type):return sys.getsizeof(value)+sum(estimate_size_bytes(getattr(value,f.name),seen) for f in fields(value))
    # Plotly figures keep numeric arrays in these owned dictionaries; no to_json.
    if value.__class__.__module__.startswith('plotly.') and hasattr(value,'__dict__'):
        return sys.getsizeof(value)+estimate_size_bytes(vars(value),seen)
    return sys.getsizeof(value)

@dataclass
class _Entry:
    value: Any
    size_bytes: int
    expires_at: float

class BoundedCache:
    """LRU with byte/count/TTL bounds, owned by exactly one session or request.

    No process-wide instance is created here. Call clear() when a dataset changes
    or the session is explicitly released. Idle entries expire on access; session
    lifetime cleanup is also the UI host's responsibility.
    """
    def __init__(self, max_entries: int, max_bytes: int, ttl_seconds: float = 1800.0, *, clock: Callable[[],float] = time.monotonic):
        if isinstance(max_entries,bool) or isinstance(max_bytes,bool) or not isinstance(max_entries,int) or not isinstance(max_bytes,int) or max_entries<1 or max_bytes<1 or not math.isfinite(ttl_seconds) or ttl_seconds<=0:raise ValueError('缓存数量、字节和TTL必须为有限正数')
        self.max_entries=int(max_entries);self.max_bytes=int(max_bytes);self.ttl_seconds=float(ttl_seconds);self._clock=clock
        self._items: OrderedDict[Hashable,_Entry]=OrderedDict();self._bytes=0
        self.hits=0;self.misses=0;self.evictions=0

    def expire(self) -> int:
        now=self._clock();expired=[key for key,entry in self._items.items() if entry.expires_at<=now]
        for key in expired:self.pop(key);self.evictions+=1
        return len(expired)

    def get(self,key: Hashable,default: Any = None) -> Any:
        self.expire();entry=self._items.get(key)
        if entry is None:self.misses+=1;return default
        self.hits+=1;self._items.move_to_end(key)
        entry.expires_at=self._clock()+self.ttl_seconds
        return entry.value

    def put(self,key: Hashable,value: Any, *, size_bytes: int | None = None) -> None:
        size=estimate_size_bytes(value) if size_bytes is None else int(size_bytes)
        if size<0:raise ValueError('缓存大小不可为负数')
        if size>self.max_bytes:
            raise MemoryBudgetExceeded(f'对象估计占用{size/MiB:.1f} MiB，超过本会话缓存预算{self.max_bytes/MiB:.1f} MiB；未截断数据。请提高明确预算或减少所选输入。')
        self.expire();self.pop(key)
        while self._items and (len(self._items)>=self.max_entries or self._bytes+size>self.max_bytes):
            _,old=self._items.popitem(last=False);self._bytes-=old.size_bytes;self.evictions+=1
        self._items[key]=_Entry(value,size,self._clock()+self.ttl_seconds);self._bytes+=size

    def pop(self,key: Hashable,default: Any = None) -> Any:
        entry=self._items.pop(key,None)
        if entry is None:return default
        self._bytes-=entry.size_bytes;return entry.value

    def clear(self) -> None:self._items.clear();self._bytes=0

    def __len__(self) -> int:self.expire();return len(self._items)

    @property
    def size_bytes(self) -> int:self.expire();return self._bytes

    def stats(self) -> dict[str,int|float]:
        self.expire()
        return {'entries':len(self._items),'estimated_bytes':self._bytes,'max_entries':self.max_entries,'max_bytes':self.max_bytes,'ttl_seconds':self.ttl_seconds,'hits':self.hits,'misses':self.misses,'evictions':self.evictions}
