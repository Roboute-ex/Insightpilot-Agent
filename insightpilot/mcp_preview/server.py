"""Dependency-free MCP preview that preserves stable English schemas."""

from __future__ import annotations

from typing import Any

import pandas as pd

from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.evaluation.harness import run_core_evaluation, run_determinism_evaluation, run_safety_evaluation
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.compiler import MetricCompiler, execute_query_plan
from insightpilot.semantic.query import MetricRequest


class MCPPreviewError(ValueError):
    """Raised when the preview surface rejects an unsafe or unknown call."""


_METRIC_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "semantic_model_id": {"type": "string"},
        "metrics": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "array", "items": {"type": "object"}},
        "date_dimension": {"type": ["string", "null"]},
        "date_from": {"type": ["string", "null"]},
        "date_to": {"type": ["string", "null"]},
        "time_grain": {"enum": ["day", "week", "month"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000},
    },
    "required": ["metrics"],
    "additionalProperties": False,
}


class MCPPreview:
    """Expose semantic planning through bounded tool calls, never arbitrary SQL."""

    def list_tools(self) -> list[dict[str, Any]]:
        execute_schema = {
            **_METRIC_REQUEST_SCHEMA,
            "properties": {
                **_METRIC_REQUEST_SCHEMA["properties"],
                "authorized": {"type": "boolean"},
                "approved_plan_id": {"type": ["string", "null"]},
            },
            "required": ["metrics", "authorized"],
        }
        return [
            {
                "name": "list_semantic_models",
                "description": "List allowlisted semantic models. 列出允许使用的语义模型。",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "preview_metric_query",
                "description": "Compile a read-only metric plan. 编译安全只读指标计划，不执行查询。",
                "inputSchema": _METRIC_REQUEST_SCHEMA,
            },
            {
                "name": "execute_metric_query",
                "description": "Execute an explicitly authorized read-only plan. 明确授权后执行只读指标计划。",
                "inputSchema": execute_schema,
            },
            {
                "name": "run_evaluation_suite",
                "description": "Run a local synthetic evaluation suite. 运行本地模拟评估套件。",
                "inputSchema": {
                    "type": "object",
                    "properties": {"suite": {"enum": ["core", "safety", "determinism"]}},
                    "required": ["suite"],
                    "additionalProperties": False,
                },
            },
        ]

    def list_resources(self) -> list[dict[str, str]]:
        return [
            {
                "uri": "insightpilot://semantic/catalog",
                "name": "semantic_catalog",
                "description": "Validated semantic catalog metadata. 已校验语义目录元数据。",
            }
        ]

    def read_resource(self, uri: str) -> dict[str, Any]:
        if uri != "insightpilot://semantic/catalog":
            raise MCPPreviewError(f"Unknown resource: {uri}")
        return load_builtin_catalog().to_dict()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        tables: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        if "sql" in arguments or "query" in arguments:
            raise MCPPreviewError("MCP preview 不接受任意 SQL 或查询文本。")
        if name == "list_semantic_models":
            if arguments:
                raise MCPPreviewError("list_semantic_models 不接受参数。")
            catalog = load_builtin_catalog()
            return {"models": [model.to_dict() for model in catalog.list_models()]}
        if name == "run_evaluation_suite":
            allowed = {"suite"}
            self._reject_unknown(arguments, allowed)
            runners = {
                "core": run_core_evaluation,
                "safety": run_safety_evaluation,
                "determinism": run_determinism_evaluation,
            }
            suite = str(arguments.get("suite", ""))
            if suite not in runners:
                raise MCPPreviewError(f"Unknown evaluation suite: {suite}")
            return runners[suite]().to_dict()
        if name not in {"preview_metric_query", "execute_metric_query"}:
            raise MCPPreviewError(f"Unknown tool: {name}")

        allowed = set(_METRIC_REQUEST_SCHEMA["properties"])
        if name == "execute_metric_query":
            allowed.update({"authorized", "approved_plan_id"})
        self._reject_unknown(arguments, allowed)
        model_id = str(arguments.get("semantic_model_id", "commerce_demo"))
        model = load_builtin_catalog().get(model_id)
        request_values = {key: value for key, value in arguments.items() if key in _METRIC_REQUEST_SCHEMA["properties"]}
        request_values.pop("semantic_model_id", None)
        request_values["execution_mode"] = "plan_only" if name == "preview_metric_query" else "execute"
        plan = MetricCompiler(model).compile(MetricRequest.from_dict(request_values))
        if name == "preview_metric_query":
            return {"query_plan": plan.to_dict(), "executed": False}
        if arguments.get("authorized") is not True:
            raise MCPPreviewError("execute_metric_query 需要 authorized=true 的明确授权。")
        frame, review = execute_query_plan(
            plan,
            tables or generate_multi_table_commerce_data(seed=42),
            approved_plan_id=arguments.get("approved_plan_id"),
        )
        return {
            "query_plan": plan.to_dict(),
            "plan_review": review.to_dict(),
            "executed": frame is not None,
            "rows": frame.to_dict(orient="records") if frame is not None else [],
        }

    @staticmethod
    def _reject_unknown(arguments: dict[str, Any], allowed: set[str]) -> None:
        unknown = sorted(set(arguments) - allowed)
        if unknown:
            raise MCPPreviewError("Unsupported arguments: " + ", ".join(unknown))
