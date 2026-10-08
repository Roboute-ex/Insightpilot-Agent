"""Small immutable run history; full results stay in the existing session cache."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any
from uuid import uuid4

from insightpilot.performance import MemoryBudgetExceeded

HISTORY_SCHEMA_VERSION = "1.0"
MAX_HISTORY_NODES = 10
MAX_SUMMARY_ROWS = 128


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _scalar(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise ValueError("历史只能保存JSON标量和有界配置，不能保存数据表或执行对象。")


def _plain(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        raise ValueError("历史配置嵌套过深。")
    if isinstance(value, dict):
        if len(value) > 256:
            raise ValueError("历史配置字段数量过多。")
        return {str(k): _plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise ValueError("历史配置列表过长。")
        return [_plain(v, depth + 1) for v in value]
    return _scalar(value)


@dataclass(frozen=True)
class RunNode:
    thread_id: str
    node_id: str
    parent_run_id: str | None
    run_id: str
    dataset_revision: str
    analysis_config_snapshot: str
    semantic_fingerprint: str
    result_ref: str
    result_summary: str
    comparison_context: str
    created_at: str
    status: str

    @property
    def config(self) -> dict[str, Any]:
        return json.loads(self.analysis_config_snapshot)

    @property
    def summary(self) -> dict[str, Any]:
        return json.loads(self.result_summary)

    @property
    def context(self) -> dict[str, Any]:
        return json.loads(self.comparison_context)

    @property
    def estimated_bytes(self) -> int:
        # Include Python Unicode/container overhead, not merely UTF-8 wire bytes.
        from insightpilot.performance import estimate_size_bytes
        return estimate_size_bytes(self)


def _summary(result: dict[str, Any], definitions: list[dict[str, Any]]) -> dict[str, Any]:
    package = result.get("analysis_result_package") or {}
    rows = []
    seen = set()
    defined_metrics = {str(d.get("metric_id", d.get("metric_name", ""))) for d in definitions}
    comparisons = package.get("metric_comparisons") or []
    ordered = sorted(comparisons, key=lambda x: x.get("baseline_period") != "前 7 日均值")
    for item in ordered:
        metric = str(item.get("metric_id", ""))
        if metric and metric in defined_metrics and metric not in seen:
            seen.add(metric)
            rows.append({"metric_id": metric, "value": _scalar(item.get("current_value")),
                         "unit": item.get("unit", "未确认"), "group": {},
                         "window": item.get("current_period"), "baseline": item.get("baseline_period")})
        if len(rows) >= MAX_SUMMARY_ROWS:
            break
    if not rows:
        parameters = result.get("playbook_parameters") or {}
        mapping = result.get("column_mapping") or {}
        metric = str(parameters.get("metric") or next(iter(mapping.get("metric_columns") or []), ""))
        tables = result.get("result_tables") or {}
        frame = tables.get("period_summary")
        if frame is not None and {"comparison_period", "metric_value"}.issubset(frame.columns):
            current = frame.loc[frame["comparison_period"] == "current", "metric_value"]
            if len(current) == 1 and metric:
                definition = next((d for d in definitions if d.get("metric_id", d.get("metric_name")) == metric), {})
                rows.append({"metric_id": metric, "value": _scalar(current.iloc[0]),
                             "unit": definition.get("unit", "未确认"), "group": {}})
        frame = tables.get("semantic_metric_result")
        if frame is not None and len(frame) <= MAX_SUMMARY_ROWS:
            ids = [str(d.get("metric_id", "")) for d in definitions if d.get("metric_id") in frame.columns]
            dimensions = [str(c) for c in frame.columns if c not in ids]
            if len(frame) * max(1, len(ids)) <= MAX_SUMMARY_ROWS:
                for record in frame.to_dict(orient="records"):
                    for metric_id in ids:
                        definition = next(d for d in definitions if d.get("metric_id") == metric_id)
                        rows.append({"metric_id": metric_id, "value": _scalar(record[metric_id]),
                                     "unit": definition.get("unit", "未确认"),
                                     "group": {c: _scalar(record[c]) for c in dimensions}})
    if not rows:
        exploration = package.get("metadata", {}).get("exploration") or {}
        tables = result.get("result_tables") or {}
        totals, cells = tables.get("exploration_totals"), tables.get("exploration_cells")
        metric = str((exploration.get("metric_card") or {}).get("metric_id") or "")
        definition = next((d for d in definitions if d.get("metric_id") == metric), {})
        if totals is not None and metric and definition:
            overall = totals.loc[totals["scope"] == "all"]
            if len(overall) == 1:
                rows.append({"metric_id": metric, "value": _scalar(overall.iloc[0]["metric_value"]), "unit": definition.get("unit", "未确认"), "group": {"_scope": "all"}})
            if cells is not None and len(cells) <= MAX_SUMMARY_ROWS - len(rows):
                for record in cells.to_dict(orient="records"):
                    group = {"_scope": "cell", "row_key": str(record["row_key"])}
                    if record.get("column_key"):
                        group["column_key"] = str(record["column_key"])
                    rows.append({"metric_id": metric, "value": _scalar(record["metric_value"]), "unit": definition.get("unit", "未确认"), "group": group})
    return {"rows": rows, "summary_scope": "已计算的有限聚合摘要；不代表完整结果表",
            "text": str(result.get("summary") or package.get("executive_summary") or "")[:2000],
            "evidence_count": len(package.get("evidence") or []),
            "table_rows": {str(k): int(len(v)) for k, v in (result.get("result_tables") or {}).items()}}


def _effective_playbook(result: dict[str, Any], config: dict[str, Any]) -> str | None:
    """Use the successful run's method; frozen request metadata is a fallback."""
    if result.get("execution_status") == "COMPLETED":
        selected = result.get("selected_playbook") or {}
        executed_id = selected.get("playbook_id")
        if isinstance(executed_id, str) and executed_id and executed_id not in {"auto", "auto_recommended"}:
            return None if executed_id == "__legacy__" else executed_id
        manifest = result.get("run_manifest") or {}
        for advice in (result.get("analysis_advice") or {}, manifest.get("analysis_advice") or {}):
            effective = advice.get("effective_method") or {}
            if effective.get("kind") == "route" and effective.get("id") == "legacy":
                return None
            if effective.get("kind") == "playbook" and effective.get("id"):
                return effective["id"]
        if "playbook_id" in manifest and manifest["playbook_id"] not in {"auto", "auto_recommended"}:
            return None if manifest["playbook_id"] == "__legacy__" else manifest["playbook_id"]
    # None is a meaningful frozen value: the original automatic workflow route.
    # Older explicit selections and the legacy None route remain compatible.
    method = config.get("effective_playbook_id") if "effective_playbook_id" in config else config.get("playbook_id")
    # An unresolved auto sentinel is retained so comparison can refuse it.
    return None if method == "__legacy__" else method


def comparison_context(result: dict[str, Any], config: dict[str, Any], dataset_id: str,
                       revision: str, schema: dict[str, Any]) -> dict[str, Any]:
    mapping = result.get("column_mapping") or config.get("column_mapping") or {}
    params = result.get("playbook_parameters") or config.get("parameters") or {}
    package = result.get("analysis_result_package") or {}
    definitions = result.get("metric_definitions") or []
    request = result.get("metric_request") or {}
    periods = (result.get("playbook_result") or {}).get("metadata", {}).get("periods")
    exploration = params.get("exploration_request") or {}
    return _plain({"dataset_id": dataset_id, "dataset_revision": str(revision),
        "schema": schema, "definitions": definitions,
        "dimensions": [exploration[k] for k in ("row_dimension", "column_dimension") if exploration.get(k)] if exploration else request.get("dimensions") or ([params["dimension"]] if params.get("dimension") else mapping.get("dimension_columns", [])),
        "filters": exploration.get("filters", []) if exploration else (config.get("parameters") or {}).get("filters", request.get("filters", params.get("filters", []))),
        "date_column": mapping.get("date_column") or request.get("date_dimension"),
        "timezone": mapping.get("timezone", "未确认"),
        "time_grain": exploration.get("time_grain") if exploration else request.get("time_grain") or params.get("time_grain", mapping.get("time_grain", "day")),
        "window": {"periods": periods,
            **({"exploration": {k: exploration.get(k) for k in ("date_from", "date_to")}} if exploration else {}),
            "parameters": {k: params.get(k) for k in ("current_start", "current_end", "previous_start", "previous_end", "date_range", "target_date", "date_from", "date_to") if params.get(k) is not None},
            "semantic": {k: request.get(k) for k in ("date_from", "date_to") if request.get(k) is not None},
            "computed": sorted({(str(x.get("current_period")), str(x.get("baseline_period"))) for x in package.get("metric_comparisons", [])}),
            "definitions": [{"metric_id":d.get("metric_id"),"time_range":d.get("time_range"),"baseline":d.get("comparison_baseline")} for d in definitions]},
        "method": {"goal": result.get("goal_mode"), "playbook": _effective_playbook(result, config),
                   "aggregation": params.get("aggregation", mapping.get("aggregation")),
                   **({"exploration": {k: exploration.get(k) for k in ("kind", "field", "distribution_type")}} if exploration else {}),
                   "experiments": [{k: e.get(k) for k in ("metric_id", "method", "statistical_unit", "control_group", "treatment_group")} for e in package.get("experiment_results", [])]},
        "groups": {k: params.get(k) for k in ("control_value", "treatment_value", "confidence_level")},
        "execution_status": result.get("execution_status", "NEEDS_INPUT")})


class AnalysisThread:
    """At most ten JSON-only nodes; its budget is reserved from result_max_bytes."""
    def __init__(self, max_bytes: int = 512 * 1024, max_nodes: int = MAX_HISTORY_NODES):
        if not 1 <= max_nodes <= MAX_HISTORY_NODES or max_bytes < 0:
            raise ValueError("历史条目或内存预算无效。")
        self.thread_id = str(uuid4())
        self.max_bytes = max_bytes
        self.max_nodes = max_nodes
        self.nodes: list[RunNode] = []
        self.active_node_id: str | None = None
        self.dataset_identity: tuple[str, str] | None = None
        self.request_node_id: str | None = None
        self.parent_run_id: str | None = None

    @property
    def size_bytes(self) -> int:
        return sum(n.estimated_bytes for n in self.nodes)

    def bind_dataset(self, dataset_id: str, revision: str) -> None:
        identity = (dataset_id, str(revision))
        if self.dataset_identity is not None and identity != self.dataset_identity:
            self.clear()
        self.dataset_identity = identity

    def clear(self) -> None:
        self.nodes.clear()
        self.active_node_id = self.request_node_id = self.parent_run_id = None
        self.dataset_identity = None
        self.thread_id = str(uuid4())

    def get(self, node_id: str) -> RunNode:
        node = next((n for n in self.nodes if n.node_id == node_id), None)
        if node is None:
            raise ValueError("此历史节点不属于当前会话或已过期。")
        return node

    def select(self, node_id: str) -> RunNode:
        node = self.get(node_id)
        self.active_node_id = node.node_id
        self.request_node_id = None
        return node

    def begin_request(self, parent_run_id: str | None = None) -> str:
        if parent_run_id is not None and not any(n.run_id == parent_run_id for n in self.nodes):
            raise ValueError("父运行不属于当前会话历史。")
        self.parent_run_id = parent_run_id
        self.request_node_id = str(uuid4())
        return self.request_node_id

    def add(self, result: dict[str, Any], config: dict[str, Any], *, dataset_id: str,
            revision: str, schema: dict[str, Any], node_id: str | None = None) -> RunNode:
        self.bind_dataset(dataset_id, revision)
        run_id = str((result.get("run_manifest") or {}).get("run_id") or "")
        if not run_id:
            raise ValueError("历史需要真实运行编号。")
        existing = next((n for n in self.nodes if n.run_id == run_id), None)
        if existing:
            self.active_node_id = existing.node_id
            self.request_node_id = None
            return existing
        if node_id is not None and node_id != self.request_node_id:
            raise ValueError("旧任务与当前分支不一致，未采纳历史结果。")
        definitions = result.get("metric_definitions") or []
        context = comparison_context(result, config, dataset_id, revision, schema)
        node = RunNode(self.thread_id, node_id or str(uuid4()), self.parent_run_id, run_id,
            str(revision), _json(_plain(config)), str(result.get("semantic_fingerprint", "")), run_id,
            _json(_summary(result, definitions)), _json(context),
            str((result.get("run_manifest") or {}).get("created_at") or datetime.now(timezone.utc).isoformat()),
            str(result.get("execution_status", "NEEDS_INPUT")))
        if node.estimated_bytes > self.max_bytes:
            raise MemoryBudgetExceeded("历史元数据超过从现有结果预算预留的空间；完整分析结果仍可使用。")
        while self.nodes and (len(self.nodes) >= self.max_nodes or self.size_bytes + node.estimated_bytes > self.max_bytes):
            self.nodes.pop(0)
        self.nodes.append(node)
        self.active_node_id = node.node_id
        self.request_node_id = None
        return node

    def result_available(self, node: RunNode, result: dict[str, Any] | None) -> bool:
        if node.thread_id != self.thread_id or node not in self.nodes:
            return False
        return bool(result and str((result.get("run_manifest") or {}).get("run_id")) == node.result_ref)

    def export_json(self) -> str:
        def redact(value: Any, key: str = "") -> Any:
            if any(term in key.lower() for term in ("password", "secret", "token", "path", "connection", "query", "sql")) or key in {"question", "value", "values", "control_value", "treatment_value", "original_request", "notes"}:
                return {"requires_input": True}
            if isinstance(value, dict):
                return {k: redact(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v, key) for v in value]
            return value
        return _json({"schema_version": HISTORY_SCHEMA_VERSION, "nodes": [{
            "node_id": n.node_id, "parent_run_id": n.parent_run_id, "run_id": n.run_id,
            "status": n.status, "config": redact(n.config),
            "summary": {"evidence_count": n.summary["evidence_count"], "table_rows": n.summary["table_rows"]},
            "requires_input": True} for n in self.nodes]})


def validate_history_json(content: str) -> dict[str, Any]:
    """Validate a portable configuration document without adopting result references."""
    if not isinstance(content, str) or len(content.encode("utf-8")) > 512 * 1024:
        raise ValueError("历史JSON超过512KiB或类型无效。")
    def unique(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("历史JSON包含重复字段。")
            output[key] = value
        return output
    try:
        value = json.loads(content, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非有限JSON值")))
    except RecursionError as exc:
        raise ValueError("历史JSON嵌套过深。") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "nodes"} or value["schema_version"] != HISTORY_SCHEMA_VERSION:
        raise ValueError("历史JSON版本或schema不兼容。")
    nodes = value["nodes"]
    if not isinstance(nodes, list) or len(nodes) > MAX_HISTORY_NODES:
        raise ValueError("历史节点数不合法。")
    seen_nodes, seen_runs = set(), set()
    for node in nodes:
        required = {"node_id", "parent_run_id", "run_id", "status", "config", "summary", "requires_input"}
        if not isinstance(node, dict) or set(node) != required or not isinstance(node["config"], dict) or node["requires_input"] is not True:
            raise ValueError("历史节点schema不合法；导入不能授权或恢复结果。")
        for key in ("node_id", "run_id", "status"):
            if not isinstance(node[key], str) or not 0 < len(node[key]) <= 128:
                raise ValueError("历史节点标识无效。")
        if node["status"] not in {"COMPLETED", "FAILED", "NEEDS_INPUT", "UNSUPPORTED", "INVALID_INPUT", "PLANNED", "AWAITING_APPROVAL", "PREVIEW", "WAITING_APPROVAL", "CANCELLED", "REJECTED", "BLOCKED"}:
            raise ValueError("历史执行状态不合法。")
        summary = node["summary"]
        if not isinstance(summary, dict) or set(summary) != {"evidence_count", "table_rows"}:
            raise ValueError("历史摘要schema不合法。")
        if type(summary["evidence_count"]) is not int or summary["evidence_count"] < 0 or not isinstance(summary["table_rows"], dict):
            raise ValueError("历史摘要计数不合法。")
        if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in summary["table_rows"].items()):
            raise ValueError("历史摘要表行数不合法。")
        if node["node_id"] in seen_nodes or node["run_id"] in seen_runs:
            raise ValueError("历史节点标识重复。")
        # Evicted parents may be absent; never accept forward references/cycles.
        parent = node["parent_run_id"]
        if parent is not None and (not isinstance(parent, str) or parent == node["run_id"] or len(parent) > 128):
            raise ValueError("历史父节点引用无效。")
        seen_nodes.add(node["node_id"]); seen_runs.add(node["run_id"])
        _plain(node)
    all_runs = {n["run_id"] for n in nodes}
    prior = set()
    for node in nodes:
        if node["parent_run_id"] in all_runs and node["parent_run_id"] not in prior:
            raise ValueError("历史引用关系包含前向引用或循环。")
        prior.add(node["run_id"])
    return value


def compare_runs(left: RunNode, right: RunNode) -> dict[str, Any]:
    """Compare finite aggregate summaries by keys, never by row position or causality."""
    a, b = left.context, right.context
    reasons, differences = [], []
    if left.thread_id != right.thread_id:
        reasons.append("两个运行不属于同一会话历史。")
    for key, label in (("dataset_id", "数据集身份"), ("dataset_revision", "数据版本"), ("schema", "字段结构"),
                       ("dimensions", "维度"), ("filters", "过滤条件"), ("date_column", "日期字段"),
                       ("timezone", "时区"), ("time_grain", "时间粒度"), ("method", "统计方法"), ("groups", "实验分组或方向")):
        if a.get(key) != b.get(key):
            reasons.append(label + "不同，不直接相减。")
            differences.append({"field": key, "left": a.get(key), "right": b.get(key)})
    for field, label in (("dataset_id", "数据集身份"), ("dataset_revision", "数据版本"), ("schema", "字段结构")):
        if not a.get(field) or not b.get(field):
            reasons.append(label + "未记录，无法认证可比性。")
    for side, context in (("A", a), ("B", b)):
        if (context.get("method") or {}).get("playbook") in {"auto", "auto_recommended"}:
            reasons.append(f"运行{side}未记录自动推荐后实际执行的分析方法，无法认证可比性。")
    if a.get("execution_status") != "COMPLETED" or b.get("execution_status") != "COMPLETED":
        reasons.append("仅成功完成的分析可比较数值。")
    defs_a = {d.get("metric_id", d.get("metric_name")): d for d in a.get("definitions", [])}
    defs_b = {d.get("metric_id", d.get("metric_name")): d for d in b.get("definitions", [])}
    if not defs_a or not defs_b or set(defs_a) != set(defs_b):
        reasons.append("指标口径缺失或指标集合不同。")
    semantic_fields = ("definition_version", "metric_version", "unit", "numerator", "denominator", "aggregation",
        "deduplication_key", "dedup_key", "statistical_unit", "date_column", "timezone", "valid_sample",
        "eligibility", "null_policy", "zero_denominator_policy", "additivity", "expression", "formula", "scope", "table_name", "grain", "business_meaning", "model_id", "model_computation_fingerprint")
    for metric in set(defs_a) & set(defs_b):
        for field in semantic_fields:
            if defs_a[metric].get(field) != defs_b[metric].get(field):
                reasons.append(f"{metric}的{field}口径不同。")
        for side, definition in (("A", defs_a[metric]), ("B", defs_b[metric])):
            for required in ("metric_id", "definition_version", "unit", "aggregation", "statistical_unit", "timezone", "scope", "expression"):
                value = definition.get(required)
                if value is None or value == "" or (isinstance(value, str) and value in {"未确认", "未声明", "unknown", "unconfirmed"}):
                    reasons.append(f"运行{side}的{metric}缺少已明确的{required}，无法认证可比性。")
            for required in ("date_column", "deduplication_key", "null_policy", "zero_denominator_policy"):
                if required not in definition:
                    reasons.append(f"运行{side}的{metric}未声明{required}策略。")
    window_differs = a.get("window") != b.get("window")
    if window_differs:
        differences.append({"field": "window", "left": a.get("window"), "right": b.get("window")})
    status = "not_comparable" if reasons else "context_differs" if window_differs else "comparable"
    for node in (left, right):
        unknown_rows = {r.get("metric_id") for r in node.summary.get("rows", [])} - set(defs_a) - set(defs_b)
        if unknown_rows:
            reasons.append("聚合摘要包含未声明口径的指标：" + "、".join(sorted(map(str,unknown_rows))))
            status = "not_comparable"
    rows = []
    if not reasons:
        def indexed(node):
            output = {}
            for row in node.summary.get("rows", []):
                key = (row["metric_id"], _json(row.get("group", {})))
                if key in output:
                    raise ValueError("聚合摘要的维度键重复，不能按行位置比较。")
                output[key] = row
            return output
        try:
            x, y = indexed(left), indexed(right)
            for key in sorted(set(x) | set(y)):
                r1, r2 = x.get(key), y.get(key)
                v1, v2 = (r1 or {}).get("value"), (r2 or {}).get("value")
                definition = defs_a.get(key[0], {})
                unit = definition.get("unit", (r1 or r2 or {}).get("unit", "未确认"))
                ratio = unit in {"比例", "ratio", "percent", "%"}
                valid = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (v1, v2))
                delta = (v2 - v1) if valid else None
                relative = (v2 - v1) / v1 if valid and v1 != 0 else None
                note = "仅描述性运行差异，不是显著性检验或因果效果。"
                if not valid: note = "一侧分组缺失或值未定义，未补0。"
                elif v1 == 0: note = "运行A为0，相对变化未定义。" + note
                if window_differs: note = "时间窗口/基准不同；" + note
                rows.append({"metric_id": key[0], "definition_version": definition.get("definition_version", definition.get("metric_version", "未确认")),
                    "group": json.loads(key[1]), "run_a": v1, "run_b": v2,
                    "absolute_change": delta * 100 if delta is not None and ratio else delta,
                    "relative_change": relative, "unit": "百分点" if ratio else unit, "note": note})
        except ValueError as exc:
            reasons.append(str(exc)); status = "not_comparable"; rows = []
    if not rows and not reasons:
        reasons.append("没有共同支持的有限聚合摘要；完整表未被复制或按行相减。")
        status = "not_comparable"
    return {"status": status, "reasons": reasons, "configuration_differences": differences,
            "run_a": left.run_id, "run_b": right.run_id, "rows": rows,
            "notice": "运行差异仅供描述性复核，不替代显著性检验或因果识别。"}
