"""Session-owned data/results: no Streamlit calls, global user cache, or disk state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Hashable
from uuid import uuid4
import hashlib
import json
import time
from pathlib import Path

import pandas as pd
from insightpilot.agents.dataset import PreparedDataset
from insightpilot.analysis.threads import AnalysisThread
from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.performance import BoundedCache, MemoryBudgetExceeded, PerformanceConfig, estimate_size_bytes


@dataclass
class DatasetSnapshot:
    source_key: Hashable
    prepared: PreparedDataset
    tables: dict[str, pd.DataFrame]
    metadata: dict[str, Any]
    fingerprints: dict[str, str]
    registry: TableRegistry
    source_type: str
    estimated_bytes: int

    @property
    def dataset_id(self) -> str:
        return self.prepared.dataset_id

    @property
    def revision(self) -> str:
        return self.prepared.revision

    def suggest_mapping(self, table_name: str) -> ColumnMapping:
        suggestion = self.metadata.get(table_name, {}).get("schema_mapping", {})
        return ColumnMapping(
            table_name=table_name,
            date_column=next(iter(suggestion.get("detected_date_columns", [])), None),
            metric_columns=list(suggestion.get("possible_metric_columns", [])[:3]),
            dimension_columns=list(suggestion.get("possible_dimension_columns", [])[:5]),
            outcome_column=next(iter(suggestion.get("possible_metric_columns", [])), None),
            notes=list(suggestion.get("warnings", [])),
        )


class DatasetSession:
    """Keep one owned revision. Public tables are display copies of the protected source."""
    def __init__(self, config: PerformanceConfig | None = None, *, clock: Callable[[], float] = time.monotonic):
        self.config = config or PerformanceConfig.from_environment()
        self.cache = BoundedCache(1, self.config.dataset_max_bytes, self.config.session_ttl_seconds, clock=clock)
        self.revision = 0
        self.dataset_id = str(uuid4())

    @property
    def current(self) -> DatasetSnapshot | None:
        return self.cache.get("active")

    def load(self, source_key: Hashable, loader: Callable[[], tuple[dict[str, pd.DataFrame], dict[str, Any] | None]], *, source_type: str, force: bool = False, retained_source_bytes: int = 0) -> tuple[DatasetSnapshot, bool]:
        current = self.current
        if not force and current is not None and current.source_key == source_key:
            return current, True
        revision = self.reserve_revision()
        snapshot = prepare_dataset_snapshot(source_key, loader, source_type=source_type,
            dataset_id=self.dataset_id, revision=revision, config=self.config,
            retained_source_bytes=retained_source_bytes)
        self.adopt(snapshot)
        return snapshot, False

    def reserve_revision(self) -> str:
        self.cache.clear()
        self.revision += 1
        return str(self.revision)

    def adopt(self, snapshot: DatasetSnapshot) -> None:
        if snapshot.dataset_id != self.dataset_id or str(snapshot.revision) != str(self.revision):
            raise ValueError("准备结果与当前会话预留的数据修订不一致，未采纳旧任务结果")
        self.cache.put("active", snapshot, size_bytes=snapshot.estimated_bytes)

    def clear(self) -> None:
        self.cache.clear()


def prepare_dataset_snapshot(source_key, loader, *, source_type: str, dataset_id: str,
                             revision: str, config: PerformanceConfig,
                             retained_source_bytes: int = 0) -> DatasetSnapshot:
    """Pure worker function. Only the UI owner may adopt the returned revision."""
    from insightpilot.performance_tasks import report_stage, cancellation_checkpoint as checkpoint
    report_stage("data_loading")
    tables, metadata = loader()
    checkpoint()
    input_bytes = estimate_size_bytes(tables)
    if retained_source_bytes < 0:
        raise ValueError("保留源文件字节数不可为负数")
    if input_bytes + retained_source_bytes > config.dataset_max_bytes:
        raise MemoryBudgetExceeded("输入超过本会话数据预算，未截断或分析。请减少所选输入或调整明确预算。")
    report_stage("dataset_preparation")
    prepared = PreparedDataset.from_tables(tables, dataset_id=dataset_id, revision=revision, metadata=metadata)
    checkpoint()
    public_tables = prepared.tables
    metadata = prepared.metadata
    copy_bytes = sum(int(frame.memory_usage(deep=True).sum()) for frame in public_tables.values()
                     if int(pd.__version__.split('.')[0]) < 3 or any(pd.api.types.is_object_dtype(dtype) for dtype in frame.dtypes))
    size = prepared.estimated_bytes + copy_bytes + retained_source_bytes
    if size > config.dataset_max_bytes:
        raise MemoryBudgetExceeded("受控数据快照与保留源文件合计超过本会话数据预算，未截断数据。")
    return DatasetSnapshot(source_key, prepared, public_tables, metadata, prepared.fingerprints,
                           TableRegistry(public_tables, metadata), source_type, size)


def analysis_cache_key(*, dataset_id: str, dataset_revision: str, config: dict[str, Any],
                       catalog_version: str, computation_version: str) -> str:
    """Only answer-affecting values belong here; callers omit display navigation."""
    from insightpilot.metrics.definitions import computation_payload
    config = computation_payload(config)
    payload = {"dataset_id": dataset_id, "dataset_revision": str(dataset_revision), "configuration": config,
               "catalog_version": catalog_version, "computation_version": computation_version}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


class AnalysisSession:
    """Same API for Streamlit and benchmarks; one successful result cache per session."""
    def __init__(self, config: PerformanceConfig | None = None, *, clock: Callable[[], float] = time.monotonic):
        self.config = config or PerformanceConfig.from_environment()
        # History consumes part of the existing 256 MiB result budget, never extra.
        self.history_reserved_bytes = min(512 * 1024, self.config.result_max_bytes // 16) if self.config.result_max_bytes >= 4096 else 0
        self.history = AnalysisThread(max_bytes=self.history_reserved_bytes)
        self.cache = BoundedCache(1, self.config.result_max_bytes - self.history_reserved_bytes, self.config.session_ttl_seconds, clock=clock)
        self.last_key: str | None = None
        self.last_result: dict[str, Any] | None = None
        self._clock = clock
        self._expires_at = 0.0

    @property
    def current(self) -> dict[str, Any] | None:
        if self.last_result is not None and self._clock() >= self._expires_at:
            self.clear()
        if self.last_result is not None:
            self._expires_at = self._clock() + self.config.session_ttl_seconds
        return self.last_result

    def run(self, key: str, compute: Callable[[], dict[str, Any]], *, force: bool = False) -> tuple[dict[str, Any], bool]:
        result = None if force else self.lookup(key)
        if result is not None:
            return result, True
        self.clear()
        result = compute()
        self.accept(key, result)
        return result, False

    def lookup(self, key: str) -> dict[str, Any] | None:
        result = self.cache.get(key)
        if result is not None:
            self.last_key = key
            self.last_result = result
            self._expires_at = self._clock() + self.config.session_ttl_seconds
        return result

    def accept(self, key: str, result: dict[str, Any], *, size_bytes: int | None = None) -> None:
        size = estimate_size_bytes(result) if size_bytes is None else size_bytes
        if size > self.cache.max_bytes:
            raise MemoryBudgetExceeded("分析结果超过本会话结果保留预算，未截断统计数据。请调整明确预算。")
        self.clear()
        status = result.get("execution_status", "COMPLETED")
        if status in {"COMPLETED", "PREVIEW", "WAITING_APPROVAL"} and not result.get("errors"):
            self.cache.put(key, result, size_bytes=size)
            self.last_key = key
        self.last_result = result
        self._expires_at = self._clock() + self.config.session_ttl_seconds

    def clear(self) -> None:
        self.cache.clear()
        self.last_key = None
        self.last_result = None
        self._expires_at = 0.0


def catalog_version(project_root: Path, *, presentation: bool = False) -> str:
    """Read small YAML content every rerun; semantic and display changes differ."""
    import yaml
    from insightpilot.metrics.definitions import computation_payload
    model_root = project_root / "insightpilot" / "semantic" / "models"
    digest = hashlib.sha256()
    for path in sorted([*model_root.glob("*.yaml"), *model_root.glob("*.yml")]):
        content = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0")
        if not presentation:
            try:
                content = json.dumps(computation_payload(yaml.safe_load(content)), ensure_ascii=False,
                    sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            except (yaml.YAMLError, UnicodeError):
                # Invalid content changes the key and will be rejected by model load.
                pass
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def expire_session_caches(state) -> int:
    """Drop expired display/export bytes even when their tabs stay closed."""
    expired = 0
    for key in list(state):
        value = state[key]
        if key.startswith("performance_") and isinstance(value, BoundedCache):
            expired += value.expire()
    return expired
