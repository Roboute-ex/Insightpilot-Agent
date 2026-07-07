"""In-memory table registry for synthetic, uploaded, and database tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from insightpilot.ingestion.file_loader import sanitize_table_name
from insightpilot.ingestion.schema_mapper import infer_schema_mapping
from insightpilot.ingestion.validation import validate_dataframe_for_analysis


@dataclass
class TableRegistry:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _unique_name(self, name: str) -> str:
        base = sanitize_table_name(name)
        candidate = base
        index = 2
        while candidate in self.tables:
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def add_table(self, name: str, df: pd.DataFrame, source_type: str, source_name: str) -> str:
        table_name = self._unique_name(name)
        schema_mapping = infer_schema_mapping(table_name, df)
        warnings = validate_dataframe_for_analysis(df)
        for warning in schema_mapping.warnings:
            if warning not in warnings:
                warnings.append(warning)
        self.tables[table_name] = df
        self.metadata[table_name] = {
            "source_type": source_type,
            "source_name": source_name,
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": [str(column) for column in df.columns],
            "schema_mapping": schema_mapping.to_dict(),
            "warnings": warnings,
        }
        return table_name

    def remove_table(self, name: str) -> None:
        self.tables.pop(name, None)
        self.metadata.pop(name, None)

    def list_tables(self) -> list[str]:
        return sorted(self.tables.keys())

    def get_table(self, name: str) -> pd.DataFrame:
        try:
            return self.tables[name]
        except KeyError as exc:
            raise KeyError(f"Table is not registered: {name}") from exc

    def get_metadata(self, name: str) -> dict[str, Any]:
        try:
            return self.metadata[name]
        except KeyError as exc:
            raise KeyError(f"Table metadata is not registered: {name}") from exc

    def to_duckdb_tables(self) -> dict[str, pd.DataFrame]:
        return dict(self.tables)

    def profile_all(self) -> dict[str, dict[str, Any]]:
        return {name: dict(metadata) for name, metadata in self.metadata.items()}
