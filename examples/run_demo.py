"""Run built-in synthetic demo scenarios from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data
from insightpilot.ingestion.db_loader import mask_database_url, run_database_query
from insightpilot.ingestion.file_loader import load_uploaded_file
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.planning.goal_modes import GOAL_MODE_DISPLAY_NAMES
from insightpilot.reports.export import write_text_report


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
    return parser.parse_args()


def _sheet_name(value: str | None) -> str | int | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


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
    report_dir = PROJECT_ROOT / "reports"
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
        scenario_question = args.question or question or SCENARIO_QUESTIONS[scenario]
        result = run_agent_analysis(
            scenario_question,
            tables,
            goal_mode=args.goal_mode,
            use_langgraph=args.use_langgraph,
            data_source_type=data_source_type,
            table_metadata=table_metadata,
        )
        report_path = write_text_report(report_dir / f"{scenario}_report.md", result["report_markdown"])
        reviewer = result["reviewer"]
        print(
            f"scenario={scenario} data_source={result['data_source_type']} intent={result['intent']} goal_mode={result['goal_mode']} "
            f"goal_mode_source={result['goal_mode_source']} workflow_backend={result['workflow_backend']} "
            f"reviewer_status={reviewer['status']} reviewer_score={reviewer['score']}"
        )
        print(f"report: {report_path}")
        print(f"route_taken: {', '.join(result['route_taken'])}")
        for finding in result["findings"][:3]:
            print(f"- {finding}")


if __name__ == "__main__":
    main()
