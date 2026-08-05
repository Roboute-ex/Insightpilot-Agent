"""Run built-in synthetic demo scenarios from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data, generate_multi_table_commerce_data
from insightpilot.evaluation.harness import (
    run_core_evaluation,
    run_determinism_evaluation,
    run_safety_evaluation,
)
from insightpilot.ingestion.db_loader import mask_database_url, run_database_query
from insightpilot.ingestion.file_loader import load_uploaded_file
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.planning.goal_modes import GOAL_MODE_DISPLAY_NAMES
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.reports.bundle import generate_export_bundle
from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.export import write_text_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.reports.pdf import generate_pdf_report
from insightpilot.ui.formatters import format_enum_value, format_metric_name, format_metric_text


SCENARIO_QUESTIONS = {
    "transaction": "为什么昨天某城市订单量下降？",
    "content": "新策略是否提升了内容完播率？",
    "live": "请定位直播体验异常的主要维度。",
    "multi_table": "请按客户城市分析总收入与订单量。",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run InsightPilot Agent synthetic demos.")
    parser.add_argument(
        "--scenario",
        choices=["transaction", "content", "live", "multi_table", "all"],
        default="transaction",
        help="Demo scenario to run.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Synthetic data seed.")
    parser.add_argument(
        "--data-source",
        choices=["synthetic", "file", "database"],
        default="synthetic",
        help="Data source type. Defaults to synthetic.",
    )
    parser.add_argument("--input-file", help="CSV or Excel file path for file ingestion.")
    parser.add_argument("--sheet-name", help="Excel sheet name or index for file ingestion.")
    parser.add_argument("--table-name", help="Table name for file or database ingestion.")
    parser.add_argument("--database-url", help="SQLAlchemy database URL for database ingestion.")
    parser.add_argument("--query", help="Read-only SELECT/WITH SQL query for database ingestion.")
    parser.add_argument("--question", help="Natural-language analysis question for custom data.")
    parser.add_argument("--date-column", help="Date column for custom data mapping.")
    parser.add_argument("--metric-columns", help="Comma-separated metric columns for custom data mapping.")
    parser.add_argument("--dimension-columns", help="Comma-separated dimension columns for custom data mapping.")
    parser.add_argument("--group-column", help="Group column for experiment analysis.")
    parser.add_argument("--treatment-column", help="Treatment column for causal exploration.")
    parser.add_argument("--outcome-column", help="Outcome column for causal exploration.")
    parser.add_argument(
        "--time-grain",
        choices=["day", "week", "month"],
        default="day",
        help="Time grain for custom trend analysis.",
    )
    parser.add_argument(
        "--goal-mode",
        choices=list(GOAL_MODE_DISPLAY_NAMES.keys()),
        default="auto",
        help="Analysis goal mode. Defaults to auto.",
    )
    parser.add_argument(
        "--use-langgraph",
        action="store_true",
        help="Use optional LangGraph workflow when installed; otherwise fall back automatically.",
    )
    parser.add_argument(
        "--language",
        choices=["zh-CN", "en"],
        default="zh-CN",
        help="CLI display language. Stable JSON keys always remain English.",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Human-readable text or stable machine-readable JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show workflow routes, stable identifiers, and other debugging details in text output.",
    )
    parser.add_argument("--semantic-model", default="commerce_demo", help="Allowlisted semantic model identifier.")
    parser.add_argument("--metric", help="Comma-separated allowlisted semantic metric identifiers.")
    parser.add_argument("--dimensions", help="Comma-separated allowlisted semantic dimension identifiers.")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="DIMENSION:OPERATOR:VALUE",
        help="Structured semantic filter; repeat as needed. No SQL fragments are accepted.",
    )
    parser.add_argument("--date-dimension", help="Allowlisted semantic date dimension identifier.")
    parser.add_argument("--limit", type=int, default=1000, help="Semantic query row limit, from 1 to 10000.")
    parser.add_argument("--plan-only", action="store_true", help="Compile and review the plan without executing SQL.")
    parser.add_argument("--approve-plan-id", help="Approve this exact high-risk plan identifier for read-only execution.")
    parser.add_argument(
        "--evaluation-suite",
        choices=["core", "safety", "determinism", "all"],
        help="Run a local evaluation suite and include its summary.",
    )
    parser.add_argument("--playbook", choices=[playbook.playbook_id for playbook in get_playbook_registry().list_all()])
    parser.add_argument("--list-playbooks", action="store_true", help="List built-in playbooks and exit.")
    parser.add_argument("--date-from", help="Playbook date range start date.")
    parser.add_argument("--date-to", help="Playbook date range end date.")
    parser.add_argument("--aggregation", choices=["sum", "mean", "count", "min", "max"])
    parser.add_argument("--rolling-window", type=int)
    parser.add_argument("--top-n", type=int)
    parser.add_argument("--comparison-type", choices=["previous_period", "custom"])
    parser.add_argument("--control-value")
    parser.add_argument("--treatment-value")
    parser.add_argument("--confidence-level", type=float)
    parser.add_argument("--covariates", help="Comma-separated causal covariate columns.")
    parser.add_argument("--config-in", help="Load playbook configuration or RunManifest JSON.")
    parser.add_argument("--config-out", help="Write a safe configuration JSON after the run.")
    parser.add_argument(
        "--export-format",
        help="Comma-separated exports: pdf,markdown,html,excel,manifest,bundle.",
    )
    parser.add_argument("--export-dir", default=str(PROJECT_ROOT / "reports"), help="Export directory.")
    return parser.parse_args()


def _sheet_name(value: str | None) -> str | int | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def _split_columns(value: str | None) -> list[str]:
    if not value:
        return []
    return [column.strip() for column in value.split(",") if column.strip()]


def _column_mapping_from_args(args: argparse.Namespace) -> dict[str, object] | None:
    mapping = {
        "table_name": args.table_name,
        "date_column": args.date_column,
        "metric_columns": _split_columns(args.metric_columns),
        "dimension_columns": _split_columns(args.dimension_columns),
        "group_column": args.group_column,
        "treatment_column": args.treatment_column,
        "outcome_column": args.outcome_column,
        "time_grain": args.time_grain,
    }
    if not any(value for key, value in mapping.items() if key != "time_grain"):
        return None
    return mapping


def _list_playbooks(language: str = "zh-CN") -> None:
    for playbook in get_playbook_registry().list_all():
        requirements = [
            name.removeprefix("requires_")
            for name, required in playbook.requirements.to_dict().items()
            if name.startswith("requires_") and required
        ]
        if language == "zh-CN":
            print(f"{playbook.playbook_id}\t{playbook.display_name}\t字段要求={','.join(requirements) or '无'}")
        else:
            print(f"{playbook.playbook_id}\t{playbook.display_name}\trequires={','.join(requirements) or 'none'}")


def _parse_filter(value: str) -> dict[str, Any]:
    parts = value.split(":", 2)
    if len(parts) != 3 or not all(parts[:2]):
        raise SystemExit("--filter 必须使用 DIMENSION:OPERATOR:VALUE 格式。")
    dimension_id, operator, raw_value = parts
    if operator not in {"eq", "in", "gt", "gte", "lt", "lte", "between"}:
        raise SystemExit(f"--filter 使用了不支持的操作符：{operator}")
    try:
        parsed_value = json.loads(raw_value)
    except json.JSONDecodeError:
        parsed_value = raw_value
    return {"dimension_id": dimension_id, "operator": operator, "value": parsed_value}


def _metric_request_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    metrics = _split_columns(args.metric)
    if not metrics:
        return None
    return {
        "metrics": metrics,
        "dimensions": _split_columns(args.dimensions),
        "filters": [_parse_filter(value) for value in args.filter],
        "date_dimension": args.date_dimension,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "time_grain": args.time_grain,
        "limit": args.limit,
        "execution_mode": "plan_only" if args.plan_only else "execute",
    }


def _run_evaluations(suite: str | None) -> dict[str, Any]:
    if not suite:
        return {}
    runners = {
        "core": run_core_evaluation,
        "safety": run_safety_evaluation,
        "determinism": run_determinism_evaluation,
    }
    selected = runners if suite == "all" else {suite: runners[suite]}
    return {name: runner().to_dict() for name, runner in selected.items()}


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        raise SystemExit(f"config-in file does not exist: {source}")
    try:
        values = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"config-in could not be read: {exc}") from exc
    if not isinstance(values, dict):
        raise SystemExit("config-in must contain a JSON object.")
    if any(key in values for key in ("tables", "dataframes", "raw_data")):
        raise SystemExit("config-in must not contain raw table data.")
    if "manifest_version" in values:
        try:
            return RunManifest.from_dict(values).to_dict()
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    return values


def _playbook_parameters_from_args(
    args: argparse.Namespace,
    config: dict[str, Any],
    playbook_id: str | None,
) -> dict[str, Any]:
    values = dict(config.get("playbook_parameters", {})) if isinstance(config.get("playbook_parameters"), dict) else {}
    supplied = {
        "aggregation": args.aggregation,
        "rolling_window": args.rolling_window,
        "top_n": args.top_n,
        "comparison_type": args.comparison_type,
        "control_value": args.control_value,
        "treatment_value": args.treatment_value,
        "confidence_level": args.confidence_level,
    }
    for key, value in supplied.items():
        if value is not None:
            values[key] = value
    if args.date_from or args.date_to:
        values["date_range"] = {"start": args.date_from, "end": args.date_to}
        values["current_start"] = args.date_from
        values["current_end"] = args.date_to
    if args.covariates:
        values["covariates"] = _split_columns(args.covariates)
    if args.time_grain:
        values["time_grain"] = args.time_grain
    if not playbook_id:
        return {}
    try:
        allowed = {parameter.name for parameter in get_playbook_registry().get(playbook_id).parameters}
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return {key: value for key, value in values.items() if key in allowed}


def _export_formats(value: str | None) -> list[str]:
    if not value:
        return []
    allowed = {"pdf", "markdown", "html", "excel", "manifest", "bundle"}
    values = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [item for item in values if item not in allowed]
    if invalid:
        raise SystemExit(f"Unsupported export format: {', '.join(invalid)}")
    return list(dict.fromkeys(values))


def _unique_path(directory: Path, stem: str, suffix: str, run_id: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}{suffix}"
    if not target.exists():
        return target
    target = directory / f"{stem}_{run_id[:8]}{suffix}"
    index = 2
    while target.exists():
        target = directory / f"{stem}_{run_id[:8]}_{index}{suffix}"
        index += 1
    return target


def _write_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _generate_requested_exports(
    result: dict[str, Any],
    formats: list[str],
    export_dir: Path,
    stem: str,
) -> list[Path]:
    if not formats:
        return []
    result["route_taken"] = list(dict.fromkeys([*result.get("route_taken", []), "generate_exports"]))
    if isinstance(result.get("trace"), dict):
        result["trace"]["route_taken"] = list(result["route_taken"])
    manifest_values = dict(result["run_manifest"])
    manifest_values["route_taken"] = list(result["route_taken"])
    manifest = RunManifest.from_dict(manifest_values)
    result["run_manifest"] = manifest.to_dict()
    result["export_formats"] = formats
    result["report_markdown"] = generate_markdown_report(result)
    html_report: str | None = None
    excel_bytes: bytes | None = None
    pdf_bytes: bytes | None = None
    paths: list[Path] = []

    def html_content() -> str:
        nonlocal html_report
        if html_report is None:
            html_report = generate_html_report(result, result.get("charts", []), manifest)
        return html_report

    def excel_content() -> bytes:
        nonlocal excel_bytes
        if excel_bytes is None:
            excel_bytes = generate_excel_report(result, manifest)
        return excel_bytes

    def pdf_content() -> bytes:
        nonlocal pdf_bytes
        if pdf_bytes is None:
            pdf_bytes = generate_pdf_report(result, manifest)
        return pdf_bytes

    for export_format in formats:
        if export_format == "pdf":
            paths.append(_write_bytes(_unique_path(export_dir, stem, ".pdf", manifest.run_id), pdf_content()))
        elif export_format == "markdown":
            path = _unique_path(export_dir, stem, ".md", manifest.run_id)
            paths.append(write_text_report(path, result["report_markdown"]))
        elif export_format == "html":
            path = _unique_path(export_dir, stem, ".html", manifest.run_id)
            path.write_text(html_content(), encoding="utf-8")
            paths.append(path)
        elif export_format == "excel":
            paths.append(_write_bytes(_unique_path(export_dir, stem, ".xlsx", manifest.run_id), excel_content()))
        elif export_format == "manifest":
            path = _unique_path(export_dir, stem, ".json", manifest.run_id)
            path.write_text(manifest.to_json(), encoding="utf-8")
            paths.append(path)
        elif export_format == "bundle":
            bundle = generate_export_bundle(
                result["report_markdown"], html_content(), excel_content(), manifest.to_json(), result.get("result_tables", {}), pdf_bytes=pdf_content()
            )
            paths.append(_write_bytes(_unique_path(export_dir, stem, ".zip", manifest.run_id), bundle))
    return paths


def _load_file_tables(args: argparse.Namespace) -> tuple[dict[str, object], dict[str, dict[str, object]], str]:
    if not args.input_file:
        raise SystemExit("--data-source file requires --input-file.")
    input_path = Path(args.input_file)
    if not input_path.exists():
        raise SystemExit(f"Input file does not exist: {input_path}")
    registry = TableRegistry()
    with input_path.open("rb") as file_obj:
        loaded = load_uploaded_file(
            file_obj,
            input_path.name,
            sheet_name=_sheet_name(args.sheet_name),
            table_name=args.table_name,
        )
    table_name = registry.add_table(loaded.name, loaded.dataframe, loaded.source_type, loaded.source_name)
    registry.metadata[table_name]["warnings"] = list(dict.fromkeys(registry.metadata[table_name]["warnings"] + loaded.warnings))
    return registry.to_duckdb_tables(), registry.metadata, args.question or "请对上传数据做通用趋势和结构分析。"


def _load_database_tables(args: argparse.Namespace) -> tuple[dict[str, object], dict[str, dict[str, object]], str]:
    if not args.database_url:
        raise SystemExit("--data-source database requires --database-url.")
    if not args.query:
        raise SystemExit("--data-source database requires --query.")
    result = run_database_query(args.database_url, args.query, table_name=args.table_name or "db_query_result")
    registry = TableRegistry()
    table_name = registry.add_table(result.table_name, result.dataframe, result.source_type, mask_database_url(args.database_url))
    registry.metadata[table_name]["warnings"] = list(dict.fromkeys(registry.metadata[table_name]["warnings"] + result.warnings))
    return registry.to_duckdb_tables(), registry.metadata, args.question or "请对数据库查询结果做通用趋势和结构分析。"


def _result_payload(
    scenario: str,
    result: dict[str, Any],
    report_path: Path,
    exported_paths: list[Path],
) -> dict[str, Any]:
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    query_plan = result.get("query_plan") if isinstance(result.get("query_plan"), dict) else {}
    join_plan = result.get("join_plan") if isinstance(result.get("join_plan"), dict) else {}
    reviewer = result.get("reviewer") if isinstance(result.get("reviewer"), dict) else {}
    manifest = result.get("run_manifest") if isinstance(result.get("run_manifest"), dict) else {}
    package = result.get("analysis_result_package") if isinstance(result.get("analysis_result_package"), dict) else {}
    return {
        "scenario": scenario,
        "data_source_type": result.get("data_source_type"),
        "intent": result.get("intent"),
        "goal_mode": result.get("goal_mode"),
        "goal_mode_source": result.get("goal_mode_source"),
        "workflow_backend": result.get("workflow_backend"),
        "playbook_id": selected.get("playbook_id"),
        "playbook_name": selected.get("display_name"),
        "semantic_model_id": query_plan.get("semantic_model_id"),
        "semantic_model_name": (result.get("semantic_model") or {}).get("display_name")
        if isinstance(result.get("semantic_model"), dict)
        else None,
        "query_plan_id": query_plan.get("plan_id"),
        "join_step_count": len(join_plan.get("steps", [])),
        "risk_level": query_plan.get("risk_level") or join_plan.get("risk_level") or "safe",
        "plan_review": result.get("plan_review"),
        "reviewer": reviewer,
        "run_id": manifest.get("run_id"),
        "report_path": str(report_path),
        "export_paths": [str(path) for path in exported_paths],
        "route_taken": list(result.get("route_taken", [])),
        "findings": [str(item) for item in result.get("findings", [])],
        "executive_summary": package.get("executive_summary") or result.get("summary"),
        "experiment_results": [item for item in package.get("experiment_results", []) if isinstance(item, dict)],
    }


def _print_experiment_results(payload: dict[str, Any], language: str) -> None:
    rows = payload.get("experiment_results", [])
    if not isinstance(rows, list) or not rows:
        return
    print("实验分析结果：" if language == "zh-CN" else "Experiment results:")
    for item in rows:
        metric_id = str(item.get("metric_id", ""))
        is_rate = metric_id.endswith("_rate") or metric_id in {"ctr", "cvr", "conversion_rate"}
        value = lambda number: f"{float(number or 0):.2%}" if is_rate else f"{float(number or 0):,.4g}"
        if language == "zh-CN":
            print(f"- 分析指标：{format_metric_name(metric_id)}")
            print(f"- 实验组：{value(item.get('treatment_value'))}，样本量 {int(item.get('treatment_sample_size', 0)):,}")
            print(f"- 对照组：{value(item.get('control_value'))}，样本量 {int(item.get('control_sample_size', 0)):,}")
            print(f"- lift：绝对 {value(item.get('absolute_lift'))}，相对 {float(item.get('relative_lift', 0)):.2%}")
            print(f"- p-value：{float(item.get('p_value', 1)):.6g}")
            print(f"- 95% 置信区间：[{value(item.get('confidence_interval_lower'))}, {value(item.get('confidence_interval_upper'))}]")
            print(f"- 显著性结论：{item.get('significance_conclusion')}")
        else:
            print(f"- Metric: {metric_id}")
            print(f"- Treatment: {value(item.get('treatment_value'))}, n={int(item.get('treatment_sample_size', 0)):,}")
            print(f"- Control: {value(item.get('control_value'))}, n={int(item.get('control_sample_size', 0)):,}")
            print(f"- Lift: absolute {value(item.get('absolute_lift'))}, relative {float(item.get('relative_lift', 0)):.2%}")
            print(f"- p-value: {float(item.get('p_value', 1)):.6g}")
            print(f"- 95% CI: [{value(item.get('confidence_interval_lower'))}, {value(item.get('confidence_interval_upper'))}]")
            print(f"- Significance: {item.get('significance_conclusion')}")


def _print_text_result(payload: dict[str, Any], language: str, *, verbose: bool = False) -> None:
    reviewer = payload.get("reviewer") if isinstance(payload.get("reviewer"), dict) else {}
    if language == "zh-CN":
        scenario_name = {"transaction": "交易转化异常", "content": "内容消费与实验", "live": "体验质量", "multi_table": "多表语义指标", "file": "上传文件", "database": "本地数据库"}.get(payload["scenario"], "自定义分析")
        print(f"场景：{scenario_name}")
        print(f"数据来源：{format_enum_value('data_source', payload['data_source_type'])}")
        print(f"分析目标：{format_enum_value('goal_mode', payload['goal_mode'])}")
        print(f"分析剧本：{payload['playbook_name'] or format_enum_value('playbook', payload['playbook_id']) if payload['playbook_id'] else '自动路由'}")
        print(f"质量评分：{reviewer.get('score', '未知')}")
        print(f"报告路径：{payload['report_path']}")
        for export_path in payload["export_paths"]:
            print(f"导出路径：{export_path}")
        print(f"执行摘要：{format_metric_text(payload.get('executive_summary'))}")
        _print_experiment_results(payload, language)
        print("核心发现：")
    else:
        print(f"Scenario: {payload['scenario']}")
        print(f"Data source: {payload['data_source_type']}")
        print(f"Analysis goal: {payload['goal_mode']}")
        print(f"Playbook: {payload['playbook_id'] or 'automatic routing'}")
        print(f"Workflow backend: {payload['workflow_backend']}")
        print(f"Reviewer score: {reviewer.get('score', 'unknown')}")
        print(f"Run ID: {payload['run_id']}")
        print(f"Report path: {payload['report_path']}")
        print(f"Executive summary: {payload.get('executive_summary')}")
        _print_experiment_results(payload, language)
        print("Key findings:")
    for finding in payload["findings"][:3]:
        print(f"- {format_metric_text(finding) if language == 'zh-CN' else finding}")
    if verbose:
        print(
            f"scenario={payload['scenario']} data_source={payload['data_source_type']} intent={payload['intent']} "
            f"goal_mode={payload['goal_mode']} goal_mode_source={payload['goal_mode_source']} "
            f"workflow_backend={payload['workflow_backend']} playbook={payload['playbook_id'] or 'none'} "
            f"run_id={payload['run_id']} reviewer_status={reviewer.get('status')} reviewer_score={reviewer.get('score')}"
        )
        print(f"report: {payload['report_path']}")
        for export_path in payload["export_paths"]:
            print(f"export: {export_path}")
        print(f"route_taken: {', '.join(payload['route_taken'])}")


def main() -> None:
    args = parse_args()
    if args.list_playbooks:
        _list_playbooks(args.language)
        return
    config = _load_config(args.config_in)
    report_dir = Path(args.export_dir)
    column_mapping = _column_mapping_from_args(args)
    if column_mapping is None and isinstance(config.get("column_mapping"), dict):
        column_mapping = config["column_mapping"]
    playbook_id = args.playbook or config.get("playbook_id")
    export_formats = _export_formats(args.export_format)
    metric_request = _metric_request_from_args(args)
    evaluations = _run_evaluations(args.evaluation_suite)
    effective_goal_mode = args.goal_mode
    if effective_goal_mode == "auto" and config.get("goal_mode") in GOAL_MODE_DISPLAY_NAMES:
        effective_goal_mode = str(config["goal_mode"])
    configured_question = str(config.get("question") or "")
    if args.data_source == "file":
        tables, table_metadata, question = _load_file_tables(args)
        scenarios = ["file"]
        data_source_type = "uploaded_files"
    elif args.data_source == "database":
        tables, table_metadata, question = _load_database_tables(args)
        scenarios = ["database"]
        data_source_type = "database"
    else:
        tables = {}
        table_metadata = None
        scenarios = SCENARIO_QUESTIONS.keys() if args.scenario == "all" else [args.scenario]
        question = ""
        data_source_type = "synthetic"
    output_runs: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_tables = tables
        effective_playbook_id = str(playbook_id) if playbook_id else None
        effective_metric_request = metric_request
        if args.data_source == "synthetic":
            if scenario == "multi_table":
                scenario_tables = generate_multi_table_commerce_data(seed=args.seed)
                effective_playbook_id = effective_playbook_id or "semantic_metric_query"
                effective_metric_request = effective_metric_request or {
                    "metrics": ["total_revenue", "order_count"],
                    "dimensions": ["customer_city"],
                    "filters": [],
                    "date_dimension": None,
                    "date_from": args.date_from,
                    "date_to": args.date_to,
                    "time_grain": args.time_grain,
                    "limit": args.limit,
                    "execution_mode": "plan_only" if args.plan_only else "execute",
                }
            else:
                scenario_tables = generate_all_demo_data(seed=args.seed)
        playbook_parameters = _playbook_parameters_from_args(args, config, effective_playbook_id)
        scenario_question = args.question or configured_question or question or SCENARIO_QUESTIONS[scenario]
        result = run_agent_analysis(
            scenario_question,
            scenario_tables,
            goal_mode=effective_goal_mode,
            use_langgraph=args.use_langgraph,
            data_source_type=data_source_type,
            table_metadata=table_metadata,
            column_mapping=column_mapping,
            playbook_id=effective_playbook_id,
            playbook_parameters=playbook_parameters,
            plan_only=args.plan_only,
            approved_plan_id=args.approve_plan_id,
            semantic_model_id=args.semantic_model,
            metric_request=effective_metric_request,
        )
        run_id = str(result["run_manifest"]["run_id"])
        report_path = write_text_report(
            _unique_path(report_dir, f"{scenario}_report", ".md", run_id),
            result["report_markdown"],
        )
        selected = result.get("selected_playbook") or {}
        export_stem = f"{selected.get('playbook_id') or scenario}_{run_id[:8]}"
        try:
            exported_paths = _generate_requested_exports(result, export_formats, report_dir, export_stem)
        except Exception as exc:
            exported_paths = []
            if args.output_format == "text":
                print(f"导出警告：{exc}" if args.language == "zh-CN" else f"Export warning: {exc}")
        if args.config_out:
            config_path = Path(args.config_out)
            if config_path.exists():
                config_path = _unique_path(config_path.parent, config_path.stem, config_path.suffix or ".json", run_id)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(result["run_manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
            exported_paths.append(config_path)
        payload = _result_payload(str(scenario), result, report_path, exported_paths)
        output_runs.append(payload)
        if args.output_format == "text":
            _print_text_result(payload, args.language, verbose=args.verbose)
    if args.output_format == "json":
        print(
            json.dumps(
                {"schema_version": "0.6", "runs": output_runs, "evaluations": evaluations},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    elif evaluations:
        for name, evaluation in evaluations.items():
            label = "评估套件" if args.language == "zh-CN" else "Evaluation suite"
            print(f"{label}={name} overall_score={evaluation['overall_score']:.6f} passed={evaluation['passed']}")


if __name__ == "__main__":
    main()
