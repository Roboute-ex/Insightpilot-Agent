"""Data ingestion helpers for uploaded files and local database queries."""

from insightpilot.ingestion.db_loader import (
    DatabaseQueryResult,
    is_safe_select_query,
    mask_database_url,
    normalize_database_url,
    run_database_query,
)
from insightpilot.ingestion.file_loader import (
    LoadedTable,
    get_excel_sheet_names,
    load_uploaded_file,
    read_csv_file,
    read_excel_file,
    sanitize_table_name,
)
from insightpilot.ingestion.mapping import (
    ColumnMapping,
    normalize_column_mapping,
    suggest_column_mapping,
    validate_column_mapping,
)
from insightpilot.ingestion.schema_mapper import SchemaMappingSuggestion, infer_schema_mapping
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.ingestion.validation import validate_dataframe_for_analysis, validate_tables_for_workflow

__all__ = [
    "DatabaseQueryResult",
    "LoadedTable",
    "ColumnMapping",
    "SchemaMappingSuggestion",
    "TableRegistry",
    "get_excel_sheet_names",
    "infer_schema_mapping",
    "is_safe_select_query",
    "load_uploaded_file",
    "mask_database_url",
    "normalize_database_url",
    "normalize_column_mapping",
    "read_csv_file",
    "read_excel_file",
    "run_database_query",
    "sanitize_table_name",
    "suggest_column_mapping",
    "validate_column_mapping",
    "validate_dataframe_for_analysis",
    "validate_tables_for_workflow",
]
