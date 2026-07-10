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
from insightpilot.data.synthetic import generate_all_demo_data
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


SCENARIO_QUESTIONS = {
    "transaction": "为什么昨天某城市订单量下降？",
    "content": "新策略是否提升了内容完播率？",
    "live": "请定位直播体验异常的主要维度。",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run InsightPilot Agent synthetic demos.")
    parser.add_argument(
        "--scenario",
        choices=["transaction", "content", "live", "all"],
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
        help="Comma-separated exports: markdown,html,excel,manifest,bundle.",
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


def _list_playbooks() -> None:
    for playbook in get_playbook_registry().list_all():
        requirements = [
            name.removeprefix("requires_")
            for name, required in playbook.requirements.to_dict().items()
            if name.startswith("requires_") and required
        ]
        print(f"{playbook.playbook_id}\t{playbook.display_name}\trequires={','.join(requirements) or 'none'}")


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
    allowed = {"markdown", "html", "excel", "manifest", "bundle"}
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

    for export_format in formats:
        if export_format == "markdown":
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
                result["report_markdown"], html_content(), excel_content(), manifest.to_json(), result.get("result_tables", {})
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


def main() -> None:
    args = parse_args()
    if args.list_playbooks:
        _list_playbooks()
        return
    config = _load_config(args.config_in)
    report_dir = Path(args.export_dir)
    column_mapping = _column_mapping_from_args(args)
    if column_mapping is None and isinstance(config.get("column_mapping"), dict):
        column_mapping = config["column_mapping"]
    playbook_id = args.playbook or config.get("playbook_id")
    playbook_parameters = _playbook_parameters_from_args(args, config, str(playbook_id) if playbook_id else None)
    export_formats = _export_formats(args.export_format)
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
        tables = generate_all_demo_data(seed=args.seed)
        table_metadata = None
        scenarios = SCENARIO_QUESTIONS.keys() if args.scenario == "all" else [args.scenario]
        question = ""
        data_source_type = "synthetic"
    for scenario in scenarios:
        scenario_question = args.question or configured_question or question or SCENARIO_QUESTIONS[scenario]
        result = run_agent_analysis(
            scenario_question,
            tables,
            goal_mode=effective_goal_mode,
            use_langgraph=args.use_langgraph,
            data_source_type=data_source_type,
            table_metadata=table_metadata,
            column_mapping=column_mapping,
            playbook_id=str(playbook_id) if playbook_id else None,
            playbook_parameters=playbook_parameters,
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
            print(f"export_warning={exc}")
        if args.config_out:
            config_path = Path(args.config_out)
            if config_path.exists():
                config_path = _unique_path(config_path.parent, config_path.stem, config_path.suffix or ".json", run_id)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(result["run_manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
            exported_paths.append(config_path)
        reviewer = result["reviewer"]
        print(
            f"scenario={scenario} data_source={result['data_source_type']} intent={result['intent']} goal_mode={result['goal_mode']} "
            f"goal_mode_source={result['goal_mode_source']} workflow_backend={result['workflow_backend']} "
            f"playbook={selected.get('playbook_id') or 'none'} run_id={run_id} "
            f"reviewer_status={reviewer['status']} reviewer_score={reviewer['score']}"
        )
        print(f"report: {report_path}")
        for export_path in exported_paths:
            print(f"export: {export_path}")
        print(f"route_taken: {', '.join(result['route_taken'])}")
        for finding in result["findings"][:3]:
            print(f"- {finding}")


if __name__ == "__main__":
    main()
