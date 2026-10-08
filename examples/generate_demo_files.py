"""Generate synthetic CSV, multi-sheet Excel and SQLite without overwriting files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from insightpilot.data.scenarios import generate_demo_scenario


def _spreadsheet_safe(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.select_dtypes(include=["object", "str", "string"]).columns:
        result[column] = result[column].map(lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
    return result


def generate_demo_files(output_dir: str | Path, scenario: str = "transaction", scale: str = "small", seed: int = 42,
                        formats: tuple[str, ...] = ("csv", "excel", "sqlite")) -> list[Path]:
    """Write only to the explicitly supplied output directory with exclusive creation."""
    if not formats or set(formats) - {"csv", "excel", "sqlite"}:
        raise ValueError("格式须为 csv、excel 或 sqlite。")
    destination = Path(output_dir).expanduser().resolve()
    scenarios = ["transaction", "content", "live", "multi_table_commerce"] if scenario == "all" else [scenario]
    written: list[Path] = []
    # Preflight before generating data or writing any requested scenario.
    for name in scenarios:
        if any(destination.glob(f"{name}_*")):
            raise FileExistsError(f"目录中已有 {name} 输出；请选择新输出目录，避免覆盖。")
    destination.mkdir(parents=True, exist_ok=True)
    for name in scenarios:
        dataset = generate_demo_scenario(name, scale=scale, seed=seed)
        if "excel" in formats and any(len(frame) >= 1_048_576 for frame in dataset.tables.values()):
            raise ValueError("超过Excel单工作表行数上限；请改用CSV/SQLite或较小规模。")
        if "csv" in formats:
            for table, frame in dataset.tables.items():
                path = destination / f"{name}_{table}.csv"
                with path.open("x", encoding="utf-8-sig", newline="") as handle:
                    _spreadsheet_safe(frame).to_csv(handle, index=False)
                written.append(path)
        if "excel" in formats:
            path = destination / f"{name}_demo.xlsx"
            with path.open("xb") as handle, pd.ExcelWriter(handle, engine="openpyxl") as writer:
                for table, frame in dataset.tables.items():
                    if len(frame) >= 1_048_576:
                        raise ValueError(f"{table} 超过Excel单工作表行数上限；请改用 CSV/SQLite 或较小规模。")
                    _spreadsheet_safe(frame).to_excel(writer, sheet_name=table[:31], index=False)
            written.append(path)
        if "sqlite" in formats:
            path = destination / f"{name}_demo.sqlite"
            with path.open("xb"):
                pass
            with sqlite3.connect(path) as connection:
                for table, frame in dataset.tables.items():
                    frame.to_sql(table, connection, index=False, if_exists="fail")
            written.append(path)
        path = destination / f"{name}_metadata.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(dataset.metadata, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在指定目录生成本地模拟数据；已有同名输出拒绝覆盖。")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scenario", choices=["transaction", "content", "live", "multi_table_commerce", "all"], default="transaction")
    parser.add_argument("--scale", choices=["small", "standard", "large"], default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--formats", nargs="+", choices=["csv", "excel", "sqlite"], default=["csv", "excel", "sqlite"])
    args = parser.parse_args(argv)
    try:
        paths = generate_demo_files(args.output_dir, args.scenario, args.scale, args.seed, tuple(args.formats))
    except (OSError, ValueError) as exc:
        print(f"模拟文件生成失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"files": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
