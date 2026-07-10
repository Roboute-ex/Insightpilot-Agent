# Demo 演示脚本

本演示只使用 synthetic data 或当前会话内存中的用户提供表。不要提交真实数据、上传文件、数据库查询结果或凭据。

## Demo 1：Synthetic 交易转化异常分析

数据来源：Synthetic demo data

命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis
```

预期输出：

- route_taken 包含 `load_data_source`、`validate_tables`、`infer_schema`、`route_metric_diagnosis`、`run_anomaly`、`run_attribution`。
- Reviewer Score 为 PASS 区间。
- Markdown Report 包含数据来源、表结构摘要和限制说明。

注意事项：

- synthetic data 中目标日期的 South City 被注入订单下降信号。
- 归因排序用于定位优先排查方向，不代表最终因果结论。

## Demo 2：Upload CSV

数据来源：Upload CSV / Excel

操作步骤：

1. 准备一个 tiny synthetic CSV，例如包含 `date,value,city` 三列。
2. 在 Streamlit 侧边栏选择 `Upload CSV / Excel`。
3. 上传 CSV。
4. 修改 table name。
5. 查看 preview、schema mapping 和 warnings。
6. 在 Metric / Column Mapping 面板选择 date、metric 和 dimension。
7. 选择 `growth_trend`。
8. 运行分析。

CLI 示例：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.csv --table-name uploaded_table --goal-mode growth_trend
```

带字段映射：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.csv --table-name uploaded_table --goal-mode growth_trend --date-column date --metric-columns value --dimension-columns city
```

预期输出：

- data_source 为 `uploaded_files`。
- route_taken 包含 `generic_analysis_fallback`。
- 如果识别到日期列和数值列，会输出通用趋势或异常摘要。

注意事项：

- 上传文件默认只在当前会话内存中处理。
- 不要把上传文件提交到仓库。

## Demo 3：Upload Excel

数据来源：Upload CSV / Excel

操作步骤：

1. 准备一个 tiny synthetic Excel 文件。
2. 在 Streamlit 上传 Excel。
3. 选择 sheet。
4. 修改 table name。
5. 查看 schema mapping。
6. 在 Metric / Column Mapping 面板确认 date column 和 metric columns。
7. 运行分析。

CLI 示例：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.xlsx --sheet-name Sheet1 --table-name uploaded_table --goal-mode growth_trend
```

预期输出：

- Excel sheet 被读取为一张 pandas DataFrame。
- 报告包含表结构摘要和 schema warnings。

注意事项：

- Excel 读取依赖 openpyxl。
- 如果 sheet 为空，会显示友好错误或 warning。

## Demo 4：SQLite Query

数据来源：Database query

操作步骤：

1. 准备一个 tiny synthetic SQLite 文件或使用测试生成数据。
2. 在 Streamlit 选择 `Database query`。
3. 输入 `sqlite:///path/to/local.db`。
4. 输入只读 SQL，例如 `SELECT * FROM metrics`。
5. 点击 `Test Query / Load Data`。
6. 查看 preview、schema mapping 和 warnings。
7. 在 Metric / Column Mapping 面板选择字段。
8. 运行分析。

CLI 示例：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source database --database-url sqlite:///local.db --query "SELECT * FROM metrics" --table-name db_table --goal-mode growth_trend
```

预期输出：

- data_source 为 `database`。
- unsafe SQL 会被拒绝，不执行。
- report 不展示明文密码。

注意事项：

- database query 只允许单条 SELECT/WITH。
- 不要提交真实数据库凭据或本地数据库文件。

## Demo 5：Synthetic 内容与体验质量

命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario content --goal-mode experiment_analysis
.\.venv\Scripts\python.exe examples/run_demo.py --scenario live --goal-mode live_quality
```

预期输出：

- content 场景包含 p_value、sample_size 和 reviewer 实验检查。
- live 场景包含体验质量指标和维度归因。
- 两个场景继续使用 synthetic data，不受 v0.3 ingestion 影响。

## Demo 6：Analysis Playbook 与 Visual Diagnostics

命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --playbook metric_trend --time-grain week --rolling-window 4
```

预期输出：

- selected playbook 为 `metric_trend`。
- route 包含 mapping validation、安全查询、playbook execution、chart generation 和 manifest。
- Streamlit 的 Visual Diagnostics tab 展示趋势与滚动均值。
- Reviewer 检查 playbook requirements、参数、查询安全和 manifest。

## Demo 7：Export Bundle

命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --playbook periodic_summary --export-format markdown,html,excel,manifest,bundle
```

预期输出：

- CLI 输出 playbook、run_id、backend、reviewer score 和导出路径。
- ZIP 包含 report、Excel、manifest 和有限行数的分析结果 CSV。
- bundle 不包含 synthetic 源表文件、上传文件或数据库连接信息。
- 已存在文件不会被静默覆盖，会追加短 run ID。

## Streamlit v0.5 流程

1. 选择数据来源并预览表。
2. 对 custom data 配置 Column Mapping。
3. 选择 goal mode 与 playbook。
4. 在 form 中配置 playbook 参数并运行。
5. 查看 Summary、Result Tables、Visual Diagnostics、Reviewer、Trace。
6. 在 Export tab 准备内存导出并下载所需格式。
