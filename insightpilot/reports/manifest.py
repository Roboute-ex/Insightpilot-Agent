"""JSON-serializable run manifest for reproducible analysis configuration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePath
from typing import Any

import pandas as pd


CURRENT_MANIFEST_VERSION = "1.0"


def _safe_string(value: str, key: str = "") -> str:
    lowered = key.lower()
    if any(term in lowered for term in ("password", "passwd", "token", "secret", "api_key", "credential")):
        return "***"
    masked = re.sub(r"(://[^:/@\s]+:)[^@/\s]+(@)", r"\1***\2", value)
    if any(term in lowered for term in ("path", "file", "source_name")) and (re.match(r"^[A-Za-z]:[\\/]", masked) or masked.startswith("/")):
        return PurePath(masked).name
    return masked


def sanitize_manifest_value(value: Any, key: str = "") -> Any:
    if isinstance(value, pd.DataFrame):
        return {
            "row_count": int(len(value)),
            "column_count": int(len(value.columns)),
            "columns": [str(column) for column in value.columns],
        }
    if isinstance(value, dict):
        return {str(item_key): sanitize_manifest_value(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_manifest_value(item, key) for item in value]
    if isinstance(value, str):
        return _safe_string(value, key)
    if hasattr(value, "item"):
        try:
            return value.item()
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
    caveats: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_manifest_value(asdict(self))

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "RunManifest":
        if not isinstance(values, dict):
            raise ValueError("manifest 必须是 JSON object。")
        field_names = cls.__dataclass_fields__.keys()
        missing = [name for name in field_names if name not in values and name not in {"caveats", "errors"}]
        if missing:
            raise ValueError(f"manifest 缺少字段：{', '.join(missing)}")
        manifest = cls(**{key: values[key] for key in field_names if key in values})
        errors = manifest.validate()
        if errors:
            raise ValueError("manifest 校验失败：" + "；".join(errors))
        return manifest

    @classmethod
    def from_json(cls, content: str) -> "RunManifest":
        try:
            values = json.loads(content)
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
        return errors
