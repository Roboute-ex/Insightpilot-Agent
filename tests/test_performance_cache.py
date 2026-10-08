from types import MappingProxyType
import pandas as pd
import pytest
from insightpilot.performance import BoundedCache,MemoryBudgetExceeded,PerformanceConfig,estimate_size_bytes


def test_cache_enforces_count_bytes_and_lru_without_cross_session_values():
    first=BoundedCache(2,10);second=BoundedCache(2,10)
    first.put('a',b'1234');first.put('b',b'5678')
    assert first.get('a')==b'1234'
    first.put('c',b'90')
    assert first.get('b') is None and first.get('a')==b'1234'
    assert second.get('a') is None
    assert first.size_bytes==6 and len(first)==2
    first.put('d',b'0123456789')
    assert len(first)==1 and first.size_bytes==10
    assert first.stats()['evictions']==3


def test_cache_expiry_replacement_and_release_drop_owned_references():
    now=[0.0];cache=BoundedCache(2,20,5,clock=lambda:now[0])
    cache.put('a',b'123');now[0]=3
    assert cache.get('a')==b'123'
    now[0]=7;assert cache.expire()==0
    cache.put('a',b'12');assert cache.size_bytes==2
    now[0]=13;assert cache.expire()==1 and cache.size_bytes==0
    cache.put('b',b'456');cache.clear()
    assert len(cache)==0 and cache.size_bytes==0 and cache.get('b') is None


def test_oversize_is_rejected_without_silent_truncation_or_eviction():
    cache=BoundedCache(1,4);cache.put('safe',b'abcd')
    with pytest.raises(MemoryBudgetExceeded,match='未截断数据'):
        cache.put('large',b'12345')
    assert cache.get('safe')==b'abcd' and cache.get('large') is None
    with pytest.raises(ValueError):cache.put('bad',b'',size_bytes=-1)


def test_shared_dataframe_estimate_scans_deep_memory_once(monkeypatch):
    frame=pd.DataFrame({'text':['模拟值']*10,'n':range(10)})
    original=pd.DataFrame.memory_usage;calls=[]
    def measured(self,*a,**kw):calls.append(self);return original(self,*a,**kw)
    monkeypatch.setattr(pd.DataFrame,'memory_usage',measured)
    value={'first':frame,'same':frame,'view':MappingProxyType({'frame':frame})}
    size=estimate_size_bytes(value)
    assert size>=int(original(frame,deep=True).sum()) and len(calls)==1


def test_performance_config_validates_explicit_environment(monkeypatch):
    monkeypatch.setenv('INSIGHTPILOT_PERF_EXPORT_MAX_BYTES','1048576')
    monkeypatch.setenv('INSIGHTPILOT_PERF_SESSION_TTL_SECONDS','120.5')
    config=PerformanceConfig.from_environment()
    assert config.export_max_bytes==1048576 and config.session_ttl_seconds==120.5
    assert config.dataset_max_entries==config.result_max_entries==1
    with pytest.raises(ValueError):PerformanceConfig(table_page_size=99)
    with pytest.raises(ValueError):PerformanceConfig(export_max_bytes=0)
    with pytest.raises(ValueError):PerformanceConfig(duckdb_threads=65)


def test_nonfinite_expiry_cannot_disable_resource_cleanup():
    for value in (float("nan"),float("inf"),-1):
        with pytest.raises(ValueError):PerformanceConfig(session_ttl_seconds=value)
        with pytest.raises(ValueError):BoundedCache(1,100,value)
