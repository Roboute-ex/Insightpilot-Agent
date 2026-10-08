"""JSON-serializable run manifest for reproducible analysis configuration."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import MISSING, asdict, dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

import pandas as pd


CURRENT_MANIFEST_VERSION = "1.1"


def _safe_string(value: str, key: str = "") -> str:
    lowered = key.lower()
    if any(term in lowered for term in ("password", "passwd", "token", "secret", "api_key", "credential")):
        return "***"
    if lowered in {"database_url", "connection_string", "connection_url"}:
        return "[数据库连接地址已脱敏]"
    if lowered in {"database_url", "connection_url", "connection_string"}:
        return "<数据库连接需重新提供>"
    value = re.sub(r"(?i)([?&][A-Za-z_][A-Za-z0-9_]*=)[^&#\s]+", r"\1***", value)
    masked = re.sub(r"\b(?:postgres(?:ql)?(?:\+\w+)?|mysql(?:\+\w+)?|mssql(?:\+\w+)?|sqlite(?:\+\w+)?|oracle(?:\+\w+)?)://[^\s<>]+", "[数据库连接地址已脱敏]", value, flags=re.IGNORECASE)
    masked = re.sub(r"(://[^:/@\s]+:)[^@/\s]+(@)", r"\1***\2", masked)
    masked = re.sub(r"([?&](?:[^=&\s]*(?:token|password|passwd|secret|key|credential)[^=&\s]*)=)[^&#\s]*", r"\1***", masked, flags=re.IGNORECASE)
    masked = re.sub(r"(?i)\b(password|passwd|token|secret|api_key)\s*[=:]\s*[^\s,;]+", r"\1=***", masked)
    if any(term in lowered for term in ("path", "file", "source_name")) and (re.match(r"^[A-Za-z]:[\\/]", masked) or masked.startswith("/")):
        return PureWindowsPath(masked).name if re.match(r"^[A-Za-z]:[\\/]", masked) else PurePosixPath(masked).name
    return masked


def sanitize_manifest_value(value: Any, key: str = "") -> Any:
    if any(term in key.lower() for term in ("password", "passwd", "token", "secret", "api_key", "credential")):
        return "***"
    if key == "parameters" and isinstance(value, (list, tuple)):
        return ["***" for _ in value]
    if isinstance(value, pd.DataFrame):
        return {
            "row_count": int(len(value)),
            "column_count": int(len(value.columns)),
            "columns": [str(column) for column in value.columns],
        }
    if isinstance(value, dict):
        is_filter = "operator" in value and ("dimension_id" in value or "dimension" in value or "column" in value or "field" in value)
        return {str(item_key): ("<已脱敏，需重新输入>" if is_filter and str(item_key) in {"value", "values"} else sanitize_manifest_value(item, str(item_key))) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_manifest_value(item, key) for item in value]
    if isinstance(value, str):
        return _safe_string(value, key)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        try:
            return sanitize_manifest_value(value.item(), key)
        except (TypeError, ValueError):
            return str(value)
    return value


def fingerprint_dataframe(df: pd.DataFrame) -> str:
    """Return a deterministic SHA-256 fingerprint without serializing the table."""

    digest = hashlib.sha256()
    schema = {
        "columns": [str(column) for column in df.columns],
        "dtypes": [str(dtype) for dtype in df.dtypes],
        "row_count": int(len(df)),
    }
    digest.update(json.dumps(schema, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    try:
        row_hashes = pd.util.hash_pandas_object(df, index=True, categorize=True)
    except (TypeError, ValueError):
        row_hashes = pd.util.hash_pandas_object(df.astype(str), index=True, categorize=True)
    digest.update(row_hashes.to_numpy().tobytes())
    return digest.hexdigest()


@dataclass
class RunManifest:
    manifest_version: str
    project_version: str
    run_id: str
    created_at: str
    data_source_type: str
    source_summary: dict[str, Any]
    table_summaries: list[dict[str, Any]]
    dataset_fingerprints: dict[str, str]
    question: str
    goal_mode: str
    goal_mode_source: str
    workflow_backend: str
    playbook_id: str | None
    playbook_parameters: dict[str, Any]
    column_mapping: dict[str, Any]
    route_taken: list[str]
    reviewer_status: str
    reviewer_score: int
    caveats: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    semantic_model_id: str | None = None
    catalog_fingerprint: str | None = None
    metric_request: dict[str, Any] = field(default_factory=dict)
    query_plan_id: str | None = None
    join_plan_id: str | None = None
    plan_review: dict[str, Any] = field(default_factory=dict)
    contract_summary: dict[str, Any] = field(default_factory=dict)
    lineage_summary: dict[str, Any] = field(default_factory=dict)
    telemetry_summary: dict[str, Any] = field(default_factory=dict)
    evaluation_summary: dict[str, Any] = field(default_factory=dict)

    metric_definitions: list[dict[str, Any]] = field(default_factory=list)
    semantic_fingerprint: str | None = None
    presentation_fingerprint: str | None = None
    planning_status: str = "ready"
    clarification: dict[str, Any] = field(default_factory=dict)
    analysis_advice: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_manifest_value(asdict(self))

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True, allow_nan=False)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "RunManifest":
        if not isinstance(values, dict):
            raise ValueError("manifest 必须是 JSON object。")
        fields = cls.__dataclass_fields__
        field_names = fields.keys()
        unknown = set(values) - set(field_names)
        if unknown:
            raise ValueError("manifest 包含未知字段：" + ", ".join(sorted(unknown)))
        unknown = set(values) - set(field_names)
        if unknown:
            raise ValueError(f"manifest 包含未知字段：{', '.join(sorted(unknown))}")
        missing = [
            name
            for name, definition in fields.items()
            if name not in values
            and definition.default is MISSING
            and definition.default_factory is MISSING
        ]
        if missing:
            raise ValueError(f"manifest 缺少字段：{', '.join(missing)}")
        manifest = cls(**sanitize_manifest_value({key: values[key] for key in field_names if key in values}))
        errors = manifest.validate()
        if errors:
            raise ValueError("manifest 校验失败：" + "；".join(errors))
        return manifest

    @classmethod
    def from_json(cls, content: str) -> "RunManifest":
        try:
            def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("manifest JSON 包含重复字段。")
                    result[key] = value
                return result
            values = json.loads(content, object_pairs_hook=unique_object)
        except json.JSONDecodeError as exc:
            raise ValueError(f"manifest JSON 无法解析：{exc}") from exc
        return cls.from_dict(values)

    def validate(self) -> list[str]:
        errors: list[str] = []
        major = str(self.manifest_version).split(".", 1)[0]
        current_major = CURRENT_MANIFEST_VERSION.split(".", 1)[0]
        if major != current_major:
            errors.append(
                f"manifest_version={self.manifest_version} 与当前 {CURRENT_MANIFEST_VERSION} 不兼容"
            )
        if not self.run_id:
            errors.append("run_id 不能为空")
        if not self.project_version:
            errors.append("project_version 不能为空")
        if not isinstance(self.dataset_fingerprints, dict):
            errors.append("dataset_fingerprints 必须是 object")
        if not isinstance(self.column_mapping, dict):
            errors.append("column_mapping 必须是 object")
        for name in ("source_summary", "playbook_parameters", "metric_request", "plan_review", "contract_summary", "lineage_summary", "telemetry_summary", "evaluation_summary", "clarification"):
            if not isinstance(getattr(self, name), dict):
                errors.append(f"{name} 必须是 object")
        for name in ("table_summaries", "route_taken", "caveats", "errors", "metric_definitions"):
            if not isinstance(getattr(self, name), list):
                errors.append(f"{name} 必须是 array")
        for name in ("run_id", "project_version", "created_at", "data_source_type", "question", "goal_mode", "workflow_backend"):
            if not isinstance(getattr(self, name), str):
                errors.append(f"{name} 必须是 string")
        if self.planning_status not in {"ready", "needs_clarification", "unsupported", "invalid_input"}:
            errors.append("planning_status 无效")
        if isinstance(self.metric_definitions, list) and any(not isinstance(item, dict) for item in self.metric_definitions):
            errors.append("metric_definitions 的每项必须是 object")
        for name in ("semantic_fingerprint", "presentation_fingerprint"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                errors.append(f"{name} 必须是 string 或 null")
        return errors
