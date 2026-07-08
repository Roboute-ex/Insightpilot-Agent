# Data Ingestion

v0.3 支持三类数据来源：

- Synthetic demo data
- CSV / Excel upload
- Database query ingestion

所有外部数据默认只在当前会话内存中处理，不写入仓库。

## CSV / Excel Upload

支持格式：

- `.csv`
- `.xlsx`
- `.xlsm`
- `.xls`

读取逻辑：

- CSV 依次尝试 `utf-8-sig`、`utf-8`、`gbk`。
- Excel 使用 pandas Excel reader，xlsx/xlsm 默认依赖 openpyxl。
- Excel 支持选择 sheet。
- 每个文件读取为一张 pandas DataFrame。
- table name 会通过 `sanitize_table_name()` 转为 SQL-safe 名称。

## Schema Mapping

`infer_schema_mapping()` 会输出：

- detected_date_columns
- detected_numeric_columns
- detected_categorical_columns
- possible_metric_columns
- possible_dimension_columns
- warnings

规则是启发式的，主要基于字段名、dtype、unique count 和 id-like 字段排除。

## Metric / Column Mapping

v0.4 在 schema mapping 之后增加 ColumnMapping。用户可以在 Streamlit 或 CLI 中手动选择：

- date_column
- metric_columns
- dimension_columns
- group_column
- treatment_column
- outcome_column
- time_grain

手动 mapping 优先于自动推断。mapping 会写入 trace、reviewer 和 report。若 mapping 不完整，workflow 会保留 warnings 并进入 generic fallback。

## Validation

`validate_dataframe_for_analysis()` 会检查：

- 空表
- 行数过少
- 列数过少
- 缺少数值列
- 缺少日期列
- 高缺失率
- 重复列名
- 全空列
- 高基数字段

Warnings 不会默认阻断 workflow，除非没有任何可用表。

## TableRegistry

`TableRegistry` 统一管理：

- tables
- metadata
- source_type
- source_name
- row_count
- column_count
- columns
- schema_mapping
- warnings

metadata 不包含完整 DataFrame，避免 trace/report 误序列化数据。

## Generic Analysis Fallback

自定义数据缺少 demo 表结构时，workflow 会进入 `generic_analysis_fallback`：

- metric_diagnosis / growth_trend：尝试用日期列 + 数值列做趋势或异常检测。
- experiment_analysis：需要 control/treatment 分组和数值 outcome，否则输出说明。
- causal_exploration：需要 treatment/outcome 和控制变量，否则只输出 caveat。
- live_quality / content_performance：缺少相关字段时退化为 schema profile。

如果用户提供 ColumnMapping，fallback 会优先使用用户选择的字段，而不是完全依赖字段名和 dtype。

## Safety Limitations

- 不保存上传文件。
- 不保存数据库查询结果。
- 不把自定义数据结果描述为真实业务结论。
- 复杂业务口径需要后续手动 metric mapping UI 支持。
