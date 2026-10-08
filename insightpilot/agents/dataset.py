"""Session-owned immutable dataset snapshots and exact ingestion metadata."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

import pandas as pd
import numpy as np

from insightpilot.ingestion.schema_mapper import infer_schema_mapping
from insightpilot.ingestion.validation import validate_tables_for_workflow
from insightpilot.observability.tracer import LocalTracer, trace_stage, use_tracer
from insightpilot.reports.manifest import fingerprint_dataframe
from insightpilot.performance_tasks import cancellation_checkpoint



READINESS_SUMMARY_VERSION = "1"


def build_readiness_summary(frame: pd.DataFrame, schema: dict[str, Any]) -> dict[str, Any]:
    """Exact bounded preparation facts, calculated once per owned table revision.

    No rows enter the advisor. Low-cardinality values retain their original types;
    IDs retain counts, not unbounded option lists. Missing facts are not a PASS.
    """
    columns: dict[str, Any] = {}
    numerics: dict[str, pd.Series] = {}
    dates = set(schema.get("detected_date_columns", []))
    groups: dict[str, pd.Series] = {}
    for raw_name in frame.columns:
        cancellation_checkpoint()
        name, series = str(raw_name), frame[raw_name]
        fact: dict[str, Any] = {"dtype": str(series.dtype), "non_null_count": int(series.notna().sum())}
        if name in dates and not pd.api.types.is_numeric_dtype(series):
            parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            valid = parsed.dropna()
            days = sorted(pd.DatetimeIndex(valid.dt.normalize().unique()).strftime("%Y-%m-%d")) if len(valid) else []
            fact.update(valid_date_count=len(valid), date_min=days[0] if days else None,
                        date_max=days[-1] if days else None, distinct_day_count=len(days),
                        observed_dates=days if len(days) <= 4096 else None)
        identity = name.lower().endswith("_id") or name.lower() in {"id", "user", "entity"}
        categorical = not pd.api.types.is_numeric_dtype(series) and name not in dates
        group_like = any(word in name.lower() for word in ("group", "arm", "treatment", "variant", "分组", "组别"))
        counts = None
        if identity or categorical or group_like or pd.api.types.is_bool_dtype(series):
            try:
                counts = series.value_counts(dropna=True)
            except TypeError:
                fact["values_complete"] = False
        if pd.api.types.is_numeric_dtype(series) or name not in dates:
            if categorical and counts is not None:
                # Parse each distinct value once. Arrow/string vector screening
                # avoids Python exception parsing of hundreds of thousands of IDs.
                distinct = pd.Series(counts.index)
                if pd.api.types.is_string_dtype(distinct.dtype):
                    possible = distinct.astype('string').str.strip().str.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?").fillna(False)
                    parsed = pd.to_numeric(distinct[possible], errors="coerce")
                else:
                    parsed = pd.to_numeric(distinct, errors="coerce")
                valid_unique = parsed.notna() & np.isfinite(parsed)
                positions = parsed.index[valid_unique]
                valid_count = int(counts.iloc[positions].sum()) if len(positions) else 0
                fact["valid_numeric_count"] = valid_count
                if valid_count:
                    fact["binary_numeric"] = bool(parsed[valid_unique].isin([0, 1]).all())
                    numerics[name] = None if valid_count == len(frame) else series.isin(counts.index[positions])
            else:
                numeric = pd.to_numeric(series, errors="coerce")
                finite = numeric.notna() & np.isfinite(numeric)
                valid_count = int(finite.sum())
                fact["valid_numeric_count"] = valid_count
                if valid_count:
                    fact["binary_numeric"] = bool(numeric[finite].isin([0, 1]).all())
                    numerics[name] = None if valid_count == len(frame) else finite
            if counts is None and fact.get("binary_numeric"):
                counts = series.value_counts(dropna=True)
        if counts is not None:
            fact["unique_count"] = len(counts)
            fact["values_complete"] = len(counts) <= 100
            if len(counts) <= 100:
                fact["values"] = [value.item() if hasattr(value, "item") else value for value in counts.index]
                fact["value_counts"] = [int(value) for value in counts.values]
            if len(counts) <= 20 and (group_like or len(counts) == 2) and not identity:
                groups[name] = series
        columns[name] = fact
    for group_name, series in groups.items():
        group_fact = columns[group_name]
        masks = [series.eq(value).fillna(False).to_numpy(dtype=bool) for value in group_fact["values"]] if any(valid is not None for valid in numerics.values()) else []
        group_fact["valid_numeric_by_value"] = {
            metric: list(group_fact["value_counts"]) if valid is None else [int(np.count_nonzero(valid.to_numpy(dtype=bool) & mask)) for mask in masks]
            for metric, valid in numerics.items()
        }
    return {"version": READINESS_SUMMARY_VERSION, "exact": True, "row_count": len(frame), "columns": columns}


def _owned_copy(frame: pd.DataFrame) -> pd.DataFrame:
    # pandas deep copy does not recursively copy Python objects inside cells.
    cancellation_checkpoint()
    copied = frame.copy(deep=True)
    cancellation_checkpoint()
    for column in [name for name in copied.columns if pd.api.types.is_object_dtype(copied[name].dtype)]:
        cancellation_checkpoint()
        copied[column] = copied[column].map(deepcopy)
        cancellation_checkpoint()
    return copied


def _public_copy(frame: pd.DataFrame) -> pd.DataFrame:
    # pandas 3 guarantees CoW. Older supported pandas versions get a real copy.
    if int(pd.__version__.split('.')[0]) >= 3 and not any(pd.api.types.is_object_dtype(dtype) for dtype in frame.dtypes):
        return frame.copy(deep=False)
    return _owned_copy(frame)


@dataclass(frozen=True,init=False)
class PreparedDataset:
    """One owned revision; public tables cannot mutate the internal snapshot.

    Create a new object on refresh or changed input. Keep only this object in the
    owning session and release the prior object rather than retaining input copies.
    Private tables are used only by read-only analysis nodes; no global cache exists.
    """
    dataset_id: str
    revision: str
    _tables: Mapping[str, pd.DataFrame]
    _metadata: dict[str, dict[str, Any]]
    _fingerprints: dict[str, str]
    estimated_bytes: int
    preparation_telemetry: dict[str, Any]

    @classmethod
    def from_tables(cls, tables: dict[str, pd.DataFrame], dataset_id: str | None = None, revision: str | int = '1', *, metadata: dict[str, Any] | None = None) -> 'PreparedDataset':
        from insightpilot.performance import PerformanceConfig, MemoryBudgetExceeded, estimate_size_bytes
        config=PerformanceConfig.from_environment()
        dataset_id=dataset_id or str(uuid4())
        tracer=LocalTracer()
        with use_tracer(tracer):
            with trace_stage('dataset_budget',table_count=len(tables)):
                unique={id(frame):frame for frame in tables.values()}
                estimated_input=0
                for frame in unique.values():
                    cancellation_checkpoint()
                    estimated_input+=int(frame.memory_usage(index=True,deep=True).sum())
                if estimated_input>config.dataset_max_bytes:
                    raise MemoryBudgetExceeded(f"输入估计{estimated_input}字节超过dataset预算{config.dataset_max_bytes}字节；未复制或截断输入。")
            with trace_stage('dataset_snapshot', table_count=len(tables), cache_hit=False):
                copies={}
                owned={}
                for name,frame in tables.items():
                    with trace_stage('dataset_table_copy',table=name,rows=len(frame),cache_hit=id(frame) in copies):
                        if id(frame) not in copies:
                            copies[id(frame)]=_owned_copy(frame)
                        owned[name]=copies[id(frame)]
            prepared_metadata={}
            readiness_by_object={}
            with trace_stage('dataset_profile', rows=sum(len(frame) for frame in owned.values()), cache_hit=False):
                for name,frame in owned.items():
                    source=deepcopy((metadata or {}).get(name,{}))
                    with trace_stage('dataset_validation',table=name,rows=len(frame)):
                        warnings=list(dict.fromkeys([*source.get("warnings",[]),*validate_tables_for_workflow({name:frame})]))
                    with trace_stage('dataset_schema',table=name,rows=len(frame)):
                        schema_mapping=infer_schema_mapping(name,frame).to_dict()
                    with trace_stage('dataset_readiness',table=name,rows=len(frame),cache_hit=id(frame) in readiness_by_object):
                        if id(frame) not in readiness_by_object:
                            readiness_by_object[id(frame)]=build_readiness_summary(frame,schema_mapping)
                    source['readiness_summary']=readiness_by_object[id(frame)]
                    source['dataset_revision']=str(revision)
                    source['dataset_id']=dataset_id
                    source.update(row_count=len(frame),column_count=len(frame.columns),columns=list(map(str,frame.columns)),schema_mapping=schema_mapping,warnings=warnings)
                    source.pop("builtin_scenario", None)
                    if frame.attrs.get("insightpilot_builtin_scenario"):
                        source["builtin_scenario"] = frame.attrs["insightpilot_builtin_scenario"]
                    source.setdefault('source_type','in_memory')
                    source.setdefault('source_name',name)
                    prepared_metadata[name]=source
                estimated_bytes=estimated_input
            with trace_stage('dataset_fingerprints', rows=sum(len(frame) for frame in owned.values()), cache_hit=False):
                hashes={}
                fingerprints={}
                for name,frame in owned.items():
                    with trace_stage('dataset_table_fingerprint',table=name,rows=len(frame),cache_hit=id(frame) in hashes):
                        if id(frame) not in hashes:
                            hashes[id(frame)]=fingerprint_dataframe(frame)
                        fingerprints[name]=hashes[id(frame)]
                        prepared_metadata[name]["data_fingerprint"]=fingerprints[name]
        telemetry={**tracer.to_dict(),"summary":tracer.summary().to_dict()}
        estimated_bytes=estimated_input+estimate_size_bytes((prepared_metadata,fingerprints,telemetry))
        if estimated_bytes>config.dataset_max_bytes:
            raise MemoryBudgetExceeded(f"数据及精确元数据估计{estimated_bytes}字节超过dataset预算{config.dataset_max_bytes}字节；未截断或缓存输入。")
        instance=object.__new__(cls)
        for key,value in {"dataset_id":dataset_id or str(uuid4()),"revision":str(revision),"_tables":MappingProxyType(owned),"_metadata":prepared_metadata,"_fingerprints":fingerprints,"estimated_bytes":estimated_bytes,"preparation_telemetry":telemetry}.items():
            object.__setattr__(instance,key,value)
        cancellation_checkpoint()
        return instance

    @classmethod
    def from_registry(cls, registry, dataset_id: str | None = None, revision: str | int = '1') -> 'PreparedDataset':
        # Existing mutable registries are not trusted as immutable validation caches.
        return cls.from_tables(registry.tables,dataset_id,revision,metadata=registry.metadata)

    @property
    def tables(self) -> dict[str,pd.DataFrame]:
        copies={}
        output={}
        for name,frame in self._tables.items():
            cancellation_checkpoint()
            if id(frame) not in copies:
                copies[id(frame)]=_public_copy(frame)
            output[name]=copies[id(frame)]
        return output

    @property
    def metadata(self) -> dict[str,dict[str,Any]]:
        return deepcopy(self._metadata)

    @property
    def fingerprints(self) -> dict[str,str]:
        return dict(self._fingerprints)
