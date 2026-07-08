# Metric / Column Mapping

v0.4 增加 Metric / Column Mapping，用于让用户在自定义数据中手动指定关键字段。它解决的问题是：上传文件或数据库查询结果往往没有固定字段名，单靠 dtype 和列名推断不够稳定。

## 自动推断 vs 手动选择

自动推断来自 `infer_schema_mapping()`，会根据字段名、dtype 和 unique count 找出日期列、数值列和维度列。手动选择来自 Streamlit UI 或 CLI 参数。手动选择优先于自动推断。

如果手动 mapping 不完整，workflow 不会崩溃，而是进入 generic analysis fallback，并在 mapping_warnings 和 caveats 中说明缺少哪些字段。

## 字段说明

- `date_column`：趋势、异常检测和周期汇总使用的日期字段。
- `metric_columns`：一个或多个数值指标字段。
- `dimension_columns`：用于拆解、分组或控制变量候选的维度字段。
- `group_column`：实验分析的分组字段，最好包含 control/treatment。
- `treatment_column`：轻量因果探索的处理变量字段。
- `outcome_column`：轻量因果探索的结果变量字段。
- `time_grain`：趋势聚合粒度，可选 day、week、month。

## Streamlit 使用方式

1. 选择 Upload CSV / Excel 或 Database query。
2. 加载表后，在 Metric / Column Mapping 面板中选择表。
3. 查看自动建议 mapping。
4. 手动选择 date、metric、dimension、group、treatment、outcome。
5. 选择 time_grain。
6. 点击运行分析。
7. 在 Data Source、Trace JSON 和 Markdown Report 中查看最终 mapping。

## CLI 使用方式

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.csv --table-name uploaded_table --goal-mode growth_trend --date-column date --metric-columns revenue,orders --dimension-columns city,channel
```

实验分析示例：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/experiment.csv --table-name experiment_table --goal-mode experiment_analysis --group-column group --metric-columns completion_rate
```

轻量因果探索示例：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.csv --table-name causal_table --goal-mode causal_exploration --treatment-column treatment --outcome-column outcome --dimension-columns city,segment
```

这些路径仅是示例占位。不要把真实数据文件提交到仓库。

## 常见问题

如果没有日期列，growth_trend 会退化为指标摘要。

如果没有 metric_columns，custom data workflow 会输出 schema profile 和改进建议。

如果 experiment_analysis 没有 group_column，系统会说明无法执行实验比较。

如果 causal_exploration 没有 treatment/outcome，系统会说明只输出 caveat，不执行轻量因果估计。
